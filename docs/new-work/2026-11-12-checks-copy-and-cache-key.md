# The verifier judges from a digested copy of the checks, and an import cache is stored only under the key of what it was built from (#307)

## What changed

Two readings that were not held against each other, both left open when #318 merged.

**The checks.** A job's `policyDigest` came from one reading of the spec and route files, made by
the orchestrator's own code, and the gate read them again from the checkout to judge. Nothing
compared the two, and the two did not read alike.

- `expectrail.gate.verify.read_checks` is the one reader: each spec and route file once, with the
  gate's reader (no link followed, a size cap), into one `Checks` object that holds the approved
  specs, the routes as bytes, what was refused and why, and a digest. The job's `policyDigest` is
  that digest. A file the reader refuses is in the digest by its name and the refusal; what a link
  leads to is never opened.
- When a job runs, the engine reads the checks once with that reader, stops if the digest is not
  the job's ("the checks changed after the job was created", needs-review, nothing replayed), and
  hands the object to `run_gate`. The gate then opens no spec or route file. There is no second
  source: without that reading there is no verdict.
- The gate, with or without a job, replays copies of the routes written from the bytes it read, in
  its work folder. Before, each route file was read three times (to parse, to hash, to replay).
- After the run the worker holds the digest the engine judged with against the job's, as it does
  the game's trees.

My first version of this copied the checks into the job's folder with a reader of its own and gave
the gate that folder. The merge guard's review showed the two ways that fails: the copy followed
links the gate refuses (so a job said "all 4 checks pass" where the plain gate says 2 and names the
refused spec), and an engine without its copy went back to the checkout without a word. One reader
and one source replace both.

So for a job: the checks that judge are the bytes its digest names. This closes gap 7 of #307.

**The import cache.** Its key came from one reading of the game and its imports from a copy made by
a second (the merge guard's finding 1 on #318): with the folder changed in between and changed
back, a cache built from game B was stored under game A's key and reused by a later replay of A.
The copy's digest is now compared with the digest the key was made from, and a cache whose copy is
another tree is not stored. A replay passes the digest it already took, so the key, the cache's
copy and the replay's copy are all held to one reading.

## What was run

- `python3 -m unittest discover -s tests -t .`: 2,053 tests, OK, 22 skipped (bubblewrap and Unity, as on main).
- New tests in `tests/test_orchestrator.py`:
  - a replay stand-in that spoils every spec and deletes every route in the checkout during the run:
    the job still gets the decision and the record the gate gave on the checkout as it was, and
    every route a replay played has the sha256 the record names and is not a file of the checkout;
  - an engine that edits the spec before verifying: needs-review, nothing replayed;
  - an engine that says it judged with other checks: needs-review, no evidence published;
  - `specs/two.json` as a file, a link to a file inside the checkout, a link outside it, a link to
    nothing, a link to something that is not JSON, and a file over the cap: the job's decision,
    reasons, check count and specs equal the plain gate's on the same checkout, and for the links an
    audit hook on every `open` in the process shows the target was never opened;
  - the digest: unchanged by a route that is a link and by files that only look like checks, changed
    by a draft, changed by a spec that is a link but not by what the link leads to.
- New test in `tests/test_harness.py`: with the game changed for the moment of the cache's copy,
  nothing is imported and no cache or key is stored; with the folder still, a cache is stored under
  the key of what was copied.
- Real Godot 4.7.2, `python3 -m expectrail.orchestrator sample`: exit 0; accept, reject, accept, each
  as expected, with each replay playing the gate's copy of the route (`work/gate/checks/routes`).

## Not done

- Unity's build copy (`harness/unity/run.py`) and the web runner's copy still use their own walks. I
  cannot run Unity here, and its CI needs a person's approval, so I did not change it blind (#324).
- A spec the gate refuses does not stop an accept: the reasons name it and the decision stands on
  the specs that were read. That is the gate's behaviour before this change and is unchanged; whether
  a refused spec should be needs-review is a question for its own issue.
- Held-out routes are still replayed from their own folder; this change does not touch that path.

## Files

- `expectrail/gate/verify.py`, `expectrail/orchestrator/request.py`, `expectrail/orchestrator/runner.py`,
  `expectrail/orchestrator/engines.py`, `expectrail/orchestrator/store.py`
- `harness/run.py`
- `tests/test_orchestrator.py`, `tests/test_harness.py`
- `docs/orchestrator.md`, `docs/harness.md`, `docs/capabilities.json`, `docs/capabilities.md`
