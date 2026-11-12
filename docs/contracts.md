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

Since November 12, 2026 a record says which observers judged it (`observers`), and under the rule
`both` every row says what the engine's record and the visual observer each said (`observed`), with
the digest of the visual observer's answer ([ci-gate.md](ci-gate.md), "Two observers, one rule"). A
record without the block is from before it and is read as `engine-only`; the first example is one.
`contracts/examples/findings-both-observers.json` is a record under `both`, made with the tests'
stand-in replay and stand-in model, not by a live run.

`checkProblems` (added November 12, #340) counts the problems the gate found reading the spec and
route files. Above 0 the decision is never accept, and the reader that recomputes the decision from
the record holds it to that. A record written before the field existed has none and reads as 0.

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

## The capability ledger (added November 11)

`capabilities` (`expectrail.capabilities/v1`,
[`contracts/capabilities.v1.schema.json`](../contracts/capabilities.v1.schema.json)) is the one record
of how far each advertised mode is proven: [`docs/capabilities.json`](capabilities.json), rendered as
[capabilities.md](capabilities.md). The example is four rows of the real ledger. Each cited run records how it ended (`conclusion`), read from GitHub when the row was written; a run that did not end in success needs a `conclusionNote` saying why it is evidence all the same, and only an implemented or experimental row may cite one. A run's evidence may name the `jobs` it rests on. `python3 -m expectrail.capabilities recheck` (`expectrail.capability_runs`) asks GitHub again: it fails when a run's conclusion is not the one recorded, when a named or linked job is missing or did not end in success, when a wall time's step is missing or failed, when a time read from the step's timestamps is not what the step lasted to the second, when a time measured inside the step (one with `phases`) is longer than the step (a shorter one passes, since the step does other work too), and when a run cannot be read. A run's evidence may also carry `counts`: the counts in its `shows` that are tied to the notices the run published (the annotations a job writes with `::notice`, where the bench jobs put their public counts). An entry names the words it backs (`says`), the numbers (`n`, `of`), the notices by title (`titled`, with `*` for any text, and `not` for titles left out), and one of three ways of counting: `count`, where `of` is how many such notices there are and `n` how many have that text as one whole field of their message (the fields are what lies between semicolons), and every such notice must say which side it is on: it has `count`, or it has the field named under `otherwise` (for example "caught with SAM off: no"), once and not both, so a notice that lacks the field is "cannot tell" and never a "no"; or `reads`, where exactly one notice has the title and one of its fields is that text with `{n}` and `{of}` filled in (neither may stand beside a digit or beside the other, so no two counts fill it the same); or `has`, for a job whose notice is one JSON object: `of` is how many notices with the title have the members under `where` as given (a value, or a list of values to be one of), and `n` how many of those have the members under `has` as given. A member is equal only to a value of its own kind, and a notice that is not one JSON object, has a member twice, lacks a named member or has it as another kind of value is "cannot tell", never a "no". `recheck` reads those runs' notices and counts again: a different count is a problem, and so is a notice that is missing, is there twice, comes from a job that did not end in success, or cannot be read. The test suite checks without the network that the words stand in `shows` where a count is found ("8 of 8" is not in "8 of 80"), that the numbers are the ones the words give (words that hold no count speak of every notice counted, so their `n` is their `of`), and that an entry counting fewer notices than there are names `otherwise`, and counts the committed ledger against the notices saved in `tests/capability_notices.json`. It reads conclusions, jobs, steps and notices only, never logs or artifacts, so a count with no `counts` entry is as its writer wrote it; the page says how many are tied.

| Record | Written by | Read by |
| --- | --- | --- |
| `capabilities` | a person or an agent, by hand, in the pull request that changes what a mode has shown | `expectrail.capabilities` (`check`, `render`, `recheck`) and `tests/test_capabilities.py` |

It is not in `expectrail.contracts.KINDS`. The schema fixes the shape, the four statuses and the four
grades. `expectrail.capabilities.problems` checks what a schema cannot: a `measured` row links a CI
run, a measured or integrated row cites only runs whose recorded `conclusion` is success, every file a
row points at exists, the `protected` grade is refused, and every command, switch,
workflow, doc page and watched name in the README or `docs/index.html` belongs to a row.

A wall time in the ledger may carry `phases` (import, replay, evaluate, other), copied from a run's
`timing.json`, with `phasesFrom` saying where in the run they can be read. The check fails when the
phases do not add up to the whole.

## The public reproduction bench (added November 11)

Three records for issue #285, all about public defects only.

| Record | Written by | Read by |
| --- | --- | --- |
| `repro-bench` (`expectrail.repro-bench/v1`, [`contracts/repro-bench.v1.schema.json`](../contracts/repro-bench.v1.schema.json), example [`repro-bench.json`](../contracts/examples/repro-bench.json)) | By hand: [`bench/jit/public/defects.json`](../bench/jit/public/defects.json) | `expectrail.repro.bench.load`, `python3 -m expectrail.repro check` |
| `repro-visibility` (`expectrail.repro-visibility/v1`, [`contracts/repro-visibility.v1.schema.json`](../contracts/repro-visibility.v1.schema.json); the committed records [`bench/jit/public/visibility.json`](../bench/jit/public/visibility.json), on the library probes, and [`visibility-reach.json`](../bench/jit/public/visibility-reach.json), on the reach probes, are the examples) | `python3 -m expectrail.repro visibility`, with `--reach` for the reach probes | `expectrail.repro.visibility.load`, `python3 -m expectrail.repro render` |
| `repro-score` (`expectrail.repro-score/v1`, [`contracts/repro-score.v1.schema.json`](../contracts/repro-score.v1.schema.json), example [`repro-score.json`](../contracts/examples/repro-score.json), made-up rows) | `python3 -m expectrail.repro score`, from a live run's `jit-run` records | `expectrail.repro.score.load`, `python3 -m expectrail.repro score-render` |

A bench entry is a defect id, its family, a patch against the clean game, a bug report, where its
author expects it to show, and whether probes or signals were designed around it. The reader refuses
a path outside `bench/` and `bugs/`; a path with a part that names held-out material (it starts with
`fresh`, or has `blind`, `heldout` or `held-out` in it, in any case; `expectrail.repro.bench.held_out_name`
is the one copy of that rule); a path reached through a link, whether the link is the file or a
folder on the way and wherever it leads; an id or a patch listed
twice, an empty report, and a patch that names a file the game does not have. The bench holds no
result.

A visibility record says, per defect, what replaying the probes it names (the library's, or the reach probes of `expectrail.repro.reach`) on the defect build changed against
the clean game: the signals that moved, the fields of the engine's record that differ, and one of
`signal`, `trace-only`, `none` or `error`. The reader recomputes that label and the totals from the
rows and refuses a record where they disagree, or one that names a signal `expectrail.trace.signals` does not have. It says what those probes can see, not how often a defect is reproduced, and has
no field for a rate.

A score record has one row per defect of the bench: `reproduced`, `not-reproduced` or `no-result`;
the checks that reproduced it; for a miss, a reason from a closed list and the evidence for it; what
the run spent on it; and the digest of the `jit-run` record it was read from. The writer takes a
check's standing from its runs, never from the record's own `valid` flag, and gives `no-result` to a
record whose flag disagrees with its runs or that was made for another candidate, defect or report.
The reader recomputes the totals from the rows and refuses a row whose outcome does not follow from
it, and a reason the records cannot show (`route-never-reaches`, `probe-language`). That is all a
reader of this record can check: a score record holds no runs, so a row changed to `reproduced` with
a check named, a spend, a digest and the totals redone to match reads as well as a true one. What
ties a row to runs is its `recordSha256` and the `jit-run` record it names; to trust a rate, score
the run's records again and compare. The writer counts a check as reproducing only when the
`jit-run` record's catch entry for it shows three fails on the bug build, and writes free text
(`why`, `evidence`, `source`) as one line; the reader refuses free text that is not. It has no
decision field: nothing reads it to accept or reject a change. No score record is committed, because
no live run has been made.

## Wall time per phase (added November 11)

`verify-timing` (`expectrail.verify-timing/v1`,
[`contracts/verify-timing.v1.schema.json`](../contracts/verify-timing.v1.schema.json), example
[`verify-timing.json`](../contracts/examples/verify-timing.json)) says where the wall time of one
verification went. It never feeds a decision.

| Record | Written by | Read by |
| --- | --- | --- |
| `verify-timing` | `agents.verifier.verify`, as `timing.json` beside `verification.json` | `python3 -m expectrail.timing show` (a CI notice and job summary), and by hand into the ledger's wall times |

Four phases that add up to the total: `import` (Godot's `--import`, and warming the shared import
cache when it is cold), `replay` (the Godot process playing the route), `evaluate` (everything the
verifier does outside a harness run: observations, the checks, the verdict files; with SAM on this
includes the model calls) and `other` (the harness copying the game, applying patches and hashing
frames). `evaluate` is the total less the harness's own time, not a timer of its own. `arms` gives
the harness's five steps for each replay the verifier asked for: `reference`, `candidate`, `clean`,
and `held-out-1`, `held-out-2` and so on; a private route is named by its position only, and the
schema refuses any other name. It is not in `expectrail.contracts.KINDS`. One run on one machine: it
is a measurement of that run, with no spread. If the record cannot be written the verification
stands, `timing.json` is removed and `timing-error.txt` says why; a second fault while doing that is
noted, never raised. A number that is not finite (`NaN`, `Infinity`) is refused when a record is read or written. The review's replays
(`agents.review_change`) and the CI gate's are not timed yet.

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

## Verification jobs (added November 11)

`verify-request` (`expectrail.verify-request/v1`,
[`contracts/verify-request.v1.schema.json`](../contracts/verify-request.v1.schema.json)) and `verify-job`
(`expectrail.verify-job/v1`, [`contracts/verify-job.v1.schema.json`](../contracts/verify-job.v1.schema.json))
are the orchestrator's two records ([orchestrator.md](orchestrator.md)). The request example is a real
request with its checkout paths replaced; the job example is the status of that request run through
the Godot engine on the gate tests' stand-in replay, with a placeholder worker.

| Record | Written by | Read by |
| --- | --- | --- |
| `verify-request` | whoever asks for a verification, through `expectrail.orchestrator.request.build` | `expectrail.orchestrator.store` when it creates the job, and the worker |
| `verify-job` | `expectrail.orchestrator.store`, the only code that changes a job's status | `status`, `report`, and whoever waits for the job |

Neither is in `expectrail.contracts.KINDS`. Both are read with a size cap, strict JSON and the
standard-library validator in `expectrail.gate.record`, and the store then checks what a schema
cannot: only a completed job has a decision or an output, and no history leaves a final phase.

