extends CharacterBody2D
var playing := false

func start_play() -> void:
	playing = true
	get_node("../Menu/Start").hide()

func _physics_process(_delta: float) -> void:
	if playing:
		position.x = get_viewport().get_mouse_position().x
		position.y = 130 if Input.is_mouse_button_pressed(MOUSE_BUTTON_RIGHT) else 120
