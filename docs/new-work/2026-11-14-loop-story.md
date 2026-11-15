# Show the original reject and the proposed repair (#433)

## What changed

The homepage introduction links directly to the loop. The home page, concepts page and README explain when auto-fix starts and who reviews the result.
The app instructions name its checkbox. The Run it card has a static link target before its script loads.
The viewer example shows a fixture patch judged with stand-in replay and observations.
It does not document a live fix. The capability ledger lists the app guide with the installed command.

## What was run

The handover contains the CLI help, the fixture run, the link and front-door checks, and both full suite logs.
The fixture run wrote an original reject and an accepted candidate. The viewer export came from that repair
record. The fixture section was reproduced byte for byte. The two pages were inspected in Qt WebEngine at 1280 × 900 and 390 × 844 with JavaScript disabled and reduced motion enabled. Four section screenshots are in the handover.

[Writer and reader test](../../tests/test_repair_command.py) · [Auto-fix tests](../../tests/test_auto_fix.py).

## Not done

Live repair awaits the [spend caps](https://github.com/Expectrail/Expectrail/pull/436).
CI auto-fix remains under review in [slice 4](https://github.com/Expectrail/Expectrail/pull/463).
The [Run it test](../../tests/test_visible_repair.py) checks that the unpublished card cannot start a run.
No live fixer, vision call, workflow dispatch or deployment was run.

## Files

- `README.md`
- `docs/index.html`, `docs/concepts.html`, `docs/assets/front-door.css`
- `docs/app.md`, `docs/capabilities.json`
- `docs/run-it/index.html`, `docs/viewer-samples/fixture-repair.html`
- `tests/test_loop_story.py`
- `docs/new-work/2026-11-14-loop-story.md`

## Architect's correction on integration

- #436 (spend caps) and #463 (CI auto-fix, fixture fixer behind a maintainer label, off by default)
  merged after this was written. The README, the front page and the concepts page now say so,
  instead of "waiting for spend caps" and "still in review": caps are in, no live repair has been run
  yet, and CI auto-fix runs only the fixture fixer.
- The README now names `expectrail-autofix.yml`, and the capability ledger had no row for repair at
  all (#447, #451 and #463 merged without one), so the ledger check failed. Added a `repair` row:
  grade fixture, status implemented, the three test files as evidence, and the limit stated plainly
  (no live fixer has produced a repair yet; CI auto-fix is off by default and fixture-only; Expectrail
  never merges a repair). `docs/capabilities.md` re-rendered.
