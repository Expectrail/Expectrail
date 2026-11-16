"""jit.yml's observer input (#286): the pixel checks judged by SAM 3.1 or by the no-model template sensor.

``sam-3.1-anchor`` (the default) leaves every job as it was. ``visual-sensor`` tells propose and revise
which observer will judge (``--observer visual-sensor``), calibrates the sensor's bank once a run in a
``sensor-bank`` job on the clean game alone, and judges in replay-final with that bank; pixel-ask and
pixel-judge do not run. ``template_observer.calibrate_bank`` is tested here with a stand-in for the game.

The structure is read from the workflow file; each job's shell step is run with bash and a stand-in for
``python`` that records how it was called (tests/test_jit_candidate_workflow.py), so no game, model or SAM
is involved and nothing is dispatched."""
from __future__ import annotations

import contextlib
import io
import json
import shlex
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail.jit import cli
from expectrail.jit import offer as offer_mod
from expectrail.jit import template_observer
from tests.test_jit_candidate_workflow import REPO, Scratch, step

try:
    import PIL  # noqa: F401 - the sensor reads its bank's pixels with Pillow
    import numpy  # noqa: F401 - and matches with NumPy
    HAVE_PIXELS = True
except ModuleNotFoundError as exc:  # the test job's image has neither; the jobs that run the sensor install both
    if exc.name not in ("PIL", "numpy"):
        raise
    HAVE_PIXELS = False
needs_pixels = unittest.skipUnless(HAVE_PIXELS, "the template sensor needs Pillow and NumPy")

PX = offer_mod.PIXEL
SENSOR = "visual-sensor"
SAM = "sam-3.1-anchor"
BANK = "runs/sensor-bank/bank.json"
OBSERVER_JOBS = ("propose", "revise", "replay-final")
MODEL_STEPS = {"propose": "Propose checks", "revise": "Revise the rejected checks"}


def argv_of(call: str) -> list[str]:
    return shlex.split(call)


class TheInput(Scratch):
    def test_the_input_is_a_choice_of_the_two_observers_sam_by_default(self):
        on = self.wf[True] if True in self.wf else self.wf["on"]
        inp = on["workflow_dispatch"]["inputs"]["observer"]
        self.assertEqual(inp["type"], "choice")
        self.assertEqual(inp["options"], [SAM, SENSOR])
        self.assertEqual(inp["default"], SAM)
        self.assertEqual(self.jobs["plan"]["env"]["OBSERVER"], "${{ inputs.observer || 'sam-3.1-anchor' }}")
        self.assertEqual(self.jobs["plan"]["outputs"]["observer"], "${{ steps.plan.outputs.observer }}")

    def test_only_the_jobs_that_use_it_take_it(self):
        for job, d in self.jobs.items():
            with self.subTest(job=job):
                if job in OBSERVER_JOBS:
                    self.assertEqual(d["env"]["OBSERVER"], "${{ needs.plan.outputs.observer }}")
                elif job != "plan":
                    self.assertNotIn("OBSERVER", json.dumps(d.get("env", {})))

    def test_no_job_holds_more_than_before(self):
        text = (REPO / ".github" / "workflows" / "jit.yml").read_text(encoding="utf-8")
        self.assertEqual(text.count("permissions:"), 1)
        self.assertIn("permissions:\n  contents: read\n", text)
        held = sorted(j for j, d in self.jobs.items() if "environment" in d)
        self.assertEqual(held, ["pixel-ask", "propose", "revise"])


