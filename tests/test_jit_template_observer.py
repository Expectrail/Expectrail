"""The no-model sensor of #262 as the ``visual-sensor`` observer of pixel checks (#286).

Offline: synthetic replays (small PNG frames, a trace with the player's body box and the camera) and a
template bank calibrated from a clean one with agents/template_observations.py. No engine, no model, no
request. These show the observer reads the sensor's answers into the shape the pixel judge reads, the
replay checks it shares with SAM's observer, and the rule end to end through ``run.generate``; they say
nothing about how often the sensor is right on the bundled game's frames (docs/template-sensor-measurement.md).
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    from PIL import Image
except ModuleNotFoundError as exc:  # pragma: no cover - the CI image has Pillow
    if exc.name != "PIL":
        raise
    Image = None
try:
    import numpy  # noqa: F401 - the sensor's matcher needs it
except ModuleNotFoundError as exc:  # pragma: no cover
    if exc.name != "numpy":
        raise
    numpy = None

from expectrail.contracts import validate_v1
from expectrail.jit import intent as intent_mod
from expectrail.jit import offer as offer_mod
from expectrail.jit import pixel
from expectrail.jit.run import from_base_alone, generate
from tests.jit_fixtures import PROFILE, Case, JitGame

needs_pixels = unittest.skipIf(Image is None or numpy is None, "the template sensor needs Pillow and NumPy")

TREE = "a" * 64
SIZE = (96, 80)
AT = (40, 30)                       # where the player's box is on screen
BODY = [100.0, 584.0, 112.0, 600.0]  # the player's body box in the world, 12 x 16
CONFIG = dict(matchThreshold=0.9, searchMarginPx=8, stridePx=1, scales=[1.0], sampleSide=12)
PX = offer_mod.PIXEL
PROBE = "hold-right"


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sprite():
    rng = random.Random(286)
    image = Image.new("L", (12, 16))
    image.putdata([rng.randrange(20, 235) for _ in range(12 * 16)])
    return image


def picture(drawn: bool, at=AT):
    image = Image.new("L", SIZE, 17)
    if drawn:
        image.paste(sprite(), at)
    return image


def write_replay(run_dir, name: str, ticks: int, *, drawn=True, at=AT, screen=AT, patched=False, frames=None):
    """A replay of route ``name`` over ``ticks`` ticks at 120 a second, 60 frames a second: the player stands
    still, the camera puts its body box at ``screen``, and the frames draw the sprite at ``at`` (or not)."""
    run_dir = Path(run_dir)
    (run_dir / "frames").mkdir(parents=True, exist_ok=True)
    view = [1, 0, 0, 1, screen[0] - BODY[0], screen[1] - BODY[1]]
    trace = {"format": "expectrail.trace/v0", "ticks": ticks, "physicsTicksPerSecond": 120,
             "rows": [{"tick": t, "player": [106.0, 600.0], "body": list(BODY), "view": view} for t in range(ticks)]}
    (run_dir / "trace.json").write_text(json.dumps(trace), encoding="utf-8")
    count = ticks // 2
    hashes = []
    for n in range(count):
        path = run_dir / "frames" / f"f{n:08d}.png"
        drawn_here = drawn(n) if callable(drawn) else drawn
        picture(drawn_here, at).save(path)
        hashes.append(sha(path))
    if frames is not None:   # keep only these frames on disk, as a trimmed replay does
        for n in range(count):
            if n not in frames:
                (run_dir / "frames" / f"f{n:08d}.png").unlink()
    replay = {"format": "expectrail.replay/v0", "route": {"name": name, "sha256": "c" * 64},
              "game": {"tree": TREE, "patch": "bug.patch" if patched else None,
                       "patchSha256": "b" * 64 if patched else None},
              "capture": {"fps": 60, "physicsTicksPerSecond": 120, "frames": count},
              "trace": {"path": "trace.json", "sha256": sha(run_dir / "trace.json")}, "frameSha256": hashes}
    (run_dir / "replay.json").write_text(json.dumps(replay), encoding="utf-8")
    return run_dir


def check(**kw) -> dict:
    entry = {"id": "player-drawn", "statement": "The player is drawn where the engine puts it.", "object": "player",
             "observer": "visual-sensor", "probe": PROBE, "predicate": {"type": "visible", "minScore": 0.8}, **kw}
    doc, why = pixel.parse_candidate(entry, pixel.BUNDLED_BINDINGS, [PROBE])
    assert why is None, why
    doc["id"] = pixel.ID_PREFIX + doc["id"]
    return doc


@needs_pixels
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from agents import template_observations as sensor

        cls.tmp = Path(tempfile.mkdtemp(prefix="jit-sensor-"))
        clean = write_replay(cls.tmp / "calibration", "calibration", 6)
        cls.bank_path = cls.tmp / "bank.json"
        sensor.calibrate(clean, clean_tree=TREE, frames=[0], config=CONFIG, out=cls.bank_path)
        cls.bank = json.loads(cls.bank_path.read_text())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def observer(self, **kw):
        from expectrail.jit.template_observer import TemplateSensorObserver

        return TemplateSensorObserver(self.bank_path, **kw)

    def ask(self, name="r", ticks=60, observer=None, **kw):
        run_dir = write_replay(Path(tempfile.mkdtemp(dir=self.tmp)) / name, PROBE, ticks, **kw)
        return pixel.observe(observer or self.observer(), run_dir, {"name": PROBE, "ticks": ticks})


class WhatTheSensorSays(Base):
    def test_drawn_where_the_engine_puts_it_passes_with_no_image_charged(self):
        setting, run, images = self.ask()
        self.assertEqual(images, 0)
        self.assertEqual(setting["model"], "expectrail.template-ncc/v2")
        self.assertEqual(len(setting["bankSha256"]), 64)
        self.assertEqual(run["framesProbed"], [0, 10, 20, 29])   # SAM's plan: every 10th frame and the last
        self.assertEqual({f["status"] for f in run["frames"]}, {"matched"})
        self.assertTrue(all(f["holdsPoint"] for f in run["frames"]))
        verdict = pixel.judge(check(), run)
        self.assertEqual((verdict["result"], verdict["framesJudged"]), ("pass", 4))

    def test_not_drawn_is_an_observation_of_absence_and_fails(self):
        _, run, _ = self.ask(drawn=False)
        self.assertEqual({f["status"] for f in run["frames"]}, {"not-found"})
        self.assertTrue(all(f["absent"] and f["box"] is None for f in run["frames"]))
        verdict = pixel.judge(check(), run)
        self.assertEqual((verdict["result"], verdict["framesJudged"]), ("fail", 4))

    def test_drawn_elsewhere_is_not_seen_where_the_engine_puts_it(self):
        _, run, _ = self.ask(at=(48, 30))
        self.assertEqual({f["status"] for f in run["frames"]}, {"displaced"})
        self.assertFalse(any(f["holdsPoint"] for f in run["frames"]))
        self.assertEqual(pixel.judge(check(), run)["result"], "fail")

    def test_missing_on_one_frame_fails_from_that_frame(self):
        _, run, _ = self.ask(drawn=lambda n: n != 20)
        verdict = pixel.judge(check(), run)
        self.assertEqual((verdict["result"], verdict["firstFrame"]), ("fail", 20))

    def test_a_box_not_wholly_on_screen_is_a_gap_and_needs_review(self):
        _, run, _ = self.ask(screen=(-4, 30), at=(0, 30))
        self.assertTrue(all(not f["asked"] and f["status"] == "out-of-frame" for f in run["frames"]))
        verdict = pixel.judge(check(), run)
        self.assertEqual(verdict["result"], "needs-review")
        self.assertIn("out-of-frame", verdict["reason"])

    def test_inside_region_and_never_crosses(self):
        _, run, _ = self.ask()
        inside = check(predicate={"type": "inside-region", "region": {"engine": "player", "marginPx": 2}})
        self.assertEqual(pixel.judge(inside, run)["result"], "pass")
        below = check(predicate={"type": "never-crosses", "boundary": {"side": "below", "value": 20}})
        self.assertEqual(pixel.judge(below, run)["result"], "pass")   # the box's top is at 30
        above = check(predicate={"type": "never-crosses", "boundary": {"side": "above", "value": 20}})
        self.assertEqual(pixel.judge(above, run)["result"], "fail")   # its bottom is at 46
        _, gone, _ = self.ask(drawn=False)
        self.assertNotEqual(pixel.judge(inside, gone)["result"], "pass")

    def test_the_frame_plan_takes_every_and_first(self):
        _, run, _ = self.ask(observer=self.observer(every=5, first=12))
        self.assertEqual(run["framesProbed"], [0, 5, 10, 11])
        self.assertEqual(len(run["frames"]), 4)

    def test_a_trimmed_replay_with_the_planned_frames_is_read(self):
        _, run, _ = self.ask(frames={0, 10, 20, 29})
        self.assertEqual(pixel.judge(check(), run)["result"], "pass")


class TheKeepRule(Base):
    def test_kept_where_it_passes_on_clean_and_fails_on_the_bug(self):
        clean = [self.ask(f"clean-{n}")[:2] for n in range(3)]
        bug = [self.ask(f"bug-{n}", drawn=False, patched=True)[:2] for n in range(3)]
        row = pixel.keep(check(), clean, bug)
        self.assertTrue(row["kept"], row["reason"])

    def test_two_banks_are_two_settings_and_never_compared(self):
        from agents import template_observations as sensor

        other = self.tmp / "other-bank.json"
        if not other.exists():
            sensor.calibrate(self.tmp / "calibration", clean_tree=TREE, frames=[1], config=CONFIG, out=other)
        from expectrail.jit.template_observer import TemplateSensorObserver

        clean = [self.ask(f"c-{n}")[:2] for n in range(3)]
        bug = [self.ask(f"b-{n}", drawn=False, observer=TemplateSensorObserver(other))[:2] for n in range(3)]
        row = pixel.keep(check(), clean, bug)
        self.assertFalse(row["kept"])
        self.assertIn("setting", row["reason"])


class FailsClosed(Base):
    def run_dir(self, **kw):
        return write_replay(Path(tempfile.mkdtemp(dir=self.tmp)) / "r", PROBE, 60, **kw)

    def refused(self, run_dir, expect, route=None, **kw):
        with self.assertRaises(pixel.PixelError) as caught:
            pixel.observe(self.observer(), run_dir, route or {"name": PROBE, "ticks": 60}, **kw)
        self.assertIn(expect, str(caught.exception))

    def test_a_frame_that_is_not_the_replays_is_refused(self):
        run_dir = self.run_dir()
        picture(False).save(run_dir / "frames" / "f00000010.png")
        self.refused(run_dir, "frame 10 on disk is not the frame the replay recorded")

    def test_a_trace_that_is_not_the_replays_is_refused(self):
        run_dir = self.run_dir()
        trace = json.loads((run_dir / "trace.json").read_text())
        trace["rows"][21]["body"] = [0, 0, 12, 16]
        (run_dir / "trace.json").write_text(json.dumps(trace))
        self.refused(run_dir, "trace.json on disk is not the trace the replay recorded")

    def test_a_replay_of_another_route_is_refused(self):
        self.refused(self.run_dir(), "the replay is of 'hold-right'", route={"name": "hold-left", "ticks": 60})

    def test_a_planned_frame_missing_from_a_trimmed_replay_is_refused(self):
        self.refused(self.run_dir(frames={0, 10, 29}), "frame 20, which is asked about, is missing")

    def test_named_objects_and_no_player_are_refused(self):
        run_dir = self.run_dir()
        with self.assertRaises(pixel.PixelError) as caught:
            self.observer()(run_dir, {"name": PROBE, "ticks": 60}, objects=("enemy",))
        self.assertIn("not pointed at the boxes of enemy", str(caught.exception))
        with self.assertRaises(pixel.PixelError) as caught:
            self.observer()(run_dir, {"name": PROBE, "ticks": 60}, player=False)
        self.assertIn("would be asked about nothing", str(caught.exception))
        self.assertEqual(self.observer().most_images({"name": PROBE, "ticks": 60}), 0)

    def test_a_bank_that_is_not_whole_or_has_no_player_is_refused(self):
        from expectrail.jit.template_observer import TemplateSensorObserver

        edited = copy.deepcopy(self.bank)
        edited["templates"][0]["pixelsSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "the template bank cannot be used"):
            TemplateSensorObserver(edited)
        other = copy.deepcopy(self.bank)
        for t in other["templates"]:
            t["object"] = "coin"
        with self.assertRaisesRegex(ValueError, "no template of the player"):
            TemplateSensorObserver(other)
        with self.assertRaisesRegex(ValueError, "every is at most 60"):
            TemplateSensorObserver(self.bank, every=61)


class SensorFrames:
    """A frame runner for ``run.generate``: the simulated game's trace replay (tests/jit_fixtures.py), then
    the replay folder rewritten as a captured one, with the sprite drawn unless the build has the air-jump
    bug (standing in here for a defect that only shows on the screen)."""

    def __init__(self):
        self.game = JitGame()
        self.builds: list[str] = []

    def __call__(self, route_path, run_dir, patches=()):
        self.game(route_path, run_dir, patches=patches)
        route = json.loads(Path(route_path).read_text())
        stems = {Path(p).stem for p in patches}
        hidden = "air-jump" in stems and "fix-good" not in stems
        self.builds.append(Path(run_dir).parent.name)
        write_replay(run_dir, route["name"], route["ticks"], drawn=not hidden, patched=bool(patches))


def handing(checks):
    """An intent that hands the run these pixel checks and asks no model (a proposal made for the sensor is
    in tests/test_jit_propose_observer.py)."""
    def propose(report, patch_text, dmap, profile, probes, revision=None):
        return {"probes": [], "candidates": [], "diagnostics": [], "pixelChecks": copy.deepcopy(checks),
                "usage": {"model": "none", "promptTokens": 0, "completionTokens": 0}, "promptSha256": None}
    propose.model, propose.system, propose.offer, propose.candidate = "none", "", PX, intent_mod.SHOWN
    return propose


class EndToEnd(Base):
    def generate(self, fix: str, observer=None):
        # Kept on the test: the fixture removes its folder when the Case is dropped, and the
        # assertions below read files under `self.last_out` after this helper returns.
        case = self.case = Case()
        frames = SensorFrames()
        doc = generate(PROFILE, "The player is not drawn.", case.patch(fix), [case.patch("air-jump")],
                       case.dir / f"out-{fix}", runner=JitGame(), intent=handing([check()]),
                       variants_fn=case.variants(), observer=observer or self.observer(), frame_runner=frames,
                       offer=PX, clock=lambda: 0.0)
        self.last_out = case.dir / f"out-{fix}"
        return doc, frames

    def test_a_wrong_fix_is_caught_and_nothing_is_charged_for_the_observer(self):
        doc, frames = self.generate("fix-wrong")
        validate_v1(doc, "jit-run")
        self.assertEqual(doc["status"], "complete", doc["reason"])
        [row] = doc["pixelChecks"]
        self.assertEqual((row["status"], row["outcome"]), ("kept", "catch"), row["reason"])
        self.assertEqual((row["clean"], row["bug"], row["candidate"]), (["pass"] * 3, ["fail"] * 3, ["fail"] * 3))
        self.assertEqual(row["reservedUsd"], 0.0)
        self.assertEqual(row["setting"]["model"], "expectrail.template-ncc/v2")
        self.assertEqual((doc["spend"]["samImages"], doc["spend"]["samUsd"]), (0, 0))
        self.assertEqual(frames.builds, ["pixel-reference"] * 3 + ["pixel-base"] * 3 + ["pixel-candidate"] * 3)
        self.assertEqual(from_base_alone(doc)["pixelReproducing"], ["jit-px-player-drawn"])
        self.assertEqual([r["check"]["id"] for r in pixel.kept_rows(doc)], ["jit-px-player-drawn"])

    def test_a_good_fix_is_not_caught(self):
        doc, _ = self.generate("fix-good")
        [row] = doc["pixelChecks"]
        self.assertEqual((row["status"], row["outcome"]), ("kept", "no-catch"), row["reason"])

    def test_the_row_records_the_frames_the_check_was_planned_on(self):
        # The correct-fix pressure (expectrail/jit/pressure.py) replays a counting check only under this plan.
        doc, _ = self.generate("fix-good")
        [row] = doc["pixelChecks"]
        [route_file] = (self.last_out / "jit-routes").glob(f"*{row['check']['probe']}*.json")
        route = json.loads(route_file.read_text())
        self.assertTrue(row["framesPlanned"])
        self.assertEqual(row["framesPlanned"], pixel.frames_to_ask(row["check"], self.observer().frames(route)))

    def test_a_run_judged_by_sam_does_not_run_a_check_naming_the_sensor(self):
        class Sam:
            name = "sam-3.1-anchor"

            def frames(self, route):
                return [0]

        doc, frames = self.generate("fix-wrong", observer=Sam())
        [row] = doc["pixelChecks"]
        self.assertEqual(row["status"], "not-run")
        self.assertIn("this run's observer is sam-3.1-anchor", row["reason"])
        self.assertEqual(frames.builds, [])


if __name__ == "__main__":
    unittest.main()
