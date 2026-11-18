"""jit.yml's model steps set the spec sender's cap (#285, #267).

The propose and revise steps send one Muse Spark request each through ``spec_writer.http_transport``
(``intent.spark_intent``'s default transport). Since #267 that sender holds against
``EXPECTRAIL_SPEC_USD_CAP`` and sends nothing when it is unset. A step that does not set it stops before
its first request, and ``spark_intent`` records the stop as the model being unavailable, so a live
dispatch spends runner time and measures nothing (found by #573's preflight).

These tests read the workflow, build each model step's environment from the job's and the step's
``env`` with the plan's budget filled in, and send one request through the real propose path with the
network replaced. Nothing here runs a workflow, a game or a model."""
from __future__ import annotations

import io
import json
import os
import re
import unittest
from pathlib import Path
from unittest import mock

import yaml

from expectrail import spend
from expectrail.jit import intent
from expectrail.jit.diff_map import diff_map
from expectrail.jit.probes import jit_library
from tests.jit_fixtures import PROFILE, reply

REPO = Path(__file__).resolve().parents[1]
WF = REPO / ".github" / "workflows" / "jit.yml"
PROF = json.loads(PROFILE.read_text(encoding="utf-8"))
NO_FIX = REPO / "bench" / "jit" / "public" / "no-fix.patch"
REPORT = "When I jump and press shoot in the air, nothing comes out."
BUDGET = "2"
# A command that sends a model request through the spec sender.
SENDS = re.compile(r"python -m expectrail\.jit\.cli (propose|revise)\b")
EXPR = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")
# One valid check, the shape tests/test_jit_offer.py uses, so the answer parses once it is sent.
ANSWER = reply({"candidates": [
    {"id": "check-0", "statement": "A rule.", "claimId": "player.jump", "class": "player",
     "operation": {"type": "relation", "signal": "air_jumps", "comparator": "lte", "toleranceAbs": 0,
                   "left": "jump-w0-x2", "right": "jump-w0-x8"}}]},
    usage={"prompt_tokens": 10, "completion_tokens": 10})


def model_steps() -> list[tuple[str, dict, dict]]:
    """Every (job name, job, step) of jit.yml whose run line sends a model request."""
    doc = yaml.safe_load(WF.read_text(encoding="utf-8"))
    return [(name, job, s) for name, job in doc["jobs"].items() for s in job.get("steps", [])
            if SENDS.search(s.get("run") or "")]


def resolve(value) -> str:
    """The value as the runner would give it: the plan's budget filled in, a secret as a stand-in."""
    def one(m: re.Match) -> str:
        expr = m.group(1)
        if expr == "needs.plan.outputs.budget":
            return BUDGET
        if expr.startswith("secrets."):
            return "test-not-a-key"
        return "x"
    return EXPR.sub(one, str(value))


def step_env(job: dict, step: dict) -> dict:
    env = {k: resolve(v) for k, v in (job.get("env") or {}).items()}
    env.update({k: resolve(v) for k, v in (step.get("env") or {}).items()})
    return env


def propose_once() -> None:
    patch = NO_FIX.read_text(encoding="utf-8")
    probes = jit_library(PROF["actions"])
    intent.spark_intent()(REPORT, patch, diff_map(patch, PROF, probes), PROF, probes)


class ModelStepsSetTheSpecCap(unittest.TestCase):
    def setUp(self):
        spend.reset_for_tests()
        self.addCleanup(spend.reset_for_tests)

    def test_both_model_steps_are_found(self):
        self.assertEqual(sorted(name for name, _, _ in model_steps()), ["propose", "revise"])

    def test_every_model_step_caps_the_spec_sender_at_the_changes_budget(self):
        for name, job, step in model_steps():
            with self.subTest(job=name):
                env = step_env(job, step)
                self.assertEqual(env.get("EXPECTRAIL_SPEC_USD_CAP"), BUDGET,
                                 f"{name}: the spec sender's cap must be the plan's per-defect budget")
                self.assertEqual(env.get("EXPECTRAIL_SPEC_USD_CAP"), env.get("BUDGET"))

    def test_with_exactly_a_model_steps_environment_the_request_is_sent(self):
        for name, job, step in model_steps():
            with self.subTest(job=name):
                spend.reset_for_tests()
                with mock.patch.dict(os.environ, step_env(job, step), clear=True), \
                        mock.patch("urllib.request.urlopen",
                                   return_value=io.BytesIO(json.dumps(ANSWER).encode())) as network:
                    propose_once()
                network.assert_called_once()
                self.assertEqual(spend.METER.snapshot_roles()["spec"]["requests"], 1)

    def test_without_the_cap_nothing_is_sent_and_the_step_records_the_model_unavailable(self):
        # The failure the workflow had: the stop is swallowed into an unavailable model, not a crash.
        _, job, step = model_steps()[0]
        env = step_env(job, step)
        env.pop("EXPECTRAIL_SPEC_USD_CAP", None)
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("urllib.request.urlopen") as network:
            with self.assertRaises(intent.IntentUnavailable) as stopped:
                propose_once()
        network.assert_not_called()
        self.assertIn("EXPECTRAIL_SPEC_USD_CAP", str(stopped.exception))


if __name__ == "__main__":
    unittest.main()
