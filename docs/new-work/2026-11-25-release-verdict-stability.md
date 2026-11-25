# Count three-repeat verdict stability for the release evaluation (#282)

## What changed

The release evaluation can summarize an in-memory histogram of three verdicts per candidate. Three matching verdicts are stable. Any disagreement counts as unstable. Each candidate with one or more accepts contributes once to the any-accept count. Q1 uses that count for its already selected population of eligible wrong fixes.

Malformed verdict triples and counts are refused. The histogram must add up to the supplied candidate denominator.

## What was run

- On original main, the four new stability tests failed because the aggregation entry point was absent.
- `python3 -m unittest -v tests.test_jit_evaluation_report` passed all 12 tests. The new cases cover all 27 ordered verdict triples, multiple candidates per triple, empty input and malformed or incomplete counts.
- A synthetic majority-accept substitute failed two of the four stability tests.
- `TZ=UTC python3 -m unittest discover -s tests -t .` ran 6,026 tests in 810.180 seconds with zero failures or errors and 81 skips. The rerun confirmed exit status 0 after the first tool invocation reported an inconsistent status.

## Not done

Population selection, the counts artifact, Q2 classification and the release run are separate stages. All input counts in these tests are synthetic.

## Files

- `expectrail/jit/evaluation_report.py` aggregates repeat counts.
- `tests/test_jit_evaluation_report.py` exercises the aggregation and its input validation.
