""""Run it" (#265, slice 2): the page's contracts, latest.json, the local stub of the edge function,
and the page's own rules.

No live Godot and no live model. The stub runs the stand-in replays of tests/test_two_observers.py
through the real `expectrail.runit run`, the real gate, the real viewer and main's real
`expectrail.runit check`; its HTTP server is the real one, bound to 127.0.0.1.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import re
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from expectrail import runit, runit_site
from tests.test_runit import Case
from tools import runit_stub

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "contracts" / "examples"
PAGE = REPO / "docs" / "run-it" / "index.html"
SCRIPT = REPO / "docs" / "run-it" / "run-it.js"


class ContractTest(unittest.TestCase):
    def test_the_examples_match_their_schemas(self):
        for name in ("run-it-api-status", "run-it-api-refused"):
            with self.subTest(name=name):
                self.assertEqual(runit_site.api_errors(json.loads((EXAMPLES / f"{name}.json").read_text())), [])
        latest = json.loads((EXAMPLES / "run-it-latest.json").read_text())
        self.assertEqual(runit_site.rec.errors(latest, runit_site._schema(runit_site.LATEST_SCHEMA)), [])

    def test_a_body_is_exactly_one_kind(self):
        status = json.loads((EXAMPLES / "run-it-api-status.json").read_text())
        for change in ({"state": "done"}, {"verdict": "accept"}, {"requestId": "../x"}, {"kind": "health"},
                       {"requestId": "abc\n"}):
            with self.subTest(change=change):
                self.assertNotEqual(runit_site.api_errors({**status, **change}), [])
        refused = json.loads((EXAMPLES / "run-it-api-refused.json").read_text())
        for change in ({"reason": "because"}, {"detail": ""}, {"retryAfterSeconds": 0}, {"resetsAt": "tomorrow"}):
            with self.subTest(change=change):
                self.assertNotEqual(runit_site.api_errors({**refused, **change}), [])


class LatestTest(Case):
    def publish(self, sample: str, request_id: str, finished: str | None = None) -> Path:
        out = self.results / request_id
        self.quiet(runit.run, sample, out, request_id=request_id, root=self.root, replay=self.game.replay)
        if finished:
            doc = json.loads((out / "status.json").read_text())
            doc["finishedAt"] = finished
            (out / "status.json").write_text(json.dumps(doc))
        return out

    def setUp(self):
        super().setUp()
        self.results = self.tmp / "results"
        self.results.mkdir()

    def test_a_published_run_becomes_its_samples_latest(self):
        self.publish("fall-through-bug", "r1", "2026-11-20T15:00:00Z")
        index = runit_site.update_latest(self.results, "r1", self.root)
        self.assertEqual(index["samples"], {"fall-through-bug": {"requestId": "r1", "finishedAt": "2026-11-20T15:00:00Z"}})
        self.assertEqual(runit_site.read_latest(self.results), index)
        self.publish("clean", "r2", "2026-11-20T15:10:00Z")
        index = runit_site.update_latest(self.results, "r2", self.root)
        self.assertEqual(set(index["samples"]), {"fall-through-bug", "clean"})
        self.assertNotIn("decision", json.dumps(index))   # an index only: the verdict is the run's status.json

    def test_an_older_run_does_not_replace_a_newer_one(self):
        self.publish("clean", "new", "2026-11-20T15:10:00Z")
        runit_site.update_latest(self.results, "new", self.root)
        self.publish("clean", "old", "2026-11-20T15:00:00Z")
        index = runit_site.update_latest(self.results, "old", self.root)
        self.assertEqual(index["samples"]["clean"]["requestId"], "new")

    def test_a_folder_that_is_not_a_good_run_is_refused_and_nothing_is_written(self):
        out = self.publish("clean", "r1")
        cases = {
            "a bad id": ("../r1", None),
            "no folder": ("missing", None),
            "another request": ("r1", lambda d: d.update(requestId="r9")),
            "a broken status": ("r1", lambda d: d.update(decision="maybe")),
            "an unknown sample": ("r1", lambda d: d["sample"].update(id="not-a-sample")),
        }
        original = (out / "status.json").read_text()
        for name, (request_id, change) in cases.items():
            with self.subTest(name=name):
                doc = json.loads(original)
                if change:
                    change(doc)
                (out / "status.json").write_text(json.dumps(doc))
                with self.assertRaises(runit_site.SiteError):
                    runit_site.update_latest(self.results, request_id, self.root)
                self.assertFalse((self.results / "latest.json").exists())

    def test_a_broken_index_is_refused_not_overwritten(self):
        self.publish("clean", "r1")
        (self.results / "latest.json").write_text('{"format": "expectrail.run-it-latest/v1", "samples": {"clean": 3}}')
        with self.assertRaises(runit_site.SiteError):
            runit_site.update_latest(self.results, "r1", self.root)
        self.assertIn('"clean": 3', (self.results / "latest.json").read_text())

    def test_the_command_line(self):
        self.publish("clean", "r1")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(runit_site.main(["latest", str(self.results), "nope"]), 1)
        self.assertIn("refused", err.getvalue())


class Clock:
    def __init__(self, moment: dt.datetime):
        self.moment = moment

    def __call__(self) -> dt.datetime:
        return self.moment


class LimitsTest(unittest.TestCase):
    def test_per_visitor_daily_cap_and_breaker_each_say_which_and_when(self):
        clock = Clock(dt.datetime(2026, 11, 20, 15, 0, tzinfo=dt.UTC))
        limits = runit_stub.Limits(per_visitor=2, daily_cap=3, breaker=2, clock=clock)
        a, b = limits.visitor("10.0.0.1"), limits.visitor("10.0.0.2")
        self.assertNotIn("10.0.0.1", a)   # never the address itself
        for _ in range(2):
            self.assertIsNone(limits.refuse(a))
            limits.started(a)
        refused = limits.refuse(a)
        self.assertEqual((refused["reason"], refused["resetsAt"]), ("visitor-quota", "2026-11-21T00:00:00Z"))
        self.assertIsNone(limits.refuse(b))
        limits.started(b)
        refused = limits.refuse(b)
        self.assertEqual((refused["reason"], refused["resetsAt"]), ("daily-cap", "2026-11-21T00:00:00Z"))
        clock.moment += dt.timedelta(hours=10)   # the next day
        self.assertIsNone(limits.refuse(a))
        limits.finished(True)
        self.assertIsNone(limits.refuse(a))
        limits.finished(True)
        refused = limits.refuse(a)
        self.assertEqual((refused["reason"], refused["resetsAt"]), ("circuit-open", None))
        for body in (refused,):
            self.assertEqual(runit_site.api_errors(body), [])


class StubTest(Case):
    """The stub's HTTP contract, end to end, with the stand-in replays."""

    def setUp(self):
        super().setUp()
        self.results = self.tmp / "results"
        self.gate = None   # a threading.Event the runner waits on, when a test needs a run held open
        self.fail_next = 0

        def runner(sample, out, request_id):
            if self.gate is not None:
                self.gate.wait(30)
            if self.fail_next:
                self.fail_next -= 1
                raise RuntimeError("the stand-in run failed")
            self.quiet(runit.run, sample, out, request_id=request_id, root=self.root, replay=self.game.replay)

        self.limits = runit_stub.Limits(per_visitor=3, daily_cap=40, breaker=3)
        self.service = runit_stub.Service(self.results, runner, self.root, limits=self.limits, stand_in=True)
        self.logged: list[str] = []
        self.service.log = self.logged.append
        self.server = runit_stub.serve(self.service, 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def call(self, path: str, body: bytes | None = None) -> tuple[int, dict | bytes]:
        request = urllib.request.Request(self.base + path, data=body, method="POST" if body is not None else "GET",
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as r:
                code, data, kind = r.status, r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            code, data, kind = exc.code, exc.read(), exc.headers.get("Content-Type", "")
        if kind.startswith("application/json") and path.startswith("/api/"):
            doc = json.loads(data)
            self.assertEqual(runit_site.api_errors(doc), [], doc)   # every body keeps the contract
            return code, doc
        return code, data

    def start(self, sample: str) -> tuple[int, dict]:
        return self.call("/api/run", json.dumps({"sample": sample}).encode())

    def wait(self, request_id: str) -> dict:
        deadline = time.time() + 60
        while time.time() < deadline:
            _, doc = self.call(f"/api/status/{request_id}")
            if doc["state"] not in runit_stub.ACTIVE:
                return doc
            time.sleep(0.05)
        self.fail("the run did not finish")

    def test_a_run_is_published_checked_and_listed(self):
        code, health = self.call("/api/health")
        self.assertEqual((code, health["open"], health["standIn"]), (200, True, True))
        code, doc = self.start("fall-through-bug")
        self.assertEqual((code, doc["kind"], doc["sample"]), (202, "accepted", "fall-through-bug"))
        self.assertRegex(doc["requestId"], r"^[0-9a-f-]{36}$")   # minted by the service
        final = self.wait(doc["requestId"])
        self.assertEqual((final["state"], final["standIn"]), ("published", True))
        code, status = self.call(f"/results/{doc['requestId']}/status.json")
        status = json.loads(status)
        self.assertEqual((code, status["decision"], status["requestId"]), (200, "reject", doc["requestId"]))
        code, latest = self.call("/results/latest.json")
        self.assertEqual(json.loads(latest)["samples"]["fall-through-bug"]["requestId"], doc["requestId"])
        code, page = self.call(f"/results/{doc['requestId']}/viewer/evidence.html")
        self.assertEqual(code, 200)
        self.assertIn(b"Content-Security-Policy", page)

    def test_one_run_at_a_time(self):
        self.gate = threading.Event()
        code, first = self.start("clean")
        self.assertEqual(code, 202)
        code, doc = self.start("clean")
        self.assertEqual((code, doc["reason"], doc["retryAfterSeconds"]), (409, "busy", 60))
        self.gate.set()
        self.assertEqual(self.wait(first["requestId"])["state"], "published")
        self.assertEqual(self.start("clean")[0], 202)

    def test_bad_requests_are_refused_before_anything_runs(self):
        cases = [b"not json", b'{"sample": 3}', b'{"sample": "clean", "extra": 1}', b"[]",
                 b'{"sample": "../../etc"}', b'{"sample": "not-a-sample"}', b"{" + b" " * 2000 + b"}"]
        for body in cases:
            with self.subTest(body=body[:40]):
                code, doc = self.call("/api/run", body)
                self.assertEqual(code, 400)
                self.assertIn(doc["reason"], ("bad-request", "unknown-sample"))
        self.assertEqual(self.service.runs, {})
        self.assertEqual(self.game.replays, [])
        code, doc = self.call("/api/status/nope")
        self.assertEqual((code, doc["reason"]), (404, "unknown-request"))
        code, doc = self.call("/api/status/..%2F..%2Fx")
        self.assertEqual(code, 404)

    def test_the_quota_says_when_it_resets(self):
        self.limits.per_visitor = 1
        _, doc = self.start("clean")
        self.wait(doc["requestId"])
        code, doc = self.start("clean")
        self.assertEqual((code, doc["reason"]), (429, "visitor-quota"))
        self.assertRegex(doc["resetsAt"], r"T00:00:00Z$")

    def test_failed_runs_publish_nothing_and_open_the_breaker(self):
        self.fail_next = 3
        for _ in range(3):
            code, doc = self.start("clean")
            self.assertEqual(code, 202)
            self.assertEqual(self.wait(doc["requestId"])["state"], "failed")
        self.assertEqual([p.name for p in self.results.iterdir()], [])
        code, doc = self.start("clean")
        self.assertEqual((code, doc["reason"]), (503, "circuit-open"))
        self.assertFalse(self.call("/api/health")[1]["open"])

    def test_a_folder_that_fails_the_check_is_not_published(self):
        def runner(sample, out, request_id):
            self.quiet(runit.run, sample, out, request_id=request_id, root=self.root, replay=self.game.replay)
            (out / "viewer" / "extra.js").write_text("alert(1)")
        self.service.runner = runner
        _, doc = self.start("clean")
        self.assertEqual(self.wait(doc["requestId"])["state"], "failed")
        self.assertFalse((self.results / doc["requestId"]).exists())
        self.assertFalse((self.results / "latest.json").exists())
        self.assertIn("viewer/extra.js", "".join(self.logged))

    def test_switched_off_refuses_and_says_so(self):
        self.service.open = False
        self.assertFalse(self.call("/api/health")[1]["open"])
        code, doc = self.start("clean")
        self.assertEqual((code, doc["reason"]), (503, "disabled"))

    def test_files_are_served_only_from_their_folders(self):
        self.assertEqual(self.call("/run-it/")[0], 200)
        self.assertEqual(self.call("/run-it/run-it.js")[0], 200)
        (self.tmp / "secret.txt").write_text("x")
        for path in ("/results/../secret.txt", "/results/%2e%2e/secret.txt", "/..%2f..%2fsecret.txt",
                     "/run-it/.hidden", "/results/"):
            with self.subTest(path=path):
                self.assertEqual(self.call(path)[0], 404)


class PageTest(unittest.TestCase):
    """The page's rules, read from its source. A browser looked at it too (see the work log)."""

    @classmethod
    def setUpClass(cls):
        cls.page = PAGE.read_text(encoding="utf-8")
        cls.script = SCRIPT.read_text(encoding="utf-8")

    def test_the_page_talks_only_to_itself_the_service_and_the_results_branch(self):
        csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', self.page).group(1)
        connect = next(d for d in csp.split(";") if d.strip().startswith("connect-src")).split()[1:]
        self.assertEqual(connect, ["'self'", "https://api.expectrail.tech", "https://raw.githubusercontent.com"])
        self.assertIn("form-action 'none'", csp)
        self.assertIn("base-uri 'none'", csp)

    def test_the_viewer_frame_is_sandboxed_without_the_pages_origin(self):
        frame = re.search(r'<iframe id="viewer"[^>]*>', self.page).group(0)
        self.assertIn('sandbox="allow-scripts"', frame)
        self.assertNotIn("allow-same-origin", self.page + self.script)

    def test_nothing_is_written_as_html(self):
        for never in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            self.assertNotIn(never, self.script)

    def test_only_an_accept_with_recorded_vision_is_green(self):
        self.assertEqual(self.script.count('tone: "pass"'), 1)
        green = self.script[self.script.index('if (status.decision === "accept")'):self.script.index('tone: "pass"')]
        for needed in ("v.recorded === true", "v.notRecorded === 0", "v.answered > 0", "v.answered === v.asked"):
            self.assertIn(needed, green)

    def test_the_local_service_is_used_only_on_loopback(self):
        self.assertIn('var API = LOCAL ? "/api" : "https://api.expectrail.tech";', self.script)
        self.assertIn('["localhost", "127.0.0.1", "[::1]", "::1"]', self.script)
        self.assertNotIn("location.search", self.script)   # no link can point the page at another service


if __name__ == "__main__":
    unittest.main()
