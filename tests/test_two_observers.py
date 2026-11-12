"""Two observers on every check (#251, #327): the engine's record and a visual observer over the
captured frames, joined by one rule. A check passes only when both pass; a failure on either is a
failure; anything else needs review; nothing is accepted on the engine's record alone.

No live Godot and no live model. Replays are stand-ins that write a position log (with the ground
line and the camera, as the current harness logs them) and real PNG frames. The vision model is a
scripted stand-in that answers in SAM 3.1's wire format (as tests/test_sam.py does): these are not
recordings of the live model. The real observations code, the real evaluator and the real record
reader judge them.
"""
from __future__ import annotations

import base64
import contextlib
import copy
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import agents.sam_observations as sam
from agents.sam_observations import Cache, MetaSamClient
from expectrail.contracts import digest
from expectrail.evaluator import evaluate
from expectrail.gate import comment as gc
from expectrail.gate import record as rec
from expectrail.gate import verify as gv
from expectrail.observers import FramesObserver
from expectrail.orchestrator import engines, runner
from expectrail.orchestrator import request as req
from expectrail.orchestrator import sample as smp
from expectrail.orchestrator import store as st
from tests.test_ci_gate import BASE, HEAD, make_heldout, make_repo
from tests.test_ci_gate import ctx as gate_ctx
from tests.test_sam import GROUND_TOP, H, W, box_token, png_bytes

REPO = Path(__file__).resolve().parent.parent
SPEC_ID = "player-stays-above-ground"
SPEC = json.loads((REPO / "agents" / "specs" / f"{SPEC_ID}.json").read_text(encoding="utf-8"))
PLAYER_PROMPT, GROUND_PROMPT = SPEC["objects"]["player"]["prompt"], SPEC["objects"]["ground"]["prompt"]
FRAMES, TICKS = 120, 240
FEET = 13.25   # agents.observations.FEET_OFFSET: the player's feet below its origin
# What a game folder holds decides what its replay shows. LOOKS: what the engine logs and what is
# drawn, as (the engine's player sinks, the drawn player sinks, the drawn player is missing).
LOOKS = {"clean": (False, False, False), "BUG": (True, True, False), "DRAWN": (False, True, False),
         "HIDDEN": (False, False, True)}


def sink(i: int) -> float:
    """Nothing until frame 33, then 5 px a frame: past the spec's 20 px tolerance at frame 38."""
    return max(0, i - 33) * 5.0


def look_of(game: Path) -> str:
    return next((name for name in LOOKS if name != "clean" and (game / name).exists()), "clean")


