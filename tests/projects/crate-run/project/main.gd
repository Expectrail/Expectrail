extends Node2D
## Crate Run's level. The floor is a TileMapLayer built here, so the project holds no image file.

const TILE := 32
const FLOOR_ROW := 8        # the floor's top edge is at y = FLOOR_ROW * TILE = 256
const FLOOR_FROM := -8
const FLOOR_TO := 64


func _ready() -> void:
	var image := Image.create(TILE, TILE, false, Image.FORMAT_RGBA8)
	image.fill(Color(0.25, 0.3, 0.38))
	var source := TileSetAtlasSource.new()
	source.texture = ImageTexture.create_from_image(image)
	source.texture_region_size = Vector2i(TILE, TILE)
	source.create_tile(Vector2i.ZERO)
	var tiles := TileSet.new()
	tiles.tile_size = Vector2i(TILE, TILE)
	tiles.add_physics_layer()
	tiles.add_source(source)
	var half := TILE / 2.0
	var data := source.get_tile_data(Vector2i.ZERO, 0)
	data.add_collision_polygon(0)
	data.set_collision_polygon_points(0, 0, PackedVector2Array([
		Vector2(-half, -half), Vector2(half, -half), Vector2(half, half), Vector2(-half, half)]))
	var ground := TileMapLayer.new()
	ground.name = "Floor"
	ground.tile_set = tiles
	for x in range(FLOOR_FROM, FLOOR_TO):
		ground.set_cell(Vector2i(x, FLOOR_ROW), 0, Vector2i.ZERO)
	add_child(ground)
