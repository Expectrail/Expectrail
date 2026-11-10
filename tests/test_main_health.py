"""agents.main_health: a red main is never silent, and runs finishing out of order never mislead it."""
from __future__ import annotations

import unittest

from agents.main_health import BOT, CI_PATH, TITLE, decide, run_check

REPO = "owner/repo"


def _run(run_id: int, conclusion: str | None, created: str, *, event: str = "push", branch: str = "main",
         path: str = CI_PATH, status: str = "completed") -> dict:
    return {"id": run_id, "conclusion": conclusion, "status": status, "created_at": created, "event": event,
            "head_branch": branch, "path": path, "head_sha": f"{run_id:040d}",
            "html_url": f"https://example.test/runs/{run_id}", "head_commit": {"message": f"Merge {run_id}\n\nbody"}}


ISSUE = {"number": 7, "title": f"{TITLE}: CI failed at 0000001", "user": {"login": BOT}}


class FakeApi:
    def __init__(self, run: dict, runs: list[dict], issues: list[dict], *, pulls=None, jobs=None):
        self.run, self.runs, self.issues = run, runs, issues
        self.pulls = pulls if pulls is not None else [{"number": 113, "merged_at": "2026-10-30T20:54:23Z"}]
        self.jobs = jobs if jobs is not None else [
            {"name": "agents-harness-private", "conclusion": "failure", "html_url": "https://example.test/job/1"},
            {"name": "test", "conclusion": "success", "html_url": "https://example.test/job/2"}]
        self.writes: list[tuple[str, str, dict | None]] = []

    def __call__(self, method: str, path: str, body: dict | None = None):
        if method != "GET":
            self.writes.append((method, path, body))
            return {"number": 8} if path == f"/repos/{REPO}/issues" else {}
        if path == f"/repos/{REPO}/actions/runs/{self.run['id']}":
            return self.run
        if path.startswith(f"/repos/{REPO}/actions/workflows/ci.yml/runs"):
            return {"workflow_runs": self.runs}
        if path.startswith(f"/repos/{REPO}/issues?"):
            return self.issues
        if path.endswith("/jobs?per_page=100"):
            return {"jobs": self.jobs}
        if path.endswith("/pulls"):
            return self.pulls
        raise AssertionError(f"unexpected GET {path}")


class DecideTest(unittest.TestCase):
    def test_a_failure_opens_and_a_later_failure_comments(self):
        red = _run(1, "failure", "2026-10-30T19:30:00Z")
        self.assertEqual(decide(red, [red], None), "open")
        self.assertEqual(decide(red, [red], ISSUE), "comment")

    def test_a_pass_closes_an_open_issue_and_is_otherwise_quiet(self):
        green = _run(2, "success", "2026-10-30T20:54:00Z")
        self.assertEqual(decide(green, [green], ISSUE), "close")
        self.assertEqual(decide(green, [green], None), "none")

    def test_timeouts_and_startup_failures_are_red(self):
        for conclusion in ("timed_out", "startup_failure"):
            self.assertEqual(decide(_run(1, conclusion, "t1"), [], None), "open")

    def test_cancelled_or_unfinished_runs_say_nothing(self):
        self.assertEqual(decide(_run(1, "cancelled", "t1"), [], ISSUE), "none")
        self.assertEqual(decide(_run(1, None, "t1", status="in_progress"), [], ISSUE), "none")

    def test_pull_requests_other_branches_and_other_workflows_are_ignored(self):
        self.assertEqual(decide(_run(1, "failure", "t1", event="pull_request"), [], None), "ignore")
        self.assertEqual(decide(_run(1, "failure", "t1", branch="feature"), [], None), "ignore")
        self.assertEqual(decide(_run(1, "failure", "t1", path=".github/workflows/sam-probe.yml"), [], None),
                         "ignore")

    def test_the_schedule_and_dispatches_count(self):
        for event in ("schedule", "workflow_dispatch"):
            self.assertEqual(decide(_run(1, "failure", "t1", event=event), [], None), "open")

    def test_an_older_run_finishing_after_a_newer_one_changes_nothing(self):
        old_red = _run(1, "failure", "2026-10-30T20:54:00Z")
        new_green = _run(2, "success", "2026-10-30T20:57:00Z")
        self.assertEqual(decide(old_red, [new_green, old_red], None), "superseded")
        old_green = _run(3, "success", "2026-10-30T20:50:00Z")
        new_red = _run(4, "failure", "2026-10-30T20:58:00Z")
        self.assertEqual(decide(old_green, [new_red, old_green], ISSUE), "superseded")

    def test_a_newer_run_still_going_or_cancelled_does_not_supersede(self):
        red = _run(1, "failure", "2026-10-30T20:54:00Z")
        going = _run(2, None, "2026-10-30T20:57:00Z", status="in_progress")
        cancelled = _run(3, "cancelled", "2026-10-30T20:58:00Z")
        pr = _run(4, "success", "2026-10-30T20:59:00Z", event="pull_request")
        self.assertEqual(decide(red, [pr, cancelled, going, red], None), "open")


