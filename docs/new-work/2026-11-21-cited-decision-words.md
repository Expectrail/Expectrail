# Check decision words against every citation (#645)

## What changed

A rejected run could display “The change is accepted” when the cited route was named `accepted`. It could also call a passing check “rejected” when a different check caused the run to reject. The reader now checks the words in a name when used in prose. The full evidence ID still names the check unambiguously. “Accepted” and “rejected” must agree with both the run and every cited after-verdict. The stand-in example records the updated prompt digest.

## What was run

- Six cases reproduced on the previous reader. Four used a route name that carried a claim. Two attributed the run's rejection to a passing check.
- `python3 -m unittest tests.test_explanation` passed 34 tests, including the seven mixed-citation probes from #645, the positive pass and fail examples, and verdict lines copied from the record.
- `python3 -m unittest discover -s tests -t .` ran 5,951 tests in 703.377 s and passed with 78 skips. The strengthened fixture consistency checks also passed on the focused rerun.
- The public export scan checked 1,330 files with zero errors or warnings.

- After rebasing onto main at `88707aa5`, the full suite ran 5,954 tests in 653.265 seconds and passed with 78 skips. The export scan checked 1,334 files with zero errors or warnings. Chromium showed the recorded rejection and withheld the contradictory sentence at 375 and 1280 px with JavaScript disabled.

## Not done

No live model call or human reading trial. The latter belongs to #264.

## Files

- `expectrail/explanation.py`
- `contracts/explanation.v1.schema.json`
- `contracts/examples/explanation.v1.json`
- `docs/viewer.md`
- `tests/test_explanation.py`
- `docs/new-work/2026-11-21-cited-decision-words.md`
