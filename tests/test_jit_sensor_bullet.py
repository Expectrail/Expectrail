"""The no-model sensor's ring witness for the bullet (#286; agents/template_radial.py).

Offline: a tiny trusted "game" folder holding a player's art and a round bullet's art, synthetic replays in
which the bullet turns as it flies and is drawn behind its logged box (as physics interpolation draws it on
the bundled game), a bank calibrated with expectrail/jit/template_observer.py ``add_radial``, and the
``visual-sensor`` observer judging pixel checks about the bullet. No engine, no model, no request. These show
the witness's rules (the path, the rings, fading, the reader's recomputation) and the keep rule's inputs; how
often it is right on the bundled game's frames is measured on the real engine, not here.
"""
from __future__ import annotations

import copy
import json
import math
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

from expectrail.jit import pixel

needs_pixels = unittest.skipIf(np is None or Image is None, "the template sensor needs Pillow and NumPy")

SIZE = (240, 90)
PLAYER_AT = (14, 10)
BODY = [14, 10, 26, 26]
SIDE = 16                       # the bullet's 8 x 8 art drawn at 2x, and its logged box
SPEED = 6.0                     # frame pixels a tick
LAG = 1.3                       # ticks the frame draws it behind the box logged on the frame's tick
CONFIG = dict(searchMarginPx=8, sampleSide=12, scales=[1])
PROBE = "fire"
FADES = 18
CLEAR = 6                       # frame pixels another logged box must stay from a bullet's path
RECIPE = {"bullet": {"art": "bullet.png", "side": SIDE, "fadesAfterTicks": FADES, "clearPx": CLEAR}}


def make_game(game: Path) -> None:
    game.mkdir(parents=True)
    (game / "project.godot").write_text("[application]\n")
    grey = np.random.default_rng(262).integers(40, 201, (16, 12), dtype=np.uint8)
    player = np.zeros((16, 12, 4), np.uint8)
    player[:, :, :3] = grey[:, :, None]
    player[2:14, 2:10, 3] = 255
    Image.fromarray(player).save(game / "robot.png")
    # A round bullet, concentric rings with a small mark off centre so that turning it changes its pixels.
    art = np.zeros((8, 8, 4), np.uint8)
    y, x = np.mgrid[0:8, 0:8]
    r = np.hypot(x - 3.5, y - 3.5)
    for limit, colour in ((4.0, (20, 120, 110)), (3.0, (60, 220, 230)), (1.6, (250, 250, 250))):
        art[r < limit] = (*colour, 255)
    art[1, 3] = (20, 120, 110, 255)
    Image.fromarray(art).save(game / "bullet.png")


