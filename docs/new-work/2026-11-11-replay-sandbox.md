# The replay runs in a sandbox: no network, its own process tree, only its own files (#253, Godot)

## What changed
The game under test is the candidate's code, and the harness started it as a plain child process: the
host's network, every file the user can read or write, and a `/proc` where the starting process's
environment is readable. A control test with the real engine shows all of it: a copy of the bundled
game with one added script connects to a port on the host, writes outside its folder, opens an
approved check and the verifier's source, and opens the harness's environment.

`harness/sandbox.py` runs both of Godot's steps (import and replay) inside bubblewrap: no network, its
own process tree and session, a file system holding only the work copy at `/game`, one output folder
at `/out`, the route read-only at `/in/route.json`, the engine and the system's `/usr`, a 256 MiB
`/tmp` and home, an environment built from nothing, no further user namespaces, 2 GiB per file. The
harness takes back only `trace.json` and `frames/f*.png`, plain files only, and fails the replay on a
link.

Modes `auto` (default: isolate when possible, record why not), `require` and `off`, by `--sandbox` or
`EXPECTRAIL_SANDBOX`. Every `replay.json` carries `isolation` (schema and example updated). A trace
left by an earlier run in the same folder is deleted before the replay, so it can no longer stand in
for a run that wrote none.

After the merge guard's first review: the sandbox gets a session of its own (`--new-session`), because
without it a game started from a developer's terminal could open that terminal through `/dev/tty`;
`--warm-cache --sandbox require` on a machine without bubblewrap ends in one line, not a traceback.

## What was run
- In real bubblewrap 0.9.0 on a hosted runner, CI job `seeded-bugs`, run
  [43104148935](https://github.com/Expectrail/Expectrail/actions/runs/43104148935/job/130802949557)
  (commit bb3e1a0, success): `tests.test_replay_sandbox` with the sandbox tests required, 31 ran, 31
  passed, none skipped; then every seeded-bug replay with `EXPECTRAIL_SANDBOX=require`. That run is
  from before the session change and before main's orchestrator was merged in: the pull request
  names the run that covers both.
- Locally: the full suite passes; the tests that need bubblewrap skip, because this machine has none
  and none can be installed. The controls with real processes and the real engine pass locally.
- Locally, and not evidence for the sandbox: the two engine tests and four replays against a stand-in
  made from util-linux `unshare` with the same mounts gave the same frame and trace hashes, and showed
  that `xvfb-run` hangs as the first process of its namespace, so bubblewrap is never given
  `--as-pid-1`.

## Not done
- The Unity player and the web replay.
- The gate and the orchestrator do not read `isolation` yet, so no verdict is graded by it and the
  gate's own workflow does not install bubblewrap.
- Total disk use is limited per file only.
- The fixer's sandbox has the same terminal gap (#309).

## Files
`harness/sandbox.py`, `harness/run.py`, `contracts/replay.schema.json`,
`contracts/examples/replay.json`, `tests/test_replay_sandbox.py`, `docs/replay-sandbox.md`,
`docs/ci-gate.md`, `docs/capabilities.json`, `docs/capabilities.md`, `.github/workflows/ci.yml`
