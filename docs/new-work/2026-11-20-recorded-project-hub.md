# Open four recorded screens from the signed-out project hub (#709)

## What changed

The hub shows the bundled project, its clean and broken verification results, the first failing frame, and a setup review for a separate draft project. The four screens are ordinary links. The GitHub sign-in control is disabled and explains its future purpose. The empty playtest panel links to #531.

| Sample | Recording source |
| --- | --- |
| Bundled platformer, verdicts, route, first failure and date | [Published sample provenance](../viewer-samples/provenance.json) and the embedded findings in the [fall-through viewer](../viewer-samples/fall-through-bug.html). The hub uses the exact after PNG from frame 5, SHA-256 `bbf3c8d8ab79c831a9118a5cc06bddea6a61fc432a929e6f07e87586d137500a`. |
| Crate Run verify screen | [17 November browser demonstration](../demo/local-app.md), transcribed as a read-only screen. |
| Breakout draft review | [Review](../onboarding-examples/breakout.html) from the [16 November pointer trial](../outside-trials/breakout-pointer/commands.json). |
| Repair evidence | [Fixture viewer](../viewer-samples/fixture-repair.html), published on [14 November](https://github.com/Expectrail/Expectrail/commit/e1efc4dd0). Its fixer and observations were stand-ins. |

## What was run

- Before building the hub, the new browser check reported ten missing controls and screen links across the two viewport widths. With the hub in place it reported zero.
- Chromium opened all 19 HTML pages with the site's offline checker and found zero problems. With JavaScript disabled, a visitor at 375 px and 1280 px could follow each of the four links to a readable screen. The hub fit both widths and sign-in was visibly disabled.
- The historic fetch succeeded. The full suite ran 5,676 tests in 692.291 seconds with 78 skips and zero failures or errors.
- The public export scan checked 1,283 files and reported zero errors and zero warnings.

## Not done

This slice is under `/hub/`. The site root is owned by open PR #593. Moving the entry point and checking the deployed site with the nightly platform tester remain open. The local app's integration with the shared stylesheet belongs to builder two.

## Files

- `agents/check_pages.py`
- `docs/assets/hub.css`
- `docs/assets/recorded-platformer-frame-5.png`
- `docs/hub/index.html`
- `docs/hub/verify.html`
- `docs/new-work/2026-11-20-recorded-project-hub.md`
