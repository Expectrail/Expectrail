# Bind captured game trees to both revisions (#467)

## What changed

The trusted workflow checks out the repository and head SHA named by the validated candidate run in a separate folder. It uses the existing read permission and keeps no checkout credentials. A full checkout lets the judge use the same file and symlink rules as capture, including links to files elsewhere in that checkout. No step runs from the head folder.

The judge hashes each checkout's game once with `verify.game_tree`. It compares every saved replay against its side's digest before calling the gate. A mismatch names the side and returns `EVIDENCE_MISMATCH`. The gate still receives the base policy and saved replays.

## What was run

Before the fix, both cases of the offline regression failed because the judge accepted a complete archive despite a different checkout tree. After the fix, the release-gate judge subprocess returned exit 3 for each side with an intact stand-in archive. Both responses had a null decision and neither produced a report.

Full unittest discovery on the clean checkouts ran 3,700 tests before and 3,701 after. Both ended OK with 47 skipped and zero failures or errors. A separate discovery with Godot present ran 3,749 tests, OK, with 37 skipped. The focused gate and workflow checks ran 123 tests, OK, with three release-gate classes skipped.

## Not done

The real-engine release-gate bundle tests skipped locally because xvfb-run is missing. The stand-in capture exercises the judge without Godot. No hosted workflow was run.

## Files

- .github/workflows/expectrail-comment.yml
- docs/ci-gate.md
- docs/new-work/2026-11-15-judge-binds-trees.md
- tools/ci_bundle.py
- tools/ci_checks.py
- tests/release_gate/bundle.py
- tests/release_gate/controls.py
- tests/release_gate/gate_bundle.py
- tests/test_ci_gate.py
- tests/test_combat_recording.py
- tests/test_release_gate.py
