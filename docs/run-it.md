# Run it

"Run it" on expectrail.tech lets a visitor verify one of Expectrail's sample changes, live, without a
terminal or GitHub (#265). This page describes slice 1: the workflow, the samples, the recorded vision
answers and the same run offline. The page itself (slice 2) and the edge function (slice 3) come next.

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

## The token, plainly

A fine-grained token cannot be limited to one workflow: "Actions: write" can dispatch or cancel any
workflow in the repository. The edge function only ever calls the dispatch endpoint for `run-it.yml`
and the read endpoints. Workflows that spend money sit behind the `main-only` environment's approval,
so a stolen token cannot spend without Sean.

## What Sean does

- Review and merge this workflow's `permissions` (`contents: write` on the publish job).
- Dispatch the one live recording run per sample, about $1 in all.
- Later (slice 3): the edge-function account, the token, DNS for an `api.` subdomain.
