"""The one revision under the pixel setting (#286): ``intent.revise_to_file`` replaces rejected trace checks
only, and carries the first round's pixel checks to the second round as they are, with the probes they
replay. jit.yml's revise job runs between the first replay and the final one, so a revision that dropped
pixel checks, or refused the setting, would leave the final replay with none to capture.

Offline: the simulated game (tests/jit_fixtures.py), recorded model replies, and the test double observer
of tests/test_jit_pixel_replay.py, which answers with SAM's recorded smoke-route answers stamped with the
replayed probe's name. These tests check the plumbing and the rules, not SAM on these probes."""
from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest import mock

from expectrail.contracts import load_strict
from expectrail.jit import cli, intent as intent_mod
from expectrail.jit import offer as offer_mod
from expectrail.jit.intent import from_proposal, propose_to_file, revise_to_file
from expectrail.jit.run import from_base_alone, generate
from tests.jit_fixtures import ALWAYS_PASSES, GOOD_CHECK, MISCALIBRATED, PROFILE, Case, JitGame, Transport, reply
from tests.test_jit_pixel_replay import DRAWN, PROBE, REPORT, RecordedSam
from tests.test_jit_revise import SECOND_GOOD

PX = offer_mod.PIXEL
PROF = load_strict(PROFILE, "mechanics-profile")
PROBES = offer_mod.library(PROF["actions"], PX, REPORT)
# A probe of the model's own, so a pixel check can name a probe no trace check keeps.
OWN_PROBE = {"id": "own-walk", "description": "walk right a while", "program": PROBES[0]["program"]}
ON_OWN = dict(DRAWN, id="drawn-on-own", probe="jit-own-walk")


SPARK = intent_mod.spark_intent


def spark(answer: dict) -> tuple:
    t = Transport(reply(answer))
    return SPARK(transport=t, offer=PX), t


