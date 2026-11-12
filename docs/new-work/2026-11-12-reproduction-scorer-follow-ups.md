# The reproduction scorer reads the bug build's runs, and its free text is one line (#285)

## What changed
The merge guard's review of #311 left three gaps in the scorer. None could raise the rate; all three
are closed here.

1. **Free text from a record could add lines to the page.** A budget reason was copied into
   `evidence` as it was, and the page replaced `|` only, so a reason with a newline put its own
   lines into the page that goes to the step summary (the reviewer's case:
   `OUT_OF_BUDGET\n| injected | row |\n# heading`). Fixed as a class, in three places:
   - the writer makes `why` and `evidence` one line where a row is finished, whatever set them
     (`score.one_line`: every run of whitespace, control or format characters becomes one space),
     and `source` the same way;
   - the schema refuses a control character in `why`, `evidence` and `source`, and the reader
     refuses any of the three that is not exactly as the writer writes it;
   - the page writes each as a code span, where GitHub renders no link, image, HTML or mention, and
     a backtick inside cannot close it.
2. **"Failed on the bug build 3 of 3" was read from a list, not from runs.** The `jit-run` record
   keeps the bug build's runs only for a catch. A reproducing check is always a catch (it failed
   3 of 3 on the candidate), so the scorer now counts a check only when its catch entry is there,
   has the same candidate runs as its validity row, and shows three fails on the bug build. A
   record that lists the bug build as failed for such a check and has no catch that shows it gives
   no result. The `flaky` reason of the second kind still rests on the list, since that check is no
   catch and the record keeps no runs for it; the module, the schema and the bench's page say so.
3. **What the reader cannot check** is now in `docs/contracts.md`: a score record holds no runs, so
   a row changed to `reproduced` with the totals redone reads as well as a true one. What ties a
   row to runs is its `recordSha256`; to trust a rate, score the run's records again.

4. **After the merge guard's review of #322: what the writer writes, the reader accepts.**
   `one_line` cut after it collapsed, so a cut could end on a space, and the reader (which holds a
   text to `text == one_line(text)`) refused the record the writer had just made: a `--source` of
   199 characters, a space and more gave an error where main gives a record, and so did a
   disagreement that names a check id of 193 or 199 characters. `one_line` now cuts and then
   strips, so running it again changes nothing. An empty text in a code span gives a dash, not two
   backticks. One test was renamed to say what it reads (the fixture's catch, not the pipeline's).

## What was run
- `python3 -m unittest tests.test_repro_score`: 72 tests, OK (61 before). New: the reviewer's case
  and 16 kinds of line break, control and format character in a budget reason and in another
  failure's reason; markdown in a reason; the source; ten ways for the reader to be handed free
  text that is not one line; a page made from an edited record; and ten records that name the bug
  build as failed without a catch that shows three fails there (no entry, another check's, missing
  runs, two of three, one run, a pass, a fourth run, an error, other candidate runs, two entries).
  With the one-line step taken out, 17 of these tests fail; with the catch check taken out, 12.
- The one whole run of the real pipeline on the simulated game (already in that file) still scores
  the air-jump case as reproduced: the record the job writes has the catch the scorer now reads.
- The full suite, `python3 -m unittest discover -s tests -t .`, on the branch, which is cut from
  current main (`b76d90c`): 2,039 tests, OK, 22 skipped.

- After the review of #322: `python3 -m unittest tests.test_repro_score`: 77 tests, OK. New: running
  `one_line` twice gives the same text for a gap at each of six places around the cut, for 200 and
  300; a source cut on a space reads back; a check id of 185 to 204 characters in a disagreement
  gives no result and a record the reader accepts; long reasons in each place one is written; the
  empty code span. With `.rstrip()` taken out again, three of the new tests fail (15 cases); put
  back, the file passes. The full suite on the branch merged with main is in the pull request.

## Not done
- No live run. The scorer has still read no record from one, and there is still no reproduction
  rate.
- One assertion in an existing test changed: the page now writes the source as a code span, so
  `From run 123 456.` became ``From `run 123 456`.`` No test was removed, skipped or loosened.
- The test fixture's `jit-run` records now carry catch entries, as the pipeline writes them; before,
  they had none and the scorer did not look.

## Files
- `expectrail/repro/score.py`, `contracts/repro-score.v1.schema.json`
- `tests/test_repro_score.py`
- `docs/contracts.md`, `bench/jit/public/README.md`
