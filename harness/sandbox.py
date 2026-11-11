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
- no terminal: a session of its own, so the terminal the harness was started from cannot be opened
  through ``/dev/tty`` (on kernels that still allow it, a program that can open a terminal can type
  into the shell behind it).

``run`` in ``harness.run`` asks ``probe`` whether this machine can do that and records the answer in
``replay.json`` (``isolation``), so a reader of the evidence can tell an isolated replay from one
that ran with the host in reach. Nothing here falls back silently: the mode is ``auto`` (isolate
when possible, say why not otherwise), ``require`` (refuse to run without it) or ``off``.

What it does not do, stated so nobody assumes it: the work copy and the output folder are on the
host's disk, so their total size is limited only per file and by the replay's time limit; CPU and
memory are limited only by that time limit; and it is a namespace sandbox on a shared kernel, not a
virtual machine.
"""
from __future__ import annotations

import functools
import os
import resource
import shutil
import subprocess
import sys
import tempfile
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
    inner = {k: v for k, v in (env or {}).items()
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


def run(tool: Tool, argv: list[str], *, timeout: float, **binds) -> subprocess.CompletedProcess:
    """Run ``argv`` in the sandbox (see ``command``) and return the finished process. The sandbox
    dies with this process, and everything in it dies with the sandbox."""
    return subprocess.run(command(tool, argv, **binds), capture_output=True, text=True, timeout=timeout,
                          stdin=subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin"}, preexec_fn=limits)


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
            done = run(tool, ["true"], timeout=30, game=game, out=out)
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
            "limits": {"scratchBytes": SCRATCH_BYTES, "fileBytes": FILE_BYTES, "processes": PROCESSES}}


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
