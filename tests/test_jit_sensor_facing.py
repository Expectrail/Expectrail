"""Which way the enemy is drawn facing, against the way the engine moves it: ``faces-motion`` (#286).

Offline: the tiny trusted game of tests/test_jit_sensor_named.py (a player and an enemy with its own palette),
synthetic replays whose enemies move one pixel a tick and are drawn mirrored when they walk left (the clean
game's rule) or the other way round (a bug that flips the sprite, like ``enemy-walks-backwards``), a bank
calibrated from clean replays, and the ``visual-sensor`` observer. No engine, no model, no request. These show
the labels, the facing validation and its reader, the observer's rows, the predicate and the keep rule; they
say nothing about how often the sensor tells facing right on the bundled game's frames.
"""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail.contracts import validate_v1
from expectrail.jit import pixel
from tests.test_jit_sensor_named import CONFIG, ENEMY, PLAYER_AT, BODY, SIZE, make_game, needs_pixels, np, Image

PROBE = "patrol"
EXAMPLE = Path(__file__).resolve().parents[1] / "contracts" / "examples" / "pixel-check-facing.json"


def walk_right_then_left(tick):
    """Enemy 1 walks right one pixel a tick for 12 ticks, then left."""
    x = 50 + tick if tick < 12 else 50 + 22 - tick
    return [(1, x, 40)]


def clean_flip(n, ident, motion):
    return motion == "left"


def scene(root: Path, game: Path, *, frames=12, path=walk_right_then_left, flip=clean_flip, background=17,
          patched=False, name=PROBE):
    """A replay of ``frames`` frames, two ticks a frame (120 a second, 60 fps). ``path(tick)`` gives
    [(id, x, y), ...]: each enemy's logged box on that tick. Frame n shows tick 2n+1, the enemy drawn at its box,
    mirrored where ``flip(n, id, motion)`` says; ``motion`` is the way it moved from tick 2n to 2n+1."""
    from agents import template_observations as sensor
    from harness.run import tree_digest

    root = Path(root)
    (root / "frames").mkdir(parents=True)
    with Image.open(game / "robot.png") as a, Image.open(game / "enemy.png") as b:
        player, enemy = a.copy(), b.copy()
    mirrored = enemy.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    rows, hashes = [], []
    for tick in range(2 * frames + 1):
        logged = [[ident, float(x), float(y), float(x + ENEMY[0]), float(y + ENEMY[1])] for ident, x, y in path(tick)]
        rows.append({"tick": tick, "body": list(BODY), "player": [30, 30], "view": [1, 0, 0, 1, 0, 0],
                     "enemyBoxes": logged})
    for n in range(frames):
        image = Image.new("RGB", SIZE, (background,) * 3)
        image.paste(player, PLAYER_AT, player)
        before = {i: x for i, x, _ in path(2 * n)}
        for ident, x, y in path(2 * n + 1):
            motion = "still" if before.get(ident, x) == x else ("right" if x > before[ident] else "left")
            art = mirrored if flip(n, ident, motion) else enemy
            image.paste(art, (x - 2, y - 2), art)
        file = root / "frames" / f"f{n:08d}.png"
        image.save(file)
        hashes.append(sensor.sha(file))
    trace = {"format": "expectrail.trace/v0", "ticks": 2 * frames + 1, "physicsTicksPerSecond": 120, "rows": rows,
             "capabilities": {"objectBoxes": True}}
    (root / "trace.json").write_text(json.dumps(trace))
    doc = {"format": "expectrail.replay/v0", "route": {"name": name, "sha256": "c" * 64},
           "game": {"tree": tree_digest(game), "patch": "bug.patch" if patched else None,
                    "patchSha256": "b" * 64 if patched else None},
           "capture": {"fps": 60, "physicsTicksPerSecond": 120, "frames": frames},
           "trace": {"path": "trace.json", "sha256": sensor.sha(root / "trace.json")}, "frameSha256": hashes}
    (root / "replay.json").write_text(json.dumps(doc))
    return root


def facing_check(**kw) -> dict:
    entry = {"id": "enemy-faces", "statement": "Every enemy is drawn facing the way it walks.", "object": "enemy",
             "observer": "visual-sensor", "probe": PROBE, "predicate": {"type": "faces-motion"}, **kw}
    doc, why = pixel.parse_candidate(entry, pixel.BUNDLED_BINDINGS, [PROBE], pixel.proposed("visual-sensor"))
    assert why is None, why
    doc["id"] = pixel.ID_PREFIX + doc["id"]
    return doc


