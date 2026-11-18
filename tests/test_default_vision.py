"""Default verdict entry points, using scripted answers only; no engine or model service."""
import contextlib
import io
import json
import os
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from expectrail import __version__
from expectrail.gate import record as rec
from expectrail.gate import verify as gv
from tests.test_two_observers import Case, repo


class DefaultVisionTest(Case):
    def test_api_without_an_observer_cannot_accept(self):
        head = repo(self.tmp / "head")
        doc = gv.run_gate(repo=head, game="game/platformer", routes=["routes/*.json"], specs="specs",
                          out=self.tmp / "out", work=self.tmp / "work", replay=self.game.replay)
        self.assertEqual(doc["decision"], "needs-review")
        self.assertEqual(doc["observers"]["rule"], "both")
        self.assertIn("visual observer", " ".join(doc["reasons"] + [f["reason"] for f in doc["findings"]]))

    def cli(self, look="clean", observer=None):
        head = repo(self.tmp / "head", look)
        real = gv.run_gate
        def run(**kw):
            return real(**kw, replay=self.game.replay)
        with mock.patch("expectrail.observers.FramesObserver", return_value=observer), \
                mock.patch.object(gv, "run_gate", side_effect=run), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("live call")) as network, \
                contextlib.redirect_stdout(io.StringIO()):
            code = gv.main(["--repo", str(head), "--game", "game/platformer", "--routes", "routes/*.json",
                            "--specs", "specs", "--out", str(self.tmp / "out")])
        network.assert_not_called()
        return code, rec.read_record(self.tmp / "out/findings.json")

    def test_cli_pass_needs_both_and_records_versions(self):
        code, doc = self.cli(observer=self.game.observer())
        self.assertEqual((code, doc["decision"]), (0, "accept"))
        self.assertTrue(self.game.asked)
        self.assertEqual(doc["observers"]["engine"], {"name": "expectrail.engine-record", "version": __version__})
        self.assertEqual(doc["observers"]["visual"]["version"], __version__)
        for row in doc["checks"]:
            self.assertEqual(row["observed"]["after"]["engine"], "pass")
            self.assertEqual(row["observed"]["after"]["visual"], "pass")
            self.assertRegex(row["observed"]["after"]["visualAnswerSha256"], r"^[0-9a-f]{64}$")
        bad = json.loads(json.dumps(doc))
        bad["observers"]["engine"]["version"] = ""
        with self.assertRaises(rec.RecordError):
            rec.check_record(bad)

    def test_cli_without_vision_is_review(self):
        code, doc = self.cli()
        self.assertEqual((code, doc["decision"]), (2, "needs-review"))
        self.assertIsNone(doc["observers"]["visual"])

    def test_cli_engine_failure_still_rejects_without_vision(self):
        code, doc = self.cli("BUG")
        self.assertEqual((code, doc["decision"]), (1, "reject"))

    def test_cli_stopped_record_keeps_both_rule(self):
        with mock.patch.object(gv, "run_gate", side_effect=gv.ConfigError("stand-in setup failure")), \
                contextlib.redirect_stdout(io.StringIO()):
            code = gv.main(["--repo", str(self.tmp), "--game", "missing", "--routes", "routes/*.json",
                            "--specs", "specs", "--out", str(self.tmp / "out")])
        doc = rec.read_record(self.tmp / "out/findings.json")
        self.assertEqual((code, doc["decision"], doc["observers"]["rule"]), (2, "needs-review", "both"))
        self.assertIn("stand-in setup failure", " ".join(doc["reasons"]))


