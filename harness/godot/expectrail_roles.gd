extends RefCounted
## Configured Godot roles only. No node names, textures or sizes from the bundled game.
## A box is an AABB of authored geometry, not a claim about opaque pixels or occlusion.

var bindings: Dictionary
var seen: Dictionary = {}
var identities: Dictionary = {}
var generations: Dictionary = {}
var objects: Array = []
var points: Array = []
var previous_objects: Array = []
var previous_points: Array = []
var player: Node2D
var error := ""


func _init(value: Dictionary) -> void:
	bindings = value


func collect(tree: SceneTree) -> void:
	objects = []
	points = []
	player = null
	var roles := bindings.keys()
	roles.sort()
	var roots: Dictionary = {}
	var selected: Dictionary = {}
	for role in roles:
		var binding: Dictionary = bindings[role]
		var nodes: Array = []
		var locator: String = str(binding.get("node", binding.get("group", "")))
		if binding.has("group"):
			nodes = tree.get_nodes_in_group(locator)
		else:
			var scene := tree.current_scene
			if scene != null:
				if locator.begins_with("/") or locator.contains("/"):
					var found := scene.get_node_or_null(NodePath(locator))
					if found != null:
						nodes.append(found)
				else:
					if str(scene.name) == locator:
						nodes.append(scene)
					for candidate in scene.find_children("*", "", true, false):
						if str(candidate.name) == locator:
							nodes.append(candidate)
		if nodes.size() > 1 and (binding.has("node") or role == "player"):
			error = "expectrail: bindings.%s %s is ambiguous: %d matches; use a full node path or a unique player group" % [role, locator, nodes.size()]
			return
		nodes.sort_custom(func(a, b): return str(a.get_path()) < str(b.get_path()))
		for node in nodes:
			if not node is Node2D:
				error = "expectrail: bindings.%s %s is not a Node2D; bind a spatial node" % [role, locator]
				return
			if node.get_viewport() != tree.root or node.get_canvas() != tree.root.find_world_2d().canvas:
				error = "expectrail: bindings.%s %s uses another canvas or viewport; its world box cannot be measured" % [role, locator]
				return
			roots[node] = true
		selected[role] = nodes
	for role in roles:
		for node in selected[role]:
			var geometry := _geometry(node, roots)
			if geometry.points.is_empty():
				error = "expectrail: bindings.%s %s has no supported drawing or collision bounds to measure" % [role, node.get_path()]
				return
			seen[role] = true
			if role == "player":
				player = node
			var instance: int = node.get_instance_id()
			if not identities.has(instance):
				var path := str(tree.current_scene.get_path_to(node)).replace("#", "##")
				var generation: int = int(generations.get(path, 0)) + 1
				generations[path] = generation
				identities[instance] = path if generation == 1 else "%s#%d" % [path, generation]
			objects.append({"id": identities[instance], "role": role,
				"worldBox": _box(geometry.points, Transform2D.IDENTITY),
				"box": [], "visible": geometry.visible, "boundsSource": geometry.source})
			points.append(geometry.points)


func missing() -> String:
	var roles := bindings.keys()
	roles.sort()
	var absent := []
	for role in roles:
		if not seen.has(role):
			var binding: Dictionary = bindings[role]
			absent.append("bindings.%s %s" % [role, str(binding.get("node", binding.get("group", "")))])
	return "" if absent.is_empty() else "expectrail: %s not found on any tick; setup was not exercised" % ", ".join(absent)


func place(view: Transform2D) -> Array:
	# Camera2D updates after physics: tick t's image uses the view read at t+1.
	# Keep the actual world vertices, not just their AABB, when transforming rotated drawings.
	for i in previous_objects.size():
		previous_objects[i]["box"] = _box(previous_points[i], view)
	for i in objects.size():
		objects[i]["box"] = _box(points[i], view)  # last tick has no next view
	previous_objects = objects
	previous_points = points
	return objects


static func _corners(rect: Rect2) -> PackedVector2Array:
	return PackedVector2Array([rect.position, Vector2(rect.end.x, rect.position.y), rect.end, Vector2(rect.position.x, rect.end.y)])


static func _box(vertices: PackedVector2Array, transform: Transform2D) -> Array:
	var first := transform * vertices[0]
	var lo := first
	var hi := first
	for point in vertices:
		var p := transform * point
		lo = lo.min(p)
		hi = hi.max(p)
	return [snappedf(lo.x, 0.001), snappedf(lo.y, 0.001), snappedf(hi.x, 0.001), snappedf(hi.y, 0.001)]


static func _geometry(root: Node2D, roots: Dictionary) -> Dictionary:
	var drawing := PackedVector2Array()
	var visible_drawing := PackedVector2Array()
	var collision := PackedVector2Array()
	var visible := false
	var pending: Array = [root]
	while not pending.is_empty():
		var node: Node = pending.pop_back()
		if node != root and (roots.has(node) or node is PhysicsBody2D or node is Area2D):
			continue  # never borrow another object's art or collider
		if node is CanvasLayer or node is SubViewport:
			continue
		var local := PackedVector2Array()
		var shape := false
		if node is Sprite2D and node.texture != null:
			local = _corners(node.get_rect())
		elif node is AnimatedSprite2D and node.sprite_frames != null:
			var frames: SpriteFrames = node.sprite_frames
			if frames.has_animation(node.animation) and node.frame < frames.get_frame_count(node.animation):
				var texture := frames.get_frame_texture(node.animation, node.frame)
				if texture != null:
					var size: Vector2 = texture.get_size()
					var offset: Vector2 = node.offset - (size / 2.0 if node.centered else Vector2.ZERO)
					local = _corners(Rect2(offset, size))
					# Sprite flipping reverses UVs inside this rect; it does not move the rect.
		elif node is Polygon2D:
			for p in node.polygon:
				local.append(p + node.offset)
		elif node is CollisionShape2D and node.shape != null and not node.disabled:
			local = _corners(node.shape.get_rect())
			shape = true
		elif node is CollisionPolygon2D and not node.disabled:
			local = node.polygon
			shape = true
		if not local.is_empty():
			var spatial := node as Node2D
			for point in local:
				if shape:
					collision.append(spatial.global_transform * point)
				else:
					drawing.append(spatial.global_transform * point)
					if spatial.is_visible_in_tree():
						visible_drawing.append(spatial.global_transform * point)
			if not shape and spatial.is_visible_in_tree():
				visible = true
		for child in node.get_children():
			pending.append(child)
	if not drawing.is_empty():
		return {"points": visible_drawing if visible else drawing, "visible": visible, "source": "drawing"}
	return {"points": collision, "visible": root.is_visible_in_tree(), "source": "collision"}
