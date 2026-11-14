# Pixel checks offered to the proposer, under a setting of their own (#286)

## What changed
- A fourth offer setting, `signals-reach-evidence-pixel` (`expectrail/jit/offer.py`, `PIXEL`). It
  gives the proposer everything the evidence setting gives it, and lets it write up to four pixel
  checks in `pixelChecks`. It is in `offer.ALL`, which `measure` and `propose` take. It is not in
  `offer.OFFERS`, so `run`, `revise`, the run record, the score and the workflow do not take it.
  `offer.replayable` refuses it, because the replay does not judge pixel checks yet.
- The prompt (`expectrail/jit/intent.py`), under this setting only:
  - The system prompt adds `PIXEL_TEXT`, which gives the four predicate shapes.
  - The user prompt adds `pixelChecksOffered`, from `pixel.menu`: the predicates each existing
    observer judges, the bound objects it can be asked about, and each object no observer can judge,
    with why. On the bundled game that is SAM with `visible`, `inside-region` and `never-crosses`,
    about the player only.
  - Every other setting's prompts are byte for byte as before (digest tests unchanged and passing).
- Reading the answer:
  - `intent.parse_answer_pixel` reads `pixelChecks` through `pixel.parse_answer`, which uses
    `parse_candidate`. Each check is renamed `jit-px-<id>` and is `model_prior`.
  - A refused check, a repeated id, or a check past the fourth is dropped, with a note saying so.
  - An answer with pixel checks and no trace check is usable under this setting only.
  - Under other settings, `pixelChecks` is not read and the diagnostics say so.
  - `parse_answer` still returns three values, as before.
- The proposal file carries `pixelChecks` under this setting only, an empty list when the call failed.
  `from_proposal` re-checks each one: it must come out of `parse_candidate` unchanged, with a `jit-px-`
  id, at most four. An edited check, or pixel checks added to another setting's proposal, is refused.
- `pixel.assess` judges a proposal's pixel checks from an observer's answers. Each check's images are
  reserved against the cap together with the checks before it, because `Spend.reserve` checks one
  amount at a time and reservations do not add up on their own. Then the keep rule applies, or the
  check is `not-run`.

## What was run
- `python3 -m unittest tests.test_jit_pixel_offer tests.test_jit_pixel tests.test_jit_offer tests.test_jit_offer_evidence tests.test_repro_reach`:
  OK.
- Full suite on the branch (main 6e6ca6a plus this change): the first run had one failure.
  `tests.test_repro_reach` forbids the text `reach-` in any `expectrail/jit` file but `offer.py`, and
  `pixel.py`'s docstring named the setting. The docstring now says "the pixel setting". Second run:
  3,272 tests, OK, 31 skipped.
- On the recorded SAM answers (run 43335151089, smoke route, asked with a box), a proposal's pixel check
  "the player is found where the engine puts it, score ≥ 0.8":
  - kept for `layering_v1`;
  - dropped for `missing-texture_v1` (`does-not-fail-on-bug`);
  - `needs-review` for physics fall-through.

  A `never-crosses` check on the same frames is `needs-review` for `layering_v1`: where the player is
  not found, a line cannot be judged. Asked with a point (run 43310237299), the visible check is
  dropped, `fails-on-clean`. These recordings hold one answer per frame per build, so the "three runs"
  are the same answers three times.
- No model call, no observer call, no dispatch. Nothing was spent.

## Not done
- The replay does not judge pixel checks. The next slice puts them in the run record (schema, writer,
  reader) and lets `run` take the pixel setting.
- Pixel-check windows are in the observer's frame numbers. The evidence's frame numbers use their own
  capture rate, and the two have not been checked against each other on the bench.
- No SAM answers are recorded for the public bench's screen-only defects. That needs a live run, which
  will be proposed on #286 with its cost and `needs-sean`.
- The bindings are still the bundled game's (`pixel.bindings_for`) until #259.

## Files
- `expectrail/jit/offer.py`, `expectrail/jit/pixel.py`, `expectrail/jit/intent.py`, `expectrail/jit/run.py`,
  `expectrail/jit/cli.py`
- `tests/test_jit_pixel_offer.py` (new)
- `docs/jit.md`, `docs/new-work/2026-11-14-pixel-offer.md`
