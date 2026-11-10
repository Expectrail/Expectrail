"""The known-bugs bench (expectrail/jit/bench.py): its cases, its scoring, and the registration gate."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from expectrail.jit import bench

REPO = Path(__file__).resolve().parents[1]
BAR = {"minWrongCaught": 3, "minWrongCaughtUntuned": 2, "maxCorrectFalseCatches": 0, "maxNoResult": 0,
       "maxSpendUsdPerCase": 2.0}


def sha(p):
    return hashlib.sha256((REPO / p).read_bytes()).hexdigest()


def record(case, strong=0, weak=0, status="complete", candidate=None, spend=0.07):
    return {"format": "expectrail.jit-run/v1", "runId": case["case"], "advisory": True, "status": status,
            "reason": None if status == "complete" else "MODEL_UNAVAILABLE: test",
            "inputs": {"patchSha256": sha(candidate or case["candidate"]), "reportSha256": "0" * 64,
                       "basePatchSha256": [sha(case["base"])], "profileSha256": "0" * 64, "model": "m",
                       "promptSha256": None},
            "settings": {"reps": 3, "variantLimit": 8, "budgetUsd": 2.0}, "diffMap": None, "proposed": [],
            "probes": [], "variants": [], "validity": [], "catches": [],
            "counts": {"proposed": 4, "valid": 2 if strong or weak else 1, "strong": strong, "weak": weak},
            "spend": {"usd": spend, "capUsd": 2.0, "sparkUsd": 0.0, "replayUsd": 0.0, "samUsd": 0.0, "samImages": 0,
                      "replays": 10, "promptTokens": 1, "completionTokens": 1,
                      "prices": {"sparkUsdPerMTokIn": 1.0, "sparkUsdPerMTokOut": 4.0, "runnerUsdPerMinute": 0.008,
                                 "samUsdPerImage": 0.0025, "source": "assumed"}},
            "diagnostics": []}


class Cases(unittest.TestCase):
    def test_eight_cases_each_bug_a_wrong_and_a_correct_fix_and_every_file_exists(self):
        cases = bench.load_cases()
        self.assertEqual(len(cases), 8)
        for c in cases:
            for k in ("base", "candidate", "report"):
                self.assertTrue((REPO / c[k]).is_file(), c[k])
        self.assertEqual(sorted(c["label"] for c in cases), ["correct"] * 4 + ["wrong"] * 4)
        self.assertEqual({c["bug"] for c in cases if c["tunedOn"]}, {"air-jump"})

    @unittest.skipUnless(shutil.which("patch"), "patch is not installed")
    def test_every_candidate_applies_after_its_bug_and_the_undo_restores_the_clean_game(self):
        for c in bench.load_cases():
            with self.subTest(case=c["case"]), tempfile.TemporaryDirectory() as tmp:
                game = Path(tmp) / "g"
                shutil.copytree(REPO / "game/platformer", game, ignore=shutil.ignore_patterns(".godot"))
                for p in (c["base"], c["candidate"]):
                    subprocess.run(["patch", "-p1", "-s", "-d", str(game), "-i", str(REPO / p)], check=True)
                changed = subprocess.run(["diff", "-r", "-q", "-x", ".godot", str(REPO / "game/platformer"), str(game)],
                                         capture_output=True, text=True).stdout.strip()
                if c["label"] == "correct":
                    self.assertEqual(changed, "")
                else:
                    self.assertNotEqual(changed, "")


class Score(unittest.TestCase):
    def setUp(self):
        self.cases = bench.load_cases()
        self.dir = Path(tempfile.mkdtemp())

    def write(self, case, doc):
        d = self.dir / case["case"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "jit-run.json").write_text(json.dumps(doc))

    def test_meets_the_bar_only_with_catches_off_air_jump_and_no_false_catch(self):
        for c in self.cases:
            self.write(c, record(c, strong=1 if c["label"] == "wrong" else 0))
        doc = bench.score(self.cases, self.dir, BAR)
        self.assertEqual(doc["verdict"], "meets-bar", doc["reasons"])
        self.assertEqual((doc["totals"]["wrongCaught"], doc["totals"]["wrongCaughtUntuned"]), (4, 3))

        # Caught only on the bug it was tuned on plus one other: below the bar.
        for c in self.cases:
            if c["label"] == "wrong" and c["bug"] in ("gun-cooldown", "body-flip"):
                self.write(c, record(c))
        doc = bench.score(self.cases, self.dir, BAR)
        self.assertEqual(doc["verdict"], "below-bar")
        self.assertTrue(any("nobody tuned on" in r for r in doc["reasons"]))

    def test_any_catch_on_a_correct_fix_is_a_false_catch(self):
        for c in self.cases:
            self.write(c, record(c, strong=1 if c["label"] == "wrong" else 0))
        c = next(c for c in self.cases if c["label"] == "correct")
        self.write(c, record(c, weak=1))
        doc = bench.score(self.cases, self.dir, BAR)
        self.assertEqual(doc["totals"]["correctFalseCatches"], 1)
        self.assertEqual(doc["verdict"], "below-bar")

    def test_missing_failed_or_mismatched_records_are_no_result_never_a_pass(self):
        for c in self.cases:
            self.write(c, record(c, strong=1 if c["label"] == "wrong" else 0))
        wrong = [c for c in self.cases if c["label"] == "wrong"]
        shutil.rmtree(self.dir / wrong[0]["case"])
        self.write(wrong[1], record(wrong[1], strong=1, status="nothing-generated"))
        self.write(wrong[2], record(wrong[2], strong=1, candidate=wrong[3]["candidate"]))
        doc = bench.score(self.cases, self.dir, BAR)
        outcomes = {r["case"]: r["outcome"] for r in doc["rows"]}
        self.assertEqual([outcomes[c["case"]] for c in wrong[:3]], ["no-result"] * 3)
        self.assertEqual(doc["verdict"], "below-bar")
        self.assertIn("the record is for another candidate", bench.render(doc))


class Registration(unittest.TestCase):
    def test_a_draft_refuses_to_run(self):
        prereg = dict(json.loads(bench.PREREG.read_text()), status="draft", signedOffBy=None)
        self.assertTrue(bench.check_registration(prereg))

    def test_signed_with_current_pins_runs_and_any_moved_pin_refuses(self):
        prereg = dict(json.loads(bench.PREREG.read_text()), status="registered", signedOffBy="test", pins=bench.pins())
        self.assertEqual(bench.check_registration(prereg), [])
        moved = copy.deepcopy(prereg)
        moved["pins"]["expectrail/jit/intent.py"] = "0" * 64
        self.assertEqual(bench.check_registration(moved), ["pin moved: expectrail/jit/intent.py"])
        unsigned = dict(prereg, signedOffBy=None)
        self.assertTrue(bench.check_registration(unsigned))

    def test_the_registration_holds_once_registered(self):
        prereg = json.loads(bench.PREREG.read_text())
        if prereg["status"] == "registered":
            self.assertEqual(bench.check_registration(prereg), [])


class Workflow(unittest.TestCase):
    def test_bench_mode_runs_from_main_checks_the_registration_and_keys_stay_in_main_only(self):
        import yaml

        text = (REPO / ".github/workflows/jit.yml").read_text()
        plan = text[text.index("  plan:"):text.index("  measure:")]
        self.assertIn('[[ "$GITHUB_REF" == "refs/heads/main" ]]', plan)
        self.assertIn("expectrail.jit.cli bench-check", plan)
        self.assertNotIn("workflow_call", text)  # a called workflow would not see main-only's keys
        jobs = yaml.safe_load(text)["jobs"]
        for name, job in jobs.items():
            if "secrets." in yaml.safe_dump(job):
                self.assertEqual(job.get("environment"), "main-only", name)
        self.assertIn("bench-score", yaml.safe_dump(jobs["score"]))
        self.assertFalse((REPO / ".github/workflows/jit-bench.yml").exists())

if __name__ == "__main__":
    unittest.main()
