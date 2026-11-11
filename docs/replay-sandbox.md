# The replay's sandbox

The game under test is the candidate's code. Until November 11 the harness started it as a plain child
process: same user, the host's network, every file that user can read or write, and a `/proc` in which
the starting process's environment (every key the job holds) is readable. Narrowing the game's own
environment (`game_env`) did not close any of that. `harness/sandbox.py` does, with bubblewrap.

## What the game gets

| | Inside the sandbox | Without it |
| --- | --- | --- |
| Network | none: a new, empty network namespace | the host's |
| Processes | its own tree and `/proc` | the harness and everything else the user runs |
| Files it can write | its work copy (`/game`), one output folder (`/out`), a 256 MiB `/tmp` and home | anything the user can |
| Files it can read | those, its route (`/in/route.json`), the engine (`/engine/godot`), and the system's `/usr` and a few folders of `/etc` (fonts, OpenGL, X11) | anything the user can |
| The repository, the checks, the caller's home | not mounted | readable |
| Environment | built from nothing: display and rendering variables only | the same variables |
| Terminal | none: a session of its own, so `/dev/tty` cannot be opened | the terminal the harness was started from |
| Limits | 2 GiB per file, no core dumps, no further user namespaces, the replay's time limit | the time limit |

Both of Godot's steps run inside: the import (which runs the project's own import code) and the replay.
A replay with frames starts its own virtual display inside; the host's display is never used.

The harness takes only two things back from the output folder: `trace.json` and `frames/f*.png`, and
only when they are plain files. A link is refused and the replay fails, because following one would
read a file the game itself could not.

## Modes

`python3 -m harness.run --sandbox auto|require|off`, or `EXPECTRAIL_SANDBOX` for every replay a
command starts.

- `auto` (default): isolate when this machine can; otherwise run as before and record why not.
- `require`: refuse to run when it cannot be isolated. CI's `seeded-bugs` job uses this.
- `off`: do not isolate, and record that it was turned off.

There is no silent fallback. Every `replay.json` carries an `isolation` block
(`contracts/replay.schema.json`): the tool and its version or `null`, the mode asked for, the reason
when not isolated, and what the game could reach (`network`, `filesystem`, `processes`).

## What a machine needs

Linux, `bwrap` and, for replays with frames, `xvfb-run`. The harness checks by running the real
command once, so a bubblewrap too old for `--disable-userns` or `--size`, or a kernel that refuses user
namespaces, is found and named in `isolation.reason`. Ubuntu 24.04 refuses them by default; CI turns
that off first (`kernel.apparmor_restrict_unprivileged_userns=0`), as the fixer's sandbox job does.

## What it does not do

- It is a namespace sandbox on the host's kernel, not a virtual machine.
- The work copy and the output folder are on the host's disk: each file is limited, their total is not.
  CPU and memory are limited only by the replay's time limit.
- The process limit (4,096) is the kernel's per-user count, which includes that user's processes
  outside the sandbox. A user already running more than that gets "could not start a sandbox" without
  the limit being named; `auto` records it and `require` refuses.
- The fixer's sandbox (`agents/sandbox.py`) is a separate one and still shares its starter's terminal
  (#309).
- Godot only. The Unity player and the web replay are not sandboxed yet.
- The gate and the orchestrator do not yet read `isolation`: no verdict is graded by it, and the
  gate's own workflow does not install bubblewrap. Both are the rest of #253.

## How it is tested

`tests/test_replay_sandbox.py`. Every escape has a control: the same attempt outside the sandbox
succeeds, so a refusal inside is the sandbox's doing.

- A program inside cannot open a socket to a port on the host's loopback, write outside its two folders,
  write its input or `/usr`, read a check, read the verifier, read the starting process's environment or
  make a user namespace; started from a terminal, it cannot open that terminal; a time limit ends
  everything it started; a file over the limit is cut off.
- The real engine, with a copy of the bundled game that tries the four things #253 names from GDScript
  (socket, write outside, read a check and the verifier, read the environment): all reached without the
  sandbox, none inside.
- The clean game's frame and trace hashes are the same with and without the sandbox.

The tests that need bubblewrap are skipped where it cannot run and are required in CI's `seeded-bugs`
job (`EXPECTRAIL_SANDBOX_TESTS=required`).
