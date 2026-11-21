# Installing Expectrail

Expectrail is a Python package with one command, `expectrail`. This page says how to install it,
what the package holds, and what is not built yet. It is not on PyPI: publishing needs an account
and a token, which only a person sets up (#249).

## Install and open the local app

### Ubuntu 24.04 on a 64-bit Intel or AMD computer

For an internal rehearsal, use the `expectrail_<version>_amd64.deb` provided by
your maintainer. Open the file in **App Center** or your graphical package
installer and choose **Install**. If double-clicking opens an archive viewer,
use the file's **Open With** menu to choose the package installer. Ubuntu may
ask for permission or download system packages.

Open **Applications**, search for **Expectrail**, and select it. In your default
browser, choose your **Before** and **After** project folders, then select
**Check folders**. Installing the app supplies the launcher and replay tools.
The first replay still needs the pinned Godot engine, and live vision requires
the settings described below. The package is a rehearsal build. A public release
and a timed, unaided session on a developer's own game are pending.

A maintainer can reproduce the candidate on Ubuntu using the build dependencies
in `requirements-build.txt`, `dpkg-deb`, and the existing release wheel:

```sh
python3 tools/build_deb.py --output-dir dist dist/expectrail-*.whl
```

### Install from the wheel on Linux or macOS

Download `expectrail-0.1.0-py3-none-any.whl` to **Downloads**. Ask your
maintainer for the wheel with the Expectrail launcher. On a prepared Linux or
macOS computer, open **Terminal**, paste this single line, and press Enter:

```sh
python3 -m venv "$HOME/.local/share/expectrail/app-env" && "$HOME/.local/share/expectrail/app-env/bin/python" -m pip install --no-deps --force-reinstall "$HOME/Downloads/expectrail-0.1.0-py3-none-any.whl" && "$HOME/.local/share/expectrail/app-env/bin/expectrail" app --install-launcher && "$HOME/.local/share/expectrail/app-env/bin/expectrail" app --open-browser
```

The first launch keeps Terminal open while you work. In the browser, enter the
**Before** and **After** folder paths, click **Check folders**, then **Verify**.
Use **Require the replay sandbox** to stop verification if isolation is
unavailable. The result shows how the replays ran.

On later visits:

- **Linux:** Open **Expectrail** from the applications menu. To open the launcher
  from your file manager, go to `~/.local/share/applications` (or the
  `applications` folder in your configured XDG data directory) and double-click
  `expectrail.desktop`. Some desktops ask you to trust the local launcher first.
  This opens the browser without a Terminal window. Closing the browser leaves
  the local server running until you log out.
- **macOS:** In Finder, open **Applications** in your home folder and
  double-click **Expectrail.command**. macOS opens a Terminal window for the
  app and then opens the browser. You can leave Terminal alone while you work.
  Closing that window stops the local app.

Python 3.12 or later with `venv`, a default browser, and the system Godot replay
tools must be ready first. Installing or updating **from the wheel** uses Terminal on both
systems. Your maintainer may also need Terminal for system tools, preparing
project checks and routes, and configuring live vision. macOS lacks Bubblewrap,
so requiring the replay sandbox there stops the job. The macOS launcher file
was checked with a POSIX shell on Linux. Finder and macOS replays were not run.

## From a checkout

```bash
python3 -m pip install .          # in a clone; Python 3.12 or later
expectrail --version              # says "installed package" and where its files are
expectrail doctor                 # does this machine have what a verification needs? names the fix for what is missing
expectrail sample                 # three real verifications of the bundled game: accept, reject, accept
```

`expectrail sample` needs what any verification of a Godot project needs from the system: a
virtual display (`xvfb-run`), Mesa's software OpenGL, and `patch`, `curl` and `unzip`. Godot itself
is fetched on first use (4.7.2, checked against its SHA-512) and kept in the user's cache folder,
`~/.cache/expectrail` (or `$XDG_CACHE_HOME/expectrail`; `$EXPECTRAIL_TOOLS` names another place, and
`$EXPECTRAIL_GODOT` names an engine binary to use as it is). `expectrail doctor` checks all of this
and names the fix for each missing piece.

## `expectrail doctor`

```bash
expectrail doctor                 # exit 0: nothing required is missing; exit 3: something is
expectrail doctor --json          # one expectrail.doctor/v1 document (contracts/doctor.v1.schema.json)
expectrail doctor --isolated      # also require the replay sandbox, as the isolated class does
expectrail doctor --no-fetch      # only look for the engine; do not download it
```

It checks the machine and is not a verdict on any change. Each piece is checked the way a run uses it:

| Piece | How it is checked | Required |
| --- | --- | --- |
| Python | 3.12 or later | yes |
| Godot | found as a replay finds it (so the first `doctor` fetches it, SHA-512 checked), and `--version` says 4.7.2 | yes |
| A virtual display | `xvfb-run` is on the PATH (Linux; not checked elsewhere) | yes |
| OpenGL | the engine draws one frame of an empty project, started as a replay starts it, and names its device. A device other than Mesa's `llvmpipe` passes with a note: every recorded run used `llvmpipe` | yes |
| Free disk | 1 GB in the engine's folder and the temporary folder (the engine is 140 MB; one replay's 120 frames were 24 MB) | yes |
| The replay sandbox | bubblewrap, by the probe a replay uses | only with `--isolated` |
| `patch` | on the PATH: `sample` and seeded bugs put a patch on a copy of the game | yes |
| `curl`, `unzip` | on the PATH: they fetch the engine | no; when the engine cannot be fetched, the engine's own line names them |
| A vision key | `MODEL_API_KEY` is present in the environment; its value is never printed. A `.env` file is not read | yes |
| A vision spend cap | `EXPECTRAIL_SAM_USD_CAP`, a finite amount in US dollars, 0 or more; doctor reports its value | yes |

