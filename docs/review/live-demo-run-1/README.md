# A live review: Muse Code's fix, before and after

Open [`index.html`](index.html) (it needs no server). It is one run of the live overnight demo:
demo run 1 of fix matrix run [41105875960](https://github.com/Expectrail/Expectrail/actions/runs/41105875960)
(Oct 30, 2026, commit `5e792b4`). Muse Wonder triaged the physics-fall-through report, Muse Code fixed it
in bubblewrap through the key gateway, the verifier accepted with SAM 3.1 and the private routes, and
the review ran the same checks on the seeded game and on the fixed one.

| Check | Role | Before | After |
| --- | --- | --- | --- |
| `player-stays-above-ground` | requested | fail | pass |
| `player-always-visible` | guard | fail | pass |
| `player-motion-on-smoke` | guard | fail | pass |
| `coins-visible` | guard | pass | pass |

Status `REPAIR DEMONSTRATED`. Private routes: 1 check, passed. The frames are frame 5 of each replay:
before the fix the robot is sinking into the floor; after it, the robot stands on it.

## Files

- `change-evidence.json`: the record byte for byte as the run wrote it (SHA256
  `29bb21625eba3f801c3cfde59a48a2a1575a4f04a612bff0bf9710ab06201967`).
- `assets/base.png`, `assets/candidate.png`: the two frames; their SHA256 are in the record, and the
  page shows a frame only while its file still matches.
- `candidate.patch`: Muse Code's patch (its SHA256 is the record's `candidate.patchSha256`). It is byte
  for byte the same as the repository's reference fix, `agents/fixtures/fix-collision-mask.patch`: the
  one line that adds the ground's collision layer. The fixer's workspace holds the game's editable files
  only, never the fixtures.
- `index.html`: rendered here with `python3 -m agents.review_html change-evidence.json --recorded "..." --name index.html`.
  Shown again, a fresh live run is recorded evidence, so the page labels it `RECORDED LIVE` and says the
  run labelled it `FRESH LIVE`.

They came from the run's `demo-run-1` artifact (`runs/demo/run-01/run-00/review/`), downloaded and
attached on Oct 30; `agents.export_scan` found nothing private, no key and no machine path in it.

## Check it

    python3 -c "from expectrail.change_evidence import load_record as l; r = l('docs/review/live-demo-run-1/change-evidence.json'); print(r['status'], r['candidate'])"
    sha256sum docs/review/live-demo-run-1/assets/*.png docs/review/live-demo-run-1/candidate.patch
