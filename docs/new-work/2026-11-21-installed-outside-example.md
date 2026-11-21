# Ship the recorded outside example's project configuration (#249)

## What changed

The wheel and the curated quickstart checkout now include
`contracts/examples/project-recorded.json`. The installed
`python -m expectrail.app_kinematic` command needs this file to prepare the
kinematic-character example described in `docs/app.md`.

## What was run

Before the fix, the installed command exited 2 with
`project-recorded.json: no such file`. The wheel rebuilt from the curated
source distribution also lacked that file.

```sh
EXPECTRAIL_PACKAGE_TESTS=required python3 -m unittest -v \
  tests.test_package.InstalledTest.test_installed_outside_example_prepares_the_published_files \
  tests.test_package.QuickstartPackageTest
```

All four tests passed on Python 3.12.14. From outside the checkout, the installed
command prepared a minimal project and exited 0. The test compared all eight
output files byte for byte with their sources, including the existing approved
check, route, recording, calibration and project configuration. The wheel rebuilt
from the curated source distribution contained the exact published configuration.

The same command ran on the public kinematic-character game at upstream
`b761b4cd`. The original wheel exited 2. The corrected wheel, installed in a
new environment, exited 0. Its 22 game files and five setup files matched the
checkout's preparation byte for byte. This rehearsal ended at project preparation.
[Recorded comparison](https://github.com/Expectrail/Expectrail/issues/249#issuecomment-7054143305)

## Files

- `pyproject.toml`
- `tools/quickstart.py`
- `tests/test_package.py`
- `docs/new-work/2026-11-21-installed-outside-example.md`
