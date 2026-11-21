# Serve the hub fonts from the hub (#712)

## What changed

Hub headings and the wordmark use the two existing TeX Gyre Adventor weights.
The service serves the repository's WOFF bytes and a small stylesheet at
explicit same-origin paths. The Content Security Policy permits fonts from
that origin. The existing font license is in `docs/assets/fonts/`.

Guard: test change intended (#712)

## What was run

- The new stylesheet and WOFF route tests failed before the change.
- The focused hub, receipt and font suite ran 49 tests and passed.
- Offline Chromium loaded both Adventor weights, used Adventor for the hub
  heading, and made no external browser requests.
- `python3 -m unittest discover -s tests -t .` reported `Ran 5948 tests in 836.513s` and `OK (skipped=79)`.
- Scoped export scan: five files, zero errors and zero warnings.

## Not done

This change has only been exercised locally. Durable hub storage and the live
GitHub App setup remain open under #712.

## Files

- `hub/server.py`, `hub/web.py` and `hub/fonts.css`
- `tests/test_hub_auth_assets.py`
- This work log
