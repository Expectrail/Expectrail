# A hand-written counter stand-in for `coin-counts-twice` (#285)

**No model wrote these checks.** They are not a reproduction and the reproduction score gives a record made
from them no result (`expectrail/repro/score.py`, `STAND_INS`; `tests/test_menu_counter_stand_in.py`).

- `jit-proposal.json`: one check on each of the three menu probes of `signals-reach-evidence-menu`: after the
  walk, the pause menu's one integer label equals the coins the engine says were picked up
  (`signal_compare`, `coins_collected` `eq` `ui_integer_at_end`, tolerance 0). Written by
  `python3 -m tools.menu_counter_stand_in --defect coin-counts-twice --out <dir>`, through the parser a model's
  answer goes through, with the candidate withheld, so it is bound to the bench's report and to no patch. The
  tool does not choose the probes: the keep rule does.
- `jit-run.json`: `jit run --proposal` on that file, on the real engine, on November 18, 2026.

## The run

Godot 4.7.2-stable (`harness/get_godot.sh`, SHA-512 checked), a cloud container, no model key in the
environment, main `32c416d` plus this change. 1 minute 31 seconds, 22 replays.

```
python3 -m expectrail.jit.cli run \
  --report-file bench/jit/public/coin-counts-twice/report.txt \
  --base bench/jit/public/coin-counts-twice/defect.patch \
  --candidate bench/jit/public/no-fix.patch \
  --proposal bench/jit/stand-in/coin-counts-twice-menu-counter/jit-proposal.json \
  --out OUT --budget-usd 1 --model off --run-id local-menu-counter-stand-in-coin-counts-twice \
  --offer signals-reach-evidence-menu --withhold-candidate
```

| Check, on the probe | Clean game | Bug build | Bug build plus the no-fix candidate | Kept |
| --- | --- | --- | --- | --- |
| `hold-right-then-toggle-pause` | pass 3 of 3 (counter 5) | fail 3 of 3 (counter 10) | fail 3 of 3 | yes |
| `hold-left-then-toggle-pause` | pass 3 of 3 (counter 0) | one replay, counter 0; the record keeps no result for a check it drops | not run | no: killed no near-miss variant |
| `reverse-then-toggle-pause` | pass 3 of 3 (counter 4) | fail 3 of 3 (counter 8) | fail 3 of 3 | yes |

The counter readings are the last row's `uiIntegers` of each replay's trace (the traces are not committed).
A clean pass means `coins_collected` equalled the counter on that replay. The walk left picks up no coin,
so a counter that counts double still reads 0 there and the keep rule drops that check.

The record's spend, $0.1361, is its own accounting at assumed prices: $0.1240 for the intent call, which the
run reserves even when it replays a saved proposal, and $0.0121 of assumed runner time. No model was called and
nothing was paid. SAM was asked about 0 images.

## What this shows and what it does not

It shows that under the menu setting, with the candidate withheld, `jit run` itself on the real engine keeps a
counter check on this defect that fails the bug build 3 of 3 and passes the clean game 3 of 3, on two of the
three menu probes. It does not show that a model, given the menu probes and their counter readings (#624),
proposes such a check. That needs the live dispatch on #285: `jit.yml` from main, `mode=repro`,
`offer=signals-reach-evidence-menu`, `budget_usd=2`.