class ThePlan(Scratch):
    def plan(self, ok=True, **env):
        self.reset()
        self.run_step(step(self.jobs["plan"], "Plan the cases")["run"], ok=ok,
                      **{"MODE": "repro", "OFFER": PX, "CANDIDATE_TO_MODEL": "shown", "GITHUB_REF": "refs/heads/main",
                         **env})
        return dict(line.partition("=")[::2] for line in self.out.read_text().splitlines()) if self.out.exists() else {}

    def test_unset_is_sam(self):
        self.assertEqual(self.plan()["observer"], SAM)

    def test_the_sensor_passes_under_the_pixel_setting(self):
        self.assertEqual(self.plan(OBSERVER=SENSOR)["observer"], SENSOR)

    def test_the_sensor_is_refused_without_the_pixel_setting(self):
        for offer in ("baseline", "signals-reach", offer_mod.EVIDENCE):
            with self.subTest(offer=offer):
                self.plan(ok=False, OBSERVER=SENSOR, OFFER=offer)
                self.assertIn("only the signals-reach-evidence-pixel offer has", self.stderr)

    def test_sam_without_the_pixel_setting_is_as_before(self):
        self.assertEqual(self.plan(OFFER="baseline")["observer"], SAM)

    def test_anything_else_is_refused(self):
        for bad in ("sam", "SAM-3.1-anchor", "visual-sensor; echo x", "visual-sensor --sam-live", "sam-3x1-anchor",
                    "none", " visual-sensor"):
            with self.subTest(bad=bad):
                self.plan(ok=False, OBSERVER=bad)
                self.assertIn("observer must be sam-3.1-anchor or visual-sensor", self.stderr)


class TheModelSteps(Scratch):
    def call(self, job, observer):
        self.reset()
        calls = self.run_step(step(self.jobs[job], MODEL_STEPS[job])["run"], OFFER=PX, CANDIDATE_TO_MODEL="shown",
                              OBSERVER=observer)
        [call] = [c for c in calls if f"jit.cli {job}" in c]
        return argv_of(call)

    def test_the_sensor_is_named_once_to_propose_and_revise(self):
        for job in MODEL_STEPS:
            with self.subTest(job=job):
                argv = self.call(job, SENSOR)
                self.assertEqual(argv.count("--observer"), 1)
                self.assertEqual(argv[argv.index("--observer") + 1], SENSOR)

    def test_under_sam_the_call_is_as_before(self):
        for job in MODEL_STEPS:
            with self.subTest(job=job):
                self.assertNotIn("--observer", self.call(job, SAM))

    def test_the_command_line_takes_what_the_step_builds(self):
        # The real parser and its checks: propose and revise accept the step's arguments, --observer
        # visual-sensor under the pixel setting included, and go on to choose the probes.
        class Reached(Exception):
            pass

        for job in MODEL_STEPS:
            with self.subTest(job=job):
                argv = self.call(job, SENSOR)[2:]
                for rel in ("bench/r.txt", "bench/c.patch", "bugs/x.patch"):
                    self.touch(rel, "text")
                err = io.StringIO()
                with mock.patch.object(cli, "offered_library", side_effect=Reached), \
                        contextlib.chdir(self.dir), contextlib.redirect_stderr(err), self.assertRaises(Reached):
                    try:
                        cli.main(argv)
                    except SystemExit:
                        self.fail(f"{job} refused the step's arguments: {err.getvalue()}")


