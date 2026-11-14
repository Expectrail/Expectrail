"""OS sandbox for Muse Code / trust probes — real mount confinement when available.

Prefer bubblewrap (`bwrap`) on Linux. Docker can film a blocked canary read by mounting
only fixer-work. When neither works, kind is `none` (deny-by-absence + env scrub only).

    python3 -m agents.sandbox --probe /path/to/fixer --canary /path/to/key

`--require-sandbox` fails closed when kind is none.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Mapping

from agents.keys import muse_subprocess_env

SANDBOX_KINDS = frozenset({"bwrap", "docker", "none"})


def _bwrap_namespaces(*, network: bool) -> list[str]:
    return ["--unshare-pid"] + ([] if network else ["--unshare-net"])


def bwrap_problem() -> str | None:
    """Probe the namespaces needed by offline and gateway calls; return the refusal, if any."""
    if not shutil.which("bwrap"):
        return "Bubblewrap (bwrap) is not installed"
    cmd = [
        "bwrap",
        "--die-with-parent",
        "--new-session",   # the probe runs what the fixer runs
        *_bwrap_namespaces(network=False),
        "--dev", "/dev",
        "--tmpfs", "/tmp",
    ]
    for ro in ("/usr", "/bin", "/lib", "/lib64"):
        if Path(ro).exists():
            cmd.extend(["--ro-bind", ro, ro])
    cmd.extend(["--", "true"])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Bubblewrap could not run: {type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        why = next((line.strip() for line in (proc.stderr or "").splitlines() if line.strip()),
                   f"exit {proc.returncode}")
        return f"Bubblewrap probe failed: {why[:300]}"
    return None


_BWRAP_WARNED = False


def _bwrap_usable() -> bool:
    global _BWRAP_WARNED
    why = bwrap_problem()
    if why is not None and not _BWRAP_WARNED:
        print(f"Expectrail: {why}; trying the next sandbox choice (or none)", file=sys.stderr)
        _BWRAP_WARNED = True
    return why is None


def detect_sandbox() -> str:
    """Return bwrap | docker | none (first usable tool)."""
    if _bwrap_usable():
        return "bwrap"
    if shutil.which("docker"):
        # Probe that docker daemon answers (cheap version check).
        try:
            proc = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode == 0:
                return "docker"
        except (OSError, subprocess.TimeoutExpired):
            pass
    return "none"


# The Muse Code installer puts a shell launcher (``muse``) beside the program it runs
# (``muse-bin-<version>``, 415 MB for 1.4.14) and three small files that say which version is
# installed. The sandbox replaces the home directory with an empty one, so binding the launcher
# alone made it download the program again, inside the sandbox, on every attempt (found Oct 30,
# run 41072542154). These are bound read-only instead; the launcher's directory stays writable
# (tmpfs) for its temporary files. Its own leftovers from installing (.muse-launcher.*) are not.
MUSE_INSTALL_FILES = ("muse", "muse-bin-*", ".muse-version", ".muse-release-info.json",
                      ".muse-update-checked-at")


def muse_install_files(launcher: str | None = None) -> list[Path]:
    """The launcher and the installed program beside it, to bind read-only into the sandbox."""
    found = launcher or shutil.which("muse")
    if not found:
        return []
    launcher_path = Path(found)
    root = launcher_path.resolve().parent
    files = {launcher_path.resolve()}
    for pattern in MUSE_INSTALL_FILES:
        files.update(p for p in root.glob(pattern) if p.is_file())
    return sorted(files)


_WARMED: set[str] = set()


def warm_muse() -> None:
    """Let the launcher finish any install or update check on the host, once per process.

    Inside the sandbox its directory is read-only (and with the gateway on, it has no network), so
    an update due there would fail. ``muse --version`` runs the same check; no key is passed.
    """
    launcher = shutil.which("muse")
    if not launcher or launcher in _WARMED:
        return
    _WARMED.add(launcher)
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "USER", "LANG", "TMPDIR")}
    try:
        subprocess.run([launcher, "--version"], env=env, capture_output=True, text=True, timeout=600, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _bwrap_cmd(work: Path, argv: list[str], *, network: bool, gateway=None,
               extra_ro: list[Path] | None = None) -> list[str]:
    """Bind only fixer-work as /fixer; ro system paths for a usable userspace.

    With ``gateway`` (agents.gateway.Gateway) the sandbox has no network at all: its directory is
    bound read-only at /gateway and ``argv`` runs behind the bridge there, so the key gateway is the
    only way out.

    ``--new-session`` gives the agent a session of its own, with no controlling terminal.
    bubblewrap's ``--dev`` provides ``/dev/tty``; without a new session the agent could open the
    terminal the loop was started from and, where the kernel still allows ``TIOCSTI``, type into
    the shell behind it (#309). In its own session a signal to the starter's process group does not
    reach the agent; what ends it is bubblewrap itself going (``--die-with-parent`` and the PID
    namespace: when bubblewrap is killed, everything inside is).
    """
    work = work.resolve()
    cmd = [
        "bwrap",
        "--die-with-parent",
        "--new-session",
        *_bwrap_namespaces(network=network and gateway is None),
        "--bind", str(work), "/fixer",
    ]
    if (work / ".muse").is_dir():
        # Muse Code project config and the fixer guard: readable, never writable by the agent.
        cmd.extend(["--ro-bind", str(work / ".muse"), "/fixer/.muse"])
    cmd += [
        "--chdir", "/fixer",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
    ]
    if gateway is not None:
        from agents.gateway import SANDBOX_DIR

        cmd.extend(["--ro-bind", str(gateway.dir), SANDBOX_DIR])
        argv = gateway.bridge_argv(argv)
    for ro in (
        "/usr", "/bin", "/lib", "/lib64",
        "/etc/ssl", "/etc/ca-certificates",
        # DNS + name service (without these Muse cannot reach api.meta.ai).
        "/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf",
        "/etc/protocols", "/etc/services",
    ):
        if Path(ro).exists():
            cmd.extend(["--ro-bind", ro, ro])
    # Host muse binary (Linux ELF) when present. Give Muse a writable tmpfs $HOME so
    # session locks / update stamps work; never rw-bind the real host home.
    #
    # Nothing else from the host's ~/.local is mounted. Muse Code 1.4 keeps its sessions under
    # ~/.local/share/muse/sessions, which must be writable; a read-only bind of the host's
    # ~/.local/share (which exists as soon as Godot has run, since Godot writes
    # ~/.local/share/godot) made every Muse run fail with "failed to acquire the session writer
    # lease ... Read-only file system". It also exposed other programs' data to the fixer.
    home = Path.home()
    cmd.extend(["--tmpfs", str(home), "--setenv", "HOME", str(home)])
    files = muse_install_files()
    if files:
        cmd.extend(["--dir", str(files[0].parent)])
        for path in files:
            cmd.extend(["--ro-bind", str(path), str(path)])
    # A BYO coding agent's install (agents.byo_fixer): read-only, after the empty $HOME so an agent
    # installed under it is still visible. Never the verifier's files: callers pass only the agent's.
    for path in extra_ro or ():
        if Path(path).exists():
            cmd.extend(["--ro-bind", str(path), str(path)])
    cmd.extend(["--"] + argv)
    return cmd


def _docker_cmd(work: Path, argv: list[str], *, network: bool, image: str = "alpine:3.20") -> list[str]:
    """Mount only fixer-work at /fixer. argv runs inside the image (not host muse)."""
    work = work.resolve()
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{work}:/fixer:rw",
        "-w", "/fixer",
    ]
    if not network:
        cmd.append("--network=none")
    for k, v in muse_subprocess_env().items():
        cmd.extend(["-e", f"{k}={v}"])
    cmd.append(image)
    cmd.extend(argv)
    return cmd


def run_sandboxed(
    argv: list[str],
    *,
    work: Path,
    env: Mapping[str, str] | None = None,
    network: bool = True,
    kind: str | None = None,
    timeout: int | None = None,
    gateway=None,
    extra_ro: list[Path] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run argv confined to fixer-work when a sandbox tool exists.

    - bwrap: runs host argv (e.g. muse) with only work + minimal ro binds.
    - docker: runs argv inside alpine with only work mounted (good for probes;
      not for host `muse` Mach-O on macOS).
    - none: plain subprocess with cwd=work (honesty / env scrub only).
    """
    resolved = kind if kind is not None else detect_sandbox()
    if resolved not in SANDBOX_KINDS:
        raise ValueError(f"unknown sandbox kind: {resolved}")
    run_env = dict(env) if env is not None else muse_subprocess_env()
    if resolved == "bwrap":
        cmd = _bwrap_cmd(work, argv, network=network, gateway=gateway, extra_ro=extra_ro)
        # No input: the agent is given its task as arguments and files, and an inherited stdin
        # would be the starter's terminal when the loop is run from one.
        return subprocess.run(
            cmd, capture_output=True, text=True, env=run_env, timeout=timeout, stdin=subprocess.DEVNULL,
        )
    if resolved == "docker":
        # Docker injects env via -e; still pass a minimal host env for docker CLI itself.
        host_env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "DOCKER_HOST", "USER")}
        cmd = _docker_cmd(work, argv, network=network)
        return subprocess.run(
            cmd, capture_output=True, text=True, env=host_env or None, timeout=timeout,
        )
    return subprocess.run(
        argv, cwd=str(work), capture_output=True, text=True, env=run_env, timeout=timeout,
    )