class LegacyCommandTest(unittest.TestCase):
    def test_library_defaults_to_vision_and_labels_the_explicit_counterfactual(self):
        from agents import verifier
        from tests.test_agents import _request, REPO
        for provider, expected in (("", "needs-review"), ("trace", "accept")):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.dict(os.environ, {"EXPECTRAIL_OBS_PROVIDER": provider, "MODEL_API_KEY": "",
                                                 "EXPECTRAIL_SAM_USD_CAP": ""}), \
                    mock.patch("urllib.request.urlopen", side_effect=AssertionError("live call")) as network:
                doc = verifier.verify(_request(), REPO / "agents/fixtures/fix-collision-mask.patch", Path(tmp),
                                      skip_harness=True, observations_path=REPO / "agents/fixtures/obs-fixed.json")
                self.assertEqual(doc["decision"], expected)
                self.assertEqual(doc["observers"]["rule"], "engine-only" if provider == "trace" else "both")
                if provider == "trace":
                    self.assertIn("engine-only diagnostic", " ".join(doc["reasons"]))
                network.assert_not_called()

    def test_trace_fixture_cannot_clear_a_command_line_verification(self):
        from agents import verifier
        from expectrail.contracts import load
        from tests.test_agents import _request, REPO
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"EXPECTRAIL_OBS_PROVIDER": "trace", "MODEL_API_KEY": "",
                                             "EXPECTRAIL_SAM_USD_CAP": ""}), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("live call")) as network, \
                contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            (root / "request.json").write_text(json.dumps(_request()))
            code = verifier.main(["--request", str(root / "request.json"), "--candidate",
                                  str(REPO / "agents/fixtures/fix-collision-mask.patch"), "--out", str(root / "out"),
                                  "--skip-harness", "--observations", str(REPO / "agents/fixtures/obs-fixed.json")])
            doc = load(root / "out/verification.json", "verification")
            self.assertEqual((code, doc["decision"]), (1, "needs-review"))
            self.assertEqual(doc["observers"]["rule"], "both")
            self.assertEqual(doc["observers"]["visual"]["model"], "sam-3.1")
            self.assertTrue(any(c["result"] == "needs-review" for c in doc["checks"]))
            self.assertIn("visual observer", " ".join(doc["reasons"]))
            network.assert_not_called()


@unittest.skipUnless(shutil.which("patch"), "patch is not installed; install patch to construct public seed/fix trees")
class BenchmarkDispatchTest(unittest.TestCase):
    def test_all_fifteen_candidates_reach_the_shared_gate_and_old_summary_reader(self):
        from agents import judge_bench, verifier
        from harness.run import tree_digest

        seen = []
        observer = object()
        def gate(**kw):
            self.assertEqual((kw["rule"], kw["intent"]), ("both", "none"))
            self.assertIs(kw["visual"], observer)
            self.assertEqual(tree_digest(kw["base"] / "game"), tree_digest(judge_bench.GAME))
            self.assertEqual(len(list((kw["base"] / "specs").glob("*.json"))), 3)
            restored = tree_digest(kw["repo"] / "game") == tree_digest(judge_bench.GAME)
            seen.append(restored)
            return {"decision": "accept" if restored else "needs-review", "reasons": ["stand-in judge"]}

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("live call")) as network:
            rows = [verifier.judge_candidate(key, Path(tmp), gate=gate, visual=observer)
                    for key in judge_bench.cases()]
            self.assertEqual(len(rows), 15)
            self.assertEqual(sum(row["label"] == "good" for row in rows), 8)
            self.assertEqual(sum(row["label"] == "bad" for row in rows), 7)
            self.assertTrue(all("error" not in row for row in rows), rows)
            self.assertEqual(seen.count(True), 8)
            self.assertEqual(seen.count(False), 7)
            self.assertTrue(all(row["samImages"] == 0 for row in rows))
            self.assertEqual(judge_bench.summarize(Path(tmp))["judges"]["expectrailSam"]["good"], 8)
            network.assert_not_called()

    def test_an_interrupted_case_is_not_a_verdict(self):
        from agents import judge_bench, verifier
        with tempfile.TemporaryDirectory() as tmp:
            row = verifier.judge_candidate(next(iter(judge_bench.cases())), Path(tmp),
                                            gate=mock.Mock(side_effect=RuntimeError("stand-in crash")),
                                            visual=object())
            self.assertEqual(row["decisions"], {})
            self.assertIn("RuntimeError", row["error"])
