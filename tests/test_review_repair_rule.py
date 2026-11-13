"""The review (agents.review_change) judges a repair by the gate's rule (issue #284).

A requested claim that went from FAIL to PASS is replayed twice more on each side, and the repair
counts only when it failed on the base and passed on the candidate three times of three:
expectrail.gate.record.row_counts, the same function the gate uses. The record carries the runs in a
``repair`` block of the gate's shape, and the reader recomputes it.
"""
from __future__ import annotations

import itertools
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents.review_change import EXIT, review
from expectrail import change_evidence as ce
from expectrail.change_evidence import load_record, pair, review_status
from expectrail.contracts import ContractError
from expectrail.gate import record as gate
from harness.run import REPO
from tests.test_agents import _held_out_dir, _request, _walk_trace
from tests.test_review_change import FIX, FIXTURES, SEED, _fake_harness

GROUND, MOTION = "player-stays-above-ground", "player-motion-on-smoke"
IDS = {"specs": {GROUND: "a" * 64}, "routeSha256": "b" * 64, "evaluator": "0.1.0", "observer": "engine"}
EXAMPLE = REPO / "contracts" / "examples" / "change-evidence.json"
ACCEPT = {"decision": "accept", "reasons": []}


def check(spec: str, result: str, kind: str = "regression") -> dict:
    return {"spec": spec, "kind": kind, "route": "smoke", "result": result, "verdictSha256": "c" * 64}


def rows_repaired() -> list[dict]:
    return pair([check(GROUND, "fail"), check(MOTION, "pass", "gameplay")],
                [check(GROUND, "pass"), check(MOTION, "pass", "gameplay")],
                primary={GROUND}, base_ids=IDS, candidate_ids=IDS)


def runs(base: list, head: list) -> dict:
    return {(GROUND, "smoke"): {"base": base, "head": head}}


