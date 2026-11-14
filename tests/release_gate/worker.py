"""The release gate's worker and command: the orchestrator's own, with the visual observer answering
from the recorded vision answers of the "Run it" samples (docs/run-it/vision/), so no model is called
and nothing is spent.

    python3 -m tests.release_gate.worker verify ...     the orchestrator's command line (cli.main),
                                                        whose workers are started as below
    python3 -m tests.release_gate.worker _work ROOT LEASE JOB

Since #379 the registered engine judges with both observers and, without a vision key, accepts
nothing. The release gate needs a run that can be cleared, or "not cleared" would say nothing: these
workers run the same engine (``GodotGate``, rule ``both``, a real Godot replay) with a
``RecordedObserver`` over the three samples' recordings joined. An answer is found only for a frame
whose SHA256 and prompt were recorded; any other frame gets none, so the decision is needs-review, as
on the site. Everything else is the orchestrator's code, unchanged: the command line, the job store,
the worker's body, the time limit, cancelling and leases.

One addition, for the "swapped policy" row only: when ``EXPECTRAIL_RELEASE_GATE_HOLD`` names a file,
the worker waits while that file exists (at most ``HOLD_SECONDS``) before it begins the job. The job
has been created by then and names its inputs, so a test can change a check between the request and
the run without racing the worker. The worker is alive while it waits, so its lease holds.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from expectrail import recorded
from expectrail.gate import record as rec
from expectrail.orchestrator import cli, engines, runner
from expectrail.orchestrator import store as st

REPO = Path(__file__).resolve().parents[2]
RECORDINGS = ("clean", "fall-through-bug", "fall-through-repair")
HOLD = "EXPECTRAIL_RELEASE_GATE_HOLD"
HOLD_SECONDS = 120


def recording() -> dict:
    """The samples' recordings as one: every answer, once. A frame recorded in two samples (the clean
    game is the head of one and the base of another) can carry two takes of the model's answer about
    that same picture; the first one, in the order of RECORDINGS, is kept. No answer is ever used for
    a frame with another SHA256 or for another prompt."""
    docs = [recorded.read_recording(REPO / "docs" / "run-it" / "vision" / f"{name}.json") for name in RECORDINGS]
    answers, seen = [], {}
    for doc in docs:
        for answer in doc["answers"]:
            key = (answer["kind"], answer["frameSha256"], answer["prompt"])
            if key in seen:
                continue
            seen[key] = answer["detections"]
            answers.append(answer)
    first = docs[0]
    return {**first, "sample": "release-gate", "answers": answers}


def table() -> dict:
    return {"godot": engines.GodotGate(rule=rec.BOTH, visual=recorded.RecordedObserver(recording()))}


def hold() -> None:
    """Wait while the file named by ``EXPECTRAIL_RELEASE_GATE_HOLD`` exists (see the module's note)."""
    named = os.environ.get(HOLD)
    if not named:
        return
    deadline = time.monotonic() + HOLD_SECONDS
    while Path(named).exists() and time.monotonic() < deadline:
        time.sleep(0.05)


def spawn(store: st.JobStore, job_id: str, command: list[str] | None = None):
    return SPAWN(store, job_id, command=command or [
        sys.executable, "-m", "tests.release_gate.worker", "_work", str(store.root), str(store.lease_seconds), job_id])


SPAWN = runner.spawn

if __name__ == "__main__":
    if sys.argv[1:2] == ["_work"]:
        root, lease, job = sys.argv[2:5]
        hold()
        runner.work(st.JobStore(Path(root), lease_seconds=float(lease)), job, engines=table(), own_group=True)
        sys.exit(0)
    runner.spawn = spawn
    sys.exit(cli.main(sys.argv[1:], prog="expectrail"))
