"""Pixel checks offered to the proposer (#286): the setting ``signals-reach-evidence-pixel``
(expectrail/jit/offer.py, ``PIXEL``), what the prompt offers (expectrail/jit/pixel.py, ``menu``), reading
the model's ``pixelChecks``, saving and re-reading them in a proposal, and judging a proposal's pixel
checks from recorded SAM answers (``pixel.assess``).

Offline: the model is a recorded reply, the observer is the recorded answers in tests/data/sam-anchor/.
Those recordings are one answer per frame per build, so three runs here are the same answers three
times: the tests check the rules, not how repeatable SAM is."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail.contracts import validate_v1
from expectrail.jit import cli, intent, offer, pixel
from expectrail.jit.diff_map import diff_map
from expectrail.jit.run import Spend, generate
from tests.jit_fixtures import PROFILE, Transport, reply
from tests.test_jit_offer import NO_FIX, PROF, REPORT, SYSTEM_SHA, answer_on, sha
from tests.test_jit_offer_evidence import REACH_SYSTEM_SHA
from tests.test_jit_pixel import BOX, POINT

PX = offer.PIXEL
EV = offer.EVIDENCE
B = pixel.BUNDLED_BINDINGS


def px(**over) -> dict:
    entry = {"id": "player-drawn", "statement": "The player is drawn where the engine puts it.",
             "object": "player", "observer": "sam-3.1-anchor", "probe": "smoke",
             "window": {"fromFrame": 0, "toFrame": 119},
             "predicate": {"type": "visible", "minFraction": 1.0, "minScore": 0.8}}
    entry.update(over)
    return entry


def library(which: str = PX) -> list[dict]:
    """The offered library, with a probe named like the recorded route, so a pixel check can name it."""
    probes = offer.library(PROF["actions"], which, REPORT)
    probes.append({"id": "smoke", "family": "jit", "description": "the smoke route",
                   "program": probes[0]["program"], "tags": []})
    return probes


def answer(trace=("air_jumps",), pixels=()) -> str:
    doc = json.loads(answer_on(*trace)) if trace else {"candidates": []}
    if pixels:
        doc["pixelChecks"] = list(pixels)
    return json.dumps(doc)


class TheSetting(unittest.TestCase):
    def test_it_offers_everything_the_evidence_setting_offers_and_pixel_checks(self):
        self.assertEqual(offer.check(PX), PX)
        self.assertTrue(offer.shows_evidence(PX))
        self.assertTrue(offer.offers_pixel(PX))
        for other in offer.OFFERS:
            self.assertFalse(offer.offers_pixel(other), other)
        self.assertEqual(offer.signals(PX), offer.signals(EV))
        self.assertEqual([p["id"] for p in offer.library(PROF["actions"], PX, REPORT)],
                         [p["id"] for p in offer.library(PROF["actions"], EV, REPORT)])

    def test_a_replay_takes_it_and_a_revision_the_score_and_the_workflow_do_not(self):
        # The replay judges pixel checks since #286's third slice (tests/test_jit_pixel_replay.py).
        self.assertEqual(offer.ALL, (*offer.OFFERS, PX))
        self.assertNotIn(PX, offer.OFFERS)
        self.assertIn(PX, offer.REPLAYABLE)
        self.assertEqual(offer.replayable(PX), PX)
        with self.assertRaisesRegex(offer.OfferError, "cannot be revised yet"):
            offer.revisable(PX)
        for other in offer.OFFERS:
            self.assertEqual(offer.replayable(other), other)
            self.assertEqual(offer.revisable(other), other)

    def test_the_other_settings_prompts_do_not_move(self):
        self.assertEqual(sha(intent.system_for("baseline")), SYSTEM_SHA)
        self.assertEqual(sha(intent.system_for("signals-reach")), REACH_SYSTEM_SHA)
        self.assertNotIn("pixelChecks", intent.system_for(EV))

    def test_the_pixel_system_prompt_is_the_evidence_one_with_the_pixel_text(self):
        ev, pxs = intent.system_for(EV), intent.system_for(PX)
        self.assertIn(intent.PIXEL_TEXT, pxs)
        self.assertEqual(pxs.replace(intent.PIXEL_TEXT, "", 1), ev)
        withheld = intent.system_for(PX, intent.WITHHELD)
        self.assertIn(intent.PIXEL_TEXT, withheld)
        self.assertIn("not shown any fix", withheld)


class WhatThePromptOffers(unittest.TestCase):
    def test_the_user_prompt_carries_the_menu_under_the_pixel_setting_only(self):
        patch = NO_FIX.read_text(encoding="utf-8")
        probes = library(EV)
        dmap = diff_map(patch, PROF, probes)
        self.assertNotIn("pixelChecksOffered", json.loads(intent.prompt(REPORT, patch, dmap, PROF, probes, offer=EV)))
        sent = json.loads(intent.prompt(REPORT, patch, dmap, PROF, probes, offer=PX))
        self.assertEqual(sent["pixelChecksOffered"], pixel.menu(B))
        withheld = json.loads(intent.prompt(REPORT, "", dmap, PROF, probes, offer=PX, candidate=intent.WITHHELD))
        self.assertEqual(withheld["pixelChecksOffered"], pixel.menu(B))
        self.assertNotIn("untrustedCandidatePatch", withheld)

    def test_on_the_bundled_game_sam_can_be_asked_about_the_player_only(self):
        m = pixel.menu(B)
        self.assertEqual(list(m["observers"]), ["sam-3.1-anchor"])
        self.assertEqual(m["observers"]["sam-3.1-anchor"]["objects"], ["player"])
        self.assertEqual(m["observers"]["sam-3.1-anchor"]["predicates"], ["visible", "inside-region", "never-crosses"])
        self.assertEqual(sorted(m["notJudgeable"]), ["bullet", "coin", "coins-counter", "ground"])
        self.assertIn("does not find the ground", m["notJudgeable"]["ground"])
        self.assertIn("not built yet", m["notJudgeable"]["coin"])

    def test_everything_the_menu_offers_is_accepted_and_nothing_it_withholds(self):
        """The menu and the refusals are made from the same tables: an offered (observer, predicate,
        object) is accepted by parse_candidate, and an object under notJudgeable is refused by every
        observer, with or without a second anchored sprite bound."""
        shapes = {"visible": lambda role: {"type": "visible"},
                  "inside-region": lambda role: {"type": "inside-region", "region": {"engine": role}},
                  "never-crosses": lambda role: {"type": "never-crosses", "boundary": {"side": "above", "value": 700}},
                  "reaches": lambda role: {"type": "reaches", "goal": role}}
        for bindings in (B, {**B, "enemy": {"node": "Enemy", "kind": "sprite", "anchor": "engine-position"}}):
            m = pixel.menu(bindings)
            for name, o in m["observers"].items():
                for pred in o["predicates"]:
                    for role in o["objects"]:
                        with self.subTest(observer=name, predicate=pred, role=role):
                            _, why = pixel.parse_candidate(px(object=role, observer=name, predicate=shapes[pred](role)),
                                                           bindings, ["smoke"])
                            self.assertIsNone(why)
            for role in m["notJudgeable"]:
                for name in pixel.OBSERVERS:
                    for pred, shape in shapes.items():
                        with self.subTest(role=role, observer=name, predicate=pred):
                            check, _ = pixel.parse_candidate(px(object=role, observer=name, predicate=shape(role)),
                                                             bindings, ["smoke"])
                            self.assertIsNone(check)
        self.assertIn("enemy", pixel.menu({**B, "enemy": {"node": "Enemy", "kind": "sprite",
                                                          "anchor": "engine-position"}})["observers"]["sam-3.1-anchor"]["objects"])


class ReadingTheAnswer(unittest.TestCase):
    def parse(self, content, which=PX, ids=("smoke",)):
        return intent.parse_answer_pixel(content, PROF, set(ids) | {p["id"] for p in library(which)}, offer=which)

    def test_a_pixel_check_is_read_renamed_and_model_prior(self):
        _, entries, checks, notes = self.parse(answer(pixels=[px(approval={"by": "sean"}, authority="approved")]))
        self.assertEqual(len(entries), 1)
        self.assertEqual([c["id"] for c in checks], ["jit-px-player-drawn"])
        self.assertEqual(checks[0]["authority"], "model_prior")
        self.assertNotIn("approval", checks[0])
        validate_v1(checks[0], "pixel-check")
        self.assertEqual(notes, [])

    def test_an_answer_with_pixel_checks_only_is_usable_under_the_pixel_setting_only(self):
        content = answer(trace=(), pixels=[px()])
        _, entries, checks, _ = self.parse(content)
        self.assertEqual((len(entries), len(checks)), (0, 1))
        with self.assertRaisesRegex(intent.IntentUnavailable, "no contract survived"):
            self.parse(content, which=EV)
        with self.assertRaisesRegex(intent.IntentUnavailable, "no contract survived"):
            self.parse(answer(trace=(), pixels=[px(object="ground")]))

    def test_under_another_setting_pixel_checks_are_not_read_and_that_is_said(self):
        _, entries, checks, notes = self.parse(answer(pixels=[px()]), which=EV)
        self.assertEqual((len(entries), checks), (1, []))
        self.assertTrue(any("not read: the offer signals-reach-evidence" in n for n in notes), notes)
        # The old three-part reader is unchanged and never returns pixel checks.
        probes, entries, notes = intent.parse_answer(answer(pixels=[px()]), PROF, {p["id"] for p in library(PX)}, offer=PX)
        self.assertEqual(len(entries), 1)

    def test_refused_repeated_and_extra_pixel_checks_are_dropped_and_said(self):
        pixels = [px(object="ground"), px(), px(id="jit-px-player-drawn"), px(probe="nowhere"),
                  px(observer="visual-sensor")]
        _, _, checks, notes = self.parse(answer(pixels=pixels))
        self.assertEqual([c["id"] for c in checks], ["jit-px-player-drawn"])
        text = "\n".join(notes)
        self.assertIn("cannot tell 'ground'", text)
        self.assertIn("probe 'nowhere' is not on offer", text)
        self.assertIn("used twice", text)
        self.assertIn("1 beyond the first 4 not read", text)
        self.assertNotIn("cannot judge anything yet", text)  # the fifth is never read
        _, _, checks, notes = self.parse(json.dumps({**json.loads(answer()), "pixelChecks": "all of them"}))
        self.assertEqual(checks, [])
        self.assertIn("not a list", notes[-1])

    def test_a_pixel_check_may_name_a_probe_the_model_proposes(self):
        doc = json.loads(answer())
        doc["probes"] = [{"id": "fall", "description": "walk off the edge",
                          "program": {"op": "hold", "action": "move_right", "durationTicks": 600}}]
        doc["pixelChecks"] = [px(probe="jit-fall")]
        probes, _, checks, notes = self.parse(json.dumps(doc), ids=())
        self.assertEqual([p["id"] for p in probes], ["jit-fall"], notes)
        self.assertEqual([c["probe"] for c in checks], ["jit-fall"], notes)

    def test_the_spark_call_returns_pixel_checks_under_the_pixel_setting_only(self):
        patch = NO_FIX.read_text(encoding="utf-8")
        probes = library(PX)
        t = Transport(reply(answer(pixels=[px()])))
        got = intent.spark_intent(transport=t, offer=PX)(REPORT, patch, diff_map(patch, PROF, probes), PROF, probes)
        self.assertEqual([c["id"] for c in got["pixelChecks"]], ["jit-px-player-drawn"])
        self.assertIn(intent.PIXEL_TEXT, t.bodies[0]["messages"][0]["content"])
        self.assertIn("pixelChecksOffered", t.bodies[0]["messages"][1]["content"])
        t = Transport(reply(answer(pixels=[px()])))
        got = intent.spark_intent(transport=t, offer=EV)(REPORT, patch, diff_map(patch, PROF, probes), PROF, probes)
        self.assertNotIn("pixelChecks", got)


class TheProposal(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jit-pixel-offer-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.patch = NO_FIX.read_text(encoding="utf-8")

    def propose(self, content, which=PX) -> Path:
        out = self.tmp / which
        doc = intent.propose_to_file(intent.spark_intent(transport=Transport(reply(content)), offer=which), REPORT,
                                     self.patch, PROF, library(which), out)
        self.assertIsNone(doc["error"])
        return out / intent.PROPOSAL_NAME

    def replay(self, path, which=PX):
        probes = library(which)
        return intent.from_proposal(path, offer=which)(REPORT, self.patch, diff_map(self.patch, PROF, probes), PROF, probes)

    def edit(self, path, fn):
        doc = json.loads(path.read_text(encoding="utf-8"))
        fn(doc)
        path.write_text(json.dumps(doc), encoding="utf-8")

    def test_saved_and_read_back_as_written(self):
        path = self.propose(answer(pixels=[px()]))
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["offer"], PX)
        self.assertEqual([c["id"] for c in saved["pixelChecks"]], ["jit-px-player-drawn"])
        got = self.replay(path)
        self.assertEqual(got["pixelChecks"], saved["pixelChecks"])
        self.assertEqual(len(got["candidates"]), 1)

    def test_a_proposal_of_pixel_checks_only_is_read(self):
        got = self.replay(self.propose(answer(trace=(), pixels=[px()])))
        self.assertEqual((len(got["candidates"]), len(got["pixelChecks"])), (0, 1))

    def test_other_settings_proposals_have_no_pixel_checks_key(self):
        saved = json.loads(self.propose(answer(pixels=[px()]), which=EV).read_text(encoding="utf-8"))
        self.assertNotIn("pixelChecks", saved)
        self.assertNotIn("pixelChecks", self.replay(self.tmp / EV / intent.PROPOSAL_NAME, which=EV))

    def test_a_failed_call_still_writes_an_empty_list(self):
        out = self.tmp / "failed"
        doc = intent.propose_to_file(intent.spark_intent(transport=Transport(reply("not json")), offer=PX), REPORT,
                                     self.patch, PROF, library(PX), out)
        self.assertTrue(doc["error"])
        self.assertEqual(doc["pixelChecks"], [])

    def test_an_edited_pixel_check_is_refused(self):
        edits = {
            "approval": lambda c: c.update(approval={"by": "sean"}),
            "authority": lambda c: c.update(authority="approved"),
            "observer": lambda c: c.update(observer="visual-sensor"),
            "object": lambda c: c.update(object="coins-counter"),
            "id": lambda c: c.update(id="player-drawn"),
            "probe": lambda c: c.update(probe="nowhere"),
        }
        for what, fn in edits.items():
            with self.subTest(edit=what):
                path = self.propose(answer(pixels=[px()]))
                self.edit(path, lambda d: fn(d["pixelChecks"][0]))
                with self.assertRaisesRegex(intent.IntentUnavailable, "PROPOSAL_INVALID: pixel check"):
                    self.replay(path)
        path = self.propose(answer(pixels=[px()]))
        self.edit(path, lambda d: d.update(pixelChecks=d["pixelChecks"] * 2))
        with self.assertRaisesRegex(intent.IntentUnavailable, "PROPOSAL_INVALID"):
            self.replay(path)
        self.edit(path, lambda d: d.update(pixelChecks=d["pixelChecks"][:1] * 5))
        with self.assertRaisesRegex(intent.IntentUnavailable, "at most 4"):
            self.replay(path)

    def test_pixel_checks_added_to_another_settings_proposal_are_refused(self):
        path = self.propose(answer(), which=EV)
        good = json.loads(self.propose(answer(pixels=[px()])).read_text(encoding="utf-8"))["pixelChecks"]
        self.edit(path, lambda d: d.update(pixelChecks=good))
        with self.assertRaisesRegex(intent.IntentUnavailable, "offers none"):
            self.replay(path, which=EV)


class NotReplayedYet(unittest.TestCase):
    def test_the_replay_takes_the_pixel_setting_and_records_it(self):
        # Since #286's third slice the replay judges pixel checks (tests/test_jit_pixel_replay.py); with no
        # model it still records nothing generated, under the setting it was given.
        with tempfile.TemporaryDirectory() as tmp:
            doc = generate(PROFILE, REPORT, NO_FIX, [], Path(tmp) / "out", offer=PX, runner=lambda *a, **k: None)
            self.assertEqual((doc["status"], doc["settings"]["offer"], doc["pixelChecks"]),
                             ("nothing-generated", PX, []))
            self.assertIn("MODEL_UNAVAILABLE", doc["reason"])

    def test_revise_refuses_it(self):
        propose = intent.spark_intent(transport=Transport(reply(answer())), offer=PX)
        with self.assertRaisesRegex(offer.OfferError, "cannot be revised yet"):
            intent.revise_to_file(propose, REPORT, "", PROF, [], Path("p"), Path("r"), Path("o"), budget_usd=1.0)

    def test_the_commands(self):
        for cmd in ("run", "revise"):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
                cli.main([cmd, "--offer", PX, "--out", "x", "--report-file", "r", "--candidate", "c",
                          "--proposal", "p", "--record", "r"])
            self.assertEqual(stop.exception.code, 2, cmd)
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            report = Path(tmp) / "r.txt"
            report.write_text(REPORT, encoding="utf-8")
            from unittest import mock

            with mock.patch.object(intent, "spark_intent", _fake):
                cli.main(["propose", "--report-file", str(report), "--candidate", str(NO_FIX), "--out", tmp,
                          "--offer", PX])
            doc = json.loads((Path(tmp) / intent.PROPOSAL_NAME).read_text(encoding="utf-8"))
        self.assertEqual(doc["offer"], PX)
        self.assertEqual(doc["pixelChecks"], [])


def _fake(offer="baseline", **_kw):
    def propose(*_a, **_k):
        return {"probes": [], "candidates": [], "diagnostics": [], "usage": {}, "promptSha256": None,
                "pixelChecks": []}
    propose.model, propose.system, propose.offer = "test", "", offer
    return propose


class Assess(unittest.TestCase):
    """A proposal's pixel checks judged end to end from recorded SAM answers (run 43335151089, the smoke
    route asked with a box)."""

    def setUp(self):
        self.box = pixel.load_recording(BOX)
        self.frames = [f["frame"] for f in self.box["runs"]["clean"]["frames"]]
        _, _, self.checks, notes = intent.parse_answer_pixel(
            answer(pixels=[px(), px(id="stays-above", predicate={"type": "never-crosses",
                                                                    "boundary": {"side": "above", "value": 800}})]),
            PROF, {"smoke"} | {p["id"] for p in library(PX)}, offer=PX)
        self.assertEqual(notes, [])

    def runs(self, name, rec=None):
        rec = rec or self.box
        return [(rec["setting"], rec["runs"][name])] * 3

    def test_kept_on_a_screen_only_bug_and_dropped_where_it_cannot_see_it(self):
        spend = Spend(2.0, {})
        rows = pixel.assess(self.checks, self.runs("clean"), self.runs("layering_v1"), spend, self.frames)
        self.assertEqual([(r["check"], r["status"]) for r in rows],
                         [("jit-px-player-drawn", "kept"), ("jit-px-stays-above", "dropped")])
        # Where the layering bug hides the player, a line it must stay above cannot be judged: undecided,
        # never a pass and never a catch.
        self.assertTrue(rows[1]["reason"].startswith("needs-review"), rows[1]["reason"])
        self.assertIn("never a pass", rows[1]["reason"])
        self.assertEqual(spend.usd, 0.0)  # nothing was asked
        rows = pixel.assess(self.checks[:1], self.runs("clean"), self.runs("missing-texture_v1"), spend, self.frames)
        self.assertEqual(rows[0]["reason"], "does-not-fail-on-bug")
        rows = pixel.assess(self.checks[:1], self.runs("clean"), self.runs("physics-fall-through_v1"), spend, self.frames)
        self.assertTrue(rows[0]["reason"].startswith("needs-review"))

    def test_a_check_that_fails_on_the_clean_game_is_dropped(self):
        point = pixel.load_recording(POINT)
        rows = pixel.assess(self.checks[:1], self.runs("clean", point), self.runs("layering_v1", point),
                            Spend(2.0, {}), self.frames)
        self.assertEqual(rows[0]["reason"], "fails-on-clean")

    def test_reservations_add_up_across_checks(self):
        one = pixel.cost(self.checks[0], self.frames, Spend(1, {}).prices["samUsdPerImage"])
        self.assertGreater(one, 0)
        # Room for one check's observer calls, not two: each fits alone, the second does not after the first.
        spend = Spend(one * 1.5, {})
        rows = pixel.assess(self.checks, self.runs("clean"), self.runs("layering_v1"), spend, self.frames)
        self.assertEqual([r["status"] for r in rows], ["kept", "not-run"])
        self.assertIn("OUT_OF_BUDGET", rows[1]["reason"])
        self.assertNotIn("runs", rows[1])
        self.assertEqual(rows[1]["reservedUsd"], 0.0)

    def test_a_check_judged_on_another_route_is_never_kept(self):
        trav = copy.deepcopy(self.checks[0])
        trav["probe"] = "traversal"
        rows = pixel.assess([trav], self.runs("clean"), self.runs("layering_v1"), Spend(2.0, {}), self.frames)
        self.assertFalse(rows[0]["kept"])
        self.assertTrue(rows[0]["reason"].startswith("needs-review"))


if __name__ == "__main__":
    unittest.main()
