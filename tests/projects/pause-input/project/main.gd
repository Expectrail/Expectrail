extends Node2D
## The scene's root runs while the tree is paused, so the pause key can also unpause it, as the
## bundled game's root does. The player does not: it stands still while the game is paused.


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed(&"pause"):
		get_tree().paused = not get_tree().paused
		$UI/Paused.visible = get_tree().paused
