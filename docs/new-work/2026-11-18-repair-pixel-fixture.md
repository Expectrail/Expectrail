# Repair verification reads the bundled robot from captured frames

## What changed

The repair CLI fixture used the engine trace for the player's visual box. The fresh gate correctly reported `observation-timeline: visual target is not pixel evidence at frame 0`. The seeded bug failed on the base, but the repaired head had only one observer that could pass the ground check.

The fixture now gives `FramesObserver` a local client that locates the bundled robot's blue paint in each captured PNG. The box prompt also checks for paint inside the requested region. The regular observer adapter attaches the image digest, tick and frame. The same Godot executable decodes full-size frames in a separate headless process that loads only the fixture script. Answers are cached by the PNG digest. The small unit fixture uses the standard-library PNG decoder.

## What was run

On the PR head, both repair tests failed with Godot 4.7.2 and Bubblewrap 0.12.0. A real-engine diagnostic run kept the fresh job's findings. Rejudging its saved captures with the updated fixture found the first engine failure on the broken base at frame 5 and a pass from both observers on all 120 repaired frames.

The two unchanged CLI tests also ran before and after on native Linux with real Bubblewrap and Pillow unavailable. Both failed before the patch. Both passed after it. In each fresh job all six replays were sandboxed, the base failed three of three, and the repaired head passed three of three. Full discovery passed before (5,137 tests) and after (5,138 tests), with 71 skips on each run. The pixel fixture unit test also passed with site packages disabled. The export scan reported zero errors or warnings.

## Not done

The hosted seeded-bugs job was not dispatched. The fixture identifies one palette colour in the bundled game on this route. This run measures no other game's visual behaviour.

## Files

- `tests/repair_cli_fixture.py`
- `tests/test_repair_pixels.py`
- `tests/repair_decode_frames.gd`
- `docs/new-work/2026-11-18-repair-pixel-fixture.md`