class ReplayFinal(Scratch):
    def call(self, ok=True, bank=True, **env):
        self.reset()
        self.touch("runs/jit-proposal-2/jit-proposal.json")
        self.touch("runs/jit-proposal-2/revised.txt", "revised=false\n")
        if bank:
            self.touch(BANK)
        calls = self.run_step(step(self.jobs["replay-final"], "Replay the revised proposal")["run"], ok=ok,
                              **{"OFFER": PX, "CANDIDATE_TO_MODEL": "shown", "SAM_EVERY": "20", **env})
        return [argv_of(c) for c in calls if "jit.cli run" in c]

    def test_the_sensor_judges_here_with_the_bank(self):
        [argv] = self.call(OBSERVER=SENSOR)
        self.assertEqual(argv[argv.index("--observer") + 1], SENSOR)
        self.assertEqual(argv[argv.index("--sensor-bank") + 1], BANK)
        self.assertEqual(argv[argv.index("--sam-every") + 1], "20")
        for absent in ("--pixel-capture", "--sam-answers", "--sam-live", "--sam-run", "--pixel-replays"):
            self.assertNotIn(absent, argv)

    def test_without_the_bank_nothing_is_replayed(self):
        self.assertEqual(self.call(ok=False, bank=False, OBSERVER=SENSOR), [])
        self.assertIn("needs the sensor-bank job's bank", self.stderr)

    def test_under_sam_the_frames_are_captured_as_before(self):
        [argv] = self.call(OBSERVER=SAM)
        self.assertEqual(argv[argv.index("--observer") + 1], SAM)
        self.assertIn("--pixel-capture", argv)
        self.assertNotIn("--sensor-bank", argv)

    def test_without_the_pixel_setting_no_observer_is_named(self):
        self.reset()
        self.touch("runs/jit-proposal-2/jit-proposal.json")
        self.touch("runs/jit-proposal-2/revised.txt", "revised=true\n")
        calls = self.run_step(step(self.jobs["replay-final"], "Replay the revised proposal")["run"],
                              OFFER=offer_mod.EVIDENCE, CANDIDATE_TO_MODEL="shown", OBSERVER=SAM)
        [run] = [c for c in calls if "jit.cli run" in c]
        self.assertNotIn("--observer", run)

    def test_the_record_is_the_result_under_the_sensor(self):
        job = self.jobs["replay-final"]
        upload = next(s for s in job["steps"] if s.get("name") == "Keep the record")
        self.assertIn("needs.plan.outputs.observer != 'visual-sensor' && '-captured'", upload["with"]["name"])
        download = next(s for s in job["steps"] if (s.get("with") or {}).get("name") == "jit-sensor-bank")
        self.assertEqual(download["if"], "needs.plan.outputs.observer == 'visual-sensor'")
        self.assertEqual(download["with"]["path"], "runs/sensor-bank")

    def test_it_waits_for_the_bank_and_runs_when_the_bank_job_is_skipped_under_sam(self):
        job = self.jobs["replay-final"]
        self.assertEqual(job["needs"], ["plan", "replay", "revise", "sensor-bank"])
        cond = " ".join(job["if"].split())
        for part in ("!cancelled()", "needs.plan.result == 'success'", "needs.replay.result == 'success'",
                     "needs.revise.result == 'success'", "needs.sensor-bank.result == 'success'",
                     "(needs.sensor-bank.result == 'skipped' && needs.plan.outputs.observer != 'visual-sensor')"):
            self.assertIn(part, cond)
        self.assertNotIn("always()", cond)


class TheSamJobs(Scratch):
    def test_pixel_ask_and_pixel_judge_do_not_run_under_the_sensor(self):
        for job in ("pixel-ask", "pixel-judge"):
            with self.subTest(job=job):
                self.assertIn("needs.plan.outputs.observer != 'visual-sensor'", self.jobs[job]["if"])


