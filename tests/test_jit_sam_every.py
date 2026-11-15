"""How often a frame is asked about: ``--sam-every`` (#286; expectrail/jit/sam_observer.py, cli.py).

Offline. Until now the SAM observer asked about every 10th frame and the last, with no way to change it
from the command line, so a probe naming the enemy or the bullet could reserve more than the $2
per-change cap at MAX_FRAMES. ``--sam-every N`` sets it, from 1 to 60, in every job of one change.

The plan of frames must be the same in the job that asks SAM and the job that judges from its answers.
A recorded answer file carries the frames each run was asked about (``framesProbed``, else its rows), and
the observer refuses, before it sends anything, to judge or ask from a recording whose plan is not its
own: a denser plan would stop part way on a frame the recording never saw, and a sparser one would judge
fewer frames than were paid for.

SAM's answers are the recorded ones in tests/data/sam-anchor/; for the sparser plan, a copy of that
recording keeps only the frames that plan asks about (each answer as SAM gave it), so the three jobs can
be shown end to end with ``--sam-every 20``. Nothing is sent or spent."""
from __future__ import annotations

import contextlib
import io
import json
import unittest
from pathlib import Path

from expectrail.jit import cli, pixel, pixel_jobs
from expectrail.jit import run as run_mod
from expectrail.jit.sam_observer import DEFAULT_EVERY, MAX_EVERY, MAX_FRAMES, RecordedSamClient, SamAnchorObserver
from tests.test_jit_cli_observer import RECORDED, args_of
from tests.test_jit_pixel_jobs import SAM, SETTING, Jobs
from tests.test_jit_sam_observer import BOX, PROBE, ROUTE, RUNS, Scratch, boxed, make_run, rows_from

PX = "signals-reach-evidence-pixel"
LONG = {**ROUTE, "ticks": 582}   # frames 0 to 290 at 60 fps and 120 ticks a second: 30 at every 10th
CAP_USD = 2.0
USD_PER_IMAGE = 0.0025
RUNS_A_CHECK = 9   # three clean, three bug, three candidate


def sparser_recording(path: Path, every: int) -> Path:
    """A copy of the smoke recording that was asked about only the frames ``every`` plans within 120."""
    doc = json.loads(BOX.read_text(encoding="utf-8"))
    plan = SamAnchorObserver(object(), box=(48, 68), lift=17.0, first=120, every=every).frames(ROUTE)
    for run in doc["runs"]:
        run["framesProbed"] = plan
        run["frames"] = [f for f in run["frames"] if f["frame"] in plan]
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


class TheSettingPlansTheFrames(unittest.TestCase):
    def test_the_default_is_unchanged(self):
        self.assertEqual(DEFAULT_EVERY, 10)
        self.assertEqual(SamAnchorObserver(object()).frames(ROUTE), [*range(0, 170, 10), 169])

    def test_every_twentieth_frame_and_the_last(self):
        self.assertEqual(SamAnchorObserver(object(), every=20).frames(ROUTE), [*range(0, 170, 20), 169])

    def test_a_denser_setting_is_still_held_to_max_frames(self):
        frames = SamAnchorObserver(object(), every=1).frames(LONG)
        self.assertLessEqual(len(frames), MAX_FRAMES)
        self.assertEqual((frames[0], frames[-1]), (0, 290))

    def test_one_to_sixty_and_nothing_else(self):
        self.assertEqual(MAX_EVERY, 60)
        for every in (1, 60):
            self.assertEqual(SamAnchorObserver(object(), every=every).every, every)
        for every in (0, -1, 61, 1000, 2.5, True, "20"):
            with self.subTest(every=every), self.assertRaises(ValueError):
                SamAnchorObserver(object(), every=every)

    def test_a_sparser_plan_fits_a_named_role_under_the_cap(self):
        """The case #523 left open: a probe whose check names the enemy only and whose route fills the
        plan (582 ticks). At every 10th frame it reserves 30 frames x 3 boxes x 9 runs, $2.025; at every
        20th, 16 frames, $1.08."""
        def usd(every):
            images = SamAnchorObserver(object(), every=every).most_images(LONG, ["enemy"], player=False)
            return images, images * RUNS_A_CHECK * USD_PER_IMAGE

        images10, usd10 = usd(10)
        images20, usd20 = usd(20)
        self.assertEqual(images10, 30 * pixel.MAX_BOXES)
        self.assertGreater(usd10, CAP_USD)
        self.assertEqual(images20, 16 * pixel.MAX_BOXES)
        self.assertLessEqual(usd20, CAP_USD)


