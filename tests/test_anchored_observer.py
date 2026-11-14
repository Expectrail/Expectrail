"""The anchored visual observer for games Expectrail did not write (#330).

No live Godot and no live model. The replays are stand-ins that log the player's body box, the
camera and the ground line as the harness does, with real PNG frames. The models are stand-ins too,
answering ``segment_in`` directly:

- ``Sees``:  answers with the drawn player (a 16 x 16 sprite at the engine's place), whatever box it
  was asked with: the model the rules are meant to let in.
- ``Echo``:  answers with the box it was asked with: a model that only repeats the question.
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


def make_run(root: Path, *, fall: bool = False, frames: int = 120, seed: int = 0) -> dict:
    """A replay whose player stands on the ground at x = 40 + frame (or falls through it, ``fall``)."""
    rows = []
    for t in range(frames * 2):
        n = t // 2
        x = 40.0 + n
        bottom = GROUND_TOP + (3.0 * n if fall else 0.0)
        rows.append({"tick": t, "player": [x, bottom - SPRITE / 2], "onFloor": not fall,
                     "ground": float(GROUND_TOP), "view": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
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
        n = int(Path(png).stem[1:])
        x0, y0, x1, y1 = self.rows[2 * n]["body"]   # the sprite is drawn exactly where the engine says
        return [x0, y0, x1, y1]


class Sees(Stand):
    def segment_in(self, png, boxes):
        self.calls += 1
        return [{"box": self.drawn(png), "score": 0.93} for _ in boxes]


class Echo(Stand):
    def segment_in(self, png, boxes):
        self.calls += 1
        return [{"box": [float(v) for v in b], "score": 0.9} for b in boxes]


class Blind(Stand):
    def segment_in(self, png, boxes):
        self.calls += 1
        return [None for _ in boxes]


class Broke(Stand):
    def segment_in(self, png, boxes):
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
        self.assertEqual(client.calls, 26)   # 13 frames of 120 (every tenth and the last), asked twice
        an.check_calibration(doc)

    def test_a_model_that_echoes_the_question_is_not_enabled(self):
        doc = an.calibrate(GAME, self.run, Echo(self.run))
        self.assertFalse(doc["enabled"])
        self.assertEqual(doc["rates"]["found"], 1.0)
        self.assertEqual(doc["rates"]["stable"], 0.0)
        self.assertTrue(any("twice as large" in w for w in doc["why"]))

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