class TheBankJob(Scratch):
    def test_it_runs_only_for_the_sensor_and_holds_nothing(self):
        job = self.jobs["sensor-bank"]
        self.assertEqual(job["needs"], ["plan"])
        self.assertIn(f"needs.plan.outputs.offer == '{PX}'", job["if"])
        self.assertIn("needs.plan.outputs.observer == 'visual-sensor'", job["if"])
        self.assertNotIn("environment", job)
        self.assertNotIn("secrets.", json.dumps(job))

    def test_nothing_of_the_change_reaches_it(self):
        job = self.jobs["sensor-bank"]
        dumped = json.dumps(job)
        self.assertFalse([s for s in job["steps"] if "download-artifact" in (s.get("uses") or "")])
        for word in ("matrix.", "CANDIDATE", "BASE", "REPORT", "proposal", "jit.cli run", "--base", ".patch",
                     '"packages": "patch'):
            self.assertNotIn(word, dumped)

    def test_it_calibrates_and_keeps_the_bank(self):
        job = self.jobs["sensor-bank"]
        self.reset()
        (self.dir / "runs/sensor-bank").mkdir(parents=True)
        calls = self.run_step(step(job, "Calibrate the template bank")["run"])
        [argv] = [argv_of(c) for c in calls if "jit.cli sensor-bank" in c]
        self.assertEqual(argv[argv.index("--out") + 1], BANK)
        self.assertEqual(argv[argv.index("--work") + 1], "runs/sensor-calibration")
        self.assertTrue((self.dir / "runs/sensor-bank/summary.json").exists())
        upload = next(s for s in job["steps"] if "upload-artifact" in (s.get("uses") or ""))
        self.assertEqual(upload["with"]["name"], "jit-sensor-bank")
        self.assertEqual(upload["with"]["if-no-files-found"], "error")
        uses = [s.get("uses") for s in job["steps"]]
        self.assertIn("./.github/actions/get-godot", uses)
        install = next(s for s in job["steps"] if s.get("uses") == "./.github/actions/apt-install")
        self.assertIn("xvfb", install["with"]["packages"])

    def test_both_jobs_that_run_the_sensor_install_pillow_and_numpy(self):
        # requirements-dev.txt has neither; the sensor reads frames with Pillow and matches with NumPy.
        self.assertNotIn("pillow", (REPO / "requirements-dev.txt").read_text(encoding="utf-8").lower())
        bank_pip = next(s["run"] for s in self.jobs["sensor-bank"]["steps"] if "pip install" in (s.get("run") or ""))
        self.assertIn("pillow==12.3.0 numpy==2.5.3", bank_pip)
        final = next(s for s in self.jobs["replay-final"]["steps"]
                     if s.get("name") == "Pillow and NumPy, for the template sensor")
        self.assertEqual(final["if"], "needs.plan.outputs.observer == 'visual-sensor'")
        self.assertEqual(final["run"], "python -m pip install pillow==12.3.0 numpy==2.5.3")

    def test_a_failed_calibration_stops_the_job(self):
        job = self.jobs["sensor-bank"]
        self.reset()
        failing = self.dir / "bin" / "python"
        original = failing.read_text()
        self.addCleanup(failing.write_text, original)
        failing.write_text("#!/bin/bash\nexit 1\n")
        self.run_step(step(job, "Calibrate the template bank")["run"], ok=False)
        self.assertFalse((self.dir / "runs/sensor-bank/summary.json").exists())


EXAMPLE_BANK = REPO / "contracts" / "examples" / "template-bank.json"


