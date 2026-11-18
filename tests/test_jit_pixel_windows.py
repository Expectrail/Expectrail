"""The observer is asked only about the planned frames inside the checks' windows (#605).

A check judges only the planned frames in its window (expectrail/jit/pixel.py ``observations``), so the
in-process replay, the capture, the asking job and the judging job all plan the same frames: the observer's
plan inside the union of the windows of the checks on a probe (``pixel.planned``). These tests hold that
each of the four plans that way and they agree; that the windows the capture writes are read back as
untrusted data; that answers planned for other windows are refused by the judging run, never passed; that a
check whose window holds no planned frame is not run and asks for nothing; and that the bullet stand-in of
#286 now reserves 675 images ($1.69), not 1,296. Offline: no game, no model, no SAM call. The replay folders
and the recorded answers are those of tests/test_jit_sam_observer.py and tests/test_jit_pixel_jobs.py."""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail.contracts import validate_v1
from expectrail.jit import cli
from expectrail.jit import intent as intent_mod
from expectrail.jit import pixel, pixel_jobs
from expectrail.jit import run as run_mod
from expectrail.jit.sam_observer import RecordedSamClient, SamAnchorObserver
from tests.jit_fixtures import JitGame, Transport, reply
from tests.test_jit_pixel_jobs import PX, SAM, SETTING, Jobs
from tests.test_jit_sam_observer import BOX, DRAWN, PROBE, ROUTE, RUNS, FrameGame, boxed, make_run, rows_from

WINDOW = {"fromFrame": 30, "toFrame": 80}
WHOLE = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 119]   # boxed(): every 10th of the first 120, and 119
IN_WINDOW = [30, 40, 50, 60, 70, 80]


def windowed_recording(dst: Path, windows) -> Path:
    """The recorded answers of tests/data/sam-anchor/ as if asked only about the frames inside ``windows``."""
    doc = json.loads(BOX.read_text(encoding="utf-8"))
    for run in doc["runs"]:
        probed = run.get("framesProbed") or [f["frame"] for f in run["frames"]]
        keep = pixel.in_windows(probed, windows)
        run["framesProbed"] = keep
        run["frames"] = [f for f in run["frames"] if f["frame"] in keep]
    dst.write_text(json.dumps(doc), encoding="utf-8")
    return dst


class TheWindowsOfAProbe(unittest.TestCase):
    def test_each_window_once_in_a_fixed_order(self):
        checks = [{"id": "a", "window": {"fromFrame": 50}}, {"id": "b", "window": {"fromFrame": 10, "toFrame": 20}},
                  {"id": "c", "window": {"fromFrame": 50}}]
        self.assertEqual(pixel.probe_windows(checks), [{"fromFrame": 10, "toFrame": 20}, {"fromFrame": 50}])

    def test_a_check_without_a_window_asks_about_the_whole_route(self):
        self.assertIsNone(pixel.probe_windows([{"id": "a", "window": {"fromFrame": 50}}, {"id": "b"}]))
        self.assertEqual(pixel.in_windows(WHOLE, None), WHOLE)

    def test_the_union_of_the_windows(self):
        windows = [{"fromFrame": 10, "toFrame": 20}, {"fromFrame": 100}]
        self.assertEqual(pixel.in_windows(WHOLE, windows), [10, 20, 100, 110, 119])
        self.assertEqual(pixel.in_windows(WHOLE, [WINDOW]), IN_WINDOW)

    def test_a_window_that_holds_no_planned_frame_gives_nothing(self):
        self.assertEqual(pixel.in_windows(WHOLE, [{"fromFrame": 31, "toFrame": 39}]), [])
        self.assertEqual(pixel.in_windows(WHOLE, [{"fromFrame": 120}]), [])
        self.assertEqual(pixel.in_windows(WHOLE, [{"fromFrame": 80, "toFrame": 30}]), [])

    def test_a_malformed_window_is_refused(self):
        for bad in ({}, {"toFrame": 3}, {"fromFrame": -1}, {"fromFrame": True}, {"fromFrame": 1.5},
                    {"fromFrame": 0, "every": 2}, {"fromFrame": 0, "toFrame": "9"}, [0, 9], None,
                    {"fromFrame": pixel.MAX_WINDOW_FRAME + 1}):
            with self.subTest(bad=bad), self.assertRaises(pixel.PixelError):
                pixel.in_windows(WHOLE, [bad])


