"""The anchored rule (#330): the anchored probe's boxes held against the range a clean run sets.

Two kinds of test. Made-up rows hold what the rule means: what is in, what is out, what is never a
pass. The recorded answers under tests/data/sam-anchor are what SAM 3.1 said on November 12, 2026
about the bundled game and its eight seeded bugs (runs 43306507436 and 43310237299, 95 images each,
the point at the origin and 14 game pixels above it): they hold what the rule says about real
answers. Nothing here is sent anywhere. Standard library only.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents import anchor_rule as rule

DATA = Path(__file__).resolve().parent / "data" / "sam-anchor"
AT_ORIGIN = DATA / "bundled-lift-0.json"
MID_BODY = DATA / "bundled-lift-14.json"
OTHER_CLEAN = DATA / "bundled-lift-14-other-clean-routes.json"      # run 43316420400: coins, combat, traversal


def row(frame, width=40.0, height=60.0, above=30.0, below=30.0, holds=True):
    return {"frame": frame, "asked": True, "box": [0, 0, 1, 1], "score": 0.9, "holdsPoint": holds,
            "worldSize": [width, height], "aboveOrigin": above, "belowOrigin": below}


def clean_run():
    return {"run": "clean", "frames": [row(0, 40, 60, 30, 30), row(10, 50, 56, 28, 28), row(20, 44, 64, 34, 30)]}


class CalibrateTest(unittest.TestCase):
    def test_the_range_is_the_clean_runs_smallest_and_largest_widened_by_the_pad(self):
        cal = rule.calibrate(clean_run(), pad=0)
        self.assertEqual(cal["ranges"], {"width": [40, 50], "height": [56, 64], "above": [28, 34], "below": [28, 30]})
        self.assertEqual((cal["from"], cal["frames"], cal["pad"]), ("clean", [0, 10, 20], 0))
        self.assertEqual(rule.calibrate(clean_run(), pad=2)["ranges"]["below"], [26, 32])
        self.assertEqual(rule.calibrate(clean_run())["pad"], rule.DEFAULT_PAD)

    def test_frames_that_were_not_asked_about_set_nothing(self):
        run = clean_run()
        run["frames"].append({"frame": 30, "asked": False, "note": "the player is outside the picture"})
        self.assertEqual(rule.calibrate(run, pad=0)["frames"], [0, 10, 20])

    def test_a_clean_run_the_observer_could_not_read_sets_no_range(self):
        for broken in ({"frame": 30, "asked": True, "box": None, "score": None, "note": "nothing came back for the point"},
                       {"frame": 30, "asked": True, "box": None, "score": None, "error": "unrecognised"},
                       row(30, holds=False)):
            run = clean_run()
            run["frames"].append(broken)
            with self.subTest(broken=broken), self.assertRaises(rule.RuleError) as refused:
                rule.calibrate(run)
            self.assertIn("[30]", str(refused.exception))

    def test_no_asked_frame_or_a_negative_pad_is_refused(self):
        with self.assertRaises(rule.RuleError):
            rule.calibrate({"run": "clean", "frames": [{"frame": 0, "asked": False}]})
        with self.assertRaises(rule.RuleError):
            rule.calibrate(clean_run(), pad=-1)


class JudgeTest(unittest.TestCase):
    CAL = rule.calibrate(clean_run(), pad=2)       # width 38-52, height 54-66, above 26-36, below 26-32

    def one(self, r):
        return rule.judge_frame(r, self.CAL["ranges"])

    def test_a_box_inside_every_range_is_in_and_the_ends_count_as_inside(self):
        self.assertEqual(self.one(row(5, 45, 60, 30, 30)), {"frame": 5, "state": "in", "why": []})
        self.assertEqual(self.one(row(5, 38, 66, 26, 32))["state"], "in")

    def test_each_measure_outside_is_out_and_says_which(self):
        cases = {"width": row(5, width=52.5), "height": row(5, height=53.5), "above": row(5, above=36.5),
                 "below": row(5, below=50.5)}
        for name, r in cases.items():
            with self.subTest(measure=name):
                got = self.one(r)
                self.assertEqual(got["state"], "out")
                self.assertEqual(len(got["why"]), 1)
                self.assertTrue(got["why"][0].startswith(name + " "), got["why"])
        self.assertEqual(self.one(row(5, below=50.5))["why"], ["below 50.5 (clean 26 to 32)"])

    def test_a_box_that_does_not_hold_the_point_is_out_whatever_its_size(self):
        self.assertEqual(self.one(row(5, holds=False)), {"frame": 5, "state": "out", "why": ["the box does not hold the point"]})

    def test_no_box_is_no_answer_and_a_frame_not_asked_is_not_judged(self):
        self.assertEqual(self.one({"frame": 5, "asked": True, "box": None, "note": "nothing came back for the point"}),
                         {"frame": 5, "state": "no-answer", "why": ["nothing came back for the point"]})
        self.assertEqual(self.one({"frame": 5, "asked": True, "box": None, "error": "unrecognised sam-3.1 output"})["state"], "no-answer")
        self.assertEqual(self.one({"frame": 5, "asked": False, "note": "the player is outside the picture"}),
                         {"frame": 5, "state": "not-asked", "why": ["the player is outside the picture"]})

    def test_a_run_fails_on_its_first_frame_out(self):
        got = rule.judge({"run": "bug", "frames": [row(0), row(10, below=50), row(20, height=20)]}, self.CAL)
        self.assertEqual((got["result"], got["judged"], got["out"], got["in"]), ("fail", 3, 2, 1))
        self.assertIn("2 of 3 judged frames are outside the clean range, first frame 10: below 50 (clean 26 to 32)", got["reason"])

    def test_a_frame_out_fails_the_run_even_beside_a_missing_answer(self):
        got = rule.judge({"run": "bug", "frames": [row(0, below=50), {"frame": 10, "asked": True, "box": None}]}, self.CAL)
        self.assertEqual(got["result"], "fail")

    def test_a_missing_answer_is_never_a_pass(self):
        got = rule.judge({"run": "r", "frames": [row(0), {"frame": 10, "asked": True, "box": None}]}, self.CAL)
        self.assertEqual((got["result"], got["no-answer"]), ("needs-review", 1))
        self.assertIn("never a pass", got["reason"])

    def test_a_run_with_nothing_judged_is_needs_review(self):
        for frames in ([], [{"frame": 0, "asked": False, "note": "the player is outside the picture"}]):
            with self.subTest(frames=frames):
                self.assertEqual(rule.judge({"run": "r", "frames": frames}, self.CAL)["result"], "needs-review")

    def test_every_judged_frame_inside_is_a_pass_and_says_how_many(self):
        got = rule.judge({"run": "r", "frames": [row(0), row(10), {"frame": 20, "asked": False}]}, self.CAL)
        self.assertEqual((got["result"], got["reason"], got["not-asked"]), ("pass", "all 2 judged frames are inside the clean range", 1))


class RecordedAnswersTest(unittest.TestCase):
    """What the rule says about SAM's real answers on the bundled game. Set on its clean run."""

    def judged(self, path, on="clean", pad=rule.DEFAULT_PAD):
        report, clean = rule.load_run(path, on)
        cal = rule.calibrate(clean, pad, report["lift"])
        return cal, {r["run"]: r for r in (rule.judge(run, cal) for run in report["runs"])}

    def test_at_mid_body_the_clean_robots_range_is_the_robots_size(self):
        cal, _ = self.judged(MID_BODY, pad=0)
        self.assertEqual(cal["ranges"], {"width": [30.5, 59.0], "height": [52.0, 64.5], "above": [26.0, 36.0], "below": [25.5, 37.5]})
        self.assertEqual((len(cal["frames"]), cal["lift"]), (13, 14.0))

    def test_at_mid_body_clean_and_the_coins_bug_pass_and_the_drawing_bugs_fail(self):
        _, got = self.judged(MID_BODY)
        outs = {name: (r["result"], r["out"], r["judged"]) for name, r in got.items()}
        self.assertEqual(outs, {
            "clean": ("pass", 0, 13),
            "missing-texture_v1": ("pass", 0, 13),          # the coins' texture: nothing about the robot changed
            "missing-texture_v2": ("pass", 0, 13),
            "layering_v1": ("fail", 9, 13),                 # the robot behind the level
            "layering_v2": ("fail", 9, 13),
            "sinking_v2": ("fail", 13, 13),                 # drawn 26 px lower than the engine says: every frame
            "sinking_v1": ("fail", 1, 13),                  # the engine's to catch; one frame's box is 73.5 px wide
            "physics-fall-through_v1": ("pass", 0, 2),      # the engine's to catch; 11 frames are out of the picture
            "physics-fall-through_v2": ("pass", 0, 2),
        })
        # Clean frame 0 reaches 29 px above the point and 30 below. The patch moves the drawing 26 px down: 3 and 56.
        self.assertIn("first frame 0: above 3 (clean 24 to 38); below 56 (clean 23.5 to 39.5)", got["sinking_v2"]["reason"])
        self.assertEqual(got["physics-fall-through_v1"]["not-asked"], 11)

    def test_the_sinking_bug_the_engine_cannot_see_is_out_by_its_reach_in_every_frame(self):
        _, got = self.judged(MID_BODY)
        for frame in got["sinking_v2"]["frames"]:
            self.assertTrue(any(w.startswith("below ") for w in frame["why"]), frame)

    def test_with_no_pad_the_clean_run_fails_the_range_another_clean_looking_run_sets(self):
        # The pad's reason: the same robot in the same frames, only the coins different.
        _, unpadded = self.judged(MID_BODY, on="missing-texture_v1", pad=0)
        self.assertEqual((unpadded["clean"]["result"], unpadded["clean"]["out"]), ("fail", 1))
        _, padded = self.judged(MID_BODY, on="missing-texture_v1")
        self.assertEqual((padded["clean"]["result"], padded["layering_v1"]["out"], padded["sinking_v2"]["out"]), ("pass", 9, 13))

    def test_at_the_origin_the_clean_range_is_too_wide_to_mean_much(self):
        # Two clean frames got a small part of the robot, so "clean" spans a 7.5 px part to the whole robot.
        cal, got = self.judged(AT_ORIGIN, pad=0)
        self.assertEqual((cal["ranges"]["height"], cal["ranges"]["width"]), ([7.5, 63.5], [12.5, 59.5]))
        self.assertEqual((got["layering_v1"]["out"], got["sinking_v2"]["out"], got["missing-texture_v1"]["out"]), (6, 13, 2))

    def held_out(self, pad=rule.DEFAULT_PAD):
        """The clean game on three routes the range was not set on, against the smoke route's clean range."""
        report, clean = rule.load_run(MID_BODY, "clean")
        cal = rule.calibrate(clean, pad, report["lift"])
        other = rule.load_report(OTHER_CLEAN)
        self.assertEqual(other["lift"], report["lift"])
        return {r["run"]: r for r in (rule.judge(run, cal) for run in other["runs"])}

    def test_the_known_false_alarm_one_clean_frame_in_36_fails_a_clean_route(self):
        # The first measurement on clean frames the range was not set on (November 12, 2026). In frame
        # 20 of the traversal route the robot jumps in front of a tree and SAM answered with the robot
        # and the trunk under it as one object, 107.5 px tall. The rule as it stands fails the route.
        # This test holds the fault in view; it changes when the rule does.
        got = self.held_out()
        self.assertEqual({n: (r["result"], r["out"], r["judged"]) for n, r in got.items()}, {
            "clean-coins": ("pass", 0, 13), "clean-combat": ("pass", 0, 10), "clean-traversal": ("fail", 1, 13)})
        self.assertIn("first frame 20: height 107.5 (clean 50 to 66.5); below 81 (clean 23.5 to 39.5)",
                      got["clean-traversal"]["reason"])

    def test_no_pad_cures_it_and_no_pad_at_all_is_much_worse(self):
        self.assertEqual([r["out"] for r in self.held_out(pad=0).values()], [4, 1, 3])     # 8 of 36 with no pad
        self.assertEqual([r["out"] for r in self.held_out(pad=16).values()], [0, 0, 1])
        self.assertEqual([r["out"] for r in self.held_out(pad=43).values()], [0, 0, 1])
        # A pad wide enough to take the trunk in (44 px) would take the sinking bug in with it.
        report, clean = rule.load_run(MID_BODY, "clean")
        wide = rule.calibrate(clean, 44, report["lift"])
        sinking = rule.judge(rule.load_run(MID_BODY, "sinking_v2")[1], wide)
        self.assertEqual([r["out"] for r in self.held_out(pad=44).values()], [0, 0, 0])
        self.assertEqual(sinking["result"], "pass")

    def test_the_two_recorded_runs_are_the_runs_they_say_they_are(self):
        for path, lift, run_id in ((AT_ORIGIN, 0.0, "43306507436"), (MID_BODY, 14.0, "43310237299")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual((doc["lift"], doc["stats"]["calls"], len(doc["runs"]), doc["stopped"]), (lift, 95, 9, None))
            self.assertTrue(doc["source"].endswith(run_id))


class MainTest(unittest.TestCase):
    def run_main(self, argv, env=None):
        out, err = io.StringIO(), io.StringIO()
        keep = {k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"}
        with mock.patch.dict(os.environ, {**keep, **(env or {})}, clear=True), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = rule.main([str(a) for a in argv])
        return code, out.getvalue(), err.getvalue()

    def test_it_prints_the_table_and_decides_nothing_by_its_exit_code(self):
        code, out, _ = self.run_main(["--calibrate", f"{MID_BODY}:clean", "--judge", MID_BODY])
        self.assertEqual(code, 0)                         # a probe's rule: a failing run is a row, not an exit code
        self.assertIn("| sinking_v2 | fail | 13 | 13 | 0 | 0 |", out)
        self.assertIn("| clean | pass | 13 | 0 | 0 | 0 | all 13 judged frames are inside the clean range |", out)
        self.assertIn("| below | 23.5 | 39.5 |", out)
        self.assertIn("pad 2 game px, point 14 px above the origin", out)

    def test_it_leaves_the_page_the_numbers_and_notices(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = self.run_main(["--calibrate", f"{MID_BODY}:clean", "--judge", MID_BODY, "--out", tmp],
                                         {"GITHUB_ACTIONS": "true"})
            self.assertEqual(code, 0)
            doc = json.loads((Path(tmp) / "anchor-rule.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["calibration"]["ranges"]["height"], [50.0, 66.5])
            self.assertEqual([r["result"] for r in doc["results"]].count("fail"), 4)
            self.assertTrue((Path(tmp) / "anchor-rule.md").is_file())
        self.assertIn("::notice title=Anchored rule sinking_v2::fail: 13 of 13 judged frames", out)
        self.assertIn("::notice title=Anchored rule range::set on clean, pad 2; width 28.5 to 61;", out)

    def test_answers_asked_at_another_point_are_not_compared(self):
        code, _, err = self.run_main(["--calibrate", f"{MID_BODY}:clean", "--judge", AT_ORIGIN])
        self.assertEqual(code, 2)
        self.assertIn("cannot be compared", err)

    def test_a_run_name_that_is_not_there_or_not_given_is_an_error(self):
        code, _, err = self.run_main(["--calibrate", f"{MID_BODY}:tidy", "--judge", MID_BODY])
        self.assertEqual(code, 2)
        self.assertIn("no run named 'tidy'", err)
        code, _, err = self.run_main(["--calibrate", MID_BODY, "--judge", MID_BODY])
        self.assertEqual(code, 2)
        self.assertIn("holds 9 runs; name one", err)

    def test_a_file_that_is_not_a_report_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "x.json"
            bad.write_text("{}", encoding="utf-8")
            code, _, err = self.run_main(["--calibrate", f"{bad}:clean", "--judge", MID_BODY])
        self.assertEqual(code, 2)
        self.assertIn("not an anchored probe's report", err)


class WorkflowTest(unittest.TestCase):
    """sam-probe.yml, probe mode: other clean routes are replayed with no key, and the rule follows the probe."""

    def setUp(self):
        text = (DATA.parent.parent.parent / ".github" / "workflows" / "sam-probe.yml").read_text(encoding="utf-8")
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        self.job = code.split("\n  sam-probe:\n", 1)[1].split("\n  sam-video:\n", 1)[0]

    def test_the_replay_of_other_clean_routes_holds_no_key_and_takes_only_route_names(self):
        step = self.job.split("- name: Replay the clean game on other routes, when asked", 1)[1].split("\n      - name:", 1)[0]
        self.assertNotIn("secrets.", step)
        self.assertIn("if: ${{ inputs.anchor && inputs.clean_routes != '' }}", step)
        self.assertIn('[[ "$CLEAN_ROUTES" =~ ^[a-z][a-z0-9-]*(,[a-z][a-z0-9-]*){0,5}$ ]]', step)
        self.assertIn('[[ -f "harness/routes/$r.json" ]]', step)
        self.assertIn('python -m harness.run --route "harness/routes/$r.json" --out "runs/seeded/clean-$r"', step)

    def test_the_rule_runs_after_the_probe_and_cannot_fail_the_step(self):
        probe = self.job.index('python -m agents.sam_anchor "${anchor[@]}"\n')
        ruled = self.job.index("python -m agents.anchor_rule --calibrate runs/sam-probe/anchor.json:clean")
        self.assertLess(probe, ruled)
        self.assertIn('|| echo "::warning title=Anchored rule::', self.job[ruled:ruled + 400])
        self.assertIn("for page in anchor-rule.md anchor.md probe.md; do", self.job)


if __name__ == "__main__":
    unittest.main()
