# Installed sample fixture imports (#257)

## What changed

The sample test added by #589 runs outside the repository in a clean wheel installation. Its replay fixture now imports the sandbox and tree modules from `expectrail._bundle.harness`, where the wheel installs them. The test continues to exercise the installed entry point, gate, and evaluator without optional dependencies.

## What was run

`python3 -m unittest tests.test_package.InstalledTest.test_installed_sample_checks_new_capture_without_optional_packages` failed on clean main with a missing top-level `harness` import and passed with the corrected fixture. It checked the original exit code, all three decisions, and the saved sample evidence. The integration test results are recorded in the pull request.

## Files

- `tests/fixtures/installed_sample.py`
- `docs/new-work/2026-11-18-installed-sample-imports.md`
