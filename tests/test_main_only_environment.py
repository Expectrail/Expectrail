"""Model keys and the held-out token are reachable only through the main-only environment.

Anyone with write access, or a coding agent acting for them, could read any repository secret by
pushing a branch with a new workflow. So HELDOUT_TOKEN (which reads the private held-out repository)
and every model API key live in the `main-only` environment, which only `main` may deploy to, and
every job that uses one declares it. These tests keep it that way: a job that names one of these
secrets outside the environment, or a job in the environment that a pull request can start, fails.

The Unity licence is the one other secret; it lives in the `unity` environment, which requires a
maintainer's approval for every run (.github/obaaf.yml records that review).
"""
from __future__ import annotations

import re
import unittest

import yaml

from harness.run import REPO

WORKFLOWS = REPO / ".github" / "workflows"
PROTECTED = re.compile(r"secrets\.([A-Z0-9_]*_API_KEY|HELDOUT_TOKEN)\b")
ANY_SECRET = re.compile(r"secrets\.([A-Z0-9_]+)\b")
# Jobs in main-only that a pull_request_target can start: they run as main, so the branch rule does
# not stop them. Each is reviewed in .github/obaaf.yml.
PULL_REQUEST_TARGET_REVIEWED = {"private-scan.yml:private-export-scan"}


def workflows():
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        triggers = doc.get("on", doc.get(True)) or {}
        triggers = set(triggers) if isinstance(triggers, (dict, list)) else {triggers}
        yield path, doc, triggers


def environment(job: dict) -> str | None:
    env = job.get("environment")
    return env.get("name") if isinstance(env, dict) else env


class MainOnlyEnvironmentTest(unittest.TestCase):
    def test_every_job_using_a_protected_secret_declares_main_only(self):
        users = []
        for path, doc, _ in workflows():
            self.assertNotRegex(yaml.safe_dump(doc.get("env") or {}), PROTECTED, path.name)
            for name, job in (doc.get("jobs") or {}).items():
                text = yaml.safe_dump(job)
                self.assertNotIn("toJSON(secrets)", text, f"{path.name} job {name} takes every secret")
                self.assertNotEqual(job.get("secrets"), "inherit", f"{path.name} job {name} inherits every secret")
                if PROTECTED.search(text):
                    users.append(f"{path.name}:{name}")
                    self.assertEqual(environment(job), "main-only",
                                     f"{path.name} job {name} uses a model key or HELDOUT_TOKEN outside main-only")
        self.assertGreater(len(users), 20)

    def test_the_only_other_secrets_are_unitys_behind_approval(self):
        for path, doc, _ in workflows():
            for name, job in (doc.get("jobs") or {}).items():
                others = {s for s in ANY_SECRET.findall(yaml.safe_dump(job))
                          if s != "GITHUB_TOKEN" and not PROTECTED.search(f"secrets.{s}")}
                if others:
                    self.assertTrue(others <= {"UNITY_LICENSE", "UNITY_EMAIL", "UNITY_PASSWORD"},
                                    f"{path.name} job {name} uses {sorted(others)}")
                    self.assertEqual(environment(job), "unity", f"{path.name} job {name}")

    def test_no_main_only_job_runs_on_a_pull_request(self):
        """A job in main-only that a pull request could start would fail at the environment check;
        each such job must be limited to other events, by its own `if:` or by a job it needs."""
        for path, doc, triggers in workflows():
            jobs = doc.get("jobs") or {}

            def limited(name: str, seen=()) -> bool:
                job = jobs[name]
                cond = str(job.get("if", ""))
                if "github.event_name == 'workflow_dispatch'" in cond and "||" not in cond:
                    return True
                if "github.event_name != 'pull_request'" in cond and "||" not in cond:
                    return True
                if re.search(r"\b(always|cancelled|failure)\s*\(", cond):
                    return False  # it can run although the job it needs was skipped
                needs = job.get("needs") or []
                needs = [needs] if isinstance(needs, str) else needs
                return any(limited(n, seen + (name,)) for n in needs if n not in seen)

            for name, job in jobs.items():
                if environment(job) != "main-only":
                    continue
                key = f"{path.name}:{name}"
                if "pull_request_target" in triggers:
                    self.assertIn(key, PULL_REQUEST_TARGET_REVIEWED)
                if "pull_request" in triggers:
                    self.assertTrue(limited(name), f"{key} is in main-only but a pull request can start it")


if __name__ == "__main__":
    unittest.main()
