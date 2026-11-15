"""The replay's sandbox: the game runs inside bubblewrap, not as a plain child of the verifier.

The game under test is the candidate's code. GDScript can open sockets, read and write files and
read ``/proc``, and Godot's import step runs the project's own import code. Outside a sandbox that
code runs as the verifier's user: it can reach the network, read the approved checks and the
verifier's source, read the environment of the process that started it (``/proc/<parent>/environ``,
which holds every key the job has) and write into the evidence folder. Inside, it gets:

- no network: a new, empty network namespace;
- its own process tree and ``/proc``, so no other process's environment or memory is in reach;
- a file system built from nothing: the system's programs and libraries read-only, the game's work
  copy at ``/game`` and one output folder at ``/out`` writable, each input file read-only under
  ``/in``, the engine read-only at ``/engine``, and a size-limited empty ``/tmp`` and home. The
  repository, the checks, the caller's home and every other folder are not there;
- an environment built from nothing, holding only the display and rendering variables;
- no way to make another user namespace, a cap on any one file's size, and no core dumps;
- a bound on everything it writes to the two folders it can write to (the work copy and the output
  folder, which are on the host's disk): ``DISK_BYTES`` more bytes and ``DISK_ENTRIES`` more files
  and folders than were there when it started. ``run`` measures both folders every
  ``DISK_INTERVAL`` seconds while the game runs and once more after it ends; past the bound the
  sandbox is killed and the run is refused (``DiskBoundError``), never used;
- no terminal: a session of its own, so the terminal the harness was started from cannot be opened
  through ``/dev/tty`` (on kernels that still allow it, a program that can open a terminal can type
  into the shell behind it).

``run`` in ``harness.run`` asks ``probe`` whether this machine can do that and records the answer in
``replay.json`` (``isolation``), so a reader of the evidence can tell an isolated replay from one
that ran with the host in reach. Nothing here falls back silently: the mode is ``auto`` (isolate
when possible, say why not otherwise), ``require`` (refuse to run without it) or ``off``.

What it does not do, stated so nobody assumes it: the disk bound is measured, not enforced by the
file system, so between two measurements a game can write past it by as much as the machine's disk
writes in ``DISK_INTERVAL`` seconds (each file stays under ``FILE_BYTES`` all the same), and the
run is refused afterwards; CPU and memory are limited only by the replay's time limit; and it is a
namespace sandbox on a shared kernel, not a virtual machine.
"""
from __future__ import annotations

import functools
import os
import resource
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

MODES = ("auto", "require", "off")
ENV = "EXPECTRAIL_SANDBOX"

# Where things are inside the sandbox.
GAME, OUT, INPUTS, ENGINE, HOME = "/game", "/out", "/in", "/engine", "/home/player"
ENGINE_BINARY = ENGINE + "/godot"

SCRATCH_BYTES = 256 * 1024 * 1024  # each of /tmp and the home folder (memory-backed)
FILE_BYTES = 2 * 1024 ** 3         # the largest single file the game may write
PROCESSES = 4096                   # processes and threads for the user (the kernel exempts root)
# What the game may add to its work copy and its output folder together, over what they held when it
# started. A replay of the bundled game adds about 30 MB and 340 files (120 frames); the longest
# route in the repository (360 frames) about 100 MB. The bound is far above that and well below a
# CI runner's free disk, with room for what a game can write between two measurements (Godot writing
# 1 MB files on the machine this was measured on: about 200 MB in 0.1 s, into the page cache).
DISK_BYTES = 4 * 1024 ** 3
DISK_ENTRIES = 250_000
DISK_INTERVAL = 0.1                # seconds between two measurements while the game runs
DISK_ENV = "EXPECTRAIL_SANDBOX_DISK_BYTES"   # set by the person running the verifier, to lower the bound

# Read-only pieces of the host that a program needs to start, draw and find fonts. No /etc/passwd,
# no /sys, no /home, no /var, no /run.
SYSTEM = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/etc/alternatives", "/etc/fonts",
          "/etc/glvnd", "/etc/X11", "/etc/ld.so.cache")

# Never passed in: the host's display cannot be reached from the sandbox (it starts its own), and
# the paths are the sandbox's own.
ENV_DROP = frozenset({"DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "HOME", "PATH", "TMPDIR", "USER",
                      "LOGNAME", "SHELL"})
ENV_DROP_PREFIXES = ("XDG_",)


