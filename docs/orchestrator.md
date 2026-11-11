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

Exit code: 0 accept, 1 reject, 2 needs review, 3 the job failed (no result), 4 cancelled, 5 the
command could not be carried out. 1 only ever means a job that completed as reject: a request that is
refused and a crash in the command itself are both 5, with one line saying why. Jobs are kept under
`--jobs-root` (default `$EXPECTRAIL_JOBS`, else `runs/jobs`), which may not be inside the game folder.

## The request and the job

| Record | What it is | Schema |
| --- | --- | --- |
| `expectrail.verify-request/v1` | What to verify: the adapter, the game folder, routes and specs, a checkout of the head and of the base, the execution class, the time limit, an idempotency key | [`verify-request.v1.schema.json`](../contracts/verify-request.v1.schema.json) |
| `expectrail.verify-job/v1` | A job's status: phase, decision, reasons, diagnostics, the input digests, the worker and its lease | [`verify-job.v1.schema.json`](../contracts/verify-job.v1.schema.json) |

A request carries no digest. The orchestrator computes them from the files when it creates the job
(`inputs`): the head's game tree, the base's, and the policy digest, which covers the spec and route
files read from the base when there is one, so a change cannot edit the checks that judge it.

**A game's digest describes what a replay reads.** The harness copies the game folder into a work
folder, following links and leaving out only `.godot`. The digest walks the same way and leaves out
the same one name; it keeps no skip list of its own, so a file under `__pycache__`, `.git` or any other
folder in the game changes it, and so does a file reached through a link. For a game with no links it
is `harness.run.tree_digest` exactly. A link that leaves the checkout, loops or points at nothing is
not hashed and not skipped: the tree is recorded as `null`, the reason becomes part of what the
request means, and the job completes as needs-review with `INPUT_INVALID` before anything runs.

**A request names paths inside the checkout only.** `game`, `specs` and every route pattern are
checked as text by the gate's own rule (`gate.verify.safe_relative`: relative, no `..`, no backslash)
before any file is opened. `/etc`, `../..` and `/etc/*.json` are refused and nothing is read.

**The worker reads the files again before it runs them.** If the game or its checks changed after the
job was created, the job completes as needs-review with `INPUT_INVALID`: the recorded inputs would
describe files that were not the ones verified.

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
- **No accept or reject without evidence.** A worker that returns either with nothing written is a
  `failed` job with `INTERNAL_ERROR`, not a result.
- **Cancelling stops everything.** The worker runs in a process group of its own; `cancel` makes the
  status final first, then stops the group named in that final status, so the game and anything else
  the worker started end with it. A worker that recorded itself a moment before the cancel is the
  one stopped; one that arrives after finds the job final and does nothing.
- **A job has one worker, whoever records it first.** The process that starts a worker and the
  worker itself both record it; the second to arrive changes nothing, and any other process is
  refused.
- **A worker that dies is not waited for, and neither is one that never comes.** A job has a lease
  from the moment it is created; taking the job and working on it renew it. A job whose lease has run
  out and whose worker is gone, or that no worker ever took, is reported `failed` with `WORKER_LOST`.
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