class TheObserverAsksOnlyInsideTheWindows(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.run_dir = make_run(self.tmp / "pixel-reference" / f"{PROBE}-1", PROBE, rows_from(RUNS["clean"], 340))
        self.windowed = windowed_recording(self.tmp / "windowed.json", [WINDOW])

    def test_it_plans_asks_and_reserves_the_window_s_frames(self):
        observer = boxed(RecordedSamClient(self.windowed, "clean"))
        self.assertEqual(pixel.planned(observer, ROUTE, [WINDOW]), IN_WINDOW)
        self.assertEqual(observer.most_images(ROUTE, windows=[WINDOW]), len(IN_WINDOW))
        self.assertEqual(observer.most_images(ROUTE), len(WHOLE))
        setting, run, images = pixel.observe(observer, self.run_dir, ROUTE, windows=[WINDOW])
        self.assertEqual((run["framesProbed"], [f["frame"] for f in run["frames"]], images),
                         (IN_WINDOW, IN_WINDOW, len(IN_WINDOW)))

    def test_the_window_s_verdict_is_the_whole_plan_s(self):
        check = {**DRAWN, "window": dict(WINDOW)}
        _, whole, _ = pixel.observe(boxed(RecordedSamClient(BOX, "clean")), self.run_dir, ROUTE)
        _, part, _ = pixel.observe(boxed(RecordedSamClient(self.windowed, "clean")), self.run_dir, ROUTE,
                                   windows=[WINDOW])
        self.assertEqual(pixel.judge(check, part), pixel.judge(check, whole))

    def test_answers_asked_about_the_whole_route_are_refused(self):
        # The judging job: answers planned for other windows stop the observer, so the checks are dropped.
        with self.assertRaisesRegex(pixel.PixelError, "asked about 13 frames.*plans 6"):
            pixel.observe(boxed(RecordedSamClient(BOX, "clean")), self.run_dir, ROUTE, windows=[WINDOW])

    def test_answers_asked_about_another_window_are_refused(self):
        other = windowed_recording(self.tmp / "other.json", [{"fromFrame": 40, "toFrame": 90}])
        with self.assertRaisesRegex(pixel.PixelError, "recorded answers were asked about 6 frames"):
            pixel.observe(boxed(RecordedSamClient(other, "clean")), self.run_dir, ROUTE, windows=[WINDOW])

    def test_windows_with_no_planned_frame_ask_nothing(self):
        client = RecordedSamClient(self.windowed, "clean")
        with self.assertRaisesRegex(pixel.PixelError, "hold no frame"):
            pixel.observe(boxed(client), self.run_dir, ROUTE, windows=[{"fromFrame": 31, "toFrame": 39}])
        self.assertEqual(client.calls, 0)

    def test_an_answer_about_frames_outside_the_windows_is_refused(self):
        real = boxed(RecordedSamClient(BOX, "clean"))

        class Ignores:
            """An observer that takes the windows and answers about its whole plan anyway."""
            name, frames, setting = real.name, real.frames, real.setting

            def __call__(self, run_dir, route, windows=None):
                return real(run_dir, route)

        with self.assertRaisesRegex(pixel.PixelError, "answer is about others"):
            pixel.observe(Ignores(), self.run_dir, ROUTE, windows=[WINDOW])


class TheCaptureKeepsTheWindows(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.full = make_run(self.tmp / "out" / "pixel-reference" / f"{PROBE}-1", PROBE, rows_from(RUNS["clean"], 340))
        self.store = self.tmp / "store"

    def kept(self, windows):
        return pixel_jobs.store_replay(self.full, self.store, ROUTE, pixel.in_windows(WHOLE, windows),
                                       windows=windows)

    def test_the_windows_and_their_frames_alone(self):
        dest = self.kept([WINDOW])
        self.assertEqual(json.loads((dest / pixel_jobs.WINDOWS_FILE).read_text()), {"windows": [WINDOW]})
        self.assertEqual(sorted(p.name for p in (dest / "frames").iterdir()), [f"f{n:08d}.png" for n in IN_WINDOW])
        self.assertEqual(pixel_jobs.windows_of(dest), [WINDOW])
        self.assertEqual([n for n, _ in pixel_jobs.replays(self.store)], [f"pixel-reference/{PROBE}-1"])

    def test_no_windows_writes_nothing_and_reads_as_the_whole_route(self):
        dest = pixel_jobs.store_replay(self.full, self.store, ROUTE, WHOLE)
        self.assertFalse((dest / pixel_jobs.WINDOWS_FILE).exists())
        self.assertIsNone(pixel_jobs.windows_of(dest))

    def test_malformed_windows_are_refused_when_read(self):
        dest = self.kept([WINDOW])
        for bad in ("not json", "[]", '{"windows": []}', '{"windows": [{"fromFrame": 30}], "every": 1}',
                    '{"windows": [{"fromFrame": -1}]}', '{"windows": [{"fromFrame": 30}, {"fromFrame": 30}]}',
                    json.dumps({"windows": [{"fromFrame": n} for n in range(pixel.MAX_PIXEL_CHECKS + 1)]}),
                    '{"windows": [{"fromFrame": 30, "toFrame": null}]}'):
            with self.subTest(bad=bad):
                (dest / pixel_jobs.WINDOWS_FILE).write_text(bad, encoding="utf-8")
                with self.assertRaises(pixel_jobs.StoreError):
                    pixel_jobs.windows_of(dest)

    def test_the_writer_refuses_what_the_reader_would(self):
        with self.assertRaises(pixel_jobs.StoreError):
            self.kept([])
        with self.assertRaises(pixel_jobs.StoreError):
            self.kept([WINDOW, WINDOW])

    def test_the_asking_job_reserves_and_asks_the_windows_frames(self):
        self.kept([WINDOW])
        observer = boxed(RecordedSamClient(windowed_recording(self.tmp / "w.json", [WINDOW]), "clean"))
        with self.assertRaisesRegex(pixel_jobs.AskRefused, r"need up to 6 images, \$0\.0150"):
            pixel_jobs.ask(self.store, observer, 0.01, 0.0025)
        doc = pixel_jobs.ask(self.store, observer, 1.0, 0.0025)
        self.assertIsNone(doc["stopped"])
        self.assertEqual((doc["stats"]["plannedImages"], doc["stats"]["calls"]), (6, 6))
        self.assertEqual(doc["runs"][0]["framesProbed"], IN_WINDOW)

    def test_the_asking_job_refuses_windows_that_hold_no_planned_frame(self):
        dest = self.kept([WINDOW])
        (dest / pixel_jobs.WINDOWS_FILE).write_text(json.dumps({"windows": [{"fromFrame": 31, "toFrame": 39}]}))
        client = RecordedSamClient(BOX, "clean")
        with self.assertRaisesRegex(pixel_jobs.AskRefused, "hold no frame"):
            pixel_jobs.ask(self.store, boxed(client), 1.0, 0.0025)
        self.assertEqual(client.calls, 0)

    def test_windows_naming_frames_the_capture_did_not_keep_are_refused(self):
        # A forged windows.json that widens the windows asks about frames the capture did not keep: refused.
        dest = self.kept([WINDOW])
        (dest / pixel_jobs.WINDOWS_FILE).write_text(json.dumps({"windows": [{"fromFrame": 0}]}))
        doc = pixel_jobs.ask(self.store, boxed(RecordedSamClient(BOX, "clean")), 1.0, 0.0025)
        self.assertEqual(doc["runs"], [])
        self.assertRegex(doc["stopped"], "frame 0, which is asked about, is missing")


class WindowedJobs(Jobs):
    """The three jobs of tests/test_jit_pixel_jobs.py for a check with a window."""

    check = {**DRAWN, "window": dict(WINDOW)}

    def run_cli(self, fix, out, extra, frame_game=None):
        real = run_mod.generate
        transport = Transport(reply({"candidates": [], "pixelChecks": [self.check]}))

        def with_stand_ins(*a, **kw):
            kw.update(runner=JitGame(), variants_fn=self.case.variants(), clock=lambda: 0.0,
                      intent=intent_mod.spark_intent(transport=transport, offer=PX))
            if frame_game is not None:
                kw["frame_runner"] = frame_game
            return real(*a, **kw)

        with mock.patch.object(cli, "generate", side_effect=with_stand_ins), \
                contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["run", "--report-file", str(self.report), "--candidate", str(self.case.patch(fix)),
                             "--base", str(self.case.patch("air-jump")), "--out", str(out), "--model", "off",
                             "--offer", PX, *SAM, *SETTING, *extra])
        self.assertEqual(code, 0)
        doc = json.loads((out / run_mod.RECORD_NAME).read_text(encoding="utf-8"))
        validate_v1(doc, "jit-run")
        return doc

    def capture_here(self):
        builds = {"pixel-reference": "clean", "pixel-base": "layering_v1", "pixel-candidate": "layering_v1"}
        return self.run_cli("fix-wrong", self.tmp / "out-capture", ["--pixel-capture", str(self.store)],
                            FrameGame(builds))

    def ask_with(self, recording, budget="1"):
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["pixel-ask", "--replays", str(self.store), "--out", str(self.answers),
                             "--budget-usd", budget, "--sam-answers", str(recording), *SETTING,
                             "--sam-run", "pixel-reference=clean", "--sam-run", "pixel-base=layering_v1",
                             "--sam-run", "pixel-candidate=layering_v1"])
        return code, json.loads(printed.getvalue())


