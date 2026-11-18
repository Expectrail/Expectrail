# The evidence viewer shows a written explanation only when it cannot contradict the decision (#264)

## What changed
- `expectrail.explanation/v1` is a new contract: `contracts/explanation.v1.schema.json`, the example `contracts/examples/explanation.v1.json`, and the format registered in `expectrail/contracts.py`.
- `expectrail/explanation.py` holds three parts:
  - `prompt` asks a model the question.
  - `from_answer` is the writer. Expectrail fills in the decision and `recordSha256`; the model never does.
  - `read` and `check` are the reader. `check` fails closed: a different decision or record, an id that is not in the record, a stated verdict that is not the record's, non-ASCII text, a number not in the cited evidence (or written as a word), a verdict word with no stated verdict, a decision word that does not match the decision, a negated verdict, or a word of certainty all withhold the explanation.
- `expectrail/viewer.py` adds an Explanation section when there is one. It shows who wrote it, says it decides nothing, and turns each finding id into a button to that finding. A withheld explanation shows the reasons and none of its text. `write_job` reads `<job>/explanation.json`, so `expectrail report` shows it. The offline `evidence.html` carries the same section. State, decision, reasons and exit code are unchanged.
- `docs/viewer.md` explains it.

## What was run
- `python3 -m unittest tests.test_explanation tests.test_viewer tests.test_contracts`: 53 tests, OK.
- Nine mutations of `check` were each caught by `tests.test_explanation`: the ASCII, unknown-id, stated-verdict, number, negation, certainty, decision-word, digest and record-decision rules.
- I opened the viewer in Chromium (Playwright) for the example record with the example explanation, at 1280 and 390 wide. There was no horizontal scroll and no console error. Clicking a finding id in the explanation opened the inspector at that finding.
- Full suite: see the pull request.

## Not done
- No live model is asked for an explanation. That needs a budget and a recording run, both Sean's.
- The two-minute trial with a person new to Expectrail (Sean's).

## Files
- contracts/explanation.v1.schema.json, contracts/examples/explanation.v1.json, expectrail/contracts.py
- expectrail/explanation.py, expectrail/viewer.py
- tests/test_explanation.py, tests/fixtures/explanation/reject-answer.json
- docs/viewer.md, docs/new-work/2026-11-18-viewer-explanations.md
