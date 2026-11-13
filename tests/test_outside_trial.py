"""The outside projects trial (#263): the pinned list, the checkout it lays out, and what it records.

No outside project is fetched or started here. The real run is the workflow `outside-trial.yml`.
Standard library only.
"""
from __future__ import annotations

import json
import shutil
import subprocess
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
                # Nothing of the project itself is in this repository: our routes, and our patches
                # for the changes it lists (small diffs, a few lines of context each), and no other file.
                patches = sorted(REPO / c["patch"] for c in p.get("changes", []))
                for patch in patches:
                    self.assertLess(patch.stat().st_size, 2048, patch.name)
                self.assertEqual(sorted(f for f in (REPO / "tests" / "outside" / p["name"]).rglob("*") if f.is_file()),
                                 sorted(routes + patches))

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
                    ("no licence", {"licence": None}),
                    ("a patch that is not ours", {"changes": [{"name": "x", "patch": "2d/x.patch", "expect": "reject", "what": "w"}]}),
                    ("a patch that climbs out", {"changes": [{"name": "x", "expect": "reject", "what": "w",
                                                              "patch": "tests/outside/kinematic-character/changes/../../../x.patch"}]}),
                    ("a verdict that is not one", {"changes": [{"name": "x", "expect": "pass", "what": "w",
                                                                "patch": "tests/outside/kinematic-character/changes/x.patch"}]}),
                    ("a change that says nothing", {"changes": [{"name": "x", "expect": "reject",
                                                                 "patch": "tests/outside/kinematic-character/changes/x.patch"}]})):
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


class ChangeTest(TrialTest):
    def setUp(self):
        super().setUp()
        (self.tmp / "source" / self.project["path"] / "main.gd").write_text('extends Node\n\nvar speed = 1\n', encoding="utf-8")
        self.patch = REPO / "tests" / "outside" / self.project["name"] / "changes" / "test-only.patch"
        self.patch.write_text("diff --git a/main.gd b/main.gd\n--- a/main.gd\n+++ b/main.gd\n@@ -1,3 +1,3 @@\n extends Node\n \n"
                              "-var speed = 1\n+var speed = 2\n", encoding="utf-8")
        self.addCleanup(self.patch.unlink)
        self.change = {"name": "faster", "patch": str(self.patch.relative_to(REPO)), "expect": "reject", "what": "speed 2"}

    def test_the_change_is_applied_to_a_copy_and_the_project_unchanged_is_the_base(self):
        base = trial.lay_out(self.project, self.tmp / "source", self.tmp / "work")
        head = trial.lay_out(self.project, self.tmp / "source", self.tmp / "work", self.change)
        self.assertEqual(head.name, f"{self.project['name']}+faster")
        self.assertIn("speed = 2", (head / "project" / "main.gd").read_text(encoding="utf-8"))
        self.assertIn("speed = 1", (base / "project" / "main.gd").read_text(encoding="utf-8"))
        args = self.tmp / "args.txt"
        script = self.tmp / "record.py"
        script.write_text(f"import sys, json\nopen({str(args)!r}, 'w').write(json.dumps(sys.argv[1:]))\n"
                          "print(json.dumps({'decision': 'reject', 'reasons': ['a check fails']}))\nsys.exit(1)\n", encoding="utf-8")
        row = trial.verify(self.project, head, self.tmp / "out", [sys.executable, str(script)], 60, base=base, change=self.change)
        given = json.loads(args.read_text(encoding="utf-8"))
        self.assertEqual(given[given.index("--base") + 1], str(base))
        self.assertEqual(given[given.index("--head") + 1], str(head))
        self.assertEqual((row["change"], row["expect"], row["verdict"]), ("faster", "reject", "reject"))
        self.assertIn("reject (as expected)", trial.markdown([row]))
        row["verdict"] = "needs-review"
        self.assertIn("reject (DIFFERS)", trial.markdown([row]))

    def test_a_checkout_inside_a_repository_is_still_changed(self):
        # The first run on PR #385 laid checkouts out inside this repository, and `git apply` read the
        # patch's paths from the repository's top, skipped the file, and exited 0 with nothing changed.
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        head = trial.lay_out(self.project, self.tmp / "source", self.tmp / "work" / "inside", self.change)
        self.assertIn("speed = 2", (head / "project" / "main.gd").read_text(encoding="utf-8"))

    def test_a_patch_that_does_not_apply_stops_the_trial_and_says_so(self):
        self.patch.write_text("diff --git a/main.gd b/main.gd\n--- a/main.gd\n+++ b/main.gd\n@@ -1,1 +1,1 @@\n-nothing like this\n+x\n",
                              encoding="utf-8")
        with self.assertRaisesRegex(trial.TrialError, "does not apply"):
            trial.lay_out(self.project, self.tmp / "source", self.tmp / "work", self.change)

    def test_a_patch_cannot_reach_outside_the_project(self):
        self.patch.write_text("diff --git a/../escape.gd b/../escape.gd\nnew file mode 100644\n--- /dev/null\n+++ b/../escape.gd\n"
                              "@@ -0,0 +1 @@\n+x\n", encoding="utf-8")
        with self.assertRaises(trial.TrialError):
            trial.lay_out(self.project, self.tmp / "source", self.tmp / "work", self.change)
        self.assertFalse((self.tmp / "work" / f"{self.project['name']}+faster" / "escape.gd").exists())


