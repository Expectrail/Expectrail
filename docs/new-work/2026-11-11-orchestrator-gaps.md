# Orchestrator: five of the seven gaps left when #300 merged (#307)

## What changed
#300 merged under the two-round rule with its remaining gaps listed in #307. This closes 1, 2, 4, 5
and 6 of them, each with the test the issue names.

1. **Exit code 0 is a completed accept and nothing else.** `status` exited 0 for a job with no result,
   so `status "$JOB" && deploy` passed on a queued job and on one that later ended in reject. One
   function now gives the code for `verify`, `status`, `cancel` and `report`, and a job that is not
   finished has a code of its own, 6 (`report` on one used 5). The two exceptions are stated in the
   command's help and the docs: `verify --detach` (0: the job was started) and `sample`.
2. **The game's digest is the harness's, in the same order.** The files were sorted as one string, the
   harness sorts part by part, and the two differ for sibling folders such as `a/` and `a-b/`. The docs
   said "exactly"; now it is.
4. **No accept or reject without evidence, whatever the caller passes.** `finish` with `publish` left
   out gave `completed, accept, output: null`, and an empty staging folder was published as the
   evidence. Either decision now always publishes and needs at least one plain file; otherwise the job
   is `failed` with `INTERNAL_ERROR`. A status file that claims accept or reject with no output is
   refused when read.
5. **The jobs folder may not be where the checks are read.** With `--head .`, the default `runs/jobs`
   and `--routes '**/*.json'`, each job's own `request.json` was read as a route and every job ended
   `INPUT_INVALID` with a message about the game. Such a jobs folder (inside the specs folder, or
   anywhere a route pattern reaches) is now refused before the job is created, with the reason.
6. **A pipe, a socket or a device in the game is refused**, like a link that leaves the checkout. It was
   left out of the digest without a word, while the harness's copy would try to read it.

## What was run
- `python3 -m unittest tests.test_orchestrator`: 74 tests, OK. New: every phase against `status`,
  `report`, `verify` and `cancel` for the exit code; four pairs of sibling folders for the digest's
  order; `publish` left out, and three kinds of empty evidence; four placements of the jobs folder and
  eleven pattern cases; a pipe made with `os.mkfifo`.
- The full suite: OK, 10 skipped. `python3 -m expectrail.orchestrator sample` with real Godot 4.7.2: accept, reject, accept, exit 0.
- Four existing tests changed because they relied on what is now refused: three finished a job as
  accept or reject with no evidence, and one expected `status` and `report` to exit 0 and 5 for a
  queued job. No test was removed or skipped.

## Not done
- Gap 3, a killed worker's children: stopping them safely needs each of them to carry the job's id, so
  that a process group whose number was reused is never stopped by mistake, and that touches the
  harness files #304 changes. It follows when #304 has merged. Stated as a limit in
  `docs/orchestrator.md`.
- Gap 7, files that change between the worker's second read and the gate's copy: waits for #303.
  Stated as a limit.

## Files
`expectrail/orchestrator/cli.py`, `expectrail/orchestrator/request.py`,
`expectrail/orchestrator/store.py`, `tests/test_orchestrator.py`, `docs/orchestrator.md`
