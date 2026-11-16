"""The no-model sensor pointed at objects the game has many of: the enemy (#286).

Offline: a tiny trusted "game" folder holding two pieces of clean art (a player and an enemy with its own
palette), synthetic replays whose traces log the enemies' boxes the way the harness does since November 15
(``enemyBoxes``, ``capabilities.objectBoxes``), a foreground bank calibrated from clean replays with
agents/template_foreground.py ``calibrate_routes(..., objects=("enemy",))``, and the ``visual-sensor``
observer judging pixel checks about the enemy. No engine, no model, no request. These show the calibration
keeps each object's templates and validation apart, the observer's rows and its refusals, and the keep rule;
they say nothing about how often the sensor is right on the bundled game's frames.
"""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    from PIL import Image
except ModuleNotFoundError as exc:  # pragma: no cover - the CI image has both
    if exc.name not in ("numpy", "PIL"):
        raise
    np = Image = None

from expectrail.contracts import validate_v1
from expectrail.jit import pixel

needs_pixels = unittest.skipIf(np is None or Image is None, "the template sensor needs Pillow and NumPy")

SIZE = (140, 70)
PLAYER_AT = (24, 20)           # the player's art (12 x 16) is pasted here; its body box is the same rectangle
BODY = [24, 20, 36, 36]
ENEMY = (20, 14)               # the opaque part of the enemy's art, which is its logged box
CONFIG = dict(searchMarginPx=8, sampleSide=12, scales=[1])
PROBE = "patrol"


def make_game(game: Path) -> None:
    game.mkdir(parents=True)
    (game / "project.godot").write_text("[application]\n")
    grey = np.random.default_rng(262).integers(40, 201, (16, 12), dtype=np.uint8)
    player = np.zeros((16, 12, 4), np.uint8)
    player[:, :, :3] = grey[:, :, None]
    player[2:14, 2:10, 3] = 255
    Image.fromarray(player).save(game / "robot.png")
    rng = np.random.default_rng(286)
    # Opaque inside a two-pixel transparent border, as clean art is; red, so no colour is the player's grey.
    enemy = np.zeros((ENEMY[1] + 4, ENEMY[0] + 4, 4), np.uint8)
    inside = (slice(2, 2 + ENEMY[1]), slice(2, 2 + ENEMY[0]))
    enemy[inside + (0,)] = rng.integers(200, 256, (ENEMY[1], ENEMY[0]))
    enemy[inside + (1,)] = rng.integers(0, 120, (ENEMY[1], ENEMY[0]))
    enemy[inside + (2,)] = rng.integers(0, 60, (ENEMY[1], ENEMY[0]))
    enemy[inside + (3,)] = 255
    Image.fromarray(enemy).save(game / "enemy.png")


def scene(root: Path, game: Path, *, frames: int = 4, enemies=None, background=17, patched=False, name=PROBE,
          drawn=lambda n, ident: True, boxes=True):
    """A replay of ``frames`` frames (two ticks each, 120 a second, 60 fps): the player stands at PLAYER_AT;
    ``enemies(n)`` gives [(id, x, y), ...] for frame n, logged in ``enemyBoxes`` and drawn where ``drawn``."""
    from agents import template_observations as sensor
    from harness.run import tree_digest

    enemies = enemies or (lambda n: [(1, 80 + n, 40)])
    root = Path(root)
    (root / "frames").mkdir(parents=True)
    with Image.open(game / "robot.png") as a, Image.open(game / "enemy.png") as b:
        player, enemy = a.copy(), b.copy()
    rows, hashes = [], []
    for n in range(frames):
        image = Image.new("RGB", SIZE, (background,) * 3)
        image.paste(player, PLAYER_AT, player)
        logged = []
        for ident, x, y in enemies(n):
            logged.append([ident, float(x), float(y), float(x + ENEMY[0]), float(y + ENEMY[1])])
            if drawn(n, ident):
                image.paste(enemy, (x - 2, y - 2), enemy)
        path = root / "frames" / f"f{n:08d}.png"
        image.save(path)
        hashes.append(sensor.sha(path))
        for tick in (2 * n, 2 * n + 1):
            row = {"tick": tick, "body": list(BODY), "player": [30, 30], "view": [1, 0, 0, 1, 0, 0]}
            if boxes:
                row["enemyBoxes"] = copy.deepcopy(logged)
            rows.append(row)
    trace = {"format": "expectrail.trace/v0", "ticks": 2 * frames, "physicsTicksPerSecond": 120, "rows": rows}
    if boxes:
        trace["capabilities"] = {"objectBoxes": True}
    (root / "trace.json").write_text(json.dumps(trace))
    doc = {"format": "expectrail.replay/v0", "route": {"name": name, "sha256": "c" * 64},
           "game": {"tree": tree_digest(game), "patch": "bug.patch" if patched else None,
                    "patchSha256": "b" * 64 if patched else None},
           "capture": {"fps": 60, "physicsTicksPerSecond": 120, "frames": frames},
           "trace": {"path": "trace.json", "sha256": sensor.sha(root / "trace.json")}, "frameSha256": hashes}
    (root / "replay.json").write_text(json.dumps(doc))
    return root


