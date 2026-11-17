# Seed batches on main's merged reach implementation (#531)

## What changed

Rebuilt the seed-batch command layer on main 21fde1b4be9362d209852e3d44221d059d110643.
The merged reach implementation and its eight previously conflicting files are unchanged.
The new command uses main's route generator and observations. Before writing a report it
adapts the legacy `Player` anchor to `player`, appends `+ingest.1` to the producer version,
rehashes the ID, and validates with the merged reader. No invalid intermediate report file
is written. Route, bug text and ticks are preserved. Discovery and native intake fingerprints
prevent older command results from silently resuming under this adapter.

Every raw report is passed to the real ingest subprocess without propose or repair. Raw
outcomes, pairwise anchor grouping and original failed jobs remain explicit. No orchestrator,
contract, approval, workflow, original game or merged reach code was edited.

## What was run

The required historic c169a5e0da304773587304ed47bc8aabcec80da7 fetch completed.
The clean-main before-suite (same BASE tree in the ledger worktree), with EXPECTRAIL_*
variables unset: 4,654 tests in 784.479 seconds, FAILED (2 failures, 60 skipped).
Failures: tests.test_orchestrator.ProcessTest.test_waiting_on_a_worker_that_died_reports_it_at_once
and tests.test_replay_sandbox.DiskBoundTest.test_a_folder_the_game_makes_unreadable_is_cannot_tell.
Both are outside this change. An isolated BASE rerun kept the timing failure and passed the
sandbox test. Its log is retained; no assertion was changed.

The 12 command tests pass (0.533 seconds), including strict writer rejection, deterministic
nonmutating adaptation of main's findings, valid discovery output, raw/group accounting,
real subprocess arguments, native outcome distinctions and loading without numpy/PIL.
Final full suite: 4,666 tests in 762.401 seconds; FAILED (failures=1, skipped=60).
Failures: tests.test_orchestrator.ProcessTest.test_waiting_on_a_worker_that_died_reports_it_at_once.
The pinned Godot 4.7.2 smoke ran one clean seed for 240 ticks (zero reports), then two
real native ingest controls: idle returned inconclusive with anchor reached 3/3; the displaced
anchor returned anchor-desync. Both jobs had zero model phases/reservations. These are local
diagnostic checks, not the older large public experiment. The small handover retains the logs.

## Not done

The earlier 5,200-route, 322-report experiment was not rerun on this rebase and is not claimed
as a measurement of this commit or adapter version. No live model, spend, dispatch, push,
GitHub write, new approval or workflow edit. No blind, held-out or fresh content was read.

## Files

New files only: tools/playtester/command.py, command_bench.py, audit_command.py, COMMAND.md;
tests/test_playtester_command.py; this work log. Main's scale.py, producer.py, README.md,
SCALE.md, audit_scale.py, offscreen.py, docs/playtester-reach.md and
 tests/test_playtester_offscreen.py remain byte-identical to BASE.
