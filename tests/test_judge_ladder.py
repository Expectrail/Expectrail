"""The judge ladder (agents/judge_ladder.py, docs/fallbacks.md): when the judge cannot answer, judge
the same candidate again, then with Glimmer checked against the engine, then stop. Never re-judge a
rejection, and never spend a fix attempt on an outage."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agents.judge_ladder as jl
from agents.loop import one_run
from agents.sam_observations import BACKEND_ENV, SamError
from agents.verifier import verify as real_verify
from harness.run import REPO

FIXTURES = REPO / "agents" / "fixtures"


def verdict(decision: str, *, check: str = "pass") -> dict:
    return {"decision": decision, "reasons": [f"x {decision}"],
            "checks": [{"kind": "regression", "spec": "player-always-visible", "route": "smoke", "result": check}]}


class Judge:
    """A verify stand-in: answers from a script, writes an observer error when the judge is 'down'."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, request, candidate, out, **kwargs):
        answer = self.answers.pop(0)
        self.calls.append({"dir": out.name, "backend": os.environ.get(BACKEND_ENV)})
        out.mkdir(parents=True, exist_ok=True)
        if answer == "down":
            (out / "observations-player-always-visible-error.txt").write_text(
                "sam observations unavailable: HTTP 503 from the model API\n")
            return verdict("needs-review", check="needs-review")
        if answer == "budget":   # as agents/observations.py writes a SamError of that kind
            (out / "observations-player-always-visible-error.txt").write_text(
                "sam observations unavailable (kind=budget): this run's SAM spend cap is reached\n")
            return verdict("needs-review", check="needs-review")
        return verdict(answer, check={"accept": "pass", "reject": "fail"}.get(answer, "needs-review"))


class LadderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "attempt-01"
        patches = [mock.patch.dict(os.environ, {jl.RETRY_WAIT_ENV: "0", BACKEND_ENV: "sam",
                                                 "EXPECTRAIL_GLIMMER_MODEL": "accounts/x/deployments/y",
                                                 "EXPECTRAIL_GLIMMER_API_KEY": "glimmer-key"}),
                   mock.patch.object(jl, "sam_on", lambda: True),
                   mock.patch("agents.fireworks_deployment.get",
                              lambda account, deployment, key: {"minReplicaCount": 0, "maxReplicaCount": 1})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.woke = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_ladder(self, judge, warm=None):
        return jl.judge({}, Path("candidate.patch"), self.dir, verify_fn=judge, sleep=lambda s: None,
                        warm_fn=warm or (lambda timeout_s: self.woke.append(timeout_s)))

    def test_an_answer_is_final_and_climbs_nothing(self):
        for answer in ("accept", "reject"):
            judge = Judge(answer)
            v, where, record = self.run_ladder(judge)
            self.assertEqual(v["decision"], answer)
            self.assertEqual(len(judge.calls), 1)
            self.assertEqual((record["judgedBy"], record["stopped"]), ("sam", False))
            self.assertEqual(where, self.dir)

    def test_a_rejection_is_never_judged_again(self):
        judge = Judge("down", "reject")
        v, _, record = self.run_ladder(judge)
        self.assertEqual(v["decision"], "reject")
        self.assertEqual(len(judge.calls), 2)  # the retry answered: Glimmer is never asked
        self.assertEqual(self.woke, [])
        self.assertEqual(record["judgedBy"], "sam (retried)")

    def test_a_passing_outage_is_retried_on_the_same_judge(self):
        judge = Judge("down", "accept")
        v, where, record = self.run_ladder(judge)
        self.assertEqual(v["decision"], "accept")
        self.assertEqual(where.name, "attempt-01-retry")
        self.assertEqual([c["backend"] for c in judge.calls], ["sam", "sam"])
        self.assertIsNone(jl.report_note(record))

    def test_when_sam_stays_down_glimmer_checked_against_the_engine_decides(self):
        judge = Judge("down", "down", "accept")
        v, where, record = self.run_ladder(judge)
        self.assertEqual(v["decision"], "accept")
        self.assertEqual(where.name, "attempt-01-glimmer")
        self.assertEqual(judge.calls[2]["backend"], "glimmer-engine")  # never Glimmer alone
        self.assertEqual(os.environ[BACKEND_ENV], "sam")  # restored afterwards
        self.assertTrue(record["fallback"])
        self.assertEqual(record["judgedBy"], "glimmer-engine (sam did not answer)")
        self.assertEqual(len(self.woke), 1)
        self.assertIn("position log", jl.report_note(record))

    def test_glimmer_can_reject_too(self):
        v, _, record = self.run_ladder(Judge("down", "down", "reject"))
        self.assertEqual(v["decision"], "reject")
        self.assertFalse(record["stopped"])

    def test_a_budget_stop_ends_the_ladder_and_asks_no_other_judge(self):
        # First review of #343: a stop that holds spend must not start other spend, and Glimmer, which
        # would accept here, must not be asked. Before, the ladder skipped the retry and went on to it.
        judge = Judge("budget", "accept", "accept")
        v, where, record = self.run_ladder(judge)
        self.assertEqual(v["decision"], "needs-review")
        self.assertEqual(where.name, "attempt-01")
        self.assertEqual([c["backend"] for c in judge.calls], ["sam"])   # asked once; no retry, no Glimmer
        self.assertEqual(self.woke, [])                                   # the deployment was not woken
        self.assertEqual((record["judgedBy"], record["stopped"], record["budget"]), (None, True, True))
        self.assertNotIn("fallback", record)
        note = jl.report_note(record)
        self.assertIn("spend cap", note)
        self.assertIn("no other judge was asked", note)

    def test_a_budget_stop_beside_a_passing_error_is_still_a_budget_stop(self):
        # One spent cap fails every later request; an error that waiting would fix may sit beside it.
        class Both(Judge):
            def __call__(self, request, candidate, out, **kwargs):
                result = super().__call__(request, candidate, out, **kwargs)
                (out / "observations-another-spec-error.txt").write_text(
                    "sam observations unavailable (kind=rate-limit): slow down\n")
                return result
        judge = Both("budget", "accept", "accept")
        v, _where, record = self.run_ladder(judge)
        self.assertEqual(jl.outage_kind(self.dir), "budget")
        self.assertEqual((v["decision"], len(judge.calls), record.get("budget")), ("needs-review", 1, True))

    def test_when_no_judge_answers_the_ladder_stops(self):
        v, _, record = self.run_ladder(Judge("down", "down", "down"))
        self.assertEqual(v["decision"], "needs-review")
        self.assertTrue(record["stopped"])
        self.assertIsNone(record["judgedBy"])
        self.assertIn("A person must judge it", jl.report_note(record))

    def test_without_a_glimmer_deployment_the_ladder_skips_it_and_stops(self):
        with mock.patch.dict(os.environ, {"EXPECTRAIL_GLIMMER_MODEL": ""}):
            judge = Judge("down", "down")
            _, _, record = self.run_ladder(judge)
        self.assertEqual(len(judge.calls), 2)
        self.assertTrue(record["stopped"])
        self.assertIn("no Glimmer deployment", record["steps"][-1]["skipped"])

    def test_a_deployment_that_does_not_wake_is_skipped(self):
        def asleep(timeout_s):
            raise SamError("glimmer deployment did not wake within 600 s")

        judge = Judge("down", "down")
        _, _, record = self.run_ladder(judge, warm=asleep)
        self.assertEqual(len(judge.calls), 2)
        self.assertTrue(record["stopped"])
        self.assertIn("did not wake", record["steps"][-1]["skipped"])

    def test_a_deployment_scaled_to_zero_is_skipped_at_once_and_never_woken(self):
        judge = Judge("down", "down")
        with mock.patch("agents.fireworks_deployment.get",
                        lambda account, deployment, key: {"minReplicaCount": 0, "maxReplicaCount": 0}):
            _, _, record = self.run_ladder(judge)
        self.assertEqual(self.woke, [])  # no request went to the deployment
        self.assertEqual(len(judge.calls), 2)
        self.assertTrue(record["stopped"])
        self.assertIn("scaled to 0-0 replicas", record["steps"][-1]["skipped"])
        self.assertIn("glimmer-engine: skipped", jl.report_note(record))

    def test_a_deployment_that_cannot_be_read_is_skipped(self):
        from agents.fireworks_deployment import DeploymentError

        def suspended(account, deployment, key):
            raise DeploymentError("HTTP 412: account suspended")

        with mock.patch("agents.fireworks_deployment.get", suspended):
            _, _, record = self.run_ladder(Judge("down", "down"))
        self.assertTrue(record["stopped"])
        self.assertIn("could not be read", record["steps"][-1]["skipped"])
        self.assertEqual(self.woke, [])

    def test_each_outage_step_records_what_the_judge_said(self):
        _, _, record = self.run_ladder(Judge("down", "down", "down"))
        self.assertTrue(all("HTTP 503" in s["error"] for s in record["steps"]))

    def test_glimmer_is_not_its_own_fallback(self):
        with mock.patch.dict(os.environ, {BACKEND_ENV: "glimmer-engine"}):
            judge = Judge("down", "down")
            _, _, record = self.run_ladder(judge)
        self.assertEqual(len(judge.calls), 2)
        self.assertTrue(record["stopped"])

    def test_needs_review_for_any_other_reason_is_not_an_outage(self):
        self.dir.mkdir(parents=True)
        self.assertFalse(jl.judge_unavailable(verdict("needs-review", check="needs-review"), self.dir))
        (self.dir / "observations-x-error.txt").write_text("sam observations unavailable: 429\n")
        self.assertTrue(jl.judge_unavailable(verdict("needs-review", check="needs-review"), self.dir))
        failing = {"decision": "needs-review", "checks": [{"result": "fail"}, {"result": "needs-review"}]}
        self.assertFalse(jl.judge_unavailable(failing, self.dir))
        self.assertFalse(jl.judge_unavailable(verdict("accept"), self.dir))


class DrillTest(unittest.TestCase):
    def test_the_drill_takes_sam_down_before_any_cache_and_leaves_glimmer_alone(self):
        from agents.observations import from_trace

        with mock.patch.dict(os.environ, {"EXPECTRAIL_JUDGE_DRILL": "sam-unavailable", BACKEND_ENV: "sam"}):
            with self.assertRaises(SystemExit) as caught:
                from_trace({"rows": []}, provider="sam", frames_dir="/nonexistent")
        self.assertIn(jl.UNAVAILABLE, str(caught.exception))
        self.assertIn("drill", str(caught.exception))
        from agents.observations import judge_drill

        with mock.patch.dict(os.environ, {"EXPECTRAIL_JUDGE_DRILL": "sam-unavailable", BACKEND_ENV: "glimmer-engine"}):
            self.assertIsNone(judge_drill())
        with mock.patch.dict(os.environ, {"EXPECTRAIL_JUDGE_DRILL": ""}):
            self.assertIsNone(judge_drill())
        with mock.patch.dict(os.environ, {"EXPECTRAIL_JUDGE_DRILL": "everything-down"}), self.assertRaises(SystemExit):
            judge_drill()

    def test_the_trace_provider_ignores_the_drill(self):
        from agents.observations import from_trace

        with mock.patch.dict(os.environ, {"EXPECTRAIL_JUDGE_DRILL": "sam-unavailable"}):
            obs = from_trace({"rows": [], "physicsTicksPerSecond": 120}, provider="trace")
        self.assertIn("frames", obs)


class KeysTest(unittest.TestCase):
    def test_the_glimmer_key_never_reaches_the_fixer(self):
        from agents.glimmer_client import KEY_ENVS
        from agents.keys import muse_subprocess_env

        env = muse_subprocess_env({name: "glimmer-key" for name in KEY_ENVS} | {"PATH": "/usr/bin"})
        self.assertFalse(set(KEY_ENVS) & set(env))


class LoopLadderTest(unittest.TestCase):
    """The loop spends no fix attempt on an outage, and the morning report tells a person why."""

    def run_loop(self, answers):
        calls = []

        def fixer(req, out, **kwargs):
            calls.append(out.name)
            out.mkdir(parents=True, exist_ok=True)
            (out / "fixer-work" / "player").mkdir(parents=True, exist_ok=True)
            shutil.copy2(FIXTURES / "fix-collision-mask.patch", out / "candidate.patch")
            return {"source": "muse", "patchSha256": "0" * 64}

        def verifier(req, candidate, out, **kwargs):
            doc = real_verify(req, candidate, out, observations_path=FIXTURES / "obs-fixed.json", skip_harness=True)
            if answers.pop(0) == "down":
                doc = dict(doc, decision="needs-review",
                           reasons=["regression check player-stays-above-ground needs review on smoke"],
                           checks=[dict(c, result="needs-review") if c["kind"] == "regression" else c
                                   for c in doc["checks"]])
                (out / "verification.json").write_text(json.dumps(doc))
                (out / "observations-error.txt").write_text("sam observations unavailable: HTTP 503\n")
            return doc

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {jl.RETRY_WAIT_ENV: "0", "EXPECTRAIL_BRIEFING": "evidence",
                                             "EXPECTRAIL_GLIMMER_MODEL": "accounts/x/deployments/y",
                                             "EXPECTRAIL_GLIMMER_API_KEY": "glimmer-key"}), \
                mock.patch("agents.loop.run_fixer", fixer), \
                mock.patch("agents.loop.verify", verifier), \
                mock.patch.object(jl, "current_judge", lambda: "sam"), \
                mock.patch("agents.fireworks_deployment.get",
                           lambda account, deployment, key: {"minReplicaCount": 0, "maxReplicaCount": 1}), \
                mock.patch("agents.glimmer_client.warm", lambda timeout_s: 0.0):
            result = one_run(Path(tmp) / "loop", use_muse=True, offline_triage=True,
                             observations=FIXTURES / "obs-fixed.json", candidate_patch=None,
                             skip_harness=True, run_trust=False)
            md = (Path(tmp) / "loop" / "morning" / "morning-report.md").read_text()
        return result, calls, md

    def test_an_outage_stops_the_loop_without_spending_fix_attempts(self):
        result, calls, md = self.run_loop(["down", "down", "down"])
        self.assertEqual(result["decision"], "needs-review")
        self.assertEqual(len(calls), 1)  # one fix, judged three times, and no second fix
        self.assertTrue(result["judge"]["stopped"])
        self.assertEqual(result["attempts"][0]["decision"], "needs-review")
        self.assertIn("No vision judge answered", md)

    def test_a_fallback_accept_is_labelled_for_the_person_who_approves_it(self):
        result, calls, md = self.run_loop(["down", "down", "accept"])
        self.assertEqual(result["decision"], "accept")
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["attempts"][0]["judge"], "glimmer-engine (sam did not answer)")
        self.assertIn("ground was judged on the engine's position log", md)

    def review_backend(self, answers):
        """Run the loop with the review on; return the vision backend in force when the review ran."""
        seen = {}

        def fake_review(_request, _candidate, out, **_kw):
            seen["backend"] = os.environ.get(BACKEND_ENV)
            return {"status": "REPAIR DEMONSTRATED", "evidenceLabel": "FRESH LIVE", "reasons": [],
                    "arms": {"base": None, "candidate": None}}

        with mock.patch.dict(os.environ, {"EXPECTRAIL_REVIEW": "on"}), \
                mock.patch("agents.review_change.review", side_effect=fake_review):
            result, _calls, _md = self.run_loop(answers)
        return result, seen.get("backend", "review not run"), os.environ.get(BACKEND_ENV)

    def test_after_a_fallback_the_review_judges_the_base_with_the_same_judge(self):
        result, during, after = self.review_backend(["down", "down", "accept"])
        self.assertEqual(result["decision"], "accept")
        self.assertEqual(during, jl.FALLBACK)  # the base is judged by Glimmer checked against the engine
        self.assertNotEqual(after, jl.FALLBACK)  # and the setting does not outlive the review

    def test_without_a_fallback_the_review_keeps_the_usual_judge(self):
        result, during, _after = self.review_backend(["accept"])
        self.assertEqual(result["decision"], "accept")
        self.assertNotEqual(during, jl.FALLBACK)
        self.assertNotEqual(during, "review not run")


if __name__ == "__main__":
    unittest.main()
