# A Run it result names the rendering environment its frames were drawn in (#265, with #515)

## What changed
Sample recordings answer by exact image bytes (Option A on #265). #515 measured that one LLVM step on
the renderer changes two pixels in one frame, which is enough for a frame to have no recorded answer.
If the hosted runner's Mesa or LLVM changes, every visitor's run turns needs-review, and before this
change nothing published said which environment drew the frames.

- `expectrail.recorded.RecordedClient` notes the rendering environment of every capture it is asked
  about (from that capture's own `replay.json`, as before) and gives `rendering()`: this run's
  environments, the recording's (null when it names none), and `match`, `mismatch`, `unknown` or
  `unavailable`. It never answers a question and never changes a verdict.
- A frame missing from a recording that names no environment now says so in plain words, with this
  replay's environment, instead of only "the recording does not hold this frame and question". It
  never guesses the recording's environment.
- Contract: `run-it-result.v1`'s `vision` gets an optional `rendering` block. The schema, the example,
  the writer (`expectrail.runit`, which also caps `vision.why` at the schema's 300 characters) and the
  readers change together: the Run it page shows one "Rendering" line after the vision line,
  `tools/runit_smoke` fails if that line differs from `recorded.rendering_sentence`, and the nightly's
  `tools/runit_published` reports it in its pass line. Results published before this change still read.

## What was run
- `python3 -m unittest tests.test_runit_rendering`: 23 tests, OK. They cover the client, a stand-in
  Run it through the real orchestrator and gate (match, a drifted runner, a recording with no
  environment, the same bytes from another environment still answered exactly), the schema, the
  smoke's comparison, the nightly's note, and the page's own `renderingLine` under Node against the
  Python sentence for every status and nine malformed blocks.
- Six mutations (always `match`; no 240-character cap; an unnamed capture ignored; one word changed in
  the page; the smoke's comparison switched off; the writer leaving the block out) were each caught.
- The Run it page against the local stub (`tools.runit_stub --stand-in --stand-in-recorded`) in
  Chromium at 1280 and 390 px wide: the Rendering line shows after Vision, no horizontal scroll, and
  with a `mismatch` block injected the verdict stayed "Accepted" for a run whose every question was
  answered.
- Full suite on the branch merged with main: see the pull request.

## Not done
- The four checked-in recordings under `docs/run-it/vision/` still name no environment, so live runs
  will show `unknown`. Naming them needs a new recording run, which is model spend and Sean's.
- No run against the deployed service and no workflow dispatched.

## Files
- `expectrail/recorded.py`, `expectrail/runit.py`
- `contracts/run-it-result.v1.schema.json`, `contracts/examples/run-it-result.json`
- `docs/run-it/run-it.js`
- `tools/runit_smoke.py`, `tools/runit_published.py`
- `tests/test_runit_rendering.py`
- `docs/new-work/2026-11-19-run-it-renderer.md`
