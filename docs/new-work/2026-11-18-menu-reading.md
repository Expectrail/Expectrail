# The menu probes' measure and evidence replays record the pause menu's counter (#285)

## What changed
#622 offered the generator the menu probes under `--offer signals-reach-evidence-menu`, so a check can read
the coin counter the pause menu draws (`ui_integer_at_end`). The harness records that counter only when asked,
and the measure step and the evidence asked on no replay. Run on Godot 4.7.2 here, the measure step read
`ui_integer_at_end` as no reading on all three menu probes, on the clean game and on `coin-counts-twice` alike
(`hold-right-then-toggle-pause`: clean `null`, bug build `null`; `coins_collected` 5 on both). The prompt
drops a missing reading, so the proposer was shown nothing about the counter on the routes that open the menu.

- **`harness.run.run` takes `ui_integers`** (default False). True sends the existing `--ui-integers=true`
  argument, the same one a check that reads the counter already causes. Nothing else in the harness changes.
- **`offer.replay_options(probe)`**: `{"ui_integers": True}` for a menu probe, `{}` for every other probe. Only
  the menu setting has menu probes, so no other setting's replays change.
- **The measure step** (`expectrail/jit/measure.py`) and **the evidence's captures**
  (`expectrail/repro/screen.py`, `capture_probe`) pass those options to the runner.
- The checks' own replays are unchanged: they ask when a check reads the counter (`needs_ui_integers`).
- No contract changes: `uiIntegers` and `ui_integer_at_end` were already in the trace, the measurements and
  the evidence's field list.

## What was run
- `python3 -m unittest tests.test_jit_menu_reading` before the change: 8 tests, 3 failures and 5 errors. After:
  8 tests, OK, with the engine present (Godot 4.7.2 from `harness/get_godot.sh`, SHA-512 checked).
- The engine test in it measures `hold-right` and `hold-right-then-toggle-pause` on the real engine:
  `ui_integer_at_end` on the menu probe is clean 5 / bug build 10 for `coin-counts-twice` and clean 5 / bug
  build 0 for `coin-counter-stuck`; `coins_collected` is 5 on the clean game; the walk has no reading.
- The evidence on the real engine under `xvfb-run`, `coin-counts-twice`, two menu probes, two jobs (2 min 51 s):
  `hold-right-then-toggle-pause` sees `record-and-screen`, with `uiIntegers` differing from tick 310 on 154 of
  464 ticks and `ui_integer_at_end` 5 clean against 10. `hold-left-then-toggle-pause` sees `neither` (no coins
  on that walk). `offer.attach_evidence` put that row on the probe as `differs` with no diagnostic. The
  committed `menu-evidence-coin-counts-twice.json` (November 13) showed no record difference on that probe.
- Full suite on the branch (main 4fd1a75 plus the change): see the pull request for the count.
- No model call, no dispatch, nothing spent.

## Not done
- No live run under the menu setting; it is Sean's to dispatch (cost on #285). These are readings, not a
  reproduction rate.
- The committed menu evidence records under `bench/jit/public/` are left as they were recorded.
- The full menu-setting measure step for one defect (36 probes, with evidence) was started here and stopped
  after 10 minutes on two cores; it was not completed locally.

## Files
- `harness/run.py`, `expectrail/jit/offer.py`, `expectrail/jit/measure.py`, `expectrail/repro/screen.py`
- `tests/test_jit_menu_reading.py` (new), `tests/test_jit_offer_menu.py` (the simulated game takes `ui_integers`)
- `docs/jit.md`, `docs/repro-audit.md`, `docs/new-work/2026-11-18-menu-reading.md`
