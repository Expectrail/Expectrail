extends Node2D

func _physics_process(_delta: float) -> void:
	position.x += 1.0

func _draw() -> void:
	draw_rect(Rect2(0, 0, 8, 8), Color.WHITE)
