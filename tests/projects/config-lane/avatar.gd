extends CharacterBody2D

func _physics_process(delta: float) -> void:
	velocity.x = 120.0 if Input.is_action_pressed("move_right") else 0.0
	velocity.y += 600.0 * delta
	move_and_slide()
