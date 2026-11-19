# The macOS job records its own patch program and the tree after each control (#659)

## What changed
#659 asks for a native macOS record of the patch controls: the `patch` executable, its version, and the
file state after a deletion, an edit that empties a file, and one patch doing both. The macOS suite on
main shows that the three repair tests from #378 no longer fail after #662, but it records none of that.

- `tools/patch_controls.py` applies the three controls to fresh scratch copies, first with the raw
  `patch` command and then through `harness.patching.apply`, and writes the program's path, the first
  line of its version, and each file's state (absent, a file of N bytes, or not a file) after each.
  A control whose tree does not match the patch, or a machine with no `patch`, is written as such. It
  always exits 0, like the rest of the job.
- `harness.patching.command` is the command `apply` runs; the tool's raw run uses it, so the record
  measures the same command every candidate goes through. `apply` itself is unchanged in behaviour.
- `.github/workflows/macos.yml` runs the tool after the suite summary (`if: always()`), appending to
  the job summary, and also runs on pull requests that change the tool or `harness/patching.py`. No
  secret, environment, trigger type or permission was added.

## What was run
- Read from the API: the macOS suite on main at 048a871 (before #662) listed
  `test_fresh_verdict_overrides_recorded_accept`, `test_fresh_verify_uses_patched_bug_and_recorded_answers`
  and `test_metered_provider_only_record_is_replayed_without_claiming_a_sandboxed_agent` as failing. The
  runs at c8b851a (run 44592602819) and 3e27378 (run 44602738622) list none of them; their remaining
  failures are the orchestrator cancellation tests (#378) and the `film2` guard case.
- `python3 -m tools.patch_controls` here (Linux, GNU patch 2.7.6): every control left the named tree.
  Under GNU patch in POSIX mode (the test's emulation), the raw deletion leaves `BUG` with 0 bytes and
  `apply` removes it; POSIX mode also refuses the creation in `both`, and the report says it stopped.
- `python3 -m unittest tests.test_patch_controls tests.test_macos_suite tests.test_patching`: 46 tests, OK.
- The full suite on main 3e27378 plus this change, without the engine: 5,358 tests, OK, 67 skipped.

## Not done
- The native record itself comes from the macOS job on this pull request and on main after merge; it is
  read and copied to #659 then. Nothing here was run on a Mac.

## Files
- `tools/patch_controls.py` (new; added with `git add -f`, as most files under `tools/` are)
- `tests/test_patch_controls.py` (new)
- `harness/patching.py`
- `.github/workflows/macos.yml`
- `docs/new-work/2026-11-19-mac-patch-record.md`