class SandboxError(RuntimeError):
    """The sandbox was required and cannot be had, or its output cannot be trusted."""


class DiskBoundError(SandboxError):
    """The game wrote more to its work copy and output folder than the bound allows. The sandbox was
    killed (or had ended) and nothing it wrote is used."""


@dataclass(frozen=True)
class Tool:
    path: str
    version: str


def mode(value: str | None = None) -> str:
    """The mode asked for: the argument, else $EXPECTRAIL_SANDBOX, else ``auto``."""
    chosen = value if value is not None else os.environ.get(ENV, "").strip() or "auto"
    if chosen not in MODES:
        raise SandboxError(f"unknown sandbox mode {chosen!r}: expected one of {', '.join(MODES)}")
    return chosen


def _clip(text: str, limit: int = 200) -> str:
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return line[:limit]


def command(tool: Tool, argv: list[str], *, game: Path, out: Path, inputs: dict[str, Path] | None = None,
            engine: Path | None = None, env: dict | None = None) -> list[str]:
    """The bubblewrap command that runs ``argv`` with ``game`` at /game and ``out`` at /out (both
    writable), each of ``inputs`` read-only at /in/<name>, and ``engine`` read-only at /engine/godot."""
    # --new-session: without it the game shares the harness's session and can open its terminal.
    # Never --as-pid-1: xvfb-run hangs as the first process of its namespace.
    cmd = [tool.path, "--die-with-parent", "--new-session",
           "--unshare-user", "--unshare-ipc", "--unshare-pid", "--unshare-net", "--unshare-uts",
           "--unshare-cgroup-try", "--disable-userns", "--hostname", "expectrail", "--clearenv"]
    for path in SYSTEM:
        if os.path.islink(path):
            cmd += ["--symlink", os.readlink(path), path]
        elif os.path.exists(path):
            cmd += ["--ro-bind", path, path]
    cmd += ["--dev", "/dev", "--proc", "/proc",
            "--size", str(SCRATCH_BYTES), "--tmpfs", "/tmp",
            "--size", str(SCRATCH_BYTES), "--tmpfs", HOME,
            "--bind", str(Path(game).resolve()), GAME,
            "--bind", str(Path(out).resolve()), OUT]
    for name, path in sorted((inputs or {}).items()):
        if "/" in name or name in ("", ".", ".."):
            raise SandboxError(f"an input's name must be a plain file name, not {name!r}")
        cmd += ["--ro-bind", str(Path(path).resolve()), f"{INPUTS}/{name}"]
    if engine is not None:
        cmd += ["--ro-bind", str(Path(engine).resolve()), ENGINE_BINARY]
    from harness.run import game_env

    inner = {k: v for k, v in game_env(env or {}).items()
             if k not in ENV_DROP and not k.startswith(ENV_DROP_PREFIXES)}
    inner.update(HOME=HOME, PATH="/usr/bin:/bin", TMPDIR="/tmp")
    for key in sorted(inner):
        cmd += ["--setenv", key, inner[key]]
    return cmd + ["--chdir", GAME, "--"] + list(argv)


def limits() -> None:
    """Resource limits for the sandboxed process tree; runs in the child before bubblewrap starts."""
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    for name, value in ((resource.RLIMIT_FSIZE, FILE_BYTES), (resource.RLIMIT_NPROC, PROCESSES)):
        _soft, hard = resource.getrlimit(name)
        value = value if hard == resource.RLIM_INFINITY else min(value, hard)
        resource.setrlimit(name, (value, value))


class _Unmeasurable(Exception):
    """A folder under the roots could not be read, so what is in it cannot be counted."""


def usage(roots: list[Path], cap: int) -> tuple[int, int]:
    """(bytes, entries) under ``roots``, links not followed. A file counts its size or the blocks it
    holds, whichever is more, so a sparse file counts as its full length. Counting stops once
    ``cap`` entries have been seen (the caller treats more than that as over the bound), so a game
    that makes millions of files cannot make one measurement take long.

    A file or folder that disappears while it is being counted is skipped: it no longer takes room.
    A folder that exists and cannot be read raises ``_Unmeasurable``, because the game can make its
    own folders unreadable to hide what is in them."""
    total = count = 0
    stack = [os.fspath(root) for root in roots]
    while stack:
        top = stack.pop()
        try:
            listing = os.scandir(top)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError as exc:
            raise _Unmeasurable(f"{type(exc).__name__} on a folder the game could write to") from exc
        with listing:
            while True:
                try:
                    entry = next(listing)
                except StopIteration:
                    break
                except OSError as exc:
                    raise _Unmeasurable(f"{type(exc).__name__} while listing a folder the game could write to") from exc
                count += 1
                if count > cap:
                    return total, count
                try:
                    info = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise _Unmeasurable(f"{type(exc).__name__} on a file the game could write to") from exc
                total += max(info.st_size, info.st_blocks * 512)
                if stat.S_ISDIR(info.st_mode):
                    stack.append(entry.path)
    return total, count