class TheRecordedPlanMustBeTheObserversPlan(Scratch):
    def setUp(self):
        super().setUp()
        self.run_dir = make_run(self.tmp / "clean", PROBE, rows_from(RUNS["clean"], 340))

    def refused_before_asking(self, observer):
        with self.assertRaisesRegex(pixel.PixelError, "same --sam-every and --sam-first") as ctx:
            observer(self.run_dir, ROUTE)
        self.assertEqual(observer.client.calls, 0)
        return ctx.exception

    def test_the_recorded_plan_is_read_back(self):
        client = RecordedSamClient(BOX, "clean")
        self.assertEqual(client.plan_of(self.run_dir / "frames" / "f00000000.png"), RUNS["clean"]["framesProbed"])
        self.assertIsNone(RecordedSamClient(BOX, "nowhere").plan_of(self.run_dir / "frames" / "f00000000.png"))

    def test_the_same_plan_is_asked_as_before(self):
        answer = boxed(RecordedSamClient(BOX, "clean"))(self.run_dir, ROUTE)
        self.assertEqual(answer["run"]["framesProbed"], RUNS["clean"]["framesProbed"])

    def test_a_sparser_plan_is_refused_though_the_recording_holds_its_frames(self):
        observer = SamAnchorObserver(RecordedSamClient(BOX, "clean"), box=(48, 68), lift=17.0, first=120, every=20)
        self.assertTrue(set(observer.frames(ROUTE)) < set(RUNS["clean"]["framesProbed"]))
        self.refused_before_asking(observer)

    def test_a_denser_plan_is_refused_before_the_first_question(self):
        observer = SamAnchorObserver(RecordedSamClient(BOX, "clean"), box=(48, 68), lift=17.0, first=120, every=5)
        self.refused_before_asking(observer)

    def test_another_first_is_refused(self):
        observer = SamAnchorObserver(RecordedSamClient(BOX, "clean"), box=(48, 68), lift=17.0, first=60)
        self.refused_before_asking(observer)

    def test_a_recording_without_frames_probed_is_held_to_its_rows(self):
        doc = json.loads(BOX.read_text(encoding="utf-8"))
        for run in doc["runs"]:
            run.pop("framesProbed")
        path = self.tmp / "no-plan.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        self.assertEqual(RecordedSamClient(path, "clean").plans["clean"], RUNS["clean"]["framesProbed"])
        boxed(RecordedSamClient(path, "clean"))(self.run_dir, ROUTE)
        self.refused_before_asking(SamAnchorObserver(RecordedSamClient(path, "clean"), box=(48, 68), lift=17.0,
                                                     first=120, every=20))

    def test_a_matching_sparser_recording_is_asked_and_charges_its_frames(self):
        path = sparser_recording(self.tmp / "every-20.json", 20)
        client = RecordedSamClient(path, "clean")
        answer = SamAnchorObserver(client, box=(48, 68), lift=17.0, first=120, every=20)(self.run_dir, ROUTE)
        self.assertEqual(answer["run"]["framesProbed"], [0, 20, 40, 60, 80, 100, 119])
        self.assertEqual(answer["images"], sum(1 for f in answer["run"]["frames"] if f["asked"]))
        self.assertLessEqual(answer["images"], 7)


class TheCommandLineTakesIt(unittest.TestCase):
    def test_every_job_s_parser_takes_it(self):
        obs = cli.observer_from(args_of(*RECORDED, "--sam-every", "20"))
        self.assertEqual(obs.every, 20)
        self.assertEqual(cli.observer_from(args_of(*RECORDED)).every, DEFAULT_EVERY)
        capture = cli.observer_from(args_of(*SAM, "--pixel-capture", "unused", "--sam-every", "30"))
        self.assertEqual(capture.every, 30)

    def test_out_of_range_is_refused(self):
        for value in ("0", "61"):
            with self.subTest(every=value), self.assertRaises(cli.ObserverArgs):
                cli.observer_from(args_of(*SAM, "--sam-live", "--sam-every", value))

    def test_the_parser_exits_2_on_a_bad_value(self):
        for argv in (["pixel-ask", "--replays", "x", "--out", "y", "--budget-usd", "1", "--sam-live",
                      "--sam-every", "61"],
                     ["pixel-ask", "--replays", "x", "--out", "y", "--budget-usd", "1", "--sam-live",
                      "--sam-every", "ten"]):
            with self.subTest(argv=argv[-1]), contextlib.redirect_stderr(io.StringIO()), \
                    contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as stop:
                cli.main(argv)
            self.assertEqual(stop.exception.code, 2)


