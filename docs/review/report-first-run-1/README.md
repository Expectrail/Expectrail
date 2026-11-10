# A live review on the loop as it ships: Muse Code fixes from a plain report

Open [`index.html`](index.html) (it needs no server). It is one run of the live overnight demo on
the loop as it is on main since #122 and #123: demo run 1 of fix matrix run
[41223748922](https://github.com/Expectrail/Expectrail/actions/runs/41223748922) (Oct 31, 2026,
commit `4697f54`). Muse Wonder triaged the physics-fall-through report. Muse Code got a plain report
first, as the loop now gives it ([docs/report-first.md](../../report-first.md)): the failing check's
sentence, screenshots of the failing run, the route and its log, and no spec or verdict. It fixed the
bug on its first attempt, in bubblewrap, through the key gateway. The verifier accepted with SAM 3.1
and the private routes, and the review ran the same checks on the seeded game and on the fixed one.

| Check | Role | Before | After |
| --- | --- | --- | --- |
| `player-stays-above-ground` | requested | fail | pass |
| `player-always-visible` | guard | fail | pass |
| `player-motion-on-smoke` | guard | fail | pass |
| `coins-visible` | guard | pass | pass |

Status `REPAIR DEMONSTRATED`. Private routes: 1 check, passed. The frames are frame 5 of each replay:
before the fix the robot is sinking into the floor; after it, the robot stands on it.

All three demo runs of 41223748922 ended the same way: accepted on the first attempt from the plain
report, every review `REPAIR DEMONSTRATED` on `FRESH LIVE` evidence, the morning report signed. The
same fix under the older loop, which gave Muse the evidence first, is
[live-demo-run-1](../live-demo-run-1/) (Oct 30).

## Files

- `change-evidence.json`: the record byte for byte as the run wrote it (SHA256
  `b772dfdb3bef6ab427572cc5e41f6320c41bf68bbf12ea268a2a891820e3b67e`).
- `assets/base.png`, `assets/candidate.png`: the two frames; their SHA256 are in the record, and the
  page shows a frame only while its file still matches.
- `candidate.patch`: Muse Code's patch (its SHA256 is the record's `candidate.patchSha256`). It is byte
  for byte the repository's reference fix, `agents/fixtures/fix-collision-mask.patch`, the same one line
  Muse Code wrote on Oct 30 when it had the evidence. The fixer's workspace holds the game's editable
  files only, never the fixtures.
- `index.html`: rendered here with
  `python3 -m agents.review_html change-evidence.json --recorded "fix matrix run 41223748922, demo run 1" --name index.html`.
  Shown again, a fresh live run is recorded evidence, so the page labels it `RECORDED LIVE` and says the
  run labelled it `FRESH LIVE`.

They came from the run's `demo-run-1` artifact (`runs/demo/run-01/run-00/review/` and `fix/`),
downloaded and attached on Oct 31. The run scanned the artifact against the private set before
uploading it, and `agents.export_scan` found nothing private, no key and no machine path in it again
here.

## Check it

    python3 -c "from expectrail.change_evidence import load_record as l; r = l('docs/review/report-first-run-1/change-evidence.json'); print(r['status'], r['candidate'])"
    sha256sum docs/review/report-first-run-1/assets/*.png docs/review/report-first-run-1/candidate.patch
