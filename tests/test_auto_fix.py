"""Verify stays rejected when an independently verified fixture fixes the game."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents import fixer
from expectrail import cli, contracts, viewer
from expectrail.orchestrator import engines, runner, sample, store
from tests.test_two_observers import Game

FIX = Path(__file__).resolve().parents[1] / "agents/fixtures/fix-collision-mask.patch"


class AutoFixTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.jobs = store.JobStore(self.root / "jobs")
        self.base = sample.checkout(self.root / "clean", bug=False)
        self.head = sample.checkout(self.root / "bug", bug=True)
        game = Game()
        player = Path("player/player.tscn")
        clean = (self.base / sample.GAME / player).read_bytes()
        game.look_of = lambda g: "clean" if (g / player).read_bytes() == clean else "BUG"
        self.engine = engines.GodotGate(replay=game.replay, visual=game.observer(), rule="both")

    def verify(self, *options, head=None):
        def launch(jobs, job, command=None):
            with contextlib.redirect_stdout(io.StringIO()):
                if command is None:
                    runner.work(jobs, job)
                else:
                    from expectrail import auto_fix
                    self.assertEqual(command[1:3], ["-m", "expectrail.auto_fix"])
                    auto_fix.worker(*command[3:])

        args = ["verify", "--head", str(head or self.head), "--base", str(self.base),
                "--game", sample.GAME, "--routes", sample.ROUTE, "--specs", sample.SPECS,
                "--jobs-root", str(self.jobs.root), "--json", *options]
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(engines, "ENGINES", {"godot": self.engine}), mock.patch.object(runner, "spawn", side_effect=launch), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(args)
        return code, json.loads(out.getvalue()) if out.getvalue() else err.getvalue()

    def test_accept_on_candidate_leaves_original_rejected_and_retry_reuses_record(self):
        opts = ("--auto-fix", "--auto-fix-fixture", str(FIX), "--idempotency-key", "repair")
        code, parent = self.verify(*opts)
        self.assertEqual(code, 1, parent)
        self.assertEqual(parent["decision"], "reject")
        block = parent["repair"]
        folder = self.jobs.paths(parent["id"]).root
        record = contracts.load_strict(folder / block["record"], "repair-run")
        self.assertEqual(record["budget"], {"attempts": 3, "usdCap": None})
        self.assertEqual(record["parent"]["job"], parent["id"])
        self.assertEqual(block["decision"], "accept")
        self.assertEqual(block["stopReason"], "accepted")
        self.assertEqual(block["review"], record["review"])
        self.assertEqual(self.jobs.status(record["result"]["job"])["decision"], "accept")
        self.assertNotIn("repair", self.jobs.status(record["result"]["job"]))
        page = viewer.write_job(self.jobs, parent["id"])
        self.assertIn(f'href="../{block["record"]}"', page.read_text())
        self.assertIn("Auto-fix: accept", page.read_text())
        import base64
        data = (folder / block["record"]).read_bytes()
        export = (page.parent / viewer.EXPORT_NAME).read_text()
        self.assertIn("data:application/json;base64," + base64.b64encode(data).decode(), export)
        from expectrail.orchestrator.cli import describe
        self.assertIn(record["review"], describe(parent))
        self.assertIn(block["record"], describe(parent))
        with mock.patch.object(fixer, "run_fixer") as call:
            self.assertEqual(self.verify(*opts), (1, parent))
            call.assert_not_called()
        self.assertEqual(self.verify(*opts, "--auto-fix-attempts", "2")[0], 5)

    def test_recorded_candidate_exhausts_attempts(self):
        patch = self.root / "still-buggy.patch"
        patch.write_text(FIX.read_text().replace("+collision_mask = 30", "+collision_mask = 12"))
        code, parent = self.verify("--auto-fix", "--auto-fix-recorded", str(patch), "--auto-fix-attempts", "2")
        self.assertEqual(code, 1, parent)
        block = parent["repair"]
        record = contracts.load_strict(self.jobs.paths(parent["id"]).root / block["record"], "repair-run")
        self.assertEqual(record["fixer"]["source"], "recorded")
        self.assertEqual((block["decision"], block["stopReason"]), ("needs-review", "attempts-exhausted"))
        self.assertNotIn("review", block)
        self.assertEqual([a["decision"] for a in record["attempts"]], ["reject", "reject"])

    def test_no_call_without_a_cli_cap_even_with_an_environment_cap(self):
        with mock.patch.dict(os.environ, EXPECTRAIL_MUSE_USD_CAP="9"), mock.patch.object(fixer, "run_fixer") as call:
            code, error = self.verify("--auto-fix")
            self.assertEqual(code, 5)
            self.assertIn("--auto-fix-usd-cap", error)
            self.assertFalse((self.jobs.root / "jobs").exists())
            call.assert_not_called()

    def test_accept_and_needs_review_never_start_repair(self):
        with mock.patch.object(fixer, "run_fixer") as call:
            for head, decision, code in [(self.base, "accept", 0), (self.root / "missing", "needs-review", 2)]:
                actual, doc = self.verify("--auto-fix", "--auto-fix-fixture", str(FIX), head=head)
                self.assertEqual(actual, code, doc)
                self.assertEqual(doc["decision"], decision)
                self.assertNotIn("repair", doc)
            call.assert_not_called()

    def test_default_reject_summary_and_viewer_say_how_to_opt_in(self):
        code, parent = self.verify()
        self.assertEqual(code, 1, parent)
        self.assertNotIn("repair", parent)
        from expectrail.orchestrator.cli import describe
        words = "Auto-fix is off; turn it on with --auto-fix"
        self.assertIn(words, describe(parent))
        self.assertIn(words, viewer.write_job(self.jobs, parent["id"]).read_text())

    def test_limits_refused_before_verification_and_lower_cap_wins(self):
        from expectrail import auto_fix
        with mock.patch.object(fixer, "run_fixer") as called:
            for opts in (("--auto-fix-attempts", "0"), ("--auto-fix-attempts", "11"),
                         ("--auto-fix-usd-cap", "nan"), ("--auto-fix-usd-cap", "inf"), ("--auto-fix-usd-cap", "-1")):
                with self.subTest(opts=opts):
                    self.assertEqual(self.verify("--auto-fix", *opts)[0], 5)
            self.assertEqual(self.verify("--auto-fix-attempts", "1")[0], 5)
            self.assertFalse((self.jobs.root / "jobs").exists())
            # The base predates #436. Substitute only its read-only cap lookup.
            import expectrail
            meter = mock.Mock()
            with mock.patch.object(expectrail, "spend", meter, create=True):
                meter.parse_cap.return_value = None
                self.assertEqual(auto_fix.live_cap(1), 1)
                meter.parse_cap.return_value = 2
                for cap, expected in [(0, 0), (1, 1), (2, 2), (3, 2)]:
                    config, data = auto_fix.configure(True, 10, cap)
                    self.assertEqual((config["usdCap"], config["attempts"], data), (expected, 10, None))
            called.assert_not_called()

    def test_detached_worker_survives_cli_exit_and_missing_game_gets_no_repair(self):
        import subprocess
        import sys
        args = [sys.executable, "-m", "expectrail.cli", "verify", "--jobs-root", str(self.jobs.root),
                "--head", str(self.root / "missing"), "--game", sample.GAME, "--routes", sample.ROUTE,
                "--specs", sample.SPECS, "--adapter", "absent", "--auto-fix", "--auto-fix-fixture", str(FIX),
                "--detach", "--json"]
        result = subprocess.run(args, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        job = json.loads(result.stdout)["id"]
        status = runner.wait(self.jobs, job)
        self.assertEqual(status["decision"], "needs-review")
        self.assertNotIn("repair", status)
        self.assertEqual(list(self.jobs.paths(job).root.glob("repair-*")), [])

    def test_changed_patch_or_dead_worker_keeps_reject_without_an_accept(self):
        from expectrail import auto_fix
        from expectrail.orchestrator import request
        import hashlib
        req = request.build(adapter="godot", head=self.head, base=self.base, game=sample.GAME,
                            routes=[sample.ROUTE], specs=sample.SPECS)
        req["autoFix"] = {"source": "fixture", "attempts": 1, "patchSha256": hashlib.sha256(FIX.read_bytes()).hexdigest()}
        with mock.patch.object(fixer, "run_fixer") as called, contextlib.redirect_stdout(io.StringIO()):
            job = self.jobs.create(req)[0]["id"]
            (self.jobs.paths(job).root / "auto-fix.patch").write_bytes(b"changed")
            with mock.patch.object(engines, "ENGINES", {"godot": self.engine}):
                auto_fix.worker(str(self.jobs.root), "30", job)
            status = self.jobs.status(job)
            self.assertEqual((status["decision"], status["repair"]["state"]), ("reject", "interrupted"))
            self.assertIn("changed", status["repair"]["detail"])
            job = self.jobs.create(req)[0]["id"]
            self.assertEqual(runner.work(self.jobs, job, {"godot": self.engine})["repair"]["state"], "running")
            with mock.patch.object(store, "alive", return_value=False):
                status = self.jobs.status(job)
            self.assertEqual(status["decision"], "reject")
            self.assertEqual(status["repair"]["state"], "interrupted")
            self.assertNotIn("record", status["repair"])
            called.assert_not_called()

    def test_app_reject_summary_links_only_the_owned_repair_and_shows_review(self):
        from expectrail import app
        from expectrail.orchestrator.store import UnknownJob
        local = app.App(self.jobs, runner.spawn)
        code, doc = self.verify("--auto-fix", "--auto-fix-fixture", str(FIX))
        self.assertEqual(code, 1)
        job = doc["id"]
        self.assertIsNone(local.status(job, past=True)["repairUrl"])
        with self.assertRaises(UnknownJob):
            local.repair_file(job)
        local.owned.add(job)
        status = local.status(job)
        self.assertIn("Auto-fix: accept", status["summary"])
        self.assertIn(doc["repair"]["review"], status["summary"])
        self.assertEqual(status["repairUrl"], f"/repairs/{job}/repair-run.json")
        self.assertEqual(json.loads(local.repair_file(job))["parent"]["job"], job)
        page = local.viewer_file(job, ["index.html"])
        self.assertIn(status["repairUrl"].encode(), page)
        self.assertIn(b"Auto-fix: accept", page)
        self.assertNotIn(b"Auto-fix is off", page)
        self.assertIn(b"data:application/json;base64,", local.viewer_file(job, [viewer.EXPORT_NAME]))
        from threading import Thread
        import http.client
        server = app.create_server(self.jobs)
        server.app.owned.add(job)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for path, headers, expected in ((status["repairUrl"], {}, 401),
                    (status["repairUrl"], {"X-Expectrail-Token": server.token}, 200),
                    (status["repairUrl"].replace("repair-run.json", "candidate.patch"),
                     {"X-Expectrail-Token": server.token}, 404)):
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                try:
                    conn.request("GET", path, headers=headers)
                    response = conn.getresponse()
                    self.assertEqual(response.status, expected)
                    if expected == 200:
                        self.assertEqual(json.loads(response.read())["parent"]["job"], job)
                finally:
                    conn.close()
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
        record = self.jobs.paths(job).root / doc["repair"]["record"]
        record.rename(record.with_suffix(".saved"))
        record.symlink_to(record.with_suffix(".saved"))
        with self.assertRaises(OSError):
            local.repair_file(job)

    def test_app_requires_explicit_cap_and_attempt_limit_before_launch(self):
        from expectrail import app
        local = app.App(self.jobs, mock.Mock())
        body = {"before": str(self.base), "after": str(self.head), "game": sample.GAME,
                "routes": sample.ROUTE, "specs": sample.SPECS, "autoFix": True}
        with self.assertRaisesRegex(ValueError, "cap"):
            local.create(body)
        with self.assertRaisesRegex(ValueError, "attempt"):
            local.create(dict(body, attempts=11, usdCap=1))
        local.start.assert_not_called()
        self.assertFalse((self.jobs.root / "jobs").exists())
