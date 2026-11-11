# The gate records whether the game was sandboxed, and can refuse to run without it (#253, second part)

## What changed
The replay sandbox (#304) isolated the game, but nothing above the harness knew: the gate's record did
not say whether a replay was sandboxed, the gate's own workflow did not install bubblewrap, and the
orchestrator refused its `isolated` class outright.

- **Contract first.** `findings.json` gains `isolation`: replays finished, replays sandboxed, the tool,
  whether the sandbox was required, and each distinct reason a replay ran outside. Schema, example,
  writer (`expectrail.gate.verify`) and both readers (the review page and the pull request comment) in
  this change. A record without the block still reads and is described as not sandboxed.
- **A replay counts as inside only on its own account**: its `replay.json` names the tool and says no
  network, a confined file system and its own processes. A replay that says nothing counts as outside.
- **`--require-sandbox`** on the gate, and `require-sandbox` on the verify action: where the machine
  cannot sandbox, nothing is replayed and the decision is needs-review; a replay outside the sandbox
  keeps the decision from accept, and the reader recomputes that, so a record cannot claim otherwise.
  A failing check is still a reject.
- **The verify action** installs bubblewrap and lets user namespaces start (best effort; the record
  says why when it cannot). **This repository's verify workflow requires the sandbox**, so a pull
  request's game no longer runs outside it there.
- **The orchestrator's `isolated` class** runs with the sandbox required and refuses where the machine
  cannot. Its evidence stays graded `diagnostic`: the ledger's `isolated` grade also needs a trusted
  job that judges and signs (#254, #255).
- The ledger: `replay-sandbox` and `orchestrator` move to `integrated`, each citing main's CI run
  43115035122 (job `seeded-bugs`: 34 sandbox tests, every seeded-bug replay and three verifications
  through the orchestrator, all with the sandbox required).

## What was run
- `python3 -m unittest tests.test_ci_gate tests.test_orchestrator`: 142 tests, OK. New: counts over
  head, base and held-out replays; a replay that says nothing; mixed; an account that names the tool
  but not the three properties; required and outside (never accept, and the reader refuses a record
  that says accept); required where the machine cannot sandbox (nothing replayed, exit 2, a record);
  self-contradicting blocks; an old record; the comment line with hostile text; the action's input.
- The full suite on the tree merged with main: 1,921 tests, OK, 17 skipped (7 need bubblewrap).
- `python3 -m expectrail.capabilities recheck`: 24 runs read from GitHub, 0 problems, the newly cited
  run 43115035122 and its `seeded-bugs` job among them.
- One existing test changed: `tests/test_jit_rules.py` held that the decision reads only the counts and
  the held-out block. It now holds three inputs, and that the third can only take an accept away.
- Real bubblewrap through the gate with the sandbox required: this change's own `Expectrail verify`
  run on the pull request, which uses the pull request's copy of the action. See the pull request.
- Not run locally: anything in real bubblewrap (this machine has none).

## Not done
- A separate trusted job that judges (#254) and a signed receipt (#255): until then nothing is graded
  `isolated`.
- The Unity player and the web replay; a bound on total disk use.
- The gate's own digest of the game (#303).

## Files
`contracts/findings.schema.json`, `contracts/examples/findings.json`, `expectrail/gate/record.py`,
`expectrail/gate/verify.py`, `expectrail/gate/page.py`, `expectrail/gate/comment.py`,
`expectrail/orchestrator/engines.py`, `.github/actions/expectrail-verify/action.yml`,
`.github/workflows/expectrail-verify.yml`, `tests/test_ci_gate.py`, `tests/test_orchestrator.py`,
`docs/ci-gate.md`, `docs/replay-sandbox.md`, `docs/orchestrator.md`, `docs/capabilities.json`,
`docs/capabilities.md`
