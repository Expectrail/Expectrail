extends Node
## Expectrail harness. The runner adds this script to a copy of the game as an autoload; the game
## itself is never edited. It presses input actions on exact physics ticks, as a route file says,
## and records where the player is after every tick, then quits.
##
## User arguments (after `--`): --route=<path> --trace=<path> [--seed=<int>] [--player=<node name>]
##
## Each trace row also carries, when the level has tile layers:
##   ground: world y of the solid tile surface under the player (see _ground_under), from the
##           level's tile geometry, never from the player's own collision shape;
##   view:   the transform from world coordinates to captured-frame pixels, [xx, xy, yx, yy, ox, oy],
##           so a world point (x, y) lands at (xx*x + yx*y + ox, xy*x + yy*y + oy) in the frame.
##           It is read in the physics tick, so it is the camera of the frame drawn before it.
## and, when the level has collectibles of the coin class (--coins=<class_name>, default Coin):
##   coins:  world [x, y] of every such node still in the tree, so a vision model's coin boxes can
##           be checked against where the engine put the coins.
## and, for the engine-record checks (agents/trace_checks.py) and discovery (expectrail/trace/),
## the last two written every tick, empty or not (the header's capabilities say what is collected):
##   facing:      1 or -1, which way the player's sprite (--sprite=<child name>, default Sprite2D)
##                points on screen: the sign of its world x axis. A sprite flipped by a negative
##                scale anywhere above it (the sprite or the body) reads -1.
##   enemies:     [id, x, y] of every node of the enemy class (--enemies=<class_name>, default
##                Enemy) still in the tree; ids are small integers in the order the nodes were seen.
##   projectiles: [id, x, y] of every node of the projectile class (--projectiles=<class_name>,
##                default Bullet) in the tree, so the tick each one first appears is when it was fired.
## and the trace header carries levelSurfaces: every solid tile collision polygon in world
## coordinates, so the verifier can measure a candidate against the clean game's ground instead of
## the ground the candidate itself shipped; and levelArt: where the tile layers are drawn, so the
## verifier can see a floor drawn somewhere its collision is not (see _render_level_art).

const TRACE_FORMAT := "expectrail.trace/v0"
const ROUTE_FORMATS := ["expectrail.route/v0"]

var _events: Dictionary = {}   # tick -> Array of {action, pressed}
var _ticks: int = 0
var _tick: int = 0
var _trace: Array = []
var _trace_path: String = ""
var _player_name: String = "Player"
var _player: Node2D = null
var _recorder: Node = null
var _layers: Array = []          # every TileMapLayer in the level, found on the first record
var _layers_searched := false
var _coin_class: StringName = &"Coin"
var _coins: Array = []           # every coin node, found on the first record
var _coins_searched := false
var _sprite_name: String = "Sprite2D"
var _sprite: Node2D = null
var _enemy_class: StringName = &"Enemy"
var _enemies: Array = []         # [id, node] of every enemy, found on the first record
var _enemies_searched := false
var _projectile_class: StringName = &"Bullet"
var _projectiles: Array = []     # [id, node] of every projectile seen entering the tree
var _next_id := 0

# How far above the player's origin a surface may sit and still count as the ground under it:
# a robot sunk into the ground by less than this is measured against the surface it sank into.
# Platforms over the robot's head are at least about 95 px above its origin, so they never count.
const SINK_WINDOW := 64.0
# Half the player's width, to look for the highest surface under the whole body, not just its
# centre (the body rests on the highest point beneath it, e.g. on a slope or a ledge).
const BODY_HALF_WIDTH := 20.0
const SEARCH_ROWS := 16
# The tile-art render (_render_level_art): a visibility layer no game node uses, and the largest
# render it makes (world pixels a side); a bigger level is rendered in tiles of this size.
const ART_LAYER_BIT := 1 << 19
const ART_TILE := 2048
const ART_ALPHA := 128  # a pixel at least half opaque is drawn

var _art: Dictionary = {}        # levelArt for the trace header, once rendered
var _art_started := false


