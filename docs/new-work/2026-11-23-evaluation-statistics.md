# Render aggregate release evaluation statistics (#282)

## What changed

`expectrail.jit.evaluation_report` turns an arm's aggregate truth-by-verdict counts into a Markdown
table with row, column and overall denominators. The same module renders rates using exact two-sided
95% Clopper–Pearson intervals and paired comparisons using the two-sided exact McNemar test.
It reports both discordant counts and suppresses rates and tests for strata below ten candidates.
Zero-event rates say how many observations had no events and show both the exact interval and the
rule-of-three estimate.

The functions take supplied counts. A caller can pass the whole stratum size when the rate applies
to a subset of it. For instance, `render_rate(0, 20)` reports none observed in 20 and an exact interval
of 0.00%–16.84%. `render_pair(1, 3, 20)` reports the two discordant counts and (p = 0.625).

The fixed statistical rules come from [the public evaluation protocol](https://github.com/Expectrail/Expectrail/issues/282).

## What was run

The new tests first failed because the module was absent. The focused cases compare the confidence
bounds against closed-form values and direct binomial tails, check hand-counted discordances and
exercise the raw-count limit and invalid input. Every input was synthetic.

- All 63 focused statistics, registration, manifest, work log and linked-path tests passed.
- An independent calculation checked 41 synthetic count pairs against direct binomial tails.
  The maximum absolute error from the target tail probability was 5.3e-15.
- The full `python3 -m unittest discover -s tests -t . -v` suite on `de1ddd6` completed
  6,022 tests with 81 skipped and zero failures.

## Not done

The runner, aggregate counts file, unstable-verdict aggregation, the Q2 population decision for
intentional changes without a contract update, and human thresholds and sign-off remain future work.

## Files

- `expectrail/jit/evaluation_report.py`
- `tests/test_jit_evaluation_report.py`
