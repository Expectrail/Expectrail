# jit.yml's propose and revise steps set the spec sender's cap, so a live run can send its request (#285)

## What changed
The propose and revise jobs of `.github/workflows/jit.yml` send one Muse Spark request each through
`spec_writer.http_transport`. Since #267 (November 15) that sender holds against
`EXPECTRAIL_SPEC_USD_CAP` and sends nothing when it is unset. Neither step set it, so every live
`repro` or `bench` dispatch would have stopped before its first model request, and `spark_intent`
records that stop as the model being unavailable. #573 found this with a mocked preflight and left it
for Sean.

Both steps now set `EXPECTRAIL_SPEC_USD_CAP: ${{ needs.plan.outputs.budget }}`, the change's
per-defect budget that `--budget-usd` already receives. The line is a plain value in the step's `env`,
beside the model key: no new secret, environment or permission.

`tests/test_jit_workflow_spend_cap.py` reads the workflow, finds every step that runs
`jit.cli propose` or `jit.cli revise`, builds that step's environment from the job's and the step's
`env` with the plan's budget filled in, and sends one request through `intent.spark_intent()` with its
default transport and the network replaced. With the workflow's environment the request is sent and
held once; without the cap nothing is sent and the call ends as `MODEL_UNAVAILABLE: BudgetStop`.

## What was run
- `python3 -m unittest tests.test_jit_workflow_spend_cap` on main's workflow (before the fix):
  2 failures, 2 errors (no cap in either step; the request refused in both). With the fix: 4 tests, OK.
- `python3 -m unittest tests.test_jit_workflow_spend_cap tests.test_jit_candidate_workflow tests.test_main_only_environment`: OK.
- Full suite: see the pull request.
- Nothing was dispatched and nothing was spent.

## Not done
- No live run. The runs Sean is asked for on #285 and #286 are unchanged; this removes the stop they
  would have hit.
- Other workflows in the `spend` environment set no cap for the spec, Muse, Glimmer or triage roles
  either. Whether each reaches a capped sender is not checked here; filed as its own issue.
- `jit-blind.yml` is pinned by a blind registration and was not touched.

## Files
- `.github/workflows/jit.yml`
- `tests/test_jit_workflow_spend_cap.py`
- `docs/new-work/2026-11-18-jit-spec-cap.md`
