"""Exercise the label, published clearance and fixture repair offline."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from expectrail import contracts
from expectrail.orchestrator import engines, runner, sample
from tests.test_ci_gate import BASE, HEAD, INSIDE, load_yaml
from tests.test_two_observers import Game
from tools import ci_autofix, ci_checks

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
FIX = "agents/fixtures/fix-collision-mask.patch"


class WorkflowTest(unittest.TestCase):
    def test_only_the_label_can_schedule_a_read_only_fixture(self):
        workflow = load_yaml(WORKFLOWS / "expectrail-autofix.yml")
        self.assertEqual(workflow["on"], {"pull_request": {"types": ["labeled"]}})
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        auth = workflow["jobs"]["authorize"]
        self.assertIn("github.event.label.name == 'expectrail-autofix'", auth["if"])
        self.assertIn("vars.EXPECTRAIL_CI_AUTOFIX == 'true'", auth["if"])
        self.assertNotIn("||", auth["if"])
        self.assertEqual(len(auth["steps"]), 2)
        self.assertEqual(auth["steps"][0]["with"]["ref"], "${{ github.event.pull_request.base.sha }}")
        self.assertEqual(auth["steps"][1]["run"], "python3 -m tools.ci_autofix authorize")
        self.assertEqual(auth["steps"][1]["id"], "authorize")
        for field in ("decision", "head", "intent"):
            self.assertEqual(auth["outputs"][field], "${{ steps.authorize.outputs." + field + " }}")
        job = workflow["jobs"]["repair"]
        self.assertEqual(set(workflow["jobs"]), {"authorize", "repair"})
        self.assertEqual(job["needs"], "authorize")
        self.assertEqual(job["if"].split(" && "), ["needs.authorize.result == 'success'",
                         "needs.authorize.outputs.decision == 'reject'",
                         "needs.authorize.outputs.head == github.event.pull_request.head.sha"])
        for j in (auth, job):
            self.assertNotIn("permissions", j)
        steps = job["steps"]
        self.assertEqual(steps[0]["with"]["ref"], "${{ github.event.pull_request.base.sha }}")
        self.assertEqual(steps[1]["with"]["ref"], "${{ github.event.pull_request.head.sha }}")
        self.assertNotIn("github.token", str(steps))
        self.assertEqual(steps[-1]["with"]["path"], "${{ runner.temp }}/repair-artifact")
        for s in [*auth["steps"], *steps]:
            self.assertNotIn("${{", s.get("run", ""))
            action = s.get("uses", "")
            if action.startswith("actions/checkout@"):
                self.assertIs(s["with"]["persist-credentials"], False)
            if action.startswith("actions/"):
                self.assertRegex(action, r"@[a-f0-9]{40}$")
            if action.startswith("./"):
                self.assertEqual(s["with"]["restore-only"], "true")
                composite = load_yaml(ROOT / action / "action.yml")
                saves = [x for x in composite["runs"]["steps"] if "cache/save@" in x.get("uses", "")]
                self.assertTrue(saves)
                for save in saves:
                    self.assertIn("inputs.restore-only != 'true' &&", save["if"])
        for forbidden in ("secrets.", "workflow_run", "pull_request_target", "curl |", "actions/cache/save", "environment:"):
            self.assertNotIn(forbidden, (WORKFLOWS / "expectrail-autofix.yml").read_text())


class PublishedVerdictTest(unittest.TestCase):
    def setUp(self):
        self.pr = {"number": 8, "state": "open", "base": {"sha": BASE, "ref": "main"},
                   "head": {"sha": HEAD, "repo": {"full_name": "fork/game"}, "ref": "fix"},
                   "labels": [{"name": "expectrail-autofix"}]}
        self.event = {"action": "labeled", "label": self.pr["labels"][0], "pull_request": self.pr,
                      "repository": {"full_name": "org/game", "default_branch": "main"}, "sender": {"login": "sean"}}
        self.check = {"head_sha": HEAD, "name": ci_checks.CLEARANCE, "app": {"id": 73}, "external_id": "expectrail/12/1",
                      "status": "completed", "conclusion": "failure", "output": {"summary": "reject"}}
        self.run = {"id": 12, "run_attempt": 1, "head_sha": HEAD, "path": ci_checks.CALLER, "event": "pull_request",
                    "head_repository": {"full_name": "fork/game"}, "head_branch": "fix", "pull_requests": [self.pr],
                    "conclusion": "success"}
        self.checks = [self.check]
        self.access = "write"
        self.current = self.pr

    def verdict(self):
        def public(path):
            if path.endswith("/pulls/8"):
                return self.current
            if "/check-runs?" in path:
                return {"check_runs": self.checks, "total_count": len(self.checks)}
            self.assertEqual(path, "/repos/org/game/actions/runs/12/attempts/1")
            return self.run

        def permission(path):
            self.assertEqual(path, "/repos/org/game/collaborators/sean/permission")
            return {"permission": self.access}

        return ci_autofix.published_reject(self.event, 73, public, permission)

    def test_current_reject_from_the_publisher_for_this_pr(self):
        self.assertEqual(self.verdict(), HEAD)

    def test_only_the_maintainer_label_and_current_head_qualify(self):
        for obj, key, val in ((self.event, "action", "opened"), (self.event, "label", {"name": "other"}),
                              (self.run, "head_sha", BASE), (self.run, "pull_requests", [dict(self.pr, number=4)])):
            with self.subTest(key=key), mock.patch.dict(obj, {key: val}), self.assertRaises(ValueError):
                self.verdict()
        self.current = dict(self.pr, head=dict(self.pr["head"], sha=BASE))
        with self.assertRaises(ValueError):
            self.verdict()
        self.current = self.pr
        self.access = "triage"
        with self.assertRaises(ValueError):
            self.verdict()

    def test_fork_without_pr_list_needs_the_matching_merge_revision(self):
        self.run["pull_requests"] = []
        with self.assertRaisesRegex(ValueError, "tied"):
            self.verdict()
        self.current["merge_commit_sha"] = BASE
        self.run["referenced_workflows"] = [{"path": ci_checks.CAPTURE + "@refs/pull/8/merge", "sha": BASE}]
        self.assertEqual(self.verdict(), HEAD)
        self.run["referenced_workflows"][0]["sha"] = HEAD
        with self.assertRaisesRegex(ValueError, "tied"):
            self.verdict()

    def test_failure_is_not_a_verdict_and_an_older_reject_cannot_win(self):
        for field, value in (("output", {"summary": "needs-review"}), ("output", {"summary": "accept"}),
                             ("app", {"id": 9}), ("head_sha", BASE), ("status", "in_progress"),
                             ("conclusion", "cancelled"), ("name", ci_checks.EVIDENCE)):
            with self.subTest(field=field), mock.patch.dict(self.check, {field: value}), self.assertRaises(ValueError):
                self.verdict()
        self.checks.append(dict(self.check, external_id="expectrail/13/1", status="in_progress"))
        with self.assertRaises(ValueError):
            self.verdict()


class RepairStepTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.temp = Path(tmp.name)
        self.base = sample.checkout(self.temp / "base", bug=False)
        self.head = sample.checkout(self.temp / "head", bug=True)
        fixture = self.base / FIX
        fixture.parent.mkdir(parents=True, exist_ok=True)
        fixture.write_bytes((ROOT / FIX).read_bytes())
        self.game = Game()
        player = "player/player.tscn"
        clean = (self.base / sample.GAME / player).read_bytes()
        self.game.look_of = lambda game: "clean" if (game / player).read_bytes() == clean else "BUG"
        replay = self.game.replay
        self.game.replay = lambda *args: {**replay(*args), "isolation": INSIDE}
        self.env = dict(RUNNER_TEMP=tmp.name, GITHUB_STEP_SUMMARY=str(self.temp / "summary"),
                        GAME=sample.GAME, ROUTES=sample.ROUTE, SPECS=sample.SPECS, ATTEMPTS="3", INTENT="none", BASE_CHECKOUT=str(self.base),
                        FIXTURE=FIX, HEAD_SHA=HEAD, BASE_SHA=BASE)

    def step(self):
        def wait(jobs, child, proc):
            self.assertEqual(jobs.request(child)["executionClass"], "isolated")
            engine = engines.GodotGate(replay=self.game.replay, visual=self.game.observer())
            return runner.work(jobs, child, {"godot": engine})
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(runner, "spawn", return_value=None), \
                mock.patch.object(runner, "wait", side_effect=wait), \
                mock.patch("harness.sandbox.probe", return_value=("bwrap", None)):
            ci_autofix.run_fixture()

    def test_fixture_upload_contains_only_the_record_and_verified_winner(self):
        self.step()
        out = self.temp / "repair-artifact"
        record = contracts.load_strict(out / "repair-run.json", "repair-run")
        self.assertEqual(record["result"]["decision"], "accept")
        patch = record["result"]["patch"]
        self.assertEqual((out / patch).read_bytes(), (ROOT / FIX).read_bytes())
        self.assertEqual(sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()),
                         [patch, "repair-run.json"])
        summary = (self.temp / "summary").read_text()
        for word in (record["review"], "accepted", "patch --dry-run", "reject"):
            self.assertIn(word, summary)

    def test_worker_uses_only_recorded_vision_and_requires_isolation(self):
        from expectrail.orchestrator import store
        from expectrail.recorded import RecordedObserver

        jobs = store.JobStore(self.temp / "jobs")
        def create(execution):
            from expectrail.orchestrator import request
            req = request.build(adapter="godot", head=self.head, base=self.base, game=sample.GAME,
                                routes=[sample.ROUTE], specs=sample.SPECS, execution_class=execution)
            return jobs.create(req)[0]["id"]
        with mock.patch.object(runner, "work") as work:
            with self.assertRaisesRegex(ValueError, "isolated"):
                ci_autofix.recorded_worker(jobs.root, create("diagnostic"))
            work.assert_not_called()
            job = create("isolated")
            ci_autofix.recorded_worker(jobs.root, job)
            args, kwargs = work.call_args
            self.assertEqual(args[1], job)
            self.assertIsInstance(args[2]["godot"]._visual, RecordedObserver)
            self.assertEqual(kwargs, {"own_group": True})

    def test_review_uploads_only_the_record(self):
        original = self.game.observer
        observers = iter((original(), None))
        self.game.observer = lambda: next(observers)
        self.step()
        out = self.temp / "repair-artifact"
        self.assertEqual([p.name for p in out.iterdir()], ["repair-run.json"])
        self.assertEqual(contracts.load_strict(out / "repair-run.json", "repair-run")["result"]["decision"], "needs-review")

    def test_a_fresh_verification_must_reproduce_the_reject(self):
        self.env["INTENT"] = "change"
        self.game.look_of = lambda game: "clean"
        with mock.patch("agents.fixer.run_fixer") as fixer, self.assertRaisesRegex(ValueError, "reject"):
            self.step()
        fixer.assert_not_called()

    def test_fixture_link_is_refused(self):
        (self.base / "linked.patch").symlink_to(self.base / FIX)
        with mock.patch.dict(self.env, FIXTURE="linked.patch"), self.assertRaisesRegex(ValueError, "links"):
            self.step()

    def test_refuses_invalid_limits_and_fixture_paths_before_repair(self):
        for key, value in (("ATTEMPTS", "0"), ("ATTEMPTS", "11"), ("ATTEMPTS", "2.5"),
                           ("FIXTURE", "../outside.patch"), ("FIXTURE", "/outside.patch"), ("FIXTURE", "")):
            with self.subTest(key=key, value=value), mock.patch.dict(self.env, {key: value}), \
                    mock.patch("agents.fixer.run_fixer") as fixer, self.assertRaises(ValueError):
                self.step()
            fixer.assert_not_called()
