"""The macOS suite job (#378): its summary says only what the log shows, and the workflow stays report-only."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from tools import macos_suite_summary as summary
from tools import merge_guard

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "macos.yml"

PASSED = """\
test_a (tests.test_x.A.test_a) ... ok
----------------------------------------------------------------------
Ran 2843 tests in 401.512s

OK (skipped=48)
"""

FAILED = """\
======================================================================
FAIL: test_cancel (tests.test_orchestrator.CancelOrderTest.test_cancel)
----------------------------------------------------------------------
AssertionError: 5 != 4
======================================================================
ERROR: test_proc (tests.test_orchestrator.ProcessTest.test_proc)
----------------------------------------------------------------------
PermissionError
======================================================================
FAIL: test_cancel (tests.test_orchestrator.CancelOrderTest.test_cancel)
----------------------------------------------------------------------
Ran 2843 tests in 410.000s

FAILED (failures=2, errors=1, skipped=48)
"""


class Summary(unittest.TestCase):
    def test_a_passing_log_reports_its_count_and_result(self):
        found = summary.summarize(PASSED)
        self.assertEqual(found["ran"], 2843)
        self.assertEqual(found["result"], "OK (skipped=48)")
        self.assertEqual(found["failing"], [])
        self.assertTrue(found["complete"])

    def test_failing_tests_are_listed_once_each_and_sorted(self):
        found = summary.summarize(FAILED)
        self.assertEqual(found["failing"], [
            "ERROR: test_proc (tests.test_orchestrator.ProcessTest.test_proc)",
            "FAIL: test_cancel (tests.test_orchestrator.CancelOrderTest.test_cancel)",
        ])
        self.assertEqual(found["result"], "FAILED (failures=2, errors=1, skipped=48)")

    def test_an_empty_or_cut_off_log_is_never_reported_as_a_pass(self):
        for log in ("", "test_a ... ok\n", "Ran 12 tests in 1.0s\n"):
            with self.subTest(log=log):
                found = summary.summarize(log)
                self.assertFalse(found["complete"])
                text = summary.render(found)
                self.assertNotIn("`OK", text)
                self.assertIn("did not finish", text)

    def test_the_last_count_wins_when_the_log_holds_more_than_one(self):
        found = summary.summarize("Ran 3 tests in 1.0s\n\nOK\n" + PASSED)
        self.assertEqual(found["ran"], 2843)

    def test_the_command_writes_the_summary_and_exits_zero_even_on_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            log, out = Path(tmp) / "suite.log", Path(tmp) / "summary.md"
            log.write_text(FAILED, encoding="utf-8")
            done = subprocess.run([sys.executable, "-m", "tools.macos_suite_summary", str(log), str(out)],
                                  cwd=REPO, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            text = out.read_text(encoding="utf-8")
            self.assertIn("Ran: 2843 tests", text)
            self.assertIn("Failing or erroring tests: 2", text)
            self.assertIn("tests.test_orchestrator.ProcessTest.test_proc", text)

    def test_a_missing_log_is_reported_as_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "summary.md"
            done = subprocess.run([sys.executable, "-m", "tools.macos_suite_summary", str(Path(tmp) / "none.log"),
                                   str(out)], cwd=REPO, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("no log", out.read_text(encoding="utf-8"))


class Workflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.doc = yaml.safe_load(cls.text)

    def test_it_holds_no_secret_no_environment_and_reads_only(self):
        self.assertEqual(self.doc["permissions"], {"contents": "read"})
        self.assertNotIn("secrets.", self.text)
        for job in self.doc["jobs"].values():
            self.assertNotIn("environment", job)
            self.assertNotIn("permissions", job)

    def test_it_reports_and_never_gates(self):
        steps = self.doc["jobs"]["suite"]["steps"]
        suite = next(s for s in steps if s.get("id") == "suite")
        self.assertIs(suite.get("continue-on-error"), True)
        self.assertIn("pipefail", suite["run"])
        report = [s for s in steps if "tools.macos_suite_summary" in s.get("run", "")]
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0].get("if"), "always()")

    def test_it_runs_on_macos_with_a_time_limit(self):
        job = self.doc["jobs"]["suite"]
        self.assertTrue(str(job["runs-on"]).startswith("macos-"))
        self.assertLessEqual(job["timeout-minutes"], 60)

    def test_the_merge_guard_reads_no_alias_in_it(self):
        # A cron line such as '17 9 * * *' reads to the guard's line check as an alias; this file avoids it.
        self.assertEqual(merge_guard.aliases(self.text), 0)

    def test_it_never_installs_tools_the_shared_actions_own(self):
        for banned in ("apt-get", "get_godot.sh", "playwright install"):
            self.assertNotIn(banned, self.text)


if __name__ == "__main__":
    unittest.main()
