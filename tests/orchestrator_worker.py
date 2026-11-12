"""A worker process with stand-in engines, for tests/test_orchestrator.py.

    python3 -m tests.orchestrator_worker JOBS_ROOT LEASE_SECONDS JOB_ID

The engines here do no verification. They let the tests watch what the orchestrator does around an
engine: folders, phases, cancelling, a worker that dies, a job that runs out of time.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from expectrail.orchestrator import runner
from expectrail.orchestrator import store as st
from expectrail.orchestrator.engines import Result


class Instant:
    """Writes one evidence file and accepts."""

    def preflight(self, request):
        return []

    def execute(self, request, paths, advance):
        paths.staging.mkdir()
        (paths.staging / "evidence.txt").write_text(f"evidence of {paths.root.name}\n", encoding="utf-8")
        (paths.work / "scratch.txt").write_text(paths.root.name, encoding="utf-8")
        advance("evaluating")
        return Result("accept", ["the stand-in engine accepts"])


class Slow(Instant):
    """Starts a child of its own, says it is running, then works for a long time before accepting."""

    def execute(self, request, paths, advance):
        child = subprocess.Popen(["sleep", "600"])
        (paths.work / "child.pid").write_text(str(child.pid), encoding="utf-8")
        paths.staging.mkdir()
        (paths.staging / "evidence.txt").write_text("half written", encoding="utf-8")
        (paths.work / "running").write_text("1", encoding="utf-8")
        time.sleep(600)
        return Result("accept", ["too late"])


class Detached(Slow):
    """Like Slow, but its child leaves the worker's process group, as a program that starts its own
    session does (the sandboxed game is one)."""

    def execute(self, request, paths, advance):
        child = subprocess.Popen(["sleep", "600"], start_new_session=True)
        (paths.work / "child.pid").write_text(str(child.pid), encoding="utf-8")
        paths.staging.mkdir()
        (paths.staging / "evidence.txt").write_text("half written", encoding="utf-8")
        (paths.work / "running").write_text("1", encoding="utf-8")
        time.sleep(600)
        return Result("accept", ["too late"])


ENGINES = {"instant": Instant(), "slow": Slow(), "detached": Detached()}


if __name__ == "__main__":
    root, lease, job = sys.argv[1:4]
    runner.work(st.JobStore(Path(root), lease_seconds=float(lease)), job, engines=ENGINES, own_group=True)
