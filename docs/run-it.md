# Run it

"Run it" on expectrail.tech lets a visitor verify one of Expectrail's sample changes, live, without a
terminal or GitHub (#265). This page describes slice 1 (the workflow, the samples, the recorded vision
answers and the same run offline) and slice 2 (the page, `docs/run-it/`, and a local stub of the edge
function). The edge function itself (slice 3) comes next.

## What a visitor chooses

One sample id from [`run-it/samples.json`](run-it/samples.json), and nothing else:

| id | the change | a working install decides |
| --- | --- | --- |
| `clean` | the bundled platformer as it is | accept |
| `fall-through-bug` | the seeded fall-through bug, against the game as it is | reject |
| `fall-through-repair` | its repair, against the bug | accept |

The request id is minted by the edge function (a UUID), never by the visitor. The workflow checks both
against `^[a-z0-9-]{1,40}$` before anything is checked out, and `expectrail.runit` refuses any id that
is not in the manifest before anything runs. No visitor text reaches a shell, a path or a URL.

## Vision answers are recorded (Option A)

Expectrail judges every check with two observers (#327): the engine's record and a vision model over
the captured frames, and a pass needs both. For the samples, Sean decided on November 13 that the game
run and the checks are live on every visit, and the vision answers come from one recording per sample:

- `docs/run-it/vision/<sample>.json` (`expectrail.vision-recording/v1`) holds the model's answers,
  each keyed by the SHA256 of the frame's PNG bytes and the exact text asked.
- `expectrail.recorded.RecordedObserver` answers only for a frame and question in the recording. Any
  other frame gets no answer, so the decision is needs-review. An answer about another picture is never
  reused, and no model is ever called.
- The record names the observer `sam-recorded`, with the provider "meta-model-api (recorded <date>,
  run <id>)", and `status.json` carries the date, so the page can say "vision answers recorded on
  <date>" beside every verdict.

**No sample has a recording yet.** Until Sean dispatches the one live recording run per sample (about
$0.33 a sample by [sam.md](sam.md), about $1 in all), `clean` and `fall-through-repair` decide
needs-review, and `fall-through-bug` still rejects, because a check the engine's record sees failing is
a failure under the two-observer rule. That is the honest result, and `--expect` treats it as expected.

## The same run offline

```
python3 -m expectrail.runit run --sample fall-through-bug --out DIR [--request-id ID] [--require-sandbox] [--expect]
python3 -m expectrail.runit check DIR --sample fall-through-bug --request-id ID
python3 -m expectrail.runit record --sample fall-through-bug --out docs/run-it/vision/fall-through-bug.json --run RUN_ID
```

