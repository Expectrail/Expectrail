"""The pre-run SAM check (agents/sam_health.py, docs/fallbacks.md): SAM is asked once before a run
spends anything, past the cache, and a run it stops has made no triage or fixer call."""
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from agents import loop, sam_health
from agents.judge_ladder import judge, outage_kind
from agents.observations import DRILL_ENV, PROVIDER_ENV, from_trace, judge_drill
from agents.sam_observations import BACKEND_ENV, Cache, MetaSamClient, SamError, http_error_kind, observe, sam_usage
from harness.run import REPO
from expectrail.contracts import validate

FIXTURES = REPO / "agents" / "fixtures"
ANSWER = (json.dumps({"output_text": "<0f>0<|box;x1=1;y1=2;x2=3;y2=4;w=1600;h=960;c=0.9|>"}).encode(),
          "application/json")


def http_error(status: int, body: str = "") -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api.meta.ai/v1/responses", status, "x", {}, io.BytesIO(body.encode()))


def client(*replies) -> MetaSamClient:
    """A real client whose transport plays ``replies``; an exception in them is raised."""
    left = list(replies)

    def transport(_body):
        reply = left.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    return MetaSamClient(transport=transport, sleep=lambda s: None)


def sam_env(**extra) -> mock._patch_dict:
    return mock.patch.dict(os.environ, {PROVIDER_ENV: "sam", BACKEND_ENV: "sam", DRILL_ENV: "", **extra})


class KindTest(unittest.TestCase):
    def test_each_http_status_has_its_kind(self):
        for status, body, kind in ((401, "", "auth"), (403, "forbidden", "auth"), (402, "", "credit"),
                                   (403, "credit balance is too low", "credit"), (429, "", "rate-limit"),
                                   (429, '{"code": "insufficient_quota"}', "credit"),
                                   (429, "per-minute quota exceeded, slow down", "rate-limit"), (500, "", "server"),
                                   (503, "", "server"), (400, "bad image", "request"), (404, "", "request")):
            with self.subTest(status=status, body=body):
                self.assertEqual(http_error_kind(status, body), kind)

    def test_the_client_raises_the_kind_and_status(self):
        with self.assertRaises(SamError) as caught:
            client(http_error(402, "out of credit")).segment(sam_health.PROBE_FRAME, "x")
        self.assertEqual((caught.exception.kind, caught.exception.status), ("credit", 402))

    def test_a_missing_key_is_auth(self):
        with mock.patch.dict(os.environ, {"MODEL_API_KEY": ""}), self.assertRaises(SamError) as caught:
            MetaSamClient().segment(sam_health.PROBE_FRAME, "x")
        self.assertEqual(caught.exception.kind, "auth")

    def test_a_dropped_connection_is_network_after_the_retries(self):
        c = client(*[OSError("reset")] * 4)
        with self.assertRaises(SamError) as caught:
            c.segment(sam_health.PROBE_FRAME, "x")
        self.assertEqual((caught.exception.kind, caught.exception.status), ("network", None))
        self.assertEqual(c.calls, 4)

    def test_a_reply_nobody_can_read_is_unknown_so_the_ladder_keeps_its_retry(self):
        with self.assertRaises(SamError) as caught:
            client((b"I cannot help with that", "text/plain")).segment(sam_health.PROBE_FRAME, "x")
        self.assertEqual(caught.exception.kind, "unknown")

    def test_the_observer_error_carries_the_kind_for_the_ladder(self):
        def down(trace, **kwargs):
            raise SamError("sam-3.1 HTTP 402: no", kind="credit", status=402)

        with sam_env(), mock.patch("agents.observations._load_sam_provider", return_value=down), \
                self.assertRaises(SystemExit) as caught:
            from_trace({"rows": []}, provider="sam", frames_dir="/nonexistent")
        self.assertIn("sam observations unavailable (kind=credit)", str(caught.exception))


