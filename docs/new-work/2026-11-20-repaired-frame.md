# Show the captured frame where the repaired check first differs (#696)

## What changed

The public kinematic-character repair comparison selected its first measured difference at frame 20. The restored game had passed, so its exported viewer had measurements but no pictures. The rejected mask-2 change showed the Before and After pictures at frame 44. [Hosted comparison and downloadable evidence](https://github.com/Expectrail/Expectrail/actions/runs/44726059532/job/136253642904)

A repaired check now keeps each side's captured PNG at the first difference between comparable engine measurements. The viewer reserves the existing frame slots and export budget for findings first. Missing images and linked files stay absent. Each embedded PNG must match the digest recorded in the local viewer. The capture directory is used only while building the viewer.

## What was run

The gate-to-viewer regression failed before the change because the two repair timelines differed at frame 30 while their image lists were empty. All 44 tests in `python3 -m unittest tests.test_viewer_measurements tests.test_viewer tests.test_viewer_timeline` passed after the change. They cover local and exported images, missing or unsafe captures, and both frame limits.

An offline replay of the archived public kinematic-character captures used the existing recorded answers. Comparing broken Before with pinned After yielded `REPAIRED`. The engine and vision passed After. Offline Chromium selected frame 20 and displayed both 530 × 495 images with three measurement plots, zero external requests and zero script errors. Both images matched their source PNGs. The SHA-256 digests started with `5913b34c463f` Before and `e1b03824a769` After. [Original capture run](https://github.com/Expectrail/Expectrail/actions/runs/43652198623)

The full suite (`python3 -m unittest discover -s tests -t .`) ran 5,591 tests in 582.957 seconds, with 78 skipped and zero failures or errors. The export scan (`python -m agents.export_scan bench docs README.md apps --paths error`) checked 1,256 files with zero findings.

## Not done

An unaided Godot developer session on their own project remains open.

## Files

- `expectrail/viewer.py`
- `tests/test_viewer_measurements.py`
- `docs/new-work/2026-11-20-repaired-frame.md`
