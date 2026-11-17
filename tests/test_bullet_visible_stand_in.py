"""The hand-written `visible` bullet stand-in proposal for `bullet-behind-scenery`, judged by SAM (#286).

tools/bullet_visible_stand_in.py writes it; `jit run --proposal --pixel-capture` replays its probes with
frames and asks nothing. These tests hold that the committed copy is what the tool writes, that a run reads
it only under the setting it was made for, that SAM's plan on its probes asks about no frame the bench's
evidence lists a bullet partly on screen, that it says no model wrote it, and what the committed capture
record shows. They run no game and call no model.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail.contracts import load_strict
from expectrail.jit import intent, offer, pixel
from expectrail.jit.cli import PROFILE
from expectrail.jit.diff_map import withheld_map
from tools import bullet_visible_stand_in as stand_in

PX = stand_in.OFFER
SAM = stand_in.OBSERVER


class TheCapturePlan(unittest.TestCase):
    """The plan measured from the capture of the whole probes (November 17, Godot 4.7.2, no model)."""

    def setUp(self):
        self.plan = json.loads(stand_in.PLAN.read_text(encoding="utf-8"))

    def test_it_measures_every_replay_of_the_three_probes(self):
        self.assertEqual(sorted(self.plan["probes"]), sorted(p for p, _, _ in stand_in.PROBES))
        self.assertEqual(self.plan["maxBoxes"], pixel.MAX_BOXES)
        for probe, entry in self.plan["probes"].items():
            with self.subTest(probe=probe):
                self.assertEqual(sorted(entry["bullets"]), ["pixel-base", "pixel-candidate", "pixel-reference"])
                for reps in entry["bullets"].values():
                    self.assertEqual(sorted(reps), ["1", "2", "3"])
                    for counts in reps.values():
                        self.assertEqual(len(counts), len(entry["planned"]))

    def test_the_engine_logs_the_same_bullets_on_every_build(self):
        # The defect changes only what is drawn: the engine's record of the bullets is the same.
        for probe, entry in self.plan["probes"].items():
            runs = [tuple(c) for reps in entry["bullets"].values() for c in reps.values()]
            self.assertEqual(len(set(runs)), 1, probe)

    def test_every_window_is_clear(self):
        for probe, window, _ in stand_in.PROBES:
            with self.subTest(probe=probe):
                self.assertEqual(stand_in.window_problems(self.plan, probe, window), [])

    def test_what_pixel_ask_reserves(self):
        # Every planned frame of the probes, windows or not: what pixel-ask said on the capture of the whole
        # probes ("the 27 replays need up to 1296 images, $3.2400"), over jit.yml's $2 cap.
        images = stand_in.reserved_images(self.plan)
        self.assertEqual(images, 1296)
        self.assertGreater(images * 0.0025, stand_in.CAP_USD)

    def test_measure_counts_bullets_on_the_planned_frames_of_a_capture(self):
        tmp = Path(tempfile.mkdtemp(prefix="bullet-plan-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        route = {"name": "jit-move-fire-left", "ticks": 46}     # frames 0 to 22: planned 0, 10, 20, 22
        folders = []
        for build in ("pixel-reference", "pixel-base"):
            folder = tmp / build / "move-fire-left-1"
            (folder / "frames").mkdir(parents=True)
            (folder / "route.json").write_text(json.dumps(route), encoding="utf-8")
            (folder / "trace.json").write_text("{}", encoding="utf-8")
            folders.append(folder)
        boxes = {0: {"boxes": []}, 10: {"boxes": [{}]}, 20: {"boxes": [{}] * 4}, 22: {"why": "no camera"}}

        def checked(folder, route, frames, fps, tps):
            png = tmp / "f.png"
            if not png.exists():
                from PIL import Image
                Image.new("RGB", (64, 48)).save(png)
            return {}, [], {n: png for n in frames}
        with mock.patch("expectrail.jit.sam_observer.checked_replay", checked), \
                mock.patch("agents.sam_anchor.object_boxes", lambda trace, size, frames, role: boxes):
            got = stand_in.measure(tmp)
        entry = got["probes"]["move-fire-left"]
        self.assertEqual(entry["planned"], [0, 10, 20, 22])
        self.assertEqual(entry["bullets"]["pixel-base"]["1"], [0, 1, 4, None])
        self.assertEqual(stand_in.window_problems(got, "move-fire-left", {"fromFrame": 10, "toFrame": 10}), [])
        self.assertEqual(stand_in.window_problems(got, "move-fire-left", {"fromFrame": 0, "toFrame": 0}),
                         ["move-fire-left: no frame in the window has a bullet on screen on every clean replay"])
        why = stand_in.window_problems(got, "move-fire-left", {"fromFrame": 0})
        self.assertTrue(any("4 bullets on screen" in w for w in why), why)
        self.assertTrue(any("frame 22" in w and "no bullet boxes" in w for w in why), why)


class TheStandIn(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bullet-visible-stand-in-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.profile = load_strict(PROFILE, "mechanics-profile")
        self.report = stand_in.REPORT.read_text(encoding="utf-8", errors="replace")
        self.probes = offer.library(self.profile["actions"], PX, self.report)

    def replay(self, path=stand_in.COMMITTED, report=None, **kw):
        settings = {"offer": PX, "candidate": intent.WITHHELD, "observer": SAM, **kw}
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
        self.assertEqual((doc["candidates"], doc["probes"]), ([], []))

    def test_it_is_made_for_sam_so_it_records_no_observer(self):
        # SAM is the default observer: a proposal made for it is as one made before the setting existed.
        doc = json.loads(stand_in.COMMITTED.read_text(encoding="utf-8"))
        self.assertNotIn("observer", doc)
        self.assertEqual(SAM, pixel.DEFAULT_OBSERVER)

    def test_a_run_of_its_setting_reads_three_visible_checks_about_the_bullet(self):
        got = self.replay()
        self.assertEqual([(c["probe"], c["window"]) for c in got["pixelChecks"]],
                         [("shoot-left-every12", {"fromFrame": 50}), ("move-fire-left", {"fromFrame": 90}),
                          ("move-fire-right", {"fromFrame": 10, "toFrame": 80})])
        for c in got["pixelChecks"]:
            self.assertEqual((c["object"], c["observer"]), ("bullet", SAM))
            self.assertEqual(c["predicate"], {"type": "visible", "minFraction": 1.0})

    def test_every_probe_is_one_the_screen_record_shows_the_defect_on(self):
        evidence = json.loads(stand_in.EVIDENCE.read_text(encoding="utf-8"))
        rows = {r["probe"]: r for r in evidence["rows"]}
        for probe, _, _ in stand_in.PROBES:
            with self.subTest(probe=probe):
                self.assertEqual(rows[probe]["sees"], "screen-only")

    def test_it_is_bound_to_the_report_with_the_candidate_withheld(self):
        doc = json.loads(stand_in.COMMITTED.read_text(encoding="utf-8"))
        self.assertIsNone(doc["patchSha256"])
        self.assertEqual(doc["candidate"], intent.WITHHELD)
        with self.assertRaisesRegex(intent.IntentUnavailable, "different report"):
            self.replay(report=self.report + "\nAnd something else.")

    def test_a_run_of_another_setting_refuses_it(self):
        for kw, why in (({"candidate": intent.SHOWN}, "PROPOSAL_MISMATCH: .*candidate"),
                        ({"observer": "visual-sensor"}, "PROPOSAL_MISMATCH: .*observer"),
                        ({"offer": "signals-reach-evidence", "observer": None}, "PROPOSAL_MISMATCH: .*offer")):
            with self.subTest(**kw), self.assertRaisesRegex(intent.IntentUnavailable, why):
                self.replay(**kw)

    def test_the_sensor_cannot_be_asked_about_the_bullet(self):
        # Why the checks name SAM: the sensor's bank holds no bullet template.
        entry = dict(stand_in.checks()[0], observer="visual-sensor")
        check, why = pixel.parse_candidate(entry, pixel.bindings_for(), {p["id"] for p in self.probes},
                                           pixel.proposed("visual-sensor"))
        self.assertIsNone(check)
        self.assertIn("bullet", why)

    def test_no_planned_frame_is_one_a_bullet_is_partly_on_screen(self):
        evidence = json.loads(stand_in.EVIDENCE.read_text(encoding="utf-8"))
        ids = {probe for probe, _, _ in stand_in.PROBES}
        plans = stand_in.planned([p for p in self.probes if p["id"] in ids], self.profile)
        for probe, window, _ in stand_in.PROBES:
            with self.subTest(probe=probe):
                self.assertTrue(stand_in.in_window(plans[probe], window))
                self.assertFalse(set(plans[probe]) & stand_in.bullet_edges(evidence, probe))
        # The probes with edges are the ones this guards: move-fire-right has five such frames, none planned.
        self.assertEqual(sorted(stand_in.bullet_edges(evidence, "move-fire-right")), [73, 83, 84, 108, 132])

    def test_a_plan_that_asks_about_an_edge_frame_is_refused(self):
        def clash(probes, profile):
            return {p["id"]: [10, 50, 73, 90] for p in probes}
        with mock.patch.object(stand_in, "planned", clash), self.assertRaisesRegex(ValueError, "partly on screen"):
            stand_in.write(self.tmp)
        self.assertFalse((self.tmp / intent.PROPOSAL_NAME).exists())

    def test_a_plan_measured_on_other_frames_is_refused(self):
        def other(probes, profile):
            return {p["id"]: [0, 20, 40, 60, 90, 100] for p in probes}
        with mock.patch.object(stand_in, "planned", other), \
                self.assertRaisesRegex(ValueError, "measured on other planned frames"):
            stand_in.write(self.tmp)

    def test_a_window_holding_a_crowded_frame_is_refused(self):
        # move-fire-left has four bullets on screen at frame 80 on every captured replay: SAM is not asked
        # about that frame, so a window holding it is a gap on every run and its check is never kept.
        whole = (("move-fire-left", {"fromFrame": 0}, "walking left and firing"),)
        with mock.patch.object(stand_in, "PROBES", whole), self.assertRaisesRegex(ValueError, "4 bullets on screen"):
            stand_in.write(self.tmp)

    def test_a_window_with_no_bullet_on_the_clean_game_is_refused(self):
        empty = (("move-fire-right", {"fromFrame": 140}, "walking right and firing"),)
        with mock.patch.object(stand_in, "PROBES", empty), \
                self.assertRaisesRegex(ValueError, "no frame in the window has a bullet"):
            stand_in.write(self.tmp)

    def test_evidence_that_cannot_say_is_refused(self):
        evidence = {"rows": [{"probe": "move-fire-left", "edges": {"objects": {"bullet": None}}},
                             {"probe": "move-fire-right"}]}
        for probe in ("move-fire-left", "move-fire-right", "shoot-left-every12"):
            with self.subTest(probe=probe), self.assertRaises(ValueError):
                stand_in.bullet_edges(evidence, probe)

    def test_a_check_the_parser_refuses_stops_the_tool(self):
        broken = [dict(stand_in.checks()[0], object="ground")]
        with mock.patch.object(stand_in, "checks", lambda: broken):
            doc = stand_in.write(self.tmp)
        self.assertIsNotNone(doc["error"])
        self.assertEqual(doc["pixelChecks"], [])

    def test_the_scorer_names_it_a_stand_in(self):
        from expectrail.repro import score

        self.assertIn(stand_in.MODEL, score.STAND_INS)


RECORD = stand_in.COMMITTED.parent / "jit-run.json"


class TheCaptureRecord(unittest.TestCase):
    """The capture of November 17 (Godot 4.7.2, no model, no SAM): `jit run --proposal --pixel-capture` on the
    committed stand-in, at jit.yml's default cap of $2."""

    def setUp(self):
        self.doc = load_strict(RECORD, "jit-run")

    def test_it_is_a_capture_of_the_committed_stand_in_on_the_bench_defect(self):
        from expectrail.repro import bench, score

        defect = next(d for d in bench.load()["defects"] if d["id"] == stand_in.DEFECT)
        inputs = self.doc["inputs"]
        self.assertEqual(inputs["model"], stand_in.MODEL)
        self.assertEqual(inputs["reportSha256"], json.loads(stand_in.COMMITTED.read_text(encoding="utf-8"))["reportSha256"])
        self.assertEqual(inputs["basePatchSha256"], [bench.sha256(bench.REPO / defect["patch"])])
        self.assertEqual(inputs["patchSha256"], bench.sha256(bench.REPO / score.NO_FIX))
        self.assertEqual((self.doc["settings"]["offer"], self.doc["settings"]["candidate"]), (PX, intent.WITHHELD))
        self.assertEqual((self.doc["settings"]["reps"], self.doc["settings"]["budgetUsd"]), (3, stand_in.CAP_USD))
        self.assertEqual(self.doc["status"], "complete")

    def test_nothing_was_asked_and_every_check_waits_for_the_asking_job(self):
        from expectrail.jit import pixel_jobs

        self.assertEqual((self.doc["spend"]["samImages"], self.doc["spend"]["samUsd"]), (0, 0.0))
        self.assertEqual(self.doc["spend"]["replays"], 27)
        self.assertEqual([r["check"]["id"] for r in self.doc["pixelChecks"]], [c["id"] for c in stand_in.checks()])
        for row in self.doc["pixelChecks"]:
            with self.subTest(check=row["check"]["id"]):
                self.assertEqual((row["status"], row["reason"]), ("not-run", pixel_jobs.CAPTURED))
                self.assertEqual((row["clean"], row["bug"], row["candidate"]), ([], [], []))
        self.assertEqual(pixel.kept_rows(self.doc), [])

    def test_the_asking_job_would_get_less_than_it_needs(self):
        from expectrail.jit import pixel_jobs
        from expectrail.jit.run import DEFAULT_PRICES

        left, why = pixel_jobs.budget_left(RECORD, stand_in.CAP_USD)
        self.assertIsNone(why)
        self.assertAlmostEqual(left, stand_in.CAP_USD - self.doc["spend"]["usd"], places=4)
        plan = json.loads(stand_in.PLAN.read_text(encoding="utf-8"))
        self.assertGreater(stand_in.reserved_images(plan) * DEFAULT_PRICES["samUsdPerImage"], left)

    def test_the_reproduction_score_gives_it_no_result(self):
        from expectrail.repro import bench, score

        tmp = Path(tempfile.mkdtemp(prefix="bullet-visible-score-"))
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


if __name__ == "__main__":
    unittest.main()
