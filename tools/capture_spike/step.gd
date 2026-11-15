extends Node
## Capture spike (#246), approach 1: hold the engine after each drawn frame until the supervisor has
## grabbed the display. Not product code: tools/capture_spike adds it to a replay's copy of the game.
##
## Given --spike-sync=DIR, after each drawn frame it writes the frame's number to DIR/drawn and waits
## until DIR/ack holds the same number. Godot's FileAccess will not open a FIFO, so this is two
## ordinary files and polling. Without the argument it does nothing.
## This script runs inside the game, so it is the game's to lie through: the supervisor never takes
## the number it sends as evidence of what was drawn, only as the moment to grab.

const WAIT_USEC := 200
const GIVE_UP_MSEC := 60000

var _dir := ""
var _count := 0


func _ready() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--spike-sync="):
			_dir = arg.substr("--spike-sync=".length())
	if _dir == "":
		return
	RenderingServer.frame_post_draw.connect(_on_drawn)


func _on_drawn() -> void:
	var said := str(_count)
	_count += 1
	var f := FileAccess.open(_dir + "/drawn", FileAccess.WRITE)
	if f == null:
		printerr("SPIKE step: cannot write ", _dir, "/drawn: ", error_string(FileAccess.get_open_error()))
		get_tree().quit(3)
		return
	f.store_string(said)
	f.close()
	var start := Time.get_ticks_msec()
	while FileAccess.get_file_as_string(_dir + "/ack").strip_edges() != said:
		if Time.get_ticks_msec() - start > GIVE_UP_MSEC:
			printerr("SPIKE step: no acknowledgement for frame ", said)
			get_tree().quit(3)
			return
		OS.delay_usec(WAIT_USEC)
