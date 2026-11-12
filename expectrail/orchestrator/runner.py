"""Running one job: the worker's body, starting a worker process, and waiting for a job.

The worker runs in a process group of its own, so cancelling a job stops the game and everything else
it started. It renews the job's lease while it works. When the time limit passes, it completes the
job as needs-review and stops its own group: a job that ran out of time is never a pass.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

from expectrail import diagnostics as diag
from expectrail.orchestrator import engines as eng
from expectrail.orchestrator import request as req
from expectrail.orchestrator import store as st

EXPECTRAIL_ROOT = Path(__file__).resolve().parent.parent.parent
# A failure with one of these codes is a known reason there is no result: the job completes as
# needs-review and says why. Anything else is the orchestrator's own failure.
EXPLAINED = ("INPUT_INVALID", "TOOL_MISSING", "PRIVATE_SUITE_UNAVAILABLE", "PROVIDER_FAILED",
             "EXECUTION_TIMEOUT", "BASE_MISMATCH", "EVIDENCE_MISMATCH")


def _needs_review(store: st.JobStore, job_id: str, diagnostics: list[dict]) -> dict:
    return store.finish(job_id, "completed", decision="needs-review", diagnostics=diagnostics,
                        reasons=[f"{d['code']}: {d['detail']}" for d in diagnostics])


def work(store: st.JobStore, job_id: str, engines: dict | None = None, *, own_group: bool = False) -> dict:
    """Do the job and return its final status. ``own_group`` says this process leads a process group
    made for the job, so it may stop that whole group when the time limit passes."""
    engines = eng.ENGINES if engines is None else engines
    request = store.request(job_id)
    if store.claim(job_id, os.getpid(), os.getpgid(0))["phase"] in st.FINAL:
        return store.status(job_id)   # cancelled before the worker got going: nothing to do
    paths = store.paths(job_id)
    done = threading.Event()

    def beat() -> None:
        while not done.wait(max(store.lease_seconds / 3, 0.05)):
            store.heartbeat(job_id)

    def out_of_time() -> None:
        if done.wait(request["limits"]["timeoutSeconds"]):
            return
        _needs_review(store, job_id, [st.diagnostic(
            "EXECUTION_TIMEOUT", stage="executing",
            detail=f"the job passed its limit of {request['limits']['timeoutSeconds']} s")])
        if own_group and os.getpid() == os.getpgid(0):
            os.killpg(os.getpgid(0), signal.SIGKILL)

    for target in (beat, out_of_time):
        threading.Thread(target=target, daemon=True).start()
    try:
        engine = engines.get(request["project"]["adapter"])
        if engine is None:
            return _needs_review(store, job_id, [st.diagnostic(
                "INPUT_INVALID", stage="preparing", detail=f"no adapter named {request['project']['adapter']!r}")])
        status = store.advance(job_id, "preparing")
        # The files are read again here, by the process that will run them. A link that leaves the
        # checkout stops the job, and so does a game or a check that changed since the job was
        # created: its recorded inputs would describe files that were not the ones verified.
        blocking = [st.diagnostic("INPUT_INVALID", stage="preparing", detail=why) for why in req.problems(request)]
        if not blocking and req.inputs(request) != status["inputs"]:
            blocking = [st.diagnostic("INPUT_INVALID", stage="preparing",
                                      detail="the game or its checks changed after the job was created; ask again")]
        blocking = blocking or engine.preflight(request)
        if blocking:
            return _needs_review(store, job_id, blocking)
        store.advance(job_id, "executing")
        result = engine.execute(request, paths, lambda phase: store.advance(job_id, phase))
        # The worker read the files just before the run and the engine read them again to run them.
        # If the evidence names another tree than the job's inputs, the game changed in between:
        # the decision is about files nobody asked about, so it is not given and its evidence is
        # not published under this job.
        moved = [side for side in ("head", "base") if (result.trees or {}).get(f"{side}Tree") is not None
                 and result.trees[f"{side}Tree"] != status["inputs"][f"{side}Tree"]]
        if moved:
            return _needs_review(store, job_id, [st.diagnostic(
                "INPUT_INVALID", stage="executing",
                detail=f"the {' and the '.join(moved)} game changed while the job was running; what was "
                       f"verified is not what was asked. Ask again")])
        return store.finish(job_id, "completed", decision=result.decision, reasons=result.reasons,
                            evidence_grade=result.evidence_grade, publish=True)
    except BaseException as exc:  # noqa: BLE001 - whatever happens, the job ends in a final phase
        if isinstance(exc, KeyboardInterrupt):
            raise
        found = _explain(exc)
        if found is not None:
            return _needs_review(store, job_id, [found])
        traceback.print_exc()
        return store.finish(job_id, "failed", reasons=["the orchestrator failed; this says nothing about the change"],
                            diagnostics=[st.diagnostic("INTERNAL_ERROR", stage="executing",
                                                       detail=f"{type(exc).__name__}: {exc}")])
    finally:
        done.set()


def _explain(exc: BaseException) -> dict | None:
    names = {cls.__name__ for cls in type(exc).__mro__}
    if names & {"ConfigError", "RequestError", "ContractError"}:
        return st.diagnostic("INPUT_INVALID", stage="executing", detail=str(exc))
    if isinstance(exc, (SystemExit, Exception)):
        found = diag.classify(exc if isinstance(exc, Exception) else None, stage="executing", detail=str(exc))
        if found["code"] in EXPLAINED:
            return found
    return None


def spawn(store: st.JobStore, job_id: str, command: list[str] | None = None) -> subprocess.Popen:
    """Start a worker for a queued job in a session of its own and record it as the job's worker.
    ``command`` replaces the worker's command line (tests run a worker with stand-in engines)."""
    paths = store.paths(job_id)
    command = command or [sys.executable, "-m", "expectrail.orchestrator", "--jobs-root", str(store.root),
                          "--lease-seconds", str(store.lease_seconds), "_work", job_id]
    with open(paths.log, "ab") as log:
        proc = subprocess.Popen(
            command,
            cwd=EXPECTRAIL_ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            # The job's id in the environment is how what this worker starts is found if it is killed.
            env=dict(os.environ, **{st.JOB_ENV: job_id}),
            start_new_session=True)
    # The worker claims the job too, as soon as it starts; whichever call comes first records it.
    store.claim(job_id, proc.pid, proc.pid)
    return proc


def wait(store: st.JobStore, job_id: str, proc: subprocess.Popen | None = None, *, poll_seconds: float = 0.2,
         on_phase=None) -> dict:
    """Block until the job is final. With the worker's process in hand, a worker that exited without
    finishing is seen at once instead of when its lease runs out."""
    last = None
    while True:
        status = store.status(job_id)
        if on_phase is not None and status["phase"] != last:
            on_phase(status)
        last = status["phase"]
        if status["phase"] in st.FINAL:
            if proc is not None:
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            return status
        if proc is not None and proc.poll() is not None:
            status = store.status(job_id)
            if status["phase"] not in st.FINAL:
                return store.lose(job_id, "the worker stopped before the job finished", stage=status["phase"],
                                  detail=f"the worker exited with code {proc.returncode}")
            return status
        time.sleep(poll_seconds)
