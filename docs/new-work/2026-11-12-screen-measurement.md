# What each bench defect changes on the screen, measured with no model (#285)

## What changed
Part of #285 (its bench and its miss diagnosis), and the measured denominator #286 asks for. Until
now the public bench knew what each defect changes in the engine's record. "Screen only" was a label
its author wrote and two replays made by hand and not kept. Sean's decisions of November 12 make
what is drawn something a generated check must be able to speak about, so the bench now measures it.

`expectrail/repro/screen.py` replays every probe with its frames captured, on the clean game twice
and on each defect build once, and compares the frames and the engine's record of the same replays
with the clean game's. Each defect is `record-and-screen`, `screen-only`, `record-only`, `neither`,
or `error` when it could not be measured:

- A frame differs when any pixel does (red, green or blue; alpha is not compared). The same picture
  in different file bytes is not a difference.
- A frame or a record field that differs between the two clean replays of a probe is unstable there
  and counts for no defect. Two clean replays of different lengths give no record at all.
- For the probe where the most frames differ, the row keeps how many, the first one, the most
  pixels in one frame and the rectangle that holds them, from at most eight frames decoded.
- What cannot be compared is an error row with its reason, never a guess: a capture of another
  length, a frame that cannot be read, an engine that fails three times, a script error.
- The comparison needs no image library (three exclusive-ors of large numbers a frame). Pillow
  decodes the frames when it is installed; the standard-library decoder does otherwise.

New record `expectrail.repro-screen/v1`: its schema (`contracts/repro-screen.v1.schema.json`), its
writer and reader (`expectrail.repro.screen`), and the committed record
`bench/jit/public/screen.json` as its example, in this one change. Two commands:
`python3 -m expectrail.repro screen` and `screen-render`.

Nothing generated checks run on reads any of it, so a live run on the bench, the baseline included,
is unchanged. A test holds that. No visual observer and no model is asked anything.

## What was run
- **On the real engine** (Godot 4.7.2, Mesa llvmpipe, a cloud container, no model, not in CI):
  `python3 -m expectrail.repro screen --out <dir> --jobs 2`, 25 probes on 26 builds, 650 replays
  with frames, about 2 hours 35 minutes. Result, which is `bench/jit/public/screen.json`: the record
  and the screen both differ for 19 defects, only the screen for 2 (`enemy-walks-backwards` on 25
  of 25 probes, `bullet-behind-scenery` on 6), only the record for 0, nothing for 3
  (`no-shooting-in-air`, `coin-counts-twice`, `coin-counter-stuck`), no error. No frame and no
  record field differed between the two clean replays; no replay was made again.
- The same command again with `--only enemy-walks-backwards --only bullet-behind-scenery` (100
  replays): both rows identical to the stored record's.
- `enemy-ledge` and `enemy-slides-when-shot` have the same screen row. Checked directly: one replay
  of `move-fire-right` on each of the two defect builds, compared with each other: 0 of 158 frames
  differ, and the record's `enemies` field does.
- Before the full run, the same code on 2 probes and 4 defects (12 replays): the two clean captures
  were identical and the four rows came out as in the full run's classes.
- One line of `screen.py` changed after the full run started and before it was committed:
  `_sample` reads its limit when called, not when defined, so a test can lower it. The frames it
  picks are the same.
- `python3 -m unittest tests.test_repro_screen`: 47 tests, OK. They cover two frames (same, counted
  and boxed, each corner, one shade in each channel, every pixel, alpha, two sizes, files that are
  not pictures) under both decoders; a simulated game that draws, with a defect of each class, one
  pixel on the last frame, the same picture re-encoded, a short capture, an unreadable frame, a
  crash and a script error; unstable frames and fields; the retry count; a record that disagrees
  with itself in 24 ways; the commands; and the stored record against the bench, the probes and
  the page.
- The full suite on the branch merged with main: in the pull request.

## Not done
- No visual observer was asked anything. Whether SAM, or the no-model sensor of #262, reports the
  differences this finds is not shown, and a live call costs money a person must approve.
- The reach probes were not captured with frames, so `no-shooting-in-air` is `neither` here though
  a reach probe shows it in the record.
- Generated checks are not offered any of this, and the closed language still has no predicate
  about what is drawn (#286). No model was called. There is still no reproduction rate; the
  baseline run waits for a person.
- The counts are exact for one renderer. No second machine or renderer was tried.
- The frames are not kept: the record holds numbers, and a reader cannot check them without
  running the command again.
- Not in CI: 650 replays with frames take hours.

## Files
- `expectrail/repro/screen.py` (new), `expectrail/repro/__main__.py`
- `tests/test_repro_screen.py` (new)
- `contracts/repro-screen.v1.schema.json` (new), `bench/jit/public/screen.json` (new)
- `bench/jit/public/README.md`, `docs/contracts.md`, `docs/jit.md`
