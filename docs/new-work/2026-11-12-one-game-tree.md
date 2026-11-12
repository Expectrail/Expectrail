# One definition of what a game folder holds, and the decision held to the tree that was asked about (#303, #307 gap 7)

## What changed

A game is named by a digest of its files in four places (`replay.json`, the gate's record, the import
cache's key, a verification job's inputs) and copied in two (the replay's work copy, the import
cache's staging copy). Each walked the folder its own way. The harness's digest did not follow a
linked folder and the copy did, so a file behind a link was replayed without being in the digest; the
orchestrator had its own walk to cover that; the gate had a third skip list.

- `harness/tree.py` is now the one walk: `files`, `digest` and `copy`. Every digest and every copy
  goes through it (`harness.run`, `harness.adapters`, `expectrail.gate.verify`,
  `expectrail.orchestrator.request`). The copy holds exactly the files the digest covers.
- Links are followed and copied as plain files. A link that leaves the game folder (or the checkout,
  when the gate or the orchestrator gives one), a link that loops, a link to nothing, and a pipe,
  socket or device stop the replay before anything is copied or run. In the gate that is
  needs-review (exit 2) with the reason; in the orchestrator, `INPUT_INVALID`.
- `.godot` and `.git` are not part of a Godot game at any depth; nothing else is skipped. Before, a
  game at the root of its repository carried `.git` into every replay's copy and into its digest. An
  empty folder is no longer copied (no digest ever covered one).
- The gate takes both trees before any replay, and refuses an output or work folder inside the game.
- The copy returns the digest of the bytes it wrote. `replay.json` records that, and a replay stops
  if the folder changed between its first read (which keys the import cache) and its copy.
- The gate does not use a replay whose copy is not the tree its record names: `replay-error`, reason
  "the head game changed while it was being verified".
- The orchestrator's worker holds the trees the record names against the job's inputs after the run.
  If they differ the job is needs-review (`INPUT_INVALID`, "changed while the job was running") and
  the record is not published as the job's evidence. This is gap 7 of #307 for the game.

For a game with no links, no `.git` and no special files, nothing changes: same digest, same copy.

## What was run

- `python3 -m unittest discover -s tests -t .`: 2008 tests, OK, 17 skipped (the skips are the ones
  that need bubblewrap or Unity, as on main).
- `tests/test_tree.py`, 17 tests: the copy holds exactly the listed files and its digest is the
  digest; the digest changes exactly when the copy changes; the bundled Godot and Unity games keep
  the digests the old definition gave; the harness, the gate, the adapter and the orchestrator give
  one digest for one game; a replay stops before copying on a bad link, and when the game changes
  between its first read and its copy; the gate does not use a replay of another tree.
- `tests/test_orchestrator.py`: a game changed after the worker's check gives needs-review and no
  published evidence; the published record names the trees the job asked about.
- Real Godot 4.7.2, `python3 -m harness.run --route harness/routes/smoke.json`, once on main
  (bdccc2d1) and once on this branch, same machine: the two `replay.json` files are equal in every
  field (`game.tree`, all 120 frame hashes, the trace hash). Neither ran in the sandbox: bubblewrap
  is not installed on that machine.
- Real Godot, `python3 -m expectrail.orchestrator sample`: accept, reject, accept, each "as
  expected"; in each of the three jobs the published record's trees equal the job's inputs. The
  command's own exit code was not captured in that run (it was piped); CI's `seeded-bugs` job runs
  the same command and fails on a non-zero exit.
- `python3 -m expectrail.capabilities check`, `python3 -m tools.merge_guard`, the OBAAF check: see
  the pull request.

## Not done

- Nothing here was run inside bubblewrap locally; CI's sandbox tests cover the copy mounted as `/game`.
- The specs and routes are still read twice (worker, then gate) and not compared after the run. The
  record names each by sha256, the request by one digest of them all (#307).
- Unity and web replays make their copies in their own runners. The Unity adapter's digest now comes
  from the same walk; its build copy does not yet.
- A game that needs an empty folder to exist will not find it in the copy. None of the bundled games
  does; no test looks for one in other games.

## Files

- `harness/tree.py` (new), `harness/run.py`, `harness/adapters.py`
- `expectrail/gate/verify.py`
- `expectrail/orchestrator/request.py`, `expectrail/orchestrator/engines.py`, `expectrail/orchestrator/runner.py`
- `tests/test_tree.py` (new), `tests/test_orchestrator.py`, `tests/test_ci_gate.py`
- `docs/harness.md`, `docs/orchestrator.md`, `docs/ci-gate.md`, `docs/capabilities.json`, `docs/capabilities.md`
