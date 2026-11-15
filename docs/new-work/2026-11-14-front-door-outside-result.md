# Show the first outside vision verification (#263, #330)

## What changed

The front page and README show the four kinematic-character variants beside
their verdicts. Each verdict and the full run's list-price cost link to the
run. The pages explain what vision measured on the hidden player and where
Dodge the Creeps stands. The release dossier reads the four outcomes from the
published trial and keeps the earlier attempts in its history.

## What was run

- The capture and judge jobs both succeeded in [the recorded run](https://github.com/Expectrail/Expectrail/actions/runs/43652198623).
- `python -m tools.dossier` regenerated the release page. Its `--check` matched.
- `python3 -m tools.front_door` found zero problems. `python3 -m expectrail.capabilities check` exited zero.
- The focused front-page, links, dossier and capability tests ran 191 tests, OK.
- Chromium opened the results at 1280 × 900 and 390 × 844. The table fit both widths.

## Not done

No new verification was run. No live model, hosted CI or deployment.
The hidden-player wording change and Dodge check approval are separate work.

## Files

- `README.md`
- `docs/index.html`
- `docs/release/index.html`
- `docs/new-work/2026-11-14-front-door-outside-result.md`
- `tools/dossier.py`
- `tests/test_outside_result_pages.py`

## Architect's correction on integration

- #481 merged after this was written. The front page and the README now say that since #481 Expectrail reports "not drawn" for a hidden player, and that no live run has shown that yet, instead of calling it a proposed fix.
