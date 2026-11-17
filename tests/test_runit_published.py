"""The nightly check of the deployed Run it service (#265): following a run to what the page shows.

No network, no GitHub, no model. The published files are made offline by the real ``runit.run`` on
the stand-in replays of tests/test_two_observers.py, with recordings made from the scripted stand-in
model (as in tests/test_runit.py), and served from a dict or a loopback HTTP server.
"""
from __future__ import annotations

import contextlib
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from expectrail import runit_site
from tests.test_runit import Case
from tools import runit_api_smoke as smoke
from tools import runit_published as published

REPO = Path(__file__).resolve().parent.parent
NIGHTLY = REPO / ".github" / "workflows" / "run-it-nightly.yml"
BASE = "https://results.invalid"


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += max(s, 0.5)


class Published(Case):
    """Two published runs, made offline: clean (accept) and fall-through-bug (reject)."""

    def setUp(self):
        super().setUp()
        schema = self.root / runit_site.LATEST_SCHEMA
        schema.write_bytes((REPO / runit_site.LATEST_SCHEMA).read_bytes())
        self.files: dict[str, bytes] = {}
        self.finished = {}
        for sample, rid in (("clean", "nightly-clean"), ("fall-through-bug", "nightly-bug")):
            self.record(sample)
            doc, out = self.run_sample(sample, request_id=rid)
            self.finished[rid] = doc["finishedAt"]
            for path in out.rglob("*"):
                if path.is_file():
                    self.files[f"{rid}/{path.relative_to(out).as_posix()}"] = path.read_bytes()
        self.latest = {"format": "expectrail.run-it-latest/v1", "samples": {
            "clean": {"requestId": "nightly-clean", "finishedAt": self.finished["nightly-clean"]},
            "fall-through-bug": {"requestId": "nightly-bug", "finishedAt": self.finished["nightly-bug"]}}}
        self.files["latest.json"] = json.dumps(self.latest).encode()
        self.lines: list[str] = []
        self.clock = Clock()
        self.gets: list[str] = []

    def get(self, url, cap):
        self.gets.append(url)
        self.assertTrue(url.startswith(BASE + "/"))
        rel = url[len(BASE) + 1:]
        if rel not in self.files:
            raise published.Missing(url)
        data = self.files[rel]
        if len(data) > cap:
            raise ValueError("larger than its cap")
        return data

    def status(self, rid):
        return json.loads(self.files[f"{rid}/status.json"])

    def put(self, rel, doc):
        self.files[rel] = json.dumps(doc).encode() if not isinstance(doc, bytes) else doc

    def follow(self, rid="nightly-clean", sample="clean", wait=60, **kw):
        return published.follow(rid, sample, results=BASE, wait=wait, poll=5, get=kw.pop("get", self.get),
                                clock=self.clock, sleep=self.clock.sleep, emit=self.lines.append,
                                root=self.root, **kw)

    def fails_at(self, stage):
        fails = [l for l in self.lines if l.startswith("FAIL")]
        self.assertEqual(len(fails), 1, self.lines)
        self.assertTrue(fails[0].startswith(f"FAIL {stage}:"), fails[0])
        return fails[0]


