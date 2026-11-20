# Concurrent Linux setup can safely share the pinned Godot install (#677)

## What changed

The Linux installer returns an existing editor immediately. On a cold start it locks the shared install directory and checks again. One caller downloads and verifies the archive, extracts into a temporary directory on the same filesystem, sets the executable bit and renames the finished editor into place. A waiting caller can then return that path and run it immediately. If extraction stops, a later call can retry with the verified archive.

## What was run

- Both regression tests failed against the original script. The final executable was visible while the extractor held it open for writing, and a failed extraction left it there.
- `python3 -m unittest tests.test_downloads` passed all 12 tests, including overlapping consumers that immediately execute the returned path and a retry after a failed extraction. The concurrent case also passed 25 consecutive runs.
- Sending `SIGKILL` to an installer's process group while the fixture held the executable open left the final path absent. The next install acquired the lock, reused the verified archive and ran the fixture.
- Two processes simultaneously called `bash harness/get_godot.sh` with one empty temporary `EXPECTRAIL_TOOLS` directory. One verified the download, the other reused the editor, and both immediately ran `--version` and printed `4.7.2.stable.official.ed1daf0bf`. The download cache was empty afterward.
- The integrator repeated the simultaneous cold `expectrail init` commands on two copies of public Breakout. Paddle exited 0 and wrote a pending setup with the same 303-event route. Ball exited 5 with the missing movement or pointer control explanation and wrote no setup. All 105 source-file hashes matched on each copy.
- The required historical fetch of `c169a5e0da304773587304ed47bc8aabcec80da7` succeeded.
- `python3 -m unittest discover -s tests -t .` finished in 502.729 seconds with 5,429 tests, 76 skipped and no failures or errors.
- `python3 -m agents.export_scan bench docs README.md apps --paths error` scanned 1,239 files with zero errors and zero warnings.

## Not done

The runs above cover the Linux installer. The macOS installer uses a separate script. A process killed with `SIGKILL` can leave a temporary extraction directory because its cleanup trap cannot run.

## Files

- `harness/get_godot.sh`
- `tests/test_downloads.py`
- `docs/new-work/2026-11-19-concurrent-godot-install.md`
