# Read-only engine setup measurements (#260)

## What changed

Added runtime `inspect --at-tick` and `calibrate` to the existing setup command
path, reusing configured role observations and Unity's calibration statistics.
Added the setup-report schema, real example, writer and strict semantic reader in
one patch. Missing measurements are explicit, three whole traces are compared,
local engines are never downloaded, and output stays outside the source project.
Init proposes a valid capture divisor for non-60 Hz projects. The wheel includes
the calibration helper used by the installed command. Unity's default report,
observation modules, verifier and game sources are unchanged.

The recorded bundled and config-lane reports, independent hand arithmetic, named
routes, and verification limits are in `docs/onboarding-calibration.md` and
`docs/onboarding-evidence-260/`. No real approval was created or changed.

## What was run

Base: main `21fde1b4be9362d209852e3d44221d059d110643`, also the advertised claimed
branch head at task start. Read AGENTS.md and #260/#259 bodies and all comments.
Ran the required historic fetch (handover log `historic-fetch.log`).

- Full suite before changes: 4,719 tests, 44 skips, passed (900.090 s).
- New tests on unchanged main: red, 15 tests, 5 failures and 14 subtest errors.
  Missing command/API and invalid 45 Hz proposal were demonstrated.
- Focused setup/previous init/project audit/schema tests: 45 passed.
- Final focused setup/init tests without numpy/PIL: 25 passed.
- Contract/pattern checks: 15 passed. Package tests: 21 passed.
- Real headless inspect plus three clean calibration replays per project: both
  120/120 player-visible frames, 0/120 unjudgeable frames; three byte-identical
  traces each. Hand arithmetic matches every measurement and statistic.
- Real verify CLI with each proposed config and the existing unchanged public
  check: engine pass; completed needs-review (exit 2), not acceptance.
- Final installed wheel with no numpy, PIL or jsonschema: command passed; all
  120 config-lane measurements and statistics equal the source-checkout report.
- Full suite after changes: 4,738 tests, 44 skips, passed (909.851 s).
- All 4,775 discovered tests load without numpy/PIL; zero import errors.
- Export scan: 839 files, zero errors and warnings (rechecked at handover).
- Default Unity byte parity also passed on a separate populated synthetic record.

## Not done

No spend, live model, workflow, dispatch or GitHub write. No source game edits.
Only metadata was saved in disposable copies for verification. The old public
spec was copied byte-for-byte, not approved. The draft config, legacy approval
and absence of vision still prevent acceptance. Init remains static; its dry-run
does not execute project scripts. Part of #260; see the documentation's explicit
remaining cases. The generated first route was validated, but these recorded
verification and hand-check runs used the named public smoke/walk routes.

## Files

`expectrail/onboarding.py`, `expectrail/cli.py` (setup dispatch),
`agents/unity_observations.py` (calibrate only), `expectrail/contracts.py`,
`contracts/setup-report.v1.schema.json`, `contracts/examples/setup-report.json`,
`setup.py` (one calibration helper in the existing module whitelist),
`tests/test_setup_calibration.py`, this entry, `docs/onboarding-calibration.md`,
and the four recorded reports under `docs/onboarding-evidence-260/`.
