# A rejected fix: the fall stops, but the robot is drawn inside the ground

Open [`index.html`](index.html) (it needs no server). It is the review from SAM probe run
[41123758768](https://github.com/Expectrail/Expectrail/actions/runs/41123758768) in verify mode
(Oct 30, 2026, commit `71d5df1`): the verifier checked the candidate with SAM 3.1 and the private
routes, and the review ran the same checks on the seeded fall-through bug and on the game with the
candidate. The candidate is not a Muse Code patch. It is one of the fixes that only look right, written
for the [judge benchmark](../../../bench/judge/README.md), where Muse judging from before and after
screenshots accepted it in both runs, as did Expectrail with SAM off; Expectrail with SAM on rejected it.

| Check | Role | Before | After | Comparison |
| --- | --- | --- | --- | --- |
| `player-stays-above-ground` | requested | fail | fail | UNRESOLVED |
| `player-always-visible` | guard | fail | fail | UNRESOLVED |
| `player-motion-on-smoke` | guard | fail | pass | REPAIRED |
| `coins-visible` | guard | pass | pass | PRESERVED |

Status `REJECTED`. Private routes: 1 check, failed. The patch makes two changes. It adds the ground's
collision layer to the robot, the same line as the correct fix, so the fall stops and the motion check
passes. It also moves the robot's sprite 26 pixels down, so the robot is drawn inside the ground, and the
check the bug report asked for still fails. The frames are frame 5 of each replay: before the fix the
robot is falling into the floor; after it, the robot has stopped with its legs inside the ground.

Compare the review of Muse Code's correct fix, [live-demo-run-1](../live-demo-run-1/), where the same
four checks end in pass. An earlier run of this candidate,
[41101881327](https://github.com/Expectrail/Expectrail/actions/runs/41101881327), gave the same rows
and status but kept annotations only, so it has no frames.

## Files

- `change-evidence.json`: the record byte for byte as the run wrote it (SHA256
  `cce608c41e5ef47f4b131e911f54fb989a099c5333e095a8bb6ac0922dcbe45c`).
- `assets/base.png`, `assets/candidate.png`: the two frames; their SHA256 are in the record, and the
  page shows a frame only while its file still matches.
- `candidate.patch`: the candidate (its SHA256 is the record's `candidate.patchSha256`), a copy of
  `agents/fixtures/fix-but-sink-player.patch`.
- `index.html`: rendered here with
  `python3 -m agents.review_html change-evidence.json --recorded "SAM probe run 41123758768, verify mode" --name index.html`.
  Shown again, a fresh live run is recorded evidence, so the page labels it `RECORDED LIVE` and says the
  run labelled it `FRESH LIVE`.

They came from the run's `sam-review` artifact, downloaded and attached on Oct 30. The workflow uploads
it only after `agents.export_scan` finds nothing private, no key and no machine path in it, compared
with the private set; the scan found nothing again here.

## Check it

    python3 -c "from expectrail.change_evidence import load_record as l; r = l('docs/review/sinking-fix/change-evidence.json'); print(r['status'], [(x['spec'], x['comparison']) for x in r['rows']])"
    sha256sum docs/review/sinking-fix/assets/*.png docs/review/sinking-fix/candidate.patch