def disk_bytes() -> int:
    """The byte bound in force: ``DISK_BYTES``, or less when $EXPECTRAIL_SANDBOX_DISK_BYTES asks for
    less. It can only lower the bound: the game's code never sets the verifier's environment, and a
    larger or unreadable value is refused rather than used."""
    asked = os.environ.get(DISK_ENV, "").strip()
    if not asked:
        return DISK_BYTES
    if not asked.isdigit() or not 0 < int(asked) <= DISK_BYTES:
        raise SandboxError(f"${DISK_ENV} must be a whole number of bytes from 1 to {DISK_BYTES}, not {asked[:40]!r}")
    return int(asked)


def _over(roots: list[Path], start: tuple[int, int], allowed: int) -> str | None:
    """Why the folders are past the bound, or None while they are within it."""
    try:
        used, entries = usage(roots, start[1] + DISK_ENTRIES)
    except _Unmeasurable as exc:
        return f"what the game wrote could not be measured ({exc}), so the run is not used"
    if entries > start[1] + DISK_ENTRIES:
        return (f"the game made more than {DISK_ENTRIES} files and folders in its work copy and output folder, "
                "the most a replay may add")
    if used > start[0] + allowed:
        return (f"the game wrote {used - start[0]} bytes to its work copy and output folder, more than the "
                f"{allowed} a replay may add")
    return None


def run(tool: Tool, argv: list[str], *, timeout: float, **binds) -> subprocess.CompletedProcess:
    """Run ``argv`` in the sandbox (see ``command``) and return the finished process. The sandbox
    dies with this process, and everything in it dies with the sandbox.

    While it runs, the two folders it can write to are measured every ``DISK_INTERVAL`` seconds, and
    once more after it ends. Past the bound (``DISK_BYTES``, ``DISK_ENTRIES``) the sandbox is killed
    and ``DiskBoundError`` is raised; the caller uses nothing it wrote. Past ``timeout`` it is killed
    and ``subprocess.TimeoutExpired`` is raised with its output, as ``subprocess.run`` does."""
    # The sandbox tool itself gets nothing from this process's environment but the job's id, which
    # is how the orchestrator finds it if its worker is killed; the game's environment is built by
    # `command` from `env`.
    cmd = command(tool, argv, **binds)
    return watched(cmd, roots=[Path(binds["game"]), Path(binds["out"])], timeout=timeout, env=_own_env(),
                   preexec_fn=limits)


def _own_env() -> dict:
    return {"PATH": "/usr/bin:/bin", **{k: v for k, v in os.environ.items() if k == "EXPECTRAIL_JOB"}}


def watched(cmd: list[str], *, roots: list[Path], timeout: float, **popen) -> subprocess.CompletedProcess:
    """Run ``cmd`` to the end and return it, as ``subprocess.run(capture_output=True, text=True)``
    does, while holding what it adds under ``roots`` to the disk bound (see ``run``). Kept apart from
    the sandbox's command so the bound can be shown on any process."""
    allowed = disk_bytes()
    try:
        start = usage(roots, sys.maxsize)
    except _Unmeasurable as exc:
        raise SandboxError(f"the folders the game may write to cannot be measured before it starts: {exc}") from exc
    deadline = time.monotonic() + timeout
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                            text=True, **popen)
    try:
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=max(0.0, min(DISK_INTERVAL, deadline - time.monotonic())))
                break
            except subprocess.TimeoutExpired:
                pass   # retrying communicate loses no output (the subprocess documentation says so)
            why = _over(roots, start, allowed)
            if why is not None:
                proc.kill()
                proc.communicate()
                raise DiskBoundError(why + "; the sandbox was stopped")
            if time.monotonic() >= deadline:
                proc.kill()
                stdout, stderr = proc.communicate()
                raise subprocess.TimeoutExpired(proc.args, timeout, output=stdout, stderr=stderr)
    except BaseException:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        raise
    # The last measurement, after the end: the one a game cannot slip between.
    why = _over(roots, start, allowed)
    if why is not None:
        raise DiskBoundError(why)
    return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)


