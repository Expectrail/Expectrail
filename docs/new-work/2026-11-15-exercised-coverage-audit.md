# Audit the five exercised-coverage cases (#256)

## What changed

This audit records how main at `7ed6106a1ef49e990282979963d950b0f8bc86fb` meets the five cases in #256. All five already had tests. The patch adds this work log only.

All five gate tests below are in `tests.test_exercised_coverage.CoverageGateTest` on main. The publisher test is `tests.test_ci_gate.HeadChecksTest.test_clearance_accept_only_and_interrupted_runs`.

| Case | Existing test on main | What ran | Decision | Expectrail clearance |
| --- | --- | --- | --- | --- |
| Empty suite | `test_empty_suite_needs_review` | Zero checks ran. | needs-review | failure |
| Required route skipped | `test_required_route_skipped_blocks_other_passing_checks` | The selected route passed. A second route required by the spec was missing. | needs-review | failure |
| Window truncated to one frame | `test_one_observed_frame_cannot_pass_even_with_explicit_minimum_one` | The engine observations covered one of 120 required window frames. | needs-review | failure |
| Required observer disabled | `test_disabled_required_observer_blocks_accept` | The rule required both observers. No visual observer was available. | needs-review | failure |
| Checkpoint never reached | `test_checkpoint_never_reached_blocks_accept_under_both_rules` | The player never entered the declared region. The test ran under both observer rules. | needs-review | failure |

## What was run

- `python3 -m unittest -v tests.test_exercised_coverage tests.test_ci_gate.HeadChecksTest.test_clearance_accept_only_and_interrupted_runs tests.test_runit.RecordedTest.test_recorded_answers_give_the_samples_their_decisions_and_ask_no_model` ran 28 tests, all OK.
- The offline audit read each case's saved findings and passed the decision to the real check publisher with an in-memory GitHub API. In six judgements across the five cases, each decision was needs-review and each clearance conclusion was failure. The simulated capture succeeded and was current.
- Each gate or evaluator test went red when its relevant rule was omitted in memory. The five clearance cases also went red when the publisher's accept-only condition was omitted. The checkpoint case ran twice. The handover contains the commands, scripts and red output.

- `python3 -m unittest discover -s tests -t .` — The full suite ran 3,738 tests before and 3,738 after. Both runs ended OK with 47 skips and zero failures or errors.

The smoke route was captured once per game with pinned Godot and Bubblewrap required in a Linux VM with no network device. The bug patch was applied to a disposable copy. Both the unchanged base checkout and the proposed tree independently checked the route, game trees, traces and frame digests, then judged the same captures under the two-observer rule using only the published Run it vision answers. Each capture contained 240 physics ticks and 120 frames. On clean, engine and vision both passed. On the buggy candidate, the engine failed and the gate recorded vision as `not-asked`.

| Bundled build | Before | After | Checks | Passed | Failed | Needs review |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| clean | accept | accept | 1 | 1 | 0 | 0 |
| fall-through-bug | reject | reject | 1 | 0 | 1 | 0 |

## Not done

No workflow was dispatched and no live model was called. The clearance tests observed the publisher's outgoing requests through an in-memory API.

## Files

- `docs/new-work/2026-11-15-exercised-coverage-audit.md`
