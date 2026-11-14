"""Release gate, operations (#258): timeout, cancellation, a killed worker, retry, duplicate requests.

Each test runs the orchestrator's command, ``verify``, whose worker runs the real Godot replay of the
bundled game and judges it with both observers (the visual one answering from recorded answers:
``tests.release_gate.worker``), and asserts that clearance (exit 0, a job completed as accept) is not granted, that the
job names the reason, and that nothing it started is left running. ``BaselineTest`` is the positive
control: the same command on the same game does clear it, so "not cleared" here means something.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time

from tests.release_gate.common import GAME, LEASE, REPO, ROUTE, SPECS, GateCase


def codes(status: dict) -> list[str]:
    return [d["code"] for d in status["diagnostics"]]


class BaselineTest(GateCase):
    def test_the_unchanged_game_is_cleared_through_the_same_command(self):
        code, status, err = self.verify(self.clean)
        self.assertEqual((code, status["phase"], status["decision"]), (0, "completed", "accept"), err)
        # Nothing here can defend against a frame the game rewrites (#246), so no grade above
        # `diagnostic` is given: the release gate's "rewritten frame" row stays open on this.
        self.assertEqual(status["evidenceGrade"], "diagnostic")
        code, status, err = self.verify(self.bug, base=self.clean)
        self.assertEqual((code, status["decision"]), (1, "reject"), err)


class OperationsTest(GateCase):
    def test_a_job_that_runs_out_of_time_is_not_clearance_and_leaves_nothing_running(self):
        code, status, err = self.verify(self.clean, "--timeout", "3")
        self.assertNotCleared(code, status, err)
        self.assertEqual((code, status["phase"], status["decision"], status["output"]),
                         (2, "completed", "needs-review", None))
        self.assertIn("EXECUTION_TIMEOUT", codes(status))

    def test_a_cancelled_job_is_not_clearance_and_leaves_nothing_running(self):
        job = self.start(self.clean)
        self.game_running(job)
        code, out, err = self.command("cancel", job, "--json")
        status = json.loads(out)
        self.assertNotCleared(code, status, err)
        self.assertEqual((code, status["phase"], status["decision"], status["output"]), (4, "cancelled", None, None))
        code, out, _ = self.command("report", job)
        self.assertEqual(code, 4)
        self.assertFalse(self.store.paths(job).output.exists())

    def test_a_killed_worker_is_not_clearance_and_leaves_nothing_running(self):
        job = self.start(self.clean)
        self.kill_worker(job)
        code, status = self.wait_for_status(job)
        self.assertNotCleared(code, status)
        self.assertEqual((code, status["phase"], status["decision"], status["output"]), (3, "failed", None, None))
        self.assertIn("WORKER_LOST", codes(status))

    def test_asking_again_after_a_lost_worker_returns_the_failure_not_a_new_verdict(self):
        job = self.start(self.clean, "--idempotency-key", "retry-1")
        self.kill_worker(job)
        self.assertEqual(self.wait_for_status(job)[0], 3)
        code, status, err = self.verify(self.clean, "--idempotency-key", "retry-1")
        self.assertNotCleared(code, status, err)
        self.assertEqual((code, status["id"], status["phase"]), (3, job, "failed"))
        self.assertEqual(len(list((self.jobs / "jobs").iterdir())), 1, "asking again started another job")

    def test_a_key_used_for_one_change_does_not_clear_another(self):
        code, status, err = self.verify(self.clean, "--idempotency-key", "dup-1")
        self.assertEqual((code, status["decision"]), (0, "accept"), err)
        # The broken game, compared with the clean one, asks under the same key: the earlier accept is
        # not handed to it.
        code, status, err = self.verify(self.bug, "--idempotency-key", "dup-1", base=self.clean)
        self.assertNotCleared(code, status, err)
        self.assertEqual(code, 5)
        self.assertIn("different inputs", err)

    def test_the_same_request_twice_at_once_is_one_job_with_one_verdict(self):
        argv = [sys.executable, "-m", "tests.release_gate.worker", "--jobs-root", str(self.jobs), "--lease-seconds", LEASE,
                "verify", "--head", str(self.bug), "--base", str(self.clean), "--game", GAME, "--routes", ROUTE,
                "--specs", SPECS, "--idempotency-key", "dup-2", "--json"]
        procs = [subprocess.Popen(argv, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for _ in range(2)]
        results = [(p.wait(timeout=300), p.stdout.read(), p.stderr.read()) for p in procs]
        for proc in procs:
            proc.stdout.close()
            proc.stderr.close()
        statuses = [json.loads(out) for _, out, _ in results]
        self.watched += [s["id"] for s in statuses]
        for (code, _, err), status in zip(results, statuses):
            self.assertNotCleared(code, status, err)
        self.assertEqual({s["id"] for s in statuses}, {statuses[0]["id"]})
        self.assertEqual([(code, s["decision"]) for (code, _, _), s in zip(results, statuses)], [(1, "reject")] * 2)
        self.assertEqual(len(list((self.jobs / "jobs").iterdir())), 1)

    # --- helpers ------------------------------------------------------------------------------------
    def kill_worker(self, job: str) -> None:
        """Kill the job's worker and its process group while the game runs, as a machine that runs
        out of memory or an operator would."""
        self.game_running(job)
        worker = self.store.status(job)["worker"]
        os.killpg(worker["pgid"], signal.SIGKILL)

    def wait_for_status(self, job: str, seconds: float = 30) -> tuple[int, dict]:
        """`expectrail status` until the job is final: a worker that is gone is noticed there when its
        lease runs out."""
        deadline = time.monotonic() + seconds
        while True:
            code, status = self.status(job)
            if status["phase"] in ("completed", "failed", "cancelled") or time.monotonic() > deadline:
                return code, status
            time.sleep(0.2)