def probe_blocked_canary_read(
    work: Path,
    canary: Path,
    *,
    kind: str | None = None,
) -> dict:
    """Attempt to read canary from inside the sandbox; expect failure when enforced.

    Uses `cat` of the absolute host canary path. When only fixer-work is mounted,
    that path is invisible → non-zero exit / no key bytes.
    """
    resolved_kind = kind if kind is not None else detect_sandbox()
    canary = canary.resolve()
    marker = "DEMO-FAKE-SIGNING-KEY-NOT-REAL"
    key_raw = canary.read_bytes() if canary.is_file() else b""
    argv = ["cat", str(canary)]

    def _leaked(blob: str | bytes, *, exit_ok: bool) -> bool:
        if isinstance(blob, str):
            data = blob.encode("utf-8", errors="surrogateescape")
            text = blob
        else:
            data = blob
            text = blob.decode("utf-8", errors="ignore")
        if marker in text:
            return True
        if key_raw and key_raw in data:
            return True
        # Successful cat of the canary path is a leak even when stdout is mangled.
        return bool(exit_ok and data)

    # Inside docker/bwrap the host absolute path usually does not exist.
    if resolved_kind == "none":
        # Honesty: host process can still read the canary.
        try:
            raw = canary.read_bytes()
            text = raw.decode("utf-8", errors="ignore")
            return {
                "kind": "none",
                "enforced": False,
                "blocked": False,
                "exitCode": 0,
                "leakedKeyBytes": _leaked(raw, exit_ok=True),
                "stdout": text[:200],
                "stderr": "",
                "detail": "no OS sandbox; host process can read canary (deny-by-absence only)",
            }
        except OSError as exc:
            return {
                "kind": "none",
                "enforced": False,
                "blocked": True,
                "exitCode": 1,
                "leakedKeyBytes": False,
                "stdout": "",
                "stderr": str(exc),
                "detail": f"host read failed unexpectedly: {exc}",
            }

    proc = run_sandboxed(argv, work=work, network=False, kind=resolved_kind, timeout=60)
    out = (proc.stdout or "") + (proc.stderr or "")
    leaked = _leaked(out, exit_ok=proc.returncode == 0)
    blocked = proc.returncode != 0 and not leaked
    return {
        "kind": resolved_kind,
        "enforced": True,
        "blocked": blocked,
        "exitCode": proc.returncode,
        "leakedKeyBytes": leaked,
        "stdout": (proc.stdout or "")[:500],
        "stderr": (proc.stderr or "")[:500],
        "detail": (
            f"{resolved_kind} blocked canary read (exit {proc.returncode})"
            if blocked
            else f"{resolved_kind} FAILED to block canary (leak or success)"
        ),
    }


