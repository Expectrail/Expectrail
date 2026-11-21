"""#254: a lost runner on the latest capture of a pull request's head, with no re-run.

The trusted job opens **Expectrail clearance** in progress when the capture starts and concludes it
after judging. If the runner of the job that judges is lost and nobody re-runs the capture, nothing
else ever concludes that check: it stays in progress (never counted as cleared, but never finished).
``close_lost`` is the sweep for it, run by any later trusted job in the repository: an open clearance
on an open pull request's head is concluded failed once its capture ended longer ago than the trusted
job can run. It never clears anything, and anything it cannot read it leaves as it is.
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tests.test_ci_gate import HEAD, ctx
from tools import ci_checks as c

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
LOST_SHA, FRESH_SHA, OTHER_SHA, UNREAD_SHA = "a" * 40, "b" * 40, "c" * 40, "d" * 40
RUN = {"id": 123, "run_attempt": 2, "workflow_id": 99, "conclusion": "success"}


def stamp(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def attempt(sha, *, hours_ago=8.0, status="completed", path=c.CALLER, event="pull_request"):
    return {"id": 1, "status": status, "conclusion": "success", "head_sha": sha, "path": path,
            "event": event, "updated_at": stamp(hours_ago)}


class LostLatestCapture(unittest.TestCase):
    def setUp(self):
        self.writes = []

    def api(self, *, pulls=None, checks=None, attempts=None, refuse=(), seen=None):
        pub, other = {"slug": "publisher"}, {"slug": "someone"}
        default_checks = {
            # The latest capture of an open pull request's head ended 8 hours ago; its judge was lost.
            LOST_SHA: [{"id": 11, "name": c.CLEARANCE, "external_id": "expectrail/40/1", "status": "in_progress",
                        "app": pub, "head_sha": LOST_SHA},
                       {"id": 12, "name": c.CLEARANCE, "external_id": "expectrail/39/1", "status": "completed",
                        "app": pub, "head_sha": LOST_SHA},
                       {"id": 13, "name": c.CLEARANCE, "external_id": "expectrail/38/1", "status": "in_progress",
                        "app": other, "head_sha": LOST_SHA},
                       {"id": 14, "name": c.CLEARANCE, "external_id": "not-ours", "status": "in_progress",
                        "app": pub, "head_sha": LOST_SHA}],
            # A capture that ended an hour ago: its trusted job may still be judging.
            FRESH_SHA: [{"id": 21, "name": c.CLEARANCE, "external_id": "expectrail/50/1", "status": "in_progress",
                         "app": pub, "head_sha": FRESH_SHA}],
            # A capture still running: its clearance is meant to be open.
            OTHER_SHA: [{"id": 31, "name": c.CLEARANCE, "external_id": "expectrail/60/1", "status": "in_progress",
                         "app": pub, "head_sha": OTHER_SHA}],
            # A capture whose run cannot be read: nothing is decided about it.
            UNREAD_SHA: [{"id": 41, "name": c.CLEARANCE, "external_id": "expectrail/70/1", "status": "in_progress",
                          "app": pub, "head_sha": UNREAD_SHA}],
            # This trusted job's own capture.
            HEAD: [{"id": 51, "name": c.CLEARANCE, "external_id": "expectrail/123/2", "status": "in_progress",
                    "app": pub, "head_sha": HEAD}]}
        default_attempts = {"/40/attempts/1": attempt(LOST_SHA), "/50/attempts/1": attempt(FRESH_SHA, hours_ago=1),
                            "/60/attempts/1": attempt(OTHER_SHA, status="in_progress", hours_ago=9),
                            "/123/attempts/2": attempt(HEAD, hours_ago=30)}
        checks = default_checks if checks is None else checks
        attempts = default_attempts if attempts is None else attempts
        pulls = ([{"number": n, "head": {"sha": s}} for n, s in
                  ((1, LOST_SHA), (2, FRESH_SHA), (3, OTHER_SHA), (4, UNREAD_SHA), (7, HEAD))]
                 if pulls is None else pulls)

        def call(method, path, body=None):
            if seen is not None:
                seen.append((method, path))
            if method == "PATCH":
                if path.rsplit("/", 1)[1] in refuse:
                    raise urllib.error.HTTPError(path, 403, "refused", {}, None)
                self.writes.append((path, body))
                return {}
            if method != "GET":
                self.fail(f"unexpected {method} {path}")
            if "/pulls?" in path:
                return pulls(path) if callable(pulls) else pulls
            if "check-runs?" in path:
                sha = path.split("/commits/")[1].split("/")[0]
                name = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)["check_name"][0]
                return {"check_runs": [x for x in checks.get(sha, []) if x["name"] == name]}
            if "/actions/runs/" in path:
                for tail, doc in attempts.items():
                    if path.endswith(tail):
                        return doc
                raise urllib.error.HTTPError(path, 404, "Not Found", {}, None)
            self.fail(path)
        return call

    def patched(self):
        return {path.rsplit("/", 1)[1]: body for path, body in self.writes}

    def test_a_lost_latest_capture_is_concluded_failed_never_cleared(self):
        api = self.api()
        concluded, refused = c.close_lost(api, api, ctx(), RUN, "publisher", NOW)
        self.assertEqual((concluded, refused), ([11], []))
        body = self.patched()["11"]
        self.assertEqual((body["status"], body["conclusion"]), ("completed", "failure"))
        self.assertIn("is not cleared", body["output"]["summary"])
        self.assertIn("re-run the Expectrail verify workflow", body["output"]["summary"])
        self.assertIn("8 hours", body["output"]["summary"])
        self.assertEqual(body["output"]["title"], c.CLEARANCE)

    def test_nothing_is_ever_concluded_as_success(self):
        api = self.api()
        c.close_lost(api, api, ctx(), RUN, "publisher", NOW)
        self.assertTrue(self.writes)
        self.assertTrue(all(body["conclusion"] == "failure" for _, body in self.writes))

    def test_a_capture_that_ended_recently_or_still_runs_is_left_open(self):
        api = self.api()
        c.close_lost(api, api, ctx(), RUN, "publisher", NOW)
        self.assertNotIn("21", self.patched())   # ended an hour ago: its judge may still run
        self.assertNotIn("31", self.patched())   # the capture is still running

    def test_the_limit_is_longer_than_the_trusted_job_can_run(self):
        workflow = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "expectrail-comment.yml")
        minutes = [int(line.split(":")[1]) for line in workflow.read_text().splitlines()
                   if line.strip().startswith("timeout-minutes:")]
        self.assertTrue(minutes, "the trusted job has no timeout, so no capture can be called lost")
        self.assertGreaterEqual(c.LOST_AFTER_S, 4 * 60 * max(minutes))
        for hours, lost in ((c.LOST_AFTER_S / 3600 - 0.01, False), (c.LOST_AFTER_S / 3600 + 0.01, True)):
            with self.subTest(hours=hours):
                self.writes.clear()
                api = self.api(attempts={"/40/attempts/1": attempt(LOST_SHA, hours_ago=hours)})
                c.close_lost(api, api, ctx(), RUN, "publisher", NOW)
                self.assertEqual("11" in self.patched(), lost)

    def test_another_apps_check_a_completed_one_and_an_unknown_key_are_left_alone(self):
        api = self.api()
        c.close_lost(api, api, ctx(), RUN, "publisher", NOW)
        for cid in ("12", "13", "14"):
            self.assertNotIn(cid, self.patched())

    def test_this_trusted_jobs_own_capture_is_never_touched(self):
        seen = []
        api = self.api(seen=seen)
        c.close_lost(api, api, ctx(), RUN, "publisher", NOW)
        self.assertNotIn("51", self.patched())
        self.assertNotIn(("GET", "/repos/owner/game/actions/runs/123/attempts/2"), seen)

    def test_a_run_that_does_not_match_its_check_decides_nothing(self):
        bad = {"another head": attempt(OTHER_SHA), "another workflow": attempt(LOST_SHA, path=".github/workflows/x.yml"),
               "another event": attempt(LOST_SHA, event="push"), "no time": dict(attempt(LOST_SHA), updated_at=None),
               "unreadable time": dict(attempt(LOST_SHA), updated_at="yesterday"),
               "not a run": ["completed"], "a time to come": attempt(LOST_SHA, hours_ago=-30)}
        for case, doc in bad.items():
            with self.subTest(case=case):
                self.writes.clear()
                api = self.api(attempts={"/40/attempts/1": doc})
                concluded, _ = c.close_lost(api, api, ctx(), RUN, "publisher", NOW)
                self.assertEqual((concluded, self.writes), ([], []))

    def test_an_unreadable_run_leaves_its_check_and_the_rest_are_still_swept(self):
        api = self.api()  # run 70's attempt is a 404
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            concluded, _ = c.close_lost(api, api, ctx(), RUN, "publisher", NOW)
        self.assertEqual(concluded, [11])
        self.assertNotIn("41", self.patched())
        self.assertIn("::warning::", out.getvalue())

    def test_an_unreadable_list_of_pull_requests_sweeps_nothing(self):
        for case, pulls in {"not a list": {"message": "rate limited"},
                            "a head that is not a commit": [{"number": 1, "head": {"sha": "abc"}}],
                            "no head": [{"number": 1}]}.items():
            with self.subTest(case=case):
                self.writes.clear()
                api = self.api(pulls=pulls)
                if case == "not a list":
                    with self.assertRaisesRegex(ValueError, "cannot tell"):
                        c.close_lost(api, api, ctx(), RUN, "publisher", NOW)
                else:
                    self.assertEqual(c.close_lost(api, api, ctx(), RUN, "publisher", NOW), ([], []))
                self.assertEqual(self.writes, [])

    def test_unreadable_check_runs_for_one_head_skip_that_head_only(self):
        api = self.api()

        def broken(method, path, body=None):
            if f"/commits/{FRESH_SHA}/check-runs" in path:
                return {"message": "Not Found"}
            return api(method, path, body)
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            concluded, _ = c.close_lost(broken, broken, ctx(), RUN, "publisher", NOW)
        self.assertEqual(concluded, [11])

    def test_only_the_most_recently_updated_open_pull_requests_are_read(self):
        seen = []
        api = self.api(seen=seen)
        c.close_lost(api, api, ctx(), RUN, "publisher", NOW, pulls=2)
        listing = [p for m, p in seen if "/pulls?" in p]
        self.assertEqual(len(listing), 1)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(listing[0]).query)
        self.assertEqual((query["state"], query["sort"], query["direction"], query["per_page"]),
                         (["open"], ["updated"], ["desc"], ["2"]))
        read = {p.split("/commits/")[1].split("/")[0] for m, p in seen if "check-runs?" in p}
        self.assertEqual(read, {LOST_SHA, FRESH_SHA})

    def test_a_refused_update_is_returned_and_not_counted(self):
        api = self.api(refuse={"11"})
        self.assertEqual(c.close_lost(api, api, ctx(), RUN, "publisher", NOW), ([], [11]))

    def test_a_later_judgment_still_replaces_the_conclusion(self):
        # The sweep concludes a check by id; the late trusted job finds the same check by its key
        # (``start`` reads every status) and concludes it again with its own result.
        api = self.api()
        c.close_lost(api, api, ctx(), RUN, "publisher", NOW)
        swept = {"check_runs": [{"id": 11, "external_id": "expectrail/40/1", "app": {"slug": "publisher"},
                                 "status": "completed", "conclusion": "failure"}]}
        later = mock.Mock(side_effect=lambda method, path, body=None: swept if method == "GET" else {"id": 99})
        late_ctx = ctx(RUN_ID="40", HEAD_SHA=LOST_SHA)
        ids = c.start(later, late_ctx, {"run_attempt": 1}, "https://example.invalid/run", "publisher")
        self.assertEqual(ids[c.CLEARANCE], 11)


class StartRunsTheSweep(unittest.TestCase):
    """The trusted job's start step runs the sweep as housekeeping: a failure only warns."""

    def event(self, tmp):
        event = {"action": "in_progress", "repository": {"default_branch": "main", "full_name": "owner/game"},
                 "workflow_run": {"id": 123, "run_attempt": 2, "workflow_id": 99, "event": "pull_request",
                                  "head_sha": HEAD, "head_branch": "fix/floor", "conclusion": None,
                                  "path": c.CALLER, "head_repository": {"full_name": "owner/game",
                                                                        "owner": {"login": "owner"}},
                                  "repository": {"full_name": "owner/game"}}}
        path = Path(tmp) / "event.json"
        path.write_text(json.dumps(event))
        return {"GITHUB_EVENT_PATH": str(path), "GITHUB_RUN_ID": "900", "RUNNER_TEMP": tmp,
                "GITHUB_OUTPUT": str(Path(tmp) / "out"), "GH_TOKEN": "t", "CHECKS_TOKEN": "t",
                "CHECKS_APP": "publisher"}

    def test_start_calls_the_sweep_and_survives_its_failure(self):
        calls = []

        def sweep(*args, **kwargs):
            calls.append(args)
            raise RuntimeError("anything at all")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, self.event(tmp)), \
                mock.patch.object(c, "latest", return_value=True), \
                mock.patch("expectrail.gate.comment.find_pull_request",
                           return_value={"number": 7, "head": {"sha": HEAD}}), \
                mock.patch.object(c, "start", return_value={c.CLEARANCE: 1, c.EVIDENCE: 2}), \
                mock.patch.object(c, "close_superseded", return_value=[]), \
                mock.patch.object(c, "close_earlier_heads", return_value=[]), \
                mock.patch.object(c, "close_lost", side_effect=sweep), \
                mock.patch("expectrail.gate.comment.http_api", return_value=lambda *a, **k: {}), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            c.main("start")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][4], "publisher")
        self.assertIsInstance(calls[0][5], datetime)
        self.assertIn("::warning::Could not sweep lost captures (RuntimeError", out.getvalue())


if __name__ == "__main__":
    unittest.main()
