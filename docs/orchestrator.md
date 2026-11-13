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
0 only when all three decide that way and 3 otherwise (it checks the install; it is not a verdict on a
change, so it never exits 1), and CI runs it on every pull request (`seeded-bugs`).

```bash
python3 -m expectrail.orchestrator sample
```

Exit code, the same for `verify`, `status`, `cancel` and `report`:

| Code | Meaning |
| --- | --- |
| 0 | the job completed as accept |
| 1 | the job completed as reject |
| 2 | the job completed as needs review |
| 3 | the job failed: no result |
| 4 | the job was cancelled |
| 5 | the command could not be carried out (a refused request, an unknown job, a crash in the command, a command line that cannot be read) |
| 6 | the job is not finished: no result yet |

0 only ever means a job that completed as accept, and 1 one that completed as reject. So
`status "$JOB" && deploy` cannot pass on a job that is still queued. Two stated exceptions for 0:
`verify --detach` exits 0 when the job was started, which says nothing about its result, and `sample`
exits 0 when all three of its runs were as expected.

Jobs are kept under `--jobs-root` (default `$EXPECTRAIL_JOBS`, else `runs/jobs`). The jobs folder may
not be inside the game folder or the specs folder, or anywhere a route pattern looks: a job's own
`request.json` would be read as part of the game or as a check. With `--routes '**/*.json'` the default
folder is refused; name the routes' own folder (`routes/*.json`) or keep the jobs elsewhere.

## The request and the job

| Record | What it is | Schema |
| --- | --- | --- |
| `expectrail.verify-request/v1` | What to verify: the adapter, the game folder, routes and specs, a checkout of the head and of the base, the execution class, the time limit, an idempotency key | [`verify-request.v1.schema.json`](../contracts/verify-request.v1.schema.json) |
| `expectrail.verify-job/v1` | A job's status: phase, decision, reasons, diagnostics, the input digests, the worker and its lease | [`verify-job.v1.schema.json`](../contracts/verify-job.v1.schema.json) |

A request carries no digest. The orchestrator computes them from the files when it creates the job
(`inputs`): the head's game tree, the base's, and the policy digest, which covers the spec and route
files read from the base when there is one, so a change cannot edit the checks that judge it.

