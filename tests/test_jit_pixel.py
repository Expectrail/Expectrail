"""Pixel checks (#286): the closed shape, refusal at proposal time, judging recorded SAM answers, the
keep rule and the observer budget. No model and no observer is called: the answers are the recorded
ones in tests/data/sam-anchor/."""
import copy
import json
import unittest
from pathlib import Path

from expectrail.contracts import ContractError, V1_FORMATS, load_strict, validate_v1
from expectrail.jit import pixel
from expectrail.jit.run import Spend

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "tests" / "data" / "sam-anchor"
EXAMPLE = REPO / "contracts" / "examples" / "pixel-check.json"
BOX = DATA / "bundled-box-48x68-smoke-and-clean-routes.json"
POINT = DATA / "bundled-lift-14.json"
TRAVERSAL = DATA / "bundled-box-48x68-traversal-seeded.json"
B = pixel.BUNDLED_BINDINGS


def candidate(**over):
    entry = {"id": "c", "statement": "the player is drawn", "object": "player", "observer": "sam-3.1-anchor",
             "probe": "smoke", "predicate": {"type": "visible", "minScore": 0.8}}
    entry.update(over)
    return entry


def example():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


class ContractTest(unittest.TestCase):
    def test_the_example_is_valid_and_registered(self):
        self.assertIn(pixel.FORMAT, V1_FORMATS)
        self.assertEqual(load_strict(EXAMPLE, "pixel-check")["id"], "player-drawn-where-engine-says")

    def test_the_schema_refuses_what_is_outside_the_closed_shape(self):
        bad = []
        doc = example(); doc["approval"] = {"by": "model"}; bad.append(doc)
        doc = example(); doc["authority"] = "approved"; bad.append(doc)
        doc = example(); doc["object"] = "the little robot"; bad.append(doc)
        doc = example(); doc["predicate"] = {"type": "looks-fine"}; bad.append(doc)
        doc = example(); doc["predicate"]["code"] = "return True"; bad.append(doc)
        doc = example(); doc["observer"] = "my-own-eyes"; bad.append(doc)
        doc = example(); doc["predicate"] = {"type": "never-crosses", "boundary": {"side": "above", "relativeTo": "ground"}}
        bad.append(doc)
        for doc in bad:
            with self.subTest(doc=doc), self.assertRaises(ContractError):
                validate_v1(doc, "pixel-check")