class CheckTest(unittest.TestCase):
    def test_a_passing_check_says_nothing_and_sends_one_image(self):
        before = sam_usage()["images"]
        with sam_env():
            self.assertIsNone(sam_health.check(client(ANSWER)))
        self.assertEqual(sam_usage()["images"] - before, 1)

    def test_an_answer_with_nothing_in_it_is_still_an_answer(self):
        with sam_env():
            self.assertIsNone(sam_health.check(client((b'{"output_text": ""}', "application/json"))))

    def test_every_failure_says_its_kind(self):
        for reply, kind in ((http_error(401), "auth"), (http_error(403), "auth"), (http_error(402), "credit"),
                            (http_error(400), "request"), ((b"nope", "text/plain"), "unknown")):
            with self.subTest(kind=kind), sam_env():
                problem = sam_health.check(client(reply))
                self.assertEqual(problem["kind"], kind)
                self.assertIn(f"SAM did not answer before the run: {kind}", sam_health.reason(problem))

    def test_a_rate_limit_and_a_server_error_are_retried_and_then_stop_the_run(self):
        for status, kind in ((429, "rate-limit"), (503, "server")):
            with self.subTest(status=status), sam_env():
                c = client(*[http_error(status)] * 4)
                self.assertEqual(sam_health.check(c)["kind"], kind)
                self.assertEqual(c.calls, 4)

    def test_a_rate_limit_that_passes_is_not_a_problem(self):
        with sam_env():
            self.assertIsNone(sam_health.check(client(http_error(429), ANSWER)))

    def test_a_surprise_in_the_client_is_no_answer_not_a_crash(self):
        class Broken:
            def segment(self, png, prompt):
                raise KeyError("surprise")

        with sam_env():
            self.assertEqual(sam_health.check(Broken())["kind"], "unknown")

    def test_it_goes_past_the_cache(self):
        """The trap: a dead SAM plus a cached answer looks healthy through observe()."""
        with tempfile.TemporaryDirectory() as tmp, sam_env():
            cache = Cache(Path(tmp))
            observe({0: sam_health.PROBE_FRAME}, [0], {"robot": sam_health.PROBE_PROMPT}, client(ANSWER), cache)
            dead = client(http_error(402))
            self.assertIsNotNone(observe({0: sam_health.PROBE_FRAME}, [0], {"robot": sam_health.PROBE_PROMPT},
                                         dead, cache))  # the cache answers for a dead SAM
            self.assertEqual(dead.calls, 0)
            with mock.patch.dict(os.environ, {"EXPECTRAIL_SAM_CACHE": tmp}):
                self.assertEqual(sam_health.check(client(http_error(402)))["kind"], "credit")

    def test_nothing_is_sent_when_sam_is_not_the_judge(self):
        class Forbidden:
            def segment(self, png, prompt):
                raise AssertionError("no request may go out")

        with sam_env(**{PROVIDER_ENV: "trace"}):
            self.assertIsNone(sam_health.check(Forbidden()))
        with sam_env(**{BACKEND_ENV: "glimmer-engine"}):
            self.assertIsNone(sam_health.check(Forbidden()))

    def test_an_unknown_backend_is_reported(self):
        with sam_env(**{BACKEND_ENV: "nonsense"}):
            self.assertIn("nonsense", sam_health.check(client(ANSWER))["error"])


