extends CharacterBody2D

func _physics_process(_delta: float) -> void:
    if Input.is_action_pressed(&"right"):
        position.x += 2.0
    if Input.is_action_pressed(&"left"):
        position.x -= 2.0
