"""The command line's ``run`` builds the observer for pixel checks (#286; expectrail/jit/cli.py, ``observer_from``).

Offline. SAM's answers are the recorded ones in tests/data/sam-anchor/ (the bundled game's smoke route,
asked with a 48 x 68 game px box 17 px above the origin). The end-to-end case goes through ``cli.main``
with the simulated game standing in for the engine (the harness is the only thing replaced), the model
answering from a test transport, and the observer the command line built from ``--sam-answers``. No
request is sent and nothing is spent."""
from __future__ import annotations

import argparse
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
from expectrail.jit import offer as offer_mod
from expectrail.jit import run as run_mod
from expectrail.jit.sam_observer import RecordedSamClient, SamAnchorObserver
from tests.jit_fixtures import Case, JitGame, Transport, reply
from tests.test_jit_sam_observer import BOX, DRAWN, LIFT, FrameGame

PX = offer_mod.PIXEL
SAM = ["--observer", "sam-3.1-anchor"]
RECORDED = [*SAM, "--sam-answers", str(BOX), "--sam-box", "48x68", "--sam-lift", str(LIFT), "--sam-first", "120"]


def args_of(*extra, offer=PX) -> argparse.Namespace:
    """The run command's arguments as the parser reads them, from the observer flags alone."""
    ns = {"offer": offer, "observer": "none", "sam_answers": None, "sam_run": [], "sam_live": False,
          "sam_box": "body", "sam_pad": 4.0, "sam_lift": 0.0, "sam_first": None}
    it = iter(extra)
    for flag in it:
        key = flag[2:].replace("-", "_")
        if key == "sam_live":
            ns[key] = True
        elif key == "sam_run":
            ns[key].append(next(it))
        else:
            value = next(it)
            ns[key] = {"sam_answers": Path, "sam_pad": float, "sam_lift": float, "sam_first": int}.get(key, str)(value)
    return argparse.Namespace(**ns)


