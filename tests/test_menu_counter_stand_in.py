"""The hand-written counter stand-in proposals for the two pause-menu counter defects (#285).

tools/menu_counter_stand_in.py writes them; `jit run --proposal` replayed them on the real engine on November
18 (bench/jit/stand-in/<defect>-menu-counter/README.md). These tests hold that the committed proposals are what
the tool writes, that a run reads them only under the setting they were made for, that they say no model wrote
them, that the reproduction score gives their records no result, and what the committed run records show.
They run no game.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail.contracts import load_strict
from expectrail.jit import intent, offer
from expectrail.jit.diff_map import withheld_map
from expectrail.repro import score
from tools import menu_counter_stand_in as stand_in

REPO = Path(__file__).resolve().parents[1]
MENU_IDS = ["hold-right-then-toggle-pause", "hold-left-then-toggle-pause", "reverse-then-toggle-pause"]
KEPT = {"hold-right-then-toggle-pause", "reverse-then-toggle-pause"}


def record(defect):
    return load_strict(stand_in.committed(defect).parent / "jit-run.json", "jit-run")


class TheProposals(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="menu-counter-stand-in-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def replay(self, defect, report=None, **kw):
        profile, text, probes = stand_in.library(defect)
        settings = {"offer": stand_in.OFFER, "candidate": intent.WITHHELD, **kw}
        return intent.from_proposal(stand_in.committed(defect), **settings)(
            text if report is None else report, "", withheld_map(probes), profile, probes)

    def test_the_committed_copies_are_what_the_tool_writes(self):
        for defect in stand_in.DEFECTS:
            with self.subTest(defect):
                stand_in.write(defect, self.tmp / defect)
                self.assertEqual((self.tmp / defect / intent.PROPOSAL_NAME).read_bytes(),
                                 stand_in.committed(defect).read_bytes())

    def test_they_say_no_model_wrote_them_and_carry_no_probe_of_their_own(self):
        for defect in stand_in.DEFECTS:
            doc = json.loads(stand_in.committed(defect).read_text(encoding="utf-8"))
            self.assertEqual(doc["model"], "hand-written-stand-in")
            self.assertIn(doc["model"], score.STAND_INS)
            self.assertIsNone(doc["promptSha256"])
            self.assertTrue(any("no model was called" in d for d in doc["diagnostics"]), doc["diagnostics"])
            self.assertEqual(doc["probes"], [])
            self.assertNotIn("pixelChecks", doc)

    def test_a_run_of_their_setting_reads_one_counter_check_on_each_menu_probe(self):
        for defect in stand_in.DEFECTS:
            got = self.replay(defect)
            self.assertEqual([c["applies"] for c in got["candidates"]],
                             [{"kind": "probes", "ids": [p]} for p in MENU_IDS])
            for c in got["candidates"]:
                self.assertEqual(c["spec"]["operation"], stand_in.COUNTER)
                self.assertEqual(c["spec"]["expectationRef"]["authority"], "model_prior")
                self.assertFalse(c["approved"])

    def test_they_are_bound_to_their_report_with_the_candidate_withheld(self):
        for defect in stand_in.DEFECTS:
            doc = json.loads(stand_in.committed(defect).read_text(encoding="utf-8"))
            self.assertIsNone(doc["patchSha256"])
            self.assertEqual(doc["candidate"], intent.WITHHELD)
            with self.assertRaisesRegex(intent.IntentUnavailable, "different report"):
                self.replay(defect, report="The jump is too short.")
        # Each defect's proposal is bound to its own report, so one cannot stand in for the other.
        other = stand_in.library("coin-counter-stuck")[1]
        with self.assertRaisesRegex(intent.IntentUnavailable, "different report"):
            self.replay("coin-counts-twice", report=other)

    def test_a_run_of_another_setting_refuses_them(self):
        for kw, why in (({"candidate": intent.SHOWN}, "PROPOSAL_MISMATCH: .*candidate"),
                        ({"offer": offer.EVIDENCE}, "PROPOSAL_MISMATCH: .*offer")):
            with self.subTest(**kw), self.assertRaisesRegex(intent.IntentUnavailable, why):
                self.replay("coin-counts-twice", **kw)

    def test_the_comparison_is_refused_where_the_setting_does_not_offer_the_counter(self):
        profile, _, probes = stand_in.library("coin-counts-twice")
        with self.assertRaisesRegex(intent.IntentUnavailable, "no contract survived"):
            intent.parse_answer(json.dumps(stand_in.answer(probes)), profile, {p["id"] for p in probes},
                                offer=offer.SIGNALS_REACH)

    def test_a_probe_list_without_a_menu_probe_gives_no_answer(self):
        profile, report, _ = stand_in.library("coin-counts-twice")
        with self.assertRaisesRegex(ValueError, "no menu probe"):
            stand_in.answer(offer.library(profile["actions"], offer.EVIDENCE, report))

    def test_only_the_two_counter_defects_have_one(self):
        with self.assertRaisesRegex(ValueError, "no counter stand-in"):
            stand_in.write("coin-stays", self.tmp)


class TheRecordedRuns(unittest.TestCase):
    """What `jit run --proposal` recorded on Godot 4.7.2 here, on November 18. The keep rule decided."""

    def test_they_are_menu_runs_with_the_candidate_withheld_and_no_model(self):
        for defect in stand_in.DEFECTS:
            doc = record(defect)
            self.assertEqual(doc["status"], "complete")
            self.assertEqual((doc["settings"]["offer"], doc["settings"]["candidate"], doc["settings"]["reps"]),
                             (offer.MENU, intent.WITHHELD, 3))
            self.assertEqual(doc["inputs"]["model"], "hand-written-stand-in")
            self.assertEqual({p["source"] for p in doc["probes"]}, {"menu"})
            self.assertEqual(doc["spend"]["samImages"], 0)

    def test_the_keep_rule_kept_the_two_walks_that_pick_up_coins_and_dropped_the_one_that_picks_up_none(self):
        for defect in stand_in.DEFECTS:
            doc = record(defect)
            kept = {v["specId"].removeprefix("jit-menu-counter-") for v in doc["validity"] if v["valid"]}
            self.assertEqual(kept, KEPT, defect)
            for v in doc["validity"]:
                self.assertEqual(v["reference"], ["pass"] * 3, v["specId"])
                if not v["valid"]:
                    self.assertEqual(v["reasons"], ["killed no near-miss variant"])

    def test_each_kept_check_fails_the_bug_build_three_of_three_and_the_no_fix_candidate_too(self):
        for defect in stand_in.DEFECTS:
            doc = record(defect)
            self.assertEqual(len(doc["catches"]), 2)
            for c in doc["catches"]:
                self.assertEqual((c["base"], c["candidate"], c["strength"]), (["fail"] * 3, ["fail"] * 3, "strong"))

    def test_the_score_gives_a_stand_in_record_no_result(self):
        defects = {d["id"]: d for d in json.loads((REPO / "bench/jit/public/defects.json").read_text())["defects"]}
        for defect in stand_in.DEFECTS:
            got, why = score._read(defects[defect], stand_in.committed(defect).parent / "jit-run.json", REPO,
                                   offer=offer.MENU, candidate=intent.WITHHELD)
            self.assertIsNone(got)
            self.assertIn("written by hand", why)


if __name__ == "__main__":
    unittest.main()