def visible_check() -> dict:
    return {**facing_check(), "id": pixel.ID_PREFIX + "enemy-drawn", "predicate": {"type": "visible", "minScore": 0.8}}


def backwards(n, ident, motion):
    return motion == "right"


@needs_pixels
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from agents import template_foreground as fg
        from harness.run import tree_digest

        cls.tmp = Path(tempfile.mkdtemp(prefix="jit-sensor-facing-"))
        cls.game = cls.tmp / "game"
        make_game(cls.game)
        train = scene(cls.tmp / "train", cls.game, name="train")
        validation = scene(cls.tmp / "validation", cls.game, background=230, name="validation")
        cls.bank = fg.calibrate_routes([train], validation, clean_game=cls.game, clean_tree=tree_digest(cls.game),
                                       art={"player": "robot.png", "enemy": "enemy.png"}, config=CONFIG,
                                       objects=("enemy",))
        cls.bank_path = cls.tmp / "bank.json"
        cls.bank_path.write_text(json.dumps(cls.bank))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def observer(self, bank=None):
        from expectrail.jit.template_observer import TemplateSensorObserver

        return TemplateSensorObserver(bank or self.bank_path, every=1)

    def ask(self, observer=None, frames=12, **kw):
        run_dir = scene(Path(tempfile.mkdtemp(dir=self.tmp)) / "r", self.game, frames=frames, **kw)
        return pixel.observe(observer or self.observer(), run_dir, {"name": PROBE, "ticks": 2 * frames},
                             objects=("enemy",), player=False)


class Motion(unittest.TestCase):
    def trace(self, xs, **kw):
        rows = [{"tick": t, "enemyBoxes": [[7, float(x), 0.0, float(x) + 10, 10.0]]} for t, x in enumerate(xs)]
        return {"physicsTicksPerSecond": 120, "ticks": len(xs), "rows": rows, "capabilities": {"objectBoxes": True},
                **kw}

    def test_the_way_the_engine_moves_each_object_from_its_own_boxes(self):
        from agents import template_observations as sensor

        # Frame n reads tick 2n+1 and the ticks either side of it.
        cases = {"right": [0, 1, 2, 3], "left": [5, 4, 3, 2], "still": [3, 3, 3, 3], "turning": [0, 1, 0, 0]}
        for expect, xs in cases.items():
            with self.subTest(expect=expect):
                self.assertEqual(sensor.object_motion(self.trace(xs), [0], "enemy"), {0: {7: expect}})

    def test_the_record_that_cannot_say_makes_no_claim(self):
        from agents import template_observations as sensor

        # The last frame has no tick after it; a trace without object boxes says nothing.
        self.assertEqual(sensor.object_motion(self.trace([0, 1]), [0], "enemy"), {0: {7: None}})
        self.assertEqual(sensor.object_motion(self.trace([0, 1, 2], capabilities={}), [0], "enemy"), {0: None})
        broken = self.trace([0, 1, 2])
        broken["rows"][1]["enemyBoxes"] = [[7, "x", 0, 1, 1]]
        self.assertEqual(sensor.object_motion(broken, [0], "enemy"), {0: None})
        other = self.trace([0, 1, 2])
        other["rows"][0]["enemyBoxes"] = [[8, 0.0, 0.0, 10.0, 10.0]]
        self.assertEqual(sensor.object_motion(other, [0], "enemy"), {0: {7: None}})
        with self.assertRaisesRegex(sensor.SensorError, "logs no box"):
            sensor.object_motion(self.trace([0, 1, 2]), [0], "coin")


