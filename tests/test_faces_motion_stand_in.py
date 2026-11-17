"""The hand-written `faces-motion` stand-in proposal for `enemy-walks-backwards` (#286).

tools/faces_motion_stand_in.py writes it; `jit run --proposal` replays it under the keep rule. These tests
hold that the committed copy is what the tool writes, that a run reads it only under the setting it was made
for, that its windows avoid the frames the bench's evidence lists the enemy partly on screen, and that it
says no model wrote it. They run no game.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail.contracts import load_strict
from expectrail.jit import intent, offer
from expectrail.jit.cli import PROFILE
from expectrail.jit.diff_map import withheld_map
from tools import faces_motion_stand_in as stand_in

PX = stand_in.OFFER
SENSOR = stand_in.OBSERVER


class TheStandIn(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="faces-motion-stand-in-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.profile = load_strict(PROFILE, "mechanics-profile")
        self.report = stand_in.REPORT.read_text(encoding="utf-8", errors="replace")
        self.probes = offer.library(self.profile["actions"], PX, self.report)

    def replay(self, path=stand_in.COMMITTED, report=None, **kw):
        settings = {"offer": PX, "candidate": intent.WITHHELD, "observer": SENSOR, **kw}
        report = self.report if report is None else report
        return intent.from_proposal(path, **settings)(report, "", withheld_map(self.probes), self.profile,
                                                      self.probes)

    def test_the_committed_copy_is_what_the_tool_writes(self):
        stand_in.write(self.tmp)
        self.assertEqual((self.tmp / intent.PROPOSAL_NAME).read_bytes(), stand_in.COMMITTED.read_bytes())

    def test_it_says_no_model_wrote_it_and_carries_no_trace_check(self):
        doc = json.loads(stand_in.COMMITTED.read_text(encoding="utf-8"))
        self.assertEqual(doc["model"], "hand-written-stand-in")
        self.assertIsNone(doc["promptSha256"])
        self.assertTrue(any("no model was called" in d for d in doc["diagnostics"]), doc["diagnostics"])
        self.assertEqual(doc["candidates"], [])
        self.assertEqual(doc["probes"], [])

    def test_a_run_of_its_setting_reads_three_faces_motion_checks_about_the_enemy(self):
        got = self.replay()
        self.assertEqual([(c["probe"], c["window"]["fromFrame"]) for c in got["pixelChecks"]],
                         [("hold-right", 30), ("reverse", 130), ("move-fire-right", 30)])
        for c in got["pixelChecks"]:
            self.assertEqual((c["object"], c["observer"], c["predicate"]), ("enemy", SENSOR, {"type": "faces-motion"}))
            self.assertNotIn("toFrame", c["window"])

    def test_it_is_bound_to_the_report_with_the_candidate_withheld(self):
        doc = json.loads(stand_in.COMMITTED.read_text(encoding="utf-8"))
        self.assertIsNone(doc["patchSha256"])
        self.assertEqual(doc["candidate"], intent.WITHHELD)
        with self.assertRaisesRegex(intent.IntentUnavailable, "different report"):
            self.replay(report=self.report + "\nAnd something else.")

    def test_a_run_of_another_setting_refuses_it(self):
        for kw, why in (({"candidate": intent.SHOWN}, "PROPOSAL_MISMATCH: .*candidate"),
                        ({"observer": "sam-3.1-anchor"}, "PROPOSAL_MISMATCH: .*observer"),
                        ({"offer": "signals-reach-evidence", "observer": None}, "PROPOSAL_MISMATCH: .*offer")):
            with self.subTest(**kw), self.assertRaisesRegex(intent.IntentUnavailable, why):
                self.replay(**kw)

    def test_a_run_that_judges_no_pixel_checks_still_reads_it(self):
        # jit.yml's first replay judges no pixel checks (--observer none): the checks are read, then not run.
        self.assertEqual(len(self.replay(observer=None)["pixelChecks"]), 3)

    def test_every_window_starts_after_the_enemy_is_last_partly_on_screen(self):
        evidence = json.loads(stand_in.EVIDENCE.read_text(encoding="utf-8"))
        for probe, start, _ in stand_in.WINDOWS:
            with self.subTest(probe=probe):
                last = stand_in.last_enemy_edge(evidence, probe)
                self.assertIsNotNone(last)
                self.assertGreater(start, last)

    def test_a_window_on_an_edge_frame_is_refused(self):
        bad = (("hold-right", 27, "holding right"),)
        with mock.patch.object(stand_in, "WINDOWS", bad), self.assertRaisesRegex(ValueError, "partly on screen"):
            stand_in.write(self.tmp)
        self.assertFalse((self.tmp / intent.PROPOSAL_NAME).exists())

    def test_evidence_that_cannot_say_is_refused(self):
        evidence = {"rows": [{"probe": "hold-right", "edges": {"objects": {"enemy": None}}}, {"probe": "reverse"}]}
        for probe in ("hold-right", "reverse", "move-fire-right"):
            with self.subTest(probe=probe), self.assertRaises(ValueError):
                stand_in.last_enemy_edge(evidence, probe)

    def test_a_check_the_parser_refuses_stops_the_tool(self):
        broken = [dict(stand_in.checks()[0], object="coin")]
        with mock.patch.object(stand_in, "checks", lambda: broken):
            doc = stand_in.write(self.tmp)
        # propose_to_file records the refusal as the proposal's error, so nothing can be replayed from it.
        self.assertIsNotNone(doc["error"])
        self.assertEqual(doc["pixelChecks"], [])


RECORD = stand_in.COMMITTED.parent / "jit-run.json"


class TheRecordedRun(unittest.TestCase):
    """The run of November 17 (Godot 4.7.2, no model): `jit run --proposal` on the committed stand-in."""

    def setUp(self):
        self.doc = load_strict(RECORD, "jit-run")

    def test_it_is_a_run_of_the_committed_stand_in_on_the_bench_defect(self):
        from expectrail.repro import bench, score

        defect = next(d for d in bench.load()["defects"] if d["id"] == stand_in.DEFECT)
        inputs = self.doc["inputs"]
        self.assertEqual(inputs["model"], stand_in.MODEL)
        self.assertEqual(inputs["reportSha256"], json.loads(stand_in.COMMITTED.read_text(encoding="utf-8"))["reportSha256"])
        self.assertEqual(inputs["basePatchSha256"], [bench.sha256(bench.REPO / defect["patch"])])
        self.assertEqual(inputs["patchSha256"], bench.sha256(bench.REPO / score.NO_FIX))
        self.assertEqual(self.doc["settings"]["offer"], PX)
        self.assertEqual(self.doc["settings"]["candidate"], intent.WITHHELD)
        self.assertEqual(self.doc["settings"]["reps"], 3)
        self.assertEqual(self.doc["status"], "complete")
        self.assertEqual(self.doc["spend"]["samImages"], 0)

    def test_the_keep_rule_keeps_all_three_from_their_runs(self):
        from expectrail.jit import pixel

        kept = pixel.kept_rows(self.doc)
        self.assertEqual([r["check"]["id"] for r in kept], [c["id"] for c in stand_in.checks()])
        for row in self.doc["pixelChecks"]:
            with self.subTest(check=row["check"]["id"]):
                self.assertEqual((row["clean"], row["bug"], row["candidate"]),
                                 (["pass"] * 3, ["fail"] * 3, ["fail"] * 3))
                self.assertEqual(row["setting"]["model"], "expectrail.template-foreground/v3")

    def test_the_reproduction_score_gives_it_no_result(self):
        from expectrail.repro import bench, score

        tmp = Path(tempfile.mkdtemp(prefix="faces-motion-score-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        case = tmp / "records" / f"{score.CASE_PREFIX}{stand_in.DEFECT}"
        case.mkdir(parents=True)
        shutil.copy(RECORD, case / "jit-run.json")
        doc = score.score(bench.load(), tmp / "records", offer=PX, candidate=intent.WITHHELD)
        row = next(r for r in doc["rows"] if r["id"] == stand_in.DEFECT)
        self.assertEqual(row["outcome"], "no-result")
        self.assertIn("written by hand", row["why"])
        self.assertEqual(doc["totals"]["reproduced"], 0)
        self.assertEqual(score.problems(doc), [])

    def test_the_scorer_names_every_stand_in_the_repository_has(self):
        from expectrail.repro import score

        self.assertIn(stand_in.MODEL, score.STAND_INS)
        rehearsal = sorted((bench_root := stand_in.ROOT / "bench" / "jit" / "rehearsal").glob("*/jit-proposal.json"))
        self.assertTrue(rehearsal, bench_root)
        for path in rehearsal:
            with self.subTest(path=path.parent.name):
                self.assertIn(json.loads(path.read_text(encoding="utf-8"))["model"], score.STAND_INS)


if __name__ == "__main__":
    unittest.main()