Verification (`expectrail verify`, `expectrail sample`, and the app through verify) needs
`MODEL_API_KEY` and `EXPECTRAIL_SAM_USD_CAP` in the verifier's environment. It judges with both the
engine's record and a `FramesObserver`; an accept needs both. Without either setting, nothing is
sent to the model, but the game still replays and its engine checks run. An engine failure
**rejects**; otherwise the result is **needs-review**. A `PROVIDER_FAILED` diagnostic names each
missing setting and its fix. There is no command option for an engine-only accept. `expectrail doctor` checks both settings
without printing the key, and `expectrail report` names the observers that judged.

Cost depends on frames, checks and cached answers. [The recorded costs in sam.md](sam.md)
describe **up to $0.60 for both prompts over one 120-frame run**, at $2.50 per 1,000 images.
More routes or checks add work; cached answers reduce it. This is not a price guarantee for another project. The spend cap is
the most one run may send, in US dollars; reaching it gives no answer, never an accept on silence.

**`doctor` and a run cannot disagree about a tool.** The engine's preflight
(`GodotGate._tools`) asks `expectrail.doctor.for_run()`, the part of the same list every run needs
(Godot, the display, OpenGL, disk), checked by the same functions. So when `doctor` passes, a job is
not stopped for a missing tool, and when a job is stopped its `TOOL_MISSING` diagnostic carries the
same words and the same fix. `doctor` asks for more than the preflight (`patch`, Python), never less.
This makes the preflight stricter than it was: it used to look only for the engine's file and
`xvfb-run`, and now also asks the engine its version and has it draw a frame (0.7 s on one machine).

In a clone nothing changes: `python3 -m expectrail.orchestrator ...` and every other `python3 -m`
entry point work as before, and the engine stays in `tools/`.

## The command

