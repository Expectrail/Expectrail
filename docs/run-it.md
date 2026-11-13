# Run it

"Run it" on expectrail.tech lets a visitor verify one of Expectrail's sample changes, live, without a
terminal or GitHub (#265). This page describes slice 1 (the workflow, the samples, the recorded vision
answers and the same run offline), slice 2 (the page, `docs/run-it/`, and a local stub of the edge
function) and slice 3 (the edge function, `apps/run-it-edge/`, and a scripted burst).

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

## Recording the vision answers (run-it-record.yml)

Sean records a sample from the Actions tab, with no terminal:
[`.github/workflows/run-it-record.yml`](../.github/workflows/run-it-record.yml), "Run it record", with
the sample picked from a list and a spend cap (default $1.00, at most $2). It runs on main only.

- **record** (`main-only` environment, so Sean approves each run; `MODEL_API_KEY`; `contents: read`;
  30 minutes): replays the sample with every replay in the sandbox, runs `expectrail.runit record`
  with `EXPECTRAIL_SAM_USD_CAP` set to the cap, and uploads the recording. It prints the spend at list
  price (requests sent, images answered), even when the recording fails.
- **propose** (`contents: write`, no environment, no secret, 5 minutes): never runs the game, the
  harness or anything from the sample. It downloads the recording outside its checkout, checks it with
  main's `expectrail.runit check-recording` (a usable recording, for this sample, with at least one
  answer), commits it to a new branch `run-it-vision/<sample>-<run id>`, and puts a link in the run's
  summary that opens the pull request with the run and the spend in its description. It never pushes
  to main.

The link is there instead of a pull request opened by the workflow because a pull request opened with
the workflow's own token starts no workflow, so its required checks would never run. A pull request
Sean opens from the link runs them as any other. Sean's whole part: dispatch it once per sample (about
$1 in all), approve each run, open the three pull requests from their links and merge them.

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
`visitor-quota` 429, `daily-cap` 429, `circuit-open` 503, `disabled` 503, `unavailable` 502 when
GitHub could not be reached and nothing was started or counted), a sentence, and when it resets. The service never sends a verdict: the page reads the published `status.json` itself.

### The local stub

```
python3 -m tools.runit_stub                                 real runs (needs Godot, as `runit run` does)
python3 -m tools.runit_stub --stand-in --stand-in-recorded  stand-in replays, no Godot
```

then open http://127.0.0.1:8765/run-it/#local (the fragment tells the page to use the stub; it
switches only to the page's own origin, on loopback). The stub binds 127.0.0.1 only, serves `docs/` and the
published folders under `/results/`, and does what the workflow does in the same order: run, main's
`expectrail.runit check`, publish only a folder that passes, update `latest.json`. It holds the limits
the edge function will hold: one run at a time, 3 runs per visitor per day (a salted hash of the
address, never the address), 40 a day in all, and a circuit breaker after 3 failed runs in a row
(`--per-visitor`, `--daily-cap`, `--breaker`, `--closed` to switch it off). With `--stand-in` the runs
do not play the game, and the page says so in a banner.

## The edge function (slice 3)

[`apps/run-it-edge/`](../apps/run-it-edge/) is the service the page calls at
`https://api.expectrail.tech` (`/health`, `/run`, `/status/<id>`; the stub's `/api/...` paths work
too). `service.js` holds everything and uses only web-standard APIs, with its storage, clock and fetch
passed in; `worker.js` adapts it to a Workers-style runtime with one Durable Object named `run-it`,
so every request sees the same strongly consistent state, and requests inside it are handled one at a
time.

- **What a visitor can send:** `{"sample": id}`, from the page's origin (`ALLOWED_ORIGINS`, default
  `https://expectrail.tech`), at most 1,024 bytes, with an id from the three samples. Anything else is
  refused before GitHub is called. The request id is a UUID minted here.