`run` writes `DIR/status.json` (`expectrail.run-it-result/v1`), `DIR/findings.json` (the gate's
record) and `DIR/viewer/` (the evidence viewer, #264). `check` is what the publishing job runs. `record`
is the live recording run: it needs a model key and `EXPECTRAIL_SAM_USD_CAP`, spends money, and is
Sean's to dispatch. All three run from a clone of the repository (the manifest is under `docs/`).

## The workflow

[`.github/workflows/run-it.yml`](../.github/workflows/run-it.yml), dispatched on main only:

- **verify** (`contents: read`, no secret, no environment, 15 minutes): replays the sample with every
  replay in the sandbox (`--require-sandbox`) and uploads the folder.
- **publish** (`contents: write`, 5 minutes): never runs the game, the harness or anything from the
  sample. It downloads verify's folder outside its checkout, runs main's `expectrail.runit check` on it
  (only `status.json`, `findings.json`, `viewer/index.html`, `viewer/views.json`,
  `viewer/evidence.html` and frames named as the viewer names them; PNG and JSON checked by content;
  the pages must carry the viewer's Content-Security-Policy at the top; size caps; `status.json`
  must agree with the request, the sample and the findings record), then commits it to the branch
  `run-it-results` under `<request id>/`. A request id already published is refused.
- `concurrency: run-it`: one run at a time. GitHub keeps one pending run per group and cancels the rest,
  so the edge function refuses a request while one is queued or running.

The check is an allowlist, not a sanitizer: the page (slice 2) still shows the viewer inside a
sandboxed frame.

## The page (slice 2)

[`docs/run-it/`](run-it/) is the Run it page: `index.html` and `run-it.js`, static, served by GitHub
Pages at expectrail.tech/run-it/. It lists the samples from `samples.json`, asks the service to start
a run, follows it through its phases (waiting for a runner; playing the game and judging each check;
checking and publishing the evidence), and then shows the run's published folder:

- **The verdict is `status.json`'s decision**, and only an accept backed by recorded vision answers
  (every question answered from the recording) is shown as accepted, in green. A failed or cancelled
  run says "no verdict"; a result the page cannot read says "cannot tell". The page never shows more
  than the verifier decided.
- Beside every verdict: "vision answers recorded on <date>", or that none are recorded yet; whether
  the run ended as the sample is expected to; the receipt, "not signed yet (#255)"; when it ran.
- **The evidence** is the viewer's one-file export (`viewer/evidence.html`, frames embedded), shown in
  a frame sandboxed with `allow-scripts` only, so it has no origin of its own and cannot reach the
  page. It can also be downloaded as one file.
- **The latest finished run of each sample** is listed from `latest.json` at the root of the
  `run-it-results` branch (`expectrail.run-it-latest/v1`, an index only, never a verdict), and is
  always labelled as an earlier run with its time. When the service refuses (busy, quota, daily cap,
  circuit breaker, switched off) or cannot be reached, the page says which and when it resets, and
  shows the latest run of the sample instead. The publish job writes `latest.json` with main's
  `python -m expectrail.runit_site latest` after `expectrail.runit check` passed.
- The page talks only to itself, `https://api.expectrail.tech` and `raw.githubusercontent.com`
  (its Content-Security-Policy's `connect-src`). No link can point it at another service.

### The service's contract

`contracts/run-it-api.v1.schema.json` (`expectrail.run-it-api/v1`): every body the service sends.

| Request | Answer |
| --- | --- |
| `GET /api/health` | `health`: `open`, and `standIn` (true only on the stub with stand-in replays) |
| `POST /api/run` `{"sample": id}` | `accepted` (202) with a request id the service mints, or `refused` |
| `GET /api/status/<request id>` | `status`: `queued`, `running`, `publishing`, `published`, `failed` or `cancelled`; or `refused` (404) |

A refusal names its `reason` (`bad-request`, `unknown-sample`, `unknown-request`, `busy` 409,
`visitor-quota` 429, `daily-cap` 429, `circuit-open` 503, `disabled` 503), a sentence, and when it
resets. The service never sends a verdict: the page reads the published `status.json` itself.

### The local stub

```
python3 -m tools.runit_stub                                 real runs (needs Godot, as `runit run` does)
python3 -m tools.runit_stub --stand-in --stand-in-recorded  stand-in replays, no Godot
```

then open http://127.0.0.1:8765/run-it/. The stub binds 127.0.0.1 only, serves `docs/` and the
published folders under `/results/`, and does what the workflow does in the same order: run, main's
`expectrail.runit check`, publish only a folder that passes, update `latest.json`. It holds the limits
the edge function will hold: one run at a time, 3 runs per visitor per day (a salted hash of the
address, never the address), 40 a day in all, and a circuit breaker after 3 failed runs in a row
(`--per-visitor`, `--daily-cap`, `--breaker`, `--closed` to switch it off). With `--stand-in` the runs
do not play the game, and the page says so in a banner.

## The token, plainly

A fine-grained token cannot be limited to one workflow: "Actions: write" can dispatch or cancel any
workflow in the repository. The edge function only ever calls the dispatch endpoint for `run-it.yml`
and the read endpoints. Workflows that spend money sit behind the `main-only` environment's approval,
so a stolen token cannot spend without Sean.

## What Sean does

- Review and merge this workflow's `permissions` (`contents: write` on the publish job).
- Dispatch the one live recording run per sample, about $1 in all.
- Later (slice 3): the edge-function account, the token, DNS for an `api.` subdomain
  (`api.expectrail.tech`, the address the page calls).
