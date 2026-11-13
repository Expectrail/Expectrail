"""expectrail.change_evidence: what a pair of runs, before and after a change, may claim."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from expectrail.change_evidence import (compare, load_record, mismatch, pair, repair_block, repair_claims,
                                       review_status)
from expectrail.contracts import ContractError, validate
from harness.run import REPO

GROUND, MOTION, VISIBLE = "player-stays-above-ground", "player-motion-on-smoke", "player-always-visible"
IDS = {"specs": {GROUND: "a" * 64}, "routeSha256": "b" * 64, "evaluator": "0.1.0", "observer": "engine"}
EXAMPLE = REPO / "contracts" / "examples" / "change-evidence.json"


def check(spec: str, result: str, kind: str = "regression", sha: str = "c" * 64) -> dict:
    return {"spec": spec, "kind": kind, "route": "smoke", "result": result, "verdictSha256": sha}


def status(base: list[dict], cand: list[dict], decision: str = "accept", primary=(GROUND,), cand_ids=IDS):
    """The status when every claim that went from FAIL to PASS held three times of three on each side
    (the gate's rule, #284; tests/test_review_repair_rule.py covers the runs themselves)."""
    rows = pair(base, cand, primary=set(primary), base_ids=IDS, candidate_ids=cand_ids)
    held = {(r["spec"], r["route"]): {"base": ["fail"] * 3, "head": ["pass"] * 3} for r in repair_claims(rows)}
    return rows, review_status(rows, {"decision": decision, "reasons": ["a check failed"]}, repair_block(rows, held))


class CompareTest(unittest.TestCase):
    def test_the_table(self):
        self.assertEqual(compare("fail", "pass"), "REPAIRED")
        self.assertEqual(compare("pass", "pass"), "PRESERVED")
        self.assertEqual(compare("pass", "fail"), "REGRESSION")
        self.assertEqual(compare("fail", "fail"), "UNRESOLVED")
        for before, after in (("needs-review", "pass"), ("fail", "needs-review"), (None, "pass"), ("fail", None)):
            self.assertEqual(compare(before, after), "INCONCLUSIVE")


class PolicyTest(unittest.TestCase):
    """The acceptance rows of the review policy, one test each."""

    def test_a_requested_failure_that_now_passes_is_a_demonstrated_repair(self):
        rows, (s, reasons) = status([check(GROUND, "fail"), check(MOTION, "pass", "gameplay")],
                                    [check(GROUND, "pass"), check(MOTION, "pass", "gameplay")])
        self.assertEqual((s, reasons), ("REPAIR DEMONSTRATED", []))
        self.assertEqual(rows[0]["spec"], GROUND)  # primary rows first
        self.assertEqual((rows[0]["comparison"], rows[1]["comparison"]), ("REPAIRED", "PRESERVED"))

    def test_passing_before_and_after_shows_no_repair_even_when_the_verifier_accepts(self):
        _rows, (s, reasons) = status([check(GROUND, "pass")], [check(GROUND, "pass")])
        self.assertEqual(s, "NO REPAIR DEMONSTRATED")
        self.assertIn("preserved", reasons[0])

    def test_an_optional_check_changing_never_qualifies(self):
        _rows, (s, _r) = status([check(GROUND, "pass"), check(MOTION, "fail", "gameplay")],
                                [check(GROUND, "pass"), check(MOTION, "pass", "gameplay")])
        self.assertEqual(s, "NO REPAIR DEMONSTRATED")

    def test_still_failing_is_unresolved_and_rejected(self):
        rows, (s, _r) = status([check(GROUND, "fail")], [check(GROUND, "fail")], decision="reject")
        self.assertEqual((rows[0]["comparison"], s), ("UNRESOLVED", "REJECTED"))

    def test_a_check_that_passed_and_now_fails_is_a_regression_and_rejected(self):
        rows, (s, reasons) = status([check(GROUND, "fail"), check(MOTION, "pass", "gameplay")],
                                    [check(GROUND, "pass"), check(MOTION, "fail", "gameplay")])
        self.assertEqual([r["comparison"] for r in rows], ["REPAIRED", "REGRESSION"])
        self.assertEqual(s, "REJECTED")  # even if a verifier somehow accepted
        self.assertIn(MOTION, reasons[0])

    def test_a_missing_observation_is_inconclusive_never_a_pass_or_a_failure(self):
        for before, after in (("needs-review", "pass"), ("fail", "needs-review")):
            rows, (s, _r) = status([check(GROUND, before)], [check(GROUND, after)])
            self.assertEqual((rows[0]["comparison"], s), ("INCONCLUSIVE", "INCONCLUSIVE"))

    def test_arms_judged_differently_are_not_compared_and_the_difference_is_named(self):
        other = dict(IDS, routeSha256="d" * 64, observer="SAM 3.1")
        rows, (s, reasons) = status([check(GROUND, "fail")], [check(GROUND, "pass")], cand_ids=other)
        self.assertEqual(s, "INCONCLUSIVE")
        self.assertEqual(rows[0]["mismatch"], ["observer", "routeSha256"])
        self.assertIn("observer, routeSha256", reasons[0])
        self.assertEqual(mismatch(IDS, IDS), [])

    def test_a_requested_claim_neither_arm_judged_is_a_row_and_inconclusive(self):
        rows, (s, _r) = status([check(GROUND, "fail")], [check(GROUND, "pass")], primary=(GROUND, VISIBLE))
        visible = [r for r in rows if r["spec"] == VISIBLE][0]
        self.assertEqual((visible["before"], visible["after"], visible["route"]), (None, None, "smoke"))
        self.assertEqual(s, "INCONCLUSIVE")

    def test_the_verifier_s_needs_review_blocks_a_repair_claim(self):
        _rows, (s, reasons) = status([check(GROUND, "fail")], [check(GROUND, "pass")], decision="needs-review")
        self.assertEqual(s, "INCONCLUSIVE")
        self.assertIn("needs-review", reasons[0])

    def test_nothing_requested_was_judged(self):
        _rows, (s, _r) = status([check(MOTION, "fail", "gameplay")], [check(MOTION, "pass", "gameplay")], primary=())
        self.assertEqual(s, "INCONCLUSIVE")

    def test_a_claim_judged_twice_in_one_arm_is_refused(self):
        with self.assertRaises(ValueError):
            pair([check(GROUND, "fail"), check(GROUND, "pass")], [check(GROUND, "pass")], primary={GROUND},
                 base_ids=IDS, candidate_ids=IDS)

    def test_a_missing_verdict_has_no_digest_not_a_zero_one(self):
        rows, _s = status([check(GROUND, "needs-review", sha="0" * 64)], [check(GROUND, "pass")])
        self.assertEqual(rows[0]["evidence"], {"before": None, "after": "c" * 64})


class RecordTest(unittest.TestCase):
    def write(self, text: str) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "change-evidence.json"
        path.write_text(text, encoding="utf-8")
        return path

    def test_the_example_is_a_real_sample_review_and_loads(self):
        doc = load_record(EXAMPLE)
        self.assertEqual((doc["status"], doc["evidenceLabel"], doc["mode"]), ("REPAIR DEMONSTRATED", "SAMPLE", "sample"))
        self.assertEqual(doc["candidate"]["origin"], "fixture")

    def test_duplicate_keys_are_refused(self):
        text = EXAMPLE.read_text(encoding="utf-8").replace('"mode": "sample",', '"mode": "sample", "mode": "live",', 1)
        with self.assertRaises(ContractError):
            load_record(self.write(text))

    def test_another_version_is_refused(self):
        doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        doc["format"] = "expectrail.change-evidence/v1"
        with self.assertRaises(ContractError):
            load_record(self.write(json.dumps(doc)))

    def test_a_claim_listed_twice_is_refused(self):
        doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        doc["rows"].append(doc["rows"][0])
        with self.assertRaises(ContractError):
            load_record(self.write(json.dumps(doc)))

    def test_an_all_zero_digest_never_stands_in_for_an_artifact(self):
        doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        doc["rows"][0]["evidence"]["before"] = "0" * 64
        with self.assertRaises(ContractError):
            validate(doc)

    def test_unknown_fields_and_frames_outside_assets_are_refused(self):
        doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        with self.assertRaises(ContractError):
            validate(dict(doc, approvedForRelease=True))
        doc["arms"]["base"] = {"provenance": "harness", "patchesSha256": ["a" * 64], "replaySha256": None,
                               "observationBackend": "engine",
                               "frame": {"path": "/home/someone/frame.png", "frame": 8, "sha256": "a" * 64}}
        with self.assertRaises(ContractError):
            validate(doc)


if __name__ == "__main__":
    unittest.main()