class Game:
    """The stand-in replay and the stand-in model for it. Every frame's bytes say which look and
    which frame it is, and the model answers from that, as a model answers from pixels."""

    def __init__(self):
        self.index: dict[str, tuple[str, int]] = {}
        self.asked: list[tuple[str, int, str]] = []   # (look, frame, prompt) for every request
        self.replays: list[tuple[str, str, bool]] = []
        self.down = False

    def replay(self, route: Path, game: Path, out: Path, frames: bool) -> dict:
        look = look_of(game)
        self.replays.append((route.name, look, frames))
        if (game / "CRASH").exists():
            raise SystemExit("godot failed (139)")
        falls = LOOKS[look][0]
        rows = [{"tick": t, "player": [70.0, GROUND_TOP - FEET + (sink(t // 2) if falls else 0.0)], "onFloor": not falls,
                 "ground": float(GROUND_TOP), "view": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]} for t in range(TICKS)]
        trace = {"physicsTicksPerSecond": 120, "rows": rows}
        out.mkdir(parents=True, exist_ok=True)
        frames_dir = None
        if frames:
            frames_dir = out / "frames"
            frames_dir.mkdir(exist_ok=True)
            for i in range(FRAMES):
                data = png_bytes(W, H, list(LOOKS).index(look) * 1000 + i)
                (frames_dir / f"f{i:08d}.png").write_bytes(data)
                self.index[base64.b64encode(data).decode()] = (look, i)
        return {"trace": trace, "replaySha256": digest({"look": look, "route": route.name}), "framesDir": frames_dir}

    def transport(self, body: dict):
        content = body["input"][0]["content"]
        look, i = self.index[content[1]["image_url"].split(",", 1)[1]]
        self.asked.append((look, i, content[0]["text"]))
        if self.down:
            raise urllib.error.HTTPError("https://model.invalid", 503, "down", {}, io.BytesIO(b"unavailable"))
        _falls, drawn_sinks, missing = LOOKS[look]
        text = ""
        if content[0]["text"] == PLAYER_PROMPT and not missing:
            bottom = GROUND_TOP + int(sink(i) if drawn_sinks else 0)
            text = box_token(0, (60, bottom - 20, 80, bottom), 0.91)
        doc = {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": f"<0f>{text}" if text else ""}]}]}
        return json.dumps(doc).encode(), "application/json"

    def observer(self, **kw) -> FramesObserver:
        client = MetaSamClient(transport=self.transport, retries=0, sleep=lambda s: None)
        return FramesObserver(client=client, cache=Cache(None), name="sam", **kw)


def repo(root: Path, look: str = "clean", **kw) -> Path:
    make_repo(root, routes=("smoke",), **kw)
    if look != "clean":
        (root / "game" / "platformer" / look).write_text("1", encoding="utf-8")
    return root


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="two-observers-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.game = Game()
        self.n = 0

    def gate(self, head: Path, base: Path | None = None, *, rule: str = rec.BOTH, visual="sam", **kw) -> dict:
        self.n += 1
        self.out = self.tmp / f"out{self.n}"
        if visual == "sam":
            visual = self.game.observer()
        with contextlib.redirect_stdout(io.StringIO()):
            return gv.run_gate(repo=head, game="game/platformer", routes=["routes/*.json"], specs="specs",
                               out=self.out, work=self.tmp / f"work{self.n}", base=base,
                               pr={"number": 7, "headSha": HEAD, "baseSha": BASE if base else None},
                               replay=self.game.replay, rule=rule, visual=visual, **kw)

    def row(self, doc: dict) -> dict:
        self.assertEqual(len(doc["checks"]), 1)
        return doc["checks"][0]


class RuleTest(unittest.TestCase):
    def test_the_table(self):
        for engine, visual, want in (
                ("pass", "pass", "pass"),
                ("fail", "pass", "fail"), ("fail", "fail", "fail"), ("fail", "needs-review", "fail"),
                ("fail", "no-answer", "fail"), ("fail", "not-asked", "fail"),
                ("pass", "fail", "fail"), ("needs-review", "fail", "fail"),
                ("pass", "needs-review", "needs-review"), ("pass", "no-answer", "needs-review"),
                ("pass", "not-asked", "needs-review"),
                ("needs-review", "pass", "needs-review"), ("needs-review", "needs-review", "needs-review"),
                ("needs-review", "no-answer", "needs-review"), ("needs-review", "not-asked", "needs-review"),
                ("replay-error", "not-asked", "replay-error")):
            with self.subTest(engine=engine, visual=visual):
                self.assertEqual(rec.combine(engine, visual), want)

    def test_nothing_passes_without_both_passing(self):
        passes = [(e, v) for e in rec.RESULTS for v in rec.VISUAL_SAID if rec.combine(e, v) == "pass"]
        self.assertEqual(passes, [("pass", "pass")])

    def test_a_word_the_rule_does_not_know_is_refused(self):
        for engine, visual in (("passed", "pass"), ("pass", "yes"), ("pass", None), (None, "pass")):
            with self.subTest(engine=engine, visual=visual), self.assertRaises(ValueError):
                rec.combine(engine, visual)


class BothObserversTest(Case):
    def test_both_pass_is_an_accept_and_the_record_says_who_judged(self):
        doc = self.gate(repo(self.tmp / "head"))
        self.assertEqual((doc["decision"], doc["counts"]["passed"]), ("accept", 1))
        self.assertEqual(doc["observers"], {"rule": "both", "visual": {"name": "sam", "provider": "meta-model-api",
                                                                      "model": "sam-3.1"}})
        seen = self.row(doc)["observed"]
        self.assertEqual((seen["before"], seen["after"]["engine"], seen["after"]["visual"]), (None, "pass", "pass"))
        self.assertTrue(self.game.asked)
        # The engine supplies the ground line, so the model is asked for the player only.
        self.assertEqual({prompt for _look, _i, prompt in self.game.asked}, {PLAYER_PROMPT})
        rec.read_record(self.out / "findings.json")

    def test_the_visual_verdict_can_be_read_again_without_the_model(self):
        doc = self.gate(repo(self.tmp / "head"))
        asked = len(self.game.asked)
        stored = json.loads((self.out / "observations" / "head" / "smoke" / f"{SPEC_ID}.visual.json").read_text())
        self.assertEqual(digest(stored), self.row(doc)["observed"]["after"]["visualAnswerSha256"])
        self.assertEqual(stored["model"]["name"], "sam-3.1")
        self.assertEqual(stored["model"]["engineObjects"], ["ground"])
        self.assertEqual(evaluate(SPEC, stored)["result"], "pass")
        verdict = json.loads((self.out / "verdicts" / "head" / "smoke" / f"{SPEC_ID}.visual.json").read_text())
        self.assertEqual(verdict["result"], "pass")
        self.assertEqual(len(self.game.asked), asked)   # reading it again asked nothing

    def test_no_visual_observer_accepts_nothing_and_says_why(self):
        doc = self.gate(repo(self.tmp / "head"), visual=None)
        self.assertEqual((doc["decision"], doc["counts"]["needsReview"]), ("needs-review", 1))
        self.assertEqual(doc["observers"], {"rule": "both", "visual": None})
        self.assertEqual(self.row(doc)["observed"]["after"],
                         {"engine": "pass", "visual": "not-asked", "visualAnswerSha256": None})
        self.assertTrue(any("no visual observer was asked" in r and "not an accept" in r for r in doc["reasons"]),
                        doc["reasons"])
        self.assertIn("no visual observer was asked", doc["findings"][0]["reason"])
        rec.read_record(self.out / "findings.json")

    def test_the_seeded_bug_is_rejected_on_the_engines_record_and_the_model_is_not_asked(self):
        for visual in ("sam", None):
            with self.subTest(visual=visual):
                self.game.asked.clear()
                doc = self.gate(repo(self.tmp / f"head-{visual}", "BUG"), visual=visual)
                self.assertEqual(doc["decision"], "reject")
                self.assertEqual(self.row(doc)["observed"]["after"],
                                 {"engine": "fail", "visual": "not-asked", "visualAnswerSha256": None})
                self.assertEqual(self.game.asked, [])

    def test_a_change_that_only_looks_wrong_is_rejected_by_the_visual_observer(self):
        # The engine's record passes: the player's body never leaves the ground. What is drawn sinks.
        doc = self.gate(repo(self.tmp / "head", "DRAWN"))
        self.assertEqual(doc["decision"], "reject")
        seen = self.row(doc)["observed"]["after"]
        self.assertEqual((seen["engine"], seen["visual"]), ("pass", "fail"))
        self.assertRegex(seen["visualAnswerSha256"], r"^[0-9a-f]{64}$")
        finding = doc["findings"][0]
        self.assertIn("the visual observer sees a failure in the frames", finding["reason"])
        self.assertEqual(finding["frame"], 38)
        # The same change under the old rule is an accept: this is what the second observer adds.
        self.assertEqual(self.gate(repo(self.tmp / "again", "DRAWN"), rule=rec.ENGINE_ONLY, visual=None)["decision"],
                         "accept")

    def test_a_model_that_does_not_answer_is_needs_review_never_an_accept(self):
        self.game.down = True
        doc = self.gate(repo(self.tmp / "head"))
        self.assertEqual(doc["decision"], "needs-review")
        self.assertEqual(self.row(doc)["observed"]["after"],
                         {"engine": "pass", "visual": "no-answer", "visualAnswerSha256": None})
        self.assertIn("the visual observer gave no answer (the model did not answer (server))", doc["findings"][0]["reason"])
        self.assertTrue(any("gave no answer" in r for r in doc["reasons"]), doc["reasons"])
        self.assertNotIn("unavailable", json.dumps(doc))   # the model's own error text is not in the record
        self.assertFalse((self.out / "observations").exists())

    def test_a_run_that_reaches_its_spend_cap_is_needs_review_and_stops_asking(self):
        # The cap of #343: four images at list price. The fifth request is not sent.
        with mock.patch.dict(os.environ, {"EXPECTRAIL_SAM_USD_CAP": "0.01"}), \
                mock.patch.dict(sam._usage, {"reservedUsd": 0.0}):
            doc = self.gate(repo(self.tmp / "head"))
        self.assertEqual(doc["decision"], "needs-review")
        self.assertEqual(self.row(doc)["observed"]["after"]["visual"], "no-answer")
        self.assertIn("the model did not answer (budget)", doc["findings"][0]["reason"])
        self.assertLessEqual(len(self.game.asked), 4)

    def test_a_visual_observer_that_cannot_find_the_player_is_needs_review(self):
        doc = self.gate(repo(self.tmp / "head", "HIDDEN"))
        self.assertEqual(doc["decision"], "needs-review")
        seen = self.row(doc)["observed"]["after"]
        self.assertEqual((seen["engine"], seen["visual"]), ("pass", "needs-review"))
        self.assertTrue(any("could not decide" in r for r in doc["reasons"]), doc["reasons"])

    def test_an_observer_that_stops_or_cannot_be_set_up_is_no_answer(self):
        class Stops:
            def describe(self):
                return {"name": "sam", "provider": "p", "model": "m"}

            def look(self, spec, run, keep=True):
                raise RuntimeError("SECRET-TEXT")

        class NoSetup(Stops):
            def describe(self):
                raise gv.NoAnswer("no key")

        class BadName(Stops):
            def describe(self):
                return {"name": "Not A Name", "provider": "p", "model": "m"}

        doc = self.gate(repo(self.tmp / "a"), visual=Stops())
        self.assertEqual((doc["decision"], self.row(doc)["observed"]["after"]["visual"]), ("needs-review", "no-answer"))
        self.assertNotIn("SECRET-TEXT", json.dumps(doc))

        class NotADocument(Stops):
            def look(self, spec, run, keep=True):
                return {"format": "expectrail.observations/v0", "frames": {1, 2}}   # nothing JSON can hold

        class NoFrames(Stops):
            def look(self, spec, run, keep=True):
                return {"format": "expectrail.observations/v0"}

        for observer in (NotADocument(), NoFrames()):
            doc = self.gate(repo(self.tmp / type(observer).__name__), visual=observer)
            self.assertEqual((doc["decision"], self.row(doc)["observed"]["after"]),
                             ("needs-review", {"engine": "pass", "visual": "no-answer", "visualAnswerSha256": None}))
        for n, observer in enumerate((NoSetup(), BadName())):
            doc = self.gate(repo(self.tmp / f"b{n}"), visual=observer)
            self.assertEqual((doc["decision"], doc["observers"]["visual"]), ("needs-review", None))
            self.assertEqual(self.row(doc)["observed"]["after"]["visual"], "not-asked")
            self.assertTrue(any("the visual observer could not be used" in r for r in doc["reasons"]), doc["reasons"])

    def test_a_replay_that_does_not_finish_asks_nobody(self):
        doc = self.gate(repo(self.tmp / "head", crash=True))
        self.assertEqual(doc["decision"], "needs-review")
        self.assertEqual(self.row(doc)["observed"]["after"],
                         {"engine": "replay-error", "visual": "not-asked", "visualAnswerSha256": None})
        self.assertEqual(self.game.asked, [])
        rec.read_record(self.out / "findings.json")

    def test_a_repair_is_judged_on_both_sides(self):
        doc = self.gate(repo(self.tmp / "head"), base=repo(self.tmp / "base", "BUG"))
        row = self.row(doc)
        self.assertEqual((doc["decision"], row["comparison"]), ("accept", "REPAIRED"))
        self.assertEqual(row["observed"]["before"], {"engine": "fail", "visual": "not-asked", "visualAnswerSha256": None})
        self.assertEqual({look for look, _i, _p in self.game.asked}, {"clean"})   # the failing base cost no image
        doc = self.gate(repo(self.tmp / "head2", "DRAWN"), base=repo(self.tmp / "base2"))
        self.assertEqual((doc["decision"], self.row(doc)["comparison"]), ("reject", "REGRESSION"))
        self.assertTrue((self.out / "observations" / "base" / "smoke" / f"{SPEC_ID}.visual.json").is_file())

    def test_held_out_checks_need_both_observers_too_and_leave_no_cache(self):
        seen = []

        class Watching(FramesObserver):
            def look(self, spec, run, *, keep=True):
                seen.append((Path(run["framesDir"]).parent.parent.name.startswith("expectrail-heldout-runs-"), keep))
                return super().look(spec, run, keep=keep)

        client = MetaSamClient(transport=self.game.transport, retries=0, sleep=lambda s: None)
        held = make_heldout(self.tmp / "heldout")
        doc = self.gate(repo(self.tmp / "head"), heldout=held, visual=Watching(client=client, cache=Cache(None), name="sam"))
        self.assertEqual((doc["decision"], doc["heldOut"]["passed"], doc["heldOut"]["checks"]), ("accept", 2, 2))
        self.assertEqual(sorted(seen), [(False, True), (True, False), (True, False)])
        doc = self.gate(repo(self.tmp / "head2"), heldout=held, visual=None)
        self.assertEqual((doc["decision"], doc["heldOut"]["passed"], doc["heldOut"]["needsReview"]), ("needs-review", 0, 2))
        doc = self.gate(repo(self.tmp / "head3", "DRAWN"), heldout=held)
        self.assertEqual((doc["decision"], doc["heldOut"]["failed"]), ("reject", 2))

    def test_the_phases_are_reported_as_the_gate_moves_on(self):
        phases = []
        self.gate(repo(self.tmp / "head"), base=repo(self.tmp / "base"), on_phase=phases.append)
        self.assertEqual(phases, ["observing", "evaluating", "observing", "evaluating"])


class EngineOnlyTest(Case):
    def test_the_old_rule_still_judges_as_it_did_and_the_record_names_it(self):
        doc = self.gate(repo(self.tmp / "head"), rule=rec.ENGINE_ONLY, visual=None)
        self.assertEqual((doc["decision"], doc["reasons"]), ("accept", ["all 1 checks pass"]))
        self.assertEqual(doc["observers"], {"rule": "engine-only", "visual": None})
        self.assertNotIn("observed", self.row(doc))
        self.assertEqual(self.game.asked, [])
        self.assertFalse((self.out / "observations").exists())
        rec.read_record(self.out / "findings.json")

    def test_a_visual_observer_under_the_old_rule_is_refused_not_ignored(self):
        with self.assertRaisesRegex(gv.ConfigError, "engine-only"):
            self.gate(repo(self.tmp / "head"), rule=rec.ENGINE_ONLY)
        with self.assertRaisesRegex(gv.ConfigError, "rule must be one of"):
            self.gate(repo(self.tmp / "head2"), rule="visual-only", visual=None)
        self.assertEqual(self.game.asked, [])

    def test_a_record_from_before_the_block_reads_as_engine_only(self):
        doc = self.gate(repo(self.tmp / "head"), rule=rec.ENGINE_ONLY, visual=None)
        del doc["observers"]
        rec.check_record(doc)
        self.assertEqual(rec.rule_of(doc), rec.ENGINE_ONLY)
        self.assertIn("the engine's record only", rec.observers_words(doc))


class ReaderTest(Case):
    """The trusted side recomputes each row from what the observers said."""

    def accepted(self) -> dict:
        return self.gate(repo(self.tmp / f"head{self.n}"))

    def refused(self, doc: dict, words: str):
        with self.assertRaisesRegex(rec.RecordError, words):
            rec.check_record(doc)

    def test_a_pass_without_the_visual_observers_pass_is_refused(self):
        for said in ("not-asked", "no-answer", "needs-review", "fail"):
            with self.subTest(said=said):
                doc = self.accepted()
                doc["checks"][0]["observed"]["after"].update(visual=said)
                self.refused(doc, "does not follow from what the two observers said")

    def test_a_both_record_cannot_drop_what_the_observers_said(self):
        doc = self.accepted()
        del doc["checks"][0]["observed"]
        self.refused(doc, "does not say what each said")

    def test_an_engine_only_record_cannot_carry_observers_and_the_rule_cannot_be_swapped(self):
        doc = self.accepted()
        doc["observers"]["rule"] = "engine-only"
        self.refused(doc, "engine-only")
        doc["observers"]["visual"] = None
        self.refused(doc, "the rule is engine-only")

    def test_a_visual_verdict_needs_a_named_observer_and_its_digest(self):
        doc = self.accepted()
        doc["checks"][0]["observed"]["after"]["visualAnswerSha256"] = None
        self.refused(doc, "digest of the visual observer's answer")
        doc = self.accepted()
        doc["observers"]["visual"] = None
        self.refused(doc, "names no visual observer")
        doc = self.gate(repo(self.tmp / "none"), visual=None)
        doc["checks"][0]["observed"]["after"]["visualAnswerSha256"] = "0" * 64
        self.refused(doc, "digest of the visual observer's answer")

    def test_each_side_says_what_was_observed_exactly_when_it_was_judged(self):
        doc = self.accepted()
        doc["checks"][0]["observed"]["before"] = copy.deepcopy(doc["checks"][0]["observed"]["after"])
        self.refused(doc, "exactly when that side was judged")

    def test_a_field_the_schema_does_not_have_is_refused(self):
        doc = self.accepted()
        doc["checks"][0]["observed"]["after"]["note"] = "x"
        self.refused(doc, "does not match the findings schema")
        doc = self.accepted()
        doc["observers"]["rule"] = "visual-only"
        self.refused(doc, "does not match the findings schema")

    def test_the_examples_are_valid_records(self):
        for name, rule in (("findings.json", "engine-only"), ("findings-both-observers.json", "both")):
            doc = rec.read_record(REPO / "contracts" / "examples" / name)
            self.assertEqual(rec.rule_of(doc), rule)
        both = rec.read_record(REPO / "contracts" / "examples" / "findings-both-observers.json")
        self.assertEqual((both["decision"], both["observers"]["visual"]["model"]), ("accept", "sam-3.1"))
        self.assertEqual({(c["observed"]["before"]["engine"], c["observed"]["before"]["visual"],
                           c["observed"]["after"]["engine"], c["observed"]["after"]["visual"], c["comparison"])
                          for c in both["checks"]}, {("fail", "not-asked", "pass", "pass", "REPAIRED")})


class WordsTest(Case):
    def test_the_page_and_the_comment_say_which_observers_judged(self):
        ctx = gate_ctx()
        for kw, words in (({"rule": rec.ENGINE_ONLY, "visual": None}, "the engine's record only"),
                          ({"visual": None}, "none was asked, so nothing here is accepted"),
                          ({}, "two observers on every check")):
            with self.subTest(words=words):
                doc = self.gate(repo(self.tmp / f"head{self.n}"), **kw)
                self.assertIn(words, rec.observers_words(doc))
                page = (self.out / "review" / "index.html").read_text(encoding="utf-8")
                self.assertIn("Judged on", page)
                self.assertIn(words.replace("'", "&#x27;"), page)
                self.assertIn("**Judged on:**", gc.render(doc, ctx))

    def test_an_observers_name_in_a_record_is_made_inert_in_the_comment(self):
        doc = self.gate(repo(self.tmp / "head"))
        doc["observers"]["visual"]["model"] = "m](https://evil.example) @someone <b>"
        rec.check_record(doc)
        ctx = gate_ctx()
        text = gc.render(doc, ctx)
        self.assertNotIn("](https://evil.example)", text)
        self.assertNotIn("<b>", text)


class FramesObserverTest(Case):
    def run_of(self, look: str = "clean", frames: bool = True) -> dict:
        game = self.tmp / f"game-{look}"
        game.mkdir(exist_ok=True)
        if look != "clean":
            (game / look).write_text("1", encoding="utf-8")
        return self.game.replay(Path("smoke.json"), game, self.tmp / f"run-{look}-{frames}", frames)

    def test_it_looks_at_the_frames_against_the_engines_ground_line(self):
        obs = self.game.observer().look(SPEC, self.run_of())
        self.assertEqual(obs["format"], "expectrail.observations/v0")
        self.assertEqual(obs["model"]["engineObjects"], ["ground"])
        self.assertEqual(obs["frames"][0]["objects"]["ground"][0]["source"], "engine")
        self.assertEqual(evaluate(SPEC, obs)["result"], "pass")
        self.assertEqual(evaluate(SPEC, self.game.observer().look(SPEC, self.run_of("DRAWN")))["result"], "fail")

    def test_no_frames_or_no_model_is_no_answer(self):
        with self.assertRaisesRegex(gv.NoAnswer, "captured no frames"):
            self.game.observer().look(SPEC, self.run_of(frames=False))
        self.game.down = True
        with self.assertRaisesRegex(gv.NoAnswer, r"the model did not answer \(server\)"):
            self.game.observer().look(SPEC, self.run_of())

    def test_keep_false_reads_and_writes_no_cache(self):
        cache = Cache(self.tmp / "cache")
        client = MetaSamClient(transport=self.game.transport, retries=0, sleep=lambda s: None)
        observer = FramesObserver(client=client, cache=cache, name="sam")
        run = self.run_of()
        observer.look(SPEC, run, keep=False)
        self.assertFalse((self.tmp / "cache").exists())
        asked = len(self.game.asked)
        observer.look(SPEC, run)
        self.assertTrue(any((self.tmp / "cache").rglob("*.json")))
        again = len(self.game.asked)
        self.assertGreater(again, asked)
        observer.look(SPEC, run)   # answered from the cache
        self.assertEqual(len(self.game.asked), again)
        observer.look(SPEC, run, keep=False)   # and not from it
        self.assertGreater(len(self.game.asked), again)

    def test_describe_names_the_model_without_asking_it(self):
        self.assertEqual(self.game.observer().describe(), {"name": "sam", "provider": "meta-model-api", "model": "sam-3.1"})
        self.assertEqual(self.game.asked, [])


class EngineTest(Case):
    """The orchestrator's godot engine with the rule: the same gate, so the same decisions."""

    def setUp(self):
        super().setUp()
        self.store = st.JobStore(self.tmp / "jobs", lease_seconds=5)

    def work(self, head: Path, engine) -> tuple[dict, dict]:
        request = req.build(adapter="godot", head=head, game="game/platformer", routes=["routes/*.json"], specs="specs")
        status, _created = self.store.create(request)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            status = runner.work(self.store, status["id"], engines={"godot": engine})
        record = rec.read_record(self.store.paths(status["id"]).output / "findings.json")
        return status, record

    def test_the_engine_and_the_gate_decide_alike_under_both_observers(self):
        for look, visual, want in (("clean", True, "accept"), ("clean", False, "needs-review"),
                                   ("BUG", True, "reject"), ("DRAWN", True, "reject"), ("HIDDEN", True, "needs-review")):
            with self.subTest(look=look, visual=visual):
                head = repo(self.tmp / f"{look}-{visual}", look)
                observer = self.game.observer() if visual else None
                status, record = self.work(head, engines.GodotGate(replay=self.game.replay, rule=rec.BOTH, visual=observer))
                gate = self.gate(head, visual=self.game.observer() if visual else None)
                self.assertEqual((status["phase"], status["decision"]), ("completed", want))
                self.assertEqual(gate["decision"], want)
                self.assertEqual(record["checks"], gate["checks"])
                self.assertEqual(record["observers"], gate["observers"])

    def test_the_job_passes_through_observing_and_evaluating(self):
        status, _record = self.work(repo(self.tmp / "head"),
                                    engines.GodotGate(replay=self.game.replay, rule=rec.BOTH, visual=self.game.observer()))
        self.assertEqual([h["phase"] for h in status["history"]],
                         ["queued", "preparing", "executing", "observing", "evaluating", "completed"])

    def test_the_registered_engine_is_engine_only_and_its_record_says_so(self):
        self.assertEqual(engines.ENGINES["godot"]._rule, rec.ENGINE_ONLY)
        _status, record = self.work(repo(self.tmp / "head"), engines.GodotGate(replay=self.game.replay))
        self.assertEqual((record["decision"], record["observers"]), ("accept", {"rule": "engine-only", "visual": None}))

    def test_the_sample_without_a_visual_observer_rejects_the_bug_and_accepts_nothing(self):
        from tests.test_orchestrator import PatchedReplay

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            results = smp.run(self.store, engines={"godot": engines.GodotGate(replay=PatchedReplay(), rule=rec.BOTH)})
        self.assertEqual([r["status"]["decision"] for r in results], ["needs-review", "reject", "needs-review"])
        for r in (results[0], results[2]):
            self.assertTrue(any("no visual observer was asked" in why for why in r["status"]["reasons"]), r["status"]["reasons"])


if __name__ == "__main__":
    unittest.main()
