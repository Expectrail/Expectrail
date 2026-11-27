"""Issue #762: the hand-written reproduction checks, their recorded rows and the published table.

No engine here: the rows were recorded by ``tools/reproduction_ceiling.py`` on Godot 4.7.2. These tests hold
the pure parts (the clearance agrees with the evaluator's comparators, the compound and keep rules), that every
hand answer goes through the generator's own parser and offer, that the rows were made from the committed
answers, reports and patches, and that the measurement shows exactly what the rows say.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import tempfile
import unittest
from pathlib import Path

from expectrail.jit import intent
from expectrail.jit.probes import jit_library
from expectrail.trace.evaluator import COMPARATORS
from tools import reproduction_ceiling as rc

REPO = Path(__file__).resolve().parents[1]
ROWS = REPO / "bench/jit/ceiling/rows.json"
MEASUREMENT = REPO / "docs/measurements/762-reproduction-ceiling-hand-checks.md"
START, END = "<!-- ceiling-table:start -->", "<!-- ceiling-table:end -->"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Margin(unittest.TestCase):
    def test_positive_exactly_when_the_evaluator_passes(self):
        values = [-3.0, -0.5, 0.0, 0.5, 2.0, 7.25]
        for cmp, (left, right, tol) in itertools.product(sorted(COMPARATORS),
                                                         itertools.product(values, values, [0.0, 0.5, 2.0])):
            m = rc.margin({"comparator": cmp, "toleranceAbs": tol}, left, right)
            holds = COMPARATORS[cmp](right, left, tol)
            if m > 0:
                self.assertTrue(holds, (cmp, left, right, tol, m))
            if m < 0:
                self.assertFalse(holds, (cmp, left, right, tol, m))

    def test_no_reading_has_no_margin(self):
        self.assertIsNone(rc.margin({"comparator": "lt", "toleranceAbs": 1}, None, 2.0))

    def test_unknown_comparator_is_refused(self):
        with self.assertRaises(ValueError):
            rc.margin({"comparator": "ne", "toleranceAbs": 0}, 1.0, 2.0)


class Rules(unittest.TestCase):
    P, F = ["pass"] * 3, ["fail"] * 3

    def arms(self, clean, defect, control, harmless):
        return {"clean": {"runs": clean}, "defect": {"runs": defect}, "control": {"runs": control},
                "harmless": {"runs": harmless}}

    def test_compound_fails_when_any_part_fails(self):
        self.assertEqual(rc.compound_run(["pass", "fail"]), "fail")
        self.assertEqual(rc.compound_run(["pass", "pass"]), "pass")
        self.assertEqual(rc.compound_run(["pass", "insufficient_observation"]), "insufficient_observation")
        self.assertEqual(rc.compound_run([]), "insufficient_observation")

    def test_kept_only_with_all_four(self):
        self.assertTrue(rc.verdict(self.arms(self.P, self.F, self.F, self.P))["reproduces"])

    def test_passing_the_control_drops_it(self):
        v = rc.verdict(self.arms(self.P, self.F, self.P, self.P))
        self.assertFalse(v["reproduces"])
        self.assertIn("passes the do-nothing control", v["reasons"])

    def test_an_indeterminate_control_is_named_and_does_not_drop(self):
        v = rc.verdict(self.arms(self.P, self.F, ["fail", "insufficient_observation", "fail"], self.P))
        self.assertEqual(v["control"], "indeterminate")
        self.assertTrue(v["reproduces"])

    def test_not_failing_the_defect_or_a_harmless_reject_drops_it(self):
        self.assertFalse(rc.verdict(self.arms(self.P, self.P, self.F, self.P))["reproduces"])
        v = rc.verdict(self.arms(self.P, self.F, self.F, self.F))
        self.assertEqual(v["harmless"], "false-rejection")
        self.assertFalse(v["reproduces"])

    def test_a_held_out_work_folder_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            rc.measure(Path(tmp) / "fresh-anything")


class HandAnswers(unittest.TestCase):
    def test_every_answer_goes_through_the_generators_parser_and_offer(self):
        profile = json.loads((REPO / "discovery/platformer.profile.json").read_text())
        library = jit_library(profile["actions"])
        for defect in rc.DEFECTS:
            for name in rc.ROUND_FILES:
                path = rc.CEILING / defect / name
                if not path.exists():
                    continue
                with tempfile.TemporaryDirectory() as tmp:
                    doc = rc.proposal_for(defect, path, Path(tmp), profile, library)
                self.assertIsNone(doc["error"], (defect, name))
                self.assertEqual(doc["candidate"], intent.WITHHELD)
                self.assertIsNone(doc["patchSha256"])
                self.assertEqual(doc["offer"], rc.OFFER)
                self.assertEqual(doc["diagnostics"], [], (defect, name))
                answer = json.loads(path.read_text())
                self.assertEqual(len(doc["candidates"]), len(answer["candidates"]))
                self.assertTrue(answer["obligation"].strip())

    def test_round_one_exists_for_each_defect(self):
        for defect in rc.DEFECTS:
            self.assertTrue((rc.CEILING / defect / "round1.json").exists(), defect)


class RecordedRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(ROWS.read_text())

    def test_rows_were_made_from_the_committed_inputs(self):
        self.assertEqual(self.doc["format"], rc.FORMAT)
        self.assertEqual(self.doc["harmlessPatchSha256"], _sha(rc.HARMLESS))
        self.assertEqual([d["id"] for d in self.doc["defects"]], list(rc.DEFECTS))
        for d in self.doc["defects"]:
            self.assertEqual(d["reportSha256"], _sha(REPO / d["report"]))
            self.assertEqual(d["patchSha256"], _sha(REPO / d["patch"]))
            rounds = [r["round"] for r in d["rounds"]]
            self.assertEqual(rounds, [n for n in (1, 2) if (rc.CEILING / d["id"] / f"round{n}.json").exists()])
            for r in d["rounds"]:
                self.assertEqual(r["answerSha256"], _sha(rc.CEILING / d["id"] / f"round{r['round']}.json"))

    def test_every_replay_group_repeated_byte_for_byte(self):
        for name, runs in self.doc["replays"].items():
            self.assertEqual(len(runs), 3, name)
            self.assertEqual(len({r.get("trace") for r in runs}), 1, name)
            self.assertFalse(any("error" in r for r in runs), name)

    def test_verdicts_follow_from_the_runs(self):
        for d in self.doc["defects"]:
            for r in d["rounds"]:
                for c in r["checks"]:
                    self.assertEqual({k: c[k] for k in ("reproduces", "control", "harmless", "reasons")},
                                     rc.verdict(c["arms"]), c["specId"])
                if "compound" in r:
                    k = r["compound"]
                    runs = {arm: [rc.compound_run([c["arms"][arm]["runs"][i] for c in r["checks"]])
                                  for i in range(3)] for arm in rc.ARMS}
                    self.assertEqual({arm: k["arms"][arm]["runs"] for arm in rc.ARMS}, runs)

    def test_the_measurement_shows_the_rows(self):
        text = MEASUREMENT.read_text()
        self.assertIn(START, text)
        table = text.split(START, 1)[1].split(END, 1)[0].strip()
        self.assertEqual(table, rc.render(self.doc))


if __name__ == "__main__":
    unittest.main()
