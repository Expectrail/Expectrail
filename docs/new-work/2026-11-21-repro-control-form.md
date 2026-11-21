# Why the do-nothing rule drops five public defects: the form of their checks (#285)

## What changed
- New command `python3 -m expectrail.repro control-form` (`expectrail/repro/control_form.py`). It reads
  every check of the 24 public baseline records, names the form of what it asserts, and lays that beside
  the do-nothing control's outcome from the committed rows. Rows bind by record and check digest, as in
  `control-rate`, and each record must be the file the score names.
- The forms: `holds-when-equal` (a relation that holds when both probes measure the same, judged with
  the evaluator's own comparator), `holds-when-still` (a bound on activity), `fails-when-equal` (a strict
  relation), `needs-activity` (a minimum a still actor cannot reach), and `other`, which is never guessed.
- `docs/repro-audit.md` has a new section, "Why the dropped defects' checks state no obligation". A test
  keeps its generated part equal to what the committed rows and records give.
- Finding, from the committed rows:
  - No check of a form a still actor satisfies fails the control: 0 of 79.
  - No strict relation passes it: 0 of 32.
  - The five dropped defects were reproduced only by such checks. Their records hold no check of a
    demanding form.
  - Each of the seven defects shown to state an obligation is shown by a strict relation or a demand for
    activity.
- Recorded, not changed: since #675 the revision step sends `passed-with-the-actor-doing-nothing` to the
  proposer, but the revision's system text does not explain it. That text is pinned for the baseline, so
  changing it needs its own setting and a live run.

## What was run
- `python3 -m unittest tests.test_repro_control_form tests.test_repro_control_rate`: 31 tests, OK.
- Full suite on this branch at main 7d86d92: `python3 -m unittest discover -s tests -t .`, 5,883 tests, OK, 75 skipped (no engine on this machine).
- No engine, no model, no dispatch. Nothing was spent.

## Not done
- No replay. The forms are a reading of each operation, and the committed rows are the evidence that
  the control agreed with them on this bench.
- The revision prompt is not changed (see above).
- No new check was proposed or measured for the five dropped defects.

## Files
- `expectrail/repro/control_form.py` (new)
- `expectrail/repro/__main__.py`
- `tests/test_repro_control_form.py` (new)
- `docs/repro-audit.md`
- `docs/new-work/2026-11-21-repro-control-form.md`
