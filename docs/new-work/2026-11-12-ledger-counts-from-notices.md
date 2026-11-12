# A count a ledger row quotes is tied to the notices its run published, and counted again (#244)

## What changed
- **The ledger's contract** (`expectrail.capabilities/v1`): a run's evidence may carry `counts`. Each
  entry names words in `shows` (`says`, for example "8 of 8"), the numbers (`n`, `of`), the notices
  by title (`titled`, `*` for any text; `not` for titles left out) and one of two ways of counting:
  - `count`: `of` is how many notices have the title, `n` is how many of them have that text as one
    whole field of their message. The fields are what lies between semicolons.
  - `reads`: exactly one notice has the title, and one of its fields is that text with `{n}` and
    `{of}` filled in.
  Nothing is matched as a pattern inside a message. A field is equal or it is not.
- **`python3 -m expectrail.capabilities recheck`** reads the notices of the jobs of every run whose
  evidence has `counts` (`repos/.../check-runs/<job>/annotations`, level `notice`) and counts again.
  It reports a count that differs, and says "cannot tell" when no notice has the title, when the
  same notice is there twice, or when a job's notices cannot be read. A notice from a job that did
  not end in success is a problem. Skipped jobs are not asked about. It still reads no logs and no
  artifacts. The bench jobs already publish their public counts as notices, so no workflow changed.
- **Without the network**, `expectrail.capabilities.problems` (the test suite and `check`) fails when
  an entry's words are not in `shows`, when the numbers are not the ones the words give, when `n` is
  more than `of`, when the same words are tied twice, and when a field has a semicolon in it.
- **The ledger**: 16 entries on 9 pieces of evidence, in the rows `godot-verify`, `sam-observer`,
  `glimmer-observer`, `web-checkout`, `fix-loop` and `review-change`. Of the 17 counts written as
  "N of M" beside a run link, 11 are now tied; the other 5 entries tie words without a number in
  them ("no false alarm", "each on the first attempt", "repair demonstrated").
- **`docs/capabilities.md`** marks tied evidence with "Counted from the run's notices" and says how many
  of the quoted counts are tied, and that any other is as its writer wrote it.
- **`tests/capability_notices.json`**: the 55 notices those counts rest on, as GitHub's API gave them
  on November 12. The suite counts the committed ledger against them, and checks that changing any
  entry's `n` or `of` by one is caught.

## What was run
- `python3 -m expectrail.capabilities recheck`, November 12, against GitHub: `24 runs read, 0 problems`.
  Seven of the runs had their notices read (37, 45, 17, 55, 125, 23 and 23 notices). Every tied count
  is the count the notices give.
- One wrong count on purpose, against GitHub: `sam-observer`'s "4 of 8" recorded as 5 gave
  `'4 of 8': 5 of 8 is recorded and the run's notices give 4 of 8`.
- `python3 -m expectrail.capabilities check`: no problems.
- `python3 -m unittest discover -s tests -t .` on the branch, which is on main at fdd88c3:
  2,020 tests, 17 skipped, OK. This machine has no bubblewrap, which is where the skips above the
  usual 10 come from; I did not list them one by one.
- CI on the pull request: not run when this was written.

## Not done
- Six quoted counts are not tied. Blind set 3 (run 42942805407: "0 of 8", "3 of 8", "0 of 8") publishes,
  by its workflow file, one notice per candidate with commas between its parts, not semicolons. The three
  discovery runs (41248745687, 41319184209, 41238187197) publish their numbers as JSON inside the
  notice. Tying those needs a third way of counting; I did not read those runs' notices beyond the
  development run's (41238187197) to see their shape.
- Numbers that are not "N of M" are not tied or counted as quoted: "$3.67 for 34 candidates",
  "19 requests, 5.5 s", "100,962 ms".
- Counts quoted from a record file (`kind: record`) rather than a run are not checked.
- `recheck` is still not run by CI. It needs `permissions: actions: read` (and `checks: read` for the
  notices), which only Sean may add to a workflow.
- The saved notices are a copy. `recheck` is what compares the ledger with GitHub; the suite compares
  it with the copy.
- A person's read of each row's status and grade. The per-phase wall time still comes from one run on
  a pull request, not on main.

## Files
`expectrail/capability_runs.py`, `expectrail/capabilities.py`, `contracts/capabilities.v1.schema.json`,
`contracts/examples/capabilities.json`, `docs/capabilities.json`, `docs/capabilities.md`,
`docs/contracts.md`, `tests/test_capability_counts.py`, `tests/test_capability_runs.py`,
`tests/capability_notices.json`
