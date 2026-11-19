extends Node
## Expectrail's runtime scan for `expectrail init --runtime` and `expectrail inspect --runtime`. The
## runner adds this script to a copy of the game as an autoload; the game itself is never edited. It
## presses nothing: it lets the game run a few physics ticks, then lists the nodes of the current
## scene as the engine has them at that moment, writes one JSON file and quits.
##
## User arguments (after `--`): --scan=<path> --ticks=<n>
##
## It lists only the kinds a project config can bind or a ground check can stand on: physics bodies
## and areas, sprites, polygons, tile layers and cameras. For each: its path from the current scene,
## its class, its script's class name, its groups (Godot's own groups, whose names start with "_",
## are left out), the engine's visible flag, and per kind:
##   sprite, animatedSprite, polygon: the res:// paths of the images it draws, and how many images
##            it draws that were made in code and have no file;
##   tileLayer: how many cells hold a tile, and whether its tile set has a physics layer;
##   camera:  whether it is enabled.
## What it writes is the game's own report of itself, read as untrusted data by expectrail.runtime_scan.

const FORMAT := "expectrail.runtime-scan-raw/v0"
const MAX_NODES := 2000
const MAX_GROUPS := 32

var _scan_path := ""
var _ticks := 0
var _tick := 0
var _done := false


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--scan="):
			_scan_path = arg.substr(7)
		elif arg.begins_with("--ticks="):
			_ticks = int(arg.substr(8))
	if _scan_path == "" or _ticks < 1:
		push_error("expectrail: the scan needs --scan=<path> and --ticks=<n> with n at least 1")
		get_tree().quit(3)


func _physics_process(_delta: float) -> void:
	if _done or _scan_path == "":
		return
	_tick += 1
	if _tick < _ticks:
		return
	_done = true
	var scene := get_tree().current_scene
	var doc := {"format": FORMAT, "ticks": _tick, "scene": "", "nodes": [], "truncated": false}
	if scene == null:
		doc["error"] = "no current scene"
	else:
		doc["scene"] = scene.scene_file_path
		var nodes: Array = []
		var truncated := _visit(scene, scene, nodes)
		doc["nodes"] = nodes
		doc["truncated"] = truncated
	var file := FileAccess.open(_scan_path, FileAccess.WRITE)
	if file == null:
		push_error("expectrail: cannot write the scan file")
		get_tree().quit(4)
		return
	file.store_string(JSON.stringify(doc))
	file.close()
	get_tree().quit(0)


func _visit(scene: Node, node: Node, out: Array) -> bool:
	var kind := _kind(node)
	if kind != "":
		if out.size() >= MAX_NODES:
			return true
		out.append(_describe(scene, node, kind))
	for child in node.get_children():
		if _visit(scene, child, out):
			return true
	return false


func _kind(node: Node) -> String:
	if node is CharacterBody2D or node is RigidBody2D:
		return "body"
	if node is StaticBody2D or node is AnimatableBody2D:
		return "platform"
	if node is Area2D:
		return "area"
	if node is AnimatedSprite2D:
		return "animatedSprite"
	if node is Sprite2D:
		return "sprite"
	if node is Polygon2D:
		return "polygon"
	if node is TileMapLayer:
		return "tileLayer"
	if node is Camera2D:
		return "camera"
	return ""


func _describe(scene: Node, node: Node, kind: String) -> Dictionary:
	var path := str(scene.get_path_to(node))
	var groups: Array = []
	for group in node.get_groups():
		var label := str(group)
		if not label.begins_with("_") and groups.size() < MAX_GROUPS:
			groups.append(label)
	groups.sort()
	var attached = node.get_script()
	var class_name_text := ""
	if attached != null and attached is Script:
		class_name_text = str(attached.get_global_name())
	var entry := {"path": path, "kind": kind, "type": node.get_class(), "className": class_name_text,
				  "groups": groups}
	if node is CanvasItem:
		entry["visible"] = node.is_visible_in_tree()
	if kind == "sprite" or kind == "animatedSprite" or kind == "polygon":
		var textures: Array = []
		if kind == "animatedSprite":
			var frames: SpriteFrames = node.sprite_frames
			if frames != null:
				for animation in frames.get_animation_names():
					for i in frames.get_frame_count(animation):
						textures.append(frames.get_frame_texture(animation, i))
		elif node.texture != null:
			textures.append(node.texture)
		var files: Array = []
		var unsaved := 0
		for texture in textures:
			if texture == null:
				continue
			var source := str(texture.resource_path)
			if source.begins_with("res://") and not source.contains("::"):
				if not files.has(source):
					files.append(source)
			else:
				unsaved += 1
		files.sort()
		entry["images"] = files
		entry["unsavedImages"] = unsaved
	elif kind == "tileLayer":
		var tiles: TileSet = node.tile_set
		entry["cells"] = node.get_used_cells().size()
		entry["collides"] = tiles != null and tiles.get_physics_layers_count() > 0
	elif kind == "camera":
		entry["enabled"] = node.enabled
	return entry
