# Offline calibration loop and texture staleness (#330)

## What changed

Added an opt-in player calibration loop, shared by exact recorded SAM answers and the frozen #262
pixel sensor: propose from names/recorded phrases, score clean selection, prove on disjoint clean
and four patched copies, and write/recheck the new observer-calibration/v1 contract. Reader,
schema, stand-in example and format registry ship together. An explicit gate wrapper checks art,
observer/version and bank/recording digests and applies the learned floor. It refuses stand-in records.
Point calibration RULES and existing anchored records are unchanged.

[Audit, results and commands](../observer-calibration.md) include every Done when case. The genuine
SAM blue-robot selection passes 13/13 exact stored answers; the ambiguous phrase and independent
proofs have no answers. The no-model observer passes 12/12 separate clean samples and fails all
13 samples on each of four broken copies. Its local-search and sample-size limits are explicit.

## What was run

- Required historic fetch for `c169a5e0da304773587304ed47bc8aabcec80da7`: completed before work.
- Baseline `python3 -m unittest discover -s tests -t .`: 4,629 tests, OK, 44 skipped (762.395 s).
- Focused new module: 20 tests, OK, including actual local pixel matching on throwaway images,
  contract validation, unknown-versus-absent, named misses, disjoint proof, floor propagation and
  real-gate stale-art behavior with test doubles.
- Final package/pattern/new-module preflight: 51 tests, OK. The first full run caught an equivalent SHA regex spelling absent from the registry; the established spelling fixed it without changing any existing test.
- Six local Godot 4.7.2 captures, no model: clean selection, clean proof and four patched variants.
  Frozen #262 bank and sensor; plans and native evidence are in the handover.
- Real saved-pixel gate path with a labelled replay transport stand-in: fresh accept → stale
  needs-review. The stale-art unit test fails (stale accept) with the digest check disabled.
- Final full suite: 4,649 tests in 843.576 s, OK (44 skipped). Missing NumPy/PIL: full discovery 4,686 tests, no load errors; new module 20 tests, OK (one image test skipped by name).
- Required export scan: 782 files, zero errors/warnings; no private scan or model calls.

## Not done

Part of #330. The genuine recorded SAM enemy-ambiguity comparison and independent clean/four-copy
proof remain missing; every unanswered copy is named in the published record. Outside live anchored
calibration is already recorded on main; no new live bundled automatic loop was run. Sean owns live
dispatch/budget. No general false-alarm or cross-game claim is made from this sample. All-object
bindings, arbitrary-game patch emitters and live phrase generation remain beyond this bundled-player
slice. No approval, workflow, game source, capability ledger, release dossier or jit file changed.

## Files

- `expectrail/calibration.py`, `expectrail/contracts.py`, `setup.py`
- `agents/calibration_observers.py`, `agents/calibrate_observer.py`, `agents/calibration_copies.py`
- `contracts/observer-calibration.v1.schema.json`, `contracts/examples/observer-calibration.json`
- `tests/test_observer_calibration.py`
- `docs/observer-calibration.md`, `docs/calibration-330/`, this entry
