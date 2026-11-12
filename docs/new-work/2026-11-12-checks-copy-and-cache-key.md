# The verifier judges from a digested copy of the checks, and an import cache is stored only under the key of what it was built from (#307)

## What changed

Two readings that were not held against each other, both left open when #318 merged.

**The checks.** A job's `policyDigest` came from one reading of the spec and route files and the gate
read them again from the checkout to judge. Nothing compared the two, and the digest's own list of
files was not the gate's: it counted a route that is a link, which the gate does not read.

- `expectrail.gate.verify.check_files` is the one listing of what the gate reads to judge: every
  `*.json` in a specs folder that is a real folder (drafts included), and every matched route file
  that is not a link. `load_specs` uses it and so does the job's digest.
- Before the run the worker copies those files into the job's folder (`work/checks`), each read
  once, and compares the digest of the bytes written with the job's `policyDigest`. If they differ
  the job is needs-review (`INPUT_INVALID`, "the checks changed after the job was created") and
  nothing runs.
- `run_gate` takes `checks`: a folder to read the specs and routes from in place of their checkout.
  The orchestrator's engine passes the copy. The gate's command line and the action are unchanged.

So for a job: the checks that judge are the bytes its digest names. This closes gap 7 of #307.

**The import cache.** Its key came from one reading of the game and its imports from a copy made by
a second (the merge guard's finding 1 on #318): with the folder changed in between and changed
back, a cache built from game B was stored under game A's key and reused by a later replay of A.
The copy's digest is now compared with the digest the key was made from, and a cache whose copy is
another tree is not stored. A replay passes the digest it already took, so the key, the cache's
copy and the replay's copy are all held to one reading.

## What was run

- `python3 -m unittest discover -s tests -t .`: 2,032 tests, OK, 22 skipped (bubblewrap and Unity, as on main).
- New tests in `tests/test_orchestrator.py`: an engine that spoils every spec and deletes every
  route in the checkout before verifying still gets the decision and the record the gate gave on the
  checkout as it was; checks changed just before the copy stop the job with nothing replayed; the
  digest covers exactly the gate's listing, the copy holds exactly those files, and the gate decides
  the same from the copy as from the checkout (a clean repository and one with a draft).
- New test in `tests/test_harness.py`: with the game changed for the moment of the cache's copy,
  nothing is imported and no cache or key is stored; with the folder still, a cache is stored under
  the key of what was copied.
- Real Godot 4.7.2, `python3 -m expectrail.orchestrator sample`: exit 0; accept, reject, accept, each
  as expected. In each of the three jobs the record's trees equal the job's inputs and the digest of
  `work/checks` equals the job's `policyDigest`.

## Not done

- Unity's build copy (`harness/unity/run.py`) and the web runner's copy still use their own walks. I
  cannot run Unity here, and its CI environment needs a person's approval, so I did not change it blind.
- The gate's command line and the action read the checks from the checkout, once. Only a job
  through the orchestrator gets the digested copy.
- A spec that is a link leading outside its checkout is read by the gate from the checkout and is
  not copied or digested by the orchestrator, which opens nothing outside the checkout. A job then
  judges without it where the plain gate would use it. No bundled check is such a link.

## Files

- `expectrail/gate/verify.py`, `expectrail/orchestrator/request.py`, `expectrail/orchestrator/runner.py`,
  `expectrail/orchestrator/engines.py`, `expectrail/orchestrator/store.py`
- `harness/run.py`
- `tests/test_orchestrator.py`, `tests/test_harness.py`
- `docs/orchestrator.md`, `docs/harness.md`, `docs/capabilities.json`, `docs/capabilities.md`
