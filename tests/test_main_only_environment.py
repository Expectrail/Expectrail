"""Model keys and the held-out token are reachable only through a protected environment.

Anyone with write access, or a coding agent acting for them, could read any repository secret by
pushing a branch with a new workflow. So HELDOUT_TOKEN (which reads the private held-out repository)
and every model API key live in the `main-only` environment, which only `main` may deploy to, and
every job that uses one declares it. These tests keep it that way: a job that names one of these
secrets outside the environment, or a job in the environment that a pull request can start, fails.

Two environments gate a run by approval instead of by branch, and each holds only what its jobs need:
`provider-keys` (the BYO provider keys, so byo-smoke can test a provider-layer change on its pull
request once a maintainer approves the run) and `unity` (the Unity licence). Both must have required
reviewers in the repository settings; GitHub creates a missing environment with none.
"""
from __future__ import annotations

import re
import unittest

import yaml

from harness.run import REPO

WORKFLOWS = REPO / ".github" / "workflows"
# secrets.NAME or secrets['NAME'], in any case (expression contexts are case-insensitive).
_REF = r"(?<![.\w-])secrets\s*(?:\.\s*([A-Za-z0-9_]+)|\[\s*['\"]([A-Za-z0-9_]+)['\"]\s*\])"
ANY_SECRET = re.compile(_REF, re.I)
# toJSON(secrets) in any spelling, or an index the test cannot read (secrets[matrix.k]).
EVERY_SECRET = re.compile(r"tojson\s*\(\s*secrets\s*\)|(?<![.\w-])secrets\s*\[\s*(?!['\"])", re.I)


def secret_refs(text: str) -> set[str]:
    return {(a or b).upper() for a, b in ANY_SECRET.findall(text)}


def is_protected(name: str) -> bool:
    return name.endswith("_API_KEY") or name == "HELDOUT_TOKEN"


# Approval-gated environments: the jobs allowed in each, and the secrets those jobs may name there.
PROVIDER_KEYS = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "BASETEN_API_KEY",
                 "META_API_KEY"}
APPROVAL_GATED = {
    "provider-keys": ({"byo-smoke.yml:byo-smoke", "byo-gateway-probe.yml:byo-gateway-probe"}, PROVIDER_KEYS),
}
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
            self.assertFalse(secret_refs(yaml.safe_dump(doc.get("env") or {})), f"{path.name}: workflow-level secret")
            for name, job in (doc.get("jobs") or {}).items():
                text = yaml.safe_dump(job)
                self.assertNotRegex(text, EVERY_SECRET, f"{path.name} job {name} can take every secret")
                self.assertNotEqual(job.get("secrets"), "inherit", f"{path.name} job {name} inherits every secret")
                used = {s for s in secret_refs(text) if is_protected(s)}
                if used:
                    key = f"{path.name}:{name}"
                    users.append(key)
                    env = environment(job)
                    if env in APPROVAL_GATED:
                        jobs, allowed = APPROVAL_GATED[env]
                        self.assertIn(key, jobs, f"{key} is not expected in the {env} environment")
                        self.assertTrue(used <= allowed, f"{key} names {sorted(used - allowed)} in {env}")
                    else:
                        self.assertEqual(env, "main-only",
                                         f"{key} uses a model key or HELDOUT_TOKEN outside main-only")
        self.assertGreater(len(users), 20)

    def test_the_only_other_secrets_are_unitys_behind_approval(self):
        for path, doc, _ in workflows():
            for name, job in (doc.get("jobs") or {}).items():
                others = {s for s in secret_refs(yaml.safe_dump(job)) if s != "GITHUB_TOKEN" and not is_protected(s)}
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

    def test_no_main_only_workflow_runs_on_another_branch(self):
        """A push or merge-group trigger that is not limited to main would start main-only jobs on
        other branches, where the environment refuses them."""
        for path, doc, _ in workflows():
            if not any(environment(j) == "main-only" for j in (doc.get("jobs") or {}).values()):
                continue
            on = doc.get("on", doc.get(True)) or {}
            if not isinstance(on, dict):
                on = {event: None for event in ([on] if isinstance(on, str) else on)}
            for event in ("push", "merge_group", "pull_request_review", "issue_comment", "issues"):
                if event not in on:
                    continue
                spec = on[event] or {}
                self.assertEqual(event, "push", f"{path.name} runs main-only jobs on {event}")
                self.assertEqual(spec.get("branches"), ["main"], f"{path.name}: push must be limited to main")
                self.assertNotIn("tags", spec, f"{path.name}: a tag push is not on main")


if __name__ == "__main__":
    unittest.main()
