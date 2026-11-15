"""Pixel checks about an object the game has many of: the enemy and the bullet (#286).

The harness logs every enemy's and bullet's own box (``enemyBoxes``, ``projectileBoxes``; #508). The
observer is now pointed at those boxes, one image a box, at most ``pixel.MAX_BOXES`` a frame, and a pixel
check about ``enemy`` or ``bullet`` must hold for every one on screen, each judged on its own frames.

Offline. The replays are synthetic run folders (tests/test_jit_sam_observer.py ``make_run``) and SAM is a
scripted client: these tests show what is asked, what is charged and how the answers are judged, not what
SAM would answer on the bundled game. No model is called and nothing is spent."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agents.sam_observations import SamError
from expectrail.jit import pixel, pixel_jobs
from expectrail.jit import run as run_mod
from expectrail.jit.run import Spend
from expectrail.jit.sam_observer import NAME, RecordedSamClient, SamAnchorObserver
from tests.test_jit_sam_observer import make_run

SIZE = (200, 120)
PROBE = "hold-right"
ROUTE = {"format": "expectrail.route/v0", "name": PROBE, "ticks": 40, "seed": 0, "events": []}
FRAMES = [0, 10, 19]          # every 10th frame and the last of 40 ticks at 2 ticks a frame
ENEMIES = [[1, 100.0, 20.0, 120.0, 40.0], [2, 150.0, 60.0, 170.0, 80.0]]
B = pixel.BUNDLED_BINDINGS


def rows(enemies=ENEMIES, bullets=()) -> list[dict]:
    return [{"player": [50.0, 50.0], "body": [40.0, 40.0, 60.0, 60.0], "view": [1, 0, 0, 1, 0.0, 0.0],
             "enemies": [[e[0], (e[1] + e[3]) / 2, (e[2] + e[4]) / 2] for e in enemies],
             "enemyBoxes": [list(e) for e in enemies], "projectiles": [], "projectileBoxes": [list(b) for b in bullets]}
            for _ in range(ROUTE["ticks"])]


def replay(run_dir: Path, trace_rows=None, logged: bool = True) -> Path:
    make_run(run_dir, PROBE, trace_rows or rows(), frames=20, size=SIZE)
    trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
    if logged:
        trace["capabilities"] = {"objectBoxes": True}
    (run_dir / "trace.json").write_text(json.dumps(trace), encoding="utf-8")
    return run_dir


class Scripted:
    """A SAM client that answers each box with ``answer(frame, box)``: the box found, or None."""

    model = "sam-3.1"

    def __init__(self, answer=None):
        self.answer = answer or (lambda n, box: {"box": list(box), "score": 0.95})
        self.calls = 0
        self.asked: list[tuple[int, list]] = []

    def segment_in(self, png, boxes):
        self.calls += 1
        n = int(Path(png).stem[1:])
        self.asked.append((n, list(boxes[0])))
        return [self.answer(n, list(boxes[0]))]


def check(**kw) -> dict:
    entry = {"id": "enemies-drawn", "statement": "On hold-right every enemy is drawn where the engine puts it.",
             "object": "enemy", "observer": NAME, "probe": PROBE, "predicate": {"type": "visible", "minScore": 0.8},
             **kw}
    got, why = pixel.parse_candidate(entry, B, [PROBE])
    assert why is None, why
    return got


class Scratch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pixel-named-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def ask(self, client=None, objects=("enemy",), **kw):
        client = client or Scripted()
        observer = SamAnchorObserver(client)
        return pixel.observe(observer, replay(self.tmp / "pixel-base" / f"{PROBE}-1", **kw), ROUTE, objects), client


class TheProposerIsOfferedTheEnemyAndTheBullet(unittest.TestCase):
    def test_a_check_about_the_enemy_or_the_bullet_is_in_the_closed_language(self):
        for role in ("enemy", "bullet"):
            got, why = pixel.parse_candidate({**check(), "object": role}, B, [PROBE])
            self.assertIsNone(why)
            self.assertEqual(got["object"], role)

    def test_its_region_is_its_own_box_and_never_another_objects(self):
        got, why = pixel.parse_candidate({**check(), "predicate": {"type": "inside-region", "region": {"engine": "player"}}},
                                         B, [PROBE])
        self.assertIsNone(got)
        self.assertIn("has the engine's box of 'enemy' only", why)

    def test_an_observer_not_pointed_at_the_boxes_is_not_offered_them(self):
        observers = {NAME: {**pixel.OBSERVERS[NAME], "boxes": ()}}
        m = pixel.menu(B, observers)
        self.assertEqual(m["observers"][NAME]["objects"], ["player"])
        self.assertIn("is not pointed at the boxes the engine logs for it", m["notJudgeable"]["enemy"])
        got, why = pixel.parse_candidate(check(), B, [PROBE], observers)
        self.assertIsNone(got)
        self.assertIn("is not pointed at the boxes the engine logs for 'enemy'", why)


class TheObserverIsAskedAboutEveryBox(Scratch):
    def test_one_image_a_box_on_every_planned_frame_and_one_for_the_player(self):
        (setting, run, images), client = self.ask()
        self.assertEqual(run["framesProbed"], FRAMES)
        self.assertEqual([r["frame"] for r in run["objects"]["enemy"]], FRAMES)
        self.assertTrue(all(len(r["boxes"]) == 2 and r["asked"] for r in run["objects"]["enemy"]))
        self.assertEqual(images, len(FRAMES) * 3)
        self.assertEqual(images, client.calls)
        # Each enemy is asked about with its own logged box widened by the observer's pad (4 game px).
        self.assertIn((0, [96, 16, 124, 44]), client.asked)
        self.assertIn((0, [146, 56, 174, 84]), client.asked)
        self.assertLessEqual(images, SamAnchorObserver(client).most_images(ROUTE, ["enemy"]))
        self.assertEqual(SamAnchorObserver(client).most_images(ROUTE, ["enemy"]), len(FRAMES) * (1 + pixel.MAX_BOXES))

    def test_without_named_objects_nothing_more_is_asked(self):
        (setting, run, images), _ = self.ask(objects=())
        self.assertNotIn("objects", run)
        self.assertEqual(images, len(FRAMES))

    def test_more_on_screen_than_it_asks_about_is_a_frame_not_asked(self):
        many = [[i, 10.0 + 30 * i, 10.0, 30.0 + 30 * i, 30.0] for i in range(pixel.MAX_BOXES + 1)]
        (_, run, images), _ = self.ask(trace_rows=rows(many))
        self.assertTrue(all(not r["asked"] and "more than the 3 asked about" in r["note"] for r in run["objects"]["enemy"]))
        self.assertEqual(images, len(FRAMES))
        verdict = pixel.judge(check(), run)
        self.assertEqual(verdict["result"], "needs-review")

    def test_a_trace_that_does_not_log_boxes_is_a_gap_and_never_guessed(self):
        (_, run, _), _ = self.ask(logged=False)
        self.assertTrue(all(not r["asked"] and "objectBoxes" in r["note"] for r in run["objects"]["enemy"]))
        self.assertEqual(pixel.judge(check(), run)["result"], "needs-review")

    def test_a_role_it_is_not_pointed_at_is_refused_before_anything_is_asked(self):
        client = Scripted()
        with self.assertRaisesRegex(pixel.PixelError, "not pointed at 'coin'"):
            self.ask(client, objects=("coin",))
        self.assertEqual(client.calls, 0)

    def test_sam_stopping_part_way_charges_what_was_sent(self):
        def answer(n, box):
            if n == 10 and box[0] > 140:
                raise SamError("rate limited", kind="rate", status=429)
            return {"box": box, "score": 0.9}
        with self.assertRaises(pixel.PixelError) as caught:
            self.ask(Scripted(answer))
        # The player on three frames, then both enemies on frame 0 and the first on frame 10.
        self.assertEqual(caught.exception.images, 3 + 2 + 2)


class EveryObjectIsJudgedOnItsOwn(Scratch):
    def test_every_enemy_found_where_the_engine_puts_it_passes(self):
        (_, run, _), _ = self.ask()
        got = pixel.judge(check(), run)
        self.assertEqual(got["result"], "pass", got["reason"])
        self.assertEqual(got["framesJudged"], 6)

    def test_one_enemy_not_drawn_fails_and_names_it(self):
        # Enemy 2 is not found: SAM's answer at its box is something drawn elsewhere.
        def answer(n, box):
            return {"box": [0, 0, 5, 5], "score": 0.9} if box[0] > 140 else {"box": box, "score": 0.9}
        (_, run, _), _ = self.ask(Scripted(answer))
        got = pixel.judge(check(), run)
        self.assertEqual(got["result"], "fail")
        self.assertIn("enemy 2:", got["reason"])
        self.assertIn("1 of 2 failed", got["reason"])

    def test_no_answer_for_a_box_is_a_gap(self):
        (_, run, _), _ = self.ask(Scripted(lambda n, box: None if n == 10 and box[0] > 140 else {"box": box, "score": 0.9}))
        got = pixel.judge(check(), run)
        self.assertEqual(got["result"], "needs-review")
        self.assertIn("no answer for enemy 2", got["reason"])

    def test_none_on_screen_is_never_a_pass(self):
        (_, run, images), _ = self.ask(trace_rows=rows([]))
        self.assertEqual(images, len(FRAMES))
        got = pixel.judge(check(), run)
        self.assertEqual((got["result"], got["reason"]), ("needs-review", "no enemy was on screen in the window"))

    def test_a_run_not_asked_about_the_object_is_needs_review(self):
        (_, run, _), _ = self.ask(objects=())
        got = pixel.judge(check(), run)
        self.assertEqual(got["result"], "needs-review")
        self.assertIn("not asked about enemy", got["reason"])

    def test_inside_region_is_each_objects_own_box(self):
        def answer(n, box):
            # Enemy 1 spills 30 px out of its own box on frame 19.
            return {"box": [box[0], box[1], box[2] + 30, box[3]], "score": 0.9} if n == 19 and box[0] < 140 else \
                {"box": box, "score": 0.9}
        (_, run, _), _ = self.ask(Scripted(answer))
        inside = check(predicate={"type": "inside-region", "region": {"engine": "enemy"}, "tolerancePx": 2})
        got = pixel.judge(inside, run)
        self.assertEqual(got["result"], "fail")
        self.assertIn("enemy 1:", got["reason"])
        self.assertEqual(got["firstFrame"], 19)

    def test_the_keep_rule_holds_for_named_objects(self):
        (_, clean, _), _ = self.ask()
        (_, bug, _), _ = self.ask(Scripted(lambda n, box: {"box": [0, 0, 5, 5], "score": 0.9}))
        setting = SamAnchorObserver(Scripted()).setting()
        kept = pixel.keep(check(), [(setting, clean)] * 3, [(setting, bug)] * 3)
        self.assertTrue(kept["kept"], kept["reason"])


class TheAnswerIsUntrustedData(Scratch):
    def answer(self, run, objects=("enemy",)):
        class Fixed:
            name = NAME

            def __call__(self, run_dir, route, objects=()):
                return {"setting": {"model": "sam-3.1"}, "run": run, "images": 0}
        return pixel.observe(Fixed(), self.tmp, ROUTE, objects)

    def test_an_answer_about_other_objects_than_asked_is_refused(self):
        (_, run, _), _ = self.ask()
        with self.assertRaisesRegex(pixel.PixelError, "asked about bullet, enemy"):
            self.answer(run, ("bullet", "enemy"))
        with self.assertRaisesRegex(pixel.PixelError, "asked about no named object"):
            self.answer(run, ())

    def test_more_boxes_in_a_frame_than_are_asked_about_is_refused(self):
        (_, run, _), _ = self.ask()
        run["objects"]["enemy"][0]["boxes"] *= 2
        with self.assertRaisesRegex(pixel.PixelError, "at most 3 boxes"):
            self.answer(run)

    def test_a_frame_without_a_number_is_refused(self):
        (_, run, _), _ = self.ask()
        run["objects"]["enemy"][0]["frame"] = "0"
        with self.assertRaisesRegex(pixel.PixelError, "without a frame number"):
            self.answer(run)


class RecordedAnswersAreReplayedBoxByBox(Scratch):
    def test_the_recording_answers_each_box_and_judges_the_same(self):
        def answer(n, box):
            return {"box": [0, 0, 5, 5], "score": 0.9} if box[0] > 140 else {"box": box, "score": 0.9}
        (setting, run, _), _ = self.ask(Scripted(answer))
        doc = {"model": "sam-3.1", "lift": 0.0, "box": "body", "pad": 4.0, "runs": [{**run, "run": "pixel-base/x"}]}
        path = self.tmp / "answers.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        recorded = RecordedSamClient(path, "pixel-base/x")
        again, _ = self.ask(recorded)
        self.assertEqual(again[1]["objects"], run["objects"])
        self.assertEqual(pixel.judge(check(), again[1]), pixel.judge(check(), run))

    def test_a_box_the_recording_was_not_asked_about_stops_the_run(self):
        (_, run, _), _ = self.ask()
        run["objects"]["enemy"][1]["boxes"].pop()
        doc = {"model": "sam-3.1", "lift": 0.0, "box": "body", "pad": 4.0, "runs": [{**run, "run": "x"}]}
        path = self.tmp / "answers.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaisesRegex(pixel.PixelError, "SAM stopped at frame 10"):
            self.ask(RecordedSamClient(path, "x"))


class TheBudgetReservesEveryBox(Scratch):
    def test_a_check_about_a_role_with_many_reserves_max_boxes_a_frame(self):
        price = Spend(1, {}).prices["samUsdPerImage"]
        player = {**check(), "object": "player"}
        self.assertAlmostEqual(pixel.cost(player, FRAMES, price), len(FRAMES) * 6 * price)
        self.assertAlmostEqual(pixel.cost(check(), FRAMES, price), len(FRAMES) * pixel.MAX_BOXES * 6 * price)

    def test_the_replay_asks_about_the_named_objects_its_checks_name_and_reserves_for_them(self):
        client = Scripted()
        observer = SamAnchorObserver(client)

        def fake_replay(name, patches, pid, n, with_runner=None):
            replay(self.tmp / "jit-replays" / name / f"{pid}-{n}")

        price = Spend(1, {}).prices["samUsdPerImage"]
        # Only the enemy is named on this probe, so the player is not asked about (tests/test_jit_pixel_player.py).
        need = len(FRAMES) * pixel.MAX_BOXES * 3 * 3 * price
        state = {"pixel": {"observer": observer, "frameRunner": object()}}
        run_mod._pixel_stage([check()], {PROBE: (ROUTE,)}, ["bug.patch"], Path("cand.patch"), self.tmp, fake_replay,
                             Spend(need * 0.99, {}), 3, state, [])
        self.assertEqual(state["pixelChecks"][0]["status"], "not-run")
        self.assertIn("OUT_OF_BUDGET", state["pixelChecks"][0]["reason"])
        self.assertEqual(client.calls, 0)

        spend = Spend(need, {})
        run_mod._pixel_stage([check()], {PROBE: (ROUTE,)}, ["bug.patch"], Path("cand.patch"), self.tmp, fake_replay,
                             spend, 3, state, [])
        row = state["pixelChecks"][0]
        # The scripted SAM finds every enemy on the clean game and the bug build alike: not kept, but judged.
        self.assertEqual((row["status"], row["reason"]), ("dropped", "does-not-fail-on-bug"))
        self.assertEqual(row["clean"], ["pass"] * 3)
        self.assertEqual(spend.sam_images, client.calls)
        self.assertEqual(client.calls, 2 * 3 * len(FRAMES) * 2)


class TheThreeJobsCarryTheNamedObjects(Scratch):
    def test_the_capture_says_which_objects_and_asking_reads_and_budgets_them(self):
        run_dir = replay(self.tmp / "work" / "pixel-base" / f"{PROBE}-1")
        store = self.tmp / "store"
        dest = pixel_jobs.store_replay(run_dir, store, ROUTE, FRAMES, ["enemy"])
        self.assertEqual(pixel_jobs.objects_of(dest), ["enemy"])
        observer = SamAnchorObserver(Scripted())
        price = 0.0025
        with self.assertRaisesRegex(pixel_jobs.AskRefused, f"up to {len(FRAMES) * (1 + pixel.MAX_BOXES)} images"):
            pixel_jobs.ask(store, observer, len(FRAMES) * 2 * price, price)
        doc = pixel_jobs.ask(store, observer, 1.0, price)
        self.assertEqual(sorted(doc["runs"][0]["objects"]), ["enemy"])
        self.assertEqual(doc["stats"]["calls"], len(FRAMES) * 3)

    def test_a_forged_objects_file_is_refused(self):
        run_dir = replay(self.tmp / "work" / "pixel-base" / f"{PROBE}-1")
        dest = pixel_jobs.store_replay(run_dir, self.tmp / "store", ROUTE, FRAMES)
        self.assertEqual(pixel_jobs.objects_of(dest), [])
        for forged in ({"objects": ["coin"]}, {"objects": ["enemy", "enemy"]}, {"objects": ["enemy"], "more": 1},
                       {"objects": "enemy"}):
            with self.subTest(forged=forged):
                (dest / pixel_jobs.OBJECTS_FILE).write_text(json.dumps(forged), encoding="utf-8")
                with self.assertRaises(pixel_jobs.StoreError):
                    pixel_jobs.objects_of(dest)
        with self.assertRaises(pixel_jobs.StoreError):
            pixel_jobs.store_replay(run_dir, self.tmp / "store2", ROUTE, FRAMES, ["coin"])


if __name__ == "__main__":
    unittest.main()