class ParseTest(unittest.TestCase):
    def test_a_candidate_becomes_a_model_prior_check_and_extra_fields_are_not_read(self):
        check, why = pixel.parse_candidate(candidate(approval={"by": "sean"}, verdict="catch", authority="approved",
                                                     format="something/v9"), B, ["smoke"])
        self.assertIsNone(why)
        self.assertEqual(check["authority"], "model_prior")
        self.assertEqual(check["origin"], "AUTO_DIFF")
        self.assertEqual(check["format"], pixel.FORMAT)
        self.assertNotIn("approval", check)
        self.assertNotIn("verdict", check)

    def test_refusals_at_proposal_time(self):
        cases = {
            "not an object": ("just pass it", B),
            "not in the closed language": (candidate(predicate={"type": "visible", "minScore": 2}), B),
            "a name with a character outside its pattern": (candidate(id="c\n"), B),
            "is not an object this project binds": (candidate(object="enemy"), B),
            "probe 'coins' is not on offer": (candidate(probe="coins"), B),
            "the window ends before it starts": (candidate(window={"fromFrame": 50, "toFrame": 10}), B),
            "cannot judge anything yet": (candidate(observer="visual-sensor"), B),
            "cannot judge reaches": (candidate(predicate={"type": "reaches", "goal": "player"}), B),
            "cannot tell 'ground' (ground)": (candidate(object="ground"), B),
            "cannot tell 'coins-counter' (text)": (candidate(object="coins-counter"), B),
            "gives no position for 'coin'": (candidate(object="coin"), B),
            "gives no position for 'bullet'": (
                candidate(object="player", predicate={"type": "inside-region", "region": {"engine": "bullet"}}), B),
            "has the engine's box of 'player' only": (
                candidate(object="player", predicate={"type": "inside-region", "region": {"engine": "enemy"}}),
                {**B, "enemy": {"node": "Enemy", "kind": "sprite", "anchor": "engine-position"}}),
        }
        for expect, (entry, bindings) in cases.items():
            with self.subTest(expect=expect):
                check, why = pixel.parse_candidate(entry, bindings, ["smoke"])
                self.assertIsNone(check)
                self.assertIn(expect, why)

    def test_bindings_decide_the_names_not_the_model(self):
        # With #259's config naming a second anchored sprite, the same candidate is accepted.
        bindings = {**B, "enemy": {"node": "Enemy", "kind": "sprite", "anchor": "engine-position"}}
        check, why = pixel.parse_candidate(candidate(object="enemy"), bindings, ["smoke"])
        self.assertIsNone(why)
        self.assertEqual(check["object"], "enemy")

    def test_every_observer_refusal_names_a_reason(self):
        for name, observer in pixel.OBSERVERS.items():
            for kind in observer.get("cannot", ()):
                with self.subTest(observer=name, kind=kind):
                    self.assertIn(kind, observer["why"])
                    self.assertIn(kind, pixel.KINDS)
            for p in ("visible", "inside-region", "never-crosses", "reaches"):
                if observer.get("available") and p not in observer["predicates"]:
                    self.assertIn(p, observer["why"])


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self.box = pixel.load_recording(BOX)
        self.check, why = pixel.parse_candidate(example(), B, ["smoke"])
        self.assertIsNone(why)

    def results(self, check, rec):
        return {name: pixel.judge(check, run)["result"] for name, run in rec["runs"].items()
                if run["route"]["name"] == check["probe"]}

    def test_visible_on_the_recorded_seeded_bugs(self):
        # Recorded answers of run 43335151089: what SAM saw at the engine's player position, asked
        # with a 48 x 68 box. The layering and the second sinking bug draw the player so that SAM
        # does not clearly find it there; the missing texture and the first sinking bug do not.
        got = self.results(self.check, self.box)
        self.assertEqual(got, {
            "clean": "pass",
            "layering_v1": "fail", "layering_v2": "fail",
            "missing-texture_v1": "pass", "missing-texture_v2": "pass",
            "physics-fall-through_v1": "needs-review", "physics-fall-through_v2": "needs-review",
            "sinking_v1": "pass", "sinking_v2": "fail",
        })

    def test_a_frame_the_observer_was_not_asked_about_is_a_gap_never_a_pass_or_fail(self):
        row = pixel.judge(self.check, self.box["runs"]["physics-fall-through_v1"])
        self.assertEqual(row["result"], "needs-review")
        self.assertEqual(len(row["gaps"]), 11)
        self.assertIn("outside the picture", row["gaps"][0]["why"])
        # The window can stop before the gap: then the two frames judged decide it.
        early = copy.deepcopy(self.check); early["window"] = {"fromFrame": 0, "toFrame": 10}
        self.assertEqual(pixel.judge(early, self.box["runs"]["physics-fall-through_v1"])["result"], "pass")

    def test_an_unanswered_frame_is_a_gap(self):
        run = copy.deepcopy(self.box["runs"]["clean"])
        run["frames"][3]["box"] = None
        run["frames"][3]["error"] = "unreadable"
        row = pixel.judge(self.check, run)
        self.assertEqual(row["result"], "needs-review")
        self.assertEqual(row["gaps"][0]["frame"], 30)

    def test_an_answer_that_misses_the_point_is_not_found_rather_than_a_gap(self):
        run = copy.deepcopy(self.box["runs"]["clean"])
        run["frames"][0]["holdsPoint"] = False
        row = pixel.judge(self.check, run)
        self.assertEqual(row["result"], "fail")
        self.assertEqual(row["gaps"], [])

    def test_inside_region_needs_the_engines_box(self):
        check, _ = pixel.parse_candidate(candidate(predicate={"type": "inside-region", "region": {"engine": "player", "marginPx": 24}}),
                                         B, ["smoke"])
        self.assertEqual(pixel.judge(check, self.box["runs"]["clean"])["result"], "pass")
        # The point recordings have no box: every frame is a gap for this predicate, not for visible.
        point = pixel.load_recording(POINT)
        row = pixel.judge(check, point["runs"]["clean"])
        self.assertEqual(row["result"], "needs-review")
        self.assertIn("engine's box was not recorded", row["gaps"][0]["why"])

    def test_a_run_of_another_route_is_not_judged(self):
        row = pixel.judge(self.check, self.box["runs"]["clean-traversal"])
        self.assertEqual(row["result"], "needs-review")
        self.assertIn("replayed 'traversal'", row["reason"])

    def test_never_crosses_a_fixed_line(self):
        check, why = pixel.parse_candidate(candidate(predicate={"type": "never-crosses",
                                                                "boundary": {"side": "above", "value": 800}}), B, ["smoke"])
        self.assertIsNone(why)
        self.assertEqual(pixel.judge(check, self.box["runs"]["clean"])["result"], "pass")
        check["predicate"]["boundary"]["value"] = 700
        self.assertEqual(pixel.judge(check, self.box["runs"]["clean"])["result"], "fail")