- **What it calls:** the dispatch of `run-it.yml` on `main` with the two inputs, the list of
  `run-it.yml`'s runs, one run and its jobs, and the published `status.json` on `run-it-results`.
  Nothing else; a test reads the source for any other address, and the JavaScript tests fail on any
  other endpoint. `run-it.yml` now names each run `Run it <request id>`, which is how the function
  finds the run it dispatched.
- **One run at a time:** a start while the last run is queued, running or publishing is refused as
  busy. A run GitHub has not listed after 5 minutes, or still going after 30, is failed.
- **Quotas:** 3 runs per visitor per day (`PER_VISITOR`), counted by a SHA-256 of `VISITOR_SALT` and
  the address (`CF-Connecting-IP`), never the address itself; 40 a day in all (`DAILY_CAP`). Both
  reset at midnight UTC and the refusal says so. A start GitHub refuses is not counted.
- **Circuit breaker:** after 3 failed runs in a row (`BREAKER`) it starts nothing and says why. A run
  counts as failed when it fails, is cancelled, is lost, or publishes a `status.json` whose phase is
  not completed; a published run whose `status.json` cannot be read neither counts nor resets. A
  person closes the breaker by changing `BREAKER_EPOCH` to any new value.
- **Closed by default:** it starts runs only with `RUN_IT_OPEN` set to `true` and every setting
  valid; a missing token or salt says "not set up yet".
- **Status reads are cached** for 10 seconds per run, so visitors polling cannot use up the token's
  rate limit.
- It never sends a verdict.

### The scripted burst

```
python3 -m tools.runit_burst http://127.0.0.1:8765/api --count 50     the local stub
node apps/run-it-edge/local.mjs                                        the edge function, with a pretend GitHub
python3 -m tools.runit_burst http://127.0.0.1:8787 --count 50
python3 -m tools.runit_burst https://api.expectrail.tech --count 20   the deployed one (starts at most one real run)
```

It sends the requests at the same moment and fails unless at most one run is accepted, every refusal
names its limit, and every answer is a body of the contract. The suite runs it against the stub and
against the edge function served locally (`tests/test_runit_edge.py`); the JavaScript tests add a
burst of 200 at once and a day of bursts with runs finishing, holding every limit
(`apps/run-it-edge/test/service.test.mjs`, `node --test`).

## The token, plainly

A fine-grained token cannot be limited to one workflow: "Actions: write" can dispatch or cancel any
workflow in the repository. The edge function only ever calls the dispatch endpoint for `run-it.yml`
and the read endpoints. Workflows that spend money sit behind the `main-only` environment's approval,
so a stolen token cannot spend without Sean.

## What Sean does

- Review and merge this workflow's `permissions` (`contents: write` on the publish job).
- Dispatch the one live recording run per sample, about $1 in all.
- Put the edge function online. Everything below is Sean's (AGENTS.md: accounts, secrets, DNS), and
  none of it is in the repository:
  1. **Pick the host and create the account.** The code is written for Cloudflare Workers with a
     Durable Object; `apps/run-it-edge/wrangler.toml.example` is a starting configuration. Another
     host needs its own adapter in place of `worker.js` (a store with strongly consistent get, put and
     delete, and one instance for all requests).
  2. **Create a fine-grained token**: resource owner Expectrail, only the repository
     Expectrail/Expectrail, repository permission **Actions: Read and write** and nothing else
     (Metadata: read comes with it). Set an expiry and a reminder to rotate it.
  3. **Set two secrets on the function**: `GITHUB_TOKEN` (the token) and `VISITOR_SALT` (32 random
     characters or more). Set the variable `RUN_IT_OPEN` to `true` when ready; until then every start
     is refused as switched off.
  4. **DNS**: `api.expectrail.tech` pointing at the function (with Cloudflare, a custom domain on the
     worker, which needs the zone on Cloudflare; otherwise the host's own instructions).
  5. Then a burst against the deployed function, which starts at most one real run.
