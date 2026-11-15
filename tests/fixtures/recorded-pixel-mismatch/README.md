# The unrecorded frame-111 image (#370)

These are unmodified PNGs of the public, MIT-licensed
[kinematic-character demo](https://github.com/godotengine/godot-demo-projects/tree/b761b4cd5718a7118f2c95eb55f181d0a5f004f1/2d/kinematic_character).

- `recorded.png`: pinned/walk/frame 111 from the outside-captures artifact of
  [run 43652198623](https://github.com/Expectrail/Expectrail/actions/runs/43652198623).
- `replayed.png`: frame 111 from a Godot 4.7.2 replay on November 15, 2026, at the
  same public project commit and route, using main b947635's harness.
- `question.json`: measured hashes, exact point prompt and pixel differences.

The recorded answers in `tests/outside/recordings/kinematic-character/vision-recording.json`
contain the prompt for `recorded.png`, not `replayed.png`. The point question is unchanged.
Two pixels differ away from the point. This fixture does not authorize using one image's
answer for another image, and it contains no newly generated model answer.
`tests/test_app_projects.py` verifies exact matching with no engine, network or model.
