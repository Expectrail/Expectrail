"""HELDOUT_TOKEN is reachable only through the heldout environment.

The token reads the private held-out repository. It lives in the `heldout` environment, which only
main may deploy to, so a workflow written on another branch (by a person or a coding agent) cannot
fetch the blind sets. This test keeps every job that names the secret inside that environment, so a
new workflow cannot quietly fall back to a repository-level secret.
"""
from __future__ import annotations

import unittest

import yaml

from harness.run import REPO

WORKFLOWS = REPO / ".github" / "workflows"


class HeldoutEnvironmentTest(unittest.TestCase):
    def test_every_job_using_the_token_declares_the_environment(self):
        users = []
        for path in sorted(WORKFLOWS.glob("*.y*ml")):
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            for name, job in (doc.get("jobs") or {}).items():
                if "HELDOUT_TOKEN" not in yaml.safe_dump(job):
                    continue
                users.append(f"{path.name}:{name}")
                env = job.get("environment")
                env = env.get("name") if isinstance(env, dict) else env
                self.assertEqual(env, "heldout", f"{path.name} job {name} reads HELDOUT_TOKEN outside the heldout environment")
        self.assertGreater(len(users), 0, "no job uses HELDOUT_TOKEN; update this test if that is deliberate")

    def test_the_token_is_not_set_at_workflow_level(self):
        for path in sorted(WORKFLOWS.glob("*.y*ml")):
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertNotIn("HELDOUT_TOKEN", yaml.safe_dump(doc.get("env") or {}), path.name)


if __name__ == "__main__":
    unittest.main()