class DrillTest(unittest.TestCase):
    def test_sam_unavailable_stops_at_the_check_without_a_request(self):
        c = client()
        with sam_env(**{DRILL_ENV: "sam-unavailable"}):
            self.assertEqual(sam_health.check(c)["kind"], "drill")
        self.assertEqual(c.calls, 0)

    def test_the_mid_run_drill_passes_the_check_and_fails_the_judge(self):
        with sam_env(**{DRILL_ENV: "sam-outage-mid-run"}):
            self.assertIsNone(sam_health.check(client(ANSWER)))
            self.assertIsNone(judge_drill("preflight"))
            self.assertIn("sam-outage-mid-run", judge_drill())
            with self.assertRaises(SystemExit) as caught:
                from_trace({"rows": []}, provider="sam", frames_dir="/nonexistent")
        self.assertIn("sam observations unavailable", str(caught.exception))

    def test_a_drill_outside_the_list_is_refused(self):
        with sam_env(**{DRILL_ENV: "everything-down"}), self.assertRaises(SystemExit):
            judge_drill()

    def test_the_workflow_offers_every_drill_and_no_drill_shares_the_cache(self):
        import yaml

        from agents.observations import DRILLS

        doc = yaml.safe_load((REPO / ".github" / "workflows" / "fix-matrix.yml").read_text(encoding="utf-8"))
        options = doc[True]["workflow_dispatch"]["inputs"]["judge_drill"]["options"]
        self.assertEqual(set(options), {"off", *DRILLS})
        self.assertIn("inputs.judge_drill == 'off'", doc["jobs"]["sam-warm"]["if"])
        steps = doc["jobs"]["demo-run"]["steps"]
        restores = [s for s in steps if str(s.get("name", "")).startswith(("Fetch this run's shared", "Restore them"))]
        self.assertEqual(len(restores), 2)
        self.assertTrue(all("inputs.judge_drill == 'off'" in s["if"] for s in restores))
        run = next(s for s in steps if s.get("name") == "One live overnight run")
        self.assertEqual(run["env"]["EXPECTRAIL_JUDGE_DRILL"],
                         "${{ inputs.judge_drill != 'off' && inputs.judge_drill || '' }}")

    def test_a_drill_run_says_so_and_is_never_collected(self):
        from agents.bench_collect import collect_demo
        from agents.demo_loop import annotation

        row = {"run": 2, "decision": "needs-review", "wallClockSeconds": 1, "samImages": 0, "drill": "sam-unavailable"}
        self.assertIn("title=Demo run 2 drill", annotation(row))

        def fetch(path):
            if "annotations" in path:
                return [{"title": "Demo run 2 drill", "message": "sam-unavailable"}]
            if path.endswith("/jobs?per_page=100"):
                return {"jobs": [{"id": 1, "name": "demo-run"}]}
            return {"head_sha": "x"}

        with self.assertRaises(SystemExit) as caught:
            collect_demo(1, fetch)
        self.assertIn("drill", str(caught.exception))


class LadderKindTest(unittest.TestCase):
    def run_ladder(self, error, *answers):
        slept, calls = [], []

        def verify(request, candidate, out, **kwargs):
            calls.append(out.name)
            out.mkdir(parents=True, exist_ok=True)
            answer = answers[len(calls) - 1]
            if answer == "down":
                (out / "observations-coins-visible-error.txt").write_text(error + "\n")
                return {"decision": "needs-review", "checks": [{"result": "needs-review"}]}
            return {"decision": answer, "checks": [{"result": "pass"}]}

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"EXPECTRAIL_GLIMMER_MODEL": "", BACKEND_ENV: "sam"}), \
                mock.patch("agents.judge_ladder.sam_on", lambda: True):
            _, where, record = judge({}, Path("c.patch"), Path(tmp) / "a", verify_fn=verify, sleep=slept.append)
            return record, slept, calls, where.name

    def test_auth_and_credit_skip_the_wait_and_the_second_look(self):
        for kind in ("auth", "credit"):
            with self.subTest(kind=kind):
                record, slept, calls, where = self.run_ladder(
                    f"sam observations unavailable (kind={kind}): sam-3.1 HTTP 402", "down")
                self.assertEqual((slept, calls, where), ([], ["a"], "a"))
                self.assertIn(f"{kind} error", record["steps"][1]["skipped"])
                self.assertTrue(record["stopped"])

    def test_a_rate_limit_keeps_the_wait(self):
        record, slept, calls, _ = self.run_ladder(
            "sam observations unavailable (kind=rate-limit): sam-3.1 HTTP 429", "down", "accept")
        self.assertEqual((len(slept), calls), (1, ["a", "a-retry"]))
        self.assertEqual(record["judgedBy"], "sam (retried)")

    def test_an_unknown_kind_and_an_old_error_keep_the_wait(self):
        for error in ("sam observations unavailable (kind=unknown): odd", "sam observations unavailable: odd"):
            with self.subTest(error=error):
                self.assertEqual(len(self.run_ladder(error, "down", "accept")[1]), 1)

    def test_a_credit_error_outranks_a_passing_one_beside_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "observations-a-error.txt").write_text("sam observations unavailable (kind=server): 503\n")
            (root / "observations-b-error.txt").write_text("sam observations unavailable (kind=credit): 402\n")
            self.assertEqual(outage_kind(root), "credit")


