"""The Unity workflow: a licensed build that skips cleanly without its secrets, one Editor at a time,
a Library cache only the clean build on main writes, and an unlicensed replay in a pinned container.

Nothing here runs Unity. These tests read .github/workflows/unity.yml and run its shell steps.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from harness.run import REPO

PATH = REPO / ".github" / "workflows" / "unity.yml"
PROJECT_VERSION = REPO / "game" / "unity-platformer" / "ProjectSettings" / "ProjectVersion.txt"
UNITY_SECRETS = {"UNITY_LICENSE", "UNITY_EMAIL", "UNITY_PASSWORD"}
# game-ci/unity-builder's v4 tag (v4.8.2), resolved with git ls-remote on Nov 9, 2026.
UNITY_BUILDER = "game-ci/unity-builder@4423ee75828dff56037d1d1cfdac6b68e3a6ba00"
PRESENT = "steps.secrets.outputs.present == 'true'"


def _shell(script: str) -> str:
    """A run script with its ${{ }} expressions replaced, so bash can parse it."""
    return re.sub(r"\$\{\{.*?\}\}", "EXPR", script)


class UnityWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.text = PATH.read_text(encoding="utf-8")
        self.doc = yaml.safe_load(self.text)
        self.jobs = self.doc["jobs"]
        self.build = self.jobs["build"]
        self.replay = self.jobs["replay"]

    def steps(self, job: dict, uses: str | None = None, name: str | None = None) -> list[dict]:
        return [s for s in job["steps"]
                if (uses is None or str(s.get("uses", "")).startswith(uses))
                and (name is None or s.get("name") == name)]

    def test_it_runs_when_dispatched_or_on_pull_requests_that_touch_unity(self):
        self.assertEqual(set(self.doc[True]), {"pull_request", "workflow_dispatch"})
        self.assertEqual(self.doc[True]["pull_request"]["paths"],
                         ["game/unity-platformer/**", "harness/unity/**", ".github/workflows/unity.yml"])

    def test_permissions_are_read_only(self):
        self.assertEqual(self.doc["permissions"], {"contents": "read"})
        for name, job in self.jobs.items():
            with self.subTest(job=name):
                self.assertEqual(job.get("permissions", {"contents": "read"}), {"contents": "read"})

    def test_every_job_has_a_timeout(self):
        for name, job in self.jobs.items():
            with self.subTest(job=name):
                self.assertIsInstance(job.get("timeout-minutes"), int)

    def test_every_action_is_pinned_by_full_commit_sha(self):
        uses = re.findall(r"uses:\s*(\S+)", self.text)
        self.assertTrue(uses)
        for ref in uses:
            with self.subTest(uses=ref):
                self.assertRegex(ref, r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
        self.assertEqual(len(self.steps(self.build, uses=UNITY_BUILDER)), 1)
        self.assertIn(f"uses: {UNITY_BUILDER} # v4.8.2", self.text)

    def test_the_build_runs_in_the_unity_environment_one_editor_at_a_time(self):
        self.assertEqual(self.build["environment"], "unity")
        # One group for the whole repository: no ref, run or PR number in its name.
        self.assertEqual(self.build["concurrency"], {"group": "unity-editor-seat", "cancel-in-progress": False})
        self.assertNotIn("environment", self.replay)
        self.assertNotIn("concurrency", self.replay)

    def test_only_the_three_unity_secrets_appear_and_only_in_the_build_job(self):
        self.assertEqual(set(re.findall(r"secrets\.([A-Z0-9_]+)", self.text)), UNITY_SECRETS)
        self.assertNotIn("secrets.", yaml.safe_dump(self.replay))
        self.assertNotIn("HELDOUT", self.text)
        self.assertNotIn("Expectrail-heldout", self.text)

    def test_secret_values_reach_only_the_builder(self):
        for i, step in enumerate(self.build["steps"]):
            dumped = yaml.safe_dump(step)
            values = re.findall(r"secrets\.[A-Z_]+ \}\}", dumped)
            with self.subTest(step=step.get("name") or step.get("uses")):
                if str(step.get("uses", "")).startswith("game-ci/unity-builder@"):
                    self.assertEqual(step["env"], {s: f"${{{{ secrets.{s} }}}}" for s in UNITY_SECRETS})
                else:
                    self.assertEqual(values, [])
        # The job's own env holds only whether each secret is set, never its value.
        self.assertEqual({k: v for k, v in self.build["env"].items() if "secrets." in v},
                         {f"{s}_SET": f"${{{{ secrets.{s} != '' }}}}" for s in UNITY_SECRETS})

    def test_no_job_level_if_reads_secrets(self):
        # GitHub refuses the whole workflow if a job-level if uses the secrets context.
        for name, job in self.jobs.items():
            with self.subTest(job=name):
                self.assertNotIn("secrets.", str(job.get("if", "")))

    def test_without_secrets_the_build_skips_with_a_notice_and_never_fails_open(self):
        script = self.steps(self.build, name="Skip without the Unity licence secrets")[0]["run"]
        cases = {
            ("false", "false", "false"): (0, "present=false", "::notice title=Unity build skipped::"),
            ("true", "true", "true"): (0, "present=true", None),
            ("true", "false", "false"): (1, "", "::error title=Unity licence secrets::1 of the 3"),
            ("true", "true", "false"): (1, "", "::error title=Unity licence secrets::2 of the 3"),
        }
        for flags, (code, output, message) in cases.items():
            with self.subTest(flags=flags), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "out"
                out.write_text("")
                env = dict(os.environ, UNITY_LICENSE_SET=flags[0], UNITY_EMAIL_SET=flags[1],
                           UNITY_PASSWORD_SET=flags[2], GITHUB_OUTPUT=str(out))
                proc = subprocess.run(["bash", "-e", "-c", script], env=env, capture_output=True, text=True)
                self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
                self.assertEqual(out.read_text().strip(), output)
                if message:
                    self.assertIn(message, proc.stdout)
        notice = cases[("false", "false", "false")][2]
        self.assertIn("nothing was checked", script.split(notice, 1)[1].splitlines()[0])

    def test_every_build_step_after_the_check_waits_for_the_secrets(self):
        steps = self.build["steps"]
        self.assertEqual(steps[0]["id"], "secrets")
        for step in steps[1:]:
            with self.subTest(step=step.get("name") or step.get("uses")):
                self.assertTrue(str(step.get("if", "")).startswith(PRESENT), step.get("if"))
        self.assertEqual(self.build["outputs"]["built"], "${{ steps.done.outputs.built }}")
        self.assertEqual(steps[-1]["id"], "done")
        self.assertEqual(self.replay["needs"], "build")
        self.assertEqual(self.replay["if"], "needs.build.outputs.built == 'true'")

    def test_it_builds_with_the_projects_editor_for_linux(self):
        version = re.search(r"^m_EditorVersion: (\S+)$", PROJECT_VERSION.read_text(), re.M).group(1)
        self.assertRegex(version, r"^6000\.3\.\d+f\d+$")
        self.assertEqual(self.build["env"]["UNITY_VERSION"], version)
        image = f"unityci/editor:ubuntu-{version}-linux-il2cpp-3"
        self.assertEqual(self.build["env"]["UNITY_IMAGE"], image)
        for step in self.steps(self.build, uses="game-ci/unity-builder@"):
            with self.subTest(step=step["name"]):
                self.assertEqual(step["with"]["targetPlatform"], "StandaloneLinux64")
                self.assertEqual(step["with"]["unityVersion"], version)
                self.assertEqual(step["with"]["customImage"], image)
                # Semantic versioning would refuse a dirty tree and needs the whole history.
                self.assertEqual(step["with"]["versioning"], "None")

    def test_the_clean_build_uses_gameci_s_own_build_method(self):
        clean = self.steps(self.build, uses="game-ci/unity-builder@")[0]
        self.assertEqual(clean["with"]["projectPath"], "runs/unity/clean/project")
        self.assertNotIn("buildMethod", clean["with"])
        # A copy of the committed game: the checkout stays as committed for the digests taken later.
        copy = self.steps(self.build, name="Copy the clean game to build it")[0]["run"]
        self.assertIn("cp -a game/unity-platformer runs/unity/clean/project", copy)
        order = self.build["steps"]
        self.assertLess(order.index(self.steps(self.build, name="Copy the clean game to build it")[0]), order.index(clean))
        self.assertNotIn("game/unity-platformer", yaml.safe_dump(clean))

    def test_the_library_cache_is_saved_only_from_the_clean_build_on_main(self):
        key = self.steps(self.build, name="Library cache key (the clean game's Assets, Packages and ProjectSettings)")[0]
        self.assertEqual(key["env"]["KEY"], "unity-library-StandaloneLinux64-${{ hashFiles("
                         "'game/unity-platformer/Assets/**', 'game/unity-platformer/Packages/**', "
                         "'game/unity-platformer/ProjectSettings/**') }}")
        restores = self.steps(self.build, uses="actions/cache/restore@")
        saves = self.steps(self.build, uses="actions/cache/save@")
        self.assertEqual(len(restores), 1)
        self.assertEqual(len(saves), 1)
        self.assertEqual(self.steps(self.build, uses="actions/cache@"), [])  # the combined action saves on any branch
        library = "runs/unity/clean/project/Library"
        self.assertEqual(restores[0]["with"]["path"], library)
        self.assertEqual(saves[0]["with"]["path"], library)
        self.assertEqual(saves[0]["with"]["key"], "${{ steps.key.outputs.key }}")
        self.assertIn("github.ref == 'refs/heads/main'", saves[0]["if"])
        # Saved after the clean build and before any other build.
        order = self.build["steps"]
        builds = [i for i, s in enumerate(order) if str(s.get("uses", "")).startswith("game-ci/unity-builder@")]
        self.assertLess(builds[0], order.index(saves[0]))
        self.assertTrue(all(order.index(saves[0]) < i for i in builds[1:]))

    def test_only_clean_or_public_players_are_uploaded(self):
        names = [s["with"]["name"] for job in self.jobs.values() for s in self.steps(job, uses="actions/upload-artifact@")]
        players = [n for n in names if n.startswith("unity-player-")]
        self.assertEqual(players, ["unity-player-clean"])

    def test_the_replay_job_needs_no_licence_and_runs_in_a_pinned_container(self):
        self.assertRegex(self.replay["container"]["image"], r"^ubuntu:[\w.-]+@sha256:[0-9a-f]{64}$")
        env = self.replay["env"]
        self.assertEqual(env["LP_NATIVE_VECTOR_WIDTH"], "128")
        self.assertRegex(env["LP_NUM_THREADS"], r"^[1-9][0-9]*$")
        self.assertEqual(env["GALLIUM_DRIVER"], "llvmpipe")
        self.assertEqual(env["LIBGL_ALWAYS_SOFTWARE"], "1")
        record = self.steps(self.replay, name="Record the machine")[0]["run"]
        self.assertIn("/proc/cpuinfo", record)

    def test_times_are_published_as_notices(self):
        self.assertIn("::notice title=Unity build time::", self.text)
        self.assertIn("::notice title=Unity times::", self.text)

    def test_the_shell_steps_parse(self):
        for name, job in self.jobs.items():
            for step in job["steps"]:
                if "run" in step:
                    with self.subTest(job=name, step=step.get("name")):
                        subprocess.run(["bash", "-n"], input=_shell(step["run"]), text=True, check=True)

    def test_the_obaaf_audit_needs_no_declaration_for_these_jobs(self):
        # The jobs hold Unity secrets, not model keys, so the lane audit sees neither an agent lane
        # nor a perception job to declare (agents/assurance/audit.py).
        from agents.assurance import audit

        jobs = {f".github/workflows/unity.yml#{name}" for name in self.jobs}
        self.assertFalse(jobs & set(audit.model_jobs()))
        self.assertFalse(jobs & audit.declared_agents())
        lanes = {job: "trusted" for job in jobs}
        self.assertEqual(audit.inventory_problems(lanes, set(), {}), [])


if __name__ == "__main__":
    unittest.main()
