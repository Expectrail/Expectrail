"""The outside projects trial (#263): the pinned list, the checkout it lays out, and what it records.

No outside project is fetched or started here. The real run is the workflow `outside-trial.yml`.
Standard library only.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tools import outside_trial as trial

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "outside-trial.yml"


class ListTest(unittest.TestCase):
    def test_every_project_is_pinned_to_a_full_commit_and_has_routes_of_ours(self):
        projects = trial.load_list()
        self.assertGreaterEqual(len(projects), 2)
        for p in projects:
            with self.subTest(p["name"]):
                self.assertRegex(p["commit"], r"^[0-9a-f]{40}$")
                routes = sorted((REPO / p["routes"]).glob("*.json"))
                self.assertTrue(routes)
                for route in routes:
                    doc = json.loads(route.read_text(encoding="utf-8"))
                    self.assertEqual(doc["format"], "expectrail.route/v0")
                    self.assertTrue(all(0 <= e["tick"] < doc["ticks"] for e in doc["events"]))
                # Nothing of the project itself is in this repository.
                self.assertEqual([f for f in (REPO / "tests" / "outside" / p["name"]).rglob("*") if f.is_file()], routes)

    def test_a_list_that_does_not_pin_what_runs_is_refused(self):
        good = json.loads(trial.LIST.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "projects.json"
            for label, change in (
                    ("a short commit", {"commit": "b761b4c"}), ("a branch name", {"commit": "master"}),
                    ("another host", {"repository": "https://example.com/x/y.git"}),
                    ("a local path", {"repository": "/tmp/somewhere.git"}),
                    ("a path that climbs out", {"path": "2d/../../etc"}), ("an absolute path", {"path": "/etc"}),
                    ("routes that are not ours", {"routes": "2d/routes"}), ("a name with a slash", {"name": "a/b"}),
                    ("no licence", {"licence": None})):
                with self.subTest(label):
                    doc = json.loads(json.dumps(good))
                    doc["projects"][0].update(change)
                    path.write_text(json.dumps(doc), encoding="utf-8")
                    with self.assertRaises(trial.TrialError):
                        trial.load_list(path)
            doc = json.loads(json.dumps(good))
            doc["projects"][1]["name"] = doc["projects"][0]["name"]
            path.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaises(trial.TrialError):
                trial.load_list(path)


class TrialTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="expectrail-outside-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.project = trial.load_list()[0]
        # A stand-in for the fetched repository: only the file the layout looks for.
        folder = self.tmp / "source" / self.project["path"]
        folder.mkdir(parents=True)
        (folder / "project.godot").write_text("config_version=5\n", encoding="utf-8")
        (folder / "main.gd").write_text("extends Node\n", encoding="utf-8")

    def command(self, code: int, stdout: str) -> list[str]:
        script = self.tmp / f"stand-in-{code}.py"
        script.write_text(f"import sys\nsys.stdout.write({stdout!r})\nsys.exit({code})\n", encoding="utf-8")
        return [sys.executable, str(script)]

    def test_the_checkout_holds_the_project_our_routes_and_the_bundled_spec(self):
        checkout = trial.lay_out(self.project, self.tmp / "source", self.tmp / "work")
        self.assertEqual(sorted(p.relative_to(checkout).as_posix() for p in checkout.rglob("*") if p.is_file()),
                         ["project/main.gd", "project/project.godot", "routes/walk.json", "specs/" + trial.SPEC.name])
        self.assertEqual((checkout / "specs" / trial.SPEC.name).read_bytes(), trial.SPEC.read_bytes())   # copied, not approved here
        with self.assertRaisesRegex(trial.TrialError, "no project.godot"):
            trial.lay_out(self.project, self.tmp / "nowhere", self.tmp / "work")

    def test_a_verdict_is_recorded_with_its_reasons_and_its_time(self):
        checkout = trial.lay_out(self.project, self.tmp / "source", self.tmp / "work")
        answer = json.dumps({"decision": "needs-review", "reasons": ["no checks ran"]})
        row = trial.verify(self.project, checkout, self.tmp / "out", self.command(2, answer), 60)
        self.assertEqual((row["exit"], row["verdict"], row["decision"], row["reasons"]), (2, "needs-review", "needs-review", ["no checks ran"]))
        self.assertEqual((row["commit"], row["licence"]), (self.project["commit"], "MIT"))
        self.assertGreaterEqual(row["seconds"], 0)
        table = trial.markdown([row])
        self.assertIn("needs-review", table)
        self.assertIn(self.project["commit"][:7], table)

    def test_a_code_that_is_no_verdict_is_not_given_one(self):
        checkout = trial.lay_out(self.project, self.tmp / "source", self.tmp / "work")
        for code in (3, 4, 5, 6, 70):
            with self.subTest(code=code):
                row = trial.verify(self.project, checkout, self.tmp / "out", self.command(code, "it broke"), 60)
                self.assertEqual((row["exit"], row["verdict"], row["output"]), (code, None, "it broke"))
                self.assertIn("no verdict", trial.markdown([row]))


class WorkflowTest(unittest.TestCase):
    def test_the_job_that_starts_outside_code_holds_no_secret_and_requires_the_sandbox(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        self.assertNotIn("secrets.", code)
        self.assertNotIn("pull_request_target", code)
        self.assertNotIn("id-token", code)
        self.assertEqual([line.strip() for line in code.splitlines() if line.strip().endswith(": write")], [])
        self.assertIn("permissions:\n  contents: read\n", code)
        self.assertIn("persist-credentials: false", code)
        self.assertIn("python -m tools.outside_trial --fetch --execution-class isolated", code)


if __name__ == "__main__":
    unittest.main()