class Calibration(Base):
    def test_clean_captures_are_labelled_with_the_way_the_engine_moved_them(self):
        enemy = [t for t in self.bank["templates"] if t["object"] == "enemy"]
        self.assertEqual(sorted(t["heading"] for t in enemy), ["left", "right"])
        # The unmirrored crop came from a frame where the enemy walked right; its mirrored copy faces left.
        self.assertEqual({t["mirrorX"]: t["heading"] for t in enemy}, {False: "right", True: "left"})
        self.assertFalse(any("heading" in t for t in self.bank["templates"] if t["object"] == "player"))

    def test_the_facing_is_validated_as_drawn_and_mirrored(self):
        facing = self.bank["calibration"]["objects"]["enemy"]["facing"]
        # Validation frames 0-4 walk right, 6-11 left; frame 5 turns.
        self.assertEqual(facing, {"margin": 0.02, "templates": {"right": 1, "left": 1}, "moving": 11, "agree": 11,
                                  "disagree": 0, "mirroredAgree": 11, "mirroredDisagree": 0, "status": "met"})

    def test_a_pose_that_looks_the_same_mirrored_is_labelled_neither_way(self):
        from agents import template_foreground as fg

        settings = dict(fg.DEFAULTS, **CONFIG)
        rng = np.random.default_rng(5)
        half = rng.integers(0, 256, (16, 8, 3), dtype=np.uint8)
        even = np.concatenate([half, half[:, ::-1]], axis=1)
        mask = np.ones((16, 16), np.uint8)
        self.assertTrue(fg.symmetric(even, mask, settings, 0.995))
        odd = rng.integers(0, 256, (16, 16, 3), dtype=np.uint8)
        self.assertFalse(fg.symmetric(odd, mask, settings, 0.995))

    def test_the_reader_recomputes_the_facing_record(self):
        from agents import template_observations as sensor

        self.assertEqual(sensor.load_bank(json.loads(self.bank_path.read_text())), self.bank)
        forgeries = {
            "does not have the labelled templates": lambda b: next(
                t for t in b["templates"] if t.get("heading") == "left").update(heading="right"),
            "a status its counts do not give": lambda b: b["calibration"]["objects"]["enemy"]["facing"].update(
                mirroredAgree=0),
            "more decisions than frames": lambda b: b["calibration"]["objects"]["enemy"]["facing"].update(
                disagree=1),
            "heading its calibration does not record": lambda b: next(
                t for t in b["templates"] if t["object"] == "player").update(heading="right"),
            "heading its calibration does not record ": lambda b: b["calibration"]["objects"]["enemy"].pop("facing"),
        }
        for expect, forge in forgeries.items():
            forged = copy.deepcopy(self.bank)
            forge(forged)
            with self.subTest(expect=expect), self.assertRaisesRegex(sensor.SensorError, expect.strip()):
                sensor.load_bank(forged)

    def test_without_motion_nothing_is_labelled_and_the_facing_is_unmet(self):
        from agents import template_foreground as fg
        from harness.run import tree_digest

        still = lambda tick: [(1, 70, 40)]
        train = scene(self.tmp / "still-train", self.game, path=still, name="still-train")
        validation = scene(self.tmp / "still-validation", self.game, path=still, background=230,
                           name="still-validation")
        bank = fg.calibrate_routes([train], validation, clean_game=self.game, clean_tree=tree_digest(self.game),
                                   art={"player": "robot.png", "enemy": "enemy.png"}, config=CONFIG,
                                   objects=("enemy",))
        self.assertFalse(any("heading" in t for t in bank["templates"]))
        facing = bank["calibration"]["objects"]["enemy"]["facing"]
        self.assertEqual((facing["moving"], facing["status"]), (0, "unmet"))
        from expectrail.jit.template_observer import TemplateSensorObserver

        observer = TemplateSensorObserver(bank, every=1)
        self.assertEqual((observer.named, observer.facing), (("enemy",), ()))


