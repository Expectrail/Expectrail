extends Node2D
## Walks 2 px a tick while right is held. Stops while the tree is paused (process_mode pausable).


func _physics_process(_delta: float) -> void:
	if Input.is_action_pressed(&"right"):
		position.x += 2.0