class SharedRuleTest(unittest.TestCase):
    """The review and the gate count a demonstration the same way, on every combination of runs."""

    def test_every_combination_of_three_runs_is_judged_as_the_gate_judges_it(self):
        rows = rows_repaired()
        outcomes = ("pass", "fail", "needs-review", None)
        for rest_b in itertools.product(outcomes, repeat=2):
            for rest_h in itertools.product(outcomes, repeat=2):
                base, head = ["fail", *rest_b], ["pass", *rest_h]
                block = ce.repair_block(rows, runs(base, head))
                gate_says = gate.row_counts({"base": base, "head": head})
                status, reasons = review_status(rows, ACCEPT, block)
                self.assertEqual(status == "REPAIR DEMONSTRATED", gate_says, (base, head))
                self.assertEqual(block["demonstrated"], int(gate_says))
                if not gate_says:
                    self.assertEqual(status, "NO REPAIR DEMONSTRATED")
                    self.assertTrue(reasons[0].startswith(f"{gate.NOT_DEMONSTRATED}: "), reasons)

    def test_the_constants_are_the_gate_s(self):
        self.assertIs(ce.REPAIR_RUNS, gate.REPAIR_RUNS)
        self.assertIs(ce.NOT_DEMONSTRATED, gate.NOT_DEMONSTRATED)

    def test_three_of_three_is_a_demonstrated_repair(self):
        rows = rows_repaired()
        block = ce.repair_block(rows, runs(["fail"] * 3, ["pass"] * 3))
        self.assertEqual(review_status(rows, ACCEPT, block), ("REPAIR DEMONSTRATED", []))
        self.assertEqual(block, {"runs": 3, "demonstrated": 1, "rows": [
            {"spec": GROUND, "route": "smoke", "base": ["fail"] * 3, "head": ["pass"] * 3, "counts": True}]})

    def test_one_run_a_side_is_not_enough(self):
        rows = rows_repaired()
        for block in (None, ce.repair_block(rows, {})):
            status, reasons = review_status(rows, ACCEPT, block)
            self.assertEqual(status, "NO REPAIR DEMONSTRATED")
            self.assertTrue(reasons[0].startswith("repair-not-demonstrated: "), reasons)
            self.assertIn("3 times of 3", reasons[0])

    def test_a_flaky_base_is_not_a_demonstration_and_the_runs_are_named(self):
        rows = rows_repaired()
        status, reasons = review_status(rows, ACCEPT, ce.repair_block(rows, runs(["fail", "pass", "fail"], ["pass"] * 3)))
        self.assertEqual(status, "NO REPAIR DEMONSTRATED")
        self.assertIn("before fail, pass, fail; after pass, pass, pass", reasons[0])

    def test_a_flaky_candidate_is_not_a_demonstration(self):
        rows = rows_repaired()
        status, _r = review_status(rows, ACCEPT, ce.repair_block(rows, runs(["fail"] * 3, ["pass", "fail", "pass"])))
        self.assertEqual(status, "NO REPAIR DEMONSTRATED")

    def test_a_written_counts_is_never_trusted(self):
        rows = rows_repaired()
        forged = {"runs": 3, "demonstrated": 1, "rows": [
            {"spec": GROUND, "route": "smoke", "base": ["fail"], "head": ["pass"], "counts": True}]}
        self.assertEqual(review_status(rows, ACCEPT, forged)[0], "NO REPAIR DEMONSTRATED")

    def test_runs_for_a_claim_that_was_not_repaired_never_count(self):
        # MOTION is optional and was passing: three good-looking runs for it demonstrate nothing.
        rows = rows_repaired()
        other = {"runs": 3, "demonstrated": 1, "rows": [
            {"spec": MOTION, "route": "smoke", "base": ["fail"] * 3, "head": ["pass"] * 3, "counts": True}]}
        self.assertEqual(ce.demonstrations(rows, other), [])
        self.assertEqual(review_status(rows, ACCEPT, other)[0], "NO REPAIR DEMONSTRATED")

    def test_a_reject_and_an_unclear_claim_come_before_the_repair_rule(self):
        rows = rows_repaired()
        good = ce.repair_block(rows, runs(["fail"] * 3, ["pass"] * 3))
        self.assertEqual(review_status(rows, {"decision": "reject", "reasons": ["x"]}, good)[0], "REJECTED")
        self.assertEqual(review_status(rows, {"decision": "needs-review", "reasons": []}, good)[0], "INCONCLUSIVE")


class ReaderTest(unittest.TestCase):
    def write(self, doc: dict) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "change-evidence.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def example(self) -> dict:
        return json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def test_the_example_carries_three_runs_a_side(self):
        doc = load_record(EXAMPLE)
        self.assertFalse(ce.pre_repair_rule(doc))
        self.assertEqual(doc["repair"]["demonstrated"], 1)
        self.assertEqual(doc["repair"]["rows"][0]["base"], ["fail", "fail", "fail"])

    def test_counts_that_do_not_follow_from_the_runs_are_refused(self):
        doc = self.example()
        doc["repair"]["rows"][0]["base"] = ["fail", "pass", "fail"]  # counts still says true
        with self.assertRaisesRegex(ContractError, "does not follow from its runs"):
            load_record(self.write(doc))

    def test_a_repair_status_with_no_demonstration_is_refused(self):
        doc = self.example()
        row = doc["repair"]["rows"][0]
        row["base"], row["counts"], doc["repair"]["demonstrated"] = ["fail"], False, 0
        with self.assertRaisesRegex(ContractError, "REPAIR DEMONSTRATED"):
            load_record(self.write(doc))

    def test_a_wrong_count_of_demonstrations_is_refused(self):
        doc = self.example()
        doc["repair"]["demonstrated"] = 2
        with self.assertRaisesRegex(ContractError, "count of demonstrations"):
            load_record(self.write(doc))

    def test_repair_rows_for_other_claims_are_refused(self):
        doc = self.example()
        doc["repair"]["rows"][0]["spec"] = MOTION
        with self.assertRaisesRegex(ContractError, "not exactly the requested claims"):
            load_record(self.write(doc))
        doc = self.example()
        doc["repair"]["rows"] = []
        doc["repair"]["demonstrated"] = 0
        doc["status"] = "NO REPAIR DEMONSTRATED"
        with self.assertRaisesRegex(ContractError, "not exactly the requested claims"):
            load_record(self.write(doc))

    def test_a_first_run_that_is_not_the_row_s_own_result_is_refused(self):
        doc = self.example()
        doc["repair"]["rows"][0]["head"] = ["fail", "pass", "pass"]
        doc["repair"]["rows"][0]["counts"], doc["repair"]["demonstrated"] = False, 0
        doc["status"] = "NO REPAIR DEMONSTRATED"
        with self.assertRaisesRegex(ContractError, "first run on each side"):
            load_record(self.write(doc))

    def test_another_number_of_runs_is_refused(self):
        doc = self.example()
        doc["repair"]["runs"] = 1
        with self.assertRaises(ContractError):
            load_record(self.write(doc))

    def test_a_record_from_before_the_rule_is_read_as_written_and_says_so(self):
        doc = self.example()
        del doc["repair"]
        doc["stages"] = [s for s in doc["stages"] if s["stage"] != "repeat"]
        loaded = load_record(self.write(doc))
        self.assertTrue(ce.pre_repair_rule(loaded))
        for kept in sorted((REPO / "docs" / "review").glob("*/change-evidence.json")):
            self.assertTrue(ce.pre_repair_rule(load_record(kept)), kept)


class ReviewTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"EXPECTRAIL_HELDOUT_DIR": "", "EXPECTRAIL_OBS_PROVIDER": ""})
        env.start()
        self.addCleanup(env.stop)

    def sample(self, base_obs: str, obs: str) -> dict:
        return review(_request(), FIX, self.tmp / "review", mode="sample",
                      base_observations=FIXTURES / base_obs, observations=FIXTURES / obs)

    def live(self, harness, heldout: bool = True) -> dict:
        env = {"EXPECTRAIL_HELDOUT_DIR": str(_held_out_dir(self.tmp))} if heldout else {}
        with (mock.patch.dict(os.environ, env),
              mock.patch("agents.verifier.harness_run", side_effect=harness),
              mock.patch("harness.run.find_godot", return_value=Path("/usr/bin/true"))):
            return review(_request(), FIX, self.tmp / "review", mode="live")

    def stage(self, rec: dict, name: str) -> dict:
        return [s for s in rec["stages"] if s["stage"] == name][0]

    def test_a_sample_repair_is_replayed_three_times_and_recorded(self):
        rec = self.sample("obs-fallthrough.json", "obs-fixed.json")
        self.assertEqual(rec["status"], "REPAIR DEMONSTRATED")
        self.assertEqual(self.stage(rec, "repeat")["status"], "completed")
        self.assertEqual(rec["repair"]["rows"], [{"spec": GROUND, "route": "smoke", "base": ["fail"] * 3,
                                                  "head": ["pass"] * 3, "counts": True}])
        load_record(self.tmp / "review" / "change-evidence.json")  # the reader agrees with the writer

    def test_nothing_is_replayed_again_when_no_repair_can_be_claimed(self):
        from agents import verifier

        with mock.patch("agents.verifier.public_route_checks", wraps=verifier.public_route_checks) as calls:
            rec = self.sample("obs-fixed.json", "obs-fixed.json")
        self.assertEqual(calls.call_count, 1)  # the base's first run, nothing more
        self.assertEqual(rec["status"], "NO REPAIR DEMONSTRATED")
        self.assertEqual(self.stage(rec, "repeat")["status"], "skipped")
        self.assertEqual(rec["repair"], {"runs": 3, "demonstrated": 0, "rows": []})
        self.assertTrue(rec["reasons"][0].startswith("repair-not-demonstrated: "))

    def test_live_with_the_private_routes_replays_both_sides_twice_more(self):
        seen = []

        def harness(route, out, patches=None, **kw):
            seen.append((Path(out).parent.name, [Path(p).name for p in patches or []]))
            return _fake_harness(route, out, patches=patches, **kw)

        rec = self.live(harness)
        self.assertEqual(rec["status"], "REPAIR DEMONSTRATED", rec["reasons"])
        self.assertEqual(EXIT[rec["status"]], 0)
        for n in (2, 3):
            self.assertIn((f"base-run{n}", [SEED.name]), seen)
            self.assertIn((f"candidate-run{n}", [SEED.name, FIX.name]), seen)
        self.assertEqual(rec["repair"]["demonstrated"], 1)

    def test_a_base_that_passes_on_a_later_run_is_not_a_demonstration(self):
        def harness(route, out, patches=None, **kw):
            if Path(out).parent.name == "base-run3":  # the seed alone walks this time: a flaky failure
                return _fake_harness(route, out, patches=[SEED, FIX], **kw)
            return _fake_harness(route, out, patches=patches, **kw)

        rec = self.live(harness)
        self.assertEqual(rec["status"], "NO REPAIR DEMONSTRATED")
        self.assertEqual(EXIT[rec["status"]], 1)
        self.assertEqual(rec["repair"]["rows"][0]["base"], ["fail", "fail", "pass"])
        self.assertFalse(rec["repair"]["rows"][0]["counts"])
        self.assertTrue(rec["reasons"][0].startswith("repair-not-demonstrated: "), rec["reasons"])
        load_record(self.tmp / "review" / "change-evidence.json")

    def test_a_crash_while_replaying_again_is_inconclusive_never_a_repair(self):
        def harness(route, out, patches=None, **kw):
            if Path(out).parent.name == "candidate-run2":
                raise TimeoutError("replay timed out")
            return _fake_harness(route, out, patches=patches, **kw)

        rec = self.live(harness)
        self.assertEqual(rec["status"], "INCONCLUSIVE")
        self.assertEqual(self.stage(rec, "repeat")["status"], "failed")
        self.assertIn("could not be replayed 3 times", rec["reasons"][0])
        self.assertEqual(rec["diagnostics"][-1]["stage"], "repeat")
        self.assertTrue((self.tmp / "review" / "repeat-error.txt").is_file())
        self.assertEqual(rec["repair"]["demonstrated"], 0)
        load_record(self.tmp / "review" / "change-evidence.json")

    def test_live_without_the_private_routes_replays_nothing_more_and_stays_inconclusive(self):
        seen = []

        def harness(route, out, patches=None, **kw):
            seen.append(Path(out).parent.name)
            return _fake_harness(route, out, patches=patches, **kw)

        rec = self.live(harness, heldout=False)
        self.assertEqual(rec["status"], "INCONCLUSIVE")
        self.assertEqual(EXIT[rec["status"]], 2)
        self.assertFalse([name for name in seen if "-run" in name], seen)
        self.assertEqual(self.stage(rec, "repeat")["status"], "skipped")
        self.assertIn("PRIVATE_SUITE_UNAVAILABLE", [d["code"] for d in rec["diagnostics"]])
        self.assertEqual(len(rec["reasons"]), 1)
        self.assertTrue(rec["reasons"][0].startswith("live mode needs fresh replays"), rec["reasons"])


class PageTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def page(self, doc: dict) -> str:
        from agents.review_html import render

        path = self.tmp / "change-evidence.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return render(path, self.tmp / "out").read_text(encoding="utf-8")

    def test_the_page_says_how_many_times_the_repair_held(self):
        text = self.page(json.loads(EXAMPLE.read_text(encoding="utf-8")))
        self.assertIn("3 times of 3", text)
        self.assertIn(f"<code>{GROUND}</code> before fail, fail, fail; after pass, pass, pass: counts", text)

    def test_a_record_from_before_the_rule_says_it_was_judged_once(self):
        doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        del doc["repair"]
        text = self.page(doc)
        self.assertIn("judged once on each side", text)


if __name__ == "__main__":
    unittest.main()