func _ready() -> void:
	# Run before every game node in the physics step, so a press is seen on the tick it is scheduled.
	process_physics_priority = -1000
	var args := _parse_args(OS.get_cmdline_user_args())
	if not args.has("route"):
		return  # Not a harness run: behave as if absent.
	seed(int(args.get("seed", "1")))
	_trace_path = args.get("trace", "")
	_player_name = args.get("player", "Player")
	_coin_class = StringName(args.get("coins", "Coin"))
	_sprite_name = args.get("sprite", "Sprite2D")
	_enemy_class = StringName(args.get("enemies", "Enemy"))
	_projectile_class = StringName(args.get("projectiles", "Bullet"))
	get_tree().node_added.connect(_on_node_added)
	var route = JSON.parse_string(FileAccess.get_file_as_string(args["route"]))
	if typeof(route) != TYPE_DICTIONARY or not (route.get("format", "") in ROUTE_FORMATS):
		push_error("expectrail: not an expectrail.route/v0 file: %s" % args["route"])
		get_tree().quit(2)
		return
	_ticks = int(route["ticks"])
	for event in route.get("events", []):
		var tick := int(event["tick"])
		if not _events.has(tick):
			_events[tick] = []
		_events[tick].append({"action": String(event["action"]), "pressed": bool(event["pressed"])})
	# A second node records positions after every game node has moved in the same tick.
	_recorder = Node.new()
	_recorder.name = "ExpectrailRecorder"
	_recorder.process_physics_priority = 1000
	_recorder.set_physics_process(true)
	_recorder.set_script(_RecorderScript)
	_recorder.set_meta("harness", self)
	add_child(_recorder)


func _physics_process(_delta: float) -> void:
	if _ticks == 0:
		return
	for event in _events.get(_tick, []):
		if event["pressed"]:
			Input.action_press(event["action"])
		else:
			Input.action_release(event["action"])


func record() -> void:
	if _player == null:
		var scene := get_tree().current_scene
		if scene != null:
			_player = scene.find_child(_player_name, true, false) as Node2D
	var row := {"tick": _tick, "frame": Engine.get_frames_drawn()}
	if _player != null:
		row["player"] = [snappedf(_player.global_position.x, 0.001), snappedf(_player.global_position.y, 0.001)]
		var body := _player as CharacterBody2D
		if body != null:
			row["onFloor"] = body.is_on_floor()
		var ground = _ground_under(_player.global_position)
		if ground != null:
			row["ground"] = snappedf(ground, 0.001)
		if _sprite == null:
			_sprite = _player.find_child(_sprite_name, true, false) as Node2D
		if _sprite != null:
			row["facing"] = -1 if _sprite.global_transform.x.x < 0.0 else 1
	if not _art_started and _layers_searched and not _layers.is_empty():
		_art_started = true
		_render_level_art()  # a coroutine: finishes a frame or two later, long before the route ends
	var coins := _coin_positions()
	if not coins.is_empty():
		row["coins"] = coins
	# Written every tick, empty or not, so an empty list means none were there (the header's
	# capabilities say so): a reader can tell "no bullets" from "not recorded".
	row["enemies"] = _enemy_positions()
	row["projectiles"] = _tracked_positions(_projectiles)
	var view := get_viewport().get_final_transform() * get_viewport().get_canvas_transform()
	row["view"] = [snappedf(view.x.x, 0.0001), snappedf(view.x.y, 0.0001), snappedf(view.y.x, 0.0001),
		snappedf(view.y.y, 0.0001), snappedf(view.origin.x, 0.001), snappedf(view.origin.y, 0.001)]
	_trace.append(row)
	_tick += 1
	if _tick >= _ticks:
		_finish()


func _finish() -> void:
	if _trace_path != "":
		var out := {"format": TRACE_FORMAT, "ticks": _ticks,
			"physicsTicksPerSecond": Engine.physics_ticks_per_second, "rows": _trace,
			# What this recorder collects, for expectrail/trace/normalize.py: enemies are the instances
			# in the scene when it is first searched (later spawns are not tracked); bullets are every
			# node of the projectile class added to the tree.
			"capabilities": {"enemies": "initial-instances", "projectiles": "complete",
				"facing": _sprite != null, "onFloor": _player is CharacterBody2D}}
		var surfaces := _level_surfaces()
		if not surfaces.is_empty():
			out["levelSurfaces"] = surfaces
		if not _art.is_empty():
			out["levelArt"] = _art
		var file := FileAccess.open(_trace_path, FileAccess.WRITE)
		file.store_string(JSON.stringify(out, "", false))
		file.close()
	get_tree().quit(0)


