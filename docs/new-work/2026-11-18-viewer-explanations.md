# The evidence viewer shows a written explanation only when every word matches the record (#264)

## What changed
- `expectrail.explanation/v1` is a new contract: `contracts/explanation.v1.schema.json`, the example `contracts/examples/explanation.v1.json`, and the format is registered by its schema file.
- `expectrail/explanation.py` holds three parts:
  - `prompt` asks a model the question.
  - `from_answer` is the writer. Expectrail fills in the decision and `recordSha256`; the model never does.
  - `read` and `check` are the reader. `check` fails closed. Each of these withholds the explanation: a different decision or record; an id that is not in the record; a stated verdict that is not the record's; non-ASCII text; a number not in the cited evidence, or written as a word; any word that is not neutral, not the name of the cited evidence, and not in the verifier's own wording of that evidence (an allow-list, after the merge guard's first review showed that a list of words to refuse can always be got around); a passing word unless every stated verdict after the change is pass; a failing word without a stated failure after the change; a decision word that is not the decision; a negation; a word of certainty; a scope word ("only", "also", "other", "than"); "same" unless every cited verdict is equal before and after, and "difference" or "changed" unless one differs (after the merge guard's second review). The list of neutral words holds only words that cannot carry a claim, and a test pins it.
  - Under each point, the viewer writes the cited verdicts itself from the record.
- `expectrail/viewer.py` adds an Explanation section when there is one. It shows who wrote it, says it decides nothing, and turns each finding id into a button to that finding. A withheld explanation shows the reasons and none of its text. `write_job` reads `<job>/explanation.json`, so `expectrail report` shows it. The offline `evidence.html` carries the same section. State, decision, reasons and exit code are unchanged.
- `docs/viewer.md` explains it.

## What was run
- `python3 -m unittest tests.test_explanation tests.test_viewer tests.test_contracts`: 53 tests, OK.
- First round: nine mutations of `check` were each caught by `tests.test_explanation`.
- Second round, after the merge guard's review: the guard's six probes (a) to (f) and five accept-side descriptions of a failure are tests, and all are withheld. Ten mutations were each caught: the allow-list, after-only passing words, failing words, negation, spec names split into words, decision words, numbers, ASCII and the digest.
- Second round, full suite on the branch merged with main at edfd70b: 5,155 tests, 1 failure, 65 skipped. The failure is `tests.test_package.InstalledTest.test_installed_sample_checks_new_capture_without_optional_packages`. It fails on main edfd70b alone too: I ran that one test on a clean checkout of main and it failed. It came in with #589, which the guard is reverting in #633.
- I opened the viewer in Chromium (Playwright) for the example record with the example explanation, at 1280 and 390 wide. There was no horizontal scroll and no console error. Clicking a finding id in the explanation opened the inspector at that finding. In the second round I looked again at both widths: each point now shows its verdict line from the record.
- Third round, after the merge guard's second review: the guard's cases (g) to (l) and the accept-side mirror (a check failing before and passing after, described as "the same") are tests, and all are withheld. A test pins `NEUTRAL` and checks it against a list of comparison, scope, quantity and order words. Five mutations were each caught: the "same" rule, the "difference" rule, the scope rule, adding "same" and "only" back to `NEUTRAL`, and letting the verifier's wording bring them in. The example's second point no longer says "the same check"; it names the spec.
- Third round, full suite on the branch merged with main at 90ace87: 5,162 tests, OK, 63 skipped.
- Full suite on the branch from main at 430833a: 5,116 tests, OK, 63 skipped. The first full run found the module missing from the wheel (`tests.test_package`) and the new id pattern missing a sample (`tests.test_schema_pattern`). Both are fixed in this change.

## Not done
- The check works on words. It is not a proof that no allowed sentence can mislead; the record's verdicts are printed under every point for that reason.
- No live model is asked for an explanation. That needs a budget and a recording run, both Sean's.
- The two-minute trial with a person new to Expectrail (Sean's).

## Files
- contracts/explanation.v1.schema.json, contracts/examples/explanation.v1.json (main now finds the format from the schema file, so `expectrail/contracts.py` is unchanged)
- expectrail/explanation.py, expectrail/viewer.py
- tests/test_explanation.py, tests/fixtures/explanation/reject-answer.json, tests/test_schema_pattern.py (one sample added)
- setup.py (the module is in the wheel)
- docs/viewer.md, docs/new-work/2026-11-18-viewer-explanations.md
