"""Release gate, identity and authority (#258): the rows that need neither the trusted job (#254) nor
the signed receipt (#255).

An approval added by the change: the checks that judge a change are read from its base, so a head
that approves its own draft check is judged by nothing. With the check approved in the base too, the
same head is cleared: the approval's origin is the only difference.

A swapped policy: a job names the digest of the checks it was asked with. The checks are changed
after the job was created and before its worker begins (the worker is held for that moment:
``tests.release_gate.worker``), in the checkout they are read from. The worker reads them again,
finds another digest, and judges nothing: the engine never runs and the job says why. The swap is a
weakening, the check's tolerance raised from 20 px to 100,000 px. (Asked for afresh, that weakened
check does not clear the seeded bug in this suite either: the recorded observer has no answers for
its questions, so it is needs-review. What these tests show is the defence itself, that a swapped
check is never used.) Put back byte for byte, the same held job is cleared, so the content of the
checks is what is compared, not a file's time.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.release_gate.common import SPEC_FILE, GateCase, edit_json
from tests.release_gate.worker import HOLD

CHANGED = "the game or its checks changed after the job was created"


def weaken(doc: dict) -> None:
    """The swap: the check's tolerance raised from 20 px to 100,000 px."""
    doc["assertion"]["boundary"]["tolerancePx"] = 100000


class IdentityTest(GateCase):
    def test_an_approval_the_change_adds_to_its_own_checks_judges_nothing(self):
        base = self.copy("base-draft")
        edit_json(base / SPEC_FILE, lambda doc: doc.pop("approval"))   # in the base, the check is a draft
        head = self.copy("head-approves")                               # the change carries it approved
        code, status, err = self.verify(head, base=base)
        self.assertNotCleared(code, status, err)
        self.assertEqual((code, status["decision"]), (2, "needs-review"))
        self.assertIn("no checks ran", status["reasons"])
        # The same head against a base whose check is approved: cleared.
        code, status, err = self.verify(head, base=self.clean)
        self.assertEqual((code, status["decision"]), (0, "accept"), err)

    # --- swapped policy -----------------------------------------------------------------------------
    def held_job(self, head: Path, *extra: str) -> tuple[str, Path]:
        """A job created and named, whose worker waits until the returned file is removed."""
        hold = self.tmp / "hold"
        hold.write_text("held\n", encoding="utf-8")
        job = self.start(head, *extra, env={HOLD: str(hold)})
        self.assertEqual(self.store.status(job)["phase"], "queued")
        return job, hold

    def release(self, job: str, hold: Path) -> tuple[int, dict]:
        hold.unlink()
        self.wait_until(job, ("completed", "failed", "cancelled"), seconds=240)
        return self.status(job)

    def test_checks_swapped_between_the_request_and_the_run_judge_nothing(self):
        # No base: the head's own checks judge it, so the swap is made in the head.
        head = self.copy("swap-head", self.bug)
        job, hold = self.held_job(head)
        edit_json(head / SPEC_FILE, weaken)
        code, status = self.release(job, hold)
        self.assertNotCleared(code, status)
        self.assertEqual((code, status["phase"], status["decision"], status["output"]),
                         (2, "completed", "needs-review", None))
        self.assertEqual([d["code"] for d in status["diagnostics"]], ["INPUT_INVALID"])
        self.assertIn(CHANGED, status["diagnostics"][0]["detail"])

    def test_the_base_checks_swapped_after_the_request_judge_nothing(self):
        # With a base, the checks are read from the base: the swap is made there, the head untouched.
        base = self.copy("swap-base")
        job, hold = self.held_job(self.bug, "--base", str(base))
        edit_json(base / SPEC_FILE, weaken)
        code, status = self.release(job, hold)
        self.assertNotCleared(code, status)
        self.assertEqual((code, status["decision"], status["output"]), (2, "needs-review", None))
        self.assertIn(CHANGED, status["diagnostics"][0]["detail"])

    def test_checks_swapped_and_put_back_exactly_are_the_checks_that_were_named(self):
        # The control: the same hold and the same swap, undone byte for byte before the worker begins.
        head = self.copy("swap-and-back")
        spec = head / SPEC_FILE
        original = spec.read_bytes()
        job, hold = self.held_job(head)
        edit_json(spec, weaken)
        self.assertNotEqual(spec.read_bytes(), original)
        spec.write_bytes(original)
        code, status = self.release(job, hold)
        self.assertEqual((code, status["decision"]), (0, "accept"), json.dumps(status["diagnostics"]))
