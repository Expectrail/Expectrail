# The home page's stylesheet and script links change whenever the files do

## What changed

After #527 merged, Sean saw the new How it works section unstyled: the HTML was new, but his browser still held the
old `home.css`, which GitHub Pages lets browsers cache for up to ten minutes. The live stylesheet had the new rules
(fetched after the deploy).

- `docs/index.html`: the `home.css` and `home.js` links end in `?v=` plus the first 10 hex digits of each file's
  SHA-256, so a changed file has a new address.
- `tests/test_home_interactive.py`: the asset test now requires those exact tags, computed from the files. A change
  to either file without the new tag fails it. The test is stricter, not looser.

## What was run

- `python3 -m unittest discover -s tests -t .`: `Ran 4003 tests`, `OK (skipped=41)` on the second run; the first failed one Run it smoke test that passes alone (see the pull request).
- `python3 -m agents.check_pages docs --offline`: 15 pages, 0 problems. `python3 -m tools.front_door`: 0 problems.
- Headless Chrome at six widths: styles and script load, the equation plays and pauses, no errors.

## Not done

- `front-door.css`, shared by every page, has no tag yet.

## Files

- `docs/index.html`
- `tests/test_home_interactive.py`
- `docs/new-work/2026-11-15-home-cache-bust.md`
