# The `spend` environment: no paid run without Sean's approval

Decision A, Sean, November 16, 2026 (#265).

## Why
Run it holds a GitHub token with Actions write, so it can start its own workflow. GitHub cannot limit
such a token to one workflow: if it leaked, it could start any workflow on `main`, including the
paid ones, and the token acts as its owner. Until now every model key lived in `main-only`, which
only `main` may deploy to but which needs no approval.

## What changed
- A second environment, `spend`, holds the model keys (every `*_API_KEY`) and a copy of
  `HELDOUT_TOKEN`. Like `main-only`, only `main` may deploy to it; unlike `main-only`, every run
  waits for Sean's approval.
- Every job that uses a model key now declares `environment: spend` (38 jobs in 22 workflows).
- Jobs that hold only `HELDOUT_TOKEN` or the judge's signing key stay in `main-only`, so CI, the
  private scan and the pull-request judge run without a click.
- `tests/test_main_only_environment.py` holds it: a model-key job outside `spend` fails, a job in
  `spend` without a model key fails, and no pull request can start a `spend` job.

## What it costs
One approval per paid run, including the scheduled BYO smoke (`byo-smoke.yml`, daily). An unapproved
run waits and spends nothing.

## Setting it up (Sean, in this order)
1. Repository **Settings → Environments → New environment**, name `spend`.
2. **Required reviewers**: tick it and add yourself. Leave "Prevent self-review" off, so you can
   approve runs you start.
3. **Deployment branches and tags**: **Selected branches and tags**, add `main`.
4. **Environment secrets**: add each model key with the same name and value it has in `main-only`
   (GitHub cannot copy a secret's value): `ANTHROPIC_API_KEY`, `BASETEN_API_KEY`, `FIREWORKS_API_KEY`,
   `GEMINI_API_KEY`, `GLIMMER_API_KEY`, `META_API_KEY`, `MODEL_API_KEY`, `OPENAI_API_KEY`,
   `OPENROUTER_API_KEY`, and `HELDOUT_TOKEN`. Add only those that exist in `main-only` today.
5. Merge the pull request that moves the jobs.
6. Delete the model keys (not `HELDOUT_TOKEN`) from `main-only`, so no unapproved job can reach them.
7. Then section D of [run-it-deploy.md](run-it-deploy.md).