class TheFourPlacesAgree(WindowedJobs):
    def test_capture_keeps_the_window_s_frames_and_the_windows(self):
        doc = self.capture_here()
        [row] = doc["pixelChecks"]
        self.assertEqual((row["status"], row["reason"]), ("not-run", pixel_jobs.CAPTURED))
        found = pixel_jobs.replays(self.store)
        self.assertEqual(len(found), 9)
        for _, folder in found:
            self.assertEqual(sorted(p.name for p in (folder / "frames").iterdir()),
                             [f"f{n:08d}.png" for n in IN_WINDOW])
            self.assertEqual(pixel_jobs.windows_of(folder), [WINDOW])

    def test_ask_and_judge_reserve_the_same_images_and_the_judge_accepts_the_answers(self):
        self.capture_here()
        code, asked = self.ask_with(windowed_recording(self.tmp / "w.json", [WINDOW]))
        self.assertEqual(code, 0, asked)
        self.assertEqual((asked["plannedImages"], asked["calls"]), (len(IN_WINDOW) * 9, len(IN_WINDOW) * 9))
        doc = self.judge("fix-wrong")
        [row] = doc["pixelChecks"]
        self.assertFalse(str(row["reason"]).startswith("observer:"), row["reason"])
        self.assertIn(row["status"], ("kept", "dropped"))
        price = doc["settings"]["prices"]["samUsdPerImage"] if "prices" in doc["settings"] \
            else run_mod.DEFAULT_PRICES["samUsdPerImage"]
        # The in-process reservation is the asking job's: one image a frame in the window, on nine runs.
        self.assertAlmostEqual(row["reservedUsd"], round(len(IN_WINDOW) * 9 * price, 4))
        # pixel.cost counts the window's frames too; on all nine runs (it counts six, the keep rule's, by default).
        self.assertAlmostEqual(row["reservedUsd"], round(pixel.cost(self.check, WHOLE, price, runs=9), 4))

    def test_the_judge_refuses_answers_asked_about_the_whole_route(self):
        self.capture_here()
        code, asked = self.ask_with(windowed_recording(self.tmp / "w.json", [WINDOW]))
        self.assertEqual(code, 0, asked)
        # The same answers, but planned for the whole route (another window): its 13 frames, as a capture of
        # the whole route would have been asked.
        recorded = {r["run"]: r for r in json.loads(BOX.read_text(encoding="utf-8"))["runs"]}
        doc = json.loads(self.answers.read_text(encoding="utf-8"))
        for run in doc["runs"]:
            source = recorded["clean" if run["run"].startswith("pixel-reference/") else "layering_v1"]
            run["framesProbed"] = list(WHOLE)
            run["frames"] = [f for f in source["frames"] if f["frame"] in WHOLE]
        self.answers.write_text(json.dumps(doc), encoding="utf-8")
        judged = self.judge("fix-wrong")
        [row] = judged["pixelChecks"]
        self.assertEqual(row["status"], "dropped")
        self.assertRegex(row["reason"], r"^observer: .*asked about 13 frames")
        self.assertEqual(pixel.kept_rows(judged), [])


