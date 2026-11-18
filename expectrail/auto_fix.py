"""Run an explicitly requested repair after verification. The parent keeps its decision."""
from __future__ import annotations

import hashlib
import math
import os
import sys
import tempfile
from pathlib import Path

from expectrail.diagnostics import redact
from expectrail.gate.record import read_bytes_capped
from expectrail.orchestrator import runner, store


def options(parser):
    parser.add_argument("--auto-fix", action="store_true", help="try to repair a reject in a separate checkout")
    parser.add_argument("--auto-fix-attempts", type=int, metavar="N", help="1 to 10 attempts (default 3)")
    parser.add_argument("--auto-fix-usd-cap", type=float, metavar="USD", help="maximum fixer spend across attempts")
    parser.add_argument("--auto-fix-agent", choices=("muse-code", "llm-patch"), help="explicit fixer path; all live caps still apply")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--auto-fix-fixture", type=Path, metavar="PATCH", help="use a fixture patch offline")
    source.add_argument("--auto-fix-recorded", type=Path, metavar="PATCH", help="replay a recorded patch offline")


def configure(enabled, attempts=None, cap=None, *, fixture=None, recorded=None, agent=None):
    if agent not in (None, "muse-code", "llm-patch"):
        raise ValueError("unknown auto-fix agent")
    patch = fixture or recorded
    if type(enabled) is not bool:
        raise ValueError("auto-fix must be on or off")
    if not enabled:
        if any(v is not None for v in (attempts, cap, patch, agent)):
            raise ValueError("repair options require --auto-fix")
        return None, None
    if attempts is not None and (type(attempts) is not int or not 1 <= attempts <= 10):
        raise ValueError("--auto-fix-attempts must be between 1 and 10")
    if cap is not None and (type(cap) not in (float, int) or not math.isfinite(cap) or cap < 0):
        raise ValueError("--auto-fix-usd-cap must be a finite amount of 0 or more")
    config = {"attempts": 3 if attempts is None else attempts}
    if patch is not None:
        if agent is not None:
            raise ValueError("an agent selector cannot relabel an offline patch")
        data = read_bytes_capped(patch, label="offline repair patch")
        config.update(source="fixture" if fixture else "recorded", patchSha256=hashlib.sha256(data).hexdigest())
        return config, data
    if cap is None:
        raise ValueError("a live fixer requires --auto-fix-usd-cap before verification starts")
    config.update(source="llm-patch" if agent == "llm-patch" else "muse", usdCap=live_cap(cap))
    return config, None


def live_cap(cli_cap):
    """Supply the requested cap to the metered worker, respecting any lower deployment cap."""
    try:
        from expectrail import spend
    except ImportError:
        raise ValueError("live auto-fix requires the Muse spend meter from #436") from None
    try:
        role_cap = spend.parse_cap("muse")
    except spend.BudgetStop as exc:
        raise ValueError(str(exc)) from exc
    return cli_cap if role_cap is None else min(cli_cap, role_cap)


def launch(jobs, job, patch):
    if patch is not None:
        (jobs.paths(job).root / "auto-fix.patch").write_bytes(patch)
    return runner.spawn(jobs, job, [sys.executable, "-m", "expectrail.auto_fix", str(jobs.root),
                                    str(jobs.lease_seconds), job])


def worker(root, lease, job):
    jobs = store.JobStore(Path(root), lease_seconds=float(lease))
    if jobs.claim(job, os.getpid(), os.getpgid(0))["phase"] in store.FINAL:
        return
    settings = jobs.request(job)["autoFix"]
    status = runner.work(jobs, job, own_group=True)
    if status["decision"] != "reject":
        return
    folder = jobs.paths(job).root
    try:
        from expectrail import repair

        data = None
        if settings["source"] in ("muse", "llm-patch"):
            # This dedicated process owns the entire repair loop and its cumulative Muse meter.
            # Recheck the role cap before narrowing it. Never raise it.
            os.environ["EXPECTRAIL_MUSE_USD_CAP"] = str(live_cap(settings["usdCap"]))
        else:
            data = read_bytes_capped(folder / "auto-fix.patch", label="offline repair patch")
            if hashlib.sha256(data).hexdigest() != settings["patchSha256"]:
                raise ValueError("the saved repair patch changed")
        # Use the bytes whose digest was checked, including on later attempts.
        with tempfile.TemporaryDirectory(prefix="auto-fix-") as tmp:
            patch = None
            if data is not None:
                patch = Path(tmp) / "candidate.patch"
                patch.write_bytes(data)
            path, doc = repair.repair(jobs, job, attempts=settings["attempts"], fixture=patch,
                                      recorded=settings["source"] == "recorded",
                                      agent="llm-patch" if settings["source"] == "llm-patch" else "muse-code")
        block = {"state": "finished", "decision": doc["result"]["decision"], "stopReason": doc["stop"]["reason"],
                 "record": path.relative_to(folder).as_posix()}
        if doc["result"]["patch"]:
            block["review"] = doc["review"]
    except Exception as exc:
        # A failed repair must never erase a completed verification or claim a candidate won.
        block = {"state": "interrupted", "detail": redact(str(exc))[:600] or type(exc).__name__}
    jobs.finish_repair(job, block)


if __name__ == "__main__":
    worker(*sys.argv[1:])