class RunCheckTest(unittest.TestCase):
    def check(self, api: FakeApi, **kw) -> tuple[str, list[str]]:
        lines: list[str] = []
        action = run_check(api, REPO, api.run["id"], "owner", out=lines.append, **kw)
        return action, lines

    def test_opening_assigns_the_owner_names_the_failed_jobs_and_tells_the_merged_pr(self):
        red = _run(41126892471, "failure", "2026-10-30T20:54:26Z")
        api = FakeApi(red, [red], [])
        action, lines = self.check(api)
        self.assertEqual(action, "open")
        (m1, p1, issue), (m2, p2, comment) = api.writes
        self.assertEqual((m1, p1), ("POST", f"/repos/{REPO}/issues"))
        self.assertTrue(issue["title"].startswith(TITLE))
        self.assertEqual(issue["assignees"], ["owner"])
        self.assertIn("[agents-harness-private](https://example.test/job/1)", issue["body"])
        self.assertNotIn("[test]", issue["body"])
        self.assertIn("Commit: Merge 41126892471", issue["body"])
        self.assertEqual((m2, p2), ("POST", f"/repos/{REPO}/issues/113/comments"))
        self.assertIn("#8", comment["body"])
        self.assertTrue(any("opened issue #8" in line for line in lines))

    def test_an_assignee_github_refuses_still_opens_the_issue_unassigned(self):
        # Since the move to the Expectrail org the repository's owner is an organisation, and GitHub
        # answers 422 to assigning an issue to one: main went red on Nov 10 and no issue opened.
        import urllib.error

        class Refuses(FakeApi):
            def __call__(self, method, path, body=None):
                if method == "POST" and path == f"/repos/{REPO}/issues" and body.get("assignees"):
                    self.writes.append((method, path, body))
                    raise urllib.error.HTTPError(path, 422, "Unprocessable Entity", {}, None)
                return super().__call__(method, path, body)

        red = _run(5, "failure", "2026-11-10T20:20:00Z")
        api = Refuses(red, [red], [])
        action, lines = self.check(api)
        self.assertEqual(action, "open")
        issues = [b for m, p, b in api.writes if p == f"/repos/{REPO}/issues"]
        self.assertEqual([("assignees" in b) for b in issues], [True, False])
        self.assertTrue(any("could not assign" in line and "MAIN_HEALTH_ASSIGNEE" in line for line in lines))
        self.assertTrue(any("opened issue #8" in line for line in lines))

    def test_another_error_opening_the_issue_is_not_swallowed(self):
        import urllib.error

        class Fails(FakeApi):
            def __call__(self, method, path, body=None):
                if method == "POST" and path == f"/repos/{REPO}/issues":
                    raise urllib.error.HTTPError(path, 403, "Forbidden", {}, None)
                return super().__call__(method, path, body)

        red = _run(6, "failure", "2026-11-10T20:20:00Z")
        with self.assertRaises(urllib.error.HTTPError):
            self.check(Fails(red, [red], []))

    def test_an_unmerged_pr_for_the_commit_is_not_commented_on(self):
        red = _run(1, "failure", "t1")
        api = FakeApi(red, [red], [], pulls=[{"number": 5, "merged_at": None}])
        self.check(api)
        self.assertEqual([w[1] for w in api.writes], [f"/repos/{REPO}/issues"])

    def test_staying_red_comments_on_the_open_issue(self):
        red = _run(2, "failure", "t2")
        api = FakeApi(red, [red], [ISSUE])
        self.assertEqual(self.check(api)[0], "comment")
        [(method, path, body)] = api.writes
        self.assertEqual((method, path), ("POST", f"/repos/{REPO}/issues/7/comments"))
        self.assertIn("Still red", body["body"])

    def test_going_green_comments_and_closes(self):
        green = _run(3, "success", "t3")
        api = FakeApi(green, [green], [ISSUE])
        self.assertEqual(self.check(api)[0], "close")
        self.assertEqual([(m, p) for m, p, _ in api.writes],
                         [("POST", f"/repos/{REPO}/issues/7/comments"), ("PATCH", f"/repos/{REPO}/issues/7")])
        self.assertEqual(api.writes[1][2]["state"], "closed")

    def test_an_issue_a_person_opened_with_the_same_title_is_never_touched(self):
        green = _run(3, "success", "t3")
        human = dict(ISSUE, user={"login": "seanudeke"})
        pr_item = dict(ISSUE, pull_request={"url": "x"})
        api = FakeApi(green, [green], [human, pr_item])
        self.assertEqual(self.check(api)[0], "none")
        self.assertEqual(api.writes, [])

    def test_a_dry_run_writes_nothing(self):
        red = _run(1, "failure", "t1")
        api = FakeApi(red, [red], [])
        action, lines = self.check(api, dry_run=True)
        self.assertEqual(action, "open")
        self.assertEqual(api.writes, [])
        self.assertIn("(dry run)", lines[0])


if __name__ == "__main__":
    unittest.main()
