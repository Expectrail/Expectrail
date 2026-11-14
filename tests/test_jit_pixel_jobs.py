"""Pixel checks across three jobs: capture, ask, judge (#286; expectrail/jit/pixel_jobs.py).

Offline. The three steps go through ``cli.main`` as jit.yml would run them, with the simulated game
standing in for the engine (only the harness is replaced) and the model answering from a test transport.
SAM's answers are the recorded ones in tests/data/sam-anchor/ (the bundled game's smoke route, asked with a
48 x 68 game px box 17 px above the origin): the asking step rehearses with ``--sam-answers`` in place of
``--sam-live``, so it asks exactly the questions a live call would, and nothing is sent or spent. The
replay folders are the synthetic ones of tests/test_jit_sam_observer.py, so these tests show the plumbing
and the refusals, not SAM on a bench probe."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail.contracts import validate_v1
from expectrail.jit import cli
from expectrail.jit import intent as intent_mod
from expectrail.jit import offer as offer_mod
from expectrail.jit import pixel, pixel_jobs
from expectrail.jit import run as run_mod
from expectrail.jit.sam_observer import RecordedSamClient, SamAnchorObserver
from tests.jit_fixtures import Case, JitGame, Transport, reply
from tests.test_jit_cli_observer import args_of
from tests.test_jit_sam_observer import BOX, DRAWN, LIFT, PROBE, FrameGame

PX = offer_mod.PIXEL
SAM = ["--observer", "sam-3.1-anchor"]
SETTING = ["--sam-box", "48x68", "--sam-lift", str(LIFT), "--sam-first", "120"]
IMAGES = 13   # images a replay: the recorded smoke route's frames 0 to 119, every 10th, and 119


_CAPTURED: dict = {}   # (fix, candidate build) -> (record, capture folder): made once, copied by each test
_SHARED = Path(tempfile.mkdtemp())


def tearDownModule():
    shutil.rmtree(_SHARED, True)


class Jobs(unittest.TestCase):
    """The three jobs of one change, each through the command line."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.case = Case()
        self.report = self.tmp / "report.txt"
        self.report.write_text("The player is drawn behind the scenery.", encoding="utf-8")
        self.store = self.tmp / "captured"
        self.answers = self.tmp / "answers.json"

    def run_cli(self, fix, out, extra, frame_game=None):
        real = run_mod.generate
        transport = Transport(reply({"candidates": [], "pixelChecks": [DRAWN]}))

        def with_stand_ins(*a, **kw):
            # The engine and the model are replaced. The frame runner stays the command line's own unless
            # this job captures (then the simulated game makes the frames).
            kw.update(runner=JitGame(), variants_fn=self.case.variants(), clock=lambda: 0.0,
                      intent=intent_mod.spark_intent(transport=transport, offer=PX))
            if frame_game is not None:
                kw["frame_runner"] = frame_game
            return real(*a, **kw)

        printed = io.StringIO()
        with mock.patch.object(cli, "generate", side_effect=with_stand_ins), contextlib.redirect_stdout(printed):
            code = cli.main(["run", "--report-file", str(self.report), "--candidate", str(self.case.patch(fix)),
                             "--base", str(self.case.patch("air-jump")), "--out", str(out), "--model", "off",
                             "--offer", PX, *SAM, *SETTING, *extra])
        self.assertEqual(code, 0)
        doc = json.loads((out / run_mod.RECORD_NAME).read_text(encoding="utf-8"))
        validate_v1(doc, "jit-run")
        return doc

    def capture(self, fix, candidate_build):
        """The capture job's record, and its folder copied to ``self.store`` (captured once a module)."""
        key = (fix, candidate_build)
        if key not in _CAPTURED:
            builds = {"pixel-reference": "clean", "pixel-base": "layering_v1", "pixel-candidate": candidate_build}
            store = _SHARED / f"{fix}-{candidate_build}"
            doc = self.run_cli(fix, store.with_name(store.name + "-out"), ["--pixel-capture", str(store)],
                               FrameGame(builds))
            _CAPTURED[key] = (doc, store)
        doc, store = _CAPTURED[key]
        shutil.copytree(store, self.store)
        return doc

    def ask(self, *extra, budget="1"):
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["pixel-ask", "--replays", str(self.store), "--out", str(self.answers),
                             "--budget-usd", budget, "--sam-answers", str(BOX), *SETTING, *extra])
        return code, json.loads(printed.getvalue())

    def rehearse_ask(self, candidate_build, budget="1"):
        # The recording names its runs by seeded build; the capture folder names them by replay.
        return self.ask("--sam-run", "pixel-reference=clean", "--sam-run", "pixel-base=layering_v1",
                        "--sam-run", f"pixel-candidate={candidate_build}", budget=budget)

    def judge(self, fix):
        return self.run_cli(fix, self.tmp / "out-judge",
                            ["--sam-answers", str(self.answers), "--pixel-replays", str(self.store)])

    def three_jobs(self, fix, candidate_build):
        captured = self.capture(fix, candidate_build)
        code, asked = self.rehearse_ask(candidate_build)
        self.assertEqual(code, 0, asked)
        return captured, asked, self.judge(fix)


