# Show what the run tested beside its verdict (#264)

## What changed

Newly generated viewers put “Not tested” directly below the decision. When no findings record is available, the viewer says so. It can only describe which checks ran from evidence that exists.

The vision summary distinguishes a question the gate never asked from a question that returned no usable answer. It attributes skipped questions to engine failures only when each of those checks actually failed in the engine record. Previously, a clean engine pass with vision unavailable could produce a page that said the engine had already failed the check.

## What was run

- Before the change, the new tests reported five failures, including both recorded samples.
- `python3 -m unittest tests.test_viewer_timeline tests.test_viewer_measurements` passed all 23 tests. The sample test checks the original job and findings digests and the individual PNG digests.
- In Chromium over local HTTP at 375 and 1280 px, the scope heading was in the first viewport on fresh exports of both recorded samples with scripts on and off. Both verdicts were visible. The reject sample showed the recorded failure at frame 5 and the pair of captured images.
- The public export scan checked 1,329 files with zero warnings or errors.
- `python3 -m unittest discover -s tests -t .` ran 5,911 tests in 723.875 s and passed with 78 skips.

## Not done

Sean or Timothy still needs to time someone who has never seen the run. Start them at the published reject sample, ask them to find the failed relation and the command to reproduce it, and record the elapsed time and both answers on #264. A browser check cannot supply that result. The historical downloads on the site retain their original layout. The reject file is 7.4 MiB and updating it requires a prior reviewed exemption under the 256 KiB docs budget.

## Files

- `expectrail/viewer.py`
- `tests/test_viewer_timeline.py`
- `docs/new-work/2026-11-21-viewer-test-limits.md`
