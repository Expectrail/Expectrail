# Check an explanation against every citation (#645)

## What changed

A point can describe a route as passing only if every id it cites passed after the change. The same rule applies to failing words. The viewer prints the before and after evidence for every citation, including ids the author cited without stating a verdict. If a passing or failing word conflicts with a cited result, or a cited id has no after verdict, the viewer withholds the explanation.

## What was run

The regression run of `python3 -m unittest tests.test_explanation` reproduced nine failed assertions on the original implementation. All 32 tests passed with the change, including the two single-route controls and the offline viewer check.

On main `9218e13a` with this patch, `python3 -m unittest discover -s tests -t .` ran 5,178 tests in 491.406 seconds and passed with 71 skipped. The public export scan (`python -m agents.export_scan bench docs README.md apps --paths error`) checked 1,008 files with zero errors and zero warnings.

## Not done

An unaided Godot developer session has yet to exercise this explanation.

## Files

- `contracts/explanation.v1.schema.json`
- `contracts/examples/explanation.v1.json`
- `expectrail/explanation.py`
- `tests/test_explanation.py`
- `docs/viewer.md`
