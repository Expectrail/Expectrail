"""The capture folder keeps only what the later jobs read (#286; expectrail/jit/pixel_jobs.py, ``store_replay``).

Offline. A bench probe's replay with frames is mostly frames nobody asks about: hold-right made 170 frames
and a 39.5 MB folder on Godot 4.7.2, of which the observer asks about 18 (the measurement is in
docs/new-work/2026-11-15-trim-pixel-capture.md). These tests show that a kept replay holds only its
replay.json, trace.json, route and the frames the observer plans; that the observer judges a kept replay
exactly as it judges the full one; and that a kept replay missing a frame it asks about is refused, never
turned into a gap. The replay folders are the synthetic ones of tests/test_jit_sam_observer.py."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail.jit import pixel, pixel_jobs
from expectrail.jit import run as run_mod
from expectrail.jit.sam_observer import RecordedSamClient
from tests.test_jit_pixel_jobs import Jobs
from tests.test_jit_sam_observer import (
    BOX,
    PROBE,
    ROUTE,
    RUNS,
    SIZE,
    FrameGame,
    boxed,
    make_run,
    png,
    rows_from,
)

PLANNED = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 119]   # boxed(): every 10th of the first 120, and 119


class Scratch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.full = make_run(self.tmp / "out" / "pixel-reference" / f"{PROBE}-1", PROBE, rows_from(RUNS["clean"], 340))
        # What a real replay folder also holds (harness/run.py): the game's working copy, the log, the sound.
        (self.full / "work").mkdir()
        (self.full / "work" / "game.gd").write_text("extends Node\n")
        (self.full / "godot.log").write_text("Godot Engine v4.7.2\n")
        (self.full / "frames" / "f.wav").write_bytes(b"RIFF")
        self.store = self.tmp / "store"

    def kept(self, frames=PLANNED) -> Path:
        return pixel_jobs.store_replay(self.full, self.store, ROUTE, frames)


class AKeptReplayHoldsOnlyWhatIsRead(Scratch):
    def test_only_the_records_the_route_and_the_planned_frames(self):
        self.assertEqual(boxed(object()).frames(ROUTE), PLANNED)
        dest = self.kept()
        self.assertEqual(sorted(p.name for p in dest.iterdir()), ["frames", "replay.json", "route.json", "trace.json"])
        self.assertEqual(sorted(p.name for p in (dest / "frames").iterdir()), [f"f{n:08d}.png" for n in PLANNED])
        self.assertEqual((dest / "replay.json").read_bytes(), (self.full / "replay.json").read_bytes())
        self.assertEqual((dest / "trace.json").read_bytes(), (self.full / "trace.json").read_bytes())
        self.assertEqual(json.loads((dest / "route.json").read_text()), ROUTE)
        self.assertEqual([n for n, _ in pixel_jobs.replays(self.store)], [f"pixel-reference/{PROBE}-1"])

    def test_a_planned_frame_the_replay_did_not_capture_is_not_made_up(self):
        dest = self.kept([0, 10, 500])
        self.assertEqual(sorted(p.name for p in (dest / "frames").iterdir()), ["f00000000.png", "f00000010.png"])

    def test_a_negative_frame_is_refused(self):
        with self.assertRaises(pixel_jobs.StoreError):
            self.kept([0, -1])

    def test_anything_else_in_a_replay_folder_is_refused(self):
        def work(d):
            (d / "work").mkdir()

        def log(d):
            (d / "godot.log").write_text("x")

        def sound(d):
            (d / "frames" / "f.wav").write_bytes(b"RIFF")

        def nested(d):
            (d / "frames" / "deeper").mkdir()

        for label, spoil in (("the game's working copy", work), ("the log", log), ("the sound", sound),
                             ("a folder among the frames", nested)):
            with self.subTest(label):
                shutil.rmtree(self.store, True)
                dest = self.kept()
                spoil(dest)
                with self.assertRaisesRegex(pixel_jobs.StoreError, "kept"):
                    pixel_jobs.replays(self.store)
                route = self.tmp / "route.json"
                route.write_text(json.dumps(ROUTE))
                with self.assertRaisesRegex(pixel_jobs.StoreError, "kept"):
                    pixel_jobs.StoredReplays(self.store)(route, self.tmp / "judge" / "pixel-reference" / f"{PROBE}-1")


class TheObserverJudgesAKeptReplayAsTheFullOne(Scratch):
    def observe(self, run_dir):
        return boxed(RecordedSamClient(BOX, "clean"))(run_dir, ROUTE)

    def test_the_same_answer_and_the_same_images(self):
        full, kept = self.observe(self.full), self.observe(self.kept())
        full["run"]["run"] = kept["run"]["run"]
        self.assertEqual(kept, full)
        self.assertEqual(kept["images"], len(PLANNED))

    def test_a_kept_replay_missing_a_frame_it_asks_about_is_refused(self):
        dest = self.kept()
        (dest / "frames" / "f00000030.png").unlink()
        with self.assertRaisesRegex(pixel.PixelError, "frame 30, which is asked about, is missing"):
            self.observe(dest)

    def test_a_frame_beyond_the_replay_s_count_is_refused(self):
        dest = self.kept()
        png(dest / "frames" / "f00000170.png", SIZE, 170)
        with self.assertRaisesRegex(pixel.PixelError, "not the replay's"):
            self.observe(dest)

    def test_a_kept_frame_that_is_not_the_replay_s_is_refused(self):
        dest = self.kept()
        png(dest / "frames" / "f00000020.png", SIZE, 999)
        with self.assertRaisesRegex(pixel.PixelError, "frame 20 on disk is not the frame the replay recorded"):
            self.observe(dest)

    def test_a_short_replay_s_late_frames_stay_gaps_when_kept(self):
        short = make_run(self.tmp / "out" / "pixel-base" / f"{PROBE}-1", PROBE, rows_from(RUNS["clean"], 340), frames=101)
        dest = pixel_jobs.store_replay(short, self.store, ROUTE, PLANNED)
        full, kept = self.observe(short), self.observe(dest)
        full["run"]["run"] = kept["run"]["run"]
        self.assertEqual(kept, full)
        self.assertEqual([f["frame"] for f in kept["run"]["frames"] if not f["asked"]], [110, 119])


class TheCaptureJobKeepsOnlyThePlannedFrames(Jobs):
    def test_every_kept_replay_holds_the_planned_frames_alone(self):
        # Captured here, not from tests/test_jit_pixel_jobs.py's module cache, which that module removes.
        builds = {"pixel-reference": "clean", "pixel-base": "layering_v1", "pixel-candidate": "layering_v1"}
        self.run_cli("fix-wrong", self.tmp / "out-capture", ["--pixel-capture", str(self.store)], FrameGame(builds))
        for name, folder in pixel_jobs.replays(self.store):
            with self.subTest(name):
                self.assertEqual(sorted(p.name for p in (folder / "frames").iterdir()),
                                 [f"f{n:08d}.png" for n in PLANNED])
                self.assertEqual(json.loads((folder / "replay.json").read_text())["capture"]["frames"], 170)

    def test_an_observer_that_cannot_plan_keeps_nothing_for_that_probe(self):
        class Unplannable:
            def frames(self, route):
                raise pixel.PixelError("no plan")

        made = []
        run_mod._pixel_capture({PROBE: [{}]}, {PROBE: (ROUTE, None)}, [Path("bug.patch")], Path("fix.patch"),
                               self.tmp, lambda *a, **k: made.append(a), 3, self.store, object(), Unplannable())
        self.assertEqual(made, [])
        self.assertEqual(list(self.store.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
