# Lane contracts

Twelve JSON documents carry everything between the four lanes (seven lane hand-offs plus the
agents adjuncts `gameplay-verdict`, `release-candidate`, `overnight-summary`, `feedback-intake`
and `stability`). Each has a
schema in [`contracts/`](../contracts) and a worked example in
[`contracts/examples/`](../contracts/examples).
Agree changes in the team channel first, then change the schema, the example and the code in one
pull request. Every document starts with `"format": "expectrail.<kind>/v0"`, and only the current
IDs are accepted. The route format ID from before the October 30 rename was dropped on November 9,
once the discovery freeze and the mutation bench's registration were retired to the baseline
commit (`c169a5e`), where it is still accepted.

```
route ──► harness ──► replay + frames ──► SAM 3.1 ──► observations ─┐
                                                                    ├─► evaluator ──► verdict
test spec (Muse Spark drafts, a person approves) ───────────────────┘          │
                                                                               ▼ fail
verification ◄── verifier (rebuild, replay, all checks) ◄── candidate ◄── fixer ◄── repair request
```

| Contract | Written by | Read by | Lane |
| --- | --- | --- | --- |
| `route` | a person, or the bug-suite tooling | harness | Timo |
| `replay` | harness | evaluator, verifier, report | Timo |
| `test-spec` | Muse Spark drafts it; a person approves it once | evaluator, fixer (read-only) | Zayyad, Sean |
| `observations` | SAM 3.1 adapter | evaluator | Zayyad |
| `verdict` | evaluator | fixer, verifier, report | Zayyad |
| `repair-request` | orchestrator (`agents.orchestrator` / `agents.triage`) | fixer | Taofeek |
| `verification` | verifier (`agents.verifier`) | report, signing step (`agents.report`) | Taofeek |
| `gameplay-verdict` | verifier (`agents.gameplay` / `agents.verifier`) | morning report | Taofeek |
| `release-candidate` | morning report (`agents.report`) | demo / human sign-off | Taofeek |
| `overnight-summary` | overnight loop (`agents.loop`) | rollup / bench stub | Taofeek |
| `feedback-intake` | voice feedback intake (`agents.feedback`) | morning report, a person | Sean |
| `stability` | flaky-route detector (`agents.stability`) | overnight loop and held-out bench with `--stability`, a person | Sean |

`stability` (added November 9) is not in `expectrail.contracts.KINDS`: the discovery freeze covers
`expectrail/contracts.py` byte for byte, so `kind_of` does not recognise its format, and
`agents.stability` validates it with the kind named, `validate(doc, "stability")`. The loop's run
records carry its summary in `overnight-summary` (`results[].stability`). The baselines it compares
with (`bench/baselines/`, `expectrail.stability-baseline/v0`) have no schema: only
`agents.stability` writes and reads them ([README](../bench/baselines/README.md)).

## Discovery records (v1, added October 31)

Advisory discovery ([discovery.md](discovery.md)) has its own five records, each with a closed
schema (`contracts/<kind>.v1.schema.json`) and the format `expectrail.<kind>/v1`. They are read with
strict JSON (`expectrail.contracts.strict_loads`: duplicate keys, NaN and Infinity are refused) and
never feed the verifier's decision.

| Record | Written by | Read by |
| --- | --- | --- |
| `mechanics-profile` | written from the game's code; each claim is `inferred_code` until a person approves it (none is yet) | the template factory |
| `episode` | the episode normalizer, from one replay's trace | the trace-contract interpreter |
| `trace-spec` | the templates, or the Muse Spark planner (`model_prior` authority) | the trace-contract interpreter |
| `trace-verdict` | the trace-contract interpreter | the discovery job |
| `discovery-run` | the discovery job | the report, the CI notices and the collector |

Two more documents support the blind run without a schema of their own: `discovery/freeze.json`
(`expectrail.discovery-freeze/v1`, the digests of every file that decides a finding) and the fresh
set's manifest (`expectrail.fresh-set/v1`), which lives only in the private repository and is
checked by `python -m expectrail.discovery.fresh check`.

The difference from a `test-spec`: a person approves every test spec before it can fail a fix. A
`trace-spec` from discovery is advisory until the promotion stage exists (validation, a person's
approval, a pinned contract set), which is not built.

## The CI gate's record (added November 9)

`findings` (`expectrail.findings/v0`, [`contracts/findings.schema.json`](../contracts/findings.schema.json))
carries the CI gate's verdict from the job that runs a pull request's code to the job that posts the
comment ([ci-gate.md](ci-gate.md)). The example is a real local run: the clean game as the base, the
game with `bugs/physics-fall-through/v1.patch` as the head, and a stand-in held-out set. Its pull
request number and head commit are placeholders.

| Record | Written by | Read by |
| --- | --- | --- |
| `findings` | the gate's verify step (`expectrail.gate.verify`), untrusted | the gate's comment step (`expectrail.gate.comment`), which treats it as data |

