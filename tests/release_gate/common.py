"""What the release gate's tests share: real checkouts, the real command, and a look for leftovers.

Every test here starts real processes: the orchestrator's command line, its worker, and Godot. The
command and the worker are the orchestrator's own code run through ``tests.release_gate.worker``,
whose only difference is the visual observer: it answers from the recorded vision answers of the
"Run it" samples, so a run can be cleared without a model key (see that module). Without Godot they are skipped, or,
with ``EXPECTRAIL_RELEASE_GATE=required`` (the CI job sets it), they fail: a control that did not run
is never counted as held.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from expectrail.orchestrator import sample as smp
from expectrail.orchestrator import store as st

REPO = Path(__file__).resolve().parents[2]
REQUIRED = os.environ.get("EXPECTRAIL_RELEASE_GATE", "") == "required"
GAME, ROUTE, SPECS = smp.GAME, smp.ROUTE, smp.SPECS
SPEC_FILE = "agents/specs/player-stays-above-ground.json"
LEASE = "1.0"


def engine_missing() -> str | None:
    """Why a real replay cannot run on this machine, or None when it can (the engine's own preflight)."""
    from expectrail.orchestrator import engines

    missing = engines.GodotGate._tools()
    return "; ".join(d["detail"] for d in missing) or None


def edit_json(path: Path, change) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    change(doc)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def job_processes(job_id: str) -> list[int]:
    """The processes on this machine that still carry the job's id in their environment (the worker
    passes it to everything it starts: ``expectrail.orchestrator.store.JOB_ENV``)."""
    marker = f"{st.JOB_ENV}={job_id}".encode()
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if marker in (entry / "environ").read_bytes().split(b"\0"):
                stat = (entry / "stat").read_text()
                if stat.rsplit(")", 1)[1].split()[0] != "Z":   # a zombie runs nothing
                    found.append(int(entry.name))
        except OSError:
            continue
    return found


class GateCase(unittest.TestCase):
    """Real checkouts of the bundled game (the sample's: the game, the smoke route and the approved
    spec), made once per class, and a jobs folder per test."""

    @classmethod
    def setUpClass(cls):
        why = engine_missing()
        if why:
            if REQUIRED:
                raise AssertionError(f"EXPECTRAIL_RELEASE_GATE=required and a real replay cannot run here: {why}")
            raise unittest.SkipTest(f"a real replay cannot run here ({why}); set up Godot or see `expectrail doctor`")
        cls.root = Path(tempfile.mkdtemp(prefix="release-gate-"))
        cls.clean = smp.checkout(cls.root / "clean", bug=False)
        cls.bug = smp.checkout(cls.root / "bug", bug=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="case-", dir=self.root))
        self.jobs = self.tmp / "jobs"
        self.store = st.JobStore(self.jobs, lease_seconds=float(LEASE))
        self.watched: list[str] = []
        self.addCleanup(self._no_leftovers)

    def _no_leftovers(self):
        """Whatever a test did, nothing of its jobs may be left running (and if something is, it is
        stopped, so one test cannot slow the next)."""
        deadline = time.monotonic() + 10   # a stopped process may take a moment to exit
        while True:
            left = {job: job_processes(job) for job in self.watched}
            left = {job: pids for job, pids in left.items() if pids}
            if not left or time.monotonic() > deadline:
                break
            time.sleep(0.2)
        for pids in left.values():
            for pid in pids:
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
        self.assertEqual(left, {}, "processes of a finished job were still running")

    def copy(self, name: str, source: Path | None = None) -> Path:
        """A copy of a checkout to change for one test."""
        target = self.tmp / name
        shutil.copytree(source or self.clean, target)
        return target

    # --- the command --------------------------------------------------------------------------------
    def command(self, *argv: str, timeout: float = 300) -> tuple[int, str, str]:
        done = subprocess.run([sys.executable, "-m", "tests.release_gate.worker", "--jobs-root", str(self.jobs),
                               "--lease-seconds", LEASE, *argv],
                              cwd=REPO, capture_output=True, text=True, timeout=timeout)
        return done.returncode, done.stdout, done.stderr

    def verify(self, head: Path, *extra: str, base: Path | None = None, routes: str = ROUTE,
               specs: str = SPECS) -> tuple[int, dict | None, str]:
        """``verify --json`` and its exit code and job status (None when it printed none)."""
        argv = ["verify", "--head", str(head), "--game", GAME, "--routes", routes, "--specs", specs, "--json", *extra]
        if base is not None:
            argv += ["--base", str(base)]
        code, out, err = self.command(*argv)
        try:
            status = json.loads(out)
        except ValueError:
            status = None
        if status and "id" in status:
            self.watched.append(status["id"])
        return code, status, err

    def start(self, head: Path, *extra: str) -> str:
        """``verify --detach``: the job's id, with its worker running."""
        code, out, err = self.command("verify", "--head", str(head), "--game", GAME, "--routes", ROUTE,
                                      "--specs", SPECS, "--detach", "--json", *extra)
        self.assertEqual(code, 0, err)
        job = json.loads(out)["id"]
        self.watched.append(job)
        return job

    def status(self, job: str) -> tuple[int, dict]:
        code, out, err = self.command("status", job, "--json")
        return code, json.loads(out)

    def wait_until(self, job: str, phases, seconds: float = 120) -> dict:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            status = self.store.status(job)
            if status["phase"] in phases:
                return status
            time.sleep(0.1)
        raise AssertionError(f"job {job} did not reach {phases} in {seconds} s (it is {status['phase']})")

    def game_running(self, job: str, seconds: float = 120) -> None:
        """Wait until the job's worker has started something besides itself (the engine, its display)."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            status = self.store.status(job)
            worker = (status.get("worker") or {}).get("pid")
            if status["phase"] in st.FINAL:
                raise AssertionError(f"job {job} finished ({status['phase']}) before its game was seen running")
            if worker and [p for p in job_processes(job) if p != worker]:
                return
            time.sleep(0.1)
        raise AssertionError(f"no process of job {job} besides its worker appeared in {seconds} s")

    # --- what every control asserts -----------------------------------------------------------------
    def assertNotCleared(self, code: int, status: dict | None, msg: str = "") -> None:
        """Clearance today: exit 0, which only a job completed as accept gives."""
        self.assertNotEqual(code, 0, f"exit 0 is clearance. {msg}")
        if status is not None and "decision" in status:
            self.assertNotEqual(status["decision"], "accept", msg)
