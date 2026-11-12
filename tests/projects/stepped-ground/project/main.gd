extends Node2D
## A level of 64 px tiles built in code, so the test owns every number:
##   the floor: tiles with their top at y = 320, from x = 0 to 640
##   a gap:     no tile from x = 192 to 256
##   a step:    one tile on the floor from x = 448 to 512, its top at y = 256
## The player is a marker 8 px above the floor. While `right` is held it moves 2 px a tick at the
## same height: across the gap, up to the step, and into it. It does not fall and does not climb,
## because what is tested is which surface the harness calls the ground under each position.

const TILE := 64
@onready var player: Node2D = $Player


func _ready() -> void:
	var image := Image.create(TILE, TILE, false, Image.FORMAT_RGBA8)
	image.fill(Color(0.35, 0.55, 0.3))
	var source := TileSetAtlasSource.new()
	source.texture = ImageTexture.create_from_image(image)
	source.texture_region_size = Vector2i(TILE, TILE)
	source.create_tile(Vector2i.ZERO)
	var tiles := TileSet.new()
	tiles.tile_size = Vector2i(TILE, TILE)
	tiles.add_physics_layer()
	var id := tiles.add_source(source)
	var data := source.get_tile_data(Vector2i.ZERO, 0)
	var half := TILE / 2.0
	data.add_collision_polygon(0)
	data.set_collision_polygon_points(0, 0, PackedVector2Array(
		[Vector2(-half, -half), Vector2(half, -half), Vector2(half, half), Vector2(-half, half)]))
	var layer := TileMapLayer.new()
	layer.name = "Level"
	layer.tile_set = tiles
	for x in range(10):
		if x != 3:
			layer.set_cell(Vector2i(x, 5), id, Vector2i.ZERO)
	layer.set_cell(Vector2i(7, 4), id, Vector2i.ZERO)
	add_child(layer)
	move_child(layer, 0)


func _physics_process(_delta: float) -> void:
	if Input.is_action_pressed(&"right"):
		player.position.x += 2.0
