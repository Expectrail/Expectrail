# Verification as a job

`expectrail.orchestrator` is the one service that runs a verification, whoever asks: the command
line now, and the MCP tools, the GitHub Action and the site as they move onto it (#250, #252, #254,
#265). It runs the verifier. It never starts a fixer and never uses saved data in place of a run.

```bash
python3 -m expectrail.orchestrator verify --head . --base ../base \
    --game game/platformer --routes 'harness/routes/*.json' --specs agents/specs
python3 -m expectrail.orchestrator status JOB --json
python3 -m expectrail.orchestrator cancel JOB
python3 -m expectrail.orchestrator report JOB
```

`sample` is the quickest way to see it work. It copies the bundled game twice, once as it is and once
with the seeded fall-through bug, and runs three real verifications with no model key: the game as
it is (accept), the change that breaks it (reject) and the change that repairs it (accept). It exits
0 only when all three decide that way, and CI runs it on every pull request (`seeded-bugs`).

```bash
python3 -m expectrail.orchestrator sample
```

Exit code: 0 accept, 1 reject, 2 needs review, 3 the job failed (no result), 4 cancelled, 5 the
command could not be carried out. Jobs are kept under `--jobs-root` (default `$EXPECTRAIL_JOBS`,
else `runs/jobs`).

## The request and the job

| Record | What it is | Schema |
| --- | --- | --- |
| `expectrail.verify-request/v1` | What to verify: the adapter, the game folder, routes and specs, a checkout of the head and of the base, the execution class, the time limit, an idempotency key | [`verify-request.v1.schema.json`](../contracts/verify-request.v1.schema.json) |
| `expectrail.verify-job/v1` | A job's status: phase, decision, reasons, diagnostics, the input digests, the worker and its lease | [`verify-job.v1.schema.json`](../contracts/verify-job.v1.schema.json) |

A request carries no digest. The orchestrator computes them from the files when it creates the job
(`inputs`): the head's game tree, the base's, and the policy digest, which covers the spec and route
files read from the base when there is one, so a change cannot edit the checks that judge it.

Every job has a folder of its own:

```
<jobs-root>/jobs/<id>/request.json   the request, as accepted
                      status.json    replaced whole on every change
                      work/          the job's scratch space
                      staging/       evidence while it is being written
                      output/        the finished evidence: staging/, renamed once
                      worker.log     the worker's output
```

## Rules the code holds

- **Two jobs never share a folder.** A job's id is random and its folder is made with a call that
  fails if the folder exists.
- **A status file is always whole.** It is written to a temporary file, synced and renamed into
  place.
- **Phases only go forward, and a final phase is never left.** `queued`, `preparing`, `executing`,
  `observing`, `evaluating`, then one of `completed`, `failed`, `cancelled`. The first finish wins:
  a cancelled job cannot become accept, whatever its worker does afterwards.
- **A decision belongs to a completed job only.** A failed or cancelled job has none.
- **Output appears by one rename**, after the work is done, and only for a completed job.
- **Cancelling stops everything.** The worker runs in a process group of its own; `cancel` makes the
  status final first, then stops the group, so the game and anything else the worker started end
  with it.
- **A worker that dies is not waited for.** The worker renews a lease while it runs. A job whose
  lease has run out and whose worker is gone is reported `failed` with `WORKER_LOST`.
- **Out of time is needs-review.** When the limit passes, the job completes as needs-review with
  `EXECUTION_TIMEOUT` and its group is stopped.
- **No result is never a pass.** A missing tool, an unusable input or a project that is not there
  completes the job as needs-review with a diagnostic that names the fix
  ([`expectrail/diagnostics.py`](../expectrail/diagnostics.py)).
- **The same key with the same inputs is the same job;** the same key with different inputs is an
  error.

## Engines

An engine verifies for one adapter (`expectrail/orchestrator/engines.py`). It has `preflight`, which
returns the diagnostics that stop a job before anything runs, and `execute`, which writes evidence
into the job's `staging/` and returns a decision. `godot` is the CI gate's verification
(`expectrail.gate.verify.run_gate`), so for the same inputs the orchestrator and the gate decide
alike; a test holds that on the gate tests' stand-in replay.

## What is not built yet

- **The isolated execution class.** It needs the replay sandbox (#253). Until then a request for it
  completes as needs-review with `TOOL_MISSING` and nothing is run unsandboxed in its place. Every
  run is graded `diagnostic`.
- **`observing` and `evaluating` as separate phases for Godot.** The gate replays and judges in one
  call, so a Godot job goes from `executing` to its end. The phases are in the contract for the
  verifier split in #251.
- **Commits in place of checkouts.** A request names folders; turning `--base A --head B` commits
  into checkouts is the caller's job for now.
- **Held-out routes, the `expectrail` command, MCP, the Action and the site** on top of this.
- **More than one machine.** The store is a folder and its locks are file locks: one host.
