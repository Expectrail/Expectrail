# The evidence rule says which CI runs do not enforce the limit (#684)

## What changed
`docs/evidence-storage.md` said the per-pull-request limit "refuses an unavailable or ambiguous base
instead of skipping". Since 6f25e19 that is true only for `pull_request`, `push` and other or unnamed
events. For `schedule` and `workflow_dispatch` runs with no comparison base, `base_commit` returns no
base, the repository test skips, and `python3 tools/evidence_storage.py budget` prints "Evidence limit
not applicable: this scheduled or manual run has no pull request base." and exits 0. The doc now
states both cases, and that a scheduled or manual event that does carry a base is still checked.

A new test, `RepositoryEvidenceTest.test_written_rule_states_which_runs_do_not_enforce_the_limit`,
holds the doc to the code: it runs `budget` under a scheduled event with no base, checks that the
exact line it prints is in the doc, and checks that every event in `NO_BASE_EVENTS`, plus
`pull_request` and `push`, is named. The code's behaviour is unchanged.

## What was run
- The new test failed on the old doc (the printed line was not in it), then passed.
- Two mutations, each caught by the new test: changing the line `budget` prints, and dropping
  `workflow_dispatch` from the doc.
- By hand, with an event file `{}`: `GITHUB_EVENT_NAME=push ... budget` printed "Cannot check or move
  evidence: CI event has no comparison base; cannot enforce evidence limit" and exited 1;
  `GITHUB_EVENT_NAME=schedule ... budget` printed the not-applicable line and exited 0.
- `python3 -m unittest tests.test_evidence_storage`: 23 tests, OK.
- The full suite on the branch merged with main: see the pull request.

## Not done
Nothing else on #684. The parent, #566, keeps its pending migrations.

## Files
- `docs/evidence-storage.md`
- `tests/test_evidence_storage.py`
- `docs/new-work/2026-11-20-evidence-limit-exception.md`
