# A setting that tells the proposer what the do-nothing control is (#285)

## What changed

Since #675 the generator drops a check that passes every run of the do-nothing control. #755 found that
the form of a check decides this. On the public baseline, every check that a still actor satisfies passed
the control, and every strict relation failed it. No prompt told the proposer this. The revision was sent
the reason `passed-with-the-actor-doing-nothing` with nothing to explain it.

The new setting is `signals-reach-evidence-menu-control` (`expectrail/jit/offer.py`, `CONTROL`). It offers
exactly what the menu setting offers: the same probes, signals and evidence. It adds two texts in
`expectrail/jit/intent.py`:

- `CONTROL_TEXT`, in the system prompt. It says what the control is, and which forms a still actor cannot
  fail (`eq`, `lte` and `gte` with a tolerance of zero or more, and `max_entity_drop`, `max_episode_rise`,
  `entity_present` and `min_event_interval`). It says which forms a still actor cannot pass (`gt`, `lt`,
  `min_event_count`, `min_motion_extent` and `event_response`).
- `REVISE_CONTROL_TEXT`, in the revision's prompt. It says what the reason means and what to replace such
  a check with.

What decides a check does not change. Every other setting's prompts are byte for byte as they were. The
menu setting's four digests from main 6335e61 are pinned. A test checks the text against the evaluator's
comparators and the operation sets of `expectrail/repro/control_form.py`.

The setting is in both schemas' enums, in the `jit.yml` choice and plan check, and in the command line
through `offer.ALL`. There is a new example, `contracts/examples/jit-run-control.json`, written by
`run.generate`. `docs/repro-audit.md` lists the dispatch Sean would run, and `docs/jit.md` describes the
setting.

After Sean's review, `docs/repro-audit.md` states before the run what it will be read on. That is
survival under the control, valid catches and the form histogram, against the menu setting, with the two
outcomes written in advance. It also says that a reader of survival and the histogram over live records is
not built yet. `docs/jit.md` says the operation lists describe the evaluator and are not a menu of approved
forms.

## What was run

- `python3 -m unittest tests.test_jit_offer_control` passes: 16 tests, written first and seen failing.
- The offer, menu, evidence, pixel, withheld and audit-dispatch modules pass: 247 tests, OK, 2 skipped.
- The full suite was run on the branch merged with current main. Its result is in the pull request.

No model was called and nothing was dispatched. Whether the proposer then writes checks that survive the
control is not shown. Only the live run listed in `docs/repro-audit.md` can show it.

## Not done

- The live run: `jit.yml` from main with `mode=repro`, `offer=signals-reach-evidence-menu-control`,
  `candidate=withheld` and `budget_usd=2`. At most $48 assessed. That is Sean's decision.
- The revision is told the reason in words only. It is not told the rejected check's form.

## Files

- `expectrail/jit/offer.py`, `expectrail/jit/intent.py`
- `contracts/jit-run.v1.schema.json`, `contracts/repro-score.v1.schema.json`,
  `contracts/examples/jit-run-control.json`
- `.github/workflows/jit.yml` (one choice and the plan's check; no secret, environment, trigger or permission)
- `tests/test_jit_offer_control.py` (new); `tests/test_jit_offer.py`, `tests/test_jit_offer_menu.py`,
  `tests/test_jit_offer_evidence.py`, `tests/test_jit_pixel_revise.py`, `tests/test_jit_menu_reading.py`,
  `tests/test_trace_ui_integer.py`, `tests/test_repro_menu.py` (lists of settings widened)
- `docs/jit.md`, `docs/repro-audit.md`, `docs/new-work/2026-11-21-repro-control-told.md`