class TheThreeJobsGiveTheOneJobResult(Jobs):
    def test_capture_asks_nothing_and_keeps_every_build_s_frames(self):
        doc = self.capture("fix-wrong", "layering_v1")
        self.assertEqual(doc["status"], "complete", doc["reason"])
        [row] = doc["pixelChecks"]
        self.assertEqual((row["status"], row["outcome"], row["reason"]), ("not-run", "not-evaluated", pixel_jobs.CAPTURED))
        self.assertEqual(doc["spend"]["samImages"], 0)
        self.assertEqual(run_mod.from_base_alone(doc)["pixelReproducing"], [])
        names = [name for name, _ in pixel_jobs.replays(self.store)]
        self.assertEqual(names, [f"{b}/{PROBE}-{n}" for b in pixel_jobs.BUILDS for n in (1, 2, 3)])
        for _, folder in pixel_jobs.replays(self.store):
            self.assertEqual(json.loads((folder / "route.json").read_text())["name"], PROBE)
            self.assertTrue((folder / "replay.json").is_file() and (folder / "frames").is_dir())

    def test_ask_runs_no_game_and_writes_one_run_a_replay(self):
        self.capture("fix-wrong", "layering_v1")
        with mock.patch("harness.run.run", side_effect=AssertionError("the asking job ran a game")):
            code, printed = self.rehearse_ask("layering_v1")
        self.assertEqual(code, 0)
        doc = json.loads(self.answers.read_text())
        self.assertIsNone(doc["stopped"])
        self.assertEqual([r["run"] for r in doc["runs"]], [n for n, _ in pixel_jobs.replays(self.store)])
        self.assertEqual((printed["calls"], printed["plannedImages"]), (IMAGES * 9, IMAGES * 9))
        self.assertEqual(pixel.setting_of(doc), RecordedSamClient(BOX, "").setting)

    def test_a_wrong_fix_is_caught_as_when_one_job_asks(self):
        _, _, doc = self.three_jobs("fix-wrong", "layering_v1")
        self.assertEqual(doc["status"], "complete", doc["reason"])
        [row] = doc["pixelChecks"]
        self.assertEqual((row["status"], row["outcome"]), ("kept", "catch"), row["reason"])
        self.assertEqual((row["clean"], row["bug"], row["candidate"]), (["pass"] * 3, ["fail"] * 3, ["fail"] * 3))
        self.assertEqual(doc["spend"]["samImages"], IMAGES * 9)
        self.assertEqual(run_mod.from_base_alone(doc)["pixelReproducing"], ["jit-px-player-drawn"])

    def test_a_good_fix_is_not_caught(self):
        _, _, doc = self.three_jobs("fix-good", "clean")
        [row] = doc["pixelChecks"]
        self.assertEqual((row["status"], row["outcome"]), ("kept", "no-catch"))

    def test_the_judging_job_never_runs_the_game_for_a_pixel_replay(self):
        self.capture("fix-wrong", "layering_v1")
        self.rehearse_ask("layering_v1")
        with mock.patch.object(FrameGame, "__call__", side_effect=AssertionError("frames were made again")):
            doc = self.judge("fix-wrong")
        self.assertEqual(doc["pixelChecks"][0]["outcome"], "catch")


