extends Node2D
## Three ways a game reads input, each written into the player's position so a trace shows it:
##   start  an event in _unhandled_input; nothing moves before it
##   hop    an event in _input; each press lifts the player 8 px, a release does nothing
##   right  polled every physics tick with Input.is_action_pressed; 2 px a tick once started
##   menu   the shortcut of a button; its press drops the player to y = 300

var started := false
@onready var player: Node2D = $Player


func _input(event: InputEvent) -> void:
	if event.is_action_pressed(&"hop"):
		player.position.y -= 8.0


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed(&"start"):
		started = true


func _physics_process(_delta: float) -> void:
	if started and Input.is_action_pressed(&"right"):
		player.position.x += 2.0


func _on_menu_pressed() -> void:
	player.position.y = 300.0
