"""The propose step is told which observer will judge the pixel checks, and the proposal records it (#286).

A run is judged by one observer (expectrail/jit/run.py: a check naming another is not run). Until now the
propose step was not told which, so the proposer was offered SAM only and no proposal could name the
no-model sensor of #262. Now ``spark_intent``, ``propose_to_file``, ``from_proposal``, ``revise_to_file`` and
the command line take the observer (expectrail/jit/pixel.py ``proposed``; expectrail/jit/intent.py
``observer``), and a proposal for one observer is refused by a run judged by another.

Offline: the model is a recorded reply sent through a test transport (no call), the game is the simulated
one (tests/jit_fixtures.py), and the sensor looks at synthetic frames over a bank calibrated from a
synthetic clean replay (tests/test_jit_template_observer.py). Nothing is sent and nothing is spent. These
say nothing about the sensor on the bundled game's frames."""
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
from expectrail.jit import cli, intent, offer, pixel
from expectrail.jit.diff_map import diff_map
from expectrail.jit.run import from_base_alone, generate
from tests.jit_fixtures import PROFILE, Case, JitGame, Transport, reply
from tests.test_jit_offer import NO_FIX, PROF, REPORT
from tests.test_jit_pixel_offer import answer, library, px
from tests.test_jit_template_observer import PROBE, Base, SensorFrames

PX = offer.PIXEL
EV = offer.EVIDENCE
B = pixel.BUNDLED_BINDINGS
SAM = "sam-3.1-anchor"
SENSOR = "visual-sensor"


def sensor_px(**over) -> dict:
    """A model's pixel check for the sensor: the player, on a library probe."""
    return {k: v for k, v in px(observer=SENSOR, probe=PROBE, **over).items() if k != "window"}


class TheMenuIsForOneObserver(unittest.TestCase):
    def test_sam_by_default_and_the_sensor_when_named(self):
        self.assertEqual(list(pixel.proposed()), [SAM])
        self.assertEqual(list(pixel.proposed(SENSOR)), [SENSOR])
        for bad in ("none", "SAM", None, "sam-3.1"):
            with self.subTest(observer=bad), self.assertRaises(ValueError):
                pixel.proposed(bad)

    def test_the_sensor_menu_offers_the_player_only(self):
        m = pixel.menu(B, pixel.proposed(SENSOR))
        self.assertEqual(list(m["observers"]), [SENSOR])
        self.assertEqual(m["observers"][SENSOR]["objects"], ["player"])
        self.assertEqual(m["observers"][SENSOR]["predicates"], ["visible", "inside-region", "never-crosses"])
        self.assertEqual(sorted(m["notJudgeable"]), ["bullet", "coin", "coins-counter", "enemy", "ground"])
        self.assertNotIn(SAM, json.dumps(m))

    def test_a_check_for_the_other_observer_is_refused_with_the_reason(self):
        for judging, other in ((SAM, SENSOR), (SENSOR, SAM)):
            with self.subTest(judging=judging):
                check, why = pixel.parse_candidate(px(observer=other), B, ["smoke"], pixel.proposed(judging))
                self.assertIsNone(check)
                self.assertIn(f"{other} is not offered to the proposer", why)
                self.assertIn(f"the one that will judge this run: {judging}", why)
                check, why = pixel.parse_candidate(px(observer=judging), B, ["smoke"], pixel.proposed(judging))
                self.assertIsNone(why)


