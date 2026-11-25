# Show WebP sheet dimensions when choosing a Godot player (#370, #824)

## What changed

Check folders can now display the source image dimensions for a player that uses a WebP texture. Static inspection reads a 30-byte prefix and checks the RIFF length against the open file. An unrecognized header or mismatched declared file length leaves the size unknown. Offline review uses the same canvas reader and keeps its 4096-pixel limit for embedded art.

## What was run

The selected-player regression failed on main with a missing size. With this change, all 25 tests in `tests.test_inspect_atlas`, `tests.test_onboard_ci`, `tests.test_onboard_small_images`, and `tests.test_app_setup_picker` passed. Separate probes covered lossless, lossy, and extended WebP, four malformed inputs, and a 4608-pixel texture that static inspection could identify while offline embedding declined it.

I built the wheel, installed it without dependencies into a fresh environment, and launched the installed app from outside the checkout. In Chromium, I opened two disposable copies of Godot’s Physics Platformer and selected Player on both sides. Both panels showed `res://player/player.webp (512 × 64)`. The 76 original files in each copy retained their hashes, no files were added, and the app received zero save and verification-job requests. [Public project revision](https://github.com/godotengine/godot-demo-projects/tree/b761b4cd5718a7118f2c95eb55f181d0a5f004f1/2d/physics_platformer)

After fetching the required historical commit, full discovery ran 6,116 tests in 1,505 seconds with 2 failures, 7 errors and 47 skips on Linux with Godot 4.7.2. Seven repair-pricing failures and errors also reproduced on unchanged main. Two configured-folder checks exceeded their deadlines in the full run. Both passed when isolated on main and on the branch. The cause of the full-run timeouts is unverified. The public export scan passed.

## What remains

The grid and saved 32 × 32 cell are still missing from the picker. The browser rehearsal used automation. An unaided session on a developer’s own game remains outstanding. [Issue #824](https://github.com/Expectrail/Expectrail/issues/824)

## Files

- `expectrail/onboarding.py`
- `expectrail/onboard_review.py`
- `tests/test_inspect_atlas.py`
- This work log
