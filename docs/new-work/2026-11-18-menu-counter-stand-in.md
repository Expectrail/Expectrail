# A hand-written counter stand-in for the two pause-menu counter defects, replayed on the real engine (#285)

## What changed
- `tools/menu_counter_stand_in.py` writes, for `coin-counts-twice` and `coin-counter-stuck`, a proposal under
  `signals-reach-evidence-menu` with the candidate withheld: one check on each of the three menu probes,
  `signal_compare` of `coins_collected` and `ui_integer_at_end`, equal, tolerance 0. The answer goes through
  `intent.parse_answer`, the parser a model's answer goes through. The model is `hand-written-stand-in`, which
  the reproduction score already gives no result.
- `bench/jit/stand-in/<defect>-menu-counter/`: the two proposals, the two `jit run --proposal` records from the
  real engine, and a page for each.
- `docs/repro-audit.md`: the menu row cites the stand-in run; a dated note says the `jit.yml` spend-cap
  prerequisite it describes was met by #618.

## What was run
- `jit run --proposal ... --offer signals-reach-evidence-menu --withhold-candidate --model off` on Godot
  4.7.2-stable (`harness/get_godot.sh`, SHA-512 checked), once per defect, main `32c416d` plus this change.
  Both `complete`, 3 proposed, 2 kept, 1 min 31 s and 22 replays each. Kept: `hold-right-then-toggle-pause` and
  `reverse-then-toggle-pause`, reference pass 3/3, bug build fail 3/3, no-fix candidate fail 3/3. Dropped:
  `hold-left-then-toggle-pause`, "killed no near-miss variant" (that walk picks up no coin). Counter readings
  from the traces: clean 5 and 4; `coin-counts-twice` 10 and 8; `coin-counter-stuck` 0 and 0. Assessed spend
  $0.1361 each at assumed prices; no model called, 0 SAM images, nothing paid.
- `python3 -m unittest tests.test_menu_counter_stand_in`: 12 tests, OK.
- Full suite: see the pull request.

## Not done
- No model proposed these checks. Whether one does needs Sean's dispatch on #285 (`jit.yml`, `mode=repro`,
  `offer=signals-reach-evidence-menu`, `budget_usd=2`; at most $48 assessed). Not dispatched.
- The replays' traces are not committed.

## Files
- `tools/menu_counter_stand_in.py`
- `tests/test_menu_counter_stand_in.py`
- `bench/jit/stand-in/coin-counts-twice-menu-counter/` (`README.md`, `jit-proposal.json`, `jit-run.json`)
- `bench/jit/stand-in/coin-counter-stuck-menu-counter/` (`README.md`, `jit-proposal.json`, `jit-run.json`)
- `docs/repro-audit.md`
- `docs/new-work/2026-11-18-menu-counter-stand-in.md`
