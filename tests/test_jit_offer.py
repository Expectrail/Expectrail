"""What the generator is offered (expectrail/jit/offer.py, issue #285): one setting, off by default.

Under ``baseline`` the prompts and the probe list must be what they were before the setting existed, so
the baseline dispatch measures the generator as it was. Under ``signals-reach`` the three held-back
signals and the reach probes are offered. Each step of one change, and the score, must agree on the
setting. Offline: no engine, no model key."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from expectrail.contracts import load_strict, validate_v1
from expectrail.jit import cli, intent, offer
from expectrail.jit.diff_map import diff_map
from expectrail.jit.probes import jit_library
from expectrail.jit.run import generate
from expectrail.repro import reach, score
from tests.jit_fixtures import PROFILE, Case, JitGame, Transport, reply
from tests.test_repro_score import Fixture, check

REPO = Path(__file__).resolve().parents[1]
PROF = json.loads(PROFILE.read_text(encoding="utf-8"))
HELD = ("coins_collected", "player_screen_x_range_px", "player_screen_y_range_px")
NO_FIX = REPO / "bench" / "jit" / "public" / "no-fix.patch"
REPORT = "When I jump and press shoot in the air, nothing comes out."

# Computed on main at b87ff08, before the setting existed (the same inputs as below). If one of these
# moves, the baseline prompt changed: that is a change to the generator and needs its own run.
SYSTEM_SHA = "e4ef7a5ed490edc5742557d2c29a8303c196e35b3936f9b777ffb903ac989a11"
REVISE_SYSTEM_SHA = "544810189b454f8be6fd696e9c5882fa701676f4691730c47a9212e09d845b5a"
SAMPLE_PROMPT_SHA = "f0203e6cf11e53ede10533b765eab7d43420a85dcc6b9dd0c389facb1b8ef46c"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sample_probes(which: str = offer.BASELINE) -> list[dict]:
    probes = offer.library(PROF["actions"], which, REPORT)
    probes[0]["measured"] = {"clean": {"air_jumps": 1, "coins_collected": 5, "player_screen_x_range_px": 3.5},
                             "bugBuild": {"air_jumps": 4, "coins_collected": 0, "player_screen_x_range_px": 3.5}}
    return probes


def answer_on(*signals_used) -> str:
    return json.dumps({"candidates": [
        {"id": f"check-{i}", "statement": "A rule.", "claimId": "player.jump", "class": "player",
         "operation": {"type": "relation", "signal": name, "comparator": "lte", "toleranceAbs": 0,
                       "left": "jump-w0-x2", "right": "jump-w0-x8"}} for i, name in enumerate(signals_used)]})


class TheSetting(unittest.TestCase):
    def test_two_settings_and_the_default_is_the_baseline(self):
        self.assertEqual(offer.OFFERS, ("baseline", "signals-reach"))
        self.assertEqual(offer.DEFAULT, "baseline")
        for bad in ("", "all", None, "Baseline", 1):
            with self.assertRaises(offer.OfferError):
                offer.check(bad)

    def test_a_record_that_states_none_is_the_baseline_and_one_that_states_nonsense_is_refused(self):
        self.assertEqual(offer.of_record(None), "baseline")
        self.assertEqual(offer.of_record("signals-reach"), "signals-reach")
        with self.assertRaises(offer.OfferError):
            offer.of_record("everything")

    def test_signals_reach_adds_exactly_the_three_held_signals(self):
        self.assertEqual(set(offer.signals("baseline")), set(intent.OFFERED))
        self.assertEqual(set(offer.signals("signals-reach")) - set(offer.signals("baseline")), set(HELD))
        self.assertEqual(set(intent.NOT_YET_OFFERED), set(HELD))

    def test_the_schemas_name_the_same_settings(self):
        run = json.loads((REPO / "contracts" / "jit-run.v1.schema.json").read_text(encoding="utf-8"))
        scored = json.loads((REPO / "contracts" / "repro-score.v1.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(run["properties"]["settings"]["properties"]["offer"]["enum"], list(offer.OFFERS))
        self.assertNotIn("offer", run["properties"]["settings"]["required"])   # old records have none
        self.assertEqual(scored["properties"]["offer"]["enum"], list(offer.OFFERS))
        self.assertIn("offer", scored["required"])


class TheBaselineIsUnchanged(unittest.TestCase):
    def test_the_system_prompts_are_byte_for_byte_those_of_main_before_the_setting(self):
        self.assertEqual(sha(intent.SYSTEM), SYSTEM_SHA)
        self.assertEqual(sha(intent.system_for("baseline")), SYSTEM_SHA)
        self.assertEqual(sha(intent.SYSTEM + intent.REVISE_SYSTEM), REVISE_SYSTEM_SHA)

    def test_a_user_prompt_is_byte_for_byte_that_of_main_before_the_setting(self):
        probes = sample_probes()
        patch = NO_FIX.read_text(encoding="utf-8")
        dmap = diff_map(patch, PROF, probes)
        self.assertEqual(sha(intent.prompt(REPORT, patch, dmap, PROF, probes)), SAMPLE_PROMPT_SHA)
        self.assertEqual(sha(intent.prompt(REPORT, patch, dmap, PROF, probes, offer="baseline")), SAMPLE_PROMPT_SHA)

    def test_the_baseline_library_is_the_jit_library(self):
        self.assertEqual(offer.library(PROF["actions"], "baseline", REPORT), jit_library(PROF["actions"]))

    def test_the_spark_call_under_the_baseline_sends_the_baseline_system_prompt(self):
        t = Transport(reply(answer_on("air_jumps")))
        propose = intent.spark_intent(transport=t)
        probes = jit_library(PROF["actions"])
        propose(REPORT, NO_FIX.read_text(encoding="utf-8"), diff_map(NO_FIX.read_text(encoding="utf-8"), PROF, probes),
                PROF, probes)
        self.assertEqual(sha(t.bodies[0]["messages"][0]["content"]), SYSTEM_SHA)
        self.assertEqual(propose.offer, "baseline")


class SignalsReach(unittest.TestCase):
    def test_the_system_prompt_names_and_explains_all_fourteen_signals(self):
        system = intent.system_for("signals-reach")
        for name, meaning in {**intent.SIGNAL_MEANINGS, **intent.NOT_YET_OFFERED}.items():
            self.assertIn(f"- {name}: {meaning}", system)
        self.assertIn("The SIGNAL names are: " + ", ".join(sorted(offer.signals("signals-reach"))) + ".", system)
        self.assertNotEqual(sha(system), SYSTEM_SHA)

    def test_the_prompt_carries_the_held_signals_measurements_and_the_reach_probes(self):
        probes = sample_probes("signals-reach")
        patch = NO_FIX.read_text(encoding="utf-8")
        dmap = diff_map(patch, PROF, probes)
        sent = json.loads(intent.prompt(REPORT, patch, dmap, PROF, probes, offer="signals-reach"))["probesAvailable"]
        self.assertEqual(sent[0]["measured"]["bugBuild"],
                         {"air_jumps": 4, "coins_collected": 0, "player_screen_x_range_px": 3.5})
        self.assertIn("reach-jump-with-shoot", [p["id"] for p in sent])
        # The same probes under the baseline: no held signal, and no reach probe is in the library to send.
        base = json.loads(intent.prompt(REPORT, patch, dmap, PROF, probes, offer="baseline"))["probesAvailable"]
        self.assertEqual(base[0]["measured"]["bugBuild"], {"air_jumps": 4})

    def test_the_library_gains_the_eight_reach_probes_and_nothing_else(self):
        base = jit_library(PROF["actions"])
        more = offer.library(PROF["actions"], "signals-reach", REPORT)
        self.assertEqual(more[:len(base)], base)
        added = more[len(base):]
        self.assertEqual(len(added), 8)
        self.assertTrue(all(p["family"] == "reach" and p["id"].startswith("reach-") for p in added))
        self.assertEqual(sorted(p["id"] for p in added), sorted(p["id"] for p in reach.reach_probes(PROF["actions"], base)))
        # The no-fix candidate touches no claimed file, so the diff map keeps them for the prompt.
        self.assertTrue(set(p["id"] for p in added) <= set(diff_map(NO_FIX.read_text(encoding="utf-8"), PROF, more)["probeIds"]))

    def test_the_report_only_orders_the_reach_probes(self):
        a = offer.library(PROF["actions"], "signals-reach", "jump and shoot")
        b = offer.library(PROF["actions"], "signals-reach", "")
        self.assertEqual(sorted(p["id"] for p in a), sorted(p["id"] for p in b))
        self.assertEqual(a[len(jit_library(PROF["actions"]))]["id"], "reach-jump-with-shoot")

    def test_a_check_on_a_held_signal_is_kept_under_signals_reach_and_dropped_under_the_baseline(self):
        ids = {"jump-w0-x2", "jump-w0-x8"}
        _p, kept, notes = intent.parse_answer(answer_on("air_jumps", "coins_collected"), PROF, ids, offer="signals-reach")
        self.assertEqual([e["spec"]["operation"]["signal"] for e in kept], ["air_jumps", "coins_collected"])
        self.assertFalse(any("not offered" in n for n in notes))
        _p, kept, notes = intent.parse_answer(answer_on("air_jumps", "coins_collected"), PROF, ids)
        self.assertEqual([e["spec"]["operation"]["signal"] for e in kept], ["air_jumps"])
        self.assertTrue(any("coins_collected is not offered yet" in n for n in notes))


class OneSettingPerChange(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jit-offer-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.patch = NO_FIX.read_text(encoding="utf-8")

    def proposal(self, which: str, *signals_used) -> Path:
        t = Transport(reply(answer_on(*signals_used)))
        out = self.tmp / which
        doc = intent.propose_to_file(intent.spark_intent(transport=t, offer=which), REPORT, self.patch, PROF,
                                     offer.library(PROF["actions"], which, REPORT), out)
        self.assertIsNone(doc["error"])
        self.assertEqual(doc["offer"], which)
        return out / intent.PROPOSAL_NAME

    def replay(self, path: Path, which: str) -> dict:
        probes = offer.library(PROF["actions"], which, REPORT)
        return intent.from_proposal(path, offer=which)(REPORT, self.patch, diff_map(self.patch, PROF, probes), PROF, probes)

    def test_a_proposal_is_replayed_under_its_own_setting_only(self):
        wide = self.proposal("signals-reach", "air_jumps", "coins_collected")
        self.assertEqual(len(self.replay(wide, "signals-reach")["candidates"]), 2)
        with self.assertRaisesRegex(intent.IntentUnavailable, "PROPOSAL_MISMATCH: .*signals-reach"):
            self.replay(wide, "baseline")
        narrow = self.proposal("baseline", "air_jumps")
        with self.assertRaisesRegex(intent.IntentUnavailable, "PROPOSAL_MISMATCH"):
            self.replay(narrow, "signals-reach")
        self.assertEqual(len(self.replay(narrow, "baseline")["candidates"]), 1)

    def test_a_proposal_written_before_the_setting_is_a_baseline_proposal(self):
        path = self.proposal("baseline", "air_jumps")
        doc = json.loads(path.read_text(encoding="utf-8"))
        del doc["offer"]
        path.write_text(json.dumps(doc), encoding="utf-8")
        self.assertEqual(len(self.replay(path, "baseline")["candidates"]), 1)
        with self.assertRaisesRegex(intent.IntentUnavailable, "PROPOSAL_MISMATCH"):
            self.replay(path, "signals-reach")

    def test_a_baseline_proposal_edited_to_carry_a_held_signal_is_still_refused(self):
        path = self.proposal("baseline", "air_jumps")
        doc = json.loads(path.read_text(encoding="utf-8"))
        cand = copy.deepcopy(doc["candidates"][0])
        cand["spec"]["operation"]["signal"] = "player_screen_y_range_px"
        validate_v1(cand["spec"], "trace-spec")
        doc["candidates"] = [cand]
        path.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaisesRegex(intent.IntentUnavailable, "not offered yet"):
            self.replay(path, "baseline")

    def test_a_proposal_that_states_an_unknown_setting_is_refused(self):
        path = self.proposal("baseline", "air_jumps")
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["offer"] = "everything"
        path.write_text(json.dumps(doc), encoding="utf-8")
        for which in offer.OFFERS:
            with self.assertRaisesRegex(intent.IntentUnavailable, "PROPOSAL_MISMATCH"):
                self.replay(path, which)

    def test_the_first_round_record_must_be_of_the_same_setting_for_a_revision(self):
        record = {"inputs": {"patchSha256": intent._sha(self.patch)}, "settings": {"offer": "signals-reach"},
                  "spend": {"replayUsd": 0.0}}
        path = self.tmp / "jit-run.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        from unittest import mock

        with mock.patch("expectrail.contracts.load_strict", return_value=record):
            self.assertIs(intent.load_record(path, self.patch, offer="signals-reach"), record)
            with self.assertRaisesRegex(intent.IntentUnavailable, "RECORD_MISMATCH: .*another offer"):
                intent.load_record(path, self.patch)
            record["settings"].pop("offer")
            self.assertIs(intent.load_record(path, self.patch), record)
            with self.assertRaisesRegex(intent.IntentUnavailable, "RECORD_MISMATCH"):
                intent.load_record(path, self.patch, offer="signals-reach")


class TheRunRecord(unittest.TestCase):
    def run_case(self, which, **kw):
        case = Case()
        self.addCleanup(shutil.rmtree, case.dir, ignore_errors=True)
        t = Transport(reply(answer_on("air_jumps")))
        kw.setdefault("intent", intent.spark_intent(transport=t, offer=which))
        doc = generate(PROFILE, REPORT, case.patch("fix-wrong"), [case.patch("air-jump")], case.dir / "out",
                       runner=JitGame(), variants_fn=case.variants(), offer=which, **kw)
        return doc, t

    def test_the_record_says_which_setting_and_validates(self):
        for which in offer.OFFERS:
            doc, t = self.run_case(which)
            validate_v1(doc, "jit-run")
            self.assertEqual(doc["status"], "complete", doc["reason"])
            self.assertEqual(doc["settings"]["offer"], which)
            self.assertEqual(sha(t.bodies[0]["messages"][0]["content"]) == SYSTEM_SHA, which == "baseline")

    def test_the_default_is_the_baseline(self):
        case = Case()
        self.addCleanup(shutil.rmtree, case.dir, ignore_errors=True)
        t = Transport(reply(answer_on("air_jumps")))
        doc = generate(PROFILE, REPORT, case.patch("fix-wrong"), [case.patch("air-jump")], case.dir / "out",
                       runner=JitGame(), variants_fn=case.variants(), intent=intent.spark_intent(transport=t))
        self.assertEqual(doc["settings"]["offer"], "baseline")

    def test_a_model_told_about_another_setting_generates_nothing(self):
        doc, t = self.run_case("baseline", intent=intent.spark_intent(transport=Transport(reply(answer_on("air_jumps"))),
                                                                       offer="signals-reach"))
        self.assertEqual(doc["status"], "nothing-generated")
        self.assertTrue(doc["reason"].startswith("OFFER_MISMATCH"), doc["reason"])
        self.assertEqual(doc["catches"], [])
        self.assertEqual(t.bodies, [])

    def test_an_unknown_setting_is_refused_before_anything_runs(self):
        with self.assertRaises(offer.OfferError):
            self.run_case("everything", intent=None)

    def test_a_reach_probe_a_check_uses_is_recorded_as_reach(self):
        case = Case()
        self.addCleanup(shutil.rmtree, case.dir, ignore_errors=True)
        ans = json.dumps({"candidates": [{"id": "reach-moves", "statement": "Holding left while jumping moves left.",
                                          "claimId": "player.jump", "class": "player",
                                          "operation": {"type": "max_episode_rise", "maxPx": 100000},
                                          "appliesTo": ["reach-move-left-with-jump"]}]})
        # A patch no claim names, so the diff map keeps every probe, as on the reproduction bench.
        doc = generate(PROFILE, REPORT, case.patch("fix-wrong", NO_FIX.read_text(encoding="utf-8")),
                       [case.patch("air-jump")], case.dir / "out", runner=JitGame(), variants_fn=case.variants(),
                       intent=intent.spark_intent(transport=Transport(reply(ans)), offer="signals-reach"),
                       offer="signals-reach")
        validate_v1(doc, "jit-run")
        self.assertEqual(doc["status"], "complete", doc["reason"])
        self.assertEqual([(p["id"], p["source"]) for p in doc["probes"]], [("reach-move-left-with-jump", "reach")])

    def test_under_the_baseline_a_check_on_a_reach_probe_applies_to_nothing(self):
        case = Case()
        self.addCleanup(shutil.rmtree, case.dir, ignore_errors=True)
        ans = json.dumps({"candidates": [{"id": "reach-moves", "statement": "A rule.", "claimId": "player.jump",
                                          "class": "player", "operation": {"type": "max_episode_rise", "maxPx": 100000},
                                          "appliesTo": ["reach-move-left-with-jump"]}]})
        doc = generate(PROFILE, REPORT, case.patch("fix-wrong", NO_FIX.read_text(encoding="utf-8")),
                       [case.patch("air-jump")], case.dir / "out", runner=JitGame(), variants_fn=case.variants(),
                       intent=intent.spark_intent(transport=Transport(reply(ans))))
        self.assertEqual(doc["status"], "nothing-generated")
        self.assertEqual(doc["probes"], [])


class TheScore(Fixture):
    def put_offer(self, did, which, checks):
        path = self.put(did, checks)
        rec = json.loads(path.read_text(encoding="utf-8"))
        if which is None:
            rec["settings"].pop("offer", None)
        else:
            rec["settings"]["offer"] = which
        path.write_text(json.dumps(rec), encoding="utf-8")
        load_strict(path, "jit-run")

    def test_a_score_counts_the_records_of_its_own_setting_only(self):
        self.put_offer("sig-one", "signals-reach", [check("jit-a")])
        self.put_offer("sig-two", None, [check("jit-b")])
        base = self.score()
        self.assertEqual(base["offer"], "baseline")
        rows = {r["id"]: r for r in base["rows"]}
        self.assertEqual(rows["sig-one"]["outcome"], "no-result")
        self.assertIn("made with offer signals-reach, and this score counts offer baseline", rows["sig-one"]["why"])
        self.assertEqual(rows["sig-two"]["outcome"], "reproduced")
        wide = self.score(offer="signals-reach")
        self.assertEqual(wide["offer"], "signals-reach")
        rows = {r["id"]: r for r in wide["rows"]}
        self.assertEqual(rows["sig-one"]["outcome"], "reproduced")
        self.assertEqual(rows["sig-two"]["outcome"], "no-result")
        self.assertEqual(score.problems(wide), [])

    def test_the_page_names_the_setting(self):
        self.put_offer("sig-one", "signals-reach", [check("jit-a")])
        page = score.render(self.score(offer="signals-reach"))
        self.assertIn("Generator offered: `signals-reach`", page)
        self.assertIn("Generator offered: `baseline`", score.render(self.score()))

    def test_an_unknown_setting_or_a_score_record_without_one_is_refused(self):
        with self.assertRaises(score.ScoreError):
            self.score(offer="everything")
        record = self.score()
        del record["offer"]
        self.assertTrue(any("offer" in p for p in score.problems(record)))

    def test_the_command_takes_the_setting(self):
        from unittest import mock

        from expectrail.repro.__main__ import main

        seen = []

        def fake_score(*_a, **kw):
            seen.append(kw.get("offer"))
            raise score.ScoreError("stop here")

        for args, want in (([], "baseline"), (["--offer", "signals-reach"], "signals-reach")):
            with mock.patch.object(score, "score", fake_score), contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["score", "--records", str(self.records), "--out", str(self.tmp / "o"), *args]), 1)
            self.assertEqual(seen[-1], want)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as stop:
            main(["score", "--records", str(self.records), "--out", str(self.tmp / "o"), "--offer", "all"])
        self.assertEqual(stop.exception.code, 2)


class TheCommands(unittest.TestCase):
    def test_every_step_takes_the_setting_and_refuses_an_unknown_one(self):
        for cmd in ("run", "propose", "revise", "measure"):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
                cli.main([cmd, "--offer", "everything", "--out", "x", "--report-file", "r", "--candidate", "c",
                          "--proposal", "p", "--record", "r"])
            self.assertEqual(stop.exception.code, 2, cmd)

    def test_propose_records_the_setting_it_was_given(self):
        from unittest import mock

        seen = []

        def fake(offer="baseline"):
            seen.append(offer)

            def propose(*_a, **_k):
                return {"probes": [], "candidates": [], "diagnostics": [], "usage": {}, "promptSha256": None}
            propose.model, propose.system, propose.offer = "test", "", offer
            return propose

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(intent, "spark_intent", fake), \
                contextlib.redirect_stdout(io.StringIO()):
            report = Path(tmp) / "r.txt"
            report.write_text(REPORT, encoding="utf-8")
            cli.main(["propose", "--report-file", str(report), "--candidate", str(NO_FIX), "--out", tmp,
                      "--offer", "signals-reach"])
            doc = json.loads((Path(tmp) / intent.PROPOSAL_NAME).read_text(encoding="utf-8"))
        self.assertEqual(seen, ["signals-reach"])
        self.assertEqual(doc["offer"], "signals-reach")


class TheWorkflow(unittest.TestCase):
    def setUp(self):
        self.text = (REPO / ".github" / "workflows" / "jit.yml").read_text(encoding="utf-8")
        self.wf = yaml.safe_load(self.text)

    def test_the_input_defaults_to_the_baseline(self):
        inputs = self.wf[True]["workflow_dispatch"]["inputs"] if True in self.wf else self.wf["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["offer"]["options"], list(offer.OFFERS))
        self.assertEqual(inputs["offer"]["default"], "baseline")

    def test_the_plan_checks_it_and_the_known_bugs_bench_takes_the_baseline_only(self):
        plan = self.wf["jobs"]["plan"]
        self.assertEqual(plan["env"]["OFFER"], "${{ inputs.offer || 'baseline' }}")
        self.assertEqual(plan["outputs"]["offer"], "${{ steps.plan.outputs.offer }}")
        step = next(s["run"] for s in plan["steps"] if s.get("id") == "plan")
        self.assertLess(step.index("offer must be baseline or signals-reach"), step.index('if [[ "$MODE" == "bench" ]]'))
        self.assertIn("registered under the baseline offer", step)

    def test_every_step_of_a_change_and_the_score_get_the_same_setting(self):
        jobs = self.wf["jobs"]
        for name, command in (("measure", "jit.cli measure"), ("propose", "jit.cli propose"),
                              ("replay", "jit.cli run"), ("revise", "jit.cli revise"),
                              ("replay-final", "jit.cli run"), ("repro-score", "expectrail.repro score")):
            job = jobs[name]
            runs = [s for s in job["steps"] if command in (s.get("run") or "")]
            self.assertEqual(len(runs), 1, name)
            env = {**job.get("env", {}), **runs[0].get("env", {})}
            self.assertEqual(env.get("OFFER"), "${{ needs.plan.outputs.offer }}", name)
            self.assertIn('--offer "$OFFER"', runs[0]["run"], name)
        self.assertIn('--report-file "$REPORT"', next(s["run"] for s in jobs["measure"]["steps"]
                                                      if "jit.cli measure" in (s.get("run") or "")))

    def test_the_rehearsal_is_untouched(self):
        self.assertNotIn("offer", json.dumps(self.wf["jobs"]["rehearsal"]))