class CalibrateBank(unittest.TestCase):
    """``calibrate_bank`` with a stand-in for the game: the routes it replays and what it refuses."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="jit-sensor-bank-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.replays = []

    def runner(self, route, target, *, game, godot, patches, capture_frames):
        self.replays.append({"route": json.loads(Path(route).read_text()), "target": Path(target), "game": game,
                             "patches": patches, "frames": capture_frames})
        Path(target).mkdir(parents=True)

    def calibrate(self, bank=None, error=None, **kw):
        from agents import template_foreground as foreground
        from agents import template_observations as sensor

        def calibrated(*args, **kwargs):
            # Read only once calibration is reached, so the refusals before it need no Pillow.
            if error is not None:
                raise error
            return sensor.load_bank(json.loads(EXAMPLE_BANK.read_text())) if bank is None else bank

        with mock.patch.object(foreground, "calibrate_routes", side_effect=calibrated) as cal:
            out = template_observer.calibrate_bank(self.dir / "out" / "bank.json", self.dir / "work",
                                                   run_replay=self.runner, **kw)
        return out, cal

    @needs_pixels
    def test_the_clean_game_alone_four_routes_no_patch(self):
        summary, cal = self.calibrate()
        self.assertEqual([r["route"]["name"] for r in self.replays], ["cal-walk", "cal-air", "cal-fire", "cal-validation"])
        for r in self.replays:
            self.assertEqual(r["patches"], [])
            self.assertTrue(r["frames"])
            self.assertEqual(r["game"], template_observer.CLEAN_GAME.resolve())
        args, kwargs = cal.call_args
        self.assertEqual([p.name for p in args[0]], ["cal-walk", "cal-air", "cal-fire"])
        self.assertEqual(args[1].name, "cal-validation")
        # The player, and the enemy from the boxes the engine logs for it (#286), each from its own clean art
        # in the pinned game.
        self.assertEqual(kwargs["art"], {"player": "player/robot.webp", "enemy": "enemy/enemy.webp"})
        self.assertEqual(kwargs["objects"], ("enemy",))
        for path in kwargs["art"].values():
            self.assertTrue((template_observer.CLEAN_GAME / path).is_file(), path)
        self.assertEqual(summary["objects"], {})
        self.assertEqual(kwargs["catalogue"], template_observer.BANK_CATALOGUE)
        self.assertTrue(template_observer.BANK_CATALOGUE.is_file())
        written = json.loads((self.dir / "out" / "bank.json").read_text())
        from expectrail.contracts import digest
        self.assertEqual(summary["bankSha256"], digest(written))
        self.assertEqual(summary["templates"], 1)
        self.assertEqual(summary["validation"], "cal-validation")

    @needs_pixels
    def test_the_bank_can_judge(self):
        self.calibrate()
        observer = template_observer.TemplateSensorObserver(self.dir / "out" / "bank.json")
        self.assertEqual(observer.setting()["model"], "expectrail.template-ncc/v2")

    def test_an_existing_bank_is_never_overwritten(self):
        (self.dir / "out").mkdir()
        (self.dir / "out" / "bank.json").write_text("kept")
        with self.assertRaisesRegex(ValueError, "never overwritten"):
            self.calibrate()
        self.assertEqual((self.dir / "out" / "bank.json").read_text(), "kept")
        self.assertEqual(self.replays, [])

    def test_the_work_folder_must_be_new(self):
        (self.dir / "work").mkdir()
        with self.assertRaisesRegex(ValueError, "new folder"):
            self.calibrate()
        self.assertEqual(self.replays, [])

    def test_nothing_is_written_inside_the_game(self):
        game = self.dir / "game"
        game.mkdir()
        (game / "project.godot").write_text("")
        with self.assertRaisesRegex(ValueError, "outside the clean game"):
            template_observer.calibrate_bank(self.dir / "out.json", game / "work", game=game, run_replay=self.runner)
        self.assertEqual(self.replays, [])

    def test_a_failed_calibration_writes_no_bank(self):
        from agents import template_observations as sensor

        with self.assertRaisesRegex(ValueError, "calibration failed: no usable"):
            self.calibrate(error=sensor.SensorError("no usable clean calibration frames"))
        self.assertFalse((self.dir / "out" / "bank.json").exists())

    @needs_pixels
    def test_a_bank_without_the_player_is_refused(self):
        from agents import template_observations as sensor

        doc = json.loads(EXAMPLE_BANK.read_text())
        for t in doc["templates"]:
            t["object"] = "enemy"
        doc = sensor.load_bank(doc)
        with self.assertRaisesRegex(ValueError, "no template of the player"):
            self.calibrate(bank=doc)
        self.assertFalse((self.dir / "out" / "bank.json").exists())

    def test_the_command_line_refuses_an_existing_bank(self):
        out = self.dir / "bank.json"
        out.write_text("kept")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cli.main(["sensor-bank", "--out", str(out), "--work", str(self.dir / "work")])
        self.assertEqual(code, 1)
        self.assertIn("never overwritten", err.getvalue())
        self.assertEqual(out.read_text(), "kept")


if __name__ == "__main__":
    unittest.main()
