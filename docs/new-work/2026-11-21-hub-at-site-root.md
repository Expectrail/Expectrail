# The site's root reaches the hub and its four recorded screens in one click (#709)

## What changed
#725 put the signed-out hub at `docs/hub/` and left the site-root entry open. A visitor who landed on
expectrail.tech had no link to the hub at all.

- `docs/index.html` has a new section right after the hero, "See what you would use, before you install".
  It links the four recorded screens that the hub links: the local verify screen (Crate Run), the
  Breakout setup review, an accepted result and the fixture repair evidence. Each card carries its
  recording date ("Fixture, published" for the repair, which used a stand-in fixer) and the section
  says nothing in it runs now. It needs no JavaScript and is not hidden by the scroll-in effect.
- The hero's first button is now "See the product" and opens the hub. "Understand a verdict" left the
  hero; Concepts is still in the section menu.
- The section menu on the five front-door pages and the root's footer get a Hub link. The wordmark on
  the hub and its verify screen now leads to the site's root instead of back to the hub.
- `agents.check_pages` follows the root page's links to the hub and the four screens with scripts off at
  375 px and 1280 px, the same way it already follows the hub's. The hub and the root share one helper.
- The page checker now waits up to five seconds for the destination's heading instead of reading it once
  straight after the click. On unchanged main, one run reported the Breakout setup review as
  "unreadable without scripts" at 375 px. Three direct probes found its heading visible each time, so
  that finding came from reading the page before it had loaded.

Decision: the root's existing narrative stays below the new section. Whether the root page should be
replaced by the hub page itself is Sean's call.

## What was run
- `python3 -m unittest tests.test_check_pages` with Playwright Chromium: 16 tests, OK. Before the
  checker change, the four new root tests failed (red).
- `python3 -m agents.check_pages docs`: 19 pages, 0 problems. Before the page change it reported
  eight root findings: the hub and three screens missing from the root, at both widths. The repair
  screen was already linked from the root's repair section.
- `python3 -m tools.front_door`: 0 problems.
- Looked at the root page in Chromium at 375 px and 1280 px, with and without JavaScript. Desktop shows
  the four cards in a row, a phone shows them stacked, and neither width scrolls sideways.
- With the root check's call removed from `check`, `tests.test_check_pages` failed 5 tests (mutation caught).
- Full suite on the branch, based on main at b5a58a7: 5,887 tests, OK, 76 skipped.

## Not done
- One-click checks on the deployed site and the nightly platform tester's confirmation (#709's Done-when).
- The list of differences between the hub and the local app's page (#710).

## Files
- `docs/index.html`, `docs/assets/home.css`
- `docs/quickstart.html`, `docs/concepts.html`, `docs/guides.html`, `docs/positioning.html` (Hub link)
- `docs/hub/index.html`, `docs/hub/verify.html` (wordmark)
- `agents/check_pages.py`, `tests/test_check_pages.py`
- `docs/new-work/2026-11-21-hub-at-site-root.md`