def check(**kw) -> dict:
    entry = {"id": "enemy-drawn", "statement": "Every enemy is drawn where the engine puts it.", "object": "enemy",
             "observer": "visual-sensor", "probe": PROBE, "predicate": {"type": "visible", "minScore": 0.8}, **kw}
    doc, why = pixel.parse_candidate(entry, pixel.BUNDLED_BINDINGS, [PROBE])
    assert why is None, why
    doc["id"] = pixel.ID_PREFIX + doc["id"]
    return doc


@needs_pixels
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from agents import template_foreground as fg
        from harness.run import tree_digest

        cls.tmp = Path(tempfile.mkdtemp(prefix="jit-sensor-named-"))
        cls.game = cls.tmp / "game"
        make_game(cls.game)
        train = scene(cls.tmp / "train", cls.game, frames=6, name="train")
        validation = scene(cls.tmp / "validation", cls.game, frames=6, background=230, name="validation")
        cls.bank = fg.calibrate_routes([train], validation, clean_game=cls.game, clean_tree=tree_digest(cls.game),
                                       art={"player": "robot.png", "enemy": "enemy.png"}, config=CONFIG,
                                       objects=("enemy",))
        cls.bank_path = cls.tmp / "bank.json"
        cls.bank_path.write_text(json.dumps(cls.bank))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def observer(self, bank=None, **kw):
        from expectrail.jit.template_observer import TemplateSensorObserver

        return TemplateSensorObserver(bank or self.bank_path, every=1, **kw)

    def run_dir(self, name="r", **kw):
        return scene(Path(tempfile.mkdtemp(dir=self.tmp)) / name, self.game, **kw)

    def ask(self, observer=None, frames=4, player=False, **kw):
        return pixel.observe(observer or self.observer(), self.run_dir(frames=frames, **kw),
                             {"name": PROBE, "ticks": 2 * frames}, objects=("enemy",), player=player)


