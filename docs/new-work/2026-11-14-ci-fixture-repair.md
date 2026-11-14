# Run fixture repair on the labeled pull request (#433)

## What changed

A maintainer can request a repair after a published reject. Authorization checks the label,
the current pull request, the clearance publisher and the capture attempt before the repair
job can start. The repair job reproduces the reject with an isolated replay. Its fresh child
jobs use the base's recorded vision answers. The summary and artifact show the repair outcome.

## What was run

- `python3 -m unittest -v tests.test_ci_autofix tests.test_apt_install tests.test_downloads tests.test_workflow_expressions` ran 36 tests and ended in OK.
- The offline fixture produced a record and a patch on accept, and just the record on needs-review.
  The winning patch passed the summary's dry run against the rejected checkout.
- A real worker on a host missing xvfb-run stopped before repair and produced no artifact.
- The handover contains the full before and after suite logs and the comparison by test name.

## Not done

GitHub Actions, a hosted runner replay and live providers were not run. Only a fixture patch
can be proposed. A person reviews and applies any accepted patch.

## Files

- `.github/workflows/expectrail-autofix.yml`
- `.github/actions/apt-install/action.yml`
- `.github/actions/get-godot/action.yml`
- `tools/ci_autofix.py`
- `expectrail/repair.py`
- `tests/test_ci_autofix.py`
- `tests/test_apt_install.py`
- `docs/ci-gate.md`
- `docs/new-work/2026-11-14-ci-fixture-repair.md`
