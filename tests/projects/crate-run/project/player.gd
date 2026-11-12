extends CharacterBody2D
## The crate: walks left and right, jumps from the floor.

const SPEED := 180.0
const JUMP := -420.0
const GRAVITY := 1200.0


func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity.y += GRAVITY * delta
	elif Input.is_action_just_pressed("jump"):
		velocity.y = JUMP
	velocity.x = Input.get_axis("left", "right") * SPEED
	move_and_slide()
