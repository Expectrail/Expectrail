# Evidence for one bug build: what differs in the record and on the screen, per probe (#285)

## What changed
Part of #285, step 5 (proposal quality), as far as it goes without a model. Today a proposer is
given each probe's signals on the clean game and on the bug build. A signal is a reading of the
engine's record, so a bug that only shows on the screen gives it nothing, and a bug the record
shows late points it at the wrong moment.

`expectrail/repro/evidence.py` makes an evidence record for one bug build
(`expectrail.repro-evidence/v1`). Each probe is replayed with frames on the clean game twice and on
the bug build once, and a row says, from those same replays:

- **record**: the fields of the engine's record that differ, each with its first tick and on how
  many ticks, and the signals that read differently.
- **screen**: how many frames differ, the first one, the most pixels in one frame and the rectangle
  that holds them (the comparison of `expectrail.repro.screen`, exact).
- **observer**: where a folder of a visual observer's recorded answers is given, what it answered
  on the differing frames of both builds, per named object: on how many frames it found the object
  in each build, on how many in one only, and how far its surest box moved.

What differs between the two clean replays counts for nothing. A probe that cannot be replayed or
compared is an error row with one line of reason, and the other probes are still compared.

The observer is read and never asked. The module looks answers up in the vision adapter's answer
cache by the frame's bytes, the prompt and the model; it has no code that sends a frame anywhere,
and a frame with no recorded answer is counted as not answered. It reports numbers and applies no
threshold: it never says an observer saw the bug.

`evidence.for_proposer` is the bounded summary a prompt could carry: at most six probes, numbers,
and names its caller already has. The caller passes its own probe ids and object names; a row for
any other probe, an object under any other name and a record field that is not one of the trace's
own are counted, not named; a signal that is not a trace signal refuses the record. No error text,
prompt, model or renderer name is in it.

Changed after the merge guard's first review of #363: as first pushed, the summary copied probe
ids and object names from the record, which only have to fit the schema's pattern, while this file
said "names from closed lists only". A record renamed by hand put its own strings in the summary.
The names now come from the caller, and `problems` refuses a number that is not finite.

Schema, example, writer and reader in this one change: `contracts/repro-evidence.v1.schema.json`,
`contracts/examples/repro-evidence.json` (a recorded run), `expectrail.repro.evidence`. Two
commands: `python3 -m expectrail.repro evidence` and `evidence-render`.

**The generator is not offered any of it.** Nothing under `expectrail/jit/` and no workflow reads
the module, and a test holds that: issue #285 asks for the baseline before anything changes, and
the baseline has not been run.

## What was run
- **On the real engine** (Godot 4.7.2, Mesa llvmpipe, a cloud container, no model, not in CI),
  `python3 -m expectrail.repro evidence --defect <id> --jobs 2`, 249 replays with frames in all,
  about 52 minutes. The four records are `bench/jit/public/evidence-<defect>.json`:
  - `no-shooting-in-air` on the 8 reach probes (the first capture of a reach probe with frames):
    1 probe shows it, in both: `projectiles` from tick 19, `projectile_count` 1 to 0, 30 of 80
    frames from frame 9. The other 7 show nothing.
  - `bullet-behind-scenery` on the 25 library probes: screen only on 6, nothing on 19.
  - `enemy-walks-backwards` on the 25: screen only on all 25, from frame 0.
  - `coin-stays` on the 25: record and screen on 10, screen only on 2, nothing on 13. Frames differ
    from frame 26 (tick 52) and the record's `coins` from tick 174 on every probe that gets that
    far; the two screen-only probes end before tick 174. By reading `level/coin.tscn`, the clean
    game removes a touched coin from the tree one second into its pick-up animation.
  - No frame, field or signal differed between the two clean replays on any probe; no replay was
    made again; no error row.
- **Against the screen measurement of November 12** (`bench/jit/public/screen.json`, another run of
  another command): for the three defects both measured on the same probes, the count of probes
  whose frames differ, the count whose record differs, the fields, and the whole row of the probe
  where most frames differ are equal. `tests.test_repro_evidence.TheRecordedEvidence` holds it.
- `python3 -m unittest tests.test_repro_evidence`: 56 tests, OK (52 before the review; the guard's
  case and three more are the four added). They use the simulated game; the
  observer's part reads answers the tests wrote into a cache folder, with the network calls
  replaced by ones that fail the test.
- Full suite on the branch merged with main 2f7e35a, `python3 -m unittest discover -s tests -t .`:
  2,617 tests, OK, 27 skipped. After the review's fix, merged with main dddced6: 2,625
  tests, OK, 27 skipped. This container has no bubblewrap; the reason for each skip was not
  listed.
- `python3 -m tools.merge_guard --base origin/main --head HEAD`: "nothing to report in 13 file(s)"
  (before this file's last edit).

## Not done
- **No answer of SAM or any other model was read.** None has been recorded for the bench's frames.
  The observer's part of the record is tested with answers written by the tests. Whether an
  observer reports any of these differences is not shown. Recording answers is a paid step for a
  person: for the 2 screen-only defects on one probe each, 8 frames a build on two builds and one
  prompt, 32 images, about $0.08 at the repository's price of $2.50 per 1,000.
- The evidence is not in the proposer's prompt, and no check has been generated from it.
- No reproduction rate: the baseline run has not been dispatched.
- Evidence was recorded for 4 of the 24 defects, not all: a defect takes about 16 minutes on two cores.
- Which objects an observer is read for comes from the caller (`--object NAME=PROMPT`). It should
  come from the project's bindings (#259) when those exist.
- Why the record of `no-shooting-in-air` differs for 141 ticks when the picture differs for 30
  frames was not looked into.

## Files
- `expectrail/repro/evidence.py`, `expectrail/repro/__main__.py`
- `contracts/repro-evidence.v1.schema.json`, `contracts/examples/repro-evidence.json`
- `bench/jit/public/evidence-no-shooting-in-air.json`, `evidence-bullet-behind-scenery.json`,
  `evidence-enemy-walks-backwards.json`, `evidence-coin-stays.json`, `bench/jit/public/README.md`
- `tests/test_repro_evidence.py`
- `docs/contracts.md`, `docs/jit.md`