class WhatTheJobsRefuse(Jobs):
    def setUp(self):
        super().setUp()
        self.capture("fix-wrong", "layering_v1")

    def test_a_replay_missing_from_the_answers_drops_its_checks(self):
        self.rehearse_ask("layering_v1")
        doc = json.loads(self.answers.read_text())
        doc["runs"] = [r for r in doc["runs"] if r["run"] != f"pixel-base/{PROBE}-2"]
        self.answers.write_text(json.dumps(doc))
        [row] = self.judge("fix-wrong")["pixelChecks"]
        self.assertEqual(row["status"], "dropped")
        self.assertIn("no run", row["reason"])

    def test_answers_asked_another_way_judge_nothing(self):
        self.rehearse_ask("layering_v1")
        out = self.tmp / "out-judge"
        doc = self.run_cli("fix-wrong", out, ["--sam-answers", str(self.answers), "--pixel-replays", str(self.store),
                                              "--sam-lift", "5"])
        [row] = doc["pixelChecks"]
        self.assertEqual(row["status"], "dropped")
        self.assertIn("recorded answers were asked with", row["reason"])

    def test_a_captured_replay_of_another_route_ends_the_judging_run(self):
        self.rehearse_ask("layering_v1")
        path = self.store / "pixel-base" / f"{PROBE}-1" / "route.json"
        route = json.loads(path.read_text())
        path.write_text(json.dumps({**route, "ticks": route["ticks"] + 2}))
        doc = self.judge("fix-wrong")
        self.assertEqual(doc["status"], "nothing-generated")
        self.assertIn("not of the route this run compiled", doc["reason"])
        self.assertFalse(any(r["status"] == "kept" for r in doc["pixelChecks"]))

    def test_a_frame_changed_after_capture_drops_its_checks(self):
        self.rehearse_ask("layering_v1")
        frame = self.store / "pixel-reference" / f"{PROBE}-1" / "frames" / "f00000010.png"
        frame.write_bytes(frame.read_bytes() + b"\0")
        [row] = self.judge("fix-wrong")["pixelChecks"]
        self.assertEqual(row["status"], "dropped")
        self.assertIn("not the frame the replay recorded", row["reason"])

    def test_over_budget_nothing_is_asked(self):
        with mock.patch.object(RecordedSamClient, "segment_in", side_effect=AssertionError("asked")):
            code, printed = self.rehearse_ask("layering_v1", budget="0.2")
        self.assertEqual(code, 1)
        self.assertFalse(printed["asked"])
        self.assertIn("over the budget", printed["reason"])
        self.assertFalse(self.answers.exists())

    def test_the_first_replay_that_cannot_be_asked_about_stops_the_asking(self):
        # pixel-base's replays are answered from a run the recording does not have.
        code, printed = self.ask("--sam-run", "pixel-reference=clean", "--sam-run", "pixel-base=nowhere",
                                 "--sam-run", "pixel-candidate=layering_v1")
        self.assertEqual(code, 0)
        doc = json.loads(self.answers.read_text())
        self.assertIn(f"pixel-base/{PROBE}-1", doc["stopped"])
        self.assertEqual([r["run"] for r in doc["runs"]], [f"pixel-reference/{PROBE}-{n}" for n in (1, 2, 3)])
        self.assertEqual(printed["calls"], IMAGES * 3 + 1)   # the stopped request is counted


