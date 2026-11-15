# Run it, played by a visitor in Chromium against the local stub (#265)

## What changed
`python3 -m tools.runit_smoke` is one command that plays a visitor on the Run it page. It gives the
nightly platform test, and CI, a way to exercise the path #265's "Done when" names. It starts
`tools.runit_stub` on a free port, opens `/run-it/#local` in Chromium, and does the following, each
time comparing the page with the published `status.json`:

- While the first run is held, a second visitor must be told "Busy".
- It runs every sample the page offers. The verdict shown, title and colour, must be the one
  `status.json` allows. Only an accept with every vision question answered from the recording may be
  green. The vision line, the receipt line, the request id and the expected end must also match. The
  evidence viewer must draw in its sandboxed frame, and its headline must agree with the decision.
- One run over the visitor quota must say when the quota resets and show the latest run, labelled
  earlier.
- After a reload, each card must name its latest run and its verdict.
- With the service switched off, nothing can start, and the latest run must still open, labelled
  earlier.
- The page must log no script errors.

It runs with real Godot runs (the nightly form, optionally `--require-sandbox`) or with stand-in
replays and stand-in recordings (`--stand-in`). It can save desktop and phone screenshots of each
state. A sample the page does not offer (the recorded fix, until a repair is recorded) is listed as
"not offered". `tests/test_runit_smoke.py` tests the comparison rules without a browser, runs the
stand-in smoke in Chromium, and checks that a copy of the page that turns a reject green fails the
smoke. CI's `web-capture` job runs that test with `EXPECTRAIL_WEB_TESTS=required`. `docs/run-it.md`
describes the command.

Found while building it: Chromium leaves the evidence frame blank in a full-page screenshot when the
frame is below the viewport. The frame itself draws; reading the frame's text shows the viewer. So
the screenshots include a separate shot of the evidence, scrolled into view.

## What was run
- `python3 -m tools.runit_smoke` with **real Godot replays** (no sandbox: this session has no
  bubblewrap) and the samples' recorded vision answers, no model: 3 runs, 9 of 9 checks held, 0
  problems, 116.5 s. `clean`: page "Accepted", status.json accept. `fall-through-bug`: page
  "Rejected", reject. `fall-through-repair`: page "Accepted", accept. Each ended as expected, and the
  viewer's headline agreed. `recorded-fix` was not offered by the page.
- `python3 -m tools.runit_smoke --stand-in --screenshots ...`: 9 of 9 checks held. I looked at the
  screenshots at 1280 px and 390 px: verdict, vision line, receipt, the evidence viewer drawn in its
  frame, the quota refusal with the earlier run, and the switched-off state.
- `python3 -m unittest tests.test_runit_smoke -v`: 11 tests, OK, in about 32 s.
- The full suite on the branch at main 400e819: see the pull request.
- The new CI step has not run yet; its first run is CI on this pull request.

## Not done
- The nightly platform tester is a scheduled session, not code in this repository. It still has to be
  told to run the command. The command is ready for it.
- Nothing here talks to the deployed edge function: that waits on Sean's steps in `docs/run-it.md`.
- The sandboxed real form (`--require-sandbox`) was not run here.

## Files
- `tools/runit_smoke.py` (new)
- `tests/test_runit_smoke.py` (new)
- `.github/workflows/ci.yml` (one step in `web-capture`)
- `docs/run-it.md`
- `.gitignore` (lets `tools/runit_smoke.py` in; `tools/` otherwise holds the downloaded engine)
- `docs/new-work/2026-11-15-runit-smoke.md`
