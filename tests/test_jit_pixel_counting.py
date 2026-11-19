"""#271's six rules applied to pixel checks (#286), offline.

Pixel checks are in a run record's ``pixelChecks``, not in ``proposed``/``validity``, so until now the
six-rule assessor never looked at them and every screen-only check was advisory without a reason.
``assess.pixel_counting`` recomputes the six rules from a pixel row's own runs. It is not an input to
``decide``: these rows are reported, never counted by the gate (tested below).

The records are the committed hand-written stand-ins (bench/jit/stand-in/) and copies of them changed
one field at a time. No replay, no observer, no model."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from expectrail.contracts import ContractError
from expectrail.jit import assess

REPO = Path(__file__).resolve().parents[1]
STAND_IN = REPO / "bench/jit/stand-in"
ENEMY = STAND_IN / "enemy-walks-backwards-faces-motion/jit-run.json"
BULLET = STAND_IN / "bullet-behind-scenery-visible/jit-run.json"
ENEMY_REPORT = (REPO / "bench/jit/public/enemy-walks-backwards/report.txt").read_text()
BULLET_REPORT = (REPO / "bench/jit/public/bullet-behind-scenery/report.txt").read_text()


def load(path):
    return json.loads(path.read_text())


def passing(doc=None):
    """The enemy stand-in with the gaps a real counting run would not have: provenance, and a candidate
    that repairs (passes 3 of 3), so the base build is a near miss it kills."""
    doc = copy.deepcopy(doc or load(ENEMY))
    doc["provenance"] = {"generatorVersion": "test", "modelVersion": "test-model-1", "assessmentDiffClaims": []}
    doc["inputs"]["model"] = "test-model"
    doc["inputs"]["promptSha256"] = "a" * 64
    for row in doc["pixelChecks"]:
        row["candidate"] = ["pass"] * 3
        row["outcome"] = "no-catch"
    return doc


def first(rows):
    return rows[0]


class PixelRelevance(unittest.TestCase):
    def test_object_and_predicate_must_both_be_named(self):
        check = load(ENEMY)["pixelChecks"][0]["check"]
        self.assertTrue(assess.pixel_relevant(check, ENEMY_REPORT))
        for report in ("The robot falls far too slowly.",               # neither
                       "One of the enemies is missing.",                # the object, not facing
                       "The robot faces backwards when it walks."):     # facing, not the enemy
            self.assertFalse(assess.pixel_relevant(check, report), report)

    def test_the_bullet_report_binds_visible_on_the_bullet(self):
        check = load(BULLET)["pixelChecks"][0]["check"]
        self.assertTrue(assess.pixel_relevant(check, BULLET_REPORT))
        self.assertFalse(assess.pixel_relevant(check, ENEMY_REPORT))

    def test_the_checks_own_statement_cannot_make_it_relevant(self):
        # The statement is model text. Only the bound object and the predicate's type are read.
        check = copy.deepcopy(load(BULLET)["pixelChecks"][0]["check"])
        check["statement"] = ENEMY_REPORT
        self.assertFalse(assess.pixel_relevant(check, "The enemy walks too fast."))

    def test_an_unbound_predicate_or_object_stays_advisory(self):
        check = copy.deepcopy(load(ENEMY)["pixelChecks"][0]["check"])
        check["predicate"] = {"type": "reaches"}
        self.assertFalse(assess.pixel_relevant(check, ENEMY_REPORT + " The enemy reaches the robot."))
        check = copy.deepcopy(load(ENEMY)["pixelChecks"][0]["check"])
        check["object"] = "ground"
        self.assertFalse(assess.pixel_relevant(check, ENEMY_REPORT + " The ground faces backwards."))


class PixelSixRules(unittest.TestCase):
    def rules(self, doc, report=ENEMY_REPORT, trusted=True):
        return first(assess.pixel_counting(doc, report, trusted=trusted))

    def test_all_six_hold_only_on_a_complete_trusted_record(self):
        row = self.rules(passing())
        self.assertEqual(row["rules"], [True] * 6, row["reasons"])
        self.assertTrue(row["counting"])
        self.assertEqual(row["kind"], "pixel")
        self.assertEqual(row["killed"], ["base"])
        self.assertEqual(row["routeSha256"], [next(p["routeSha256"] for p in passing()["probes"]
                                                   if p["id"] == row["probeIds"][0])])

    def test_rule_1_withheld_complete_and_three_of_three(self):
        for change in ("shown", "incomplete", "partial-bug", "partial-clean", "two-runs"):
            doc = passing()
            px = doc["pixelChecks"][0]
            if change == "shown":
                doc["settings"]["candidate"] = "shown"
            elif change == "incomplete":
                doc["status"] = "error"
            elif change == "partial-bug":
                px["bug"][1] = "pass"
            elif change == "partial-clean":
                px["clean"][2] = "needs-review"
            else:
                px["bug"] = ["fail", "fail"]
            row = self.rules(doc)
            self.assertFalse(row["rules"][0], change)
            self.assertFalse(row["counting"], change)

    def test_rule_2_a_candidate_that_still_fails_kills_no_near_miss(self):
        # The stand-in's candidate is the no-fix patch: it fails like the base, so base and candidate
        # are not told apart and nothing independent was killed.
        doc = passing()
        doc["pixelChecks"][0]["candidate"] = ["fail"] * 3
        row = self.rules(doc)
        self.assertFalse(row["rules"][1])
        self.assertEqual(row["killed"], [])
        self.assertFalse(row["counting"])

    def test_rule_3_unrelated_report(self):
        row = self.rules(passing(), report="The robot falls far too slowly.")
        self.assertFalse(row["rules"][2])
        self.assertFalse(row["counting"])

    def test_rule_4_every_run_judged_one_setting_and_a_stable_candidate(self):
        for change in ("flaky", "unjudged", "no-setting"):
            doc = passing()
            px = doc["pixelChecks"][0]
            if change == "flaky":
                px["candidate"] = ["pass", "fail", "pass"]
            elif change == "unjudged":
                px["candidate"] = ["pass", "needs-review", "pass"]
            else:
                px["setting"] = None
            row = self.rules(doc)
            self.assertFalse(row["rules"][3], change)
            self.assertFalse(row["counting"], change)

    def test_rule_5_only_the_caller_supplies_trust(self):
        doc = passing()
        doc["trusted"] = True                         # fields in the record are never read as trust
        doc["pixelChecks"][0]["trusted"] = True
        doc["provenance"]["trusted"] = True
        row = self.rules(doc, trusted=False)
        self.assertFalse(row["rules"][4])
        self.assertFalse(row["counting"])
        self.assertTrue(self.rules(passing(), trusted=True)["rules"][4])

    def test_rule_6_provenance(self):
        for change in ("model-version", "prompt", "probe", "generator"):
            doc = passing()
            if change == "model-version":
                doc["provenance"]["modelVersion"] = None
            elif change == "prompt":
                doc["inputs"]["promptSha256"] = None
            elif change == "generator":
                del doc["provenance"]["generatorVersion"]
            else:
                doc["probes"] = [p for p in doc["probes"] if p["id"] != doc["pixelChecks"][0]["check"]["probe"]]
            row = self.rules(doc)
            self.assertFalse(row["rules"][5], change)
            self.assertFalse(row["counting"], change)

    def test_rows_are_read_from_the_runs_not_from_status_or_outcome(self):
        doc = passing()
        px = doc["pixelChecks"][0]
        px["bug"] = ["pass"] * 3
        px["status"] = "kept"
        px["outcome"] = "catch"
        row = self.rules(doc)
        self.assertFalse(row["counting"])
        self.assertEqual(row["base"], ["pass"] * 3)

    def test_a_check_that_is_not_a_pixel_check_is_refused(self):
        doc = passing()
        doc["pixelChecks"][0]["check"]["predicate"] = {"type": "glows"}
        with self.assertRaises(ContractError):
            assess.pixel_counting(doc, ENEMY_REPORT, trusted=True)

    def test_duplicate_ids_are_refused(self):
        doc = passing()
        doc["pixelChecks"][1]["check"]["id"] = doc["pixelChecks"][0]["check"]["id"]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            assess.pixel_counting(doc, ENEMY_REPORT, trusted=True)

    def test_no_pixel_checks_no_rows(self):
        doc = passing()
        doc["pixelChecks"] = []
        self.assertEqual(assess.pixel_counting(doc, ENEMY_REPORT, trusted=True), [])
        del doc["pixelChecks"]
        self.assertEqual(assess.pixel_counting(doc, ENEMY_REPORT, trusted=True), [])


class CommittedStandIns(unittest.TestCase):
    """What the six rules say about the two committed pixel stand-ins, untrusted as they are."""

    def test_enemy_faces_motion_meets_rules_1_3_4(self):
        rows = assess.pixel_counting(load(ENEMY), ENEMY_REPORT)
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(row["rules"], [True, False, True, True, False, False], row["specId"])
            self.assertFalse(row["counting"])

    def test_bullet_visible_was_not_judged_so_only_rule_3_holds(self):
        rows = assess.pixel_counting(load(BULLET), BULLET_REPORT)
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(row["rules"], [False, False, True, False, False, False], row["specId"])
            self.assertFalse(row["counting"])

    def test_the_published_page_is_what_the_records_give(self):
        from expectrail.jit import counting
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "page.md"
            summary = counting.pixel_bench(STAND_IN, out)
            self.assertEqual(out.read_text(), (REPO / "docs/measurements/271-pixel-counting.md").read_text())
        self.assertEqual(summary, {"records": 2, "checks": 6, "counting": 0, "advisory": 6})

    def test_the_audit_refuses_held_out_roots(self):
        from expectrail.jit import counting
        with self.assertRaisesRegex(ValueError, "public-only"):
            counting.pixel_bench(Path("bench/fresh-4"), Path("/dev/null"))


class NotADecisionInput(unittest.TestCase):
    def test_the_counting_envelope_still_carries_trace_rows_only(self):
        # pixel_counting is reported; counting.make (the only producer of the gate's evidence) does not
        # call it, so a pixel row can never reach decide through this change.
        text = (REPO / "expectrail/jit/counting.py").read_text()
        make = text[text.index("def make("):text.index("def read(")]
        self.assertNotIn("pixel", make)


if __name__ == "__main__":
    unittest.main()