class Calibration(Base):
    def test_each_object_keeps_its_own_templates_and_its_own_validation(self):
        objects = {t["object"] for t in self.bank["templates"]}
        self.assertEqual(objects, {"player", "enemy"})
        named = self.bank["calibration"]["objects"]
        self.assertEqual(set(named), {"enemy"})
        enemy = named["enemy"]
        self.assertEqual(enemy["templates"], sum(t["object"] == "enemy" for t in self.bank["templates"]))
        self.assertEqual(enemy["status"], "met")
        self.assertEqual((enemy["positives"], enemy["positiveMatches"]), (6, 6))
        self.assertEqual(enemy["negativeMatches"], 0)
        # The player's own threshold and counts are the player's alone.
        self.assertEqual(self.bank["calibration"]["positives"], 6)
        # Each enemy template's mask follows the enemy's palette, never the player's.
        sources = {s["object"]: s for s in self.bank["foregroundSources"]}
        self.assertEqual(set(sources), {"player", "enemy"})

    def test_the_bank_is_read_back_whole(self):
        from agents import template_observations as sensor

        self.assertEqual(sensor.load_bank(json.loads(self.bank_path.read_text())), self.bank)
        forged = copy.deepcopy(self.bank)
        forged["calibration"]["objects"]["coin"] = forged["calibration"]["objects"]["enemy"]
        with self.assertRaises(sensor.SensorError):
            sensor.load_bank(forged)

    def test_named_objects_need_their_art_and_a_logged_box(self):
        from agents import template_foreground as fg
        from agents import template_observations as sensor
        from harness.run import tree_digest

        tree = tree_digest(self.game)
        for objects, art, expect in ((("enemy",), {"player": "robot.png"}, "approved art for every"),
                                     (("coin",), {"player": "robot.png", "coin": "enemy.png"}, "logs boxes for"),
                                     (("enemy", "enemy"), {"player": "robot.png", "enemy": "enemy.png"}, "distinct")):
            with self.subTest(objects=objects), self.assertRaisesRegex(sensor.SensorError, expect):
                fg.calibrate_routes([self.tmp / "train"], self.tmp / "validation", clean_game=self.game,
                                    clean_tree=tree, art=art, config=CONFIG, objects=objects)

    def test_without_named_objects_the_bank_is_as_before(self):
        from agents import template_foreground as fg
        from harness.run import tree_digest

        bank = fg.calibrate_routes([self.tmp / "train"], self.tmp / "validation", clean_game=self.game,
                                   clean_tree=tree_digest(self.game), art={"player": "robot.png"}, config=CONFIG)
        self.assertEqual({t["object"] for t in bank["templates"]}, {"player"})
        self.assertNotIn("objects", bank["calibration"])

    def test_a_crop_never_holds_two_objects(self):
        from agents import template_foreground as fg

        trace = json.loads((self.tmp / "train" / "trace.json").read_text())
        for row in trace["rows"]:
            row["enemyBoxes"] = [[1, 80, 40, 100, 54], [2, 95, 40, 115, 54], [3, 10, 50, 30, 64]]
        boxes = fg._calibration_boxes(trace, [0, 1], 60, ("enemy",), SIZE)
        # Enemies 1 and 2 overlap, so the first that touches nothing is enemy 3.
        self.assertEqual(boxes[0]["enemy"], [10, 50, 30, 64])
        self.assertEqual(boxes[0]["player"], BODY)


