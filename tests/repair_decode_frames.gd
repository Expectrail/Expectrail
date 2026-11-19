# Decode the fixture's captured PNGs in one headless invocation, without loading a game.
extends SceneTree

func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	for name in DirAccess.get_files_at(args[0]):
		if not name.ends_with(".png"):
			continue
		var image := Image.new()
		if image.load(args[0].path_join(name)) != OK:
			quit(1)
			return
		image.convert(Image.FORMAT_RGB8)
		var file := FileAccess.open(args[1].path_join(name + ".rgb"), FileAccess.WRITE)
		if file == null:
			quit(1)
			return
		file.store_buffer(image.get_data().compress(FileAccess.COMPRESSION_DEFLATE))
	quit()