class WhatTheSensorSays(Base):
    def test_a_clean_enemy_faces_the_way_it_walks(self):
        setting, run, images = self.ask()
        self.assertEqual((images, run["facing"]), (0, ["enemy"]))
        boxes = [r["boxes"][0] for r in run["objects"]["enemy"]]
        self.assertEqual([b["motion"] for b in boxes], ["right"] * 5 + ["turning"] + ["left"] * 6)
        self.assertEqual([b.get("facing") for b in boxes], ["right"] * 5 + [None] + ["left"] * 6)
        self.assertNotIn("facing", boxes[5])
        verdict = pixel.judge(facing_check(), run)
        self.assertEqual(verdict["result"], "pass", verdict)
        self.assertEqual(verdict["framesJudged"], 11)

    def test_an_enemy_drawn_backwards_fails_faces_motion_and_still_passes_visible(self):
        setting, run, images = self.ask(flip=backwards, patched=True)
        boxes = [r["boxes"][0] for r in run["objects"]["enemy"]]
        self.assertEqual([b.get("facing") for b in boxes[:5]], ["left"] * 5)
        self.assertEqual(pixel.judge(visible_check(), run)["result"], "pass")
        verdict = pixel.judge(facing_check(), run)
        self.assertEqual(verdict["result"], "fail")
        self.assertIn("drawn facing the way the engine moves it in 0 of 11 frames", verdict["reason"])
        self.assertEqual(verdict["firstFrame"], 0)

    def test_one_frame_drawn_backwards_is_enough_to_fail(self):
        setting, run, images = self.ask(flip=lambda n, i, m: clean_flip(n, i, m) != (n == 7))
        self.assertEqual(pixel.judge(facing_check(), run)["firstFrame"], 7)

    def test_frames_where_it_stands_are_not_judged(self):
        setting, run, images = self.ask(path=lambda tick: [(1, 70, 40)])
        self.assertTrue(all(r["boxes"][0]["motion"] in ("still", None) for r in run["objects"]["enemy"]))
        verdict = pixel.judge(facing_check(), run)
        self.assertEqual(verdict["result"], "needs-review")
        self.assertIn("no enemy was seen moving one way", verdict["reason"])

    def test_two_enemies_walking_opposite_ways_are_each_judged(self):
        two = lambda tick: [(1, 40 + tick, 40), (2, 110 - tick, 4)]
        setting, run, images = self.ask(path=two, frames=8)
        self.assertEqual(pixel.judge(facing_check(), run)["result"], "pass")
        setting, run, images = self.ask(path=two, frames=8, flip=lambda n, i, m: clean_flip(n, i, m) != (i == 2))
        verdict = pixel.judge(facing_check(), run)
        self.assertEqual(verdict["result"], "fail")
        self.assertIn("enemy 2:", verdict["reason"])


class TheKeepRule(Base):
    def test_kept_where_every_clean_run_faces_its_motion_and_every_bug_run_does_not(self):
        observer = self.observer()
        clean = [self.ask(observer)[:2] for _ in range(pixel.REPEATS)]
        bug = [self.ask(observer, flip=backwards, patched=True)[:2] for _ in range(pixel.REPEATS)]
        verdict = pixel.keep(facing_check(), clean, bug)
        self.assertTrue(verdict["kept"], verdict)
        # visible cannot tell the two builds apart: an enemy drawn backwards is still drawn.
        self.assertEqual(pixel.keep(visible_check(), clean, bug)["reason"], "does-not-fail-on-bug")


class FailsClosed(Base):
    def test_a_bank_without_a_met_facing_says_nothing_about_facing(self):
        from expectrail.jit.template_observer import TemplateSensorObserver

        unmet = copy.deepcopy(self.bank)
        unmet["calibration"]["objects"]["enemy"]["facing"].update(mirroredAgree=0, status="unmet")
        observer = TemplateSensorObserver(unmet, every=1)
        self.assertEqual(observer.facing, ())
        setting, run, images = self.ask(observer)
        self.assertEqual(run["facing"], [])
        self.assertFalse(any("motion" in b for r in run["objects"]["enemy"] for b in r["boxes"]))
        verdict = pixel.judge(facing_check(), run)
        self.assertEqual(verdict["result"], "needs-review")
        self.assertIn("does not say which way enemy faces", verdict["reason"])
        # visible is judged as before.
        self.assertEqual(pixel.judge(visible_check(), run)["result"], "pass")

    def test_a_moving_enemy_whose_facing_was_not_told_is_a_gap(self):
        setting, run, images = self.ask()
        for change, expect in ((lambda b: b.update(facing=None), "could not tell"),
                               (lambda b: b.pop("facing"), "did not say"),
                               (lambda b: b.update(facing="up"), "could not tell")):
            forged = copy.deepcopy(run)
            change(forged["objects"]["enemy"][2]["boxes"][0])
            verdict = pixel.judge(facing_check(), forged)
            with self.subTest(expect=expect):
                self.assertEqual(verdict["result"], "needs-review")
                self.assertIn(expect, verdict["reason"])

    def test_an_answer_claiming_facing_for_an_object_it_was_not_asked_about_is_refused(self):
        from expectrail.jit.template_observer import TemplateSensorObserver

        real = self.observer()

        def forged(run_dir, route, **kw):
            answer = real(run_dir, route, **kw)
            answer["run"]["facing"] = ["enemy", "bullet"]
            return answer

        forged.name, forged.frames = real.name, real.frames
        run_dir = scene(Path(tempfile.mkdtemp(dir=self.tmp)) / "r", self.game)
        with self.assertRaisesRegex(pixel.PixelError, "facing of an object it was not asked about"):
            pixel.observe(forged, run_dir, {"name": PROBE, "ticks": 24}, objects=("enemy",), player=False)
        self.assertIsInstance(real, TemplateSensorObserver)