class ThePrompt(unittest.TestCase):
    def setUp(self):
        self.patch = NO_FIX.read_text(encoding="utf-8")
        self.probes = library(PX)
        self.dmap = diff_map(self.patch, PROF, self.probes)

    def prompt(self, **kw) -> str:
        return intent.prompt(REPORT, self.patch, self.dmap, PROF, self.probes, offer=PX, **kw)

    def test_sam_named_is_the_prompt_as_it_was(self):
        self.assertEqual(self.prompt(), self.prompt(observer=SAM))
        self.assertEqual(json.loads(self.prompt())["pixelChecksOffered"], pixel.menu(B))

    def test_the_sensor_named_offers_the_sensor_only_and_the_system_prompt_does_not_move(self):
        sent = json.loads(self.prompt(observer=SENSOR))
        self.assertEqual(sent["pixelChecksOffered"], pixel.menu(B, pixel.proposed(SENSOR)))
        withheld = json.loads(intent.prompt(REPORT, "", self.dmap, PROF, self.probes, offer=PX,
                                            candidate=intent.WITHHELD, observer=SENSOR))
        self.assertEqual(withheld["pixelChecksOffered"], sent["pixelChecksOffered"])
        self.assertEqual(intent.spark_intent(offer=PX, observer=SENSOR).system, intent.spark_intent(offer=PX).system)

    def test_an_observer_without_pixel_checks_or_unknown_is_refused(self):
        with self.assertRaisesRegex(ValueError, "offers no pixel checks"):
            intent.prompt(REPORT, self.patch, self.dmap, PROF, self.probes, offer=EV, observer=SENSOR)
        with self.assertRaisesRegex(ValueError, "offers no pixel checks"):
            intent.spark_intent(offer=EV, observer=SENSOR)
        with self.assertRaisesRegex(ValueError, "unknown observer"):
            intent.spark_intent(offer=PX, observer="none")
        # SAM under another setting is the default, and changes nothing there.
        self.assertNotIn("pixelChecksOffered", json.loads(
            intent.prompt(REPORT, self.patch, self.dmap, PROF, self.probes, offer=EV, observer=SAM)))


