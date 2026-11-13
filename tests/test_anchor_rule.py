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
BOXED_HELD_OUT = DATA / "bundled-box-48x68-smoke-and-clean-routes.json"   # run 43337979278: the run the predictions were for
BOXED = DATA / "bundled-box-48x68-traversal-seeded.json"            # run 43335151089: the same four runs, asked with a box
ON_TRAVERSAL = DATA / "bundled-lift-14-traversal-seeded.json"       # run 43326853189: clean and three bugs on traversal
NEAR_THE_SLIP = DATA / "bundled-lift-14-traversal-frames-15-25.json"  # run 43318368572: traversal, frames 15 to 25


def row(frame, width=40.0, height=60.0, above=30.0, below=30.0, holds=True, world=(100.0, 200.0)):
    return {"frame": frame, "asked": True, "box": [0, 0, 1, 1], "score": 0.9, "holdsPoint": holds,
            "world": list(world), "worldSize": [width, height], "aboveOrigin": above, "belowOrigin": below}


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


class PairTest(unittest.TestCase):
    """A changed game's frame against the unchanged game's same frame."""

    def one(self, base, head, tolerance=6.0):
        return rule.pair_frame(base, head, tolerance)

    def test_boxes_that_agree_within_the_tolerance_are_in_and_the_edge_counts(self):
        self.assertEqual(self.one(row(5), row(5)), {"frame": 5, "state": "in", "why": []})
        self.assertEqual(self.one(row(5, width=40), row(5, width=46))["state"], "in")
        self.assertEqual(self.one(row(5, width=40), row(5, width=46.5))["state"], "out")

    def test_each_measure_that_differs_is_named_with_both_values(self):
        got = self.one(row(5, above=29, below=30), row(5, above=3, below=56))
        self.assertEqual(got["state"], "out")
        self.assertEqual(got["why"], ["above 3 against 29 unchanged", "below 56 against 30 unchanged"])

    def test_a_slip_the_unchanged_game_has_too_is_not_a_difference(self):
        # The robot and a trunk answered as one object, 107.5 px tall, in both games: they agree.
        slip = dict(height=107.5, below=81.0)
        self.assertEqual(self.one(row(20, **slip), row(20, **slip))["state"], "in")

    def test_where_the_engine_moved_the_player_nothing_is_compared(self):
        got = self.one(row(5), row(5, height=20, world=(100.0, 226.0)))
        self.assertEqual(got["state"], "moved")
        self.assertEqual(got["why"], ["the engine has the player at 100, 226; unchanged, at 100, 200"])
        self.assertEqual(self.one(row(5), row(5, world=(100.04, 200.0)))["state"], "in")       # the trace's last digit
        self.assertEqual(self.one(row(5), row(5, world=(100.19, 200.0)))["state"], "moved")

    def test_a_fall_in_confidence_is_out_and_a_rise_is_not(self):
        def scored(score):
            return {**row(5), "score": score}
        self.assertEqual(self.one(scored(0.93), scored(0.49))["why"], ["confidence 0.49 against 0.93 unchanged"])
        self.assertEqual(self.one(scored(0.93), scored(0.83))["state"], "in")          # a fall of exactly 0.1 is allowed
        self.assertEqual(self.one(scored(0.93), scored(0.82))["state"], "out")
        self.assertEqual(self.one(scored(0.50), scored(0.93))["state"], "in")          # easier to see is not a fault here
        self.assertEqual(rule.pair_frame(scored(0.93), scored(0.49), 6.0, drop=0.5)["state"], "in")
        # A missing confidence is not a zero: nothing is compared, and nothing is made up.
        self.assertEqual(self.one(scored(0.93), scored(None))["state"], "in")
        self.assertEqual(self.one(scored(None), scored(0.2))["state"], "in")

    def test_no_box_in_either_game_and_frames_not_asked(self):
        empty = {"frame": 5, "asked": True, "box": None, "world": [100.0, 200.0], "note": "nothing came back for the point"}
        self.assertEqual(self.one(row(5), empty)["state"], "no-answer")
        self.assertEqual(self.one(empty, row(5))["state"], "no-base")
        self.assertEqual(self.one(None, row(5))["state"], "no-base")
        self.assertEqual(self.one({"frame": 5, "asked": False}, row(5))["state"], "no-base")
        self.assertEqual(self.one(row(5), {"frame": 5, "asked": False, "note": "the player is outside the picture"})["state"], "not-asked")

    def test_a_box_that_holds_the_point_in_one_game_only_is_out(self):
        self.assertEqual(self.one(row(5), row(5, holds=False))["why"], ["the box holds the point in one game and not in the other"])

    def run_of(self, *frames, name="head", route=None):
        return {"run": name, "frames": list(frames), **({"route": route} if route else {})}

    def test_a_pass_needs_every_asked_frame_compared_and_in(self):
        base = self.run_of(row(0), row(10), row(20), name="clean")
        self.assertEqual(rule.pair(base, self.run_of(row(0), row(10), row(20)))["result"], "pass")
        got = rule.pair(base, self.run_of(row(0), row(10), {"frame": 20, "asked": False}))
        self.assertEqual((got["result"], got["judged"], got["not-asked"]), ("pass", 2, 1))

    def test_a_frame_that_differs_fails_the_run_and_is_named(self):
        base = self.run_of(row(0), row(10), name="clean")
        got = rule.pair(base, self.run_of(row(0), row(10, below=56)))
        self.assertEqual((got["result"], got["out"]), ("fail", 1))
        self.assertIn("first frame 10: below 56 against 30 unchanged", got["reason"])

    def test_frames_this_rule_cannot_compare_are_never_a_pass(self):
        base = self.run_of(row(0), row(10), name="clean")
        for head in (self.run_of(row(0), row(10, world=(100.0, 226.0))),            # the engine moved the player
                     self.run_of(row(0), row(10), row(20)),                          # a frame the base does not have
                     self.run_of(row(0), {"frame": 10, "asked": True, "box": None, "world": [100.0, 200.0]}),
                     self.run_of()):
            with self.subTest(head=head):
                got = rule.pair(base, head)
                self.assertEqual(got["result"], "needs-review")
                self.assertIn("not a pass", got["reason"])

    def test_runs_of_different_routes_are_not_compared(self):
        smoke, combat = {"name": "smoke", "sha256": "a" * 64}, {"name": "combat", "sha256": "b" * 64}
        base = self.run_of(row(0), name="clean", route=smoke)
        got = rule.pair(base, self.run_of(row(0), route=combat))
        self.assertEqual((got["result"], got["judged"]), ("needs-review", 0))
        self.assertIn("a different route (combat against smoke)", got["reason"])
        self.assertEqual(rule.pair(base, self.run_of(row(0), route=dict(smoke)))["result"], "pass")
        # A route of the same name with other contents is another route: the digest decides.
        self.assertEqual(rule.pair(base, self.run_of(row(0), route={"name": "smoke", "sha256": "c" * 64}))["result"], "needs-review")
        # A run that does not say its route is compared: older reports did not record it.
        self.assertEqual(rule.pair(base, self.run_of(row(0)))["result"], "pass")

    def test_a_negative_tolerance_or_drop_is_refused(self):
        with self.assertRaises(rule.RuleError):
            rule.pair(self.run_of(row(0)), self.run_of(row(0)), tolerance=-1)
        with self.assertRaises(rule.RuleError):
            rule.pair(self.run_of(row(0)), self.run_of(row(0)), drop=-0.1)