| | |
| --- | --- |
| `expectrail verify`, `status`, `cancel`, `report` | Verification as a job ([orchestrator.md](orchestrator.md)). The same code, options and exit codes as `python3 -m expectrail.orchestrator`. `--jobs-root DIR` goes after the command, as with `app`. |
| `expectrail sample` | Three real runs on the bundled game and a seeded bug. Exit 0 only when they decide accept, reject, accept. |
| `expectrail --version` | The version, whether this copy is a clone or an installed package, and where its files are. |
| `expectrail doctor` | Checks the machine (above). Exit 0 or 3. Not a verdict. |
| `expectrail repair JOB` | Proposes and verifies a fix for a rejected job (`expectrail repair --help`). |
| `expectrail trust-check RECEIPT --trust-store FILE` | Checks an `expectrail.receipt/v1` against a trust store you already hold, with `--repo`, `--expect-head`, `--expect-build` and `--expect-policy` for what it must be about, and prints what it does and does not establish. Exit 0 clearance, 1 no clearance, 5 when nothing could be checked. Needs the `trust` extra (below); without it, it names the package to install and checks nothing. The same check as `python3 -m expectrail.receipt trust-check`, which exits 2 instead of 5. |

A command line that cannot be read (a missing or unknown option, on any command) exits 5, with the
usage on stderr and "Nothing was run". It was 2 until November 12, 2026, which is also needs-review.

## What the package holds

The wheel holds what a verification runs, and nothing that could not work from an installed copy.