It is not in `expectrail.contracts.KINDS` and is not read with `jsonschema`: the comment step
installs nothing and imports only `expectrail.gate.record` and `expectrail.gate.comment`.
`expectrail.gate.record` reads it with a size cap, strict JSON and a small standard-library
validator that refuses schema keywords it does not implement. A test holds that
validator equal to `jsonschema`. The reader then recomputes every derived value. Each finding id is
the first 12 hex digits of sha256(spec, route, kind), so a failure keeps its id across pushes. Held-out
routes appear as counts only; the schema has no field for anything else about them.

## Rules the contracts encode

- **A missing object is never a pass.** In `observations`, an object with an empty list in a frame
  was looked for and not found; a frame that is absent was not looked at. The evaluator returns
  `needs-review` when an object it needs is missing, except for the `visible` assertion, where
  absence is the thing being tested.
- **Positions stay out of prompts.** A test spec's `objects` are short noun phrases for SAM 3.1.
  Spatial and temporal conditions live in the `assertion`, which the evaluator decides in code.
  `expectrail.spec_writer` drafts specs with Muse Spark, rejects drafts with positional prompts or
  unknown objects, and only a person adds the `approval`.
- **Four assertion types, nothing else yet:** `visible`, `inside-region`, `never-crosses` and
  `reaches`. Any other instruction stays a draft marked needs review.
- **Everything is named by digest.** A verdict records the sha256 of the spec and the observations
  (`expectrail.contracts.digest`: sorted keys, no spaces), and a replay records the sha256 of the
  route, the game tree, the patch and every frame. Anyone can recompute a verdict.
- **The fixer gets a repair request and nothing more.** It can read the failing spec and verdict,
  the route and key frames. Held-out variants, clean controls, the evaluator, the gameplay checks
  and every key live on the verifier's side and are not mounted into fixer-work (deny-by-absence).
  Muse Code's vendor write confine stops writes outside its workspace; it does not claim OS read
  isolation on a shared host filesystem.
- **Feedback never reaches the fixer.** `feedback-intake` records what playtesters said and where
  each remark went. Its `policy` is fixed in the schema: nothing goes to the fixer, a bug report
  becomes a draft test spec with no approval, and a request to weaken a check goes to a person
  (`category: weaken-check` must have `route: human-queue` and no draft). Audio sources must
  record `consent: true`.
- **Every replay names its engine.** `engine.name` in a replay is `godot`, `unity`, `web` or
  `chromium`. Each adapter in `harness/adapters.py` says which one its replays record: the Godot
  harness writes `godot`, and the web harness writes `chromium` in its own
  `expectrail.web-replay/v0` document. The Unity harness (`harness/unity/run.py`) writes `unity`,
  and adds `seed`, `build` (the key of the player it replayed), `settle`, `hazards` and
  `integrity` (the exceptions and errors the game logged); an example is
  `contracts/examples/replay-unity.json`.
- **The trace has a schema.** `contracts/trace.schema.json` describes `trace.json`, which both
  harnesses write and the verifier reads but never shows the fixer. It is not in
  `expectrail.contracts.KINDS`; check a trace with `validate(doc, "trace")`. Every field but the
  header's `format`, `ticks`, `physicsTicksPerSecond` and `rows`, and each row's `tick`, is
  optional, because readers skip what they do not know. The Unity harness adds `objects` to every
  row: each tracked object's hierarchy path, role, box in frame pixels, and whether it is active and
  visible, in that row's own frame (`view` keeps the Godot convention, the camera of the frame
  before). The example, `contracts/examples/trace.json`, is hand-written.
- **Accept only if every check passes.** `verification.decision` is `accept` only when every
  regression, gameplay, held-out and clean check passes; any failure rejects; anything unclear
  needs review. An incomplete check set (missing a required kind) is `needs-review`, never
  `accept`. Accepted means the candidate passed this suite, not that the game is correct.

## Frames and ticks

The Godot demo runs physics at 120 ticks per second and the harness captures at 60 frames per second, so
frame `n` shows the state after tick `2n + 1`. Routes count ticks; observations and verdicts count
frames. Frames are 1600 by 960 pixels (the demo's window override); boxes are `[x0, y0, x1, y1]` in
those pixels, y down. The camera follows the player but stops at the level's edges, so a player who
falls through the ground is visible below the ground line for a few frames and then leaves the
screen.

The Unity game, Platformio, runs physics at 50 ticks per second (`TimeManager.asset`). The Unity
harness sets `Time.captureDeltaTime` to the fixed step so that each rendered frame holds one tick,
and fails a run in which any frame holds zero or two; frame `n` then shows the state after tick `n`,
captured at 50 frames per second. No Unity player has run yet. Its world pixels are Unity units times 128 (the art's pixels per unit), with y
negated so it points down as in the Godot traces.