class TheProposal(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jit-propose-observer-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.patch = NO_FIX.read_text(encoding="utf-8")

    def propose(self, content, name, **kw) -> tuple[Path, Transport]:
        t = Transport(reply(content))
        out = self.tmp / name
        doc = intent.propose_to_file(intent.spark_intent(transport=t, offer=PX, **kw), REPORT, self.patch, PROF,
                                     library(PX), out)
        self.assertIsNone(doc["error"])
        return out / intent.PROPOSAL_NAME, t

    def replay(self, path, **kw):
        probes = library(PX)
        return intent.from_proposal(path, offer=PX, **kw)(REPORT, self.patch, diff_map(self.patch, PROF, probes),
                                                          PROF, probes)

    def edit(self, path, fn):
        doc = json.loads(path.read_text(encoding="utf-8"))
        fn(doc)
        path.write_text(json.dumps(doc), encoding="utf-8")

    def test_a_proposal_for_sam_is_byte_for_byte_as_before(self):
        content = answer(pixels=[px()])
        before, t1 = self.propose(content, "default")
        named, t2 = self.propose(content, "named", observer=SAM)
        self.assertEqual(before.read_bytes(), named.read_bytes())
        self.assertEqual(t1.bodies, t2.bodies)
        self.assertNotIn("observer", json.loads(before.read_text(encoding="utf-8")))

    def test_a_proposal_for_the_sensor_records_it_and_keeps_only_its_checks(self):
        path, t = self.propose(answer(pixels=[sensor_px(), px(id="sam-one")]), "sensor", observer=SENSOR)
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["observer"], SENSOR)
        self.assertEqual([c["id"] for c in saved["pixelChecks"]], ["jit-px-player-drawn"])
        self.assertTrue(any("sam-one" in d and "not offered to the proposer" in d for d in saved["diagnostics"]),
                        saved["diagnostics"])
        sent = json.loads(t.bodies[0]["messages"][1]["content"])
        self.assertEqual(list(sent["pixelChecksOffered"]["observers"]), [SENSOR])
        got = self.replay(path, observer=SENSOR)
        self.assertEqual(got["pixelChecks"], saved["pixelChecks"])

    def test_a_proposal_is_refused_by_a_run_judged_by_another_observer(self):
        sensor, _ = self.propose(answer(pixels=[sensor_px()]), "sensor", observer=SENSOR)
        sam, _ = self.propose(answer(pixels=[px()]), "sam")
        with self.assertRaisesRegex(intent.IntentUnavailable, "PROPOSAL_MISMATCH: .*'visual-sensor'.*'sam-3.1-anchor'"):
            self.replay(sensor)
        with self.assertRaisesRegex(intent.IntentUnavailable, "PROPOSAL_MISMATCH: .*'sam-3.1-anchor'.*'visual-sensor'"):
            self.replay(sam, observer=SENSOR)

    def test_a_run_that_judges_no_pixel_checks_reads_either(self):
        sensor, _ = self.propose(answer(pixels=[sensor_px()]), "sensor", observer=SENSOR)
        sam, _ = self.propose(answer(pixels=[px()]), "sam")
        self.assertEqual(self.replay(sensor, observer=None)["pixelChecks"][0]["observer"], SENSOR)
        self.assertEqual(self.replay(sam, observer=None)["pixelChecks"][0]["observer"], SAM)

    def test_an_edited_proposal_is_refused(self):
        # (edit, refused by a run judged by the sensor with, refused by a run that judges no pixel checks)
        edits = {
            # The check moved to the other observer, the stated one left: refused by both.
            "check to SAM": (lambda d: d["pixelChecks"][0].update(observer=SAM), "PROPOSAL_INVALID: pixel check", True),
            # Both moved: a proposal for SAM now, refused by the sensor's run; a run judging none may read it,
            # since its pixel checks are not run.
            "both to SAM": (lambda d: (d["pixelChecks"][0].update(observer=SAM), d.pop("observer")),
                            "PROPOSAL_MISMATCH", False),
            "an observer that does not exist": (lambda d: d.update(observer="eyeball"), "PROPOSAL_INVALID: unknown",
                                                True),
            "not a string": (lambda d: d.update(observer=["visual-sensor"]), "PROPOSAL_INVALID: unknown", True),
        }
        for what, (fn, expect, by_none) in edits.items():
            with self.subTest(edit=what):
                path, _ = self.propose(answer(pixels=[sensor_px()]), what, observer=SENSOR)
                self.edit(path, fn)
                with self.assertRaisesRegex(intent.IntentUnavailable, expect):
                    self.replay(path, observer=SENSOR)
                if by_none:
                    with self.assertRaisesRegex(intent.IntentUnavailable, expect):
                        self.replay(path, observer=None)
                else:
                    self.assertEqual(self.replay(path, observer=None)["pixelChecks"][0]["observer"], SAM)

    def test_an_observer_added_to_another_settings_proposal_is_refused(self):
        t = Transport(reply(answer()))
        out = self.tmp / "ev"
        intent.propose_to_file(intent.spark_intent(transport=t, offer=EV), REPORT, self.patch, PROF, library(EV), out)
        path = out / intent.PROPOSAL_NAME
        self.edit(path, lambda d: d.update(observer=SENSOR))
        probes = library(EV)
        with self.assertRaisesRegex(intent.IntentUnavailable, "PROPOSAL_INVALID: .*offers no pixel checks"):
            intent.from_proposal(path, offer=EV)(REPORT, self.patch, diff_map(self.patch, PROF, probes), PROF, probes)
        with self.assertRaisesRegex(ValueError, "offers no pixel checks"):
            intent.from_proposal(path, offer=EV, observer=SENSOR)

    def test_revise_keeps_the_observer_and_refuses_another(self):
        from tests.jit_fixtures import ALWAYS_PASSES, GOOD_CHECK, MISCALIBRATED

        case = Case()
        cand, base = case.patch("fix-wrong"), case.patch("air-jump")
        probes = offer.library(PROF["actions"], PX, REPORT)
        first = {"candidates": [GOOD_CHECK, ALWAYS_PASSES, MISCALIBRATED], "pixelChecks": [sensor_px()]}
        doc = intent.propose_to_file(intent.spark_intent(transport=Transport(reply(first)), offer=PX, observer=SENSOR),
                                     REPORT, cand.read_text(), PROF, probes, case.dir / "p1")
        self.assertIsNone(doc["error"])
        # As jit.yml's first replay runs it: no observer, so the pixel rows are not run.
        r1 = generate(PROFILE, REPORT, cand, [base], case.dir / "r1", runner=JitGame(),
                      intent=intent.from_proposal(case.dir / "p1" / intent.PROPOSAL_NAME, offer=PX, observer=None),
                      variants_fn=case.variants(), offer=PX, clock=lambda: 0.0)
        self.assertEqual(r1["status"], "complete", r1["reason"])
        self.assertEqual(r1["pixelChecks"][0]["status"], "not-run")
        from tests.test_jit_revise import SECOND_GOOD

        def revise(observer, out):
            t = Transport(reply({"candidates": [SECOND_GOOD]}))
            return intent.revise_to_file(intent.spark_intent(transport=t, offer=PX, observer=observer), REPORT,
                                         cand.read_text(), PROF, probes, case.dir / "p1" / intent.PROPOSAL_NAME,
                                         case.dir / "r1" / "jit-run.json", case.dir / out, budget_usd=2.0), t
        doc, t = revise(SENSOR, "p2")
        self.assertTrue(doc["revision"]["revised"])
        self.assertEqual((doc["observer"], doc["pixelChecks"]), (SENSOR, self.first_checks(case)))
        self.assertEqual(list(json.loads(t.bodies[0]["messages"][1]["content"])["pixelChecksOffered"]["observers"]),
                         [SENSOR])
        with self.assertRaisesRegex(intent.IntentUnavailable, "PROPOSAL_MISMATCH"):
            revise(SAM, "p2-sam")

    @staticmethod
    def first_checks(case):
        return json.loads((case.dir / "p1" / intent.PROPOSAL_NAME).read_text(encoding="utf-8"))["pixelChecks"]


