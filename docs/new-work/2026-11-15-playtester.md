# Seeded Godot playtester and engine-only report filtering (#531, part two)

## What changed

Added `tools/playtester/`: seeded random gameplay routes from the project input map, 1–1,800 ticks
from the start through the existing headless harness. Three stated trace observations produce
`expectrail.playtest-report/v1` documents in issue #531's exact field shape, including the complete
route and the previous tick's Player anchor. Reports contain player wording, no check name or
claimed cause. IDs and serialization are deterministic for the same route, target and trace.

Added a local public-build experiment. It applies patches only to copies, identifies each build
with a reconstructible local commit and verifies the game blobs, then replays all producer
reports and two hand-written false reports three times without a fixer or model. Published
per-build counts, per-report filter results and coverage limitations in `docs/playtester-results.md`.

## What was run

- Setup: cloned the public repository, created `chatgpt/531-playtest-producer` from `origin/main`,
  recorded BASE_COMMIT `e18dd3ef5267175166743c17a7b37480a292f3c0`, and fetched
  `c169a5e0da304773587304ed47bc8aabcec80da7` using the requested flags. Read AGENTS.md,
  issue #531 and its claim comment, the route schema/auto-route, harness code/docs and public known
  bug material. No GitHub mutations.
- Before changes, `python3 -m unittest discover -s tests -t .`, with every `EXPECTRAIL_*` variable
  removed: exit 0, **4,028 tests in 444.353 s, 47 skipped**. No failing unittest test names.
- `python3 -m unittest tests.test_playtester -v`: **13 tests passed**. Covers bounded seeded
  routes, exact report shape and anchor, first observations and missing data, incomplete traces,
  unknown actions, no overwrites, three-of-three reproduction and anchor precedence.
- `python3 -m tools.playtester.bench --out ../experiment-xdg --seeds 4 --ticks 1200
  --godot /usr/local/bin/godot`, with writable XDG data/cache/config directories: exit 0.
  **Godot 4.6.3**, 24 discovery replays: clean 0 reports, air-jump 1 immobility report,
  body-flip 4 turning reports, enemy-ledge 0, gun-cooldown 0, draw-order patch 0.
  Known symptom detected: body-flip. The air-jump report does not identify infinite jumping.
- All five producer reports plus two manual false reports replayed on their unchanged target
  builds: 21 fresh filter replays plus one idle source replay. All five observations reproduced
  3/3 and reached their anchors 3/3. Idle false report: 0/3 reproduced, 3/3 anchor reached.
  Wrong-anchor report: 3/3 reproduced, 0/3 anchor reached. **2 of 7 filtered** by these engine-only
  measurements; all seven groups of three full traces were identical. No ingest or shared-verifier
  verdict is claimed. No model or fixer calls.
- Audit: reconstructed every target commit; matched every game blob; compared all seven report
  field sets to the issue table and validated embedded routes against the existing route schema;
  regenerated five producer reports identically from independent replay traces. Recorded reach
  metrics show that unreported known symptoms must not be described as wholly unreached.
- Initial engine attempt without writable XDG directories aborted on its first clean replay with
  a user-data permission error and Godot crash; no report was produced. Its log is retained.
- Full post-change suite, `python3 -m unittest discover -s tests -t .`, with every
  `EXPECTRAIL_*` variable removed: exit 0, **4,041 tests in 568.126 s, 47 skipped**. No failing
  unittest test names. `git diff --check` passed.

## Not done

Pinned Godot 4.7.2, rendered frames, arbitrary-report ingestion, shared-verifier integration,
generated checks, fixer and end-to-end repair rates were not run. This is the producer and local
engine-only measurement; the other #531 builder owns schema/ingest. No contracts/playtest-report
file or ingest command added. No approval, original game, protected verifier/orchestrator file,
GitHub workflow, blind/held-out content, remote branch, issue or PR was changed.

## Files

- `.gitignore`: include the new playtester directory.
- `tools/playtester/__init__.py`, `__main__.py`, `producer.py`, `bench.py`, `README.md`.
- `tests/test_playtester.py` (new test file; no existing test edited).
- `docs/playtester-results.md`.
- `docs/new-work/2026-11-15-playtester.md`.

The single handover zip includes `changes.patch` (new files included), base/title/body, suite logs
and exit codes, focused-test/audit/experiment logs, all report documents, routes and raw successful
engine traces/replay records. Game copies and import caches are omitted from the zip.
