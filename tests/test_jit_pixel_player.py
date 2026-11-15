"""The player is asked about only when a check on the probe names it (#286).

Until now the observer asked SAM about the player on every planned frame of every pixel replay, even when
every check on the probe was about the enemy or the bullet. Those player images were reserved against the
change's cap and sent, and judged nothing. Now a probe whose checks name only roles the game has many of
(``pixel.named``) is asked about their boxes and nothing else: the replay, the capture job and the asking
job all reserve and send that, and an answer that says it asked about the player anyway is refused.

Offline. The replays are synthetic run folders (tests/test_jit_pixel_named.py ``replay``) and SAM is a
scripted client. No model is called and nothing is spent."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail.jit import pixel, pixel_jobs
from expectrail.jit import run as run_mod
from expectrail.jit.run import Spend
from expectrail.jit.sam_observer import NAME, RecordedSamClient, SamAnchorObserver
from tests.test_jit_pixel_named import FRAMES, PROBE, ROUTE, Scripted, check, replay

ENEMY_BOXES = ([96, 16, 124, 44], [146, 56, 174, 84])   # the two enemies' logged boxes, widened by 4 px


def player_check(**kw) -> dict:
    return {**check(**kw), "id": "jit-px-player-drawn", "object": "player"}


class Scratch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pixel-player-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def ask(self, client=None, objects=("enemy",), player=False, name="pixel-base"):
        client = client or Scripted()
        observer = SamAnchorObserver(client)
        folder = self.tmp / name / f"{PROBE}-1"
        if not folder.exists():
            replay(folder)
        return pixel.observe(observer, folder, ROUTE, objects, player), client


class WhichProbesAskAboutThePlayer(unittest.TestCase):
    def test_only_a_check_about_the_player_asks_about_it(self):
        self.assertFalse(pixel.asks_player([check()]))
        self.assertFalse(pixel.asks_player([check(), {**check(), "object": "bullet"}]))
        self.assertTrue(pixel.asks_player([check(), player_check()]))
        self.assertTrue(pixel.asks_player([player_check()]))

    def test_a_frame_costs_the_player_only_when_it_is_asked_about(self):
        self.assertEqual(pixel.images_per_frame(True, ()), 1)
        self.assertEqual(pixel.images_per_frame(False, ("enemy",)), pixel.MAX_BOXES)
        self.assertEqual(pixel.images_per_frame(True, ("enemy", "bullet")), 1 + 2 * pixel.MAX_BOXES)
        observer = SamAnchorObserver(Scripted())
        self.assertEqual(observer.most_images(ROUTE, ["enemy"], player=False), len(FRAMES) * pixel.MAX_BOXES)
        self.assertEqual(observer.most_images(ROUTE, ["enemy"]), len(FRAMES) * (1 + pixel.MAX_BOXES))


class TheObserverAsksOnlyAboutTheNamedObjects(Scratch):
    def test_no_player_image_is_sent_and_every_player_row_says_why(self):
        (_, run, images), client = self.ask()
        self.assertEqual(images, len(FRAMES) * 2)
        self.assertEqual(images, client.calls)
        self.assertEqual(sorted({tuple(b) for _, b in client.asked}), sorted(tuple(b) for b in ENEMY_BOXES))
        self.assertEqual([r["frame"] for r in run["frames"]], FRAMES)
        self.assertTrue(all(not r["asked"] and r["note"] == pixel.NOT_ASKED_PLAYER for r in run["frames"]))
        self.assertEqual(run["summary"]["asked"], 0)

    def test_the_enemy_is_judged_the_same_with_or_without_the_player(self):
        (_, without, _), _ = self.ask()
        (_, with_player, _), _ = self.ask(player=True, name="pixel-reference")
        self.assertEqual(without["objects"], with_player["objects"])
        self.assertEqual(pixel.judge(check(), without), pixel.judge(check(), with_player))
        self.assertEqual(pixel.judge(check(), without)["result"], "pass")

    def test_a_check_about_the_player_on_such_a_run_is_needs_review_never_a_pass(self):
        (_, run, _), _ = self.ask()
        got = pixel.judge(player_check(), run)
        self.assertEqual(got["result"], "needs-review")
        self.assertIn(pixel.NOT_ASKED_PLAYER, got["reason"])

    def test_asking_about_nothing_is_refused_before_anything_is_sent(self):
        client = Scripted()
        with self.assertRaisesRegex(pixel.PixelError, "asked about nothing"):
            self.ask(client, objects=())
        with self.assertRaisesRegex(pixel.PixelError, "asked about nothing"):
            SamAnchorObserver(client)(self.tmp / "pixel-base" / f"{PROBE}-1", ROUTE, player=False)
        self.assertEqual(client.calls, 0)

    def test_the_frames_are_still_checked_against_the_replay_before_any_box_is_asked(self):
        folder = replay(self.tmp / "pixel-base" / f"{PROBE}-1")
        frame = folder / "frames" / "f00000010.png"
        frame.write_bytes(frame.read_bytes() + b"\0")
        client = Scripted()
        with self.assertRaisesRegex(pixel.PixelError, "frame 10 on disk is not the frame the replay recorded"):
            self.ask(client)
        self.assertEqual(client.calls, 0)

    def test_an_answer_that_says_it_asked_about_the_player_is_refused(self):
        (_, run, _), _ = self.ask(player=True)

        class Fixed:
            name = NAME

            def __call__(self, run_dir, route, objects=(), player=True):
                return {"setting": {"model": "sam-3.1"}, "run": run, "images": 0}
        with self.assertRaisesRegex(pixel.PixelError, "not asked about the player, and its answer says it asked"):
            pixel.observe(Fixed(), self.tmp, ROUTE, ("enemy",), False)
        self.assertEqual(pixel.observe(Fixed(), self.tmp, ROUTE, ("enemy",), True)[1], run)

    def test_recorded_answers_with_the_player_replay_without_it(self):
        (_, run, _), _ = self.ask(player=True)
        doc = {"model": "sam-3.1", "lift": 0.0, "box": "body", "pad": 4.0, "runs": [{**run, "run": "x"}]}
        path = self.tmp / "answers.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        (_, again, images), client = self.ask(RecordedSamClient(path, "x"))
        self.assertEqual(again["objects"], run["objects"])
        self.assertEqual(images, len(FRAMES) * 2)


class TheReplayReservesAndAsksPerProbe(Scratch):
    def stage(self, checks, spend):
        client = Scripted()
        observer = SamAnchorObserver(client)

        def fake_replay(name, patches, pid, n, with_runner=None):
            replay(self.tmp / "jit-replays" / name / f"{pid}-{n}")

        state = {"pixel": {"observer": observer, "frameRunner": object()}}
        run_mod._pixel_stage(checks, {PROBE: (ROUTE,)}, ["bug.patch"], Path("cand.patch"), self.tmp, fake_replay,
                             spend, 3, state, [])
        return state["pixelChecks"], client

    def test_a_probe_with_only_an_enemy_check_reserves_and_sends_no_player_image(self):
        price = Spend(1, {}).prices["samUsdPerImage"]
        need = len(FRAMES) * pixel.MAX_BOXES * 3 * 3 * price
        rows, client = self.stage([check()], Spend(need, {}))
        self.assertEqual(rows[0]["status"], "dropped")
        self.assertNotIn("OUT_OF_BUDGET", rows[0]["reason"] or "")
        self.assertTrue(all(tuple(b) in {tuple(e) for e in ENEMY_BOXES} for _, b in client.asked))
        self.assertEqual(client.calls, 2 * 3 * len(FRAMES) * 2)

    def test_a_probe_that_also_names_the_player_reserves_it_and_asks_it(self):
        price = Spend(1, {}).prices["samUsdPerImage"]
        need = len(FRAMES) * (1 + pixel.MAX_BOXES) * 3 * 3 * price
        rows, client = self.stage([check(), player_check()], Spend(need * 0.99, {}))
        self.assertTrue(all(r["status"] == "not-run" and "OUT_OF_BUDGET" in r["reason"] for r in rows))
        self.assertEqual(client.calls, 0)
        rows, client = self.stage([check(), player_check()], Spend(need, {}))
        self.assertTrue(all(r["status"] == "dropped" for r in rows), rows)
        self.assertEqual(client.calls, 2 * 3 * len(FRAMES) * 3)


class TheThreeJobsCarryWhetherThePlayerIsAsked(Scratch):
    def stored(self, store, objects=("enemy",), player=False):
        run_dir = replay(self.tmp / "work" / "pixel-base" / f"{PROBE}-1")
        return pixel_jobs.store_replay(run_dir, store, ROUTE, FRAMES, list(objects), player)

    def test_the_capture_says_so_and_asking_budgets_and_sends_only_the_boxes(self):
        store = self.tmp / "store"
        dest = self.stored(store)
        self.assertEqual(json.loads((dest / pixel_jobs.OBJECTS_FILE).read_text()),
                         {"objects": ["enemy"], "player": False})
        self.assertEqual(pixel_jobs.asked_of(dest), (False, ["enemy"]))
        observer = SamAnchorObserver(Scripted())
        price = 0.0025
        with self.assertRaisesRegex(pixel_jobs.AskRefused, f"up to {len(FRAMES) * pixel.MAX_BOXES} images"):
            pixel_jobs.ask(store, observer, len(FRAMES) * 2 * price, price)
        doc = pixel_jobs.ask(store, observer, len(FRAMES) * pixel.MAX_BOXES * price, price)
        self.assertEqual(doc["stats"]["calls"], len(FRAMES) * 2)
        self.assertTrue(all(not r["asked"] for r in doc["runs"][0]["frames"]))

    def test_the_player_alone_and_the_player_with_objects_read_back_as_before(self):
        self.assertFalse((self.stored(self.tmp / "a", (), True) / pixel_jobs.OBJECTS_FILE).exists())
        self.assertEqual(pixel_jobs.asked_of(self.tmp / "a" / "pixel-base" / f"{PROBE}-1"), (True, []))
        dest = self.stored(self.tmp / "b", ("enemy",), True)
        self.assertEqual(json.loads((dest / pixel_jobs.OBJECTS_FILE).read_text()), {"objects": ["enemy"]})
        self.assertEqual(pixel_jobs.asked_of(dest), (True, ["enemy"]))

    def test_asking_about_nothing_or_a_forged_file_is_refused(self):
        with self.assertRaisesRegex(pixel_jobs.StoreError, "asked about nothing"):
            self.stored(self.tmp / "none", (), False)
        with self.assertRaises(pixel_jobs.StoreError):
            self.stored(self.tmp / "odd", ("enemy",), "no")
        dest = self.stored(self.tmp / "store")
        for forged in ({"objects": [], "player": False}, {"objects": ["enemy"], "player": True},
                       {"objects": ["enemy"], "player": 0}, {"objects": ["enemy"], "player": "false"},
                       {"player": False}, {"objects": ["enemy"], "player": False, "more": 1}):
            with self.subTest(forged=forged):
                (dest / pixel_jobs.OBJECTS_FILE).write_text(json.dumps(forged), encoding="utf-8")
                with self.assertRaises(pixel_jobs.StoreError):
                    pixel_jobs.asked_of(dest)

    def test_the_capture_job_writes_what_the_probe_asks(self):
        builds_seen = []

        def fake_replay(name, patches, pid, n, with_runner=None):
            builds_seen.append(name)
            replay(self.tmp / "jit-replays" / name / f"{pid}-{n}")

        store = self.tmp / "capture"
        run_mod._pixel_capture({PROBE: [check()]}, {PROBE: (ROUTE, None)}, [Path("bug.patch")], Path("fix.patch"),
                               self.tmp, fake_replay, 3, store, object(), SamAnchorObserver(Scripted()))
        found = pixel_jobs.replays(store)
        self.assertEqual(len(found), 9)
        self.assertTrue(all(pixel_jobs.asked_of(folder) == (False, ["enemy"]) for _, folder in found))
        run_mod._pixel_capture({PROBE: [check(), player_check()]}, {PROBE: (ROUTE, None)}, [Path("bug.patch")],
                               Path("fix.patch"), self.tmp, fake_replay, 3, store, object(),
                               SamAnchorObserver(Scripted()))
        self.assertTrue(all(pixel_jobs.asked_of(folder) == (True, ["enemy"]) for _, folder in pixel_jobs.replays(store)))


if __name__ == "__main__":
    unittest.main()
