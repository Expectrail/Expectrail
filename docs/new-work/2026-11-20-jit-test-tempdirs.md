# The JIT test fixture removes its temporary folder

## What changed

`tests/jit_fixtures.Case` created a folder with `tempfile.mkdtemp(prefix="jit-test-")` and never
removed it. 25 test modules use it, most of them once per test, so a suite run left one folder behind
per test. On the architect's machine a count found **12,890 `jit-test-` folders and 176 `jit-held-`
folders**, which had filled the disk to 97% and would have started failing suite runs. Some callers
registered their own `shutil.rmtree`; most did not.

`Case` now registers a `weakref.finalize` that removes its folder when the object is collected, and at
interpreter exit otherwise. Callers that already clean up still work: removing a folder twice with
`ignore_errors=True` is not an error. `tests/test_trace_camera_coins.py` had the one other leak, a
`jit-held-` folder, and now registers `addCleanup` for it.

One test relied on the leak: `tests/test_jit_template_observer.EndToEnd.generate` made a `Case` as a
local, stored a path under its folder on `self`, and returned, so the folder had to outlive the `Case`.
It now keeps the `Case` on the test. That is the only behaviour this fix changed, and the suite found
it rather than a developer finding it later.

This is a test-hygiene fix. No product code, fixture content or assertion changed.

## What was run

- `tests.test_jit_rules`: 47 tests, OK, including two new ones: a dropped `Case` removes its folder,
  and `Case` registers a finalizer at all (so the leak cannot come back silently).
- `tests.test_trace_camera_coins`: OK.
- The full suite in 3 parts, and the export scan. Part 3 was re-run after the one test that relied on
  the leak was fixed: OK, and `ls /tmp | grep -c '^jit-test-'` gave **0** afterwards.
- Before the fix, `find /tmp -maxdepth 1 -name 'jit-test-*'` removed 16 GB.

## Not done

- Other prefixes seen in the same temporary directory (`expectrail-smoke-results-`,
  `expectrail-stub-root-`, `expectrail-submission-`, a few hundred each) are not fixed here. They are
  smaller and belong to other fixtures. Worth a follow-up with the same pattern.

## Files

- `tests/jit_fixtures.py`
- `tests/test_trace_camera_coins.py`
- `tests/test_jit_rules.py`
- `tests/test_jit_template_observer.py`
- `docs/new-work/2026-11-20-jit-test-tempdirs.md`