class AroundTest(unittest.TestCase):
    def test_a_failing_checks_first_frame_is_shown_with_what_the_engine_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "jobs" / "abc" / "work" / "gate" / "head" / "walk"
            folder.mkdir(parents=True)
            rows = [{"tick": t, "player": [float(t), 300.0], "ground": 272.5 if t >= 100 else None, "onFloor": True,
                     "view": [1, 0, 0, 1, 0, 0]} for t in range(360)]
            (folder / "trace.json").write_text(json.dumps({"physicsTicksPerSecond": 120, "rows": rows}), encoding="utf-8")
            shown = trial.around(Path(tmp) / "jobs", {"spec": "s", "route": "walk", "frame": 92})
            self.assertEqual(shown["ticksPerFrame"], 2)
            self.assertEqual([r["tick"] for r in shown["rows"]], [178, 180, 182, 184, 186, 188, 190])   # frame 92 is tick 184
            self.assertEqual(shown["rows"][3], {"tick": 184, "player": [184.0, 300.0], "ground": 272.5, "groundFrom": None,
                                                "body": None, "onFloor": True, "view": [1, 0, 0, 1, 0, 0]})
            self.assertEqual(trial.around(Path(tmp) / "jobs", {"spec": "s", "route": "other", "frame": 1})["rows"], [])
            row = {"name": "x", "commit": "b" * 40, "licence": "MIT", "kind": "k", "exit": 1, "verdict": "reject",
                   "seconds": 1, "checks": None, "reasons": ["r"], "failures": [], "around": [shown]}
            self.assertIn('"tick": 184', trial.markdown([row]))


    def test_a_check_that_could_not_be_decided_shows_the_first_frame_with_nothing_found(self):
        # Run 43428126877: kinematic-character was needs-review, "an object was not found in 5 frames
        # (first 38)", and nothing showed what the engine logged there.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            folder = tmp / "out" / "jobs" / "kc" / "abc" / "work" / "gate" / "head" / "walk"
            folder.mkdir(parents=True)
            rows = [{"tick": t, "player": [float(t), 300.0], "ground": None if 76 <= t < 86 else 320.0,
                     "groundFrom": None if 76 <= t < 86 else "body", "onFloor": False} for t in range(240)]
            (folder / "trace.json").write_text(json.dumps({"physicsTicksPerSecond": 120, "rows": rows}), encoding="utf-8")
            reason = ("player-stays-above-ground on walk: no violation in 115 frames judged, but an object was not found "
                      "in 5 frames (first 38); a missing object is never a pass")
            script = tmp / "say.py"
            script.write_text("import json, sys\nprint(json.dumps({'decision': 'needs-review', 'reasons': "
                              f"[{reason!r}]}}))\nsys.exit(2)\n", encoding="utf-8")
            project = {**trial.load_list()[0], "name": "kc"}
            row = trial.verify(project, tmp / "checkout", tmp / "out", [sys.executable, str(script)], 60)
            self.assertEqual(row["verdict"], "needs-review")
            self.assertEqual([(a["route"], a["frame"]) for a in row["around"]], [("walk", 38)])
            shown = row["around"][0]["rows"]
            self.assertEqual([r["tick"] for r in shown], list(range(70, 89, 2)))   # 3 frames before, 6 after
            self.assertEqual(shown[3]["ground"], None)
            self.assertEqual(shown[0]["groundFrom"], "body")


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


class ProbeWorkflowTest(unittest.TestCase):
    """`outside-sam-probe.yml`: the model key and the outside code never meet."""

    def setUp(self):
        text = (REPO / ".github" / "workflows" / "outside-sam-probe.yml").read_text(encoding="utf-8")
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        head, jobs = code.split("\njobs:\n", 1)
        self.head = head
        self.capture, self.probe = jobs.split("\n  probe:\n", 1)
        self.assertTrue(self.capture.startswith("  capture:\n"))

    def test_it_is_started_by_a_person_only(self):
        self.assertIn("on:\n  workflow_dispatch:", self.head)
        for trigger in ("pull_request", "push:", "schedule", "workflow_run"):
            self.assertNotIn(trigger, self.head)
        self.assertIn("permissions:\n  contents: read\n", self.head)

    def test_the_job_that_starts_outside_code_holds_no_secret(self):
        self.assertNotIn("secrets.", self.capture)
        self.assertNotIn("environment:", self.capture)
        self.assertIn("python -m tools.outside_trial --fetch --capture", self.capture)
        self.assertIn("persist-credentials: false", self.capture)

    def test_the_job_that_holds_the_key_never_fetches_or_starts_outside_code(self):
        self.assertIn("environment: main-only", self.probe)
        self.assertIn("needs: capture", self.probe)
        for word in ("outside_trial", "harness.run", "get-godot", "git fetch", "git clone", "godot", "xvfb", "bubblewrap"):
            self.assertNotIn(word, self.probe)
        self.assertIn("actions/download-artifact@", self.probe)
        self.assertIn("python -m agents.sam_probe", self.probe)

    def test_the_probe_cannot_run_without_a_cap_or_with_one_above_two_dollars(self):
        self.assertIn('export EXPECTRAIL_SAM_USD_CAP="$CAP"', self.probe)
        self.assertLess(self.probe.index('export EXPECTRAIL_SAM_USD_CAP="$CAP"'), self.probe.index("python -m agents.sam_probe"))
        self.assertIn("if not 0 < float(sys.argv[1]) <= 2:", self.probe)
        self.assertIn("group: sam-spend", self.head)

    def test_the_capture_always_requires_the_sandbox(self):
        import inspect
        self.assertEqual(inspect.signature(trial.capture).parameters["sandbox"].default, "require")
        source = inspect.getsource(trial.main)
        self.assertIn("capture(project, lay_out(project, source, work / \"checkouts\"), args.out, args.timeout)", source)
        self.assertNotIn("sandbox=", source)


if __name__ == "__main__":
    unittest.main()