func _coin_positions() -> Array:
	"""World [x, y] of every node of the coin class still in the tree (picked coins free themselves)."""
	if not _coins_searched:
		var scene := get_tree().current_scene
		if scene == null:
			return []
		_coins_searched = true
		for node in scene.find_children("*", "Node2D", true, false):
			var script = node.get_script()
			if script != null and script.get_global_name() == _coin_class:
				_coins.append(node)
	var out := []
	for coin in _coins:
		if is_instance_valid(coin) and coin.is_inside_tree():
			var p: Vector2 = coin.global_position
			out.append([snappedf(p.x, 0.01), snappedf(p.y, 0.01)])
	return out


func _is_class(node: Node, cls: StringName) -> bool:
	var script = node.get_script()
	return script != null and script.get_global_name() == cls


func _on_node_added(node: Node) -> void:
	if node is Node2D and _is_class(node, _projectile_class):
		_projectiles.append([_next_id, node])
		_next_id += 1


func _enemy_positions() -> Array:
	if not _enemies_searched:
		var scene := get_tree().current_scene
		if scene == null:
			return []
		_enemies_searched = true
		for node in scene.find_children("*", "Node2D", true, false):
			if _is_class(node, _enemy_class):
				_enemies.append([_next_id, node])
				_next_id += 1
	return _tracked_positions(_enemies)


func _tracked_positions(tracked: Array) -> Array:
	"""[id, x, y] of every tracked node still in the tree (freed nodes drop out)."""
	var out := []
	for entry in tracked:
		var node = entry[1]
		if is_instance_valid(node) and node.is_inside_tree():
			var p: Vector2 = node.global_position
			out.append([entry[0], snappedf(p.x, 0.01), snappedf(p.y, 0.01)])
	return out


func _ground_under(origin: Vector2) -> Variant:
	"""World y of the highest solid tile surface under the player's body, or null.

	Only surfaces at or below origin.y - SINK_WINDOW count. Read from each tile's authored
	collision polygons, so it stays put when a bug switches collision off or changes the player.
	"""
	if not _layers_searched:
		_layers_searched = true
		var scene := get_tree().current_scene
		if scene != null:
			_layers = scene.find_children("*", "TileMapLayer", true, false)
	var best = null
	for dx in [-BODY_HALF_WIDTH, 0.0, BODY_HALF_WIDTH]:
		for layer in _layers:
			var surface = _surface_in_column(layer, origin.x + dx, origin.y - SINK_WINDOW)
			if surface != null and (best == null or surface < best):
				best = surface
	return best


func _level_surfaces() -> Array:
	"""Every solid tile collision polygon of the level, in world coordinates."""
	var polygons := []
	for node in _layers:
		var layer := node as TileMapLayer
		if layer == null or layer.tile_set == null:
			continue
		for cell in layer.get_used_cells():
			var data: TileData = layer.get_cell_tile_data(cell)
			if data == null:
				continue
			var centre: Vector2 = layer.map_to_local(cell)
			for physics_layer in layer.tile_set.get_physics_layers_count():
				for i in data.get_collision_polygons_count(physics_layer):
					var points := []
					for point in data.get_collision_polygon_points(physics_layer, i):
						var world: Vector2 = layer.to_global(centre + point)
						points.append([snappedf(world.x, 0.01), snappedf(world.y, 0.01)])
					polygons.append(points)
	return polygons