class EndToEnd(Base):
    """Proposed for the sensor from a recorded model reply, saved, replayed and judged by the sensor on the
    simulated game: the bug build does not draw the player, a wrong fix keeps it undrawn, a good fix draws it."""

    def generate(self, fix: str):
        case = Case()
        cand = case.patch(fix)
        probes = offer.library(PROF["actions"], PX, "The player is not drawn.")
        t = Transport(reply(answer(trace=(), pixels=[sensor_px()])))
        doc = intent.propose_to_file(intent.spark_intent(transport=t, offer=PX, observer=SENSOR),
                                     "The player is not drawn.", cand.read_text(), PROF, probes, case.dir / "p")
        self.assertIsNone(doc["error"])
        frames = SensorFrames()
        run = generate(PROFILE, "The player is not drawn.", cand, [case.patch("air-jump")], case.dir / f"out-{fix}",
                       runner=JitGame(),
                       intent=intent.from_proposal(case.dir / "p" / intent.PROPOSAL_NAME, offer=PX, observer=SENSOR),
                       variants_fn=case.variants(), observer=self.observer(), frame_runner=frames, offer=PX,
                       clock=lambda: 0.0)
        return run, frames

    def test_a_wrong_fix_is_caught_with_nothing_charged_for_the_observer(self):
        doc, frames = self.generate("fix-wrong")
        validate_v1(doc, "jit-run")
        self.assertEqual(doc["status"], "complete", doc["reason"])
        [row] = doc["pixelChecks"]
        self.assertEqual(row["check"]["observer"], SENSOR)
        self.assertEqual((row["status"], row["outcome"]), ("kept", "catch"), row["reason"])
        self.assertEqual((row["clean"], row["bug"], row["candidate"]), (["pass"] * 3, ["fail"] * 3, ["fail"] * 3))
        self.assertEqual((doc["spend"]["samImages"], doc["spend"]["samUsd"]), (0, 0))
        self.assertEqual(from_base_alone(doc)["pixelReproducing"], ["jit-px-player-drawn"])
        self.assertEqual(frames.builds, ["pixel-reference"] * 3 + ["pixel-base"] * 3 + ["pixel-candidate"] * 3)

    def test_a_good_fix_is_not_caught(self):
        doc, _ = self.generate("fix-good")
        [row] = doc["pixelChecks"]
        self.assertEqual((row["status"], row["outcome"]), ("kept", "no-catch"), row["reason"])