class TheThreeJobsAgreeOnThePlan(Jobs):
    def capture(self, fix, candidate_build, *extra):
        """The capture job into this test's own folder: tests/test_jit_pixel_jobs.py's shared capture is
        removed when that module's tests end, so it is not reused here."""
        from tests.test_jit_sam_observer import FrameGame

        builds = {"pixel-reference": "clean", "pixel-base": "layering_v1", "pixel-candidate": candidate_build}
        return self.run_cli(fix, self.tmp / "out-capture", ["--pixel-capture", str(self.store), *extra],
                            FrameGame(builds))

    def rehearse(self, recording, *extra):
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["pixel-ask", "--replays", str(self.store), "--out", str(self.answers),
                             "--budget-usd", "1", "--sam-answers", str(recording), *SETTING, *extra,
                             "--sam-run", "pixel-reference=clean", "--sam-run", "pixel-base=layering_v1",
                             "--sam-run", "pixel-candidate=layering_v1"])
        return code, json.loads(printed.getvalue())

    def test_asked_at_10_and_judged_at_20_judges_nothing(self):
        self.capture("fix-wrong", "layering_v1")
        self.assertEqual(self.rehearse(BOX)[0], 0)
        doc = self.run_cli("fix-wrong", self.tmp / "out-judge",
                           ["--sam-answers", str(self.answers), "--pixel-replays", str(self.store), "--sam-every", "20"])
        [row] = doc["pixelChecks"]
        self.assertEqual(row["status"], "dropped")
        self.assertIn("same --sam-every", row["reason"])
        self.assertEqual(doc["spend"]["samImages"], 0)

    def test_captured_at_10_and_asked_at_5_asks_nothing(self):
        self.capture("fix-wrong", "layering_v1")
        code, printed = self.rehearse(BOX, "--sam-every", "5")
        self.assertEqual(code, 0)
        self.assertEqual(printed["calls"], 0)
        doc = json.loads(self.answers.read_text())
        self.assertEqual(doc["runs"], [])
        self.assertIn("which is asked about, is missing", doc["stopped"])

    def test_every_20_in_all_three_jobs_catches_the_wrong_fix_on_fewer_images(self):
        captured = self.capture("fix-wrong", "layering_v1", "--sam-every", "20")
        self.assertEqual(captured["spend"]["samImages"], 0)
        kept = sorted(p.name for p in (self.store / "pixel-base" / f"{PROBE}-1" / "frames").iterdir())
        self.assertEqual(kept, [f"f{n:08d}.png" for n in (0, 20, 40, 60, 80, 100, 119)])
        recording = sparser_recording(self.tmp / "every-20.json", 20)
        code, printed = self.rehearse(recording, "--sam-every", "20")
        self.assertEqual(code, 0, printed)
        self.assertIsNone(json.loads(self.answers.read_text())["stopped"])
        self.assertEqual(printed["plannedImages"], 7 * 9)
        doc = self.run_cli("fix-wrong", self.tmp / "out-judge",
                           ["--sam-answers", str(self.answers), "--pixel-replays", str(self.store), "--sam-every", "20"])
        [row] = doc["pixelChecks"]
        self.assertEqual((row["status"], row["outcome"]), ("kept", "catch"), row["reason"])
        self.assertLessEqual(doc["spend"]["samImages"], 7 * 9)
        self.assertEqual(run_mod.from_base_alone(doc)["pixelReproducing"], ["jit-px-player-drawn"])
        self.assertEqual([n for n, _ in pixel_jobs.replays(self.store)][0], f"pixel-reference/{PROBE}-1")


if __name__ == "__main__":
    unittest.main()