class TheObserverIsBuiltOrRefused(unittest.TestCase):
    def test_none_is_no_observer(self):
        self.assertIsNone(cli.observer_from(args_of()))
        self.assertIsNone(cli.observer_from(args_of(offer="baseline")))

    def test_recorded_answers_give_a_sam_observer_that_asks_as_the_recording_asked(self):
        obs = cli.observer_from(args_of(*RECORDED))
        self.assertIsInstance(obs, SamAnchorObserver)
        self.assertIsInstance(obs.client, RecordedSamClient)
        self.assertEqual(obs.setting(), obs.client.setting)
        self.assertEqual((obs.box, obs.lift, obs.first), ((48.0, 68.0), LIFT, 120))

    def test_live_is_named_and_sends_nothing_when_built(self):
        obs = cli.observer_from(args_of(*SAM, "--sam-live"))
        self.assertIsInstance(obs, SamAnchorObserver)
        self.assertIsNone(obs._client)   # the live client is made on the first question, not before
        self.assertEqual((obs.box, obs.pad), ("body", 4.0))

    def test_every_way_to_name_it_wrongly_is_refused(self):
        cases = {
            "an observer without the pixel setting": args_of(*RECORDED, offer="signals-reach-evidence"),
            "SAM without saying how it is asked": args_of(*SAM),
            "SAM asked both ways": args_of(*RECORDED, "--sam-live"),
            "SAM flags without SAM": args_of("--sam-live"),
            "recorded answers without SAM": args_of("--sam-answers", str(BOX)),
            "a run pick without recorded answers": args_of(*SAM, "--sam-live", "--sam-run", "pixel-base=clean"),
            "a run pick for no build": args_of(*RECORDED, "--sam-run", "elsewhere=clean"),
            "a run pick without a run": args_of(*RECORDED, "--sam-run", "pixel-base="),
            "one build picked twice": args_of(*RECORDED, "--sam-run", "pixel-base=a", "--sam-run", "pixel-base=b"),
            "a box that is not a size": args_of(*SAM, "--sam-live", "--sam-box", "big"),
            "a lift on the body box": args_of(*SAM, "--sam-live", "--sam-lift", "3"),
            "a first frame count of nought": args_of(*SAM, "--sam-live", "--sam-first", "0"),
            "an answer file that is not one": args_of(*SAM, "--sam-answers", __file__),
        }
        for label, ns in cases.items():
            with self.subTest(label), self.assertRaises(cli.ObserverArgs):
                cli.observer_from(ns)

    def test_the_parser_turns_a_refusal_into_exit_2_before_anything_runs(self):
        with mock.patch.object(cli, "generate") as gen, contextlib.redirect_stderr(io.StringIO()) as err, \
                self.assertRaises(SystemExit) as stop:
            cli.main(["run", "--report-file", __file__, "--candidate", __file__, "--out", "unused", "--model", "off",
                      "--offer", PX, *SAM])
        self.assertEqual(stop.exception.code, 2)
        self.assertIn("exactly one of --sam-answers", err.getvalue())
        gen.assert_not_called()

    def test_the_run_command_takes_the_pixel_setting_and_hands_the_observer_on(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(cli, "generate") as gen, \
                contextlib.redirect_stdout(io.StringIO()):
            gen.return_value = {"status": "complete", "reason": None, "counts": {}, "spend": {"usd": 0.0}}
            with mock.patch.object(cli, "render", return_value=""):
                cli.main(["run", "--report-file", __file__, "--candidate", __file__, "--out", tmp, "--model", "off",
                          "--offer", PX, *RECORDED])
        kw = gen.call_args.kwargs
        self.assertEqual(kw["offer"], PX)
        self.assertIsInstance(kw["observer"], SamAnchorObserver)

    def test_without_the_pixel_setting_the_run_command_hands_on_no_observer(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(cli, "generate") as gen, \
                contextlib.redirect_stdout(io.StringIO()), mock.patch.object(cli, "render", return_value=""):
            gen.return_value = {"status": "complete", "reason": None, "counts": {}, "spend": {"usd": 0.0}}
            cli.main(["run", "--report-file", __file__, "--candidate", __file__, "--out", tmp, "--model", "off"])
        self.assertIsNone(gen.call_args.kwargs["observer"])


class TheRecordedRunIsPicked(unittest.TestCase):
    def test_exact_replay_then_the_named_run_then_the_build(self):
        pick = cli.recorded_pick({"pixel-base/hold-right-2": {}, "clean": {}}, {"pixel-reference": "clean"})
        frame = lambda build, rep: Path("out/jit-replays") / build / rep / "frames" / "f00000000.png"   # noqa: E731
        self.assertEqual(pick(frame("pixel-base", "hold-right-2")), "pixel-base/hold-right-2")
        self.assertEqual(pick(frame("pixel-base", "hold-right-1")), "pixel-base")
        self.assertEqual(pick(frame("pixel-reference", "hold-right-1")), "clean")


class EndToEndThroughTheCommandLine(unittest.TestCase):
    """``cli.main(["run", ...])`` with the observer it builds; the engine and the model are stand-ins."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.case = Case()

    def run_cli(self, fix, candidate_build, extra=()):
        builds = {"pixel-reference": "clean", "pixel-base": "layering_v1", "pixel-candidate": candidate_build}
        report = self.tmp / "report.txt"
        report.write_text("The player is drawn behind the scenery.", encoding="utf-8")
        real = run_mod.generate
        transport = Transport(reply({"candidates": [], "pixelChecks": [DRAWN]}))

        def with_stand_ins(*a, **kw):
            # Only the engine and the model are replaced; the observer is the one the command line built.
            kw.update(runner=JitGame(), frame_runner=FrameGame(builds), variants_fn=self.case.variants(),
                      intent=intent_mod.spark_intent(transport=transport, offer=PX), clock=lambda: 0.0)
            return real(*a, **kw)

        out = self.tmp / f"out-{fix}"
        printed = io.StringIO()
        with mock.patch.object(cli, "generate", side_effect=with_stand_ins), contextlib.redirect_stdout(printed):
            code = cli.main(["run", "--report-file", str(report), "--candidate", str(self.case.patch(fix)),
                             "--base", str(self.case.patch("air-jump")), "--out", str(out), "--model", "off",
                             "--offer", PX, *RECORDED, "--sam-run", "pixel-reference=clean",
                             "--sam-run", "pixel-base=layering_v1", "--sam-run", f"pixel-candidate={candidate_build}",
                             *extra])
        self.assertEqual(code, 0)
        doc = json.loads((out / run_mod.RECORD_NAME).read_text(encoding="utf-8"))
        validate_v1(doc, "jit-run")
        return doc, json.loads(printed.getvalue())

    def test_a_wrong_fix_is_caught_by_the_pixel_check_judged_from_recorded_answers(self):
        doc, printed = self.run_cli("fix-wrong", "layering_v1")
        self.assertEqual(doc["status"], "complete", doc["reason"])
        self.assertEqual(doc["settings"]["offer"], PX)
        [row] = doc["pixelChecks"]
        self.assertEqual((row["status"], row["outcome"]), ("kept", "catch"), row["reason"])
        self.assertEqual((row["clean"], row["bug"], row["candidate"]), (["pass"] * 3, ["fail"] * 3, ["fail"] * 3))
        self.assertEqual(doc["spend"]["samImages"], 13 * 9)
        self.assertEqual(printed["status"], "complete")

    def test_a_good_fix_is_not_caught(self):
        doc, _ = self.run_cli("fix-good", "clean")
        [row] = doc["pixelChecks"]
        self.assertEqual((row["status"], row["outcome"]), ("kept", "no-catch"))

    def test_asked_otherwise_than_the_recording_judges_nothing(self):
        doc, _ = self.run_cli("fix-wrong", "layering_v1", extra=["--sam-lift", "5"])
        [row] = doc["pixelChecks"]
        self.assertEqual(row["status"], "dropped")
        self.assertIn("recorded answers were asked with", row["reason"])
        self.assertEqual(doc["spend"]["samImages"], 0)


if __name__ == "__main__":
    unittest.main()