class RecordedPairsTest(unittest.TestCase):
    """The recorded answers, every run against the clean run's same frame (mid-body, tolerance 6)."""

    def paired(self, path=MID_BODY, tolerance=rule.DEFAULT_TOLERANCE):
        report, clean = rule.load_run(path, "clean")
        return {run["run"]: rule.pair(clean, run, tolerance) for run in report["runs"] if run["run"] != "clean"}

    def test_the_drawing_bugs_differ_the_coins_bug_agrees_and_the_engines_bugs_are_not_compared(self):
        got = {name: (r["result"], r["out"], r["judged"], r["moved"]) for name, r in self.paired().items()}
        self.assertEqual(got, {
            "missing-texture_v1": ("pass", 0, 13, 0),
            "missing-texture_v2": ("pass", 0, 13, 0),
            "layering_v1": ("fail", 9, 13, 0),
            "layering_v2": ("fail", 9, 13, 0),
            "sinking_v2": ("fail", 13, 13, 0),
            "sinking_v1": ("needs-review", 0, 0, 13),                 # the engine has the robot 26 px lower
            "physics-fall-through_v1": ("needs-review", 0, 0, 2),     # and falling; 11 frames out of the picture
            "physics-fall-through_v2": ("needs-review", 0, 0, 2),
        })

    def test_the_sinking_bug_reads_as_the_patch_is_written(self):
        reason = self.paired()["sinking_v2"]["reason"]
        self.assertIn("first frame 0: above 3 against 29 unchanged; below 56 against 30 unchanged", reason)

    def test_the_tolerance_sits_between_the_same_robot_and_the_bugs(self):
        # The same robot in the same place differs by 5 px once (missing-texture, frame 70, the width).
        self.assertEqual(self.paired(tolerance=4.9)["missing-texture_v1"]["out"], 1)
        self.assertEqual(self.paired(tolerance=5)["missing-texture_v1"]["out"], 0)
        # The sinking bug moves two measures by 25.5 px or more in every frame.
        self.assertEqual(self.paired(tolerance=25)["sinking_v2"]["out"], 13)
        self.assertLess(self.paired(tolerance=26)["sinking_v2"]["out"], 13)

    def test_at_the_origin_pairs_inherit_the_unsteady_clean_answers(self):
        # Clean frame 60 at the origin is a 19 px part of the robot; missing-texture got the whole robot.
        got = self.paired(AT_ORIGIN)
        self.assertEqual((got["missing-texture_v1"]["result"], got["missing-texture_v1"]["out"]), ("fail", 1))
        self.assertEqual(got["sinking_v2"]["out"], 13)

    def test_on_traversal_the_first_slip_cancels_and_another_frame_is_a_new_false_alarm(self):
        # The run the pairs were built for (November 12, 2026). Frame 20, the robot and the trunk as one
        # object: 107.5 px tall in the clean game and 106.5 in the harmless change, so it agrees. Frame
        # 100, the robot touching an enemy: the clean game got the robot alone and the harmless change
        # got robot and enemy as one object, at confidence 0.69 and 0.66. Nothing near the robot differs
        # between the two pictures. This test holds that fault in view; it changes when the probe does.
        got = self.paired(ON_TRAVERSAL)
        self.assertEqual({n: (r["result"], r["out"], r["judged"], r["moved"]) for n, r in got.items()}, {
            "missing-texture_v1": ("fail", 1, 13, 0), "layering_v1": ("fail", 8, 13, 0), "sinking_v2": ("fail", 13, 13, 0)})
        harmless = {f["frame"]: f for f in got["missing-texture_v1"]["frames"]}
        self.assertEqual(harmless[20]["state"], "in")
        self.assertEqual(harmless[100]["why"], ["width 113 against 58.5 unchanged", "height 91 against 60.5 unchanged",
                                               "below 59 against 28 unchanged"])
        report = rule.load_report(ON_TRAVERSAL)
        rows = {r["run"]: {f["frame"]: f for f in r["frames"]} for r in report["runs"]}
        self.assertEqual((rows["clean"][20]["worldSize"][1], rows["missing-texture_v1"][20]["worldSize"][1]), (107.5, 106.5))
        self.assertEqual((rows["clean"][100]["score"], rows["missing-texture_v1"][100]["score"]), (0.69140625, 0.66015625))
        self.assertEqual({r["route"]["name"] for r in report["runs"]}, {"traversal"})

    def test_asked_with_a_box_the_harmless_change_passes_and_both_false_alarms_are_gone(self):
        # Run 43335151089, November 12, 2026: the same four runs on traversal, asked with a box of
        # 48 x 68 game px around the robot's body and not with a point.
        got = self.paired(BOXED)
        self.assertEqual({n: (r["result"], r["out"], r["judged"]) for n, r in got.items()}, {
            "missing-texture_v1": ("pass", 0, 13), "layering_v1": ("fail", 7, 13), "sinking_v2": ("fail", 13, 13)})
        rows = {r["run"]: {f["frame"]: f for f in r["frames"]} for r in rule.load_report(BOXED)["runs"]}
        # Frame 20, where a point got the robot and a tree trunk as one object 107.5 px tall:
        self.assertEqual((rows["clean"][20]["worldSize"], rows["missing-texture_v1"][20]["worldSize"]), ([48.5, 62.5], [48.5, 62.5]))
        # Frame 100, where a point got the robot in one game and robot and enemy in the other:
        self.assertEqual((rows["clean"][100]["worldSize"], rows["missing-texture_v1"][100]["worldSize"]), ([57.5, 60.5], [57.5, 60.5]))

    def test_asked_with_a_box_the_confidence_tells_the_bugs_from_the_clean_game(self):
        rows = {r["run"]: {f["frame"]: f for f in r["frames"]} for r in rule.load_report(BOXED)["runs"]}
        clean = [f["score"] for f in rows["clean"].values()] + [f["score"] for f in rows["missing-texture_v1"].values()]
        self.assertGreaterEqual(min(clean), 0.86)                               # 26 clean-looking frames
        self.assertLessEqual(max(f["score"] for f in rows["sinking_v2"].values()), 0.70)      # all 13
        # The robot behind the level: under 0.63 in the 7 frames it is hidden in, as the clean game in the other 6.
        hidden = sorted(n for n, f in rows["layering_v1"].items() if f["score"] < 0.8)
        self.assertEqual(hidden, [0, 10, 20, 70, 100, 110, 119])
        self.assertLessEqual(max(rows["layering_v1"][n]["score"] for n in hidden), 0.63)
        self.assertGreaterEqual(min(f["score"] for n, f in rows["layering_v1"].items() if n not in hidden), 0.91)
        # By size alone (no fall in confidence allowed for), a box misses frames a point did not:
        by_size = {n: rule.pair(rule.load_run(BOXED, "clean")[1], rule.load_run(BOXED, n)[1], drop=1.0)["out"]
                   for n in ("layering_v1", "sinking_v2")}
        self.assertEqual(by_size, {"layering_v1": 6, "sinking_v2": 12})

    def test_a_harmless_change_never_lowered_the_confidence_by_more_than_0_031(self):
        worst = 0.0
        for path, names in ((MID_BODY, ("missing-texture_v1", "missing-texture_v2")), (ON_TRAVERSAL, ("missing-texture_v1",)),
                            (BOXED, ("missing-texture_v1",))):
            report = rule.load_report(path)
            runs = {r["run"]: {f["frame"]: f for f in r["frames"]} for r in report["runs"]}
            for name in names:
                for n, f in runs[name].items():
                    worst = max(worst, runs["clean"][n]["score"] - f["score"])
        self.assertEqual(round(worst, 5), 0.03125)
        self.assertLess(worst, rule.DEFAULT_DROP)

    def test_other_routes_clean_runs_are_refused_not_judged(self):
        _, clean = rule.load_run(MID_BODY, "clean")
        for run in rule.load_report(OTHER_CLEAN)["runs"]:
            with self.subTest(run=run["run"]):
                got = rule.pair(clean, run)
                self.assertEqual((got["result"], got["judged"]), ("needs-review", 0))
                self.assertIn("a different route", got["reason"])

    def test_the_slip_lasts_nine_frames_and_the_same_frame_asked_twice_agrees_with_itself(self):
        # Why neighbours cannot tell a slip from a bug: frames 16 to 24 of clean traversal are all out
        # of the smoke route's clean range, the box growing from 69 to 140.5 px tall.
        report, clean = rule.load_run(MID_BODY, "clean")
        cal = rule.calibrate(clean, rule.DEFAULT_PAD, report["lift"])
        near = rule.load_report(NEAR_THE_SLIP)["runs"][0]
        states = {f["frame"]: f["state"] for f in rule.judge(near, cal)["frames"]}
        self.assertEqual([n for n, state in states.items() if state == "out"], list(range(16, 25)))
        self.assertEqual((states[15], states[25]), ("in", "in"))
        heights = [r["worldSize"][1] for r in near["frames"] if 16 <= r["frame"] <= 24]
        self.assertEqual((heights[0], heights[-1], heights == sorted(heights)), (69.0, 140.5, True))
        # Frame 20 was asked in two runs. Paired, the second agrees with the first exactly.
        every_tenth = next(r for r in rule.load_report(OTHER_CLEAN)["runs"] if r["run"] == "clean-traversal")
        twenty = rule.pair(every_tenth, {"run": "again", "route": near["route"],
                                         "frames": [r for r in near["frames"] if r["frame"] == 20]}, tolerance=0)
        self.assertEqual((twenty["result"], twenty["judged"]), ("pass", 1))