def args_of(*extra, offer_=PX) -> argparse.Namespace:
    ns = {"offer": offer_, "observer": "none", "sam_answers": None, "sam_run": [], "sam_live": False,
          "sam_box": "body", "sam_pad": 4.0, "sam_lift": 0.0, "sam_first": None, "sam_every": 10,
          "sensor_bank": None, "pixel_capture": None, "pixel_replays": None}
    it = iter(extra)
    for flag in it:
        key = flag[2:].replace("-", "_")
        if key == "sam_live":
            ns[key] = True
        elif key == "sam_run":
            ns[key].append(next(it))
        else:
            value = next(it)
            ns[key] = {"sam_answers": Path, "sensor_bank": Path, "pixel_capture": Path, "pixel_replays": Path,
                       "sam_pad": float, "sam_lift": float, "sam_first": int, "sam_every": int}.get(key, str)(value)
    return argparse.Namespace(**ns)


class TheCommandLine(Base):
    def test_the_sensor_is_built_from_its_bank_and_the_frame_plan(self):
        from expectrail.jit.template_observer import TemplateSensorObserver

        obs = cli.observer_from(args_of("--observer", SENSOR, "--sensor-bank", str(self.bank_path),
                                        "--sam-every", "20", "--sam-first", "60"))
        self.assertIsInstance(obs, TemplateSensorObserver)
        self.assertEqual((obs.name, obs.every, obs.first), (SENSOR, 20, 60))

    def test_every_way_to_name_it_wrongly_is_refused(self):
        bank = ["--sensor-bank", str(self.bank_path)]
        cases = {
            "needs --sensor-bank": args_of("--observer", SENSOR),
            "which only the": args_of("--observer", SENSOR, *bank, offer_=EV),
            "is the template bank of": args_of(*bank),
            "is the template bank of ": args_of("--observer", SAM, "--sam-live", *bank),
            "asks no one": args_of("--observer", SENSOR, *bank, "--sam-answers", str(self.bank_path)),
            "asks no one ": args_of("--observer", SENSOR, *bank, "--sam-live"),
            "holds no key": args_of("--observer", SENSOR, *bank, "--pixel-capture", "x"),
            "holds no key ": args_of("--observer", SENSOR, *bank, "--pixel-replays", "x"),
            "takes no --sam-box": args_of("--observer", SENSOR, *bank, "--sam-box", "48x68"),
            "takes no --sam-box ": args_of("--observer", SENSOR, *bank, "--sam-pad", "6"),
            "cannot be used": args_of("--observer", SENSOR, "--sensor-bank", str(self.tmp / "no-such-bank.json")),
            "at most": args_of("--observer", SENSOR, *bank, "--sam-every", "61"),
        }
        for expect, args in cases.items():
            with self.subTest(expect=expect), self.assertRaisesRegex(cli.ObserverArgs, expect.strip()):
                cli.observer_from(args)

    def test_propose_and_revise_take_the_observer_and_record_it(self):
        seen = []

        def fake(offer="baseline", **kw):
            seen.append(kw)

            def propose(*_a, **_k):
                return {"probes": [], "candidates": [], "diagnostics": [], "usage": {}, "promptSha256": None,
                        "pixelChecks": []}
            propose.model, propose.system, propose.offer = "test", "", offer
            propose.observer = kw.get("observer", SAM)
            return propose

        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            report = Path(tmp) / "r.txt"
            report.write_text(REPORT, encoding="utf-8")
            argv = ["propose", "--report-file", str(report), "--candidate", str(NO_FIX), "--offer", PX]
            with mock.patch.object(intent, "spark_intent", fake):
                cli.main([*argv, "--out", str(Path(tmp) / "sam")])
                cli.main([*argv, "--out", str(Path(tmp) / "sensor"), "--observer", SENSOR])
            sam = json.loads((Path(tmp) / "sam" / intent.PROPOSAL_NAME).read_text(encoding="utf-8"))
            sensor = json.loads((Path(tmp) / "sensor" / intent.PROPOSAL_NAME).read_text(encoding="utf-8"))
        self.assertEqual(seen, [{}, {"observer": SENSOR}])   # the default call is the one it always was
        self.assertNotIn("observer", sam)
        self.assertEqual(sensor["observer"], SENSOR)

    def test_an_observer_without_pixel_checks_or_unknown_exits_2(self):
        for cmd in ("propose", "revise"):
            for observer, expect in ((SENSOR, "only the"), ("none", "invalid choice")):
                with self.subTest(cmd=cmd, observer=observer):
                    extra = ["--proposal", "p", "--record", "r"] if cmd == "revise" else []
                    err = io.StringIO()
                    with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as stop:
                        cli.main([cmd, "--report-file", str(NO_FIX), "--candidate", str(NO_FIX), "--out", "x",
                                  "--offer", EV if observer == SENSOR else PX, "--observer", observer, *extra])
                    self.assertEqual(stop.exception.code, 2)
                    self.assertIn(expect, err.getvalue())

    def test_run_replays_a_sensor_proposal_only_with_the_sensor_or_no_observer(self):
        case = Case()
        cand = case.patch("fix-wrong")
        probes = offer.library(PROF["actions"], PX, REPORT)
        t = Transport(reply(answer(trace=(), pixels=[sensor_px()])))
        intent.propose_to_file(intent.spark_intent(transport=t, offer=PX, observer=SENSOR), REPORT, cand.read_text(),
                               PROF, probes, case.dir / "p")
        report = case.dir / "r.txt"
        report.write_text(REPORT, encoding="utf-8")
        seen = {}

        def fake_generate(_profile, _report, _cand, _base, out, intent=None, observer=None, **_kw):
            Path(out).mkdir(parents=True, exist_ok=True)
            try:
                intent(REPORT, cand.read_text(), diff_map(cand.read_text(), PROF, probes), PROF, probes)
                seen[getattr(observer, "name", None)] = "read"
            except intent_mod_unavailable() as exc:
                seen[getattr(observer, "name", None)] = str(exc)
            return {"status": "nothing-generated", "reason": "test", "counts": {}, "spend": {"usd": 0}}

        argv = ["run", "--report-file", str(report), "--candidate", str(cand), "--offer", PX,
                "--proposal", str(case.dir / "p" / intent.PROPOSAL_NAME)]
        with mock.patch.object(cli, "generate", fake_generate), mock.patch.object(cli, "render", lambda d: ""), \
                contextlib.redirect_stdout(io.StringIO()):
            cli.main([*argv, "--out", str(case.dir / "o1"), "--observer", SENSOR, "--sensor-bank", str(self.bank_path)])
            cli.main([*argv, "--out", str(case.dir / "o2")])
            cli.main([*argv, "--out", str(case.dir / "o3"), "--observer", SAM, "--sam-live"])
        self.assertEqual(seen[SENSOR], "read")
        self.assertEqual(seen[None], "read")
        self.assertIn("PROPOSAL_MISMATCH", seen[SAM])


def intent_mod_unavailable():
    return intent.IntentUnavailable


class TheRunPricesThePromptItSent(unittest.TestCase):
    def test_an_intent_with_an_unusable_observer_generates_nothing_and_says_why(self):
        def propose(*_a, **_k):
            raise AssertionError("never called")
        propose.model, propose.system, propose.offer, propose.candidate = "test", "", EV, intent.SHOWN
        propose.observer = SENSOR
        with tempfile.TemporaryDirectory() as tmp:
            doc = generate(PROFILE, REPORT, NO_FIX, [], Path(tmp) / "out", offer=EV, intent=propose,
                           runner=JitGame(), clock=lambda: 0.0)
        self.assertEqual(doc["status"], "nothing-generated")
        self.assertIn("OBSERVER_INVALID", doc["reason"])
        self.assertEqual(doc["spend"]["usd"], 0)


if __name__ == "__main__":
    unittest.main()
