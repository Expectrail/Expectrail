"""Public-scale measurements and miss accounting load with no image/array packages."""
import copy
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools.playtester.analyze_scale import differences, miss_reason, summarize
from tools.playtester.audit_scale import report_shape
from tools.playtester.producer import reports
from tools.playtester.scale import _batch, public_builds, trace_summary


def trace():
    return {"format": "expectrail.trace/v0", "ticks": 2, "physicsTicksPerSecond": 120,
            "rows": [{"tick": i, "frame": i, "player": [i, 10], "facing": 1,
                      "onFloor": True, "body": [i-1, 0, i+1, 20], "enemies": [], "projectiles": []}
                     for i in range(2)]}


class ScaleTest(unittest.TestCase):
    def test_public_universe_deduplicates_reported_defects_and_includes_fix(self):
        builds = public_builds()
        self.assertEqual(len(builds), 26)
        self.assertEqual(sum(b["kind"] == "defect" for b in builds), 24)
        self.assertEqual([b["id"] for b in builds].count("body-flip"), 1)
        self.assertEqual(builds[-1]["id"], "platform-z-order-pr927")
        self.assertEqual(len({b["patch"] for b in builds}), len(builds))
        self.assertTrue(all(not b["patch"] or b["patch"].startswith(("bugs/reported/", "bench/jit/public/"))
                            for b in builds))

    def test_comparisons_ignore_frame_but_keep_unread_record_fields(self):
        original = trace()
        changed = copy.deepcopy(original)
        changed["rows"][0]["frame"] = 900
        route = {"events": []}
        a = trace_summary(route, original)
        self.assertEqual(a, trace_summary(route, changed))
        changed["rows"][0]["body"][0] -= 1
        fields, signals = differences(a, trace_summary(route, changed))
        self.assertEqual(fields, ["body"])
        self.assertEqual(signals, [])
        self.assertEqual(miss_reason(set(fields), set(signals), "example")[0], "no-signal")

    def test_miss_labels_follow_evidence_and_use_existing_vocabulary(self):
        from expectrail.repro.score import MISS_REASONS
        cases = [(set(), {"player_dx_px"}, "example", "wrong-predicate"),
                 ({"body"}, set(), "example", "no-signal"),
                 (set(), set(), "coin-counter-stuck", "route-never-reaches"),
                 (set(), set(), "bullet-behind-scenery", "probe-language"),
                 (set(), set(), "other", "undetermined")]
        for fields, signals, name, expected in cases:
            reason, basis = miss_reason(fields, signals, name)
            self.assertEqual(reason, expected)
            self.assertIn(reason, MISS_REASONS)
            self.assertTrue(basis)
        # A changed current signal is never replaced by older hand evidence.
        self.assertEqual(miss_reason(set(), {"projectile_count"}, "coin-counter-stuck")[0], "wrong-predicate")

    def test_incomplete_measurement_is_not_a_zero_report_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "plan.json").write_text(json.dumps({"startSeed": 0, "seedsPerBuild": 200,
                                                       "builds": [{"id": "clean"}]}))
            with self.assertRaisesRegex(ValueError, "0/200"):
                summarize(root)

    def test_same_clean_observation_is_not_a_new_defect_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = {"startSeed": 4, "seedsPerBuild": 1,
                    "builds": [{"id": "clean"}, {"id": "example", "kind": "defect"}]}
            (root / "plan.json").write_text(json.dumps(plan))
            row = {"fields": {"player": "same"}, "signals": {"player_dx_px": 0},
                   "reports": [{"observation": "stopped-moving", "fault": {"faultTick": 120}}]}
            for build in ("clean", "example"):
                folder = root / "runs" / build / "4"
                folder.mkdir(parents=True)
                (folder / "measurement.json").write_text(json.dumps(row))
            result = summarize(root)
            self.assertEqual(result["clean"]["reports"], 1)
            self.assertEqual(result["defects"][0]["rawReports"], 1)
            self.assertFalse(result["defects"][0]["candidateFound"])

    def test_batch_keeps_raw_evidence_and_resume_skips_engine(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ):
            root = Path(tmp)
            project = root / "builds/clean/game"
            project.mkdir(parents=True)
            (project / "project.godot").write_text('[physics]\ncommon/physics_ticks_per_second=120\n[input]\nmove_right={}\n')

            def engine(_route, out, **_kw):
                out.mkdir(parents=True)
                (out / "trace.json").write_text(json.dumps(trace()))
                (out / "godot.log").write_text('Godot Engine v4.7.2\n')
                record = {"engine": {"name": "godot"}, "isolation": {"sandbox": False}}
                (out / "replay.json").write_text(json.dumps(record))
                return record

            task = (str(root), {"id": "clean", "commit": "a"*40}, [0], "/unused/godot", 2)
            with mock.patch("tools.playtester.scale.run", side_effect=engine) as replay:
                self.assertEqual(_batch(task)["completed"], 1)
                self.assertEqual(_batch(task)["completed"], 1)
                self.assertEqual(replay.call_count, 1)
                with self.assertRaisesRegex(ValueError, "no offscreen policy"):
                    _batch((*task, [100, 80]))
            with gzip.open(root / "runs/clean/0/trace.json.gz", "rt") as stream:
                self.assertEqual(json.load(stream), trace())
            self.assertFalse((root / "scratch/clean/0").exists())

    def test_unmeasured_policy_is_not_counted_as_zero_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "plan.json").write_text(json.dumps({"startSeed": 0, "seedsPerBuild": 1,
                                                       "builds": [{"id": "clean"}]}))
            folder = root / "runs/clean/0"
            folder.mkdir(parents=True)
            (folder / "measurement.json").write_text(json.dumps({"reports": []}))
            with self.assertRaisesRegex(ValueError, "was not measured"):
                summarize(root, policy="offscreen")

    def test_modules_load_when_numpy_and_pil_imports_are_blocked(self):
        program = '''
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'numpy', 'PIL'}:
            raise ImportError('deliberately unavailable: ' + fullname)
sys.meta_path.insert(0, Block())
import tools.playtester.scale
import tools.playtester.analyze_scale
import tools.playtester.audit_scale
import tools.playtester.offscreen
import tests.test_playtester
import tests.test_playtester_scale
import tests.test_playtester_offscreen
print('loaded without numpy or PIL')
'''
        done = subprocess.run([sys.executable, "-c", program], text=True, capture_output=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("loaded without numpy or PIL", done.stdout)

    def test_report_audit_requires_the_exact_recorded_anchor(self):
        route = {"format": "expectrail.route/v0", "name": "audit", "ticks": 2, "events": []}
        recorded = trace()
        recorded["levelSurfaces"] = [[[0, 100]]]
        recorded["rows"][1]["player"][1] = 200
        document = reports(route, recorded, "a" * 40)[0]
        report_shape(document, route, recorded, "a" * 40)
        document["fault"]["anchor"]["x"] += 1
        with self.assertRaisesRegex(ValueError, "logged previous position"):
            report_shape(document, route, recorded, "a" * 40)


if __name__ == "__main__":
    unittest.main()
