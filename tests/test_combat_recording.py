"""#444: bundled combat recording and the trusted CI reader, offline only."""
import contextlib
import copy
import io
import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest import mock

import yaml

from agents.sam_observations import MetaSamClient, SamError
from expectrail import recorded, runit
from expectrail.gate import record as rec, verify as gv
from tests.test_anchor_gate import Game
from tests.test_ci_gate import ctx
from tests.test_runit import Case, REPO
from tools import ci_bundle, ci_checks


class CombatRecordingTest(Case):
    def setUp(self):
        super().setUp()
        shutil.copyfile(REPO / runit.COMBAT_ROUTE, self.root / runit.COMBAT_ROUTE)
        self.path = self.root / "docs/run-it/vision/gate-combat.json"
        self.clean = self.path.with_name("clean.json")
        self.primary = json.loads((REPO / "contracts/examples/vision-recording.json").read_text())
        recorded.write_recording(self.clean, self.primary)

    def judge_combat(self, game, visual, name):
        with contextlib.redirect_stdout(io.StringIO()):
            return gv.run_gate(repo=self.root, base=self.root, game=runit.GATE_GAME, specs=runit.GATE_SPECS,
                               routes=[runit.COMBAT_ROUTE], out=self.tmp / name, work=self.tmp / (name + "-work"),
                               replay=game.replay, rule=rec.BOTH, visual=visual)

    def test_combat_gains_all_answers_and_anchor_prompts_without_a_live_fallback(self):
        game = Game()  # existing scripted model, including the player's body box
        client = MetaSamClient(transport=game.transport, retries=0, sleep=lambda _: None)
        originals = {str(p.relative_to(self.root)): p.read_bytes() for p in
                     (self.root / runit.COMBAT_ROUTE, self.root / runit.GATE_GAME / "project.godot",
                      self.root / runit.GATE_SPECS / "player-stays-above-ground.json")}
        with mock.patch("agents.sam_observations.default_client", side_effect=AssertionError("live model")):
            missing = self.judge_combat(game, ci_checks.recorded_observer(self.clean), "missing")
            self.assertEqual(missing["decision"], "needs-review")
            self.assertIn("not-recorded", json.dumps(missing))
            self.assertEqual(missing["checks"][0]["observed"]["after"]["visual"], "no-answer")
            self.quiet(runit.record, "gate-combat", self.path, run_id="stand-in-combat", client=client,
                       root=self.root, replay=game.replay, recorded_at="2026-11-15")
            doc = recorded.read_recording(self.path)
            self.assertEqual(doc["sample"], "gate-combat")
            self.assertEqual(runit.check_recording(self.path, sample_id="gate-combat", root=self.root), [])
            # Every captured frame of the actual 180-tick route, not the adapter's default stride.
            segments = [a for a in doc["answers"] if a["kind"] == "segment"]
            boxes = [a for a in doc["answers"] if a["kind"] == "segment-in"]
            self.assertEqual(len(segments), 90)
            self.assertEqual(len(boxes), 10)  # frames 0,10,...,80,89; duplicate sides share keys
            observer = ci_checks.recorded_observer(self.clean)
            with mock.patch.object(game, "transport", side_effect=AssertionError("model replayed live")):
                answered = self.judge_combat(game, observer, "answered")
            self.assertEqual(answered["decision"], "accept", answered["reasons"])
            self.assertEqual(answered["observers"]["visual"]["name"], "sam-recorded")
            self.assertEqual(answered["checks"][0]["observed"]["after"]["visual"], "pass")
            self.assertEqual(answered["anchor"]["routes"][0]["result"], "agree")
            self.assertEqual(observer.client.not_recorded, 0)
            self.assertGreater(observer.client.answered, 0)
            # Deleting the companion restores uncertainty; no stale answer cache can clear it.
            self.path.unlink()
            missing_again = self.judge_combat(game, ci_checks.recorded_observer(self.clean), "missing-again")
            self.assertEqual(missing_again["decision"], "needs-review")
            self.assertIn("not-recorded", json.dumps(missing_again))
        for name, raw in originals.items():
            self.assertEqual((self.root / name).read_bytes(), raw)

    def test_target_cannot_be_run_or_advertised_as_a_website_sample(self):
        manifest = runit.read_manifest(REPO)
        self.assertNotIn("gate-combat", [s["id"] for s in manifest["samples"]])
        with self.assertRaises(runit.RunItError):
            runit.find_sample(manifest, "gate-combat")
        with self.assertRaises(runit.RunItError):
            runit.run("gate-combat", self.tmp / "visitor", root=self.root, replay=self.game.replay)
        self.assertEqual(self.game.replays, [])

    def test_checker_accepts_gate_target_as_data_only_and_rejects_mislabelled_empty_data(self):
        doc = copy.deepcopy(self.primary)
        doc["sample"] = "gate-combat"
        recorded.write_recording(self.path, doc)
        with mock.patch.object(runit, "_record_combat", side_effect=AssertionError("executed game")), \
                mock.patch("agents.sam_observations.default_client", side_effect=AssertionError("model")):
            self.assertEqual(runit.check_recording(self.path, sample_id="gate-combat", root=self.root), [])
            self.assertIn("not 'clean'", runit.check_recording(self.path, sample_id="clean", root=self.root)[0])
            doc["answers"] = []
            recorded.write_recording(self.path, doc)
            self.assertEqual(runit.check_recording(self.path, sample_id="gate-combat", root=self.root),
                             ["the recording holds no answers"])
        doc["sample"] = "clean"
        recorded.write_recording(self.path, doc)
        with self.assertRaisesRegex(recorded.RecordingError, "not a gate-combat"):
            ci_checks.recorded_observer(self.clean)

    def test_recorder_uses_only_combat_ci_specs_every_frame_and_required_sandbox(self):
        client = mock.Mock(model="sam-3.1", provider="meta-model-api")
        with mock.patch.object(gv, "run_gate") as gate:
            runit.record("gate-combat", self.path, run_id="fixture", client=client, root=self.root, require_sandbox=True)
        call = gate.call_args.kwargs
        self.assertEqual(call["repo"], call["base"])
        self.assertNotEqual(call["repo"], self.root)
        self.assertEqual((call["game"], call["specs"], call["routes"]),
                         ("game/platformer", "agents/specs", ["harness/routes/combat.json"]))
        self.assertTrue(call["require_sandbox"])
        self.assertIs(call["replay"], gv.harness_replay)
        self.assertEqual(call["rule"], rec.BOTH)
        self.assertEqual(call["visual"]._every, 1)
        wf = yaml.safe_load((REPO / ".github/workflows/expectrail-comment.yml").read_text())
        policy = next(s["env"] for s in wf["jobs"]["judge"]["steps"] if s.get("id") == "judge")
        self.assertEqual((call["game"], call["specs"]), (policy["GAME"], policy["SPECS"]))
        self.assertIn(runit.COMBAT_ROUTE, policy["ROUTES"].splitlines())

    def test_cli_target_alias_keeps_spend_reporting(self):
        out = io.StringIO()
        with mock.patch.object(runit, "record", return_value=self.path) as record, contextlib.redirect_stdout(out):
            self.assertEqual(runit.main(["record", "--target", "gate-combat", "--out", str(self.path),
                                         "--run", "123", "--require-sandbox"]), 0)
        self.assertEqual(record.call_args.args[0], "gate-combat")
        self.assertTrue(record.call_args.kwargs["require_sandbox"])
        self.assertIn("spend: $0.0000", out.getvalue())

    def test_ci_judge_entrypoint_supplies_the_companion_from_the_base_directory(self):
        doc = dict(self.primary, sample="gate-combat")
        recorded.write_recording(self.path, doc)
        temp = self.tmp / "runner"
        temp.mkdir()
        (temp / "gate-state.json").write_text(json.dumps({"pr": {}, "intent": "none"}))
        event = temp / "event.json"
        event.write_text('{"workflow_run": {}}')
        def judge(policy, base, pr, intent, archive, out, visual):
            self.assertEqual([d["sample"] for d in visual.recordings], ["clean", "gate-combat"])
            self.assertEqual(visual.describe()["name"], "sam-recorded")
            out.mkdir()
        env = dict(GITHUB_EVENT_PATH=str(event), RUNNER_TEMP=str(temp), GITHUB_RUN_ID="999", RECORDING=str(self.clean),
                   GAME=runit.GATE_GAME, SPECS=runit.GATE_SPECS, ROUTES=runit.COMBAT_ROUTE)
        with mock.patch.dict(os.environ, env), mock.patch.object(ci_checks, "context", return_value=ctx()), \
                mock.patch.object(ci_bundle, "judge", side_effect=judge) as called, \
                mock.patch("agents.sam_observations.default_client", side_effect=AssertionError("model")):
            ci_checks.main("judge")
        called.assert_called_once()
        self.assertTrue((temp / ci_checks.REPORT).is_dir())

    def test_bank_preserves_primary_answers_and_never_matches_another_prompt_or_image(self):
        from tests.test_sam import png_bytes
        from agents.sam_observations import sha256_bytes
        png = self.tmp / "frame.png"
        png.write_bytes(png_bytes(20, 20, 1))
        first = copy.deepcopy(self.primary)
        first["answers"] = [dict(first["answers"][0], frameSha256=sha256_bytes(png))]
        second = copy.deepcopy(first)
        second["sample"] = "gate-combat"
        second["answers"][0]["detections"][0]["score"] = .5
        observer = recorded.RecordedBankObserver([first, second])
        self.assertEqual(observer.client.segment(png, "robot"), first["answers"][0]["detections"])
        with self.assertRaises(SamError) as missing:
            observer.client.segment(png, "another prompt")
        self.assertEqual(missing.exception.kind, "not-recorded")
        png.write_bytes(png_bytes(20, 20, 2))
        with self.assertRaises(SamError) as missing:
            observer.client.segment(png, "robot")
        self.assertEqual(missing.exception.kind, "not-recorded")
        second["model"] = dict(second["model"], name="different-model")
        with self.assertRaises(recorded.RecordingError):
            recorded.RecordedBankObserver([first, second])

    def test_missing_or_invalid_banks_do_not_fall_back_to_a_model(self):
        self.clean.unlink()
        with mock.patch("agents.sam_observations.default_client", side_effect=AssertionError("model")):
            self.assertIsNone(ci_checks.recorded_observer(self.clean))
            self.path.write_text("{")
            with self.assertRaises(recorded.RecordingError):
                ci_checks.recorded_observer(self.clean)

    def test_workflow_preflight_allowlist_runs_before_checkout_on_both_jobs(self):
        wf = yaml.safe_load((REPO / ".github/workflows/run-it-record.yml").read_text())
        inputs = wf.get("on", wf.get(True))["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["sam_usd_cap"]["default"], "1.00")
        for name, job in wf["jobs"].items():
            script = job["steps"][0]["run"]
            for target, success in (("gate-combat", True), ("clean", True), ("unlisted", False), ("../combat", False)):
                with self.subTest(job=name, target=target):
                    done = subprocess.run(["bash", "-e", "-c", script], env={**os.environ, "TARGET": target, "CAP": "1.00"},
                                          capture_output=True, text=True, timeout=10)
                    self.assertEqual(done.returncode == 0, success, done.stdout + done.stderr)

    def test_existing_sample_recordings_supply_clean_smoke_box_answers(self):
        # This reads only the public, shipped Run it recordings. It does not play their frames.
        folder = REPO / "docs/run-it/vision"
        primary = recorded.read_recording(folder / "clean.json")
        clean_frames = {a["frameSha256"] for a in primary["answers"]}
        self.assertFalse(any(a["kind"] == "segment-in" for a in primary["answers"]))
        observer = ci_checks.recorded_observer(folder / "clean.json")
        self.assertGreaterEqual({d["sample"] for d in observer.recordings},
                                {"clean", "fall-through-bug", "fall-through-repair"})
        boxes = [key for key in observer.client._answers if key[0] == "segment-in" and key[1] in clean_frames]
        self.assertEqual(len(boxes), 13)
        self.assertEqual(observer.recordings[0], primary)

    def test_record_and_propose_are_exactly_the_two_existing_authority_domains(self):
        wf = yaml.safe_load((REPO / ".github/workflows/run-it-record.yml").read_text())
        self.assertEqual(set(wf["jobs"]), {"record", "propose"})
        self.assertEqual(wf["permissions"], {})
        self.assertEqual(wf["jobs"]["record"]["permissions"], {"contents": "read"})
        self.assertEqual(wf["jobs"]["propose"]["permissions"], {"contents": "write"})
        self.assertEqual(wf["jobs"]["record"]["environment"], "main-only")
        self.assertNotIn("environment", wf["jobs"]["propose"])
        self.assertNotIn("secrets.", yaml.safe_dump(wf["jobs"]["propose"]))