- **In it:** the gate and the orchestrator (`expectrail.gate`, `expectrail.orchestrator`) and the
  modules they import; five harness modules (`run`, `sandbox`, `tree`, `adapters` and the package's own); the
  reader of the engine's position log, the frame observer and its model clients; the contract schemas; the bundled Godot game, the smoke
  route, one approved spec and one seeded bug, which are what `sample` runs.
- **Not in it:** the demo fix loop and the dotenv key loader; the repair command does ship its
  fixer and sandbox. Also excluded: the benches and the
  check generator (`expectrail.discovery`, `jit`, `repro`); every other seeded bug; anything
  held out. `tests/test_package.py` lists each part of `expectrail` that is left out, with why.
- **No dependencies.** A verification imports the standard library only. `jsonschema` is an extra
  (`pip install 'expectrail[contracts]'`) for checking documents against the schemas.
  `trust-check` needs `cryptography` and `jsonschema`, the `trust` extra
  (`pip install 'expectrail[trust]'`); a verification does not need them.

One top-level name is installed: `expectrail`. The wheel builder qualifies harness and agent
imports under `expectrail._bundle` and removes the old installed-copy path bootstrap from its
staged code. That covers import statements and a module name given as a literal string to
`importlib.import_module`, `__import__`, `importlib.util.find_spec` or `runpy.run_module`; a
relative name is left as it is. The build stops instead of guessing when such a call's module name
is not a literal, or when another string is exactly a harness or agents module name (as in
`-m agents.loop`). `tests/test_package.py` checks that no packaged module keeps one. It does not modify repository implementations. Importing the installed copy changes
neither `sys.path` nor another package’s top-level `harness` or `agents`. `expectrail.resources.ROOT` is the one name for "where Expectrail's own
files are" in a clone and in an installed copy.

## A release

`.github/workflows/release.yml` builds the wheel for a version tag and attaches it to the run:

- A tag `v<version>` builds from that commit, and only when it is the package's own version
  (`expectrail/__init__.py`); any other tag builds nothing and says why. A dispatch builds from main
  only, to try the workflow.
- The wheel is installed into a clean venv and its command must say "installed package" and the
  version. The wheel and its SHA-256 go up as the run's artifact `expectrail-<version>-wheel`, kept 90 days.
- It reads only and holds no secret. It publishes nowhere: PyPI or a container registry needs an
  account and a token, and pushing the tag is a person's step too.

It has not run yet: no tag has been pushed and it has not been dispatched.
`tests/test_release_workflow.py` runs its version step in bash and checks its shape.

## Limits

- Repository `python3 -m harness...` entry points remain unchanged. In the wheel, use the private
  qualified modules; the package no longer installs top-level `harness` or `agents` aliases.
- Linux only as packaged. The macOS engine script is in the wheel and was not run from an installed copy.
- Not shown: Python below 3.12; an install from PyPI. The engine download itself from an installed
  copy with no cached file was run once by hand (`expectrail doctor` with an empty home, November 12,
  2026, 5.6 s); CI does not do it: it hands the installed copy the download it already holds, and
  the copy's own script unpacks and checks it.
- The local sample-container measurement is recorded below. No macOS or other OpenGL device
  measurement is added here. The release workflow has not been dispatched by this change.

## Recorded sample profile

The wheel also carries the three original public Run it vision recordings, byte for byte.
`EXPECTRAIL_VLM_SAMPLE_RECORDINGS=1` explicitly selects them **only for doctor and the bundled
sample**. This is the default profile in `Dockerfile.sample`, not a change to ordinary verify.
Without the profile, the existing no-key quickstart still needs review on clean/repaired builds.

```sh
EXPECTRAIL_VLM_SAMPLE_RECORDINGS=1 expectrail doctor
EXPECTRAIL_VLM_SAMPLE_RECORDINGS=1 expectrail sample
```

Doctor validates the saved-answer bank and reports the live key/cap as optional for this sample.
An explicit project, or a project in the current directory, always uses the normal project doctor.
The sample uses the existing sample runner and verification gate with `RecordedBankObserver`:
real clean, broken and repaired Godot replays, both engine and recorded visual checks. It names
recording dates/runs. No model key or fallback is used. Missing exact PNG/question answers still
produce needs-review; a recording for another image never supplies a pass.

Build and run the container from a context containing only its Dockerfile, wheel and public pinned engine archive:

```sh
python3 -m pip wheel . --no-deps --no-build-isolation --no-index -w dist
EXPECTRAIL_TOOLS=/tmp/expectrail-wheel-engine GODOT_KEEP_DOWNLOAD=1 bash harness/get_godot.sh
mkdir -p /tmp/expectrail-wheel-context/dist /tmp/expectrail-wheel-context/engine-cache
cp /tmp/expectrail-wheel-engine/godot_cache/*.zip /tmp/expectrail-wheel-context/engine-cache/
cp Dockerfile.sample /tmp/expectrail-wheel-context/
cp dist/expectrail-*.whl /tmp/expectrail-wheel-context/dist/
docker build --platform linux/amd64 -f /tmp/expectrail-wheel-context/Dockerfile.sample \
  -t expectrail-wheel-local /tmp/expectrail-wheel-context
docker run --rm --network none expectrail-wheel-local expectrail doctor
docker run --rm --network none expectrail-wheel-local expectrail sample --json
```

The base image is pinned by digest. The build installs the wheel into a new Python environment
with no runtime Python dependencies, unpacks the pinned Godot through the installed script, and
checks the archive SHA-512 again inside the build with networking disabled. The host fetches the
public archive using the same pinned script; TLS verification is never disabled. The final image has no checkout. Runs use a non-root user. Bubblewrap
is checked and reported; the sample's diagnostic execution class does not claim isolation.
See [the proposed CI job](proposals/249-wheel-sample.yml.txt); Sean applies it, with no workflow
changed or dispatched here. The versioned release, registry publishing and credentials remain
Sean's steps. This patch claims part of #249, not closure of the release process.

### Recorded local container run, November 17, 2026

On main `ff2c7a7aedd1d32a2f0dfdd89ce95fabc416b9f2` plus this patch, the wheel was
installed with pip into the pinned Ubuntu container. Doctor exited **0** (Python 3.12.3,
Godot 4.7.2, Xvfb, llvmpipe LLVM 20.1.2). The real sample exited **0**:
**accept / reject / accept**, all jobs completed as expected, all with `rule: both` and
`sam-recorded` vision, no diagnostics. Both commands ran with `--network none`, as UID 10001.
Live key/cap, Chromium and the unavailable nested sandbox were reported as optional for this
explicit sample profile, not as installed or usable. No isolated execution is claimed.
The handover retains the build transcript, doctor output, complete sample JSON and image/wheel
identities. The CI proposal has not run, no image was published, and no release was tagged.