def muse_kind_for(detected: str) -> str:
    """Muse runs under bwrap or not at all (docker cannot run the host muse binary)."""
    return "bwrap" if detected == "bwrap" else "none"


def muse_workspace_root(work: Path, muse_kind: str) -> str:
    """The fixer workspace path as Muse Code sees it (bwrap binds it at /fixer)."""
    return "/fixer" if muse_kind == "bwrap" else str(work.resolve())


MUSE_ARGV = ["muse", "exec", "--disable-approval", "--trust-workspace"]


def run_muse(
    prompt: str,
    *,
    work: Path,
    env: Mapping[str, str] | None = None,
    timeout: int,
    sandboxed: bool = True,
    require_sandbox: bool = False,
    detected: str | None = None,
    provider_only: bool = False,
) -> tuple[subprocess.CompletedProcess[str], dict]:
    """Every ``muse exec`` goes through here: under bwrap when ``sandboxed`` and available, else on
    the host with an allowlisted environment; through the key gateway when it is on (agents.gateway).

    Docker is not used for Muse (the image would need a Linux muse CLI). Pass ``detected`` (from
    detect_sandbox) when the caller already probed, so the workspace it prepared matches.
    """
    from agents.gateway import muse_gateway

    kind = (detected if detected is not None else detect_sandbox()) if sandboxed else "none"
    muse_kind = muse_kind_for(kind) if sandboxed else "none"
    if (require_sandbox or provider_only) and muse_kind == "none":
        raise SystemExit(
            "--require-sandbox needs bubblewrap (bwrap) on PATH to confine Muse Code"
        )
    argv = MUSE_ARGV + [prompt]
    base = dict(env) if env is not None else muse_subprocess_env()
    meta: dict = {"kind": muse_kind, "requireSandbox": require_sandbox, "detect": kind}
    warm_muse()
    # A repair gets only the model gateway, even if the host normally disables or widens it.
    if provider_only:
        from agents.gateway import DEFAULT_HOSTS, GATEWAY_ENV, HOSTS_ENV
        channel = muse_gateway({**os.environ, GATEWAY_ENV: "on", HOSTS_ENV: DEFAULT_HOSTS})
    else:
        channel = muse_gateway()
    with channel as gateway:
        if gateway is not None:
            base = gateway.muse_env(base, in_sandbox=muse_kind == "bwrap")
            meta["network"] = "gateway only" if muse_kind == "bwrap" else "host (proxy settings)"
        try:
            if muse_kind == "bwrap":
                proc = run_sandboxed(argv, work=work, env=base, network=True, kind="bwrap", timeout=timeout,
                                     gateway=gateway)
            else:
                proc = subprocess.run(argv, cwd=str(work), capture_output=True, text=True, env=base,
                                      timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            # Time ran out, but the gateway still saw every request: hand the caller this run's record
            # so a timed-out attempt is counted like any other (agents.fixer writes it to sandbox.json).
            meta["gateway"] = gateway.summary() if gateway is not None else {"mode": "off"}
            exc.sandbox_meta = meta
            raise
        finally:
            meta["gateway"] = gateway.summary() if gateway is not None else {"mode": "off"}
    if gateway is not None:
        proc = subprocess.CompletedProcess(proc.args, proc.returncode,
                                           (proc.stdout or "").replace(gateway.placeholder, "[placeholder]"),
                                           (proc.stderr or "").replace(gateway.placeholder, "[placeholder]"))
    return proc, meta


def run_muse_sandboxed(
    prompt: str,
    *,
    work: Path,
    env: Mapping[str, str] | None = None,
    timeout: int,
    require_sandbox: bool = False,
    detected: str | None = None,
    provider_only: bool = False,
) -> tuple[subprocess.CompletedProcess[str], dict]:
    """``run_muse`` under bwrap when available (the fixer and the sandboxed screenshot judge)."""
    return run_muse(prompt, work=work, env=env, timeout=timeout, sandboxed=True,
                    require_sandbox=require_sandbox, detected=detected, provider_only=provider_only)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--probe", type=Path, help="fixer-work path for canary probe")
    p.add_argument("--canary", type=Path, help="absolute canary file outside the mount")
    p.add_argument("--require-sandbox", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    kind = detect_sandbox()
    if args.require_sandbox and kind == "none":
        print("sandbox unavailable (need bwrap or docker)", file=sys.stderr)
        return 2
    if args.probe and args.canary:
        result = probe_blocked_canary_read(args.probe, args.canary, kind=kind)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(result["detail"])
        if kind != "none" and not result["blocked"]:
            return 1
        return 0
    print(f"sandbox kind={kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