class FollowTest(Published):
    def test_an_accept_and_a_reject_as_expected_pass_every_line(self):
        self.assertEqual(self.follow(), 0, self.lines)
        self.assertEqual([l.split(":")[0] for l in self.lines],
                         ["PASS published result", "PASS findings", "PASS evidence", "PASS latest"])
        self.assertIn("accept, as clean is expected to decide", self.lines[0])
        self.assertIn("not signed yet", self.lines[0])
        self.lines.clear()
        self.assertEqual(self.follow("nightly-bug", "fall-through-bug"), 0, self.lines)
        self.assertIn("reject, as fall-through-bug is expected to decide", self.lines[0])

    def test_a_decision_other_than_the_expected_one_fails(self):
        doc = self.status("nightly-bug")
        doc["decision"] = "needs-review"
        self.put("nightly-bug/status.json", doc)
        self.assertEqual(self.follow("nightly-bug", "fall-through-bug"), 1)
        self.assertIn("expected to decide reject", self.fails_at("published result"))

    def test_an_accept_without_recorded_vision_answers_fails(self):
        doc = self.status("nightly-clean")
        doc["vision"].update(recorded=False, recordedAt=None, run=None, answered=0, asked=0, why="none")
        self.put("nightly-clean/status.json", doc)
        self.assertEqual(self.follow(), 1)
        self.assertIn("an accept without recorded vision answers behind it", self.fails_at("published result"))

    def test_a_frame_with_no_recorded_answer_fails_even_on_the_expected_decision(self):
        doc = self.status("nightly-bug")
        doc["vision"]["notRecorded"] = 1
        doc["vision"]["answered"] -= 1
        self.put("nightly-bug/status.json", doc)
        self.assertEqual(self.follow("nightly-bug", "fall-through-bug"), 1)
        self.assertIn("with no recorded answer", self.fails_at("published result"))
        # A reject is the expected decision even without a recording, but every sample has one, so a
        # run that used none did not take the visitor's path.
        doc["vision"].update(recorded=False, recordedAt=None, run=None, answered=0, asked=0, notRecorded=0)
        doc["asExpected"] = False
        self.put("nightly-bug/status.json", doc)
        self.lines.clear()
        self.assertEqual(self.follow("nightly-bug", "fall-through-bug"), 1)
        self.assertIn("no recorded vision answers were used", self.fails_at("published result"))

    def test_as_expected_that_disagrees_with_the_decision_fails(self):
        doc = self.status("nightly-clean")
        doc["asExpected"] = False
        self.put("nightly-clean/status.json", doc)
        self.assertEqual(self.follow(), 1)
        self.assertIn("asExpected", self.fails_at("published result"))

    def test_another_request_another_sample_or_no_completion_fails(self):
        for change, words in ((lambda d: d.update(requestId="someone-else"), "another request"),
                              (lambda d: d["sample"].update(id="fall-through-repair"), "another sample"),
                              (lambda d: d.update(phase="failed", decision=None, asExpected=False), "ended failed")):
            with self.subTest(words=words):
                doc = self.status("nightly-clean")
                change(doc)
                self.put("nightly-clean/status.json", doc)
                self.lines.clear()
                self.assertEqual(self.follow(), 1)
                self.assertIn(words, self.fails_at("published result"))

    def test_a_status_that_breaks_its_schema_or_strict_json_fails(self):
        signed = self.status("nightly-clean")
        signed["receipt"] = {"signed": True, "why": "signed"}
        raw = self.files["nightly-clean/status.json"].decode()
        for name, body in (("signed receipt", json.dumps(signed).encode()),
                           ("duplicate key", ('{"format": "x", ' + raw[1:]).encode()),
                           ("NaN", raw.replace('"asked": ', '"asked": NaN, "x": ', 1).encode()),
                           ("not JSON", b"<html>"),
                           ("a list", b"[]")):
            with self.subTest(name=name):
                self.put("nightly-clean/status.json", body)
                self.lines.clear()
                self.assertEqual(self.follow(), 1)
                self.fails_at("published result")

    def test_a_result_published_late_is_waited_for_and_one_never_published_fails(self):
        body = self.files.pop("nightly-clean/status.json")
        calls = []

        def late(url, cap):
            calls.append(url)
            if url.endswith("status.json") and len(calls) == 3:
                self.files["nightly-clean/status.json"] = body
            return self.get(url, cap)

        self.assertEqual(self.follow(get=late), 0, self.lines)
        self.assertGreaterEqual(self.clock.t, 10)
        self.files.pop("nightly-clean/status.json")
        self.lines.clear()
        self.assertEqual(self.follow(wait=30), 1)
        self.assertIn("not published after 30 seconds", self.fails_at("published result"))

    def test_findings_that_disagree_or_are_missing_fail(self):
        record = json.loads(self.files["nightly-clean/findings.json"])
        record["decision"] = "reject"
        self.put("nightly-clean/findings.json", record)
        self.assertEqual(self.follow(), 1)
        self.fails_at("findings")
        del self.files["nightly-clean/findings.json"]
        self.lines.clear()
        self.assertEqual(self.follow(wait=20), 1)
        self.fails_at("findings")
        doc = self.status("nightly-clean")
        doc["findings"] = None
        self.put("nightly-clean/status.json", doc)
        self.lines.clear()
        self.assertEqual(self.follow(), 1)
        self.assertIn("an accept with no findings record", self.fails_at("findings"))

    def test_an_evidence_page_without_the_viewers_policy_or_missing_fails(self):
        self.put("nightly-clean/viewer/evidence.html", b"<!doctype html><p>Accepted</p>")
        self.assertEqual(self.follow(), 1)
        self.assertIn("Content-Security-Policy", self.fails_at("evidence"))
        del self.files["nightly-clean/viewer/evidence.html"]
        self.lines.clear()
        self.assertEqual(self.follow(wait=20), 1)
        self.fails_at("evidence")

    def test_latest_must_name_this_run_or_a_later_one(self):
        self.latest["samples"]["clean"] = {"requestId": "older", "finishedAt": "2026-01-01T00:00:00Z"}
        self.put("latest.json", self.latest)
        self.assertEqual(self.follow(wait=30), 1)
        self.assertIn("the card would show an earlier run", self.fails_at("latest"))
        self.latest["samples"]["clean"] = {"requestId": "newer", "finishedAt": "2999-01-01T00:00:00Z"}
        self.put("latest.json", self.latest)
        self.lines.clear()
        self.assertEqual(self.follow(), 0, self.lines)
        self.assertIn("a later run", self.lines[-1])
        self.put("latest.json", {"format": "expectrail.run-it-latest/v1", "samples": {}, "verdict": "accept"})
        self.lines.clear()
        self.assertEqual(self.follow(), 1)
        self.assertIn("schema", self.fails_at("latest"))

    def test_an_index_that_catches_up_is_waited_for(self):
        stale = dict(self.latest, samples={})
        fresh = self.files["latest.json"]
        self.put("latest.json", stale)
        reads = []

        def catching_up(url, cap):
            if url.endswith("latest.json"):
                reads.append(url)
                if len(reads) == 3:
                    self.files["latest.json"] = fresh
            return self.get(url, cap)

        self.assertEqual(self.follow(get=catching_up), 0, self.lines)
        self.assertEqual(len(reads), 3)

    def test_a_file_over_its_cap_and_bad_ids_fail_without_reading(self):
        self.put("nightly-clean/status.json", b" " * (published.CAPS["status.json"] + 1))
        self.assertEqual(self.follow(), 1)
        self.fails_at("published result")
        for rid, sample in (("../x", "clean"), ("nightly-clean", "Clean"), ("nightly-clean", "not-a-sample")):
            with self.subTest(rid=rid, sample=sample):
                self.lines.clear()
                self.gets.clear()
                self.assertEqual(self.follow(rid, sample), 1)
                self.assertEqual(self.gets, [])

    def test_only_https_or_loopback_results(self):
        for bad in ("http://example.com/r", "https://u:p@example.com/r", "https://example.com/r?x=1", "file:///tmp"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                published.results_base(bad)
        self.assertEqual(published.results_base("http://127.0.0.1:9/r/"), "http://127.0.0.1:9/r")


class SmokeFollowTest(Published):
    """The deployed smoke hands a reserved run to follow() only once the service says published."""

    def send_with(self, states):
        states = list(states)
        sent = []

        def send(url, method="GET", body=None, origin=smoke.ORIGIN, timeout=10):
            sent.append((method, url, body))
            h = {"Access-Control-Allow-Origin": smoke.ORIGIN} if origin == smoke.ORIGIN else {}
            if url.endswith("/health"):
                return 200, h, {"format": smoke.FORMAT, "kind": "health", "open": True, "standIn": False}
            if url.endswith("/run"):
                if origin != smoke.ORIGIN:
                    return 403, {}, {"format": smoke.FORMAT, "kind": "refused", "reason": "bad-request"}
                return 202, h, {"format": smoke.FORMAT, "kind": "accepted", "sample": body["sample"],
                                "requestId": "nightly-clean"}
            state = states.pop(0) if len(states) > 1 else states[0]
            return 200, h, {"format": smoke.FORMAT, "kind": "status", "requestId": "nightly-clean",
                            "sample": "clean", "state": state, "standIn": False}
        return send, sent

    def smoke(self, states, follow, wait=100):
        send, sent = self.send_with(states)
        code = smoke.smoke("https://api.invalid", expect_open="true", sample="clean", wait=wait, poll=5,
                           follow=follow, send=send, clock=self.clock, sleep=self.clock.sleep,
                           emit=self.lines.append)
        return code, sent

    def test_follow_runs_once_published_and_its_result_is_the_smokes(self):
        followed = []

        def follow(rid, sample):
            followed.append((rid, sample))
            return self.follow(rid, sample)

        code, sent = self.smoke(["queued", "running", "publishing", "published"], follow)
        self.assertEqual(code, 0, self.lines)
        self.assertEqual(followed, [("nightly-clean", "clean")])
        self.assertIn("PASS progress: nightly-clean: published", self.lines)
        self.assertEqual(len([s for s in sent if s[0] == "POST" and s[2]["sample"] == "clean"]), 1)
        self.assertEqual(self.lines[-1].split(":")[0], "PASS latest")

        code, _ = self.smoke(["published"], lambda rid, sample: 1)
        self.assertEqual(code, 1)

    def test_a_failed_run_or_one_never_published_is_not_followed(self):
        for states, words in ((["running", "failed"], "run reports failed"),
                              (["running"], "still running after 100 seconds")):
            with self.subTest(states=states):
                self.lines.clear()
                code, sent = self.smoke(states, lambda rid, sample: self.fail("followed"))
                self.assertEqual(code, 1)
                self.assertIn(words, self.lines[-1])
                self.assertEqual(len([s for s in sent if s[0] == "POST" and s[2]["sample"] == "clean"]), 1)

    def test_without_follow_running_still_passes_as_before(self):
        code, _ = self.smoke(["running"], None)
        self.assertEqual(code, 0)
        self.assertIn("this is not a verdict check", self.lines[-1])


class HttpTest(Published):
    """The real fetch() over loopback: its User-Agent, no redirects, 404 as not there yet."""

    @contextlib.contextmanager
    def serve(self, redirect=()):
        files, seen = self.files, []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(dict(self.headers))
                rel = self.path.lstrip("/").removeprefix("r/")
                if rel in redirect:
                    self.send_response(302)
                    self.send_header("Location", "/r/latest.json")
                    self.end_headers()
                    return
                data = files.get(rel)
                self.send_response(200 if data is not None else 404)
                body = data if data is not None else b"404: Not Found"
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/r", seen
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_a_published_run_read_over_http(self):
        with self.serve() as (base, seen):
            code = published.follow("nightly-clean", "clean", results=base, wait=5, poll=1, emit=self.lines.append,
                                    root=self.root, sleep=lambda s: None)
        self.assertEqual(code, 0, self.lines)
        self.assertTrue(seen)
        for headers in seen:
            self.assertEqual(headers.get("User-Agent"), published.USER_AGENT)
            self.assertNotIn("Authorization", headers)
            self.assertNotIn("Cookie", headers)

    def test_a_redirect_is_not_followed_and_404_is_missing(self):
        with self.serve(redirect={"nightly-clean/status.json"}) as (base, _):
            with self.assertRaises(ValueError):
                published.fetch(base + "/nightly-clean/status.json", 1000)
            with self.assertRaises(published.Missing):
                published.fetch(base + "/nope.json", 1000)
            with self.assertRaises(ValueError):
                published.fetch(base + "/latest.json", 3)


class NightlyWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = NIGHTLY.read_text(encoding="utf-8")
        cls.wf = yaml.safe_load(cls.text)

    def test_it_runs_on_a_schedule_and_by_hand_only(self):
        on = self.wf[True]   # YAML reads the key `on` as true
        self.assertEqual(set(on), {"schedule", "workflow_dispatch"})
        self.assertNotIn("pull_request_target", self.text)

    def test_it_holds_no_secret_no_environment_and_reads_only(self):
        self.assertEqual(self.wf["permissions"], {"contents": "read"})
        for name, job in self.wf["jobs"].items():
            self.assertEqual(job.get("permissions"), {"contents": "read"}, name)
            self.assertNotIn("environment", job, name)
        self.assertNotIn("secrets.", self.text)
        self.assertNotIn("id-token", self.text)
        self.assertNotIn("github.token", self.text)
        steps = self.wf["jobs"]["deployed"]["steps"]
        self.assertEqual(steps[0]["with"]["persist-credentials"], False)

    def test_it_checks_the_deployed_service_and_follows_when_open(self):
        run = next(s["run"] for s in self.wf["jobs"]["deployed"]["steps"] if "run" in s)
        self.assertIn("python3 -m tools.runit_api_smoke https://api.expectrail.tech", run)
        self.assertIn("--follow", run)
        self.assertIn('--expect-open "${EXPECT_OPEN:-false}"', run)
        self.assertIn("set -o pipefail", run)
        env = next(s["env"] for s in self.wf["jobs"]["deployed"]["steps"] if "run" in s)
        self.assertEqual(env["EXPECT_OPEN"], "${{ vars.RUN_IT_EXPECT_OPEN }}")
        # Every sample the nightly may start is one the deployed smoke knows and that has a recording.
        options = self.wf[True]["workflow_dispatch"]["inputs"]["sample"]["options"]
        self.assertEqual([o for o in options if o], list(smoke.SAMPLES))
        for sample in smoke.SAMPLES:
            self.assertIn(sample, run)
            self.assertTrue((REPO / "docs" / "run-it" / "vision" / f"{sample}.json").is_file(), sample)

    def test_it_runs_every_day_and_the_merge_guard_can_read_it(self):
        from tools import merge_guard
        self.assertEqual(self.wf[True]["schedule"], [{"cron": "17 9 * * 0-6"}])
        # A quoted cron ending in `*` ("... * *") counts as a YAML alias to the guard, which then
        # leaves the pull request for a person (#586). 0-6 is every day without one.
        self.assertEqual(merge_guard.aliases(self.text), 0)
        self.assertEqual(merge_guard.unread_added(None, self.text), {"escape": 0, "alias": 0, "anchor": 0})

    def test_every_action_is_pinned_to_a_commit(self):
        for step in self.wf["jobs"]["deployed"]["steps"]:
            if "uses" in step:
                self.assertRegex(step["uses"], r"^[\w-]+/[\w-]+@[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
