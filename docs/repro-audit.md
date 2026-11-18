# Reproduction audit (#285)

Audited main: `d36c8063449afe6c4113c74d0ff39e926b861b6c` (November 16, 2026).
Public bench only. No model was called or workflow dispatched for this audit.
**#285 remains open.** The baseline is measured; later steps and reproduction with the candidate
withheld still need hosted measurements. The local counter experiment below is a signal test,
not a new reproduction rate.

## Completion criteria and main's evidence

The cases include the six Build items and every condition in [#285's Done when](https://github.com/Expectrail/Expectrail/issues/285).
Tests name behavior; a stand-in test is not presented as a live model measurement.

| Case | Evidence on audited main | Result / missing |
| --- | --- | --- |
| At least 20 public defects, player reports, multiple families | `bench/jit/public/defects.json`: 24 defects, nine families, 20 authored fixtures and four known reported defects. `tests/test_repro_bench.py::test_at_least_twenty_public_defects_across_the_families_each_with_a_patch_and_a_report` | Implemented. Public fixtures are not a held-out sample. |
| Baseline dispatched on main before later offers | [Run 43465090517](https://github.com/Expectrail/Expectrail/actions/runs/43465090517), commit `1e6055004dccfd90bc0f4d132823784838718627`, offer `baseline`, candidate shown. `tests/test_jit_offer.py::test_the_system_prompts_are_byte_for_byte_those_of_main_before_the_setting` and `test_a_user_prompt_is_byte_for_byte_that_of_main_before_the_setting` freeze the baseline | Measured; original score and all 24 input records recovered in this change. |
| Every miss classified in the fixed vocabulary | Same run's score plus `bench/jit/public/hand-reasons.json`; `expectrail/repro/breakdown.py`. `tests/test_repro_score.py::test_the_two_reasons_no_record_can_show_are_never_assigned` protects the scorer/hand distinction | Published below. Four of seven classifications need public hand findings; the scorer alone leaves those four undetermined. |
| Bounded routes from report and changed code, using discovery compiler | `expectrail/repro/reach.py`, `expectrail/jit/offer.py`, `expectrail/jit/diff_map.py`; `tests/test_repro_reach.py::test_two_probes_for_each_missing_pair_bounded_in_count_and_time`, `test_the_defect_no_library_probe_reaches_shows_on_a_reach_probe`; `visibility-reach.json` | Eight action-pair routes, bounded at 160 ticks, report orders them; diff map selects families. Not a general planner for arbitrary reach. Menu probes exist separately but no generator offer included their menu action at this audit. Since November 18 the `signals-reach-evidence-menu` offer adds them, with the menu action from the reviewed profile (`tests/test_jit_offer_menu.py`); not yet run live. |
| New trace signals needed by misses, tested and documented | `coins_collected` and two player screen ranges; `tests/test_trace_camera_coins.py`; public `visibility.json` and evidence records; `docs/jit.md` | Implemented for the two camera misses and coin-stays. No live after-step rate. This change adds a further UI reading and comparison; see below. |
| Proposer sees a bounded buggy-versus-clean summary on routes | `expectrail/repro/evidence.py`, `expectrail/jit/offer.py::attach_evidence`; `tests/test_repro_evidence.py::test_signals_come_from_the_same_replays_as_the_fields`, `test_an_unstable_field_is_left_out_and_the_same_replay_twice_gives_nothing`; `tests/test_jit_offer_evidence.py`; committed `evidence-*.json` and `menu-evidence-*.json` in the public bench | Implemented for measured library/reach probes, at most six shown. Model-invented routes are not premeasured. Menu evidence cannot be attached as usable generator probes yet. No live quality/rate measurement. |
| Reproduce from report and base alone; candidate-shaped checks do not qualify for #271 | `--withhold-candidate`; `tests/test_jit_withheld.py::test_two_different_fixes_of_one_report_give_the_model_the_same_prompt`, `test_only_checks_proposed_blind_are_from_the_base_alone`; `tests/test_repro_score_withheld.py::test_a_record_of_the_other_setting_never_raises_the_rate`; `run.from_base_alone` returns no qualifying checks for shown records | Implemented and tested with stand-ins. Baseline candidate was shown: it proves no candidate-withheld rate and qualifies no checks for that #271 condition. Hosted withheld measurement missing. (The test's name describes withholding the candidate; no private content is used.) |
| Reproduction rate after each step, with a run | `docs/jit.md` and public bench README cite only run 43465090517 for a live reproduction rate. Public API lists zero JIT runs at the audited main SHA: `docs/repro-current-main-runs.json` | Missing for signals/reach, evidence, and candidate withheld. No current-code live rate is recorded. Sender-cap workflow prerequisite below also blocks a dispatch. |
| At least 70% of trace-visible public defects reproduced; no kept clean failure | Baseline score: 16/19 trace-visible reproduced (84.21%); 91 kept checks each pass clean 3/3. `tests/test_repro_score.py::test_two_of_three_on_the_bug_build_is_not_a_reproduction`, `test_a_record_whose_valid_flag_its_own_runs_contradict` | Baseline meets the trace-visible target. This does not establish the target for current offers or for candidate-withheld checks. Zero clean failures among the 91 kept checks is the keep rule, not an independent false-reject sample. |
| Spend per defect under existing $2 cap, reported | Same run: total $2.0492 across 24 defects; maximum $0.1722 (`slow-left`), 0/24 over $2. `expectrail/jit/run.py::Spend`; `tests/test_repro_score.py::test_out_of_budget_is_a_miss_with_that_reason` | Baseline measured using recorded price assumptions, not a vendor invoice. Later-step spend missing. Premeasurement/job overhead is outside the assessed per-defect ledger. |

## Published miss breakdown: one baseline, not a new rate

Source for every count in this section: [original hosted score](../bench/jit/recordings/public-43465090517/repro-score/repro-score.json),
[24 original run records](../bench/jit/recordings/public-43465090517/repro/), and
[public hand findings](../bench/jit/public/hand-reasons.json). Run:
[43465090517](https://github.com/Expectrail/Expectrail/actions/runs/43465090517).
`source.json` records artifact ID, original archive digest and every recovered file's digest.
The downloaded archive matches GitHub's SHA-256. Recomputing the score with today's reader is
byte-identical to the downloaded score; the hand findings never change the rate.

- All public defects: **17/24 reproduced (70.83%)**, seven misses, zero no-result.
- Authored/untuned subset: **13/20 (65%)**; trace-visible subset: **16/19 (84.21%)**.
- A reproduction requires a kept check passing clean 3/3 and failing the bug build 3/3.
  This baseline shows the candidate to the proposer; its no-fix candidate is only a README comment.

| Fixed vocabulary | Count / seven misses | Count / 24 defects | Public defects | Basis in run 43465090517 |
| --- | --- | --- | --- | --- |
| route never reaches (`route-never-reaches`) | 2/7 | 2/24 | `coin-counts-twice`, `coin-counter-stuck` | Scorer: undetermined. Public hand findings: counter only opens in pause menu; baseline action catalog cannot open it. Later committed menu experiments expose both on screen. |
| no trace signal (`no-signal`) | 2/7 | 2/24 | `camera-stops-right`, `camera-cut-top` | Scorer: view differs but baseline offers no camera signal. Later screen-range signals already address this representation gap. |
| probe language cannot express it (`probe-language`) | 2/7 | 2/24 | `enemy-walks-backwards`, `bullet-behind-scenery` | Scorer: undetermined. Public hand findings and screen records show screen-only changes. Baseline trace predicates cannot read orientation/layering. An object-position observer alone does not establish either defect. |
| wrong predicate (`wrong-predicate`) | 1/7 | 1/24 | `coin-stays` | Scorer sees a differing signal, but no kept proposed check reproduces it. Published evidence dates meaningful coin divergence at tick 174; incidental enemy jitter is not coin reproduction. `coins_collected` now exposes the intended difference. |
| flaky (`flaky`) | 0/7 | 0/24 | none | No miss receives this classification in the score. |
| budget (`budget`) | 0/7 | 0/24 | none | No miss receives this classification; 0/24 records exceed their cap. |

The scorer's original totals remain **two no-signal, one wrong-predicate, four undetermined**.
The published hand file supplies the other two categories, not a model-generated causal diagnosis.
Its statements are dated before the live baseline. Later menu evidence supersedes its historical
“no run has shown” wording without rewriting that historical evidence.

Reproduce the published score and breakdown offline:

```sh
python3 -m expectrail.repro score \
  --records bench/jit/recordings/public-43465090517/repro \
  --out runs/repro-baseline-recomputed \
  --source 'jit.yml run 43465090517, attempt 1, at 1e6055004dccfd90bc0f4d132823784838718627'
python3 -m expectrail.repro breakdown \
  --score bench/jit/recordings/public-43465090517/repro-score/repro-score.json
```

## Offline step: make menu-counter state measurable and expressible

Three categories tie at two of seven baseline misses. Reach pairs and the camera/coin signals
already landed; repeating those steps would duplicate main. The recorded menu experiments
(`menu-evidence-coin-counts-twice.json`, `menu-evidence-coin-counter-stuck.json`) expose the two
counter bugs on two of three menu routes each, with no difference in the old trace. That points
to a missing UI trace reading after the separate menu reach experiment.

This change records bounded **integer-only Label state**, `uiIntegers`, from visible Label nodes
in the current scene. Recording is opt-in per evaluated trace spec: `ui_integer_at_end`
in a relation or either side of `signal_compare` requests it through the existing harness
value arguments. No requesting spec means no scene scan and no `uiIntegers` key at all. An offer
or a general measurement run does not request it. JIT and discovery pass the applicable specs
for each replay; candidate fingerprints and reproduction runs use the same request. At most 32 values, bounded magnitude, at most 4096 visited/queued nodes;
overflow means unknown (`null`), never a truncated collection. It records no free-form label text.
Hidden labels are excluded. `ui_integer_at_end` reads a value only when exactly one such label
exists at the end of the observed window; absent, empty, multiple (even equal), overflowed and
older records all give no reading. It does not carry an earlier value forward.

The closed `signal_compare` operation compares two signals in **the same route/window**. For the
reported coin counter, compare the integer with `coins_collected` using equality and zero tolerance.
That expresses the expectation without hand-picking a count of five. An absent signal is
`insufficient_observation`, never a pass. Checks remain proposals with `model_prior` authority;
the existing three-replay keep rule still decides whether to keep them.

Both additions are offered only under `signals-reach-evidence` and
`signals-reach-evidence-pixel`. Baseline and `signals-reach` retain their existing prompts and
probe library; the parser and saved-proposal reader refuse the new operation/signal there.
Old traces, episodes and trace specs remain readable. The raw trace, episode and trace-spec
schemas, handwritten examples, recorder and readers change together.

Pinned Godot 4.7.2, one existing `hold-right-then-toggle-pause` route, four local headless replays:
clean A **5**, clean B **5**, `coin-counter-stuck` **0**, `coin-counts-twice` **10**. The engine test
records that result; pure evaluator tests show equality passes on clean and fails for both defects,
and unknown does not pass. These are **signal/interpreter tests, not a model reproduction rate**.
The original-code red run includes the real-engine test failing with no UI readings.

Limitations remain explicit: this reads the engine's Label state, not drawn pixels, occlusion or
clipping; multiple numeric labels, formatted text, RichTextLabel and custom-drawn counters are not
supported. The generator still needs a trusted way to offer/compile menu actions before these two
routes can participate in an automatic report-only run. No live improvement is claimed for any
of the seven misses. The orientation/layering observer gap remains separate.

## Sean's next measurement, after this change is on main

The public API query is committed in `docs/repro-current-main-runs.json`: zero runs of `jit.yml`
on main at the audited SHA. The connected run-list tool filters to pull-request events; this audit
used GitHub's public read-only API to check main instead. No dispatch occurred.

**A workflow prerequisite is currently missing.** `spark_intent` uses
`spec_writer.http_transport`, whose live sender now requires `EXPECTRAIL_SPEC_USD_CAP`.
`jit.yml` does not export that cap to either model job. A local preflight with the HTTP opener
mocked and environment patched/restored refuses with “no spend cap for spec”; zero HTTP calls.
Dispatching today would spend measure-job runner time and then refuse before a model request.

Sean must first add the following line to the existing job-level `env:` mappings of **both**
`propose` and `revise` in `.github/workflows/jit.yml`, preserving their other entries:

```yaml
EXPECTRAIL_SPEC_USD_CAP: ${{ needs.plan.outputs.budget }}
```

That is two added env entries, using the selected per-defect budget. Repository/environment
variables alone are not automatically exported to the Python process. This audit makes no
workflow edit; this is Sean's step. The replay jobs read saved proposals and need no live sender.
After that prerequisite and this change are on main, run from an authenticated terminal:

```sh
gh workflow run jit.yml --repo Expectrail/Expectrail --ref main \
  -f mode=repro -f offer=signals-reach-evidence -f candidate=withheld -f budget_usd=2
```

It exercises current report-only trace checks, not menu routes or pixel checks. It can measure the
current automatic path even if counter misses remain. Preserve its `repro-score` artifact, the
per-case `jit-run.json` records and run URL; publish every miss and per-defect spend, even if the
rate is lower. The existing `main-only` environment must be available to Sean.

Code-derived plan: **24 defects × $2 = $48 assessed budget**, at most **48 Muse calls** (one proposal
and at most one revision per defect), at most **30,000 completion tokens reserved per call**,
**zero SAM requests/images** for this non-pixel offer. These are bounds, not a predicted bill.
`run.DEFAULT_PRICES` records assumed Muse prices $1/M input and $4/M output and runner $0.008/min.
The public baseline's $2.0492 is historical, not a forecast. Up-front measure jobs, setup and other
workflow overhead are outside the per-defect assessed cap: evidence measure has a 75-minute
job timeout per defect, so its runner-time allowance alone is 24 × 75 × $0.008 = **$14.40** at that
assumed runner price. No claim that $48 bounds the entire GitHub/vendor bill.

To fill the missing after-step comparisons as well, Sean needs separate runs with the candidate
shown, so they are comparable with the shown baseline:

```sh
gh workflow run jit.yml --repo Expectrail/Expectrail --ref main \
  -f mode=repro -f offer=signals-reach -f candidate=shown -f budget_usd=2
gh workflow run jit.yml --repo Expectrail/Expectrail --ref main \
  -f mode=repro -f offer=signals-reach-evidence -f candidate=shown -f budget_usd=2
```

Each has the same $48 assessed budget and at most 48 Muse calls, with zero SAM images.
The first measure allowance is 24 × 30 × $0.008 = $5.76; the second is $14.40.
All three dispatches together select $144 of assessed budgets, plus overhead; do them only when
Sean is ready to spend. A current combined evidence run cannot retroactively measure the earlier
evidence-only implementation before this UI addition. Exact historical attribution would require
Sean to prepare the chosen public source revision on main and identify its commit in the run.

No outcome from those unrun commands is evidence today. #285 cannot close until current and
stepwise rates/spend are recorded, report-only reproduction is measured, and the remaining reach
and representation limits are resolved or explicitly accepted against the measured target.