class LoopStopTest(unittest.TestCase):
    def one_run(self, tmp, problem):
        with mock.patch("agents.loop.sam_health.check", return_value=problem), \
                mock.patch("agents.loop.triage", side_effect=AssertionError("triage must not run")) as triage, \
                mock.patch("agents.loop.run_fixer", side_effect=AssertionError("the fixer must not run")) as fixer:
            result = loop.one_run(Path(tmp) / "run", use_muse=True, offline_triage=False, observations=None,
                                  candidate_patch=None, skip_harness=False, run_trust=False)
        return result, triage, fixer

    def test_a_failed_check_stops_before_triage_and_the_fixer(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, triage, fixer = self.one_run(tmp, {"kind": "credit", "error": "sam-3.1 HTTP 402: empty"})
            md = (Path(tmp) / "run" / "morning" / "morning-report.md").read_text()
        triage.assert_not_called()
        fixer.assert_not_called()
        self.assertEqual((result["decision"], result["attemptsConsumed"]), ("needs-review", 0))
        self.assertEqual(result["preflight"]["kind"], "credit")
        self.assertIn("SAM did not answer before the run: credit", md)
        self.assertEqual(result["verificationProvenance"], "none")  # nothing was verified

    def test_the_stopped_run_still_writes_a_valid_summary_and_rollup(self):
        from agents.report import write_loop_rollup

        with tempfile.TemporaryDirectory() as tmp:
            result, _, _ = self.one_run(tmp, {"kind": "credit", "error": "x"})
            summary = {"format": "expectrail.overnight-summary/v0", "mode": {"mode": "live"}, "runs": 1, "accepted": 0,
                       "verificationProvenance": "harness",
                       "cost": {"modelCalls": 0, "costUsd": None, "costProvenance": "unmetered-live-unset"},
                       "timing": {"wallClockMs": 1.0}, "results": [result]}
            validate(json.loads(json.dumps(summary)), "overnight-summary")
            md = write_loop_rollup(Path(tmp), summary=summary).read_text()
        self.assertIn("## Needs-review", md)
        self.assertIn("SAM did not answer before the run: credit", md)

    def test_a_passing_check_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("agents.loop.sam_health.check", return_value=None) as check:
            result = loop.one_run(Path(tmp) / "run", use_muse=False, offline_triage=False,
                                  observations=FIXTURES / "obs-fixed.json", candidate_patch=None, skip_harness=True,
                                  run_trust=False)
        check.assert_called_once()
        self.assertNotIn("preflight", result)

    def test_a_run_on_fixtures_alone_spends_nothing_to_protect_so_it_asks_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch("agents.loop.sam_health.check") as check, \
                mock.patch.dict(os.environ, {"EXPECTRAIL_OBS_PROVIDER": "trace"}):
            result = loop.one_run(Path(tmp) / "run", use_muse=False, offline_triage=True,
                                  observations=FIXTURES / "obs-fixed.json", candidate_patch=None, skip_harness=True,
                                  run_trust=False)
        check.assert_not_called()
        self.assertEqual(result["decision"], "accept")

    def test_the_demo_run_records_the_stop(self):
        from agents.demo_loop import annotation, one

        def loop_main(argv):
            out = Path(argv[1])
            out.mkdir(parents=True)
            (out / "summary.json").write_text(json.dumps({"results": [
                {"decision": "needs-review", "error": "SAM did not answer before the run: credit (x)", "attempts": [],
                 "preflight": {"kind": "credit", "error": "x"}}]}))
            return 1

        with tempfile.TemporaryDirectory() as tmp:
            row = one(1, Path(tmp), loop_main=loop_main)
        self.assertEqual((row["decision"], row["preflight"]["kind"], row["attempts"]), ("needs-review", "credit", []))
        self.assertIn("SAM did not answer before the run", annotation(row))


if __name__ == "__main__":
    unittest.main()
