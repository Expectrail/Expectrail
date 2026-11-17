# Frozen-bank agreement, false alarms and pixel-only absence proof (#262)

## What changed

Added a generated closeout measurement and an exact Done when audit for #262.
The current main sensor and all its thresholds/bank inputs stayed frozen. Main's
clean-only calibration recipe made 556 templates before evaluation capture began.
An omitted bank-schema hash was added to the freeze before any capture; the original plan is retained. Two new action schedules and all three existing seeded patch sets were specified
before capture/matching. Every captured frame was evaluated; primary rates exclude
historical/calibration PNG hashes using a rule fixed before scores existed.

The machine report contains per-frame status, PNG digest, new-pixel selection,
region events, source hashes and recomputable counts. A versioned schema, synthetic
example, writer and strict reader ship together. The reader refuses stale figures,
unknown-as-pass, missing frames, changed evidence, forged pairings and changed
pre-evaluation counting rules. The detector and default observer/gate paths are
unchanged. No capability ledger or release dossier file was edited.

The untuned clean-frame sample: 223/227 agreement (98.24%), 4/227 clean false alarms
(1.76%). The two routes individually have 2/115 and 2/112 alarms. Invisible-player
has 73 matched-clean/new-pixel alarms under identical complete engine traces; hidden
PNGs were judged with the clean trace. The original draw-order fixture is not absent
in every frame, so these are not independently labelled recall numbers. Historical
2.35% and cross-game failures remain valid and published.

## What was run

- Required historic fetch completed before baseline; branch/base is d877ddb647161e4af28aa554e7886d91e1b83f5b.
- Before: `python3 -m unittest discover -s tests -t .`: 4,603 tests, OK (44 skipped), 824.676 s, no EXPECTRAIL_* shell variables.
- Real Godot calibration + five captures; all 600 evaluation frames matched with the frozen sensor/bank. No model called.
- Frozen plan and counting rules recorded before matching. The exact sensor/game/patch/bank/capture hashes were checked again by the report reader.
- Focused sensor/schema/report tests: 89 tests, OK. After: `python3 -m unittest discover -s tests -t .`: 4,616 tests, OK (44 skipped), 771.605 s. With numpy/PIL blocked, all 4,653 tests load without errors; 169 selected tests run, 98 skip by name. Two isolated guard-removal runs make their regression tests fail; source files stay unchanged.
- Required export scan command: `python -m agents.export_scan bench docs README.md apps --paths error` — 767 files, zero errors/warnings; final repeat and logs in handover.

## Not done

No dispatch, workflow, real approval, source-game edit, live model or spend. No
verdict-readiness, speed, independent frame-recall or cross-game claim. This closes
#262's scoped diagnostic measurement cases; it does not erase the earlier untuned
2.35% route result or add default release-gate eligibility.

## Files

- `tools/template_sensor_closeout.py`, `.gitignore`: strict artifact reader and generated tables.
- `contracts/template-closeout.v1.schema.json`, example, `expectrail/contracts.py`: new record, both sides.
- `tests/test_template_closeout.py`: accounting/forgery/unknown/pairing tests and named optional-pixel test.
- `docs/template-sensor-closeout*.md`, `docs/measurements/template-closeout-*.json`: audit, generated measurement, frozen plan and source provenance.