class AWindowWithNoPlannedFrame(WindowedJobs):
    check = {**DRAWN, "window": {"fromFrame": 125}}   # --sam-first 120: the plan ends at frame 119

    def test_it_is_not_run_and_nothing_is_captured(self):
        doc = self.capture_here()
        [row] = doc["pixelChecks"]
        self.assertEqual((row["status"], row["reason"]), ("not-run", pixel.NO_PLANNED_FRAME))
        self.assertEqual(list(self.store.iterdir()) if self.store.exists() else [], [])
        self.assertEqual(doc["spend"]["samImages"], 0)

    def test_the_in_process_replay_does_not_run_it_either(self):
        self.answers.write_text(BOX.read_text(encoding="utf-8"), encoding="utf-8")
        builds = {"pixel-reference": "clean", "pixel-base": "layering_v1", "pixel-candidate": "layering_v1"}
        doc = self.run_cli("fix-wrong", self.tmp / "out-one", ["--sam-answers", str(self.answers),
                                                              *sum((["--sam-run", f"{b}={r}"] for b, r in builds.items()), [])],
                           FrameGame(builds))
        [row] = doc["pixelChecks"]
        self.assertEqual((row["status"], row["reason"], row["reservedUsd"]), ("not-run", pixel.NO_PLANNED_FRAME, 0.0))
        self.assertEqual(doc["spend"]["samImages"], 0)