class TheCaptureFolderIsUntrusted(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = self.tmp / "store"
        folder = self.store / "pixel-reference" / f"{PROBE}-1"
        (folder / "frames").mkdir(parents=True)
        (folder / "route.json").write_text(json.dumps({"name": PROBE, "ticks": 340}))
        self.folder = folder

    def test_a_good_layout_is_read(self):
        self.assertEqual([n for n, _ in pixel_jobs.replays(self.store)], [f"pixel-reference/{PROBE}-1"])

    def test_every_other_layout_is_refused(self):
        def link():
            os.symlink("/etc/hostname", self.folder / "trace.json")

        def stray():
            (self.store / "notes.txt").write_text("hi")

        def bad_build():
            (self.store / "pixel-other" / f"{PROBE}-1").mkdir(parents=True)

        def bad_name():
            (self.store / "pixel-base" / "Hold_Right").mkdir(parents=True)

        def too_many():
            for n in range(1, pixel_jobs.MAX_REPLAYS + 1):
                (self.store / "pixel-base" / f"p{n}-1").mkdir(parents=True)

        def linked_store():
            shutil.move(str(self.store), str(self.tmp / "real"))
            os.symlink(self.tmp / "real", self.store)

        for label, spoil in (("a symbolic link", link), ("a stray file", stray), ("another build", bad_build),
                             ("a folder not named <probe>-<n>", bad_name), ("too many replays", too_many),
                             ("a linked capture folder", linked_store)):
            with self.subTest(label):
                self.setUp()
                spoil()
                with self.assertRaises(pixel_jobs.StoreError):
                    pixel_jobs.replays(self.store)

    def test_an_empty_folder_and_a_route_without_ticks_are_refused(self):
        shutil.rmtree(self.store / "pixel-reference")
        with self.assertRaisesRegex(pixel_jobs.StoreError, "no replay"):
            pixel_jobs.replays(self.store)
        self.setUp()
        (self.folder / "route.json").write_text(json.dumps({"name": PROBE}))
        observer = SamAnchorObserver(object())
        with self.assertRaisesRegex(pixel_jobs.StoreError, "not a route"):
            pixel_jobs.ask(self.store, observer, 1.0, 0.0025)

    def test_stored_replays_refuse_a_folder_that_is_not_kept(self):
        runner = pixel_jobs.StoredReplays(self.store)
        route = self.tmp / "route.json"
        route.write_text(json.dumps({"name": PROBE, "ticks": 340}))
        for run_dir, pattern in ((self.tmp / "out" / "pixel-base" / f"{PROBE}-1", "has no replay"),
                                 (self.tmp / "out" / "elsewhere" / f"{PROBE}-1", "no captured replay")):
            with self.subTest(str(run_dir)), self.assertRaisesRegex(pixel_jobs.StoreError, pattern):
                runner(route, run_dir)
        runner(route, self.tmp / "out" / "pixel-reference" / f"{PROBE}-1")
        self.assertTrue((self.tmp / "out" / "pixel-reference" / f"{PROBE}-1" / "frames").is_dir())


class TheObserverArgumentsForEachJob(unittest.TestCase):
    def test_capture_builds_an_observer_that_cannot_ask(self):
        obs = cli.observer_from(args_of(*SAM, "--pixel-capture", "dir"))
        self.assertIsInstance(obs, SamAnchorObserver)
        self.assertIsNone(obs._client)

    def test_wrong_combinations_are_refused(self):
        cases = {
            "capture with a live key": args_of(*SAM, "--sam-live", "--pixel-capture", "d"),
            "capture with recorded answers": args_of(*SAM, "--sam-answers", str(BOX), "--pixel-capture", "d"),
            "judging captured frames live": args_of(*SAM, "--sam-live", "--pixel-replays", "d"),
            "judging captured frames with no answers": args_of(*SAM, "--pixel-replays", "d"),
            "capture and judge in one job": args_of(*SAM, "--sam-answers", str(BOX), "--pixel-capture", "d",
                                                    "--pixel-replays", "d"),
            "capture without an observer": args_of("--pixel-capture", "d"),
            "captured frames without an observer": args_of("--pixel-replays", "d"),
            "capture without the pixel setting": args_of(*SAM, "--pixel-capture", "d", offer="baseline"),
        }
        for label, ns in cases.items():
            with self.subTest(label), self.assertRaises(cli.ObserverArgs):
                cli.observer_from(ns)

    def test_pixel_ask_needs_exactly_one_way_to_ask(self):
        for extra in ([], ["--sam-live", "--sam-answers", str(BOX)]):
            with self.subTest(extra), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
                cli.main(["pixel-ask", "--replays", "d", "--out", "o", "--budget-usd", "1", *extra])
            self.assertEqual(stop.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
