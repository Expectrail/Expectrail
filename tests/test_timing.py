"""Wall time per phase: the parts add up, a private route is never named, and timing never decides."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents import verifier
from agents.orchestrator import build_repair_request
from expectrail import capabilities as cap
from expectrail import timing
from expectrail.contracts import load
from harness import run as harness

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "contracts" / "examples" / "verify-timing.json"


class Clock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def step(self, seconds: float) -> None:
        self.now += seconds


class RecorderTest(unittest.TestCase):
    def test_the_four_phases_add_up_to_the_total(self):
        clock = Clock()
        with timing.recording(clock) as rec:
            clock.step(0.25)  # the verifier, before any replay
            with timing.arm("candidate"):
                timing.count_run()
                with timing.phase("import-cache"):
                    clock.step(0.5)
                with timing.phase("prepare"):
                    clock.step(1)
                with timing.phase("import"):
                    clock.step(2)
                with timing.phase("replay"):
                    clock.step(8)
                with timing.phase("record"):
                    clock.step(0.75)
            clock.step(1.5)  # judging
        doc = rec.document("a test")
        self.assertEqual(doc["totalSeconds"], 14.0)
        self.assertEqual(doc["phases"], {"import": 2.5, "replay": 8.0, "evaluate": 1.75, "other": 1.75})
        self.assertEqual(doc["arms"], [{"arm": "candidate", "harnessRuns": 1, "seconds": {
            "import-cache": 0.5, "prepare": 1.0, "import": 2.0, "replay": 8.0, "record": 0.75}}])
        self.assertEqual(timing.problems(doc), [])

    def test_a_retried_replay_is_two_runs_of_one_arm_and_arms_keep_their_order(self):
        clock = Clock()
        with timing.recording(clock) as rec:
            for label in ("reference", "held-out-1", "held-out-1", "clean"):
                with timing.arm(label):
                    timing.count_run()
                    with timing.phase("replay"):
                        clock.step(1)
        doc = rec.document("a test")
        self.assertEqual([(a["arm"], a["harnessRuns"], a["seconds"]["replay"]) for a in doc["arms"]],
                         [("reference", 1, 1.0), ("held-out-1", 2, 2.0), ("clean", 1, 1.0)])
        self.assertEqual(timing.problems(doc), [])

    def test_a_step_that_raises_is_still_timed(self):
        clock = Clock()
        with timing.recording(clock) as rec:
            with self.assertRaises(subprocess.CalledProcessError):
                with timing.arm("clean"), timing.phase("import"):
                    clock.step(3)
                    raise subprocess.CalledProcessError(-6, ["godot", "--import"])
        self.assertEqual(rec.document("a test")["phases"]["import"], 3.0)

    def test_a_phase_inside_a_phase_is_not_counted_twice(self):
        clock = Clock()
        with timing.recording(clock) as rec:
            with timing.phase("replay"):
                clock.step(1)
                with timing.phase("record"):
                    clock.step(1)
                clock.step(1)
        doc = rec.document("a test")
        self.assertEqual(doc["phases"], {"import": 0.0, "replay": 3.0, "evaluate": 0.0, "other": 0.0})
        self.assertEqual(timing.problems(doc), [])

    def test_with_no_recording_open_nothing_is_kept_and_nothing_fails(self):
        with timing.arm("candidate"), timing.phase("replay"):
            timing.count_run()
        with timing.recording() as rec:
            pass
        self.assertEqual(rec.events, [])
        self.assertEqual(rec.runs, {})

    def test_an_unknown_phase_name_is_an_error_even_with_no_recording(self):
        with self.assertRaises(timing.TimingError):
            with timing.phase("evaluate"):
                pass

    def test_a_recording_ends_with_its_block(self):
        with timing.recording() as outer:
            with timing.recording() as inner:
                with timing.phase("replay"):
                    pass
            with timing.phase("import"):
                pass
        self.assertEqual([e[1] for e in inner.events], ["replay"])
        self.assertEqual([e[1] for e in outer.events], ["import"])


class RecordTest(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def test_the_example_matches_the_schema_and_adds_up(self):
        self.assertEqual(timing.load(EXAMPLE)["format"], "expectrail.verify-timing/v1")

    def test_the_schema_itself_is_valid_draft_2020_12(self):
        import jsonschema

        jsonschema.Draft202012Validator.check_schema(json.loads(timing.SCHEMA.read_text(encoding="utf-8")))

    def test_phases_that_do_not_add_up_are_refused(self):
        self.doc["phases"]["evaluate"] += 1
        self.assertIn("the phases add up to", timing.problems(self.doc)[0])

    def test_arms_that_disagree_with_the_phases_are_refused(self):
        self.doc["arms"][1]["seconds"]["replay"] -= 2
        self.assertEqual(len(timing.problems(self.doc)), 1)
        self.assertIn("the arms' replay time", timing.problems(self.doc)[0])

    def test_an_arm_listed_twice_is_refused(self):
        self.doc["arms"].append(copy.deepcopy(self.doc["arms"][0]))
        self.assertIn("verify-timing: an arm is listed twice", timing.problems(self.doc))

    def test_an_arm_may_not_carry_a_route_name(self):
        for name in ("held-out-ledge-drop", "ledge-drop", "held-out-", "held-out/1", "candidate "):
            self.doc["arms"][0]["arm"] = name
            self.assertIn("verify-timing: arms/0/arm", timing.problems(self.doc)[0], name)
        self.doc["arms"][0]["arm"] = "held-out-12"
        self.assertEqual(timing.problems(self.doc), [])

    def test_unknown_keys_negative_seconds_and_another_clock_are_refused(self):
        for change in (lambda d: d.update(host="runner-7"), lambda d: d["phases"].update(replay=-1),
                       lambda d: d.update(clock="time.time"), lambda d: d["phases"].pop("other"),
                       lambda d: d["arms"][0]["seconds"].update(sam=1.0)):
            doc = copy.deepcopy(self.doc)
            change(doc)
            self.assertEqual(len(timing.problems(doc)), 1, doc)

    def test_load_refuses_a_file_that_is_not_a_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timing.json"
            for text in ("", "[]", "{\"format\": \"expectrail.verify-timing/v0\"}"):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(timing.TimingError):
                    timing.load(path)
            with self.assertRaises(timing.TimingError):
                timing.load(Path(tmp) / "missing.json")


class ShowTest(unittest.TestCase):
    def _show(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = timing.main(["show", *args])
        return code, out.getvalue(), err.getvalue()

    def test_show_prints_the_line_and_the_table(self):
        code, out, _ = self._show(str(EXAMPLE))
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("total 20.0 s: import 1.5, replay 15.0, evaluate 0.5, other 3.0 "
                                       "(by replay: reference 3.6, candidate 8.5, clean 7.4)\n"), out)
        self.assertIn("| candidate | 1 | 0.100 | 0.500 | 1.200 | 6.000 | 0.700 |", out)

    def test_notice_writes_one_notice_line_and_the_job_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "summary.md"
            with mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}):
                code, out, _ = self._show(str(EXAMPLE), "--notice")
            self.assertEqual(code, 0)
            self.assertEqual(out.count("\n"), 1)
            self.assertTrue(out.startswith("::notice title=Verification wall time::total 20.0 s: "), out)
            self.assertIn("| replay | 15.000 |", summary.read_text(encoding="utf-8"))

    def test_show_exits_1_on_a_record_that_does_not_add_up(self):
        doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        doc["totalSeconds"] = 99
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timing.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            code, out, err = self._show(str(path), "--notice")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("the phases add up to", err)


def _request() -> dict:
    return build_repair_request(
        request_id="rr-timing",
        spec=load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec"),
        verdict=load(REPO / "contracts" / "examples" / "verdict.json", "verdict"),
        route=load(REPO / "harness" / "routes" / "smoke.json", "route"),
        base_patch="bugs/physics-fall-through/v1.patch",
        key_frames=["frames/f00000008.png"],
    )


def _stand_in_harness(_route, harness_out, patches=None, **_kw):
    """What harness.run does to the clock, without Godot: the same phases, in the same order."""
    timing.count_run()
    for name in ("import-cache", "prepare", "import", "replay", "record"):
        with timing.phase(name):
            pass
    harness_out.mkdir(parents=True, exist_ok=True)
    (harness_out / "trace.json").write_text(json.dumps({
        "rows": [{"tick": 0, "player": [0, 0], "onFloor": True}], "physicsTicksPerSecond": 120}) + "\n")
    (harness_out / "replay.json").write_text("{}\n")


class VerifierTimingTest(unittest.TestCase):
    """verify() writes timing.json, and what it writes cannot change or lose the verdict."""

    def _verify(self, out: Path, **kw) -> dict:
        return verifier.verify(_request(), REPO / "agents" / "fixtures" / "fix-collision-mask.patch", out, **kw)

    def test_a_verification_on_saved_observations_has_no_harness_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._verify(Path(tmp), observations_path=REPO / "agents" / "fixtures" / "obs-fixed.json",
                               skip_harness=True)
            record = timing.load(Path(tmp) / "timing.json")
        self.assertEqual(record["decision"], doc["decision"])
        self.assertEqual(record["arms"], [])
        self.assertEqual(record["phases"]["evaluate"], record["totalSeconds"])
        self.assertEqual((record["phases"]["import"], record["phases"]["replay"]), (0.0, 0.0))
        self.assertIs(record["sam"], False)

    def test_an_early_reject_is_timed_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = _request()
            request["base"]["tree"] = "0" * 64
            doc = verifier.verify(request, REPO / "agents" / "fixtures" / "fix-collision-mask.patch", Path(tmp),
                                  skip_harness=True)
            self.assertEqual(doc["decision"], "reject")
            self.assertEqual(timing.load(Path(tmp) / "timing.json")["decision"], "reject")

    def test_each_replay_is_timed_under_its_arm(self):
        candidate_obs = load(REPO / "agents" / "fixtures" / "obs-fixed.json", "observations")
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(verifier._REFERENCE_SURFACES, clear=True), \
                mock.patch.dict(os.environ, {"EXPECTRAIL_HELDOUT_DIR": "", "EXPECTRAIL_OBS_PROVIDER": ""}), \
                mock.patch("agents.verifier.harness_run", side_effect=_stand_in_harness), \
                mock.patch("agents.verifier.from_trace", return_value=candidate_obs):
            self._verify(Path(tmp))
            record = timing.load(Path(tmp) / "timing.json")
        arms = {a["arm"]: a["harnessRuns"] for a in record["arms"]}
        self.assertEqual(list(arms), ["reference", "candidate", "clean"])
        self.assertEqual((arms["candidate"], arms["clean"]), (1, 1))
        self.assertGreaterEqual(arms["reference"], 1)

    def test_a_private_route_is_timed_under_its_position_never_its_name(self):
        spec = load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec")
        manifest = {"routes": [{"name": "zz-secret-ledge", "file": "zz-secret-ledge.json", "minDeltaX": 1.0},
                               {"name": "zz-secret-pit", "file": "zz-secret-pit.json", "minDeltaX": 1.0}]}
        calls = []

        def flaky(route, harness_out, patches=None, **kw):
            calls.append(Path(route).name)
            if calls.count(Path(route).name) == 1 and "pit" in Path(route).name:
                timing.count_run()
                raise OSError("godot died")
            _stand_in_harness(route, harness_out, patches, **kw)

        with tempfile.TemporaryDirectory() as tmp, timing.recording() as rec, \
                mock.patch("agents.verifier.harness_run", side_effect=flaky):
            verifier._run_held_out_routes(Path(tmp) / "set", manifest, spec, [], Path(tmp) / "out")
        doc = rec.document(verifier.TIMED)
        self.assertEqual([(a["arm"], a["harnessRuns"]) for a in doc["arms"]], [("held-out-1", 1), ("held-out-2", 2)])
        self.assertEqual(timing.problems(doc), [])
        self.assertNotIn("zz-secret", json.dumps(doc))

    def test_a_timing_that_cannot_be_written_leaves_the_verdict_and_says_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "timing.json").write_text("{\"stale\": true}\n")
            with mock.patch.object(timing, "write", side_effect=timing.TimingError("verify-timing: broken")):
                doc = self._verify(out, observations_path=REPO / "agents" / "fixtures" / "obs-fixed.json",
                                   skip_harness=True)
            self.assertEqual(json.loads((out / "verification.json").read_text())["decision"], doc["decision"])
            self.assertFalse((out / "timing.json").exists(), "an earlier run's numbers were left beside this verdict")
            self.assertIn("verify-timing: broken", (out / "timing-error.txt").read_text())

    def test_the_verdict_is_the_same_with_and_without_a_recording(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            kw = dict(observations_path=REPO / "agents" / "fixtures" / "obs-fixed.json", skip_harness=True)
            timed = self._verify(Path(a), **kw)
            plain = verifier._verify(_request(), REPO / "agents" / "fixtures" / "fix-collision-mask.patch", Path(b),
                                     **kw)
        self.assertEqual(timed, plain)


class HarnessPhasesTest(unittest.TestCase):
    """harness.run, with Godot replaced by a stand-in process, records its five steps once each."""

    def test_one_run_records_each_step_once_in_order(self):
        def fake_run(cmd, **_kw):
            if "--import" not in cmd:
                trace = next(a.split("=", 1)[1] for a in cmd if a.startswith("--trace="))
                Path(trace).write_text(json.dumps({"rows": [], "physicsTicksPerSecond": 120}) + "\n")
            return subprocess.CompletedProcess(cmd, 0, stdout="Godot Engine v4.7.2.stable\n", stderr="")

        with tempfile.TemporaryDirectory() as tmp, timing.recording() as rec, \
                mock.patch.object(harness, "ensure_import_cache", return_value=None), \
                mock.patch.object(harness.subprocess, "run", side_effect=fake_run):
            with timing.arm("candidate"):
                replay = harness.run(REPO / "harness" / "routes" / "smoke.json", Path(tmp) / "out",
                                     patches=[], godot=Path("/bin/true"))
        self.assertEqual(replay["format"], "expectrail.replay/v0")
        self.assertEqual([(arm, name) for arm, name, _ in rec.events],
                         [("candidate", n) for n in ("import-cache", "prepare", "import", "replay", "record")])
        self.assertEqual(rec.runs, {"candidate": 1})
        self.assertNotIn("timing", json.dumps(replay), "replay.json must stay the same for the same replay")

    def test_a_failed_godot_run_keeps_the_time_it_took(self):
        def failing(cmd, **_kw):
            return subprocess.CompletedProcess(cmd, 0 if "--import" in cmd else 1, stdout="", stderr="crash")

        with tempfile.TemporaryDirectory() as tmp, timing.recording() as rec, \
                mock.patch.object(harness, "ensure_import_cache", return_value=None), \
                mock.patch.object(harness.subprocess, "run", side_effect=failing):
            with self.assertRaises(SystemExit):
                harness.run(REPO / "harness" / "routes" / "smoke.json", Path(tmp) / "out", patches=[],
                            godot=Path("/bin/true"))
        self.assertEqual([name for _, name, _ in rec.events], ["import-cache", "prepare", "import", "replay"])


class LedgerPhasesTest(unittest.TestCase):
    """A wall time in the capability ledger may carry its phases, and they must add up to it."""

    def setUp(self) -> None:
        self.doc = copy.deepcopy(cap.load())
        self.entry = copy.deepcopy(self.doc["timings"][0])
        self.entry.update(seconds=20.0, resolutionSeconds=0.1, phasesFrom="timing.json in the run's artifact",
                          phases={"import": 1.5, "replay": 15.0, "evaluate": 0.5, "other": 3.0})
        self.doc["timings"].append(self.entry)

    def _schema_errors(self) -> list:
        import jsonschema

        schema = json.loads(cap.SCHEMA.read_text(encoding="utf-8"))
        return list(jsonschema.Draft202012Validator(schema).iter_errors(self.doc))

    def test_phases_that_add_up_are_accepted_and_rendered(self):
        self.assertEqual(self._schema_errors(), [])
        self.assertEqual(cap.row_problems(self.doc), [])
        self.assertIn("| import 1.5, replay 15, evaluate 0.5, other 3 (timing.json in the run's artifact) |",
                      cap.render(self.doc))

    def test_phases_that_do_not_add_up_to_the_whole_are_a_problem(self):
        self.entry["phases"]["replay"] = 10.0
        self.assertEqual(cap.row_problems(self.doc),
                         ["timings: run 42934646223: the phases add up to 15 s and the whole is 20 s"])

    def test_phases_need_all_four_parts_and_where_they_were_read(self):
        del self.entry["phasesFrom"]
        self.assertEqual(len(self._schema_errors()), 1)
        self.entry["phasesFrom"] = "the notice"
        del self.entry["phases"]["other"]
        self.assertEqual(len(self._schema_errors()), 1)

    def test_a_wall_time_without_phases_says_not_measured(self):
        self.assertIn("| 29, to the nearest 1 | not measured |", cap.render(cap.load()))


class WorkflowStepTest(unittest.TestCase):
    def test_ci_reports_the_timing_of_the_verification_it_just_ran(self):
        text = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        accept = text.index("python -m agents.gate1 --out runs/harness-accept")
        show = text.index("python -m expectrail.timing show runs/harness-accept/verify/timing.json --notice")
        self.assertLess(accept, show)
        self.assertLess(show, text.index("- name: Harness-backed freeze-player must reject"))


if __name__ == "__main__":
    unittest.main()