class TheBulletStandIn(unittest.TestCase):
    """#286's three `visible` bullet checks on `bullet-behind-scenery` (tools/bullet_visible_stand_in.py)."""

    def setUp(self):
        from expectrail.contracts import load_strict
        from expectrail.discovery.route_compiler import compile_route
        from expectrail.jit import offer as offer_mod
        from expectrail.jit.cli import PROFILE
        from tools import bullet_visible_stand_in as stand_in

        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.stand_in = stand_in
        profile = load_strict(PROFILE, "mechanics-profile")
        report = stand_in.REPORT.read_text(encoding="utf-8", errors="replace")
        probes = {p["id"]: p for p in offer_mod.library(profile["actions"], stand_in.OFFER, report)}
        self.checks = stand_in.checks()
        self.routes = {c["probe"]: compile_route(probes[c["probe"]]["program"], name=c["probe"],
                                                 description=probes[c["probe"]]["description"],
                                                 actions=profile["actions"]) for c in self.checks}
        self.observer = SamAnchorObserver(object())   # the default plan; no client is ever asked here

    def test_the_in_process_replay_reserves_675_images(self):
        images = 0
        for pid, route in sorted(self.routes.items()):
            windows = pixel.probe_windows([c for c in self.checks if c["probe"] == pid])
            images += self.observer.most_images(route, ["bullet"], False, windows) * 3 * 3
        self.assertEqual(images, 675)
        self.assertEqual(images, self.stand_in.reserved_images(json.loads(self.stand_in.PLAN.read_text())))
        self.assertAlmostEqual(sum(pixel.cost(c, self.observer.frames(self.routes[c["probe"]]), 0.0025, runs=9)
                                   for c in self.checks), 675 * 0.0025)

    def test_the_asking_job_reserves_675_images(self):
        store = self.tmp / "capture"
        for c in self.checks:
            for build in pixel_jobs.BUILDS:
                for n in (1, 2, 3):
                    folder = store / build / f"{c['probe']}-{n}"
                    folder.mkdir(parents=True)
                    (folder / pixel_jobs.ROUTE_FILE).write_text(json.dumps(self.routes[c["probe"]]))
                    (folder / pixel_jobs.OBJECTS_FILE).write_text(json.dumps({"objects": ["bullet"], "player": False}))
                    (folder / pixel_jobs.WINDOWS_FILE).write_text(json.dumps({"windows": [c["window"]]}))
        with self.assertRaisesRegex(pixel_jobs.AskRefused, r"the 27 replays need up to 675 images, \$1\.6875"):
            pixel_jobs.ask(store, self.observer, 1.0, 0.0025)


if __name__ == "__main__":
    unittest.main()
