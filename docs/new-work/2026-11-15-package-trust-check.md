# `expectrail trust-check` is built, and the receipt check is in the wheel (#255)

## What changed
`expectrail trust-check RECEIPT --trust-store FILE [--repo] [--expect-head] [--expect-build] [--expect-policy]`
was a planned command that said "not built yet (#255)" and exited 5. It now runs the receipt check
from `expectrail.receipt` (the same `check_receipt` and the same report as
`python3 -m expectrail.receipt trust-check`).

- Exit 0 is clearance, 1 is no clearance, 5 is "nothing was checked": a receipt or trust store that
  cannot be read (missing, not JSON, not UTF-8, not canonical) or a command line that cannot be read.
  Nothing is printed on stdout then. `python3 -m expectrail.receipt` keeps 2 for that case, as before.
- A file that is not UTF-8 text gave a traceback from both commands; it is now "nothing was checked".
- `expectrail.receipt` is in the wheel (`setup.py`), and finds its schema through `resources.ROOT`,
  so an installed copy reads `expectrail/_bundle/contracts/receipt.v1.schema.json`.
- A `trust` extra in `pyproject.toml` (`cryptography>=42`, `jsonschema>=4.20`). A verification still
  needs the standard library only. Without the extra, `expectrail trust-check` names the missing
  package and `pip install 'expectrail[trust]'`, checks nothing and exits 5.
- `cli.PLANNED` is empty. The mechanism stays and keeps a test with a made-up command.
- `docs/install.md`: the command table had `trust-check` and `repair` as not built; `repair` is built
  and now has its own row, and `trust-check` has its row and the extra.

## What was run
- `python3 -m unittest tests.test_trust_check_command tests.test_receipt tests.test_package tests.test_doctor`: OK.
  `tests.test_package` built the wheel here and ran both installed-copy tests (not skipped).
- The full suite on the branch merged with main at 9ba5c38: 3,896 tests, OK, 40 skipped.
- Three mutations, each caught: the schema path left beside the package (the installed test fails),
  every missing module reported as the extra (three tests fail), and `ValueError` not caught (four errors).
- CI: not read when this was written.

## Not done
- What is left on #255: CI attestation (`id-token: write`, `attestations: write`: Sean's), writing the
  receipt from the trusted job, a real CI receipt through `gh attestation verify` and `trust-check`,
  and the trust store's distribution and rotation.
- The capability ledger has no receipt row yet; the signing row's limits still say there is no
  offline trust store or receipt. Not changed here.
- The installed-copy test puts the host's `cryptography` and `jsonschema` on `PYTHONPATH`; a
  `pip install '.[trust]'` from an index was not run.

## Files
`expectrail/cli.py`, `expectrail/receipt.py`, `pyproject.toml`, `setup.py`, `docs/install.md`,
`tests/test_trust_check_command.py`, `tests/test_package.py`, `tests/test_doctor.py`,
`docs/new-work/2026-11-15-package-trust-check.md`
