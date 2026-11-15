extends Node
## Capture spike (#246): a stand-in for a change written to forge its evidence. Not product code.
##
## --spike-forge=FIRST:LAST:SOURCE  once frame LAST + 5 has been drawn, overwrite the movie frames
##                                  FIRST..LAST that Movie Maker wrote with the bytes of frame SOURCE
## --spike-movie=PATH               the path given to --write-movie (Movie Maker's frames)
## --spike-reach=PATH               try to read and to write PATH (the supervisor's capture) and print
##                                  what happened, as "SPIKE reach <what> <result>"
##
## Everything here is ordinary GDScript a game script can run, from inside the game process.

var _first := -1
var _last := -1
var _source := -1
var _movie_prefix := ""
var _count := 0
var _done := false


func _ready() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--spike-movie="):
			_movie_prefix = arg.substr("--spike-movie=".length()).get_basename()
		elif arg.begins_with("--spike-forge="):
			var parts := arg.substr("--spike-forge=".length()).split(":")
			_first = int(parts[0])
			_last = int(parts[1])
			_source = int(parts[2])
		elif arg.begins_with("--spike-reach="):
			_reach(arg.substr("--spike-reach=".length()))
	if _first >= 0:
		if _movie_prefix == "":
			printerr("SPIKE forge: no --spike-movie given")
		else:
			RenderingServer.frame_post_draw.connect(_on_drawn)


func _reach(path: String) -> void:
	var f := FileAccess.open(path, FileAccess.READ)
	print("SPIKE reach read ", "ok" if f != null else error_string(FileAccess.get_open_error()))
	f = FileAccess.open(path, FileAccess.READ_WRITE)
	print("SPIKE reach write ", "ok" if f != null else error_string(FileAccess.get_open_error()))
	var beside := path.get_base_dir() + "/planted.png"
	f = FileAccess.open(beside, FileAccess.WRITE)
	print("SPIKE reach plant ", "ok" if f != null else error_string(FileAccess.get_open_error()))
	var listing := DirAccess.open(path.get_base_dir())
	print("SPIKE reach list ", "ok" if listing != null else error_string(DirAccess.get_open_error()))


func _frame(n: int) -> String:
	return "%s%08d.png" % [_movie_prefix, n]


func _on_drawn() -> void:
	_count += 1
	if _done or _count < _last + 5:
		return
	_done = true
	var source := FileAccess.get_file_as_bytes(_frame(_source))
	var rewritten := 0
	for n in range(_first, _last + 1):
		var f := FileAccess.open(_frame(n), FileAccess.WRITE)
		if f != null:
			f.store_buffer(source)
			f.close()
			rewritten += 1
	print("SPIKE forged ", rewritten, " movie frames (", _first, "..", _last, ") with frame ", _source)