**A game's digest describes what a replay reads.** The request's `headTree` and `baseTree`, the
gate's record, `replay.json` and the copy a replay runs all come from one walk of the game folder
([harness.md](harness.md#what-a-game-folder-holds)): links are followed, `.godot` and `.git` are not
part of a game, and nothing else is skipped, so a file under `__pycache__` or any other folder
changes the digest, and so does a file reached through a link. A pipe, a socket or a device in the
game is refused like a link that leaves the checkout: the copy would try to read it. A link that
leaves the checkout, loops or points at nothing is not hashed and not skipped: the tree is recorded
as `null`, the reason becomes part of what the request means, and the job completes as needs-review
with `INPUT_INVALID` before anything runs.

**The decision is about the tree that was asked about.** Three readings are held against each other.
The worker reads the files again before it starts and stops if they differ from the job's inputs.
Each replay's copy reports the digest of the bytes it was made from, and the gate does not use a
replay whose copy is not the tree its record names (the check is a `replay-error`, so needs-review).
After the run the worker holds the trees the record names against the job's inputs: if they differ,
the job completes as needs-review with `INPUT_INVALID` ("changed while the job was running") and the
record is not published as the job's evidence, because it decides about a game nobody asked about.

**The checks that judge are the ones the job names.** There is one reader of the specs and routes,
the gate's (`expectrail.gate.verify.read_checks`): each file is read once, no link is followed, and
a file over the size cap is refused. The job's `policyDigest` is that reader's digest: every `*.json`
in the specs folder (drafts included) and every route file the patterns name, each by the sha256 of
the bytes read, or by the reader's refusal when it would not read the file. A spec or a route that
is a link to a file, and a route outside the checkout, is in the digest by its name and the refusal;
what it leads to is never opened.
When the job runs, the engine reads the checks once more with the same reader. If the digest is not
the job's, the job stops ("the checks changed after the job was created") and nothing is replayed.
Otherwise the gate is handed what was read and opens no spec or route file itself: the routes the
replays play are copies made from the bytes that were read. There is no second source to fall back
to. After the run the worker holds the digest the engine judged with against the job's, as it does
the game's trees.

**A route pattern means the same on every Python.** The patterns are matched by the gate's own
matcher ([how a pattern is read](ci-gate.md#route-patterns)), so a job's `policyDigest` and the
routes that judge do not depend on the Python that runs the worker. The check that keeps the jobs
folder out of where routes are looked for (`request.pattern_reaches`) compares names with the same
function, and also without regard to case, so it can only say yes more often than the matcher finds.

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
- **No accept or reject without evidence.** Either decision always publishes the evidence folder and
  needs at least one file in it, whatever the caller asked for. With none, the job is `failed` with
  `INTERNAL_ERROR`, not a result, and a status file that claims accept or reject with no output is
  refused when read.
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
- **A lost worker's processes are stopped, and found by the job's id.** A worker that is killed
  cannot stop what it started. Every worker's environment names its job (`EXPECTRAIL_JOB`), and what
  it starts inherits that: the harness passes that one name on to the game, the virtual display and
  the sandbox tool. When a job is declared lost, and when it is cancelled, every process whose
  environment names the job is stopped, and the job's reasons say how many were found and how many
  are gone. A process number alone can pass to something else between the look and the signal, so
  where the system gives process handles (Linux 5.3 and later, unless the container refuses the
  call) the process is held by one, its environment is read again, the handle is checked to still
  be a live process, and the signal goes to the handle. Whenever that cannot be completed, at any
  step and for any reason but "no such process" (no such call, a container that refuses it, a
  handle that cannot be asked or signalled), the environment is read again and the signal goes to
  the number, and the job's reasons say "by process number" and why. The handle is the better way
  and the number stays for everything the handle does not cover, so no failure of the better way
  leaves a lost job's processes running. The job is final before the stop, so an error in the stop
  itself is not raised: it becomes a reason on the job ("could not stop what it had started").
  A process the job starts while it is being stopped is found by the next look and counted.
  The caller and its own ancestors are never stopped, so a status asked from inside a job does not
  end the asking; the reasons then say how many were left for that. A cancel that leaves something
  running says so too.
  Where there is no `/proc` to ask (macOS), nothing is stopped and the job says so. One limit: the
  environment read is what the process holds now, so a program that writes over its own environment
  is not found. The sandboxed game cannot stay alive that way: the sandbox tool is started so that
  the kernel kills it when the worker dies, and everything inside dies with the tool (seen in CI: a
  worker killed mid-replay left nothing of the job, before anything was asked to stop). An
  unsandboxed game could.
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
alike; a test holds that on the gate tests' stand-in replay. Its preflight's tool check is the part
of `expectrail doctor`'s list every run needs ([install.md](install.md)), so the two cannot disagree.

The engines are picked through the adapter registry ([harness.md](harness.md), "Adapters"):
there is one for every registered adapter that has a verify path, and it takes the replay, the file
that marks a project folder, the folders left out of the game's digest and the list of what a run
needs from that adapter. A job's trees are taken with the same adapter's folders, so the job and
its evidence name a game the same way. A job that names an adapter the registry does not hold
completes as needs-review with `INPUT_INVALID` ("no adapter named ..."), and so does one whose
adapter has no verify path ("the adapter 'unity' has no verify path yet; those that have one:
godot"). Nothing runs in either case. Today `godot` is the only adapter with a verify path.

The engine tells the job when it moves on: `observing` when a replay starts, `evaluating` when its
checks are judged. It takes the gate's rule for which observers judge (`GodotGate(rule="both",
visual=...)`, [ci-gate.md](ci-gate.md), "Two observers, one rule"). The engine registered for `godot`
still judges by `engine-only`; a job's `findings.json` has an `observers` block when the rule was `both`.

## A second Godot project

`verify` takes its game from `--head` and `--game`. A test holds that the six modules of the gate
and the orchestrator on that path do not name the bundled game, and that the gate always hands the
harness a game. `harness.run.run` itself still falls back to the bundled game when it is given
none; this path never takes that fallback. [`tests/projects/crate-run`](../tests/projects/crate-run/README.md) is
a small Godot project that shares no file with it, and `tests/test_second_project.py` verifies both
through this one command with real Godot replays (CI job `seeded-bugs`; locally with
`EXPECTRAIL_ENGINE_TESTS=required`), and the CI job `package` runs the installed command on it:

```
expectrail verify --head CHECKOUT --game project --routes routes/walk.json --specs specs
```

What a second project still has to match, because it is in code and not in the project's own config
(#259): the player is the node named `Player`, the ground is the collision of `TileMapLayer` tiles,
and the position log draws the player's box at the bundled game's size (40 by 60 pixels, its bottom
13.25 below the node's origin). A project without tile collision has no ground line, and a check
about the ground then needs review.

## What is not built yet

- **A grade above `diagnostic`.** The `isolated` execution class is built: every replay runs in the
  replay sandbox ([replay-sandbox.md](replay-sandbox.md)) or the job does not run (`TOOL_MISSING`,
  needs-review, nothing replayed unsandboxed), and a replay that does not say it ran inside keeps the
  job from accept. Its evidence is still graded `diagnostic`: the ledger's `isolated` grade also needs
  a separate trusted job that judges and signs (#254, #255). What the sandbox did is in the evidence
  (`findings.json`, `isolation`).
- **`observing` and `evaluating` as separate phases for Godot.** The gate replays and judges in one
  call, so a Godot job goes from `executing` to its end. The phases are in the contract for the
  verifier split in #251.
- **Commits in place of checkouts.** A request names folders; turning `--base A --head B` commits
  into checkouts is the caller's job for now.
- **Held-out routes, the `expectrail` command, MCP, the Action and the site** on top of this.
- **More than one machine.** The store is a folder and its locks are file locks: one host.