class RevisionUnderThePixelSetting(unittest.TestCase):
    def first_round(self, answer: dict):
        self.case = Case()
        self.cand, self.base = self.case.patch("fix-wrong"), self.case.patch("air-jump")
        intent, _t = spark(answer)
        doc = propose_to_file(intent, REPORT, self.cand.read_text(), PROF, PROBES, self.case.dir / "p1")
        self.assertIsNone(doc["error"])
        self.first = doc
        # As jit.yml's first replay runs it: no observer, so the pixel rows are not run.
        return generate(PROFILE, REPORT, self.cand, [self.base], self.case.dir / "r1", runner=JitGame(),
                        intent=from_proposal(self.case.dir / "p1" / "jit-proposal.json", offer=PX),
                        variants_fn=self.case.variants(), offer=PX, clock=lambda: 0.0)

    def revise(self, answer: dict):
        intent, t = spark(answer)
        doc = revise_to_file(intent, REPORT, self.cand.read_text(), PROF, PROBES,
                             self.case.dir / "p1" / "jit-proposal.json", self.case.dir / "r1" / "jit-run.json",
                             self.case.dir / "p2", budget_usd=2.0)
        return doc, t

    def final(self):
        game = JitGame()
        sam = RecordedSam({"pixel-reference": "clean", "pixel-base": "layering_v1", "pixel-candidate": "layering_v1"})
        return generate(PROFILE, REPORT, self.cand, [self.base], self.case.dir / "r2", runner=game,
                        intent=from_proposal(self.case.dir / "p2" / "jit-proposal.json", offer=PX),
                        variants_fn=self.case.variants(), observer=sam, frame_runner=game, offer=PX,
                        clock=lambda: 0.0)

    def test_rejected_trace_checks_are_replaced_and_the_pixel_checks_are_carried_as_they_are(self):
        r1 = self.first_round({"candidates": [GOOD_CHECK, ALWAYS_PASSES, MISCALIBRATED], "pixelChecks": [DRAWN]})
        self.assertEqual((r1["counts"]["proposed"], r1["counts"]["valid"]), (3, 1))
        self.assertEqual(r1["pixelChecks"][0]["status"], "not-run")
        other = dict(DRAWN, id="another", predicate={"type": "visible", "minScore": 0.5})
        doc, t = self.revise({"candidates": [SECOND_GOOD], "pixelChecks": [other]})
        self.assertTrue(doc["revision"]["revised"])
        self.assertEqual(doc["revision"]["added"], ["jit-r-no-extra-air-jumps-w40"])
        self.assertEqual(doc["pixelChecks"], self.first["pixelChecks"])
        self.assertEqual([c["id"] for c in doc["pixelChecks"]], ["jit-px-player-drawn"])
        self.assertIn("revision: pixel checks in the answer were not read: the first round's pixel checks are "
                      "carried as they are", doc["diagnostics"])
        system = t.bodies[0]["messages"][0]["content"]
        self.assertTrue(system.endswith(intent_mod.REVISE_SYSTEM + intent_mod.REVISE_PIXEL_TEXT))
        # The second round judges the carried pixel check beside the trace checks.
        r2 = self.final()
        self.assertEqual(r2["status"], "complete", r2["reason"])
        self.assertEqual((r2["counts"]["proposed"], r2["counts"]["valid"]), (2, 2))
        [row] = r2["pixelChecks"]
        self.assertEqual((row["check"]["id"], row["status"], row["outcome"]), ("jit-px-player-drawn", "kept", "catch"))
        self.assertEqual(from_base_alone(r2)["pixelReproducing"], ["jit-px-player-drawn"])

    def test_the_probe_a_pixel_check_replays_is_kept_when_no_trace_check_keeps_it(self):
        self.first_round({"probes": [OWN_PROBE], "candidates": [GOOD_CHECK, MISCALIBRATED],
                          "pixelChecks": [ON_OWN]})
        self.assertEqual([c["probe"] for c in self.first["pixelChecks"]], ["jit-own-walk"])
        doc, _t = self.revise({"candidates": [SECOND_GOOD]})
        self.assertTrue(doc["revision"]["revised"])
        self.assertIn("jit-own-walk", [p["id"] for p in doc["probes"]])
        replayed = from_proposal(self.case.dir / "p2" / "jit-proposal.json", offer=PX)(
            REPORT, self.cand.read_text(), {}, PROF, PROBES)
        self.assertEqual([c["id"] for c in replayed["pixelChecks"]], ["jit-px-drawn-on-own"])

    def test_a_new_probe_named_like_a_kept_one_is_not_taken(self):
        self.first_round({"probes": [dict(OWN_PROBE, id="r-own-walk")], "candidates": [GOOD_CHECK, MISCALIBRATED],
                          "pixelChecks": [dict(ON_OWN, probe="jit-r-own-walk")]})
        clash = {"id": "on-new", "statement": "The player rises less than 500 px on the new probe.",
                 "claimId": "player.jump", "class": "player",
                 "operation": {"type": "max_episode_rise", "maxPx": 500}, "appliesTo": ["plan-own-walk"]}
        doc, _t = self.revise({"probes": [OWN_PROBE], "candidates": [clash]})
        ids = [p["id"] for p in doc["probes"]]
        self.assertEqual(ids.count("jit-r-own-walk"), 1)
        self.assertNotIn("jit-r-on-new", [e["spec"]["id"] for e in doc["candidates"]])
        self.assertEqual([c["probe"] for c in doc["pixelChecks"]], ["jit-r-own-walk"])

    def test_nothing_rejected_means_no_call_and_the_pixel_checks_stand(self):
        self.first_round({"candidates": [GOOD_CHECK], "pixelChecks": [DRAWN]})
        doc, t = self.revise({"candidates": [SECOND_GOOD]})
        self.assertEqual(t.bodies, [])
        self.assertEqual(doc["revision"]["skipped"], "every proposed check was valid")
        self.assertEqual(doc["pixelChecks"], self.first["pixelChecks"])

    def test_pixel_checks_only_means_nothing_to_revise(self):
        self.first_round({"candidates": [], "pixelChecks": [DRAWN]})
        doc, t = self.revise({"candidates": [SECOND_GOOD]})
        self.assertEqual(t.bodies, [])
        self.assertFalse(doc["revision"]["revised"])
        self.assertEqual(doc["pixelChecks"], self.first["pixelChecks"])

    def test_the_command_line_revise_takes_the_setting(self):
        self.first_round({"candidates": [GOOD_CHECK, MISCALIBRATED], "pixelChecks": [DRAWN]})
        out = self.case.dir / "p2-cli"
        with mock.patch.object(intent_mod, "spark_intent", lambda **kw: spark({"candidates": [SECOND_GOOD]})[0]), \
                contextlib.redirect_stdout(io.StringIO()) as printed:
            code = cli.main(["revise", "--report-file", str(self.write_report()), "--candidate", str(self.cand),
                             "--base", str(self.base), "--proposal", str(self.case.dir / "p1" / "jit-proposal.json"),
                             "--record", str(self.case.dir / "r1" / "jit-run.json"), "--out", str(out),
                             "--offer", PX])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(printed.getvalue())["revised"], True)
        doc = json.loads((out / "jit-proposal.json").read_text())
        self.assertEqual(doc["pixelChecks"], self.first["pixelChecks"])

    def write_report(self):
        path = self.case.dir / "report.txt"
        path.write_text(REPORT)
        return path


class OtherSettingsDoNotMove(unittest.TestCase):
    def test_the_revision_prompt_is_unchanged_without_pixel_checks(self):
        for which in offer_mod.OFFERS:
            if offer_mod.tells_control(which):   # the control setting adds its own text (tests/test_jit_offer_control.py)
                continue
            self.assertEqual(intent_mod.revise_system(which), intent_mod.REVISE_SYSTEM, which)
        self.assertEqual(intent_mod.revise_system(PX), intent_mod.REVISE_SYSTEM + intent_mod.REVISE_PIXEL_TEXT)

    def test_every_setting_is_revisable_and_the_workflow_names_them_all(self):
        self.assertEqual(offer_mod.REVISABLE, offer_mod.ALL)
        self.assertEqual(offer_mod.WORKFLOW, offer_mod.ALL)
        for which in offer_mod.ALL:
            self.assertEqual(offer_mod.revisable(which), which)
        with self.assertRaises(offer_mod.OfferError):
            offer_mod.revisable("everything")


if __name__ == "__main__":
    unittest.main()
