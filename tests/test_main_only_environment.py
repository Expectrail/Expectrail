"""Model keys and the held-out token are reachable only through the main-only environment.

Anyone with write access, or a coding agent acting for them, could read any repository secret by
pushing a branch with a new workflow. So HELDOUT_TOKEN (which reads the private held-out repository)
and every model API key live in the `main-only` environment, which only `main` may deploy to, and
every job that uses one declares it. These tests keep it that way: a job that names one of these
secrets outside the environment, or a job in the environment that a pull request can start, fails.

The Unity licence is the one other secret; it lives in the `unity` environment, which requires a
maintainer's approval for every run (.github/obaaf.yml records that review). No key may live in an
approval-only environment: approving a run would hand a branch's code the key.
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
# Every secret at once: toJSON(secrets) in any spelling, an index the test cannot read
# (secrets[matrix.k]), the object filter (secrets.*), or the whole context handed to a function
# (format('{0}', secrets)). The last also matches the word before a comma or a closing bracket in a
# step's name; reword the name.
EVERY_SECRET = re.compile(
    r"tojson\s*\(\s*secrets\s*\)|(?<![.\w-])secrets\s*(?:\[\s*(?!['\"])|\.\s*\*|[,)])", re.I)


def secret_refs(text: str) -> set[str]:
    return {(a or b).upper() for a, b in ANY_SECRET.findall(text)}


def is_protected(name: str) -> bool:
    return name.endswith("_API_KEY") or name in {"HELDOUT_TOKEN", "EXPECTRAIL_CHECKS_PRIVATE_KEY"}


# Jobs in main-only that start when another workflow finishes (workflow_run) would run main's copy
# of the workflow for a run a pull request may have started. The private scan tried it
# and GitHub never started the run (#247). The publisher reads the candidate as data, as tested in test_ci_gate.py.
WORKFLOW_RUN_REVIEWED = {"expectrail-comment.yml:judge"}


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
                    self.assertEqual(environment(job), "main-only",
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
                if "workflow_run" in triggers:
                    self.assertIn(key, WORKFLOW_RUN_REVIEWED)
                if "pull_request" in triggers:
                    self.assertTrue(limited(name), f"{key} is in main-only but a pull request can start it")

    def test_no_workflow_uses_pull_request_target(self):
        """It runs as main with main's secrets on a pull request's event, and GitHub blocks it by
        default in public repositories from December 2, 2026 (#247). Adding it back is a person's
        decision (AGENTS.md)."""
        for path, _, triggers in workflows():
            self.assertNotIn("pull_request_target", triggers, path.name)

    def test_every_secret_at_once_is_seen_in_each_spelling(self):
        for text in ("${{ toJSON(secrets) }}", "${{ tojson( secrets ) }}", "${{ secrets[matrix.key] }}",
                     "${{ join(secrets.*, ' ') }}", "${{ toJSON(secrets.*) }}", "${{ format('{0}', secrets) }}",
                     "${{ format('{0}{1}', secrets, 1) }}"):
            self.assertRegex(text, EVERY_SECRET)
        for text in ("${{ secrets.MODEL_API_KEY }}", "${{ secrets['MODEL_API_KEY'] }}",
                     "${{ secrets.HELDOUT_TOKEN != '' }}", "${{ steps.secrets.outputs.x }}", "no secrets here"):
            self.assertNotRegex(text, EVERY_SECRET)

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
