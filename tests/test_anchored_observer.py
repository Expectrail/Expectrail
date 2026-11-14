"""The anchored visual observer for games Expectrail did not write (#330).

No live Godot and no live model. The replays are stand-ins that log the player's body box, the
camera and the ground line as the harness does, with real PNG frames. The models are stand-ins too,
answering ``segment_at`` (a point question) directly:

- ``Sees``:  answers with the drawn player (a 16 x 16 sprite at the engine's place), wherever inside
  it the point was: the model the rules are meant to let in.
- ``Echo``:  answers with a player-sized box centred on the point it was asked about: a model that
  only repeats the question.
- ``Tiles``: answers with a 48 px region around the point (the tiles behind the player).
- ``Blind``: answers nothing.

These are not recordings of the live model. The live calibration of kinematic-character is a
person-dispatched run (#330); until it is recorded, nothing here says how the live model behaves.
"""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from agents.sam_observations import SamError
from expectrail import anchored as an
from expectrail.evaluator import evaluate
from expectrail.gate import record as rec
from expectrail.gate.verify import NoAnswer
from expectrail.recorded import RecordedClient, RecordingClient
from tests.test_sam import GROUND_TOP, H, W, png_bytes

SPRITE = 16.0
SPEC = {
    "format": "expectrail.test-spec/v0", "id": "player-stays-above-ground",
    "instruction": "The player never falls through the ground.",
    "objects": {"player": {"prompt": "blue robot"}, "ground": {"prompt": "grass-topped ground"}},
    "assertion": {"type": "never-crosses", "object": "player",
                  "boundary": {"relativeTo": "ground", "edge": "top", "side": "above", "tolerancePx": 20}},
    "window": {"fromFrame": 0, "toFrame": 119},
}
GAME = {"name": "kinematic-character", "commit": "b761b4cd5718a7118f2c95eb55f181d0a5f004f1"}


def make_run(root: Path, *, fall: bool = False, frames: int = 120, seed: int = 0, scale: float = 1.0,
             x0: float = 40.0, speed: float = 1.0, ty: float = 0.0) -> dict:
    """A replay whose player stands on the ground at x = x0 + speed * frame (or falls through it,
    ``fall``), drawn at ``scale`` frame pixels per game pixel, shifted ``ty`` frame pixels."""
    rows = []
    for t in range(frames * 2):
        n = t // 2
        x = x0 + speed * n
        bottom = GROUND_TOP + (3.0 * n if fall else 0.0)
        rows.append({"tick": t, "player": [x, bottom - SPRITE / 2], "onFloor": not fall,
                     "ground": float(GROUND_TOP), "view": [scale, 0.0, 0.0, scale, 0.0, ty],
                     "body": [x - SPRITE / 2, bottom - SPRITE, x + SPRITE / 2, bottom]})
    folder = root / f"frames-{seed}-{int(fall)}"
    folder.mkdir(parents=True)
    for n in range(frames):
        (folder / f"f{n:08d}.png").write_bytes(png_bytes(W, H, 9000 + seed * 1000 + n))
    return {"trace": {"physicsTicksPerSecond": 120, "rows": rows}, "framesDir": folder,
            "replaySha256": f"{seed:064x}"}


class Stand:
    model, provider, base = "sam-3.1", "stand-in", ""

    def __init__(self, run: dict):
        self.rows = run["trace"]["rows"]
        self.calls = 0

    def drawn(self, png: Path):
        from agents.observations import _frame_box

        row = self.rows[2 * int(Path(png).stem[1:])]
        return _frame_box(row["view"], row["body"])   # the sprite, drawn exactly where the engine says


class Sees(Stand):
    def segment_at(self, png, points):
        self.calls += 1
        return [{"box": self.drawn(png), "score": 0.93} for _ in points]


