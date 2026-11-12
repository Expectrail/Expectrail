# The ledger counts a run's JSON notices too, and three gaps in the count check are closed (#244)

## What changed
A count a ledger row quotes could be tied to its run's notices in two ways, both for notices whose
message is text in fields. The two blind discovery runs publish one JSON object per build instead, so
their counts were as the row's writer wrote them. There is now a third way, `has`:

- Every notice with the title must be one JSON object. `of` is how many have the members named under
  `where` as given (a value, or a list of values to be one of); `n` is how many of those have the
  members named under `has` as given.
- A member is equal only to a value of its own kind: `true` is not `1`, `1` is not `"1"`.
- A message that is not JSON or not an object, a member there twice at any depth, `NaN`, a notice
  without a named member, or with it as another kind of value: "cannot tell", never a "no". So is a
  `where` that keeps no notice.
- The message is parsed by Python's `json` and nothing is searched as text.

The ledger ties four more entries with it: "4 of 8 defects flagged" and "no healthy build flagged"
for blind set 1 (run 41248745687), "3 of 8" and "no healthy build flagged" for blind set 2 (run
41319184209). 13 of the 17 counts quoted beside a run link are now tied (11 before).

The three gaps the merge guard listed on #244 after #315:

1. An entry whose words hold no number took any `n` and `of`. Such words speak of every notice
   counted, so `n` must be `of`; the check refuses anything else. The three entries of that kind
   already in the ledger are 1 of 1, 10 of 10 and 3 of 3.
2. `reads` took `{n}{of}`, which 1 of 11 and 11 of 1 fill the same. Neither placeholder may now stand
   beside a digit or beside the other (so `{n}0 of {of}` and `1{n} of {of}` are refused too), in the
   schema's pattern and in the check.
3. A notices reader that returned a title or message that is not text, a notice that is not an
   object, or something that is not a list, stopped `recheck` with an exception. Each is now "cannot
   tell" for every count of the run.

## What was run
- `python3 -m expectrail.capabilities recheck` against GitHub: `24 runs read, 0 problems`. The lines
  for the two blind runs read `12 jobs, 22 notices` each.
- `python3 -m expectrail.capabilities check`: exit 0.
- `python3 -m unittest tests.test_capabilities tests.test_capability_counts tests.test_capability_runs`:
  148 tests, OK.
- The full suite, `python3 -m unittest discover -s tests -t .`, on this branch at main 5b2ea66: 2,213 tests,
  26 skipped, OK. The change adds no skip.
- CI on the pull request: not run when this was written.

## Not done
- Four quoted counts are still not tied. Blind set 3 (run 42942805407, three counts): its notices
  are one text field with numbers inside it ("generated complete strong 4 weak 0"), and "caught" is
  "strong is more than 0", which no equal-or-not comparison can say. The development discovery run
  (41238187197, "2 of 8 development bugs"): its notices do not say which builds are the reported
  bugs and which the development bugs, and "found" is a list that is not empty. Both need the jobs
  to publish the count itself, which is a workflow change.
- `recheck` is not run by CI: a job needs `actions: read` and `checks: read`, which only Sean may add.
- A person's read of each row's status and grade.
- The per-phase wall time still comes from one run on a pull request, not on main.

## Files
- `expectrail/capability_runs.py`, `expectrail/capabilities.py`
- `contracts/capabilities.v1.schema.json`, `contracts/examples/capabilities.json`
- `docs/capabilities.json`, `docs/capabilities.md`, `docs/contracts.md`
- `tests/test_capability_counts.py`, `tests/capability_notices.json`
