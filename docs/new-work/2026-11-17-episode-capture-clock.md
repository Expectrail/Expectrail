# The episode interpreter uses the recorded draw ticks

## What changed

An episode from a new capture stores the physics tick depicted by each frame, in frame order.
Two frames can depict the same tick. A frame's interval can include several physics steps, but
only its depicted tick can witness an event. The normalizer checks the replay against the
harness placements and image digests. Reading a run directory also checks the PNG files.

The interpreter reports `insufficient_observation` with a needs-review diagnostic when a
required event has no draw, or the capture is inconsistent. A separately observed
counterexample can still fail. Trace-only episodes retain their engine samples. Historical
step metadata remains readable and cannot witness an event.

## What was run

On the bundled combat route, Godot 4.7.2 recorded 180 physics ticks at 120 ticks/s and 90
images at 60 fps. Frame 24 depicted tick 49. Frame 25 depicted tick 51, when a projectile
appeared. Counting that spawn passed. Checking the response to the shoot press at tick 50
needed review because there was no draw at tick 50. Replacing frame 25 in a copy of the
capture with frame 24's PNG made the count need review with a digest mismatch at frame 25.
The handover contains the capture, the two predicates and the commands to repeat the checks.

On the capture-clock test game, real Godot at 120 ticks/s and 50 fps drew ticks
`[0, 3, 6, 8, 11]`. At 50 ticks/s and 50 fps it drew all 12 ticks. Each image's leftmost
player pixel matched the position on its episode's mapped tick. The offline Unity-shaped
fixture exercised 50 ticks with one draw per tick and a shot on the final tick.

Full discovery before: 4,789 tests in 515.298 seconds, FAILED (failures=1, skipped=64). After: 4,797 tests in 510.806 seconds, OK (skipped=64). The baseline wheel location test passed on retry with a separately named temporary directory. The handover compares every failing test name. All eight new tests passed with NumPy and Pillow unavailable. The export scan reported zero errors and warnings.

## Not done

Native Unity remains Sean's protected run on #589. The Unity evidence here is a fixture.

## Files

- `contracts/episode.v1.schema.json` and `contracts/examples/episode-capture-clock.v1.json`
- `expectrail/observation_timeline.py`
- `expectrail/trace/normalize.py` and `expectrail/trace/evaluator.py`
- `tests/test_episode_capture_clock.py`
- This work log