def texture(seed):
    rng = np.random.default_rng(seed)
    base = rng.integers(70, 170, (SIZE[1] // 3 + 1, SIZE[0] // 3 + 1, 3), dtype=np.uint8)
    base[..., 0] = np.clip(base[..., 0].astype(int) + 40, 0, 255)
    return Image.fromarray(np.kron(base, np.ones((3, 3, 1), np.uint8))[:SIZE[1], :SIZE[0]])


def scene(root: Path, game: Path, *, frames: int = 8, seed=17, patched=False, name=PROBE, start=60.0, row=50.0,
          covered=lambda n: False, logged_from=0, boxes=True, neighbour=None, enemies=True):
    """``frames`` frames, two ticks each (120 a second, 60 fps). One bullet (id 3), logged from tick
    ``logged_from`` at x = start + SPEED * tick, turned 37 degrees more each frame and drawn LAG ticks behind the
    box logged on the frame's tick; ``covered(n)`` paints scenery over it (the bug). ``neighbour`` (dx, dy): a
    second bullet (id 4) logged and drawn that far from the first, moving with it. ``enemies``: whether the
    record logs the enemies' boxes (none are on screen)."""
    from agents import template_observations as sensor
    from harness.run import tree_digest

    root = Path(root)
    (root / "frames").mkdir(parents=True)
    with Image.open(game / "robot.png") as a, Image.open(game / "bullet.png") as b:
        player = a.copy()
        bullet = b.convert("RGBA").resize((SIDE, SIDE), Image.Resampling.NEAREST)
    background = texture(seed)
    rows, hashes = [], []
    for n in range(frames):
        image = background.copy()
        image.paste(player, PLAYER_AT, player)
        tick = 2 * n + 1
        x = start + SPEED * max(logged_from, tick - LAG)
        turned = bullet.rotate(37 * n, resample=Image.Resampling.NEAREST)
        at = (round(x), round(row))
        image.paste(turned, at, turned)
        if neighbour is not None:
            image.paste(turned, (at[0] + neighbour[0], at[1] + neighbour[1]), turned)
        if covered(n):
            image.paste((150, 90, 40), (at[0] - 2, at[1] - 2, at[0] + SIDE + 2, at[1] + SIDE + 2))
        path = root / "frames" / f"f{n:08d}.png"
        image.save(path)
        hashes.append(sensor.sha(path))
        for t in (2 * n, 2 * n + 1):
            entry = {"tick": t, "body": list(BODY), "player": [20, 20], "view": [1, 0, 0, 1, 0, 0]}
            if boxes:
                bx = start + SPEED * t
                entry["projectileBoxes"] = [[3, bx, row, bx + SIDE, row + SIDE]] if t >= logged_from else []
                if neighbour is not None and t >= logged_from:
                    dx, dy = neighbour
                    entry["projectileBoxes"].append([4, bx + dx, row + dy, bx + dx + SIDE, row + dy + SIDE])
                if enemies:
                    entry["enemyBoxes"] = []
            rows.append(entry)
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


def radial_pad() -> int:
    from agents import template_radial as radial
    return radial.PAD


def check(**kw) -> dict:
    entry = {"id": "bullet-drawn", "statement": "Every bullet is drawn where the engine puts it.", "object": "bullet",
             "observer": "visual-sensor", "probe": PROBE, "predicate": {"type": "visible", "minScore": 0.5}, **kw}
    doc, why = pixel.parse_candidate(entry, pixel.BUNDLED_BINDINGS, [PROBE])
    assert why is None, why
    doc["id"] = pixel.ID_PREFIX + doc["id"]
    return doc


@needs_pixels
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from agents import template_foreground as fg
        from expectrail.jit.template_observer import add_radial
        from harness.run import tree_digest

        cls.tmp = Path(tempfile.mkdtemp(prefix="jit-sensor-bullet-"))
        cls.game = cls.tmp / "game"
        make_game(cls.game)
        cls.tree = tree_digest(cls.game)
        cls.train = [scene(cls.tmp / "train", cls.game, name="train"),
                     scene(cls.tmp / "train-2", cls.game, name="train-2", start=40.0, row=56.0, seed=5)]
        cls.validation = scene(cls.tmp / "validation", cls.game, seed=99, name="validation", start=50.0, row=60.0)
        bank = fg.calibrate_routes(cls.train, cls.validation, clean_game=cls.game, clean_tree=cls.tree,
                                   art={"player": "robot.png"}, config=CONFIG)
        cls.bank = add_radial(bank, cls.train, cls.validation, game=cls.game, clean_tree=cls.tree, objects=RECIPE)
        cls.bank_path = cls.tmp / "bank.json"
        cls.bank_path.write_text(json.dumps(cls.bank))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def observer(self, bank=None, **kw):
        from expectrail.jit.template_observer import TemplateSensorObserver

        return TemplateSensorObserver(bank or self.bank_path, every=1, **kw)

    def ask(self, frames=8, **kw):
        run_dir = scene(Path(tempfile.mkdtemp(dir=self.tmp)) / "r", self.game, frames=frames, **kw)
        return pixel.observe(self.observer(), run_dir, {"name": PROBE, "ticks": 2 * frames}, objects=("bullet",),
                             player=False)


class Paths(unittest.TestCase):
    def trace(self, **kw):
        rows = [{"tick": t, "view": [2, 0, 0, 2, -10, 5],
                 "projectileBoxes": [[7, 10.0 + 3 * t, 10.0, 18.0 + 3 * t, 18.0]] if t >= 1 else []} for t in range(8)]
        return {"physicsTicksPerSecond": 120, "ticks": 8, "rows": rows, "capabilities": {"objectBoxes": True}, **kw}

    def test_the_path_runs_from_two_ticks_back_to_the_frames_tick_with_its_age(self):
        from agents import template_radial as radial

        got = radial.paths(self.trace(), [1, 2], "bullet")
        # Frame 1 is tick 3; two ticks back is tick 1. Both through the frame's camera, the view logged on tick 4 (x2, -10, +5).
        self.assertEqual(got[1], [(7, [16.0, 25.0, 32.0, 41.0], [28.0, 25.0, 44.0, 41.0], 2)])
        self.assertEqual(got[2][0][3], 4)

    def test_a_bullet_fired_since_starts_its_path_where_it_was_first_logged(self):
        from agents import template_radial as radial

        trace = self.trace()
        trace["rows"][1]["projectileBoxes"] = []
        got = radial.paths(trace, [1], "bullet")
        self.assertEqual(got[1][0][1], [22.0, 25.0, 38.0, 41.0])
        trace["rows"][2]["projectileBoxes"] = []
        got = radial.paths(trace, [1], "bullet")
        self.assertEqual(got[1][0][1], got[1][0][2])

    def test_a_still_bullet_under_a_scrolling_camera_has_a_still_path(self):
        from agents import template_radial as radial

        trace = self.trace()
        for row in trace["rows"]:
            row["view"] = [1, 0, 0, 1, -14 * row["tick"], 0]
            row["projectileBoxes"] = [[7, 100.0, 10.0, 108.0, 18.0]]
        before, now = radial.paths(trace, [1], "bullet")[1][0][1:3]
        # The frame is drawn under the camera of tick 4, whichever tick each box was logged on.
        self.assertEqual(before, now)
        self.assertEqual(now[0], 100.0 - 14 * 4)

    def test_a_record_that_cannot_say_is_none(self):
        from agents import template_observations as sensor
        from agents import template_radial as radial

        self.assertEqual(radial.paths(self.trace(capabilities={}), [1], "bullet"), {1: None})
        broken = self.trace()
        broken["rows"][3]["projectileBoxes"] = [[7, "x", 1, 2, 3]]
        self.assertEqual(radial.paths(broken, [1], "bullet"), {1: None})
        with self.assertRaisesRegex(sensor.SensorError, "logs no box"):
            radial.paths(self.trace(), [1], "coin")


@needs_pixels
class Rings(unittest.TestCase):
    def test_turning_a_round_sprite_keeps_its_rings(self):
        from agents import template_radial as radial

        tmp = Path(tempfile.mkdtemp(prefix="jit-rings-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        make_game(tmp / "game")
        with Image.open(tmp / "game" / "bullet.png") as art:
            sprite = art.convert("RGBA").resize((SIDE, SIDE), Image.Resampling.NEAREST)
        ground = Image.new("RGB", (SIDE, SIDE), (120, 80, 40))

        def rings(angle):
            image = ground.copy()
            turned = sprite.rotate(angle, resample=Image.Resampling.NEAREST)
            image.paste(turned, (0, 0), turned)
            return radial.profile(np.asarray(image), radial.rings_for(SIDE))

        upright = rings(0)
        self.assertEqual(radial.distance(upright, rings(90)), 0.0)
        for angle in (20, 37, 133, 251):
            self.assertLess(radial.distance(upright, rings(angle)), radial.MAX_DISTANCE)
        covered = np.full((SIDE, SIDE, 3), (150, 90, 40), np.uint8)
        self.assertGreater(radial.distance(upright, radial.profile(covered, radial.rings_for(SIDE))), 3 * radial.MAX_DISTANCE)


class Calibration(Base):
    def test_the_bullet_is_witnessed_by_rings_and_its_validation_is_its_own(self):
        witness = self.bank["radialWitnesses"]["bullet"]
        record = self.bank["calibration"]["objects"]["bullet"]
        self.assertEqual(witness["algorithm"], "expectrail.radial-witness/v1")
        self.assertEqual((witness["sidePx"], witness["rings"], witness["fadesAfterTicks"], witness["clearPx"]),
                         (SIDE, 6, FADES, CLEAR))
        self.assertEqual(witness["art"]["path"], "bullet.png")
        self.assertEqual(record["witness"], "radial")
        self.assertEqual(record["templates"], len(witness["profiles"]))
        self.assertEqual(record["status"], "met")
        self.assertEqual(record["positiveMatches"], record["positives"])
        self.assertGreater(record["negatives"], 0)
        self.assertEqual(record["negativeMatches"], 0)
        # No template of the bullet: it is witnessed by its rings alone.
        self.assertNotIn("bullet", {t["object"] for t in self.bank["templates"]})

    def test_fading_and_partly_shown_bullets_never_become_profiles_or_positives(self):
        from agents import template_radial as radial

        trace = json.loads((self.tmp / "validation" / "trace.json").read_text())
        where = radial.paths(trace, list(range(8)), "bullet")
        # Frame 8 would be tick 17 (age 17) and frame 9 tick 19 (age 19): from FADES on, not eligible.
        aged = [(3, [50, 60, 66, 76], [56, 60, 72, 76], FADES)]
        self.assertEqual(radial._eligible(aged, [list(BODY)], *SIZE, SIDE, FADES, CLEAR), [])
        self.assertEqual(len(radial._eligible(where[2], [list(BODY)], *SIZE, SIDE, FADES, CLEAR)), 1)
        edge = [(3, [-4, 60, 12, 76], [2, 60, 18, 76], 1)]
        self.assertEqual(radial._eligible(edge, [list(BODY)], *SIZE, SIDE, FADES, CLEAR), [])

    def test_a_bullet_with_another_box_within_the_clearance_never_becomes_a_profile_or_positive(self):
        """The rule ``look`` judges by (``crowded``) is the rule calibration keeps by, so the validation counts
        describe exactly the boxes the witness is asked about. Found on the real engine on November 19: every
        clean bullet the witness did not find overlapped another bullet."""
        from agents import template_radial as radial

        alone = (3, [50, 60, 66, 76], [56, 60, 72, 76], 2)
        # Another bullet's box CLEAR - 1 pixels beyond the searched area, then CLEAR + 1.
        near = [56 + SIDE + radial.PAD + CLEAR - 1, 60, 56 + 2 * SIDE + radial.PAD + CLEAR - 1, 76]
        far = [near[0] + 2, 60, near[2] + 2, 76]
        self.assertEqual(radial._eligible([alone, (4, near, near, 2)], [], *SIZE, SIDE, FADES, CLEAR),
                         [])
        self.assertEqual([e[0] for e in radial._eligible([alone, (4, far, far, 2)], [], *SIZE, SIDE, FADES, CLEAR)],
                         [3, 4])
        # Any other logged box (the player's here) must not touch the searched area; the clearance is for the
        # role's own kind, which draws around itself what the profiles hold.
        touching = [56 + SIDE + radial.PAD - 1, 60, 56 + 2 * SIDE + radial.PAD - 1, 76]
        beside = [touching[0] + 1, 60, touching[2] + 1, 76]
        self.assertEqual(radial._eligible([alone], [touching], *SIZE, SIDE, FADES, CLEAR), [])
        self.assertEqual(len(radial._eligible([alone], [beside], *SIZE, SIDE, FADES, CLEAR)), 1)
        self.assertEqual(radial._eligible([alone, (4, beside, beside, 2)], [], *SIZE, SIDE, FADES, CLEAR), [])

    def test_a_clearance_that_is_not_a_whole_number_of_pixels_is_refused(self):
        from agents import template_observations as sensor
        from expectrail.jit.template_observer import add_radial

        for bad in (-1, 2.5, None):
            with self.subTest(clear=bad), self.assertRaisesRegex(sensor.SensorError, "whole number of pixels"):
                add_radial(self.bank, self.train, self.validation, game=self.game, clean_tree=self.tree,
                           objects={"bullet": dict(RECIPE["bullet"], clearPx=bad)})

    def test_calibration_takes_the_pinned_clean_replay_only_and_a_separate_validation(self):
        from agents import template_observations as sensor
        from expectrail.jit.template_observer import add_radial

        patched = scene(Path(tempfile.mkdtemp(dir=self.tmp)) / "bug", self.game, patched=True, name="bug")
        with self.assertRaisesRegex(sensor.SensorError, "unpatched clean replay"):
            add_radial(self.bank, [patched], self.validation, game=self.game, clean_tree=self.tree, objects=RECIPE)
        with self.assertRaisesRegex(sensor.SensorError, "separate clean replay"):
            add_radial(self.bank, self.train, self.train[0], game=self.game, clean_tree=self.tree, objects=RECIPE)

    def test_art_that_is_not_a_whole_multiple_of_the_sprite_is_refused(self):
        from agents import template_observations as sensor
        from expectrail.jit.template_observer import add_radial

        odd = {"bullet": dict(RECIPE["bullet"], side=SIDE + 2)}
        with self.assertRaisesRegex(sensor.SensorError, "whole multiple"):
            add_radial(self.bank, self.train, self.validation, game=self.game, clean_tree=self.tree, objects=odd)


class Reader(Base):
    def test_the_bank_is_read_back_whole(self):
        from agents import template_observations as sensor

        self.assertEqual(sensor.load_bank(json.loads(self.bank_path.read_text())), self.bank)

    def test_forged_witnesses_are_refused(self):
        from agents import template_observations as sensor

        def witness(f):
            return lambda b: f(b["radialWitnesses"]["bullet"])

        def record(f):
            return lambda b: f(b["calibration"]["objects"]["bullet"])

        forgeries = {
            "does not match its digest": witness(lambda w: w["profiles"][0].__setitem__(0, 1.0 + w["profiles"][0][0])),
            "other settings than this reader": witness(lambda w: w.update(maxDistance=40.0)),
            "clearPx": witness(lambda w: w.update(clearPx=-1)),
            "other rings than its size gives": witness(lambda w: w.update(sidePx=w["sidePx"] + 4)),
            "does not count its ring profiles": record(lambda r: r.update(templates=r["templates"] + 1)),
            "more matches than it counted": record(lambda r: r.update(positiveMatches=r["positives"] + 1)),
            "a status its counts do not give": record(lambda r: r.update(negativeMatches=r["negatives"])),
            "does not name its radial witness": record(lambda r: r.pop("witness")),
            "has no calibration record": lambda b: b["calibration"]["objects"].pop("bullet"),
            "a radial witness the bank does not hold": lambda b: b.pop("radialWitnesses"),
            "trusted art source": lambda b: b["templates"].append(dict(b["templates"][0], object="bullet")),
        }
        for expect, forge in forgeries.items():
            forged = copy.deepcopy(self.bank)
            forge(forged)
            with self.subTest(expect=expect), self.assertRaisesRegex(sensor.SensorError, expect):
                sensor.load_bank(forged)

    def test_an_unmet_witness_is_refused_by_the_observer(self):
        from agents import template_observations as sensor

        unmet = copy.deepcopy(self.bank)
        unmet["calibration"]["objects"]["bullet"].update(positiveMatches=0, status="unmet")
        observer = self.observer(sensor.load_bank(unmet))
        self.assertNotIn("bullet", observer.named)
        with self.assertRaisesRegex(pixel.PixelError, "not met"):
            observer.most_images({"name": PROBE, "ticks": 16}, ("bullet",), False)
        self.assertIn("bullet", self.observer().named)


class WhatTheSensorSays(Base):
    def test_a_turning_bullet_drawn_behind_its_box_is_matched_on_its_path_and_passes(self):
        setting, run, images = self.ask()
        self.assertEqual(images, 0)
        rows = run["objects"]["bullet"]
        self.assertTrue(all(r["asked"] and [b["status"] for b in r["boxes"]] == ["matched"] for r in rows), rows)
        for r in rows:
            box = r["boxes"][0]
            self.assertGreaterEqual(box["score"], 0.5)
            self.assertTrue(box["holdsPoint"])
        self.assertEqual(pixel.judge(check(), run)["result"], "pass")

    def test_a_bullet_drawn_behind_the_scenery_is_absent_and_fails(self):
        setting, run, images = self.ask(covered=lambda n: n >= 3)
        boxes = [r["boxes"][0] for r in run["objects"]["bullet"]]
        self.assertEqual([b["status"] for b in boxes], ["matched"] * 3 + ["not-found"] * 5)
        self.assertEqual((boxes[4]["box"], boxes[4]["absent"]), (None, True))
        self.assertEqual(pixel.judge(check(), run)["result"], "fail")

    def test_a_fading_bullet_is_a_gap_never_absent(self):
        setting, run, images = self.ask(frames=11, start=10.0)
        statuses = [r["boxes"][0]["status"] for r in run["objects"]["bullet"]]
        # Ticks 17, 19 and 21 are frames 8, 9 and 10: the bullet is FADES ticks old or more from tick 18.
        self.assertEqual(statuses, ["matched"] * 9 + ["unavailable"] * 2)
        self.assertIn("fades it out", run["objects"]["bullet"][9]["boxes"][0]["error"])
        self.assertEqual(pixel.judge(check(), run)["result"], "needs-review")
        self.assertEqual(pixel.judge(check(window={"fromFrame": 0, "toFrame": 8}), run)["result"], "pass")

    def test_a_bullet_whose_path_leaves_the_screen_is_a_gap(self):
        setting, run, images = self.ask(start=SIZE[0] - 90.0)
        statuses = [r["boxes"][0]["status"] for r in run["objects"]["bullet"] if r.get("boxes")]
        self.assertIn("out-of-frame", statuses)
        self.assertEqual(pixel.judge(check(), run)["result"], "needs-review")

    def test_a_bullet_beside_another_is_a_gap_never_absent(self):
        """On the real engine a clean bullet beside another one was not found: the other's glow lights its rings.
        Such a bullet is not judged, so a check over it is needs-review, never fail."""
        setting, run, images = self.ask(neighbour=(SIDE + 2, 0))
        statuses = [[b["status"] for b in r["boxes"]] for r in run["objects"]["bullet"]]
        self.assertEqual(statuses, [["unavailable", "unavailable"]] * 8)
        self.assertIn("within 6 pixels of its path", run["objects"]["bullet"][0]["boxes"][0]["error"])
        self.assertEqual(pixel.judge(check(), run)["result"], "needs-review")
        # Far enough apart, each is judged on its own and both are matched.
        setting, run, images = self.ask(neighbour=(SIDE + 2 * radial_pad() + CLEAR + int(SPEED) * 2 + 8, 0))
        statuses = [[b["status"] for b in r["boxes"]] for r in run["objects"]["bullet"]]
        self.assertEqual(statuses, [["matched", "matched"]] * 8)
        self.assertEqual(pixel.judge(check(), run)["result"], "pass")

    def test_a_record_that_cannot_say_what_is_beside_a_bullet_is_a_gap(self):
        setting, run, images = self.ask(enemies=False)
        self.assertTrue(all(not r["asked"] and "beside" in r["note"] for r in run["objects"]["bullet"]))
        self.assertEqual(pixel.judge(check(), run)["result"], "needs-review")

    def test_a_trace_without_object_boxes_is_a_gap(self):
        setting, run, images = self.ask(boxes=False)
        self.assertTrue(all(not r["asked"] for r in run["objects"]["bullet"]))
        self.assertEqual(pixel.judge(check(), run)["result"], "needs-review")

    def test_the_setting_names_the_bank_so_another_witness_is_another_setting(self):
        from agents import template_observations as sensor
        from expectrail.contracts import digest

        setting, run, images = self.ask()
        self.assertEqual(setting["bankSha256"], digest(self.bank))
        other = copy.deepcopy(self.bank)
        other["radialWitnesses"]["bullet"]["fadesAfterTicks"] = FADES + 1
        self.assertNotEqual(self.observer(sensor.load_bank(other)).setting(), setting)


@needs_pixels
class Contract(unittest.TestCase):
    EXAMPLE = Path(__file__).resolve().parents[1] / "contracts" / "examples" / "template-bank-foreground-radial.json"

    def test_the_example_is_read_and_the_observer_is_pointed_at_the_bullet(self):
        from agents import template_observations as sensor
        from expectrail.jit.template_observer import TemplateSensorObserver

        bank = sensor.load_bank(self.EXAMPLE)
        self.assertEqual(bank["calibration"]["objects"]["bullet"]["witness"], "radial")
        self.assertIn("bullet", TemplateSensorObserver(bank).named)


class CommittedRun(unittest.TestCase):
    """The record of `jit run --proposal` on the real engine with the sensor's stand-in (November 19)."""
    RECORD = (Path(__file__).resolve().parents[1] / "bench" / "jit" / "stand-in" / "bullet-behind-scenery-sensor"
              / "jit-run.json")

    def test_the_sensor_kept_one_bullet_check_and_left_the_other_undecided_with_nothing_reserved(self):
        """Remade after the crowded rule (agents/template_radial.py ``crowded``): the windows end before the first
        crowded or fading bullet on the clean replay. ``move-fire-right``'s second bullet is then on one judged
        frame only, so the clean game is needs-review there, never fail."""
        from expectrail.contracts import validate_v1

        doc = json.loads(self.RECORD.read_text(encoding="utf-8"))
        validate_v1(doc, "jit-run")
        self.assertEqual(doc["inputs"]["model"], "hand-written-stand-in")
        self.assertEqual(doc["settings"]["candidate"], "withheld")
        rows = doc["pixelChecks"]
        self.assertEqual([(r["check"]["probe"], r["check"]["window"]) for r in rows],
                         [("shoot-left-every12", {"fromFrame": 50, "toFrame": 50}),
                          ("move-fire-right", {"fromFrame": 10, "toFrame": 30})])
        for r in rows:
            self.assertEqual((r["check"]["object"], r["check"]["observer"]), ("bullet", "visual-sensor"))
            self.assertEqual(r["reservedUsd"], 0.0)
            self.assertEqual(r["setting"]["model"], "expectrail.template-foreground/v3")
            self.assertEqual(r["setting"]["bankSha256"],
                             "ee1af0c9c2d8463a8b69ff8d2d831f351ace642e93c006fb0c93d8715e16f1e9")
        kept, undecided = rows
        self.assertEqual((kept["status"], kept["clean"], kept["bug"], kept["candidate"], kept["outcome"]),
                         ("kept", ["pass"] * 3, ["fail"] * 3, ["fail"] * 3, "catch"))
        self.assertEqual((undecided["status"], undecided["clean"], undecided["bug"]),
                         ("dropped", ["needs-review"] * 3, ["fail"] * 3))
        self.assertIn("not-exercised", undecided["reason"])
        self.assertNotIn("fail", undecided["clean"])

    def test_the_reproduction_score_gives_it_no_result(self):
        from expectrail.jit import intent
        from expectrail.repro import bench, score

        tmp = Path(tempfile.mkdtemp(prefix="bullet-sensor-score-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        case = tmp / "records" / f"{score.CASE_PREFIX}bullet-behind-scenery"
        case.mkdir(parents=True)
        shutil.copy(self.RECORD, case / "jit-run.json")
        doc = score.score(bench.load(), tmp / "records", offer="signals-reach-evidence-pixel",
                          candidate=intent.WITHHELD)
        row = next(r for r in doc["rows"] if r["id"] == "bullet-behind-scenery")
        self.assertEqual(row["outcome"], "no-result")
        self.assertEqual(doc["totals"]["reproduced"], 0)
