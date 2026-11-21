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

### Merge guard rework

The CLI now explicitly requires the hub. A missing hub gives one finding naming the absent file. A preview can request the same check without a CNAME. The date is also visible on the failed frame itself. Chromium with scripts disabled confirmed the recording label fit inside the image at 375 px and 1280 px. The recorded PNG bytes are unchanged.

On the old checker, `test_missing_hub_is_reported` returned ten secondary findings instead of the named missing file, and `test_hub_can_be_required_without_a_production_domain` raised a TypeError on the new argument. The new browser fixtures also cover a good hub, enabled sign-in, a missing link and a destination with the wrong heading.

For the rework, the historic fetch succeeded. The full suite ran 5,694 tests in 687.630 seconds, OK with 78 skips. The separate browser-required run of `tests.test_check_pages` ran all 12 tests in Chromium in 85.019 seconds, OK with no skips. The offline CLI opened all 19 pages with zero findings.

## Not done

This slice is under `/hub/`. The site root is owned by open PR #593. Moving the entry point and checking the deployed site with the nightly platform tester remain open. The local app's integration with the shared stylesheet belongs to builder two.

## Files

- `agents/check_pages.py`
- `tests/test_check_pages.py`
- `docs/assets/hub.css`
- `docs/assets/recorded-platformer-frame-5.png`
- `docs/hub/index.html`
- `docs/hub/verify.html`
- `docs/new-work/2026-11-20-recorded-project-hub.md`
