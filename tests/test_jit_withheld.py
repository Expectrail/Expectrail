"""Checks from the report and the bug build alone (issue #285, step 6): with ``--withhold-candidate`` the
model is given no byte of the candidate patch, so a fix cannot shape the checks that judge it. Offline:
a simulated game and recorded model answers, no Godot, no model key."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail.contracts import load_strict, validate_v1
from expectrail.jit import cli, intent as intent_mod
from expectrail.jit import offer as offer_mod
from expectrail.jit.diff_map import PatchError, diff_map, withheld_map
from expectrail.jit.intent import (SHOWN, WITHHELD, IntentUnavailable, from_proposal, propose_to_file,
                                   revise_to_file, system_for)
from expectrail.jit.probes import jit_library
from expectrail.jit.run import from_base_alone, generate
from tests.jit_fixtures import ANSWER, GOOD_CHECK, PROFILE, Case, JitGame, Transport, reply

REPO = Path(__file__).resolve().parents[1]
PROF = load_strict(PROFILE, "mechanics-profile")
PROBES = jit_library(PROF["actions"])
REPORT = "I can keep jumping in the air forever."
EXAMPLE = REPO / "contracts" / "examples" / "jit-run.json"
SECOND_GOOD = dict(GOOD_CHECK, id="no-extra-air-jumps-w40", statement="Same, after walking right.",
                   operation=dict(GOOD_CHECK["operation"], left="jump-w40-x2", right="jump-w40-x8"))


def patch_text(marker: str, path: str = "player/player.gd") -> str:
    """A unified diff whose added line is ``marker``, so a test can look for any byte of it."""
    return f"--- a/{path}\n+++ b/{path}\n@@ -1,1 +1,1 @@\n-a\n+{marker}\n"


def withheld_model(answer=ANSWER, offer=offer_mod.BASELINE):
    t = Transport(reply(answer))
    return intent_mod.spark_intent(transport=t, offer=offer, candidate=WITHHELD), t


def run(case: Case, fix: str, marker: str, *, candidate_to_model=WITHHELD, intent=None, report=REPORT, **kw):
    t = None
    if intent is None:
        intent, t = withheld_model() if candidate_to_model == WITHHELD else _shown_model()
    doc = generate(PROFILE, report, case.patch(fix, patch_text(marker)), [case.patch("air-jump")],
                   case.dir / f"out-{fix}-{candidate_to_model}", runner=JitGame(), intent=intent,
                   variants_fn=case.variants("variant-airjump"), candidate_to_model=candidate_to_model, **kw)
    return doc, t


def _shown_model(answer=ANSWER):
    t = Transport(reply(answer))
    return intent_mod.spark_intent(transport=t), t


def sent(t: Transport) -> str:
    return json.dumps(t.bodies)


class SystemPrompt(unittest.TestCase):
    def test_shown_is_the_prompt_as_it_was_under_every_offer(self):
        for offer in offer_mod.OFFERS:
            self.assertEqual(system_for(offer), system_for(offer, SHOWN))
            self.assertEqual(system_for(offer), intent_mod._system_shown(offer))
            self.assertTrue(system_for(offer).startswith(intent_mod._SHOWN_OPENING))

    def test_withheld_says_there_is_no_fix_and_keeps_everything_after_the_opening(self):
        for offer in offer_mod.OFFERS:
            text = system_for(offer, WITHHELD)
            self.assertTrue(text.startswith(intent_mod.WITHHELD_OPENING))
            self.assertIn("You are not shown any fix", " ".join(text.split()))
            for word in ("patch", "candidate patch", "proposed change", "the change"):
                self.assertNotIn(word, text)
            # The signals, the answer format and the evidence text are the same as with the candidate shown.
            tail = system_for(offer).split("What each signal measures", 1)[1]
            self.assertTrue(text.endswith(tail))
            self.assertEqual(offer_mod.shows_evidence(offer), intent_mod.EVIDENCE_TEXT in text)

    def test_an_unknown_setting_is_refused(self):
        with self.assertRaises(ValueError):
            system_for(offer_mod.BASELINE, "partly")
        with self.assertRaises(ValueError):
            intent_mod.spark_intent(transport=Transport(reply(ANSWER)), candidate="Withheld")


class UserPrompt(unittest.TestCase):
    def test_no_byte_of_the_patch_and_nothing_made_from_it(self):
        a, b = patch_text("FIX-ONE"), patch_text("FIX-TWO", "weapons/gun.gd")
        pa = intent_mod.prompt(REPORT, a, diff_map(a, PROF, PROBES), PROF, PROBES, candidate=WITHHELD)
        pb = intent_mod.prompt(REPORT, b, diff_map(b, PROF, PROBES), PROF, PROBES, candidate=WITHHELD)
        self.assertEqual(pa, pb)
        doc = json.loads(pa)
        self.assertNotIn("untrustedCandidatePatch", doc)
        self.assertNotIn("patchTouches", doc)
        self.assertNotIn("FIX-ONE", pa)
        self.assertNotIn("player.gd", pa)

    def test_every_probe_is_offered_even_where_the_patch_would_narrow_them(self):
        a = patch_text("FIX-ONE")
        narrowed = diff_map(a, PROF, PROBES)
        self.assertLess(len(narrowed["probeIds"]), len(PROBES))   # the shown map keeps fewer
        doc = json.loads(intent_mod.prompt(REPORT, a, narrowed, PROF, PROBES, candidate=WITHHELD))
        self.assertEqual([p["id"] for p in doc["probesAvailable"]], [p["id"] for p in PROBES])

    def test_shown_is_the_prompt_as_it_was(self):
        a = patch_text("FIX-ONE")
        d = diff_map(a, PROF, PROBES)
        self.assertEqual(intent_mod.prompt(REPORT, a, d, PROF, PROBES),
                         intent_mod.prompt(REPORT, a, d, PROF, PROBES, candidate=SHOWN))
        self.assertIn("FIX-ONE", json.loads(intent_mod.prompt(REPORT, a, d, PROF, PROBES))["untrustedCandidatePatch"])

    def test_the_withheld_map_has_no_file_no_claim_and_every_probe(self):
        m = withheld_map(PROBES)
        self.assertEqual((m["files"], m["claims"], m["allProbes"]), ([], [], True))
        self.assertEqual(m["probeIds"], [p["id"] for p in PROBES])


class OneStep(unittest.TestCase):
    def test_the_model_never_sees_the_candidate_and_the_candidate_is_still_judged(self):
        case = Case()
        doc, t = run(case, "fix-wrong", "SECRET-FIX-LINE")
        validate_v1(doc, "jit-run")
        self.assertEqual(doc["status"], "complete")
        self.assertNotIn("SECRET-FIX-LINE", sent(t))
        self.assertNotIn("untrustedCandidatePatch", sent(t))
        self.assertEqual(doc["settings"]["candidate"], WITHHELD)
        self.assertEqual(doc["diffMap"]["files"], [])
        # The wrong fix is caught as before: the candidate is replayed, only the model did not see it.
        self.assertEqual([(c["specId"], c["strength"]) for c in doc["catches"]], [("jit-no-extra-air-jumps", "strong")])
        self.assertEqual(doc["inputs"]["patchSha256"], __import__("hashlib").sha256(
            patch_text("SECRET-FIX-LINE").encode()).hexdigest())

    def test_two_different_fixes_of_one_report_give_the_model_the_same_prompt(self):
        case = Case()
        _good, t1 = run(case, "fix-good", "ONE-WAY")
        _wrong, t2 = run(case, "fix-wrong", "ANOTHER-WAY")
        self.assertEqual(t1.bodies, t2.bodies)
        _shown1, s1 = run(case, "fix-good", "ONE-WAY", candidate_to_model=SHOWN)
        _shown2, s2 = run(case, "fix-wrong", "ANOTHER-WAY", candidate_to_model=SHOWN)
        self.assertNotEqual(s1.bodies, s2.bodies)   # the control: shown, the fix is in the prompt

    def test_a_model_set_up_one_way_cannot_serve_a_run_recorded_the_other(self):
        case = Case()
        shown_intent, t = _shown_model()
        doc, _ = run(case, "fix-wrong", "X", intent=shown_intent)
        self.assertEqual(doc["status"], "nothing-generated")
        self.assertIn("CANDIDATE_MISMATCH", doc["reason"])
        self.assertEqual(t.bodies, [])
        withheld_intent, t = withheld_model()
        doc, _ = run(case, "fix-wrong", "X", intent=withheld_intent, candidate_to_model=SHOWN)
        self.assertIn("CANDIDATE_MISMATCH", doc["reason"])
        self.assertEqual(t.bodies, [])

    def test_a_candidate_that_is_not_a_patch_is_still_refused(self):
        case = Case()
        intent, t = withheld_model()
        doc = generate(PROFILE, REPORT, case.patch("fix-wrong", "not a diff\n"), [case.patch("air-jump")],
                       case.dir / "out", runner=JitGame(), intent=intent, variants_fn=case.variants(),
                       candidate_to_model=WITHHELD)
        self.assertEqual(doc["status"], "nothing-generated")
        self.assertEqual(t.bodies, [])
        with self.assertRaises(PatchError):
            diff_map("not a diff\n", PROF, PROBES)

    def test_an_unknown_setting_is_refused_before_anything_runs(self):
        case = Case()
        with self.assertRaises(ValueError):
            generate(PROFILE, REPORT, case.patch("fix-wrong"), [], case.dir / "out", runner=JitGame(),
                     intent=None, candidate_to_model="both")


class TwoSteps(unittest.TestCase):
    def propose(self, case: Case, report=REPORT, marker="PROPOSE-TIME-FIX"):
        intent, t = withheld_model()
        doc = propose_to_file(intent, report, patch_text(marker), PROF, PROBES, case.dir / "p")
        return case.dir / "p" / "jit-proposal.json", doc, t

    def test_a_withheld_proposal_is_bound_to_the_report_and_replays_against_any_fix(self):
        case = Case()
        path, doc, t = self.propose(case)
        self.assertIsNone(doc["patchSha256"])
        self.assertEqual(doc["candidate"], WITHHELD)
        self.assertEqual(doc["reportSha256"], intent_mod._sha(REPORT))
        self.assertNotIn("PROPOSE-TIME-FIX", sent(t))
        for fix, want in (("fix-wrong", 1), ("fix-good", 0)):
            rec, _ = run(case, fix, f"{fix}-text", intent=from_proposal(path, candidate=WITHHELD))
            self.assertEqual(rec["status"], "complete", rec["reason"])
            self.assertEqual(len(rec["catches"]), want)
            self.assertEqual(rec["settings"]["candidate"], WITHHELD)

    def test_propose_then_replay_gives_the_same_record_as_one_step(self):
        case = Case()
        one, _ = run(case, "fix-wrong", "SAME")
        path, _doc, _t = self.propose(case, marker="SAME")
        two, _ = run(case, "fix-wrong", "SAME", intent=from_proposal(path, candidate=WITHHELD))
        strip = lambda d: {k: v for k, v in d.items() if k not in ("runId", "spend")}  # noqa: E731
        self.assertEqual(strip(one), strip(two))

    def test_a_proposal_is_refused_for_another_report_or_the_other_setting(self):
        case = Case()
        path, _doc, _t = self.propose(case)
        rec, _ = run(case, "fix-wrong", "Y", intent=from_proposal(path, candidate=WITHHELD), report="Another report.")
        self.assertIn("different report", rec["reason"])
        # Made withheld, replayed as shown: refused, so the record cannot say "shown" about checks the
        # model made blind, nor the other way round.
        rec, _ = run(case, "fix-wrong", "Y", intent=from_proposal(path), candidate_to_model=SHOWN)
        self.assertIn("PROPOSAL_MISMATCH", rec["reason"])
        shown, _t = _shown_model()
        propose_to_file(shown, REPORT, patch_text("Y"), PROF, PROBES, case.dir / "shown")
        rec, _ = run(case, "fix-wrong", "Y", intent=from_proposal(case.dir / "shown" / "jit-proposal.json",
                                                                  candidate=WITHHELD))
        self.assertIn("PROPOSAL_MISMATCH", rec["reason"])

    def test_a_tampered_withheld_proposal_that_names_a_patch_is_refused(self):
        case = Case()
        path, doc, _t = self.propose(case)
        doc["patchSha256"] = intent_mod._sha(patch_text("Z"))
        path.write_text(json.dumps(doc))
        with self.assertRaises(IntentUnavailable):
            from_proposal(path, candidate=WITHHELD)(REPORT, "", withheld_map(PROBES), PROF, PROBES)

    def test_the_revision_is_withheld_too(self):
        case = Case()
        cand = case.patch("fix-wrong", patch_text("REVISE-TIME-FIX"))
        base = case.patch("air-jump")
        intent, _t = withheld_model()
        propose_to_file(intent, REPORT, cand.read_text(), PROF, PROBES, case.dir / "p1")
        generate(PROFILE, REPORT, cand, [base], case.dir / "r1", runner=JitGame(),
                 intent=from_proposal(case.dir / "p1" / "jit-proposal.json", candidate=WITHHELD),
                 variants_fn=case.variants(), candidate_to_model=WITHHELD)
        t = Transport(reply({"candidates": [SECOND_GOOD]}))
        doc = revise_to_file(intent_mod.spark_intent(transport=t, candidate=WITHHELD), REPORT, cand.read_text(),
                             PROF, PROBES, case.dir / "p1" / "jit-proposal.json", case.dir / "r1" / "jit-run.json",
                             case.dir / "p2", budget_usd=2.0)
        self.assertTrue(doc["revision"]["revised"])
        self.assertEqual((doc["candidate"], doc["patchSha256"]), (WITHHELD, None))
        self.assertNotIn("REVISE-TIME-FIX", sent(t))
        self.assertNotIn("untrustedCandidatePatch", sent(t))
        r2 = generate(PROFILE, REPORT, cand, [base], case.dir / "r2", runner=JitGame(),
                      intent=from_proposal(case.dir / "p2" / "jit-proposal.json", candidate=WITHHELD),
                      variants_fn=case.variants(), candidate_to_model=WITHHELD)
        self.assertEqual(r2["status"], "complete", r2["reason"])
        # A shown revision of a withheld record is refused before any call.
        t2 = Transport(reply({"candidates": [SECOND_GOOD]}))
        with self.assertRaises(IntentUnavailable):
            revise_to_file(intent_mod.spark_intent(transport=t2), REPORT, cand.read_text(), PROF, PROBES,
                           case.dir / "p1" / "jit-proposal.json", case.dir / "r1" / "jit-run.json",
                           case.dir / "p3", budget_usd=2.0)
        self.assertEqual(t2.bodies, [])


class Reader(unittest.TestCase):
    def test_only_checks_proposed_blind_are_from_the_base_alone(self):
        case = Case()
        blind, _ = run(case, "fix-good", "B")
        seen, _ = run(case, "fix-good", "B", candidate_to_model=SHOWN)
        self.assertEqual(from_base_alone(blind), {"candidate": WITHHELD, "reproducing": ["jit-no-extra-air-jumps"],
                                                  "fromBaseAlone": ["jit-no-extra-air-jumps"]})
        self.assertEqual(from_base_alone(seen), {"candidate": SHOWN, "reproducing": ["jit-no-extra-air-jumps"],
                                                 "fromBaseAlone": []})

    def test_a_record_from_before_the_setting_was_made_with_the_candidate_shown(self):
        case = Case()
        doc, _ = run(case, "fix-good", "B", candidate_to_model=SHOWN)
        old = copy.deepcopy(doc)
        del old["settings"]["candidate"]
        validate_v1(old, "jit-run")
        self.assertEqual(from_base_alone(old)["candidate"], SHOWN)
        self.assertEqual(from_base_alone(old)["fromBaseAlone"], [])

    def test_a_record_that_did_not_complete_or_has_no_bug_build_reproduces_nothing(self):
        case = Case()
        doc, _ = run(case, "fix-good", "B")
        broken = dict(copy.deepcopy(doc), status="nothing-generated", reason="x", catches=[])
        self.assertEqual(from_base_alone(broken)["reproducing"], [])
        no_base = copy.deepcopy(doc)
        no_base["variants"] = [v for v in no_base["variants"] if v["kind"] != "base"]
        self.assertEqual(from_base_alone(no_base)["reproducing"], [])

    def test_a_check_that_did_not_pass_on_the_clean_game_three_times_does_not_reproduce(self):
        case = Case()
        doc, _ = run(case, "fix-good", "B")
        row = next(v for v in doc["validity"] if v["specId"] == "jit-no-extra-air-jumps")
        row["reference"] = ["pass", "pass"]
        self.assertEqual(from_base_alone(doc)["reproducing"], [])

    def test_an_invalid_record_is_refused(self):
        case = Case()
        doc, _ = run(case, "fix-good", "B")
        doc["settings"]["candidate"] = "half"
        with self.assertRaises(Exception):
            from_base_alone(doc)

    def test_the_page_says_whether_the_model_saw_the_candidate(self):
        case = Case()
        blind, _ = run(case, "fix-good", "B")
        seen, _ = run(case, "fix-good", "B", candidate_to_model=SHOWN)
        self.assertIn("not shown the candidate", cli.render(blind))
        self.assertIn("derived from the report and the bug build alone", cli.render(blind))
        self.assertIn("none of them is derived without the candidate", cli.render(seen))


class Example(unittest.TestCase):
    def test_the_example_record_is_valid_and_withheld(self):
        doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        validate_v1(doc, "jit-run")
        self.assertEqual(doc["settings"]["candidate"], WITHHELD)
        self.assertEqual(from_base_alone(doc)["fromBaseAlone"], ["jit-no-extra-air-jumps"])

    def test_the_example_is_what_the_simulated_game_gives(self):
        # Rebuilt the same way it was made: one withheld run of the wrong fix on the simulated game.
        with tempfile.TemporaryDirectory() as tmp:
            case = Case()
            case.dir = Path(tmp)
            doc, _ = run(case, "fix-wrong", "the fix under test")
        made = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        strip = lambda d: {k: v for k, v in d.items() if k not in ("runId", "spend")}  # noqa: E731
        self.assertEqual(strip(doc), strip(made))


class Cli(unittest.TestCase):
    def test_propose_with_the_flag_gives_the_model_nothing_of_the_candidate(self):
        t = Transport(reply(ANSWER))
        made = []
        real = intent_mod.spark_intent

        def fake(offer="baseline", candidate=SHOWN):
            made.append(candidate)
            return real(transport=t, offer=offer, candidate=candidate)

        with tempfile.TemporaryDirectory() as tmp:
            report, cand = Path(tmp) / "r.txt", Path(tmp) / "c.patch"
            report.write_text(REPORT)
            cand.write_text(patch_text("CLI-FIX"))
            with mock.patch.object(intent_mod, "spark_intent", fake), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["propose", "--report-file", str(report), "--candidate", str(cand),
                                           "--out", tmp, "--withhold-candidate"]), 0)
            doc = json.loads((Path(tmp) / "jit-proposal.json").read_text())
        self.assertEqual(made, [WITHHELD])
        self.assertEqual(doc["candidate"], WITHHELD)
        self.assertNotIn("CLI-FIX", sent(t))

    def test_without_the_flag_the_call_is_the_one_it_always_was(self):
        calls = []

        def fake(offer="baseline"):  # no candidate parameter: the default call must not pass one
            calls.append(offer)

            def propose(*_a, **_k):
                return {"probes": [], "candidates": [], "diagnostics": [], "usage": {}, "promptSha256": None}
            propose.model, propose.system = "test", ""
            return propose

        with tempfile.TemporaryDirectory() as tmp:
            report, cand = Path(tmp) / "r.txt", Path(tmp) / "c.patch"
            report.write_text(REPORT)
            cand.write_text(patch_text("CLI-FIX"))
            with mock.patch.object(intent_mod, "spark_intent", fake), contextlib.redirect_stdout(io.StringIO()):
                cli.main(["propose", "--report-file", str(report), "--candidate", str(cand), "--out", tmp])
            doc = json.loads((Path(tmp) / "jit-proposal.json").read_text())
        self.assertEqual(calls, ["baseline"])
        self.assertNotIn("candidate", doc)


if __name__ == "__main__":
    unittest.main()