func _render_level_art() -> void:
	"""Render the tile layers alone, as the game draws them, and keep where they are opaque.

	A second viewport shares the game's 2D world but only draws canvas items on ART_LAYER_BIT,
	which only the tile layers (and the nodes above them) are given, so it draws exactly what the
	game draws for them: their tiles, materials, shaders, offsets and modulation, nothing else. The
	main viewport draws every layer, so the captured frames do not change. Per world column it
	keeps the opaque runs, [[top, bottom], ...] in world y: levelArt = {x0, y0, width, height,
	columns}. Read once: the tile layers do not move during a route.
	"""
	var bounds := Rect2()
	var have := false
	for node in _layers:
		var layer := node as TileMapLayer
		if layer == null or layer.tile_set == null:
			continue
		var used := layer.get_used_rect()
		if used.size == Vector2i.ZERO:
			continue
		var cell := Vector2(layer.tile_set.tile_size)
		# One cell of margin all round: tile art may be drawn outside its cell.
		var a := layer.to_global(layer.map_to_local(used.position) - cell * 1.5)
		var b := layer.to_global(layer.map_to_local(used.end) + cell * 0.5)
		var r := Rect2(a, Vector2.ZERO).expand(b)
		bounds = r if not have else bounds.merge(r)
		have = true
		var item: Node = layer
		while item is CanvasItem:
			(item as CanvasItem).visibility_layer |= ART_LAYER_BIT
			item = item.get_parent()
	if not have:
		return
	var x0 := int(floor(bounds.position.x))
	var y0 := int(floor(bounds.position.y))
	var width := int(ceil(bounds.end.x)) - x0
	var height := int(ceil(bounds.end.y)) - y0
	var columns := []
	columns.resize(width)
	for i in width:
		columns[i] = []
	var vp := SubViewport.new()
	vp.world_2d = get_viewport().world_2d
	vp.canvas_cull_mask = ART_LAYER_BIT
	vp.transparent_bg = true
	vp.disable_3d = true
	vp.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	add_child(vp)
	for ty in range(0, height, ART_TILE):
		for tx in range(0, width, ART_TILE):
			var w := mini(ART_TILE, width - tx)
			var h := mini(ART_TILE, height - ty)
			vp.size = Vector2i(w, h)
			vp.canvas_transform = Transform2D(0.0, Vector2(-(x0 + tx), -(y0 + ty)))
			await RenderingServer.frame_post_draw
			await RenderingServer.frame_post_draw
			var img := vp.get_texture().get_image()
			img.convert(Image.FORMAT_RGBA8)
			var data := img.get_data()
			for x in w:
				var runs: Array = columns[tx + x]
				var top := -1
				for y in h:
					var opaque := data[(y * w + x) * 4 + 3] >= ART_ALPHA
					if opaque and top < 0:
						top = y
					elif not opaque and top >= 0:
						_add_run(runs, y0 + ty + top, y0 + ty + y)
						top = -1
				if top >= 0:
					_add_run(runs, y0 + ty + top, y0 + ty + h)
	vp.queue_free()
	_art = {"x0": x0, "y0": y0, "width": width, "height": height, "columns": columns}


static func _add_run(runs: Array, top: int, bottom: int) -> void:
	# A run that continues one from the tile above it is the same run.
	if not runs.is_empty() and runs[-1][1] == top:
		runs[-1][1] = bottom
	else:
		runs.append([top, bottom])


func _surface_in_column(layer: TileMapLayer, world_x: float, min_y: float) -> Variant:
	if layer.tile_set == null:
		return null
	var start := layer.local_to_map(layer.to_local(Vector2(world_x, min_y)))
	var physics_layers := layer.tile_set.get_physics_layers_count()
	for row in range(start.y, start.y + SEARCH_ROWS):
		var cell := Vector2i(start.x, row)
		var data := layer.get_cell_tile_data(cell)
		if data == null:
			continue
		var centre := layer.map_to_local(cell)
		var local_x := layer.to_local(Vector2(world_x, 0.0)).x - centre.x
		var top = null
		for physics_layer in physics_layers:
			for i in data.get_collision_polygons_count(physics_layer):
				var y = _polygon_top(data.get_collision_polygon_points(physics_layer, i), local_x)
				if y != null and (top == null or y < top):
					top = y
		if top == null:
			continue
		var surface := layer.to_global(centre + Vector2(0.0, top)).y
		if surface >= min_y:
			return surface
	return null


static func _polygon_top(points: PackedVector2Array, x: float) -> Variant:
	var top = null
	var n := points.size()
	for i in n:
		var a := points[i]
		var b := points[(i + 1) % n]
		if x < minf(a.x, b.x) or x > maxf(a.x, b.x):
			continue
		var y := minf(a.y, b.y) if is_equal_approx(a.x, b.x) else a.y + (b.y - a.y) * (x - a.x) / (b.x - a.x)
		if top == null or y < top:
			top = y
	return top


static func _parse_args(args: PackedStringArray) -> Dictionary:
	var out := {}
	for arg in args:
		if arg.begins_with("--") and arg.contains("="):
			var key := arg.substr(2, arg.find("=") - 2)
			out[key] = arg.substr(arg.find("=") + 1)
	return out


const _RecorderScript := preload("res://expectrail_recorder.gd")
