"""The replay judges pixel checks (#286): under the pixel setting, ``run.generate`` replays a pixel check's
probe with frames on the clean game, the bug build and the candidate, asks the observer it is given about
every run, keeps the check by the keep rule, and writes the rows in the run record's ``pixelChecks``.

Offline: the simulated game (tests/jit_fixtures.py) and recorded SAM answers (tests/data/sam-anchor/). The
observer here is a test double. It answers with SAM's recorded answers on the bundled game's smoke route
(run 43337979278), chosen by the build the replay was of, and stamps them with the replayed probe's name,
because no SAM answer exists for a bench probe yet. So these tests check the plumbing and the rules, not
SAM on these probes, and three "runs" are the same recorded answers three times."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from expectrail.contracts import ContractError, load_strict, validate_v1
from expectrail.jit import cli, intent as intent_mod
from expectrail.jit import offer as offer_mod
from expectrail.jit import pixel
from expectrail.jit.run import from_base_alone, generate
from tests.jit_fixtures import GOOD_CHECK, PROFILE, Case, JitGame, Transport, reply

REPO = Path(__file__).resolve().parents[1]
BOX = REPO / "tests" / "data" / "sam-anchor" / "bundled-box-48x68-smoke-and-clean-routes.json"
EXAMPLE = REPO / "contracts" / "examples" / "jit-run-pixel.json"
PX = offer_mod.PIXEL
REPORT = "The player is drawn behind the scenery."
PROBE = "hold-right"
DRAWN = {"id": "player-drawn", "statement": "On hold-right the player is drawn where the engine puts it.",
         "object": "player", "observer": "sam-3.1-anchor", "probe": PROBE,
         "predicate": {"type": "visible", "minScore": 0.8}}


class RecordedSam:
    """Test double for an observer. ``builds`` maps the replay's build ("pixel-reference", "pixel-base",
    "pixel-candidate") to a run name in the recording."""

    name = "sam-3.1-anchor"

    def __init__(self, builds: dict, recording=BOX, images: int = 0, setting_for=None):
        doc = json.loads(Path(recording).read_text(encoding="utf-8"))
        self.setting = pixel.setting_of(doc)
        self.runs = {r["run"]: r for r in doc["runs"]}
        self.builds, self.images, self.setting_for = builds, images, setting_for
        self.asked: list[str] = []

    def frames(self, route):
        return list(self.runs["clean"]["framesProbed"])

    def __call__(self, run_dir, route):
        build = Path(run_dir).parent.name
        self.asked.append(build)
        run = copy.deepcopy(self.runs[self.builds[build]])
        run["route"] = {"name": route["name"]}   # the stamp: see the module docstring
        setting = self.setting_for(build) if self.setting_for else self.setting
        return {"setting": setting, "run": run, "images": self.images}


def model(pixel_checks, candidates=(), offer=PX, candidate=intent_mod.SHOWN):
    t = Transport(reply({"candidates": list(candidates), "pixelChecks": list(pixel_checks)}))
    return intent_mod.spark_intent(transport=t, offer=offer, candidate=candidate)


def run(case: Case, fix: str = "fix-wrong", *, checks=(DRAWN,), candidates=(), observer="default",
        base=("air-jump",), offer=PX, frame_runner="default", candidate=intent_mod.SHOWN, **kw):
    if observer == "default":
        observer = RecordedSam({"pixel-reference": "clean", "pixel-base": "layering_v1",
                                "pixel-candidate": "layering_v1" if fix == "fix-wrong" else "clean"})
    game = JitGame()
    return generate(PROFILE, REPORT, case.patch(fix), [case.patch(b) for b in base], case.dir / f"out-{fix}",
                    runner=game, intent=model(checks, candidates, offer, candidate), variants_fn=case.variants(),
                    observer=observer, frame_runner=game if frame_runner == "default" else frame_runner,
                    offer=offer, candidate_to_model=candidate, clock=lambda: 0.0, **kw)


class TheReplayJudgesPixelChecks(unittest.TestCase):
    def test_kept_where_it_fails_on_the_bug_and_a_wrong_fix_is_caught(self):
        doc = run(Case(), "fix-wrong")
        validate_v1(doc, "jit-run")
        self.assertEqual(doc["status"], "complete", doc["reason"])
        self.assertEqual(doc["settings"]["offer"], PX)
        [row] = doc["pixelChecks"]
        self.assertEqual(row["check"]["id"], "jit-px-player-drawn")
        self.assertEqual((row["status"], row["outcome"]), ("kept", "catch"))
        self.assertEqual(row["clean"], ["pass"] * 3)
        self.assertEqual(row["bug"], ["fail"] * 3)
        self.assertEqual(row["candidate"], ["fail"] * 3)
        self.assertEqual(row["setting"], {"model": "sam-3.1", "box": [48.0, 68.0], "lift": 17.0})
        self.assertIn(PROBE, [p["id"] for p in doc["probes"]])
        self.assertEqual(doc["catches"], [])   # pixel rows are not trace catches
        self.assertEqual(from_base_alone(doc)["pixelReproducing"], ["jit-px-player-drawn"])
        self.assertEqual(from_base_alone(doc)["pixelFromBaseAlone"], [])

    def test_a_good_fix_is_not_caught(self):
        doc = run(Case(), "fix-good")
        [row] = doc["pixelChecks"]
        self.assertEqual((row["status"], row["outcome"]), ("kept", "no-catch"))
        self.assertEqual(row["candidate"], ["pass"] * 3)

    def test_replays_are_made_with_the_frame_runner_and_every_run_is_asked(self):
        case, frames = Case(), []
        game = JitGame()

        def frame_runner(route_path, run_dir, patches=()):
            frames.append(Path(run_dir).parent.name)
            return game(route_path, run_dir, patches=patches)

        sam = RecordedSam({"pixel-reference": "clean", "pixel-base": "layering_v1", "pixel-candidate": "layering_v1"})
        run(case, observer=sam, frame_runner=frame_runner)
        self.assertEqual(frames, ["pixel-reference"] * 3 + ["pixel-base"] * 3 + ["pixel-candidate"] * 3)
        self.assertEqual(sam.asked, frames)

    def test_withheld_checks_are_from_the_report_and_bug_build_alone(self):
        doc = run(Case(), candidate=intent_mod.WITHHELD)
        self.assertEqual(from_base_alone(doc)["pixelFromBaseAlone"], ["jit-px-player-drawn"])

    def test_trace_and_pixel_checks_together(self):
        doc = run(Case(), candidates=[GOOD_CHECK])
        self.assertEqual(doc["counts"]["proposed"], 1)
        self.assertEqual(doc["pixelChecks"][0]["outcome"], "catch")


class DroppedOrNotRun(unittest.TestCase):
    def row(self, **kw):
        doc = run(Case(), **kw)
        validate_v1(doc, "jit-run")
        self.assertEqual(doc["status"], "complete", doc["reason"])
        [row] = doc["pixelChecks"]
        self.assertEqual(from_base_alone(doc)["pixelReproducing"], [])
        return row

    def test_no_observer(self):
        row = self.row(observer=None)
        self.assertEqual((row["status"], row["outcome"]), ("not-run", "not-evaluated"))
        self.assertIn("no observer", row["reason"])
        self.assertEqual(row["clean"], [])

    def test_a_runner_but_no_frame_runner(self):
        self.assertIn("captures frames", self.row(frame_runner=None)["reason"])

    def test_an_observer_other_than_the_one_the_check_names(self):
        sam = RecordedSam({})
        sam.name = "visual-sensor"
        self.assertIn("this run's observer is visual-sensor", self.row(observer=sam)["reason"])

    def test_no_bug_build(self):
        self.assertIn("no bug build", self.row(base=())["reason"])

    def test_fails_on_the_clean_game(self):
        sam = RecordedSam({"pixel-reference": "layering_v1", "pixel-base": "layering_v1"})
        row = self.row(observer=sam)
        self.assertEqual((row["status"], row["reason"]), ("dropped", "fails-on-clean"))
        self.assertEqual(row["candidate"], [])

    def test_does_not_fail_on_the_bug(self):
        sam = RecordedSam({"pixel-reference": "clean", "pixel-base": "missing-texture_v1"})
        self.assertEqual(self.row(observer=sam)["reason"], "does-not-fail-on-bug")

    def test_a_gap_is_needs_review_and_never_kept(self):
        sam = RecordedSam({"pixel-reference": "clean", "pixel-base": "physics-fall-through_v1"})
        row = self.row(observer=sam)
        self.assertEqual(row["status"], "dropped")
        self.assertTrue(row["reason"].startswith("needs-review"), row["reason"])
        self.assertIn("needs-review", row["bug"])

    def test_the_observer_asked_another_way_on_the_bug_build(self):
        sam = RecordedSam({"pixel-reference": "clean", "pixel-base": "layering_v1"},
                          setting_for=lambda b: {"model": "sam-3.1", "lift": 14.0} if b == "pixel-base"
                          else {"model": "sam-3.1", "box": [48.0, 68.0], "lift": 17.0})
        row = self.row(observer=sam)
        self.assertTrue(row["reason"].startswith("mixed-settings"))
        self.assertIsNone(row["setting"])

    def test_a_malformed_observer_answer_drops_it(self):
        def bad(run_dir, route):
            return {"setting": {}, "run": {"frames": "all good"}, "images": 0}

        bad.name, bad.frames = "sam-3.1-anchor", lambda route: [0]
        row = self.row(observer=bad)
        self.assertEqual(row["status"], "dropped")
        self.assertIn("observer:", row["reason"])

    def test_an_observer_that_fails_drops_it(self):
        def boom(run_dir, route):
            raise TimeoutError("no answer")

        boom.name, boom.frames = "sam-3.1-anchor", lambda route: [0]
        self.assertIn("the observer failed: TimeoutError", self.row(observer=boom)["reason"])

    def test_over_the_budget_it_is_not_run_and_the_trace_checks_stand(self):
        sam = RecordedSam({})
        sam.frames = lambda route: list(range(100000))
        doc = run(Case(), observer=sam, candidates=[GOOD_CHECK])
        self.assertEqual(doc["status"], "complete", doc["reason"])
        self.assertEqual(doc["counts"]["proposed"], 1)
        [row] = doc["pixelChecks"]
        self.assertEqual(row["status"], "not-run")
        self.assertIn("OUT_OF_BUDGET", row["reason"])
        self.assertEqual(sam.asked, [])


class Spend(unittest.TestCase):
    def test_images_the_observer_sent_are_charged(self):
        sam = RecordedSam({"pixel-reference": "clean", "pixel-base": "layering_v1", "pixel-candidate": "clean"},
                          images=13)
        doc = run(Case(), "fix-good", observer=sam)
        self.assertEqual(doc["spend"]["samImages"], 13 * 9)
        self.assertAlmostEqual(doc["spend"]["samUsd"], round(13 * 9 * 0.0025, 4))

    def test_recorded_answers_cost_nothing_and_the_reservation_is_said(self):
        doc = run(Case())
        self.assertEqual(doc["spend"]["samImages"], 0)
        self.assertAlmostEqual(doc["pixelChecks"][0]["reservedUsd"], round(13 * 9 * 0.0025, 4))


class TheRecordAndItsReader(unittest.TestCase):
    def test_keeping_is_read_from_the_runs_not_the_status(self):
        doc = run(Case())
        edited = copy.deepcopy(doc)
        edited["pixelChecks"][0]["clean"][1] = "fail"
        self.assertEqual(from_base_alone(edited)["pixelReproducing"], [])
        dropped = run(Case(), observer=RecordedSam({"pixel-reference": "layering_v1", "pixel-base": "layering_v1"}))
        dropped["pixelChecks"][0]["status"] = "kept"
        self.assertEqual(from_base_alone(dropped)["pixelReproducing"], [])
        mixed = copy.deepcopy(doc)
        mixed["pixelChecks"][0]["setting"] = None
        self.assertEqual(from_base_alone(mixed)["pixelReproducing"], [])

    def test_a_row_whose_check_is_not_a_pixel_check_is_refused(self):
        doc = run(Case())
        doc["pixelChecks"][0]["check"]["object"] = "the little robot"
        with self.assertRaises(ContractError):
            from_base_alone(doc)

    def test_the_schema_refuses_an_approval_or_a_verdict_in_a_row(self):
        doc = run(Case())
        for field, value in (("approval", {"by": "model"}), ("verdict", "catch")):
            bad = copy.deepcopy(doc)
            bad["pixelChecks"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                validate_v1(bad, "jit-run")
        bad = copy.deepcopy(doc)
        bad["pixelChecks"][0]["check"]["authority"] = "approved"
        with self.assertRaises(ContractError):
            validate_v1(bad, "jit-run")

    def test_a_run_that_did_not_complete_keeps_nothing(self):
        doc = run(Case(), base=("air-jump", "crash"))
        self.assertEqual(doc["status"], "nothing-generated")
        self.assertEqual(from_base_alone(doc)["pixelReproducing"], [])
        for row in doc["pixelChecks"]:
            self.assertEqual(row["outcome"], "not-evaluated")

    def test_other_settings_write_no_pixel_rows(self):
        doc = run(Case(), offer=offer_mod.EVIDENCE, candidates=[GOOD_CHECK])
        self.assertNotIn("pixelChecks", doc)
        self.assertNotIn("pixelReproducing", from_base_alone(doc))

    def test_the_summary_shows_the_pixel_rows(self):
        text = cli.render(run(Case()))
        self.assertIn("Pixel checks (#286): 1 proposed, 1 pass on the clean game and fail on the bug build, "
                      "1 fail on the candidate", text)
        self.assertIn("| `jit-px-player-drawn` | sam-3.1-anchor | pass, pass, pass | fail, fail, fail |", text)

    def test_the_example_is_valid_and_reads_as_one_kept_pixel_check(self):
        doc = load_strict(EXAMPLE, "jit-run")
        self.assertEqual(doc["settings"]["offer"], PX)
        self.assertEqual(from_base_alone(doc)["pixelReproducing"], ["jit-px-player-drawn"])
        self.assertEqual(doc["pixelChecks"][0]["outcome"], "catch")


class Settings(unittest.TestCase):
    def test_a_revision_does_not_take_the_pixel_setting(self):
        with self.assertRaisesRegex(offer_mod.OfferError, "cannot be revised yet"):
            offer_mod.revisable(PX)
        for other in offer_mod.OFFERS:
            self.assertEqual(offer_mod.revisable(other), other)

    def test_the_command_line_run_and_the_score_still_do_not_name_it(self):
        self.assertNotIn(PX, offer_mod.OFFERS)
        score = json.loads((REPO / "contracts" / "repro-score.v1.schema.json").read_text(encoding="utf-8"))
        self.assertNotIn(PX, score["properties"]["offer"]["enum"])


if __name__ == "__main__":
    unittest.main()
