# Run it is linked from the home page and the README (#265)

## What changed
A stranger who lands on expectrail.tech or the README can now find Run it.
- `docs/index.html`: "Run it" in the header, a "Run a check yourself" button in the hero, a sentence under
  the buttons, and a line in the footer. The sentence promises no verdict: it says the Run it page tells you
  whether it can start a run right now. On a phone the header link is hidden like the other section links;
  the hero button stays.
- `README.md`: a link to `https://expectrail.tech/run-it/` in the top row of links.
- `docs/run-it/index.html`: the intro said the vision answers "were recorded once for each sample". None are
  recorded yet. It now says they are recorded once per sample, and that a sample whose answers are not
  recorded yet cannot be accepted.
- The capability ledger has a `run-it` row: grade `diagnostic`, status `implemented`, citing run
  43453709805 (run-it.yml dispatched on main; jobs `verify` and `publish` both succeeded, read from the API)
  and the tests. Its limits say visitors cannot start a run yet and no sample can be accepted yet.
  `docs/capabilities.md` was rendered from it.
- `tests/test_runit_links.py`: the home page links Run it from the hero, the header and the footer; the note
  promises no verdict; the README links the live page; the page does not say answers were recorded.

## What was run
- `python3 -m unittest tests.test_runit_links tests.test_capabilities tests.test_runit tests.test_runit_site`:
  OK.
- The full suite on this branch (based on main at eba2518): see the pull request.
- Chromium, the docs folder served locally, at 1280x900 and 390x844: the home page shows the header link and
  the hero button on desktop, the hero button on the phone, no sideways scroll on either. The button opens
  `run-it/`, which said "Run it cannot start runs right now: the service that starts them is not reachable"
  (`api.expectrail.tech` is not set up) and listed the three samples.

## Not done
- The service is not deployed and no sample is recorded; both wait on Sean (#265, #394).
- `run-it-results` has no `latest.json` yet: the one run there (arch-smoke-1) predates it. The next
  run-it.yml run writes it.

## Files
- `docs/index.html`
- `README.md`
- `docs/run-it/index.html`
- `docs/capabilities.json`, `docs/capabilities.md`
- `tests/test_runit_links.py`
- `docs/new-work/2026-11-13-run-it-home.md`
