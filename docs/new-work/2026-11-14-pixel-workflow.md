# jit.yml runs pixel checks in three jobs; a revision carries pixel checks (#286)

## What changed
- **jit.yml** takes the offer `signals-reach-evidence-pixel`. Under it:
  - `measure` gets the virtual display and 75 minutes, as under the evidence setting (the pixel setting
    offers the evidence too).
  - `replay-final` (runs the game, no secret) always replays the revise job's proposal, revised or not,
    with `--observer sam-3.1-anchor --pixel-capture runs/pixel-capture`, on a virtual display, and uploads
    the record and the frames as `jit-<case>-captured`.
  - **New `pixel-ask`** (`environment: main-only`, SAM's key, no game, no engine, no apt packages): reads
    what the change's cap has left after the captured record's spend (`pixel-budget`), sets
    `EXPECTRAIL_SAM_USD_CAP` to it, and runs `pixel-ask --sam-live` within it. With no frames it asks
    nothing; over the budget it sends nothing and the pixel checks stay not run.
  - **New `pixel-judge`** (runs the game, no secret): replays the proposal with `--sam-answers` and
    `--pixel-replays` and uploads `jit-<case>`, the result. With no frames or no answers it keeps
    replay-final's record, its pixel checks not run.
  - `repro-score` waits for `pixel-judge` and skips `-captured` and `-pixel-answers` artifacts.
  - Every other setting runs as before: replay-final's upload name and steps are unchanged for them, and
    the two new jobs are skipped.
- **`revise` takes the pixel setting** (`expectrail/jit/intent.py`, `revise_to_file`; `offer.REVISABLE`).
  It replaces rejected trace checks only. It carries the first round's pixel checks, as re-checked by
  `from_proposal`, and keeps the probes they replay. Pixel checks in the revision's answer are not read,
  and a diagnostic says so. Under this setting only, the revision prompt adds one sentence saying pixel
  checks are not revised (`REVISE_PIXEL_TEXT`). Every other setting's revision prompt is unchanged.
- **A small fix found on the way:** a revision's new probe whose renamed id (`jit-r-…`) equals a kept
  probe's id is no longer added twice. A check naming it is not taken.
- **`pixel-budget`** (`expectrail/jit/pixel_jobs.py`, `budget_left`; `python -m expectrail.jit.cli
  pixel-budget`): the cap less the capture record's `spend.usd`. The record is read only as a valid
  `jit-run` record of at most 8 MiB, not a link, with a plain spend; otherwise 0 is left.
- `offer.WORKFLOW` names the settings jit.yml takes (all four). `OFFERS` stays the settings without
  pixel checks.
- `agents/assurance/audit.py`: `jit.yml#pixel-ask` added to `PERCEPTION`, so the lane inventory accepts
  a job holding SAM's key.
- `docs/jit.md`: the workflow's three pixel jobs and the revision.

## What was run
- `python3 -m unittest tests.test_jit_pixel_revise tests.test_jit_pixel_workflow`: 27 tests, OK.
  - The revision under the pixel setting, on the simulated game: a rejected trace check is replaced, and
    the pixel check is carried. The second round, judged with the recorded smoke-route SAM answers
    through the test double of `tests/test_jit_pixel_replay.py`, keeps it and catches the wrong fix. A
    pixel check's own probe is kept. The id clash is refused. I checked that the probe test and the clash
    test fail with their fix taken out.
  - The workflow file's structure. Each new or changed shell step was run with bash and a stand-in
    `python`, on both branches: capture or keep the first round, ask or not, judge or keep.
  - `budget_left`, including forged and unreadable records.
- Changed workflow and offer assertions in `test_jit_offer`, `test_jit_offer_evidence`,
  `test_jit_pixel_offer`, `test_jit_pixel_replay`, `test_repro_score`, `test_jit_revise`: run, OK.
- Full suite on the branch (main 191cc3d plus the change): see the pull request.
- Not run: the OBAAF audit (`obaaf check`; it cannot be installed here), any workflow, any SAM or model
  call. Nothing was dispatched and nothing was spent.

## Not done
- The pixel jobs have not run in CI. Their first run is a live dispatch: it spends model and SAM money,
  and needs Sean.
- Sean's part: `pixel-ask` gives a job SAM's key in `main-only`. That is a person's change (AGENTS.md),
  so this pull request is labelled `needs-sean`.
- If OBAAF reports a finding for `pixel-ask`, the baseline would need it added, which is also Sean's.
- The capture artifact keeps every frame of each replay. Its size on bench probes is not measured.
- The judge's record does not carry the capture run's replay spend.

## Files
- `.github/workflows/jit.yml`
- `agents/assurance/audit.py`
- `expectrail/jit/intent.py`
- `expectrail/jit/offer.py`
- `expectrail/jit/cli.py`
- `expectrail/jit/pixel_jobs.py`
- `docs/jit.md`
- `tests/test_jit_pixel_revise.py` (new)
- `tests/test_jit_pixel_workflow.py` (new)
- `tests/test_jit_offer.py`, `tests/test_jit_offer_evidence.py`, `tests/test_jit_pixel_offer.py`,
  `tests/test_jit_pixel_replay.py`, `tests/test_repro_score.py`, `tests/test_jit_revise.py`
- `docs/new-work/2026-11-14-pixel-workflow.md`
