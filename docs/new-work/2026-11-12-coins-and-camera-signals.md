# Coins and the camera reach the episode, and three signals read them; the generator is not offered them yet (#285)

## What changed
The public bench's no-model measurement (November 11) found three defects whose symptom is in the
engine's record in a field no signal read: `camera-stops-right` and `camera-cut-top` (the `view`
field) and `coin-stays` (the `coins` field; it counted as "a signal moves" only because an enemy's
drop changed by a hundredth of a pixel). This is step 4 of the issue for those three.

- **The episode keeps both fields.** `expectrail/trace/normalize.py` copies `view` and `coins` into
  every sample and says in `capabilities` whether the trace has them. The recorder finds the coins
  once and then writes `coins` only on rows that still have one, so when any row has the key, a row
  without it has none left; when no row has it, the trace cannot say, and the samples carry `null`.
  A malformed `view` or coin is refused, like the other fields. `contracts/episode.v1.schema.json`
  gains the two sample fields and the two capabilities as optional, so an episode written before
  today still validates and reads as "no reading".
- **Three signals** in `expectrail/trace/signals.py`, each a number over one replay, usable in a
  `relation` between two probes like every other signal (`contracts/trace-spec.v1.schema.json`):
  `coins_collected` (coins on the first tick less those on the last), and
  `player_screen_x_range_px` and `player_screen_y_range_px` (how far apart the player's extreme
  places on the screen are, in frame pixels). The screen place of tick t uses the view logged on
  tick t + 1, the rule `agents/observations.py` already measured against the image scroll. The
  ticks before the engine first applies the camera are left out: on the bundled game the view is
  the identity on the first two rows, which read as a 310 px jump across the screen before this
  rule.
- **The generator is not offered them yet.** The issue asks for the baseline "before changing
  anything", and that run has not been made. `expectrail/jit/intent.py` holds the three in
  `NOT_YET_OFFERED`: they are not named or explained in the system prompt, a measured value of one
  does not reach the user prompt, a check the model proposes on one is dropped with a diagnostic,
  and a saved proposal with one is refused. Offering them is moving three entries from that table
  to `SIGNAL_MEANINGS`, after the baseline is recorded.
- The committed visibility record and its table are left as measured on November 11. They describe
  what the generator can use in the baseline run, and the scorer reads its miss reasons from them.
  The bench's page says what the three signals read and gives the command to see it.

## What was run
- `python3 -m unittest tests.test_trace_camera_coins`: 28 tests, OK. The normalizer (both fields,
  the row without `coins`, a trace that never names coins, nine malformed values, an episode from
  before the fields, the example trace), each signal on made-up traces (a camera that follows, one
  that stops, one that does not go up, the one-tick pairing, the ticks before the camera, a gap, a
  scaled view, no camera), a relation on each that passes where the game is right and fails where
  it is not, and the hold on the generator.
- **The system prompt is the same text.** `sha256(SYSTEM + REVISE_SYSTEM)` is
  `544810189b454f8be6fd696e9c5882fa701676f4691730c47a9212e09d845b5a` on this branch and on an
  extract of `origin/main` at `b76d90c`.
- **On the real engine**, Godot 4.7.2, in a cloud container on November 12, not in CI, no model:
  every one of the 25 library probes replayed on the clean game twice and on each of the 24 defect
  builds once (650 replays, none made again), keeping the raw rows, and the three signals computed
  from those rows by this branch's normalizer and signal code. The clean game's two replays gave
  the same three readings on all 25 probes.

  | Defect | Signal | Probe where it moves most | Clean | Defect | Probes where it moves |
  | --- | --- | --- | --- | --- | --- |
  | `camera-stops-right` | `player_screen_x_range_px` | `hold-right` | 5 | 191.69 | 6 |
  | `camera-cut-top` | `player_screen_y_range_px` | `jump-l40-x8` | 169.81 | 203.37 | 1 |
  | `coin-stays` | `coins_collected` | `hold-right` | 5 | 0 | 10 |

  One of the three also moves on 7 other defects, each of which already moved an older signal
  (`air-jump`, `double-jump-once`, `jump-always-full`, `jump-needs-rest`, `platforms-not-solid`,
  `slides-after-stop`, `slow-left`), and on none of the remaining 14. So with them a signal moves
  on 19 of the 24 where it was 17, and the five defects the record does not show are unchanged.
  That script is not in the repository.
- The command the bench's page gives, on this branch and the same engine:
  `python3 -m expectrail.repro visibility --out <dir> --only camera-stops-right --only camera-cut-top --only coin-stays --jobs 2`.
  Its record sorts all three as `signal` (two were `trace-only`), with the readings in the table
  above, nothing unstable between the clean game's two replays and no replay made again. The
  record was not committed.
- The full suite and `python3 -m tools.merge_guard --base origin/main --head HEAD`: the results are
  in the pull request.

## Not done
- **No live run and no reproduction rate.** Nothing here was shown with a model. Whether the model,
  once offered these signals, proposes a check on them that passes on the clean game 3 of 3 is not
  known.
- **`camera-cut-top` is weakly visible.** One probe reaches high enough, and the clean game's
  reading there is 169.81, not near zero, because the camera starts on its lower limit. A relation
  on it needs a tolerance fitted between two measured numbers. A signal for "the player is off the
  screen" would say it directly and needs the frame's size, which the trace does not carry.
- The closed language still has no operation that bounds a signal on one probe; a new signal is
  only usable in a relation between two probes.
- The visibility record was not measured again and the three signals are not offered. Both wait for
  the baseline run, which a person dispatches.
- Discovery's planner is given every signal's reading (`signals.summary`), so a live discovery run
  with the planner on would now see these three as well. No discovery run was made.
- The five defects the record does not show (`no-shooting-in-air`, two screen-only, two behind the
  pause menu) are untouched: they need reach or pixels, not a signal.

## Files
- `expectrail/trace/normalize.py`, `expectrail/trace/signals.py`, `expectrail/jit/intent.py`
- `contracts/episode.v1.schema.json`, `contracts/trace-spec.v1.schema.json`
- `tests/test_trace_camera_coins.py`
- `docs/jit.md`, `docs/contracts.md`, `bench/jit/public/README.md`
