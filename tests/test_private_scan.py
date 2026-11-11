"""The private scan on a pull request without pull_request_target or workflow_run (#247).

Two halves. `private-scan-request.yml` runs on the pull request with no secret and asks main's
scanner to scan the head commit (one workflow_dispatch call). `private-scan.yml` then runs from the
default branch in the main-only environment, checks the commit out as data, scans it with main's
scanner and posts the result on the commit. These tests hold the shape that design rests on:

- the request half holds no secret, checks nothing out, and can do nothing but start a workflow;
- the trusted half starts only by dispatch, takes the commit as data, and gives the held-out token
  to one step;
- the report says pass only for a clean success, and posts only on a full commit id.

Nothing here reads the private set or calls GitHub. Not covered here: GitHub starting the dispatched
run and the environment letting it in; the pull request that made this change showed both (see its
description), and every pull request since shows them as the check `private-export-scan`.
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

import yaml

from agents import scan_handoff
from agents.scan_handoff import HandoffError, check_run, post_check
from harness.run import REPO

WORKFLOWS = REPO / ".github" / "workflows"
REQUEST = WORKFLOWS / "private-scan-request.yml"
SCAN = WORKFLOWS / "private-scan.yml"
SHA = "0123456789abcdef0123456789abcdef01234567"
PINNED = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}$")


def load(path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return doc, doc.get(True, doc.get("on"))


def expansions_in_scripts(job) -> list[str]:
    return [s["run"] for s in job["steps"] if "run" in s and "${{" in s["run"]]


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Report(unittest.TestCase):
    def setUp(self):
        self.requests = []

    def opener(self, reply: dict):
        def open_(request, timeout=None):
            self.requests.append(request)
            return FakeResponse(json.dumps(reply).encode())
        return open_

    def run_main(self, *argv, opener=None):
        buf = io.StringIO()
        patches = [mock.patch.dict(os.environ, {"GH_TOKEN": "t0ken", "GITHUB_API_URL": "https://api.github.com"})]
        if opener is not None:
            patches.append(mock.patch.object(scan_handoff.urllib.request, "urlopen", opener))
        with redirect_stdout(buf):
            for patch in patches:
                patch.start()
            try:
                code = scan_handoff.main(list(argv))
            finally:
                for patch in reversed(patches):
                    patch.stop()
        return code, buf.getvalue()

    def test_the_check_is_posted_on_the_commit_under_the_scans_name(self):
        post_check("Expectrail/Expectrail", SHA, "success", "https://example.invalid/run/1", "t0ken",
                   opener=self.opener({"id": 1}))
        request = self.requests[0]
        self.assertTrue(request.full_url.endswith("/repos/Expectrail/Expectrail/check-runs"))
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer t0ken")
        self.assertNotIn("t0ken", request.full_url)
        body = json.loads(request.data)
        self.assertEqual((body["name"], body["head_sha"], body["status"], body["conclusion"], body["details_url"]),
                         ("private-export-scan", SHA, "completed", "success", "https://example.invalid/run/1"))

    def test_only_a_clean_success_is_reported_as_a_pass(self):
        self.assertEqual(check_run(SHA, "success", "u")["conclusion"], "success")
        self.assertEqual(check_run(SHA, "cancelled", "u")["conclusion"], "cancelled")
        for status in ("failure", "skipped", "", "Success", "neutral", "anything"):
            with self.subTest(status=status):
                run = check_run(SHA, status, "u")
                self.assertEqual(run["conclusion"], "failure")
                self.assertIn("did not pass", run["output"]["title"])

    def test_the_check_never_carries_what_the_scan_found(self):
        for status in ("success", "failure"):
            text = json.dumps(check_run(SHA, status, "https://example.invalid/run/1"))
            self.assertNotIn("heldout", text.lower())
            self.assertIn("https://example.invalid/run/1", text)

    def test_only_a_full_commit_id_and_a_plain_repository_name_reach_the_url(self):
        for repo, sha in (("Expectrail/Expectrail", "main"), ("Expectrail/Expectrail", SHA[:12]),
                          ("Expectrail/Expectrail", SHA + "/../../x"), ("Expectrail/Expectrail/../x", SHA),
                          ("Expectrail/Expectrail?x=", SHA), ("Expectrail", SHA), ("Expectrail/Expectrail", SHA.upper())):
            with self.subTest(repo=repo, sha=sha), self.assertRaises(HandoffError):
                post_check(repo, sha, "success", "https://example.invalid/run", "t", opener=self.opener({}))
        self.assertEqual(self.requests, [])

    def test_a_commit_gets_a_check(self):
        code, out = self.run_main("report", "--repo", "Expectrail/Expectrail", "--ref", SHA, "--status", "failure",
                                  "--run-url", "https://example.invalid/run/2", opener=self.opener({"id": 2}))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.requests[0].data)["conclusion"], "failure")
        self.assertIn(f"reported failure on {SHA}", out)

    def test_a_branch_name_gets_no_check_and_no_call(self):
        for ref in ("main", "agent/247-private-scan", SHA[:39], SHA + "0", f"{SHA}\n", "refs/pull/1/head"):
            with self.subTest(ref=ref):
                code, out = self.run_main("report", "--repo", "Expectrail/Expectrail", "--ref", ref, "--status",
                                          "success", "--run-url", "https://example.invalid", opener=self.opener({}))
                self.assertEqual(code, 0)
                self.assertIn("no check is posted", out)
        self.assertEqual(self.requests, [])

    def test_a_bad_repository_name_fails_without_a_call(self):
        code, out = self.run_main("report", "--repo", "Expectrail/Expectrail/../x", "--ref", SHA, "--status",
                                  "success", "--run-url", "https://example.invalid", opener=self.opener({}))
        self.assertEqual(code, 1)
        self.assertIn("::error title=Private scan::not a repository name", out)
        self.assertEqual(self.requests, [])

    def test_an_api_failure_is_reported_without_the_response(self):
        def refuse(request, timeout=None):
            raise OSError("a response body that might quote a token: t0ken")
        code, out = self.run_main("report", "--repo", "Expectrail/Expectrail", "--ref", SHA, "--status", "success",
                                  "--run-url", "https://example.invalid", opener=refuse)
        self.assertEqual(code, 1)
        self.assertNotIn("t0ken", out)

    def test_it_needs_only_the_standard_library(self):
        """The workflow runs it with python -I, where the repository is not importable."""
        done = subprocess.run(["python3", "-I", str(REPO / "agents" / "scan_handoff.py"), "report", "--repo", "a/b",
                               "--ref", "main", "--status", "success", "--run-url", "u"],
                              capture_output=True, text=True, cwd=tempfile.gettempdir())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("no check is posted", done.stdout)


class RequestHalf(unittest.TestCase):
    def setUp(self):
        self.text = REQUEST.read_text(encoding="utf-8")
        self.doc, self.on = load(REQUEST)
        self.job = self.doc["jobs"]["private-scan-request"]

    def test_it_runs_on_pull_requests_with_no_secret_and_no_environment(self):
        self.assertEqual(list(self.on), ["pull_request"])
        self.assertNotIn("environment", self.job)
        code = "\n".join(line.split("#", 1)[0] for line in self.text.splitlines())
        self.assertNotIn("secrets.", code)

    def test_its_token_can_start_a_workflow_and_nothing_else(self):
        self.assertEqual(self.doc["permissions"], {"contents": "read"})
        self.assertEqual(self.job["permissions"], {"actions": "write"})

    def test_same_repository_pull_requests_only(self):
        self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", self.job["if"])

    def test_it_checks_nothing_out_and_runs_no_action(self):
        self.assertEqual(len(self.job["steps"]), 1)
        self.assertNotIn("uses", self.job["steps"][0])

    def test_it_starts_the_scan_on_the_default_branch_with_the_head_commit(self):
        step = self.job["steps"][0]
        self.assertEqual(step["env"]["HEAD_SHA"], "${{ github.event.pull_request.head.sha }}")
        self.assertEqual(step["env"]["DEFAULT_BRANCH"], "${{ github.event.repository.default_branch }}")
        self.assertIn('"repos/$REPO/actions/workflows/private-scan.yml/dispatches"', step["run"])
        self.assertIn('-f "ref=$DEFAULT_BRANCH"', step["run"])
        self.assertIn('-f "inputs[ref]=$HEAD_SHA"', step["run"])

    def test_no_event_value_is_pasted_into_a_script(self):
        self.assertEqual(expansions_in_scripts(self.job), [])


class TrustedHalf(unittest.TestCase):
    def setUp(self):
        self.text = SCAN.read_text(encoding="utf-8")
        self.doc, self.on = load(SCAN)
        self.job = self.doc["jobs"]["private-export-scan"]
        self.steps = self.job["steps"]

    def step(self, name):
        return next(s for s in self.steps if s.get("name", "").startswith(name))

    def test_it_starts_only_by_dispatch(self):
        # pull_request would run the pull request's copy with no secret; pull_request_target is blocked
        # from December 2, 2026; workflow_run never started here (startup_failure, November 11, 2026).
        self.assertEqual(list(self.on), ["workflow_dispatch"])
        self.assertEqual(list(self.on["workflow_dispatch"]["inputs"]), ["ref"])
        self.assertEqual(list(self.doc["jobs"]), ["private-export-scan"])

    def test_it_is_in_the_environment_only_main_may_use(self):
        self.assertEqual(self.job["environment"], "main-only")
        self.assertNotIn("if", self.job)   # nothing to get wrong: the environment is the gate

    def test_its_token_can_read_and_post_a_check_and_nothing_else(self):
        self.assertEqual(self.doc["permissions"], {"contents": "read"})
        self.assertEqual(self.job["permissions"], {"contents": "read", "checks": "write"})

    def test_the_held_out_token_reaches_one_step_only(self):
        holders = [s.get("name") for s in self.steps if "secrets.HELDOUT_TOKEN" in json.dumps(s)]
        self.assertEqual(holders, ["Fetch the private held-out set"])
        self.assertEqual(self.job["env"], {"HELDOUT_TOKEN_SET": "${{ secrets.HELDOUT_TOKEN != '' }}"})

    def test_the_commit_is_checked_out_as_data_beside_the_scanner(self):
        checkouts = [s for s in self.steps if str(s.get("uses", "")).startswith("actions/checkout@")]
        self.assertEqual([c.get("with", {}).get("path") for c in checkouts], [None, "scanned", "heldout-set"])
        self.assertNotIn("ref", checkouts[0]["with"])                       # the scanner: this branch
        self.assertEqual(checkouts[1]["with"]["ref"], "${{ inputs.ref }}")   # the commit: into scanned/ only
        for checkout in checkouts:
            self.assertIs(checkout["with"]["persist-credentials"], False)

    def test_the_scan_runs_mains_scanner_on_the_scanned_folder(self):
        run = self.step("Export scan")["run"]
        self.assertEqual(run, "python -m agents.export_scan scanned/bench scanned/docs scanned/README.md "
                              "scanned/apps --private heldout-set")
        # No step runs or installs anything from the scanned commit.
        for step in self.steps:
            text = str(step.get("run", ""))
            self.assertNotRegex(text, r"(pip|python[0-9.]*|bash|sh)\s+[^|]*scanned/(?!bench|docs|README|apps)")
            self.assertNotIn("cd scanned", text)

    def test_no_event_value_is_pasted_into_a_script_and_no_action_is_unpinned(self):
        self.assertEqual(expansions_in_scripts(self.job), [])
        for step in self.steps:
            if "uses" in step:
                self.assertRegex(step["uses"], PINNED)

    def test_the_result_is_posted_on_the_scanned_commit_whatever_happened(self):
        report = self.steps[-1]
        self.assertEqual(report["if"], "always()")
        self.assertEqual(report["env"]["SCANNED_REF"], "${{ inputs.ref }}")
        self.assertEqual(report["env"]["STATUS"], "${{ job.status }}")
        self.assertIn('agents/scan_handoff.py report', report["run"])
        self.assertIn('--ref "$SCANNED_REF" --status "$STATUS"', report["run"])
        self.assertIn("python3 -I", report["run"])
        # A missing token must fail after the scanner is checked out, or there is nothing to report with.
        names = [s.get("name") for s in self.steps]
        self.assertLess(names.index("Check out the scanner (this branch, never the scanned commit's code)"),
                        names.index("Require the held-out token"))

    def test_one_scan_at_a_time_for_a_commit(self):
        self.assertEqual(self.doc["concurrency"], {"group": "private-scan-${{ inputs.ref }}", "cancel-in-progress": True})


class NothingOfTheOldDesignsIsLeft(unittest.TestCase):
    def test_no_workflow_uses_the_triggers_that_failed(self):
        for path in sorted(WORKFLOWS.glob("*.yml")):
            _, on = load(path)
            triggers = [on] if isinstance(on, str) else list(on)
            self.assertNotIn("pull_request_target", triggers, path.name)
        _, on = load(SCAN)
        self.assertNotIn("workflow_run", on)
        self.assertFalse((WORKFLOWS / "private-scan-collect.yml").exists())

    def test_the_audit_config_carries_no_exception_for_the_scan(self):
        config = yaml.safe_load((REPO / ".github" / "obaaf.yml").read_text(encoding="utf-8"))
        self.assertEqual([i for i in config["ignore"] if "private-scan" in i["path"]], [])
        self.assertNotIn("pull_request_target", yaml.safe_dump(config))


if __name__ == "__main__":
    unittest.main()
