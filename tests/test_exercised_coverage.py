"""Required coverage cannot be inferred from checks that happened to produce a row. No live model."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from expectrail import contracts
from expectrail.coverage import evidence_result
from expectrail.evaluator import evaluate
from expectrail.gate import record as rec
from expectrail.gate import verify as gv
from tests.test_evaluator import ABOVE, GROUND, det, obs, spec
from tests.test_two_observers import Case, SPEC, SPEC_ID, TICKS, repo

REPO = Path(__file__).resolve().parent.parent
ZERO = dict(status="not-used", **gv.HELD_ZERO)
PASS = {"checks": 1, "passed": 1, "failed": 0, "needsReview": 0}


def observed(count=120, overlaps=None):
    return obs(*[(n, {"player": det((100, 600, 160, 700)),
                      "ground": GROUND if overlaps is None or n in overlaps else det((900, 700, 1200, 800))})
                 for n in range(count)])


def bounded(coverage=None):
    doc = spec(copy.deepcopy(ABOVE), window={"fromFrame": 0, "toFrame": 119})
    if coverage is not None:
        doc["coverage"] = coverage
    return doc


class CoverageEvaluatorTest(unittest.TestCase):
    def test_a_single_overlap_in_a_full_window_is_not_exercised(self):
        v = evaluate(bounded(), observed(overlaps={50}))
        self.assertEqual((v["result"], v["framesJudged"]), ("needs-review", 1))
        self.assertEqual(v["coverage"]["semanticResult"], "not_exercised")
        self.assertTrue(v["reason"].startswith("not-exercised:"))
        self.assertIn("needs 2", v["reason"])
        contracts.validate(v, "verdict")

    def test_window_truncated_to_one_frame_never_passes(self):
        v = evaluate(bounded(), observed(1))
        self.assertEqual(v["result"], "needs-review")
        self.assertIn("observed 1 of 120", v["reason"])
        self.assertFalse(v["coverage"]["completeWindow"])

    def test_number_and_share_use_the_stricter_requirement_and_round_up(self):
        doc = bounded({"minFrames": 20, "minFraction": 0.501})
        short = evaluate(doc, observed(overlaps=set(range(60))))
        self.assertEqual(short["result"], "needs-review")
        self.assertEqual(short["coverage"]["framesRequired"], 61)
        self.assertEqual(evaluate(doc, observed(overlaps=set(range(61))))["result"], "pass")
        doc["coverage"]["minFrames"] = 62
        self.assertEqual(evaluate(doc, observed(overlaps=set(range(61))))["result"], "needs-review")

    def test_an_explicit_one_frame_window_is_not_a_truncated_larger_window(self):
        doc = bounded()
        doc["window"] = {"fromFrame": 0, "toFrame": 0}
        self.assertEqual(evaluate(doc, observed(1))["result"], "pass")
        doc["coverage"] = {"minFrames": 2}
        self.assertEqual(evaluate(doc, observed(1))["result"], "needs-review")

    def test_route_not_applicable_is_distinct_from_required_checkpoint_not_reached(self):
        doc = bounded({"routes": ["smoke"], "reached": [{"type": "on-floor", "fromTick": 10}]})
        trace = {"rows": [{"tick": n, "player": [0, 0], "onFloor": False} for n in range(240)]}
        a = evaluate(doc, observed(), route="other", trace=trace)
        b = evaluate(doc, observed(), route="smoke", trace=trace)
        self.assertEqual((a["result"], a["coverage"]["status"]), ("not-applicable", "not-applicable"))
        self.assertEqual((b["result"], b["coverage"]["status"]), ("needs-review", "not-reached"))
        self.assertIn("not-reached", b["reason"])
        self.assertEqual(a["coverage"]["semanticResult"], "not_exercised")
        self.assertEqual(b["coverage"]["semanticResult"], "not_exercised")
        self.assertEqual(evaluate(doc, observed())["result"], "needs-review")

    def test_checkpoint_data_missing_is_unknown_not_an_invented_zero(self):
        for condition in ({"type": "on-floor"}, {"type": "position-region", "box": [0, 0, 5, 5]},
                          {"type": "coin-count-change"}):
            with self.subTest(condition=condition):
                v = evaluate(bounded({"reached": [condition]}), observed(), trace={"rows": [{"tick": 0}]})
                self.assertEqual(v["result"], "needs-review")
                self.assertEqual(v["coverage"]["semanticResult"], "insufficient_observation")
                self.assertIn("checkpoint data unavailable", v["reason"])

    def test_all_declared_checkpoint_kinds_and_their_tick_thresholds(self):
        trace = {"rows": [{"tick": 0, "player": [1, 1], "onFloor": True, "coins": [[5, 5]]},
                           {"tick": 10, "player": [20, 20], "onFloor": False, "coins": []}]}
        conditions = [{"type": "on-floor"}, {"type": "position-region", "box": [10, 10, 30, 30]},
                      {"type": "coin-count-change"}]
        self.assertEqual(evaluate(bounded({"reached": conditions}), observed(), trace=trace)["result"], "pass")
        conditions[0]["fromTick"] = 1
        self.assertEqual(evaluate(bounded({"reached": conditions}), observed(), trace=trace)["coverage"]["status"],
                         "not-reached")
        conditions[0]["fromTick"] = 50
        self.assertEqual(evaluate(bounded({"reached": conditions}), observed(), trace=trace)["result"], "needs-review")

    def test_a_counterexample_still_fails_with_incomplete_coverage(self):
        observation = obs((0, {"player": det((100, 680, 160, 785)), "ground": GROUND}))
        v = evaluate(bounded({"minFrames": 100, "reached": [{"type": "on-floor"}]}), observation)
        self.assertEqual((v["result"], v["firstFrame"]), ("fail", 0))
        self.assertEqual(v["coverage"]["semanticResult"], "fail")

    def test_duplicate_frames_cannot_inflate_the_count(self):
        data = observed(1)
        data["frames"] *= 120
        with self.assertRaisesRegex(ValueError, "duplicate frame"):
            evaluate(bounded(), data)

    def test_the_shared_semantics_retain_the_trace_evaluators_order(self):
        default = dict(counterexample=False, applicable="yes", triggered=2, evaluated=2,
                       minimum_triggers=1, minimum_evaluations=2, complete=True, complete_window=True)
        for changes, want in (({}, "pass"), ({"counterexample": True, "applicable": "unknown"}, "fail"),
                              ({"applicable": "unknown"}, "insufficient_observation"),
                              ({"applicable": "no"}, "not_exercised"), ({"triggered": 0}, "not_exercised"),
                              ({"evaluated": 1}, "not_exercised"), ({"complete": False}, "insufficient_observation")):
            self.assertEqual(evidence_result(**dict(default, **changes)), want)

    def test_sampler_collects_full_evidence_for_explicit_coverage(self):
        from agents.sam_observations import sampling_plan
        for kind in ("never-crosses", "reaches"):
            for requirement in ({"minFrames": 10}, {"minFraction": 0.8}):
                doc = bounded(requirement)
                doc["assertion"]["type"] = kind
                self.assertEqual(sampling_plan(doc, 30), 1)

    def test_legacy_decision_does_not_count_nonapplicable_rows_as_required_kinds(self):
        from expectrail.evaluator import decide, REQUIRED_CHECK_KINDS
        checks = [{"kind": kind, "spec": "x", "route": "other", "result": "not-applicable"}
                  for kind in REQUIRED_CHECK_KINDS]
        self.assertEqual(decide(checks)[0], "needs-review")

    def test_coverage_schema_and_unapproved_example(self):
        example = json.loads((REPO / "contracts/examples/test-spec-coverage.json").read_text())
        self.assertNotIn("approval", example)
        contracts.validate(example, "test-spec")
        self.assertEqual(rec.errors(example, gv._schema("test-spec")), [])
        for change in ({"minFrames": 0}, {"minFraction": 1.1}, {"routes": []},
                       {"reached": [{"type": "execute", "code": "no"}]}):
            mutant = dict(example, coverage=change)
            with self.subTest(change=change):
                self.assertTrue(rec.errors(mutant, gv._schema("test-spec")))


class CoverageGateTest(Case):
    def engine_gate(self, head):
        doc = self.gate(head, rule=rec.ENGINE_ONLY, visual=None)
        rec.read_record(self.out / "findings.json")
        return doc

    def test_empty_suite_needs_review(self):
        head = repo(self.tmp / "head")
        (head / "specs" / f"{SPEC_ID}.json").unlink()
        doc = self.engine_gate(head)
        self.assertEqual(doc["decision"], "needs-review")
        self.assertEqual(doc["counts"]["checks"], 0)
        self.assertEqual(rec.decide(dict(PASS, checks=0, passed=0), ZERO)[0], "needs-review")

    def test_required_route_skipped_blocks_other_passing_checks(self):
        head = repo(self.tmp / "head", spec_edit={"coverage": {"routes": ["smoke", "missing-route"]}})
        doc = self.engine_gate(head)
        self.assertEqual(doc["counts"], PASS)
        self.assertEqual(doc["decision"], "needs-review")
        self.assertTrue(any("1 required route(s)" in why for why in doc["reasons"]))
        forged = copy.deepcopy(doc)
        forged["decision"] = "accept"
        with self.assertRaisesRegex(rec.RecordError, "decision should be needs-review"):
            rec.check_record(forged)

    def test_a_route_that_cannot_replay_cannot_be_counted_as_skipped_success(self):
        doc = self.engine_gate(repo(self.tmp / "head", "CRASH"))
        self.assertEqual((doc["decision"], doc["checks"][0]["after"]), ("needs-review", "replay-error"))

    def test_nonapplicable_checks_are_not_passes_or_required_failures(self):
        head = repo(self.tmp / "head", spec_edit={"coverage": {"routes": ["smoke"]}})
        other = json.loads((head / "routes/smoke.json").read_text())
        other["name"] = "other"
        (head / "routes/other.json").write_text(json.dumps(other))
        doc = self.engine_gate(head)
        self.assertEqual(doc["decision"], "accept")
        self.assertEqual(doc["counts"], PASS)
        self.assertEqual({c["route"]: c["after"] for c in doc["checks"]}, {"smoke": "pass", "other": "not-applicable"})
        self.assertEqual(doc["findings"], [])
        from expectrail import viewer
        from expectrail.gate import comment
        from tests.test_ci_gate import ctx
        self.assertEqual(viewer.state_of(doc)[0], "accept")
        self.assertIn("not applicable", comment.render(doc, ctx()))
        self.assertIn("not applicable", (self.out / "review/index.html").read_text())
        forged = copy.deepcopy(doc)
        forged["specs"][0].pop("routes")
        with self.assertRaisesRegex(rec.RecordError, "applicability"):
            rec.check_record(forged)

    def test_nonapplicable_route_is_not_replayed_or_sent_to_the_observer(self):
        head = repo(self.tmp / "head", spec_edit={"coverage": {"routes": ["other"]}})
        doc = self.gate(head, rule=rec.BOTH)
        self.assertEqual(doc["checks"][0]["after"], "not-applicable")
        self.assertEqual(self.game.replays, [])
        self.assertEqual(self.game.asked, [])
        self.assertEqual(doc["decision"], "needs-review")
        rec.read_record(self.out / "findings.json")

    def test_only_nonapplicable_checks_do_not_make_an_accept(self):
        doc = self.engine_gate(repo(self.tmp / "head", spec_edit={"coverage": {"routes": ["other"]}}))
        self.assertEqual(doc["decision"], "needs-review")
        self.assertEqual(doc["counts"]["checks"], 0)
        self.assertEqual(doc["checks"][0]["after"], "not-applicable")

    def test_one_observed_frame_cannot_pass_even_with_explicit_minimum_one(self):
        head = repo(self.tmp / "head", spec_edit={"coverage": {"minFrames": 1}})
        original = gv.observations
        def one(*args):
            document = original(*args)
            document["frames"] = document["frames"][:1]
            return document
        with patch.object(gv, "observations", one):
            doc = self.engine_gate(head)
        self.assertEqual(doc["decision"], "needs-review")
        self.assertIn("covers 1 of 120 frames", doc["findings"][0]["reason"])

    def test_disabled_required_observer_blocks_accept(self):
        self.assertEqual(rec.decide(PASS, ZERO, observers={"rule": "both", "visual": None})[0], "needs-review")
        doc = self.gate(repo(self.tmp / "head"), rule=rec.BOTH, visual=None)
        self.assertEqual(doc["decision"], "needs-review")
        rec.read_record(self.out / "findings.json")

    def test_checkpoint_never_reached_blocks_accept_under_both_rules(self):
        declaration = {"reached": [{"type": "position-region", "box": [1000, 1000, 1010, 1010]}]}
        for rule in rec.RULES:
            with self.subTest(rule=rule):
                head = repo(self.tmp / rule, spec_edit={"coverage": declaration})
                doc = self.gate(head, rule=rule, visual=self.game.observer() if rule == rec.BOTH else None)
                self.assertEqual(doc["decision"], "needs-review")
                self.assertIn("not-reached", doc["findings"][0]["reason"])
                rec.read_record(self.out / "findings.json")

    def test_short_engine_log_reports_tick_count_and_keeps_no_passing_verdict(self):
        self.game.log_ticks = 20
        doc = self.engine_gate(repo(self.tmp / "head", "BUG"))
        self.assertEqual(doc["decision"], "needs-review")
        self.assertIn("20 of 240 ticks", doc["findings"][0]["reason"])
        verdict = json.loads((self.out / f"verdicts/head/smoke/{SPEC_ID}.json").read_text())
        self.assertEqual(verdict["result"], "needs-review")

    def test_repeated_tick_numbers_do_not_cover_the_route(self):
        run = self.game.replay(Path("smoke.json"), repo(self.tmp / "head") / "game/platformer", self.tmp / "run", False)
        run["engineObservations"] = gv.observations(run["trace"], run["replaySha256"])
        for row in run["trace"]["rows"]:
            row["tick"] = 0
        self.assertIn("1 of 240 ticks", gv.engine_gap(SPEC, run, TICKS))
        self.assertEqual(gv.judge_run(SPEC, run, ticks=TICKS)["result"], "needs-review")

    def test_clean_bug_and_repaired_decisions_are_preserved_with_complete_replays(self):
        clean = repo(self.tmp / "clean")
        bug = repo(self.tmp / "bug", "BUG")
        self.assertEqual(self.engine_gate(clean)["decision"], "accept")
        self.assertEqual(self.engine_gate(bug)["decision"], "reject")
        repaired = self.gate(clean, base=bug, rule=rec.ENGINE_ONLY, visual=None)
        self.assertEqual(repaired["decision"], "accept")
        self.assertEqual(repaired["checks"][0]["comparison"], "REPAIRED")

    def test_record_examples_and_both_schema_readers(self):
        for name in ("findings-coverage.json", "verdict-coverage.json"):
            doc = json.loads((REPO / "contracts/examples" / name).read_text())
            if name.startswith("findings"):
                rec.check_record(doc)
                contracts.validate(doc, "findings")
            else:
                contracts.validate(doc, "verdict")
