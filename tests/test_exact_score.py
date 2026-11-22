import unittest

from expectrail.contracts import validate
from expectrail.evaluator import evaluate
from expectrail.gate import record, verify


LABEL = "InterfaceLayer/PauseMenu/ColorRect/CoinsCounter/Label"
ROUTE = "hold-right-then-toggle-pause"


def score_spec(**coverage):
    return {
        "format": "expectrail.test-spec/v0",
        "id": "exact-score",
        "instruction": "The final coin counter reads five after pickups.",
        "objects": {"score": {"prompt": "coin counter"}},
        "assertion": {"type": "exact-ui-integer", "object": "score", "labelPath": LABEL,
                      "expected": 5, "routeTicks": 4},
        "coverage": {"routes": [ROUTE], **coverage},
    }


def observation_frames(*frames):
    return {"format": "expectrail.observations/v0", "replay": {"sha256": "0" * 64},
            "model": {"name": "engine"}, "frames": [{"frame": n, "objects": {}} for n in frames]}


def score_trace(score, *, exercised=True):
    initial = [[i, 0] for i in range(5)]
    final = [] if exercised else initial
    return {"unknownActions": [], "physicsTicksPerSecond": 60, "rows": [
        {"tick": 0, "coins": initial},
        {"tick": 1, "coins": initial},
        {"tick": 2, "coins": final, "uiLabelIntegers": {LABEL: 5}},
        {"tick": 3, "coins": final, "uiLabelIntegers": {LABEL: score}},
    ]}


def judge(trace, *, spec=None, route=ROUTE, source="trace", frames=(0, 1, 2, 3)):
    verdict = evaluate(score_spec() if spec is None else spec, observation_frames(*frames),
                       route=route, trace=trace, source_kind=source, expected_frames=[0, 1, 2, 3])
    validate(verdict, "verdict")
    return verdict


class ExactScoreTest(unittest.TestCase):
    def test_clean_exact_integer_and_both_public_wrong_values(self):
        for score, result in [(5, "pass"), (10, "fail"), (0, "fail")]:
            with self.subTest(score=score):
                verdict = judge(score_trace(score))
                self.assertEqual(verdict["result"], result)
                self.assertEqual(verdict["framesJudged"], 1)
                self.assertEqual(verdict["coverage"]["semanticResult"], result)
                self.assertEqual(verdict["firstFrame"], 3 if result == "fail" else None)
                self.assertIn(f"read {score}", verdict["reason"])

    def test_zero_pickup_control_needs_review_even_with_a_mismatch(self):
        verdict = judge(score_trace(0, exercised=False))
        self.assertEqual(verdict["result"], "needs-review")
        self.assertEqual(verdict["coverage"]["status"], "not-exercised")
        self.assertIn("no pickups", verdict["reason"])

    def test_missing_pickup_endpoints_cannot_produce_a_failure(self):
        for tick in (0, 3):
            with self.subTest(tick=tick):
                trace = score_trace(10)
                del trace["rows"][tick]["coins"]
                verdict = judge(trace)
                self.assertEqual(verdict["result"], "needs-review")
                self.assertEqual(verdict["coverage"]["status"], "insufficient-observation")

    def test_missing_or_invalid_bound_value_needs_review(self):
        for fields in ({}, {"Other/Label": 10}, {LABEL: None}, {LABEL: True}, {LABEL: "10"},
                       {LABEL: 1_000_000_001}):
            with self.subTest(fields=fields):
                trace = score_trace(10)
                trace["rows"][-1]["uiLabelIntegers"] = fields
                trace["rows"][-1]["uiIntegers"] = [10]
                self.assertEqual(judge(trace)["result"], "needs-review")

    def test_incomplete_route_or_observations_cannot_produce_a_failure(self):
        trace = score_trace(10)
        self.assertEqual(judge(trace, frames=(0, 1, 3))["result"], "needs-review")
        self.assertEqual(judge(trace, frames=(0, 1, 2))["result"], "needs-review")
        for ticks in [(0, 1, 3), (0, 2, 1, 3), (0, 1, 1, 3), (0, False, 2, 3)]:
            with self.subTest(ticks=ticks):
                trace = score_trace(10)
                trace["rows"] = [{**row, "tick": tick} for row, tick in zip(trace["rows"], ticks)]
                self.assertEqual(judge(trace)["result"], "needs-review")
        trace = score_trace(10)
        trace["unknownActions"] = ["move_right"]
        self.assertEqual(judge(trace)["result"], "needs-review")

    def test_route_scope_and_visual_context(self):
        self.assertEqual(judge(score_trace(10), route="other")["result"], "not-applicable")
        self.assertEqual(judge(score_trace(10), route=None)["result"], "needs-review")
        self.assertEqual(judge(score_trace(5), source="image")["result"], "needs-review")
        self.assertEqual(judge(score_trace(10), source=None)["result"], "needs-review")

    def test_a_declared_checkpoint_must_be_reached_before_comparison(self):
        spec = score_spec(reached=[{"type": "on-floor"}])
        trace = score_trace(10)
        self.assertEqual(judge(trace, spec=spec)["result"], "needs-review")

    def test_gate_reports_engine_failure_and_preserves_the_both_rule(self):
        calls = []

        class Observer:
            def look(self, *args, **kwargs):
                calls.append((args, kwargs))

        def through_gate(score, rule, visual=None):
            run = {"trace": score_trace(score), "engineObservations": observation_frames(0, 1, 2, 3)}
            return verify.judge_run(score_spec(), run, rule=rule, visual=visual, route=ROUTE, ticks=4)["result"]

        self.assertEqual(through_gate(5, record.ENGINE_ONLY), "pass")
        self.assertEqual(through_gate(5, record.BOTH, Observer()), "needs-review")
        self.assertEqual(through_gate(10, record.BOTH), "fail")
        self.assertEqual(calls, [])
