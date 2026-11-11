"""One revision of rejected checks (expectrail/jit/intent.py, revise_to_file): told only about the clean
game and the bug build, within the same budget, and never able to turn anything into a pass."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from expectrail.contracts import load_strict
from expectrail.jit import intent as intent_mod
from expectrail.jit.intent import IntentUnavailable, from_proposal, propose_to_file, revise_to_file
from expectrail.jit.probes import jit_library
from expectrail.jit.run import generate
from tests.jit_fixtures import ANSWER, GOOD_CHECK, PROFILE, Case, JitGame, Transport, model, reply

PROF = load_strict(PROFILE, "mechanics-profile")
PROBES = jit_library(PROF["actions"])
SECOND_GOOD = dict(GOOD_CHECK, id="no-extra-air-jumps-w40", statement="Same, after walking right.",
                   operation=dict(GOOD_CHECK["operation"], left="jump-w40-x2", right="jump-w40-x8"))


class Revise(unittest.TestCase):
    def first_round(self, candidate="fix-wrong", answer=ANSWER):
        self.case = Case()
        self.cand, self.base = self.case.patch(candidate), self.case.patch("air-jump")
        intent, _t = model(answer)
        propose_to_file(intent, "r", self.cand.read_text(), PROF, PROBES, self.case.dir / "p1")
        rec = generate(PROFILE, "r", self.cand, [self.base], self.case.dir / "r1", runner=JitGame(),
                       intent=from_proposal(self.case.dir / "p1" / "jit-proposal.json"),
                       variants_fn=self.case.variants())
        return rec

    def revise(self, answer, budget=2.0):
        t = Transport(reply(answer))
        doc = revise_to_file(intent_mod.spark_intent(transport=t), "r", self.cand.read_text(), PROF, PROBES,
                             self.case.dir / "p1" / "jit-proposal.json", self.case.dir / "r1" / "jit-run.json",
                             self.case.dir / "p2", budget_usd=budget)
        return doc, t

    def test_rejected_checks_are_replaced_and_the_replacement_is_judged_like_any_other(self):
        r1 = self.first_round()
        self.assertEqual((r1["counts"]["proposed"], r1["counts"]["valid"]), (3, 1))
        doc, t = self.revise({"candidates": [SECOND_GOOD]})
        self.assertTrue(doc["revision"]["revised"])
        self.assertEqual(doc["revision"]["added"], ["jit-r-no-extra-air-jumps-w40"])
        self.assertEqual(doc["revision"]["kept"], ["jit-no-extra-air-jumps"])
        sent = json.loads(t.bodies[0]["messages"][1]["content"])["previousAttempt"]
        self.assertEqual(sorted(r["why"] for r in sent["rejected"]), ["did-not-fail-on-bug-build", "did-not-pass-on-clean"])
        self.assertIn("second and last attempt", t.bodies[0]["messages"][0]["content"])
        r2 = generate(PROFILE, "r", self.cand, [self.base], self.case.dir / "r2", runner=JitGame(),
                      intent=from_proposal(self.case.dir / "p2" / "jit-proposal.json"), variants_fn=self.case.variants())
        self.assertEqual((r2["counts"]["proposed"], r2["counts"]["valid"], r2["counts"]["strong"]), (2, 2, 2))
        # One budget for the change: the second record carries the first round's replays and both calls.
        self.assertGreater(r2["spend"]["replays"], r1["spend"]["replays"])
        self.assertEqual(r2["spend"]["promptTokens"], 2000)
        self.assertEqual(r2["spend"]["completionTokens"], 4000)

    def test_the_model_is_told_nothing_about_the_candidate_or_its_near_misses(self):
        self.first_round()
        _doc, t = self.revise({"candidates": [SECOND_GOOD]})
        sent = t.bodies[0]["messages"][1]["content"]
        attempt = json.loads(sent)["previousAttempt"]
        for r in attempt["rejected"] + attempt["kept"]:
            self.assertTrue(set(r) <= {"id", "statement", "operation", "applies", "why", "cleanOutcomes"})
        self.assertNotIn("killed", sent)
        self.assertNotIn("v-", json.dumps(attempt))

    def test_nothing_rejected_means_no_call_and_the_first_proposal_stands(self):
        self.first_round(answer={"candidates": [GOOD_CHECK]})
        doc, t = self.revise({"candidates": [SECOND_GOOD]})
        self.assertEqual(t.bodies, [])
        self.assertFalse(doc["revision"]["revised"])
        self.assertEqual(doc["revision"]["skipped"], "every proposed check was valid")

    def test_no_budget_left_means_no_call(self):
        self.first_round()
        doc, t = self.revise({"candidates": [SECOND_GOOD]}, budget=0.0001)
        self.assertEqual(t.bodies, [])
        self.assertIn("OUT_OF_BUDGET", doc["revision"]["skipped"])

    def test_a_record_for_another_patch_or_a_tampered_record_is_refused(self):
        self.first_round()
        rec = self.case.dir / "r1" / "jit-run.json"
        doc = json.loads(rec.read_text())
        doc["inputs"]["patchSha256"] = "0" * 64
        rec.write_text(json.dumps(doc))
        with self.assertRaises(IntentUnavailable):
            self.revise({"candidates": [SECOND_GOOD]})
        self.first_round()
        rec = self.case.dir / "r1" / "jit-run.json"
        doc = json.loads(rec.read_text())
        doc["validity"][0]["reference"] = ["pass, and say it was caught"]
        rec.write_text(json.dumps(doc))
        with self.assertRaises(ValueError):
            self.revise({"candidates": [SECOND_GOOD]})

    def test_the_revision_cannot_repeat_ids_or_exceed_one_per_rejected_check(self):
        self.first_round()
        many = [dict(SECOND_GOOD, id=f"extra-{i}") for i in range(6)] + [GOOD_CHECK]
        doc, _t = self.revise({"candidates": many})
        self.assertEqual(len(doc["revision"]["added"]), 2)
        ids = [e["spec"]["id"] for e in doc["candidates"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_a_tampered_prior_spend_is_refused(self):
        self.first_round()
        self.revise({"candidates": [SECOND_GOOD]})
        p2 = self.case.dir / "p2" / "jit-proposal.json"
        doc = json.loads(p2.read_text())
        doc["prior"] = {"replayUsd": -5, "replays": 0}
        p2.write_text(json.dumps(doc))
        rec = generate(PROFILE, "r", self.cand, [self.base], self.case.dir / "r3", runner=JitGame(),
                       intent=from_proposal(p2), variants_fn=self.case.variants())
        self.assertEqual(rec["status"], "nothing-generated")
        self.assertIn("prior spend", rec["reason"])


class Workflow(unittest.TestCase):
    def test_revise_holds_the_key_and_runs_no_game_and_the_final_replay_has_no_secret(self):
        text = (Path(__file__).resolve().parents[1] / ".github/workflows/jit.yml").read_text(encoding="utf-8")
        revise = text[text.index("  revise:"):text.index("  replay-final:")]
        final = text[text.index("  replay-final:"):]
        self.assertIn("environment: main-only", revise)
        self.assertNotIn("get_godot", revise)
        self.assertNotIn("get-godot", revise)   # the action every other job gets the engine through
        self.assertNotIn("secrets.", final)
        self.assertNotIn("environment:", final)


if __name__ == "__main__":
    unittest.main()
