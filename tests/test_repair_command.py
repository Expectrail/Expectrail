"""The real seeded bug and fixture patch, judged in fresh jobs with offline observers."""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents import fixer
from expectrail import cli, contracts
from expectrail.orchestrator import engines, request, runner, sample, store
from tests.test_two_observers import Game

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "agents/fixtures/fix-collision-mask.patch"


class RepairCommandTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.jobs = store.JobStore(self.tmp / "jobs")
        self.bug = sample.checkout(self.tmp / "bug", bug=True)
        self.base = sample.checkout(self.tmp / "base", bug=False)
        self.player = Path(sample.GAME) / "player/player.tscn"
        self.original = (self.bug / self.player).read_bytes()
        self.game = Game()
        clean = (self.base / self.player).read_bytes()
        self.game.look_of = lambda g: "clean" if (g / "player/player.tscn").read_bytes() == clean else "BUG"
        engine = engines.GodotGate(replay=self.game.replay, visual=self.game.observer())
        self.engines = {"godot": engine}
        req = request.build(adapter="godot", head=self.bug, base=self.base, game=sample.GAME,
                            routes=[sample.ROUTE], specs=sample.SPECS)
        self.parent = self.jobs.create(req)[0]["id"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.work(self.jobs, self.parent, self.engines)["decision"], "reject")

    def invoke(self, *args, fixture=FIX, job=None):
        # Substitute only worker transport. The real worker reads the saved child request and findings.
        def work(st, child):
            return runner.work(st, child, self.engines)
        out = io.StringIO()
        argv = ["repair", "--jobs-root", str(self.jobs.root), job or self.parent, *args]
        if fixture is not None:
            argv += ["--fixture", str(fixture)]
        with mock.patch.object(runner, "spawn", return_value=None), mock.patch.object(
                runner, "wait", side_effect=lambda st, child, proc: work(st, child)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(argv)
        return code, out.getvalue()

    def record(self):
        files = list(self.jobs.paths(self.parent).root.rglob("repair-run.json"))
        self.assertEqual(len(files), 1)
        return files[0], contracts.load_strict(files[0], "repair-run")

    def test_fixture_accepts_only_after_fresh_fix_verification(self):
        code, text = self.invoke()
        self.assertEqual(code, 0, text)
        path, doc = self.record()
        self.assertEqual(len(doc["attempts"]), 1)
        a = doc["attempts"][0]
        self.assertEqual(doc["result"], {"decision":"accept", "job":a["job"], "patch":a["patch"]})
        self.assertEqual((doc["stop"]["reason"], a["decision"]), ("accepted", "accept"))
        self.assertNotEqual(a["job"], self.parent)
        self.assertEqual(self.jobs.request(a["job"])["base"]["checkout"], str(self.bug))
        self.assertEqual((path.parent / a["patch"]).read_bytes(), FIX.read_bytes())
        self.assertEqual((self.bug / self.player).read_bytes(), self.original)
        self.assertEqual(doc["fixer"], {"source":"fixture", "sandboxed":False})
        self.assertIn(doc["review"], text)
        findings = json.loads((self.jobs.paths(a["job"]).output / "findings.json").read_text())
        self.assertGreater(findings["repair"]["demonstrated"], 0)

    def test_each_rejection_retries_from_original_and_gets_only_public_feedback(self):
        bad = self.tmp / "still-buggy.patch"
        bad.write_text(FIX.read_text().replace("+collision_mask = 30", "+collision_mask = 12"))
        with mock.patch.object(fixer, "run_fixer", wraps=fixer.run_fixer) as called:
            code, text = self.invoke("--attempts", "2", fixture=bad)
        self.assertEqual(code, 2, text)
        _, doc = self.record()
        self.assertEqual(doc["stop"]["reason"], "attempts-exhausted")
        self.assertEqual([a["decision"] for a in doc["attempts"]], ["reject","reject"])
        self.assertEqual(len({a["job"] for a in doc["attempts"]}), 2)
        self.assertIsNone(doc["result"]["patch"])
        first, second = called.call_args_list
        self.assertTrue(all(c.kwargs["require_sandbox"] and c.kwargs["allow_empty"] for c in (first,second)))
        self.assertEqual(set(first.args[0]["failing"][0]["spec"]), {"id","instruction"})
        self.assertIsNone(first.kwargs["prior_reject"])
        self.assertIn("smoke", str(second.kwargs["prior_reject"]))
        self.assertEqual((self.bug / self.player).read_bytes(), self.original)

    def test_no_visual_answer_stops_at_needs_review(self):
        self.engines["godot"] = engines.GodotGate(replay=self.game.replay, visual=None)
        code, text = self.invoke()
        self.assertEqual(code, 2, text)
        _, doc = self.record()
        self.assertEqual([a["decision"] for a in doc["attempts"]], ["needs-review"])
        self.assertEqual(doc["stop"]["reason"], "needs-review")

    def test_completed_accept_and_missing_checkout_are_refused(self):
        req = self.jobs.request(self.parent)
        req["head"] = req["base"]
        child = self.jobs.create(req)[0]["id"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.work(self.jobs, child, self.engines)["decision"], "accept")
        with mock.patch.object(fixer, "run_fixer") as called:
            self.assertEqual(self.invoke(job=child)[0], 5)
            shutil.rmtree(self.bug)
            code, text = self.invoke()
            self.assertEqual(code, 5)
            self.assertIn("the checkout changed since the job; verify again", text)
            called.assert_not_called()

    def test_game_embedded_checks_and_vision_recording_never_reach_fixer(self):
        for checkout in (self.base, self.bug):
            game = checkout / sample.GAME
            shutil.copytree(checkout / sample.SPECS, game / "policy")
            (game / "answers.json").write_text('{"format":"expectrail.vision-recording/v1"}')
        req = self.jobs.request(self.parent)
        req["project"]["specs"] = sample.GAME + "/policy"
        self.parent = self.jobs.create(req)[0]["id"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.work(self.jobs, self.parent, self.engines)["decision"], "reject")
        actual = fixer.run_fixer

        def inspect(request, out, **kwargs):
            game = kwargs["game"]
            self.assertFalse((game / "answers.json").exists())
            self.assertEqual(list((game / "policy").glob("*.json")), [])
            self.assertTrue(kwargs["provider_only"])
            self.assertNotIn("approval", str(request["failing"]))
            return actual(request, out, **kwargs)

        with mock.patch.object(fixer, "run_fixer", side_effect=inspect):
            code, text = self.invoke()
        self.assertEqual(code, 0, text)

    def test_a_fixer_without_a_patch_stops(self):
        with mock.patch.object(fixer, "run_fixer", return_value={"ok":False}):
            code, text = self.invoke()
        self.assertEqual(code, 2, text)
        _, doc = self.record()
        self.assertEqual(doc["stop"]["reason"], "fixer-failed")
        self.assertEqual([(a["job"], a["patch"]) for a in doc["attempts"]], [(None,None)])

    def test_refuses_unfinished_job_and_changed_checkout(self):
        pending = self.jobs.create(self.jobs.request(self.parent))[0]["id"]
        with mock.patch.object(fixer, "run_fixer") as called:
            code, text = self.invoke(job=pending)
            self.assertEqual(code, 5)
            self.assertIn("completed", text)
            (self.bug / self.player).write_text("changed")
            code, text = self.invoke()
            self.assertEqual(code, 5)
            self.assertIn("the checkout changed since the job; verify again", text)
            called.assert_not_called()

    def test_refuses_changed_policy_missing_live_cap_and_invalid_attempts(self):
        with mock.patch.dict(os.environ, {"EXPECTRAIL_MUSE_USD_CAP":""}), mock.patch.object(fixer, "run_fixer") as called:
            for n in ("0", "11"):
                self.assertEqual(self.invoke("--attempts", n)[0], 5)
            code, text = self.invoke(fixture=None)
            self.assertEqual(code, 5)
            self.assertIn("EXPECTRAIL_MUSE_USD_CAP", text)
            route = self.bug / sample.ROUTE
            route.write_text(route.read_text() + "\n")
            code, text = self.invoke()
            self.assertEqual(code, 5)
            self.assertIn("checks", text)
            called.assert_not_called()