@needs_pixels
class Contract(unittest.TestCase):
    EXAMPLE = Path(__file__).resolve().parents[1] / "contracts" / "examples" / "template-bank-foreground-named.json"

    def test_the_example_is_read_and_its_claims_are_recomputed(self):
        from agents import template_observations as sensor
        from expectrail.jit.template_observer import TemplateSensorObserver

        bank = sensor.load_bank(self.EXAMPLE)
        self.assertEqual(bank["calibration"]["objects"]["enemy"]["status"], "met")
        self.assertEqual(TemplateSensorObserver(bank).named, ("enemy",))
        forgeries = {
            "does not have the templates": lambda o: o.update(templates=o["templates"] + 1),
            "more matches than it counted": lambda o: o.update(positiveMatches=o["positives"] + 1),
            "a status its counts do not give": lambda o: o.update(negativeMatches=o["negatives"]),
        }
        for expect, forge in forgeries.items():
            forged = json.loads(self.EXAMPLE.read_text())
            forge(forged["calibration"]["objects"]["enemy"])
            with self.subTest(expect=expect), self.assertRaisesRegex(sensor.SensorError, expect):
                sensor.load_bank(forged)
        unmet = json.loads(self.EXAMPLE.read_text())
        unmet["calibration"]["objects"]["enemy"].update(positiveMatches=0, status="unmet")
        self.assertEqual(TemplateSensorObserver(sensor.load_bank(unmet)).named, ())
        no_art = json.loads(self.EXAMPLE.read_text())
        no_art["calibration"]["objects"]["bullet"] = dict(no_art["calibration"]["objects"]["enemy"], templates=0,
                                                         status="unmet", positives=0, positiveMatches=0)
        with self.assertRaisesRegex(sensor.SensorError, "no trusted art source"):
            sensor.load_bank(no_art)

    def test_a_legacy_bank_is_never_pointed_at_a_named_object(self):
        from agents import template_observations as sensor
        from expectrail.jit.template_observer import TemplateSensorObserver

        tmp = Path(tempfile.mkdtemp(prefix="jit-sensor-legacy-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        game = tmp / "game"
        make_game(game)
        from harness.run import tree_digest

        run = scene(tmp / "clean", game, frames=2, name="clean")
        bank = sensor.calibrate(run, clean_tree=tree_digest(game), frames=[0], config=CONFIG,
                                predicted={0: {"player": BODY, "enemy": [80, 40, 100, 54]}})
        bank["calibration"]["objects"] = {"enemy": dict(templates=1, positives=1, negatives=1, positiveMatches=1,
                                                        negativeMatches=0, status="met")}
        observer = TemplateSensorObserver(sensor.load_bank(bank))
        self.assertEqual(observer.named, ())
        with self.assertRaisesRegex(pixel.PixelError, "not an approved-art foreground bank"):
            observer.most_images({"name": PROBE, "ticks": 8}, ("enemy",), True)


class ObjectPredictions(unittest.TestCase):
    def trace(self, **kw):
        rows = [{"tick": t, "view": [2, 0, 0, 2, -10, 5], "enemyBoxes": [[4, 10.0, 10.0, 20.0, 15.0]]} for t in range(4)]
        return {"physicsTicksPerSecond": 120, "ticks": 4, "rows": rows, "capabilities": {"objectBoxes": True}, **kw}

    def test_boxes_go_through_the_next_ticks_camera(self):
        from agents import template_observations as sensor

        got = sensor.object_predictions(self.trace(), [0, 1], "enemy")
        self.assertEqual(got[0], [(4, [10.0, 25.0, 30.0, 35.0])])

    def test_the_record_that_cannot_say_is_none_never_a_guess(self):
        from agents import template_observations as sensor

        self.assertEqual(sensor.object_predictions(self.trace(capabilities={}), [0], "enemy"), {0: None})
        broken = self.trace()
        broken["rows"][1]["enemyBoxes"] = [[4, 10.0, "x", 20.0, 15.0]]
        self.assertEqual(sensor.object_predictions(broken, [0], "enemy"), {0: None})
        no_camera = self.trace()
        del no_camera["rows"][2]["view"]
        self.assertEqual(sensor.object_predictions(no_camera, [0, 1], "enemy")[0], None)
        none = self.trace()
        for row in none["rows"]:
            row["enemyBoxes"] = []
        self.assertEqual(sensor.object_predictions(none, [0], "enemy"), {0: []})
        self.assertEqual(sensor.object_predictions(self.trace(), [5], "enemy"), {5: None})
        with self.assertRaisesRegex(sensor.SensorError, "logs no box"):
            sensor.object_predictions(self.trace(), [0], "coin")


class WhatTheSensorSays(Base):
    def test_an_enemy_drawn_where_the_engine_puts_it_passes_with_nothing_charged(self):
        setting, run, images = self.ask()
        self.assertEqual(images, 0)
        self.assertTrue(all(not f["asked"] and f["note"] == pixel.NOT_ASKED_PLAYER for f in run["frames"]))
        rows = run["objects"]["enemy"]
        self.assertTrue(all(r["asked"] and [b["status"] for b in r["boxes"]] == ["matched"] for r in rows))
        self.assertEqual(pixel.judge(check(), run)["result"], "pass")

    def test_an_enemy_not_drawn_is_an_observation_of_absence_and_fails(self):
        setting, run, images = self.ask(drawn=lambda n, ident: n != 2)
        row = run["objects"]["enemy"][2]["boxes"][0]
        self.assertEqual((row["status"], row["box"], row["absent"]), ("not-found", None, True))
        self.assertEqual(pixel.judge(check(), run)["result"], "fail")

    def test_one_of_two_enemies_missing_fails_for_that_one(self):
        two = lambda n: [(1, 80, 40), (2, 110, 10)]
        setting, run, images = self.ask(enemies=two, drawn=lambda n, ident: ident == 1)
        self.assertEqual([[b["status"] for b in r["boxes"]] for r in run["objects"]["enemy"]],
                         [["matched", "not-found"]] * 4)
        self.assertEqual(pixel.judge(check(), run)["result"], "fail")

    def test_an_enemy_partly_off_screen_is_a_gap_and_wholly_off_is_not_judged(self):
        partly = lambda n: [(1, 80, 40), (2, SIZE[0] - 5, 10)]
        setting, run, images = self.ask(enemies=partly)
        self.assertEqual(run["objects"]["enemy"][0]["boxes"][1]["status"], "out-of-frame")
        self.assertEqual(pixel.judge(check(), run)["result"], "needs-review")
        gone = lambda n: [(1, 80, 40), (2, SIZE[0] + 50, 10)]
        setting, run, images = self.ask(enemies=gone)
        self.assertEqual([(len(r["boxes"]), r["outside"]) for r in run["objects"]["enemy"]], [(1, 1)] * 4)
        self.assertEqual(pixel.judge(check(), run)["result"], "pass")

    def test_more_on_screen_than_are_asked_about_is_a_gap(self):
        many = lambda n: [(i, 4 + 30 * i, 50) for i in range(pixel.MAX_BOXES + 1)]
        setting, run, images = self.ask(enemies=many)
        self.assertTrue(all(not r["asked"] and "more than" in r["note"] for r in run["objects"]["enemy"]))
        self.assertEqual(pixel.judge(check(), run)["result"], "needs-review")

    def test_a_trace_without_object_boxes_is_a_gap_never_a_guess(self):
        setting, run, images = self.ask(boxes=False)
        self.assertTrue(all(not r["asked"] for r in run["objects"]["enemy"]))
        self.assertEqual(pixel.judge(check(), run)["result"], "needs-review")

    def test_the_player_and_the_enemy_on_one_replay(self):
        setting, run, images = self.ask(player=True)
        self.assertTrue(all(f["asked"] and f["status"] == "matched" for f in run["frames"]))
        player = {**check(), "object": "player", "id": pixel.ID_PREFIX + "player-drawn"}
        self.assertEqual(pixel.judge(player, run)["result"], "pass")
        self.assertEqual(pixel.judge(check(), run)["result"], "pass")


class TheKeepRule(Base):
    def test_kept_where_every_enemy_is_drawn_on_clean_and_one_is_not_on_the_bug(self):
        observer = self.observer()
        clean = [self.ask(observer)[:2] for _ in range(pixel.REPEATS)]
        bug = [self.ask(observer, patched=True, drawn=lambda n, ident: n < 1)[:2] for _ in range(pixel.REPEATS)]
        verdict = pixel.keep(check(), [(s, r) for s, r in clean], [(s, r) for s, r in bug])
        self.assertTrue(verdict["kept"], verdict)


class FailsClosed(Base):
    def test_a_role_the_bank_cannot_see_is_refused_so_its_checks_are_not_run(self):
        from expectrail.jit.template_observer import TemplateSensorObserver

        player_only = copy.deepcopy(self.bank)
        player_only["templates"] = [t for t in player_only["templates"] if t["object"] == "player"]
        player_only["foregroundSources"] = [s for s in player_only["foregroundSources"] if s["object"] == "player"]
        del player_only["calibration"]["objects"]
        unmet = copy.deepcopy(self.bank)
        unmet["calibration"]["objects"]["enemy"].update(positiveMatches=0, status="unmet")
        route = {"name": PROBE, "ticks": 8}
        for bank, why in ((player_only, "holds no template of it"), (unmet, "is not met")):
            observer = TemplateSensorObserver(bank, every=1)
            with self.subTest(why=why):
                with self.assertRaises(pixel.PixelError) as caught:
                    observer.most_images(route, ("enemy",), False)
                self.assertIn(why, str(caught.exception))
                with self.assertRaises(pixel.PixelError):
                    observer(self.run_dir(frames=4), route, objects=("enemy",), player=False)
        with self.assertRaisesRegex(pixel.PixelError, "engine logs no box"):
            self.observer().most_images(route, ("coin",), True)
        with self.assertRaisesRegex(pixel.PixelError, "asked about nothing"):
            self.observer().most_images(route, (), False)
        self.assertEqual(self.observer().most_images(route, ("enemy",), True), 0)

    def test_an_answer_about_the_enemy_is_read_as_the_judge_reads_it(self):
        setting, run, images = self.ask()
        broken = copy.deepcopy(run)
        broken["objects"]["enemy"][0]["boxes"][0]["error"] = "forged"
        broken["objects"]["enemy"][0]["boxes"][0]["box"] = None
        broken["objects"]["enemy"][0]["boxes"][0].pop("holdsPoint", None)
        self.assertEqual(pixel.judge(check(), broken)["result"], "needs-review")
        # A box that says it was found nowhere but still carries a box is not an absence.
        forged = copy.deepcopy(run)
        forged["objects"]["enemy"][1]["boxes"][0].update(absent=True, holdsPoint=False)
        self.assertEqual(pixel.judge(check(), forged)["result"], "fail")


if __name__ == "__main__":
    unittest.main()
