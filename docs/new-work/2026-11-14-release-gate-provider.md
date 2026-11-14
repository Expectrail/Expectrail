# The release gate's provider rows: outage and budget exhausted, against a stand-in provider (#258)

## What changed
Since #379, `expectrail verify` judges with both observers, so the vision provider and its spend cap
are on the path to clearance. Two rows of the release gate move from "not written yet" to tests:

- **Provider outage.** The real command (`python3 -m expectrail.cli`, the registered engine, its live
  visual observer and SAM client: nothing replaced) runs against a stand-in provider on 127.0.0.1
  that answers every request with HTTP 503. The unchanged game is needs-review (exit 2), not cleared,
  and the seeded bug is still rejected (exit 1): an outage does not hide a broken build.
- **Budget exhausted.** Three ways: a cap of $0 sends nothing at all (the stand-in counts 0 requests)
  and is needs-review; a cap of $0.005 (two images at list price) stops after at most two requests
  and is needs-review; a provider that answers HTTP 402 (out of credit) is needs-review.

The positive control for these rows is new: with the stand-in answering from the recorded answers
of the "Run it" samples (by each frame's SHA256 and the exact prompt), the same live command clears
the unchanged game. So "not cleared" in the other tests is the fault's doing.

`tests/release_gate/provider.py` is the stand-in. It listens only on 127.0.0.1, the key the tests
give the client is a stand-in, every vision setting from the caller's environment is dropped first,
and each test has its own empty answer cache. Nothing leaves the machine and nothing is spent.

One small fix the tests found: the job's reasons said "the visual observer gave no answer on 1
check" and not why, so an outage and a spent cap read the same in `expectrail status`. The gate now
adds the observer's reason (the kind only, as the record already keeps it per check), for example
"the visual observer gave no answer on (the model did not answer (budget))". The decision rule is
unchanged. `tests/test_two_observers.py` gains three assertions on that text; none was loosened.

## What was run
- `python3 -m unittest tests.release_gate.gate_provider` with real Godot 4.7.2 on this machine:
  5 tests, OK (223 s). Before the reasons fix, the four fault tests failed only on the reason text;
  not one run was cleared.
- `python3 -m unittest tests.test_two_observers tests.test_release_gate`: OK.
- The full suite on the branch (main at 8083215 plus this change): 3,272 tests, OK, 31 skipped.
- The full suite again after merging main at 6993726 (#428): 3,281 tests, OK, 31 skipped.
- `python3 -m tools.release_gate --require --out docs/release-gate.md` on 346f795 with real Godot:
  19 tests in 560 s, OK (1 expected failure, the #417 probe); held 12, open 23, failed 0, not run 0.
  The previous summary held 10.

## Not done
- Still open in this suite: swapped policy (real-process), a poisoned import cache, reading a private
  path and network egress (bubblewrap was not installable on this machine, so these were not written
  here), and the intent rows. The rest waits on #254, #255, #257 and #417.
- The CI `release-gate` job has not run this change yet.

## Files
- `tests/release_gate/provider.py` (new): the stand-in provider.
- `tests/release_gate/gate_provider.py` (new): the provider rows and their positive control.
- `tests/release_gate/controls.py`: the two rows name their tests; a second baseline.
- `tools/release_gate.py`: the summary's line about the positive controls.
- `expectrail/gate/verify.py`: the job's reasons say why the visual observer gave no answer.
- `tests/test_two_observers.py`: assertions on that text.
- `docs/release-gate.md`: rewritten by `tools.release_gate` from a local run.
- `docs/new-work/2026-11-14-release-gate-provider.md`: this file.
