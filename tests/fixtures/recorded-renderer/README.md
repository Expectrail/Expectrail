# Recorded renderer measurements (#515)

These are unmodified public kinematic-character capture files, not model-generated images.
The checked-in recording is [vision-recording.json](../../outside/recordings/kinematic-character/vision-recording.json).
Its answers have not changed; its rendering provenance was copied from the original capture.

- `recorded.png`, `hidden.png`, `tinted.png`, and `recorded-replay.json` come from the pinned,
  invisible and harmless arms of [outside vision run 43652198623](https://github.com/Expectrail/Expectrail/actions/runs/43652198623),
  route `walk`, frame 111. Each original arm reports the same rendering environment. The game's
  public pinned revision is `b761b4cd5718a7118f2c95eb55f181d0a5f004f1` in
  [godot-demo-projects/2d/kinematic_character](https://github.com/godotengine/godot-demo-projects/tree/b761b4cd5718a7118f2c95eb55f181d0a5f004f1/2d/kinematic_character).
- `replayed.png` and `replayed-replay.json` come from the real Godot 4.7.2 replay made for #370
  slice 4 on November 15, 2026, which produced #515. That replay used llvmpipe LLVM 19.1.7;
  the original used LLVM 20.1.2. The newer replay was diagnostic, not sandboxed. No new game
  or live model run was made for these measurements.
- `source.json` records SHA-256 for all six inputs and the original trace row at tick 222
  (frame 111). The two replay manifests name every frame hash. Only frame 111 differs;
  byte-identical frames need not be duplicated here.

`python3 -m tools.recorded_renderer --out /tmp/recorded-renderer.json` verifies these hashes,
checks the frame against the manifests and the recording, then reproduces the published table.
The player box is the existing answer for frame 111: [481,321,497,337), in frame pixels.
Distances are from changed pixel centres to the nearest pixel centre in this original box.
The shifted and resized cases use the real hidden capture as their background. Recolours alter
only the stated player pixels. These are controlled probes, not new real game replay claims.
