# Find the macOS engine outside a read-only wheel (#249)

## What changed

A wheel installation now looks for the macOS Godot bundle under the user’s tools cache.
Doctor’s no-fetch check, the replay and the integration-test prerequisite use the same
engine path. A checkout still defaults to its own `tools` folder. An explicit
`EXPECTRAIL_GODOT` selects the binary. Setting `EXPECTRAIL_TOOLS` selects the cache,
including for the manual checkout launcher. An older wheel can reuse a previously
installed executable inside its package when the user cache is empty and no tools
directory was explicitly selected.

Two installations using one cache can start at the same time. The installer locks
the cache directory, verifies and extracts the archive in a temporary directory,
then publishes the completed app by renaming it. The official SHA-512 pin is unchanged.

## What was run

On November 22, 2026, using main `b1c5539c` and Linux with macOS platform selection:

- Before the fix, an installed wheel with a read-only package directory missed an
  executable in `EXPECTRAIL_TOOLS`. Doctor reported it missing and the replay
  locator failed to create `_bundle/tools` before curl ran. The three new cold
  cache cases also failed. [Reproduction on #249](https://github.com/Expectrail/Expectrail/issues/249#issuecomment-7074748070)
- The extraction regression on the location fix alone failed because the final
  executable was already visible while unzip was paused. After staging and locking,
  both shell processes returned the same complete app and the curl stand-in ran once.
- `python3 -m unittest tests.test_downloads tests.test_doctor tests.test_platform_tools`
  passed with 69 tests run and one skip. The cases cover an empty checkout, the
  three wheel cache locations, legacy-cache reuse, explicit overrides, and a retry
  after a checksum mismatch. The invalid archive left the partial bundle intact.
- Built and installed `expectrail-0.1.0-py3-none-any.whl` into an empty venv
  offline. SHA-256 was `8bcccd19d1895f3c6b1990a1b3060128bd1af4fa7b1567386a287f9840295052`.
  With unmodified installed files and a read-only bundle directory, the replay and
  both doctor lookups found the named-cache executable. Curl ran zero times.

For cold installs, only the pinned digest **in the temporary installed helper** was
replaced with the digest of the stand-in ZIP. The package directory was set read-only
before lookup. The helper used real `shasum`, `unzip` and `chmod`. The synthetic
executable answered `--version`. Each case ran outside the repository.

| Wheel cache choice | Doctor on first fetch | Doctor with `--no-fetch` afterwards | Curl stand-in calls across cold and warm lookups |
| --- | --- | --- | --- |
| `$HOME/.cache/expectrail` | OK | OK | 1 |
| `$XDG_CACHE_HOME/expectrail` | OK | OK | 1 |
| `$EXPECTRAIL_TOOLS` with spaces in its path | OK | OK | 1 |

All three returned the expected external executable and left the installed bundle
without a `tools` directory. A separate run of the checkout’s `play_local.sh` in
a temporary sample tree selected the named-cache stand-in and forwarded the game
path and `--quit` without calling the downloader.

A separate offline wheel build from the same code exercised the shared lookup on
Linux with a real Godot executable in the named tools directory. Both installed
doctor commands exited 0 in the bundled recorded-sample profile. Godot reported
`4.7.2.stable.official.ed1daf0bf` and drew a frame using Mesa llvmpipe LLVM 19.1.7.
`EXPECTRAIL_VLM_SAMPLE_RECORDINGS=1 expectrail sample` exited 0 with three
completed jobs. Each used the real engine and the bundled recorded vision answers.

| Job | Input change | Decision |
| --- | --- | --- |
| `72707b731ae834d2a46bd8b3e88f062c` | Unchanged bundled game | Accept |
| `631b54f4efb3925a1bca29259fc94ddf` | Apply the fall-through bug | Reject |
| `203c8be49b0c9c35f8ce42a6c6275fb6` | Reverse the fall-through bug | Accept |

Full discovery (`python3 -m unittest discover -s tests -t .`) passed with 6,066
tests run and 57 skipped in 1,068.855 seconds. The nine lookup and prerequisite
tests passed with NumPy and Pillow imports blocked. The required historic fetch
succeeded. The export scan of `bench docs README.md apps` checked 1,371 files
with zero errors and zero warnings.

## Not done

Native macOS installation, Gatekeeper behavior and rendering still need a Mac.
The release tag and registry publication remain with Sean.

## Files

- `harness/run.py`, `harness/macos/get_godot_mac.sh`, `harness/macos/play_local.sh`
- `expectrail/doctor.py`
- `tests/test_downloads.py`, `tests/test_platform_tools.py`, `tests/tool_requirements.py`
- `docs/install.md`, `harness/macos/README.md`
- `docs/new-work/2026-11-22-macos-wheel-cache.md`