@functools.lru_cache(maxsize=None)
def probe(display: bool = True) -> tuple[Tool | None, str | None]:
    """(tool, None) when this machine can run the sandbox, else (None, the reason). ``display`` asks
    for a replay with frames, which needs a virtual display started inside the sandbox.

    The check is the real thing: the same command a replay uses, running ``true``. A machine whose
    bubblewrap is too old for an option, or whose kernel refuses user namespaces, fails here.
    """
    if not sys.platform.startswith("linux"):
        return None, "bubblewrap runs on Linux only"
    path = shutil.which("bwrap")
    if not path:
        return None, "bubblewrap (bwrap) is not installed"
    if display and not shutil.which("xvfb-run"):
        return None, "xvfb-run is not installed, and the sandbox cannot use the host's display"
    try:
        version = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=15)
        tool = Tool(path, version.stdout.strip().split()[-1] if version.stdout.strip() else "unknown")
        with tempfile.TemporaryDirectory(prefix="expectrail-sandbox-") as scratch:
            game, out = Path(scratch, "game"), Path(scratch, "out")
            game.mkdir()
            out.mkdir()
            # The replay's own command, running a program that writes nothing, so the disk bound's
            # watch (``watched``) is not needed for it.
            done = subprocess.run(command(tool, ["true"], game=game, out=out), capture_output=True, text=True,
                                  timeout=30, stdin=subprocess.DEVNULL, env=_own_env(), preexec_fn=limits)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"bubblewrap could not be run ({type(exc).__name__})"
    if done.returncode != 0:
        return None, f"bubblewrap could not start a sandbox: {_clip(done.stderr) or 'exit ' + str(done.returncode)}"
    return tool, None


def choose(asked: str | None, display: bool) -> tuple[Tool | None, dict]:
    """Decide how this replay runs and describe it for replay.json: (the tool or None, ``isolation``).

    ``require`` raises SandboxError when the sandbox cannot be had."""
    wanted = mode(asked)
    if wanted == "off":
        return None, describe(None, wanted, "the sandbox was turned off for this replay")
    tool, why = probe(display)
    if tool is None and wanted == "require":
        raise SandboxError(f"a sandboxed replay was required and is not possible here: {why}")
    return tool, describe(tool, wanted, why)


def describe(tool: Tool | None, wanted: str, why: str | None) -> dict:
    """The ``isolation`` block of replay.json: what the game could reach during this replay."""
    if tool is None:
        return {"sandbox": None, "mode": wanted, "reason": why, "network": "host", "filesystem": "host",
                "processes": "host", "environment": "allowlist", "limits": None}
    return {"sandbox": {"tool": "bubblewrap", "version": tool.version}, "mode": wanted, "reason": None,
            "network": "none", "filesystem": "confined", "processes": "own",
            "environment": "allowlist",
            "limits": {"scratchBytes": SCRATCH_BYTES, "fileBytes": FILE_BYTES, "processes": PROCESSES,
                       "diskBytes": disk_bytes(), "diskEntries": DISK_ENTRIES}}


def collect(staging: Path, out: Path, *, frames: bool) -> None:
    """Move the game's output from the folder it could write to (``staging``, /out inside) into the
    run folder, taking only what a replay is made of: ``trace.json`` and ``frames/f*.png``, plain
    files only. A link is refused, because following one would read a file the game could not."""
    trace = staging / "trace.json"
    if trace.is_symlink() or (trace.exists() and not trace.is_file()):
        raise SandboxError("the game left something other than a plain file as its trace")
    if trace.is_file():
        os.replace(trace, out / "trace.json")
    target = out / "frames"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir()
    source = staging / "frames"
    if frames and source.is_dir() and not source.is_symlink():
        for entry in sorted(os.scandir(source), key=lambda e: e.name):
            if not (entry.name.startswith("f") and entry.name.endswith(".png")):
                continue
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                raise SandboxError(f"the game left something other than a plain file as frame {entry.name}")
            os.replace(entry.path, target / entry.name)
    shutil.rmtree(staging, ignore_errors=True)
