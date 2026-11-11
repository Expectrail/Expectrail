# The ledger's runs can be read again from GitHub, and what #301's review left is fixed (#244)

## What changed
- **`python3 -m expectrail.capabilities recheck`** (`expectrail/capability_runs.py`) asks GitHub again
  about every CI run the capability ledger cites. It fails when a run's conclusion is not the one
  recorded, when a job the evidence rests on is missing or did not end in success, when a wall time's
  step is missing, failed or lasted a different time than recorded, and when a run cannot be read
  ("cannot tell" is a problem, never a pass). It reads conclusions, jobs and steps through `gh api`, never
  logs or artifacts. Until now the recorded conclusion was read once, when the row was written.
- **The ledger's contract** (`expectrail.capabilities/v1`): a run's evidence may carry `jobs`, the names
  of the jobs it rests on. Ten pieces of evidence that named a job in words now list it. A test fails
  when the text says "job x" and `jobs` does not have it.
- **`docs/unity.md`** rested its calibration table on runs 17 and 18, which ended in failure. It now
  rests on runs 19 and 23, which ended in success and print the same line in all four replay jobs, and
  says plainly what happened in 17 and 18. The ledger's Unity row says the same.
- **`agents.verifier.verify`**: no fault while writing `timing.json`, or while clearing up after one,
  can raise once `verification.json` is written. Before, a second `OSError` in the handler escaped
  (seen with `timing.json` a folder). A timing that is written removes an earlier run's
  `timing-error.txt`.
- **`expectrail.timing`** and the ledger refuse `NaN` and `Infinity`. JSON Schema's `number` accepts
  them and every comparison with `NaN` is false, so the sum checks passed on one.

## What was run
- `python3 -m expectrail.capabilities recheck`, November 11, against GitHub: `23 runs read, 0 problems`.
  Every recorded conclusion is the one GitHub gives (22 success, 1 failure: the Cocos trial, recorded as
  a failure), every job named ended in success, and the two wall times agree with their steps: 29 s
  recorded and the step lasted 29 s (run 42934646223); 33.1 s recorded inside a step that lasted 34 s
  (run 43081720384).
- The Unity calibration line, read from the job logs of runs 42758583740 and 42877487075 (both
  `success`; jobs `build`, `replay (a)`, `replay (b)`, `cross-runner` all `success`): the same line in
  all four replay jobs, and each number in the table of `docs/unity.md` is in it. Runs 42754753371 and
  42758198963: both `failure`; in each, one replay job failed at "Install a virtual display, software
  OpenGL and the player's libraries" and `cross-runner` failed; the other replay job ended in success
  and printed the line.
- `python3 -m unittest discover -s tests -t .` on the branch, which is main at 3d66fb4 plus this change:
  1,756 tests, 10 skipped, OK.
- CI on the pull request: not run when this was written.

## Not done
- `recheck` is not run by CI. It needs a token that can read Actions runs, and adding that permission to
  a workflow is a person's change.
- A count a row quotes ("8 of 8 held-out bugs caught") is still not checked against what its run
  printed. `recheck` shows the run and its jobs ended as recorded, nothing more. The runs of blind and
  held-out sets print private material, so their logs were not read.
- A person's read of each row's status and grade.
- The ledger's per-phase wall time still comes from one run on a pull request, not on main.

## Files
`expectrail/capability_runs.py`, `expectrail/capabilities.py`, `expectrail/timing.py`,
`agents/verifier.py`, `contracts/capabilities.v1.schema.json`, `contracts/examples/capabilities.json`,
`docs/capabilities.json`, `docs/capabilities.md`, `docs/unity.md`, `docs/contracts.md`,
`tests/test_capability_runs.py`, `tests/test_timing.py`, `tests/test_capabilities.py`