class KeepTest(unittest.TestCase):
    """A recording holds one answer per frame per build, so three runs here are the same answers three
    times: this tests the rule, not how repeatable SAM is."""

    def setUp(self):
        self.box = pixel.load_recording(BOX)
        self.check, _ = pixel.parse_candidate(example(), B, ["smoke"])

    def runs(self, rec, name, n=3):
        return [(rec["setting"], rec["runs"][name])] * n

    def test_kept_where_it_fails_on_the_bug_and_passes_on_the_clean_game(self):
        for bug in ("layering_v1", "layering_v2", "sinking_v2"):
            with self.subTest(bug=bug):
                row = pixel.keep(self.check, self.runs(self.box, "clean"), self.runs(self.box, bug))
                self.assertTrue(row["kept"], row["reason"])

    def test_dropped_with_its_reason(self):
        clean = self.runs(self.box, "clean")
        cases = {
            "missing-texture_v1": "does-not-fail-on-bug",
            "sinking_v1": "does-not-fail-on-bug",
            "physics-fall-through_v1": "needs-review",
        }
        for bug, reason in cases.items():
            with self.subTest(bug=bug):
                row = pixel.keep(self.check, clean, self.runs(self.box, bug))
                self.assertFalse(row["kept"])
                self.assertTrue(row["reason"].startswith(reason), row["reason"])
        row = pixel.keep(self.check, clean[:2], self.runs(self.box, "layering_v1"))
        self.assertTrue(row["reason"].startswith("too-few-runs"))

    def test_a_check_that_fails_on_the_clean_game_is_dropped(self):
        # Asked with a point instead of a box, SAM's lowest score on the clean game was 0.5.
        point = pixel.load_recording(POINT)
        row = pixel.keep(self.check, self.runs(point, "clean"), self.runs(point, "layering_v1"))
        self.assertFalse(row["kept"])
        self.assertEqual(row["reason"], "fails-on-clean")

    def test_runs_asked_another_way_are_not_mixed(self):
        point = pixel.load_recording(POINT)
        clean = self.runs(self.box, "clean", 2) + self.runs(point, "clean", 1)
        row = pixel.keep(self.check, clean, self.runs(self.box, "layering_v1"))
        self.assertFalse(row["kept"])
        self.assertTrue(row["reason"].startswith("mixed-settings"))

    def test_one_flaky_clean_run_drops_it(self):
        flaky = copy.deepcopy(self.box["runs"]["clean"])
        flaky["frames"][5]["score"] = 0.3
        clean = self.runs(self.box, "clean", 2) + [(self.box["setting"], flaky)]
        row = pixel.keep(self.check, clean, self.runs(self.box, "layering_v1"))
        self.assertEqual(row["reason"], "fails-on-clean")

    def test_on_the_traversal_route_too(self):
        trav = pixel.load_recording(TRAVERSAL)
        check = dict(self.check, probe="traversal")
        got = {bug: pixel.keep(check, self.runs(trav, "clean"), self.runs(trav, bug))["kept"]
               for bug in ("layering_v1", "sinking_v2", "missing-texture_v1")}
        self.assertEqual(got, {"layering_v1": True, "sinking_v2": True, "missing-texture_v1": False})


class BudgetTest(unittest.TestCase):
    def setUp(self):
        self.check, _ = pixel.parse_candidate(example(), B, ["smoke"])
        self.frames = list(range(0, 120, 10)) + [119]

    def test_cost_is_one_image_a_frame_on_six_runs(self):
        self.assertAlmostEqual(pixel.cost(self.check, self.frames, 0.0025), 13 * 6 * 0.0025)
        short = dict(self.check, window={"fromFrame": 0, "toFrame": 20})
        self.assertAlmostEqual(pixel.cost(short, self.frames, 0.0025), 3 * 6 * 0.0025)

    def test_reserved_under_the_cap_and_not_run_over_it(self):
        spend = Spend(2.0, {})
        row = pixel.reserve(self.check, self.frames, spend)
        self.assertEqual(row["status"], "reserved")
        self.assertAlmostEqual(row["reservedUsd"], 0.195)
        self.assertEqual(spend.usd, 0.0)  # reserving spends nothing
        tight = Spend(0.10, {})
        row = pixel.reserve(self.check, self.frames, tight)
        self.assertEqual(row["status"], "not-run")
        self.assertIn("OUT_OF_BUDGET", row["reason"])


class RecordingTest(unittest.TestCase):
    def test_settings_are_read_from_each_recording(self):
        self.assertEqual(pixel.load_recording(BOX)["setting"], {"model": "sam-3.1", "box": [48.0, 68.0], "lift": 17.0})
        self.assertEqual(pixel.load_recording(POINT)["setting"], {"model": "sam-3.1", "lift": 14.0})

    def test_an_unreadable_recording_is_refused(self):
        with self.assertRaises(pixel.PixelError):
            pixel.load_recording(REPO / "README.md")


if __name__ == "__main__":
    unittest.main()