class PredictionsTest(unittest.TestCase):
    """Four things written down before run 43337979278 existed (docs/sam.md, pull request #364), and how each fell.

    The box had been seen on one route and the 0.1 fall chosen after seeing it. This run asked the
    same question on the smoke route's nine runs and on the clean game on three other routes.
    """

    @classmethod
    def setUpClass(cls):
        report = rule.load_report(BOXED_HELD_OUT)
        cls.runs = {r["run"]: r for r in report["runs"]}
        cls.pairs = {n: rule.pair(cls.runs["clean"], r) for n, r in cls.runs.items() if n != "clean"}

    def scores(self, name):
        return {f["frame"]: f["score"] for f in self.runs[name]["frames"] if f.get("box")}

    def test_1_every_frame_of_the_four_clean_runs_has_a_confidence_of_0_8_or_more_held(self):
        clean = [s for n in ("clean", "clean-coins", "clean-combat", "clean-traversal") for s in self.scores(n).values()]
        self.assertEqual(len(clean), 49)
        self.assertGreaterEqual(min(clean), 0.8)
        self.assertEqual(round(min(clean), 3), 0.867)

    def test_2_both_missing_texture_runs_pass_the_pairs_held(self):
        for name in ("missing-texture_v1", "missing-texture_v2"):
            with self.subTest(run=name):
                self.assertEqual((self.pairs[name]["result"], self.pairs[name]["out"], self.pairs[name]["judged"]), ("pass", 0, 13))
        # And with room: the confidence fell by 0.008 at most where 0.1 is allowed,
        # and rose by 0.023 at most (frame 60, both runs).
        falls = [self.scores("clean")[n] - s for name in ("missing-texture_v1", "missing-texture_v2") for n, s in self.scores(name).items()]
        self.assertLess(max(falls), 0.01)
        self.assertLess(max(-f for f in falls), 0.03)

    def test_3_sinking_v2_fails_the_pairs_in_every_compared_frame_held(self):
        got = self.pairs["sinking_v2"]
        self.assertEqual((got["result"], got["out"], got["judged"]), ("fail", 13, 13))

    def test_4_both_layering_runs_fail_held_but_not_every_frame_that_differs_is_under_0_7(self):
        for name in ("layering_v1", "layering_v2"):
            with self.subTest(run=name):
                got = self.pairs[name]
                self.assertEqual((got["result"], got["out"], got["judged"]), ("fail", 8, 13))
                differing = {f["frame"]: self.scores(name)[f["frame"]] for f in got["frames"] if f["state"] == "out"}
                # The half that fell: frame 30, the robot half hidden behind a coin, at 0.82.
                self.assertEqual({n: round(s, 2) for n, s in differing.items() if s >= 0.7}, {30: 0.82})
                # It differs all the same: 13.5 px narrower than the clean game's, and 0.102 less sure
                # (0.9258 against 0.8242), which is over the 0.1 allowed by a hair. The size is what holds it.
                why = next(f["why"] for f in got["frames"] if f["frame"] == 30)
                self.assertIn("width 33 against 46.5 unchanged", why)
                self.assertIn("confidence 0.82 against 0.93 unchanged", why)

    def test_a_floor_on_the_confidence_alone_would_have_been_wrong(self):
        # One frame of the sinking bug is at 0.72 and one of layering at 0.82: no floor between the
        # clean game's 0.867 and those leaves much room. The fall against the same frame does.
        self.assertEqual(round(max(self.scores("sinking_v2").values()), 2), 0.72)
        bug_falls = [self.scores("clean")[f["frame"]] - self.scores(n)[f["frame"]]
                     for n in ("sinking_v2", "layering_v1") for f in self.pairs[n]["frames"] if f["state"] == "out"]
        self.assertEqual(round(min(bug_falls), 4), 0.1016)          # frame 30 of layering: a hair over the 0.1 allowed

    def test_the_other_routes_clean_runs_are_not_paired_with_the_smoke_route(self):
        for name in ("clean-coins", "clean-combat", "clean-traversal"):
            self.assertEqual((self.pairs[name]["result"], self.pairs[name]["judged"]), ("needs-review", 0))

    def test_the_bugs_the_engine_already_shows_are_left_to_it(self):
        self.assertEqual((self.pairs["sinking_v1"]["result"], self.pairs["sinking_v1"]["moved"]), ("needs-review", 13))
        self.assertEqual((self.pairs["physics-fall-through_v1"]["result"], self.pairs["physics-fall-through_v1"]["moved"]), ("needs-review", 2))


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

    def test_pairs_print_their_own_table_and_leave_their_own_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = self.run_main(["--pair", f"{MID_BODY}:clean", "--judge", MID_BODY, OTHER_CLEAN, "--out", tmp],
                                         {"GITHUB_ACTIONS": "true"})
            self.assertEqual(code, 0)
            page = (Path(tmp) / "anchor-pairs.md").read_text(encoding="utf-8")
            doc = json.loads((Path(tmp) / "anchor-pairs.json").read_text(encoding="utf-8"))
        self.assertIn("Unchanged game: `clean`. Tolerance 6 game px, confidence may fall by 0.1, point 14 px above the origin.", page)
        self.assertIn("| sinking_v2 | fail | 13 | 13 | 0 | 0 | 0 | 0 |", page)
        self.assertIn("| clean-combat | needs-review | 0 | 0 | 0 | 0 | 0 | 0 | a different route (combat against smoke)", page)
        self.assertNotIn("| clean |", page)                       # the unchanged game is not paired with itself
        self.assertEqual((doc["base"], doc["tolerance"], doc["drop"], doc["box"], len(doc["results"])), ("clean", 6.0, 0.1, None, 11))
        self.assertIn("::notice title=Anchored pairs sinking_v2::fail: 13 of 13 compared frames differ", out)

    def test_pairs_asked_at_another_point_are_not_compared_and_one_way_must_be_chosen(self):
        code, _, err = self.run_main(["--pair", f"{MID_BODY}:clean", "--judge", AT_ORIGIN])
        self.assertEqual(code, 2)
        self.assertIn("cannot be compared", err)
        with self.assertRaises(SystemExit):
            self.run_main(["--judge", MID_BODY])
        with self.assertRaises(SystemExit):
            self.run_main(["--pair", f"{MID_BODY}:clean", "--calibrate", f"{MID_BODY}:clean", "--judge", MID_BODY])

    def test_answers_to_a_point_and_to_a_box_are_not_compared(self):
        with tempfile.TemporaryDirectory() as tmp:
            boxed = Path(tmp) / "boxed.json"
            doc = json.loads(MID_BODY.read_text(encoding="utf-8"))
            doc["box"] = [48.0, 68.0]
            boxed.write_text(json.dumps(doc), encoding="utf-8")
            for how in ("--pair", "--calibrate"):
                with self.subTest(how=how):
                    code, _, err = self.run_main([how, f"{MID_BODY}:clean", "--judge", boxed])
                    self.assertEqual(code, 2)
                    self.assertIn("a box of 48 x 68 and the other report with a point", err)
            code, _, _ = self.run_main(["--pair", f"{boxed}:clean", "--judge", boxed])
            self.assertEqual(code, 0)

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
        self.assertIn("for page in anchor-pairs.md anchor-rule.md anchor.md probe.md; do", self.job)

    def test_the_pairs_follow_the_range_rule_and_cannot_fail_the_step_either(self):
        ruled = self.job.index("python -m agents.anchor_rule --calibrate runs/sam-probe/anchor.json:clean")
        paired = self.job.index("python -m agents.anchor_rule --pair runs/sam-probe/anchor.json:clean")
        self.assertLess(ruled, paired)
        self.assertIn('|| echo "::warning title=Anchored pairs::', self.job[paired:paired + 400])

    def test_another_route_for_the_seeded_runs_is_a_route_name_that_exists_and_no_key_is_near_it(self):
        step = self.job.split("- name: Render the clean game and every seeded bug", 1)[1].split("\n      - name:", 1)[0]
        self.assertNotIn("secrets.", step)
        self.assertIn('[[ "$ROUTE" =~ ^[a-z][a-z0-9-]*$ ]]', step)
        self.assertIn('[[ -f "harness/routes/$ROUTE.json" ]]', step)
        self.assertIn('python -m harness.check_seeded --route "harness/routes/$ROUTE.json" --out runs/seeded', step)
        self.assertIn("python -m harness.check_seeded --out runs/seeded\n", step)       # no route given: as before


if __name__ == "__main__":
    unittest.main()