@needs_pixels
class Contract(unittest.TestCase):
    BANK = Path(__file__).resolve().parents[1] / "contracts" / "examples" / "template-bank-foreground-facing.json"

    def test_the_bank_example_is_read_and_its_facing_is_recomputed(self):
        from agents import template_observations as sensor
        from expectrail.jit.template_observer import TemplateSensorObserver

        bank = sensor.load_bank(self.BANK)
        self.assertEqual(bank["calibration"]["objects"]["enemy"]["facing"]["status"], "met")
        self.assertEqual(TemplateSensorObserver(bank).facing, ("enemy",))
        forged = json.loads(self.BANK.read_text())
        forged["calibration"]["objects"]["enemy"]["facing"]["templates"]["right"] += 1
        with self.assertRaisesRegex(sensor.SensorError, "labelled templates it records"):
            sensor.load_bank(forged)
        out_of_range = json.loads(self.BANK.read_text())
        out_of_range["calibration"]["objects"]["enemy"]["facing"]["margin"] = 2
        with self.assertRaisesRegex(sensor.SensorError, "margin"):
            sensor.load_bank(out_of_range)


class TheLanguage(unittest.TestCase):
    def test_the_example_is_a_pixel_check(self):
        doc = json.loads(EXAMPLE.read_text())
        self.assertEqual(validate_v1(doc, pixel.KIND), "pixel-check")
        check, why = pixel.parse_candidate(doc, pixel.BUNDLED_BINDINGS, ["hold-right"], pixel.proposed("visual-sensor"))
        self.assertIsNone(why)
        self.assertEqual(check["predicate"], {"type": "faces-motion"})

    def test_faces_motion_is_refused_where_no_observer_can_tell_facing(self):
        doc = {k: v for k, v in json.loads(EXAMPLE.read_text()).items() if k not in ("format", "authority", "origin")}
        cases = {
            "about 'player'": ({**doc, "object": "player"}, "visual-sensor"),
            "SAM": ({**doc, "observer": "sam-3.1-anchor"}, "sam-3.1-anchor"),
            "closed language": ({**doc, "predicate": {"type": "faces-motion", "axis": "y"}}, "visual-sensor"),
        }
        for label, (entry, observer) in cases.items():
            with self.subTest(label=label):
                check, why = pixel.parse_candidate(entry, pixel.BUNDLED_BINDINGS, ["hold-right"],
                                                   pixel.proposed(observer))
                self.assertIsNone(check)
        _, why = pixel.parse_candidate({**doc, "observer": "sam-3.1-anchor"}, pixel.BUNDLED_BINDINGS, ["hold-right"],
                                       pixel.proposed("sam-3.1-anchor"))
        self.assertIn("say nothing about which way a sprite faces", why)
        _, why = pixel.parse_candidate({**doc, "object": "player"}, pixel.BUNDLED_BINDINGS, ["hold-right"],
                                       pixel.proposed("visual-sensor"))
        self.assertIn("cannot judge faces-motion about 'player'", why)

    def test_the_sam_menu_does_not_offer_it(self):
        m = pixel.menu(pixel.BUNDLED_BINDINGS, pixel.proposed("sam-3.1-anchor"))
        self.assertNotIn("faces-motion", json.dumps(m))

    def test_a_faces_motion_check_about_a_single_object_is_never_decided(self):
        check = {**json.loads(EXAMPLE.read_text()), "object": "player", "id": "jit-px-x", "probe": PROBE}
        verdict = pixel.judge(check, {"route": {"name": PROBE}, "frames": []})
        self.assertEqual(verdict["result"], "needs-review")


if __name__ == "__main__":
    unittest.main()