class Echo(Stand):
    def segment_at(self, png, points):
        self.calls += 1
        h = SPRITE / 2 * self.rows[0]["view"][0]   # player-sized, in frame pixels
        return [{"box": [x - h, y - h, x + h, y + h], "score": 0.9} for x, y in points]


class Tiles(Stand):
    def segment_at(self, png, points):
        self.calls += 1
        return [{"box": [x - 24.0, y - 24.0, x + 24.0, y + 24.0], "score": 0.9} for x, y in points]


class Blind(Stand):
    def segment_at(self, png, points):
        self.calls += 1
        return [None for _ in points]


class Broke(Stand):
    def segment_at(self, png, points):
        raise SamError("no credit", kind="credit")


class CalibrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.run = make_run(self.tmp)

    def test_a_model_that_sees_the_player_is_enabled(self):
        client = Sees(self.run)
        doc = an.calibrate(GAME, self.run, client)
        self.assertEqual(rec.errors(doc, an.calibration_schema()), [])
        self.assertTrue(doc["enabled"], doc["why"])
        self.assertEqual(doc["rates"], {"found": 1.0, "size": 1.0, "stable": 1.0})
        self.assertEqual(doc["drawnSize"], {"width": SPRITE, "height": SPRITE})
        self.assertEqual(client.calls, 13)   # 13 frames of 120 (every tenth and the last), both points in one request
        an.check_calibration(doc)

    def test_a_model_that_echoes_the_question_is_not_enabled(self):
        doc = an.calibrate(GAME, self.run, Echo(self.run))
        self.assertFalse(doc["enabled"])
        self.assertEqual(doc["rates"]["found"], 1.0)
        self.assertEqual(doc["rates"]["size"], 1.0)     # player-sized, so only the nudge can tell
        self.assertEqual(doc["rates"]["stable"], 0.0)   # its box moved with the point
        self.assertTrue(any("nudged" in w for w in doc["why"]))

    def test_an_echo_is_refused_and_a_seeing_model_enabled_at_scales_that_are_not_whole(self):
        # The guard's probe on #452: with the nudge rounded to whole frame pixels and the shift compared
        # in game pixels, an echo passed at scale 1.1. The player stays inside the 160 x 96 frame.
        for scale in (1.1, 1.5, 2.0):
            with self.subTest(scale=scale):
                run = make_run(self.tmp, seed=int(scale * 10), scale=scale, x0=20.0, speed=0.3,
                               ty=-(GROUND_TOP * scale - 70))
                echo = an.calibrate(GAME, run, Echo(run))
                self.assertEqual(echo["frames"]["asked"], echo["frames"]["listed"])
                self.assertFalse(echo["enabled"])
                self.assertEqual(echo["rates"]["stable"], 0.0)
                sees = an.calibrate(GAME, run, Sees(run))
                self.assertTrue(sees["enabled"], sees["why"])

    def test_a_model_that_answers_with_the_tiles_is_not_enabled(self):
        doc = an.calibrate(GAME, self.run, Tiles(self.run))
        self.assertFalse(doc["enabled"])
        self.assertEqual(doc["rates"]["size"], 0.0)

    def test_a_small_sprite_over_its_collision_box_agrees_within_the_floor(self):
        # The first live calibration: answers of 17 to 18 px for a 14 px collision box (#330).
        self.assertTrue(an._close(18.0, 14.0, 0.25, 4.0))
        self.assertFalse(an._close(18.0, 14.0, 0.25))
        self.assertFalse(an._close(30.0, 14.0, 0.25, 4.0))

    def test_a_blind_model_is_not_enabled(self):
        doc = an.calibrate(GAME, self.run, Blind(self.run))
        self.assertFalse(doc["enabled"])
        self.assertEqual(doc["frames"]["found"], 0)

    def test_too_few_frames_is_not_enabled(self):
        run = make_run(self.tmp, frames=30, seed=1)
        doc = an.calibrate(GAME, run, Sees(run))
        self.assertFalse(doc["enabled"])
        self.assertTrue(any("at least 8" in w for w in doc["why"]))

    def test_a_model_that_stops_is_no_calibration(self):
        with self.assertRaises(NoAnswer):
            an.calibrate(GAME, self.run, Broke(self.run))

    def test_a_hand_edited_verdict_is_refused(self):
        doc = an.calibrate(GAME, self.run, Blind(self.run))
        forged = copy.deepcopy(doc)
        forged["enabled"], forged["why"] = True, []
        with self.assertRaises(an.CalibrationError):
            an.check_calibration(forged)
        loose = copy.deepcopy(doc)
        loose["rules"]["found"] = 0.0
        with self.assertRaises(an.CalibrationError):
            an.check_calibration(loose)

    def test_the_example_is_a_usable_calibration(self):
        import json

        from expectrail import resources

        doc = json.loads((resources.ROOT / "contracts/examples/vision-calibration.v1.json").read_text())
        self.assertTrue(an.check_calibration(doc)["enabled"])


class LookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def observer(self, run, client=None):
        client = client or Sees(run)
        return an.AnchoredObserver(client, an.calibrate(GAME, run, client))

    def test_the_clean_game_passes_on_what_is_drawn(self):
        run = make_run(self.tmp)
        doc = self.observer(run).look(SPEC, run)
        self.assertEqual(doc["model"]["engineObjects"], ["ground"])
        self.assertNotIn("blue robot", str(doc["model"]["prompts"]))
        self.assertEqual(evaluate(SPEC, doc)["result"], "pass")

    def test_a_player_falling_through_the_floor_fails(self):
        clean = make_run(self.tmp)
        client = Sees(clean)
        observer = an.AnchoredObserver(client, an.calibrate(GAME, clean, client))
        broken = make_run(self.tmp, fall=True, seed=2)
        observer._client = Sees(broken)   # the same calibrated model, now asked about the broken replay
        self.assertEqual(evaluate(SPEC, observer.look(SPEC, broken))["result"], "fail")

    def test_a_player_not_drawn_is_needs_review_never_a_pass(self):
        run = make_run(self.tmp)
        observer = self.observer(run)
        observer._client = Blind(run)
        self.assertEqual(evaluate(SPEC, observer.look(SPEC, run))["result"], "needs-review")

    def test_a_game_that_is_not_calibrated_gets_no_visual_observer(self):
        run = make_run(self.tmp)
        observer = self.observer(run, Echo(run))
        for call in (observer.describe, observer.segmenter, lambda: observer.look(SPEC, run)):
            with self.assertRaises(NoAnswer) as caught:
                call()
            self.assertIn("not calibrated", str(caught.exception))

    def test_a_spec_naming_other_objects_is_not_answered(self):
        run = make_run(self.tmp)
        spec = copy.deepcopy(SPEC)
        spec["objects"]["coin"] = {"prompt": "coin"}
        with self.assertRaises(NoAnswer):
            self.observer(run).look(spec, run)

    def test_recorded_once_the_answers_replay_without_a_model(self):
        run = make_run(self.tmp)
        live = RecordingClient(Sees(run))
        calibration = an.calibrate(GAME, run, live)
        first = an.AnchoredObserver(live, calibration).look(SPEC, run)
        recording = live.recording(sample="kinematic-character", recorded_at="2026-11-14", run="local")
        replayed = an.AnchoredObserver(RecordedClient(recording), calibration).look(SPEC, run)
        self.assertEqual(replayed["frames"], first["frames"])
        self.assertEqual(an.calibrate(GAME, run, RecordedClient(recording))["rates"], calibration["rates"])
        other = make_run(self.tmp, seed=3)
        with self.assertRaises(NoAnswer):   # another picture is never answered from the recording
            an.AnchoredObserver(RecordedClient(recording), calibration).look(SPEC, other)


if __name__ == "__main__":
    unittest.main()
