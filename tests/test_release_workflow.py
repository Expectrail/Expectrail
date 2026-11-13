"""The release workflow (#333): a version tag builds the wheel and attaches it to the run, and nothing else.

It holds no secret, reads only, publishes nowhere, and builds nothing when the tag is not the package's
own version. The version step is run here in bash, as the runner runs it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

import expectrail

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


class ReleaseWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.doc = yaml.safe_load(cls.text)
        cls.on = cls.doc.get("on", cls.doc.get(True))
        cls.job = cls.doc["jobs"]["wheel"]

    def test_a_version_tag_or_a_dispatch_starts_it(self):
        self.assertEqual(set(self.on), {"push", "workflow_dispatch"})
        self.assertEqual(self.on["push"], {"tags": ["v*"]})
        self.assertIsNone(self.on["workflow_dispatch"])

    def test_it_reads_only_and_holds_no_secret(self):
        self.assertEqual(self.doc["permissions"], {"contents": "read"})
        self.assertEqual(list(self.doc["jobs"]), ["wheel"])
        self.assertNotIn("permissions", self.job)
        self.assertNotIn("environment", self.job)
        for never in ("secrets.", "github.token", "id-token", "pull_request_target"):
            self.assertNotIn(never, self.text)
        for step in self.job["steps"]:
            if step.get("uses", "").startswith("actions/checkout"):
                self.assertEqual(step["with"]["persist-credentials"], False)

    def test_it_publishes_nowhere(self):
        body = yaml.safe_dump(self.job).lower()
        for never in ("twine", "pypa/gh-action-pypi-publish", "docker push", "gh release", "git push", "ghcr.io"):
            self.assertNotIn(never, body)
        uploads = [s for s in self.job["steps"] if s.get("uses", "").startswith("actions/upload-artifact")]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0]["with"]["if-no-files-found"], "error")

    def test_the_version_is_checked_before_the_build_and_the_wheel_is_installed_before_the_upload(self):
        names = [s.get("name", s.get("uses", "")) for s in self.job["steps"]]
        at = {k: next(i for i, n in enumerate(names) if k in n)
              for k in ("The tag is the package's version", "Build the wheel", "clean venv", "upload-artifact")}
        self.assertLess(at["The tag is the package's version"], at["Build the wheel"])
        self.assertLess(at["Build the wheel"], at["clean venv"])
        self.assertLess(at["clean venv"], at["upload-artifact"])
        install = next(s for s in self.job["steps"] if "clean venv" in s.get("name", ""))["run"]
        self.assertIn('grep -q "installed package"', install)
        self.assertIn("--no-deps", install)

    def test_events_reach_shells_only_through_the_environment(self):
        for step in self.job["steps"]:
            self.assertNotRegex(step.get("run", ""), r"\$\{\{\s*(inputs|github)\.")

    def test_actions_are_pinned(self):
        for step in self.job["steps"]:
            uses = step.get("uses", "")
            if uses and not uses.startswith("./"):
                self.assertRegex(uses, r"@[0-9a-f]{40}$")


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class VersionStepTest(unittest.TestCase):
    """The version step, run in bash from a copy of the checkout's expectrail/__init__.py."""

    def setUp(self):
        doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        self.script = next(s for s in doc["jobs"]["wheel"]["steps"] if s.get("id") == "version")["run"]
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        (self.tmp / "expectrail").mkdir()
        shutil.copy(ROOT / "expectrail" / "__init__.py", self.tmp / "expectrail" / "__init__.py")

    def run_step(self, ref_type: str, ref_name: str):
        out = self.tmp / "output"
        out.write_text("")
        env = {"PATH": os.environ["PATH"], "REF_TYPE": ref_type, "REF_NAME": ref_name, "GITHUB_OUTPUT": str(out)}
        proc = subprocess.run(["bash", "-e", "-c", self.script], cwd=self.tmp, env=env, capture_output=True,
                              text=True, timeout=60)
        return proc.returncode, proc.stdout, out.read_text()

    def test_the_tag_of_the_package_version_builds(self):
        code, _, out = self.run_step("tag", "v" + expectrail.__version__)
        self.assertEqual((code, out), (0, f"version={expectrail.__version__}\n"))

    def test_another_tag_builds_nothing_and_says_why(self):
        for tag in ("v9.9.9", expectrail.__version__, "v" + expectrail.__version__ + "-rc1", "v"):
            code, said, out = self.run_step("tag", tag)
            self.assertEqual((code, out), (1, ""), tag)
            self.assertIn("Nothing was built", said)

    def test_a_dispatch_builds_from_main_only(self):
        self.assertEqual(self.run_step("branch", "main")[0], 0)
        code, said, out = self.run_step("branch", "agent/333-release-readme")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("from main only", said)


if __name__ == "__main__":
    unittest.main()
