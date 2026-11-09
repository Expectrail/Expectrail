"""The flaky-route detector: a failure counts only when it repeats; a flaky route is needs-review.

Every test uses a fake runner with harness.run's contract (it writes trace.json, replay.json and
godot.log and returns the replay document, or raises SystemExit), so no Godot is needed.
"""
import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import agents.heldout_bench as hb
from agents import stability
from agents.loop import one_run
from expectrail.contracts import ContractError, validate
from expectrail.discovery.run import REPRO_RUNS
from harness.run import REPO

GODOT_LOG = ("Godot Engine v4.7.2.stable.official.ed1daf0bf - https://godotengine.org\n"
             "OpenGL API 4.5 (Core Profile) Mesa 25.2.8-0ubuntu0.24.04.4 - Compatibility - "
             "Using Device: Mesa - llvmpipe (LLVM 20.1.2, 256 bits)\n")
EXAMPLES = REPO / "contracts" / "examples"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class FakeRunner:
    """harness.run.run's contract. ``script(route, n)`` gives the n-th replay of a route (from 1): a
    label (the frames and trace are a function of it, so equal labels make identical replays) or
    an exception to raise."""

    def __init__(self, script):
        self.script = script if callable(script) else (lambda _route, n, s=list(script): s[(n - 1) % len(s)])
        self.calls: list[tuple[Path, Path, list]] = []

    def __call__(self, route, out, patches=None, **_kw):
        route, out = Path(route), Path(out)
        n = sum(1 for r, _o, _p in self.calls if r == route) + 1
        self.calls.append((route, out, list(patches or [])))
        label = self.script(route, n)
        if isinstance(label, BaseException):
            raise label
        out.mkdir(parents=True, exist_ok=True)
        (out / "trace.json").write_text(json.dumps({"label": label, "rows": [{"tick": 1, "player": [0, 0]}]}))
        (out / "godot.log").write_text(GODOT_LOG)
        replay = {
            "format": "expectrail.replay/v0",
            "route": {"name": route.stem, "sha256": _sha(route.read_text())},
            "game": {"tree": "a" * 64, "patch": None, "patchSha256": None},
            "engine": {"name": "godot", "version": "4.7.2.stable.official.ed1daf0bf", "renderer": "opengl3",
                       "device": "Mesa - llvmpipe (LLVM 20.1.2, 256 bits)"},
            "capture": {"fps": 60, "physicsTicksPerSecond": 120, "frames": 4, "pattern": "frames/f%08d.png"},
            "frameSha256": [_sha(f"{label}-{i}") for i in range(4)],
            "trace": {"path": "trace.json", "sha256": _sha((out / "trace.json").read_text())},
        }
        (out / "replay.json").write_text(json.dumps(replay, indent=2) + "\n")
        return replay


def label_of(run_dir: Path) -> str:
    return json.loads((Path(run_dir) / "trace.json").read_text())["label"]


def judge_by_label(_replay, run_dir):
    """A replay labelled fall* fails; stand* passes; anything else cannot be decided."""
    label = label_of(run_dir)
    return "fail" if label.startswith("fall") else "pass" if label.startswith("stand") else "needs-review"


class StabilityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.route = self.root / "smoke.json"
        self.route.write_text(json.dumps({"format": "expectrail.route/v0", "name": "smoke", "ticks": 2,
                                          "seed": 1, "events": []}))
        self.cpuinfo = self.root / "cpuinfo"
        self.cpuinfo.write_text("processor\t: 0\nvendor_id\t: GenuineIntel\nmodel name\t: Test CPU 9000\n")

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, runner, judge=judge_by_label, **kw):
        kw.setdefault("cpuinfo", self.cpuinfo)
        return stability.check(runner, self.route, self.root / "out", judge=judge, **kw)

    def test_the_default_matches_discoverys_three_of_three_rule(self):
        self.assertEqual(stability.STABILITY_RUNS, REPRO_RUNS)
        self.assertEqual(stability.STABILITY_RUNS, 3)

    def test_a_stable_failure_stays_a_failure(self):
        runner = FakeRunner(["fall"])
        doc = self.check(runner)
        self.assertEqual((doc["status"], doc["result"]), ("stable-fail", "fail"))
        self.assertEqual(doc["counts"], {"fail": 3, "needs-review": 0, "pass": 0, "crashed": 0})
        self.assertEqual(len(runner.calls), 3)
        self.assertTrue(doc["replaysIdentical"])
        self.assertTrue(doc["resultsAgree"])
        self.assertEqual(doc["distinctReplays"], 1)
        self.assertEqual([r["framesDifferFromFirst"] for r in doc["replays"]], [0, 0, 0])
        self.assertEqual([r["dir"] for r in doc["replays"]], ["replay-01", "replay-02", "replay-03"])
        self.assertEqual(json.loads((self.root / "out" / "stability.json").read_text()), doc)

    def test_a_stable_pass_stays_a_pass(self):
        doc = self.check(FakeRunner(["stand"]))
        self.assertEqual((doc["status"], doc["result"]), ("stable-pass", "pass"))
        self.assertEqual(doc["counts"]["pass"], 3)

    def test_a_route_whose_output_alternates_is_flaky_and_needs_review(self):
        doc = self.check(FakeRunner(["fall", "stand"]))
        self.assertEqual((doc["status"], doc["result"]), ("flaky", "needs-review"))
        self.assertEqual(doc["counts"], {"fail": 2, "needs-review": 0, "pass": 1, "crashed": 0})
        self.assertEqual(doc["distinctReplays"], 2)
        self.assertFalse(doc["replaysIdentical"])
        self.assertFalse(doc["resultsAgree"])
        self.assertEqual([r["framesDifferFromFirst"] for r in doc["replays"]], [0, 4, 0])
        self.assertIn("not identical", doc["reason"])

    def test_replays_that_differ_but_all_fail_are_still_flaky(self):
        # Not "the same way": the frames and the trace change between replays.
        doc = self.check(FakeRunner(["fall", "fall-elsewhere"]))
        self.assertEqual(doc["counts"]["fail"], 3)
        self.assertTrue(doc["resultsAgree"])
        self.assertEqual((doc["status"], doc["result"]), ("flaky", "needs-review"))

    def test_identical_replays_judged_differently_are_flaky(self):
        answers = iter(["fail", "pass", "fail"])
        doc = self.check(FakeRunner(["fall"]), judge=lambda _r, _d: next(answers))
        self.assertTrue(doc["replaysIdentical"])
        self.assertFalse(doc["resultsAgree"])
        self.assertEqual((doc["status"], doc["result"]), ("flaky", "needs-review"))
        self.assertIn("judge's results differ", doc["reason"])

    def test_a_replay_that_does_not_run_makes_the_route_flaky(self):
        doc = self.check(FakeRunner(["fall", SystemExit("godot failed (1); see godot.log"), "fall"]))
        self.assertEqual((doc["status"], doc["result"]), ("flaky", "needs-review"))
        self.assertEqual(doc["counts"], {"fail": 2, "needs-review": 0, "pass": 0, "crashed": 1})
        self.assertEqual(doc["replays"][1]["error"], "SystemExit: godot failed (1); see godot.log")
        self.assertIsNone(doc["replays"][1]["frames"])

    def test_a_route_that_never_runs_is_undecided(self):
        doc = self.check(FakeRunner([SystemExit("godot failed")]))
        self.assertEqual((doc["status"], doc["result"]), ("undecided", "needs-review"))
        self.assertEqual(doc["counts"]["crashed"], 3)
        self.assertIsNone(doc["fingerprint"]["engine"])  # nothing ran, so no engine to name

    def test_a_judge_that_cannot_decide_is_undecided_never_a_pass(self):
        def broken(_r, _d):
            raise SystemExit("no clean-level reference for the ground line")

        doc = self.check(FakeRunner(["fall"]), judge=broken)
        self.assertEqual((doc["status"], doc["result"]), ("undecided", "needs-review"))
        self.assertEqual(doc["counts"]["needs-review"], 3)
        self.assertEqual(doc["counts"]["crashed"], 0)
        self.assertIn("no clean-level reference", doc["reason"])
        doc = self.check(FakeRunner(["fall"]), judge=lambda _r, _d: "looks fine")
        self.assertEqual(doc["result"], "needs-review")  # an unknown answer is never a pass

    def test_the_callers_first_replay_counts_as_run_one(self):
        runner = FakeRunner(["fall"])
        first_dir = self.root / "first"
        replay = runner(self.route, first_dir)
        doc = self.check(runner, first=(replay, first_dir, "fail"))
        self.assertEqual(len(runner.calls), 3)  # the caller's one, then two more
        self.assertEqual(doc["runs"], 3)
        self.assertEqual(doc["status"], "stable-fail")
        self.assertEqual([r["run"] for r in doc["replays"]], [1, 2, 3])
        self.assertEqual(doc["replays"][0]["dir"], "first")  # never an absolute path

    def test_a_check_keeps_its_result_only_when_it_held_on_every_identical_replay(self):
        flips = iter(["fail", "pass", "fail"])
        doc = self.check(FakeRunner(["fall"]), judge=lambda _r, _d: {"engine": "fail", "sam": next(flips)})
        self.assertEqual(doc["status"], "flaky")
        self.assertEqual(doc["checks"], {"engine": "fail", "sam": "needs-review"})
        doc = self.check(FakeRunner(["fall", "fall-elsewhere"]), judge=lambda _r, _d: {"engine": "fail"})
        self.assertEqual(doc["checks"], {"engine": "needs-review"})  # replays differ: nothing holds
        doc = self.check(FakeRunner(["fall"]), judge=lambda _r, _d: {"engine": "fail", "gameplay": "pass"})
        self.assertEqual(doc["status"], "stable-fail")
        self.assertEqual(doc["checks"], {"engine": "fail", "gameplay": "pass"})

    def test_the_fingerprint_names_the_cpu_mesa_and_engine(self):
        doc = self.check(FakeRunner(["fall"]))
        fp = doc["fingerprint"]
        self.assertEqual(fp["cpu"], "Test CPU 9000")
        self.assertEqual(fp["mesa"], "25.2.8-0ubuntu0.24.04.4")
        self.assertEqual(fp["engine"], "4.7.2.stable.official.ed1daf0bf")
        self.assertEqual(fp["device"], "Mesa - llvmpipe (LLVM 20.1.2, 256 bits)")
        self.assertRegex(fp["id"], r"^[0-9a-f]{16}$")
        other = self.root / "cpuinfo-arm"
        other.write_text("processor\t: 0\nHardware\t: Test Board\n")
        self.assertEqual(stability.cpu_model(other), "Test Board")
        self.assertNotEqual(stability.fingerprint({}, None, other)["id"], fp["id"])

    def test_a_headless_run_has_no_mesa_version(self):
        run_dir = self.root / "headless"
        run_dir.mkdir()
        (run_dir / "godot.log").write_text("Godot Engine v4.7.2.stable.official.ed1daf0bf\n")
        self.assertIsNone(stability.mesa_version(run_dir))
        self.assertIsNone(stability.mesa_version(self.root / "missing"))

    def test_the_fingerprint_stays_out_of_replay_json(self):
        doc = self.check(FakeRunner(["fall"]))
        for row in doc["replays"]:
            replay = json.loads((self.root / "out" / row["dir"] / "replay.json").read_text())
            self.assertNotIn("fingerprint", replay)
            self.assertNotIn("Test CPU 9000", json.dumps(replay))

    def test_baselines_are_hash_only_and_kept_per_fingerprint(self):
        baselines = self.root / "baselines"
        doc = self.check(FakeRunner(["fall"]), baselines=baselines)
        self.assertEqual(doc["baseline"]["status"], "missing")
        path = stability.record_baseline(doc, baselines)
        self.assertEqual(path.name, f"{doc['fingerprint']['id']}.json")
        saved = json.loads(path.read_text())
        self.assertEqual(saved["format"], stability.BASELINE_FORMAT)
        self.assertEqual(saved["fingerprint"], doc["fingerprint"])
        entry = saved["cases"][doc["case"]["key"]]
        self.assertEqual(entry["frameListSha256"], doc["replays"][0]["frameListSha256"])
        self.assertNotIn("smoke", path.read_text())  # digests only: no route name
        again = self.check(FakeRunner(["fall"]), baselines=baselines)
        self.assertEqual((again["baseline"]["status"], again["status"]), ("match", "stable-fail"))
        self.assertEqual(stability.record_baseline(again, baselines), path)  # a match changes nothing
        self.assertEqual(json.loads(path.read_text()), saved)
        # Another machine type gets its own file and does not see this one's entries.
        arm = self.root / "cpuinfo-arm"
        arm.write_text("Hardware\t: Test Board\n")
        elsewhere = self.check(FakeRunner(["fall-elsewhere"]), baselines=baselines, cpuinfo=arm)
        self.assertEqual((elsewhere["baseline"]["status"], elsewhere["status"]), ("missing", "stable-fail"))

    def test_identical_replays_that_differ_from_the_baseline_are_flaky(self):
        baselines = self.root / "baselines"
        stability.record_baseline(self.check(FakeRunner(["fall"]), baselines=baselines), baselines)
        doc = self.check(FakeRunner(["fall-elsewhere"]), baselines=baselines)
        self.assertTrue(doc["replaysIdentical"])
        self.assertEqual(doc["baseline"]["status"], "differs")
        self.assertEqual((doc["status"], doc["result"]), ("flaky", "needs-review"))
        with self.assertRaises(SystemExit):
            stability.record_baseline(doc, baselines)  # never overwritten

    def test_flaky_replays_are_never_recorded(self):
        doc = self.check(FakeRunner(["fall", "stand"]), baselines=self.root / "baselines")
        self.assertEqual(doc["baseline"]["status"], "not-compared")
        with self.assertRaises(SystemExit):
            stability.record_baseline(doc, self.root / "baselines")
        self.assertFalse((self.root / "baselines").exists())

    def test_reports_and_the_example_follow_the_schema(self):
        for script in (["fall"], ["fall", "stand"], [SystemExit("x")]):
            validate(self.check(FakeRunner(script)), "stability")
        example = json.loads((EXAMPLES / "stability.json").read_text())
        self.assertEqual(validate(example, "stability"), "stability")
        example["status"] = "mostly-fine"
        with self.assertRaises(ContractError):
            validate(example, "stability")
        overnight = json.loads((EXAMPLES / "overnight-summary.json").read_text())
        self.assertEqual(validate(overnight), "overnight-summary")
        overnight["results"][0]["stability"]["status"] = "mostly-fine"
        with self.assertRaises(ContractError):
            validate(overnight)

    def test_the_command_line_exits_0_only_for_a_stable_route(self):
        baselines = self.root / "baselines"
        for script, code in ((["fall"], 0), (["stand"], 0), (["fall", "stand"], 1)):
            with self.subTest(script=script), mock.patch("harness.run.run", FakeRunner(script)), \
                    mock.patch.object(stability, "ground_judge", return_value=judge_by_label), \
                    redirect_stdout(io.StringIO()) as out:
                got = stability.main(["--route", str(self.route), "--out", str(self.root / "cli"),
                                      "--baselines", str(baselines)])
            self.assertEqual(got, code)
            self.assertIn("machine ", out.getvalue())
        with mock.patch("harness.run.run", FakeRunner(["fall"])), \
                mock.patch.object(stability, "ground_judge", return_value=judge_by_label), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(stability.main(["--route", str(self.route), "--out", str(self.root / "cli"),
                                             "--baselines", str(baselines), "--record-baseline"]), 0)
        self.assertIn("recorded:", out.getvalue())
        self.assertEqual(len(list(baselines.glob("*.json"))), 1)


class LoopStabilityTest(unittest.TestCase):
    """agents.loop --stability: only a stable failure of the failing base goes on to the fixer."""

    def run_loop(self, tmp: str, script, runs: int = 3):
        runner = FakeRunner(script)
        with mock.patch("agents.loop.harness_run", runner), \
                mock.patch.object(stability, "ground_judge", return_value=judge_by_label):
            result = one_run(
                Path(tmp) / "loop", use_muse=False, offline_triage=True,
                observations=REPO / "agents" / "fixtures" / "obs-fixed.json",
                candidate_patch=REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                skip_harness=True, run_trust=False, stability_runs=runs,
            )
        return result, runner

    def test_a_flaky_failing_route_stops_the_run_as_needs_review_before_any_fix(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("agents.loop.run_fixer", side_effect=AssertionError("the fixer must not start")):
            result, runner = self.run_loop(tmp, ["fall", "stand"])
            self.assertEqual(result["decision"], "needs-review")
            self.assertEqual(result["stability"]["status"], "flaky")
            self.assertEqual(result["stability"]["counts"], {"fail": 2, "needs-review": 0, "pass": 1, "crashed": 0})
            self.assertIn("no fix was attempted", result["error"])
            self.assertEqual(result["attemptsConsumed"], 0)
            self.assertEqual(len(runner.calls), 3)
            self.assertTrue(all(c[2] and c[2][0].name.endswith(".patch") for c in runner.calls))  # the seed
            morning = (Path(tmp) / "loop" / "morning" / "morning-report.md").read_text()
            self.assertIn("`needs-review`", morning)
            self.assertIn("flaky", morning)
            self.assertTrue((Path(tmp) / "loop" / "stability" / "stability.json").is_file())

    def test_a_route_that_passes_every_replay_is_not_sent_to_the_fixer(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("agents.loop.run_fixer", side_effect=AssertionError("the fixer must not start")):
            result, _ = self.run_loop(tmp, ["stand"])
        self.assertEqual(result["decision"], "needs-review")
        self.assertEqual((result["stability"]["status"], result["stability"]["result"]), ("stable-pass", "pass"))

    def test_a_stable_failure_goes_on_to_the_fixer_and_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, runner = self.run_loop(tmp, ["fall"])
        self.assertEqual(result["decision"], "accept")
        self.assertEqual(result["stability"]["status"], "stable-fail")
        self.assertEqual(result["attemptsConsumed"], 1)
        self.assertEqual(len(runner.calls), 3)
        summary = {"format": "expectrail.overnight-summary/v0", "mode": {"mode": "offline"}, "runs": 1,
                   "accepted": 1, "verificationProvenance": "fixture",
                   "cost": {"modelCalls": 0, "costUsd": None, "costProvenance": "unmetered-offline"},
                   "timing": {"wallClockMs": 1.0}, "results": [json.loads(json.dumps(result, default=str))]}
        self.assertEqual(validate(summary), "overnight-summary")
        from agents.report import write_loop_rollup

        summary["results"][0]["morning"] = None  # the rollup copies an accepted run's frames; not under test
        with tempfile.TemporaryDirectory() as tmp:
            rollup = write_loop_rollup(Path(tmp), summary=summary).read_text()
        self.assertIn("stability=`stable-fail` (3 fail, 0 pass, 0 undecided, 0 did not run, of 3)", rollup)

    def test_off_by_default_the_loop_replays_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("agents.loop.harness_run", side_effect=AssertionError("no replay when off")):
            result = one_run(
                Path(tmp) / "loop", use_muse=False, offline_triage=True,
                observations=REPO / "agents" / "fixtures" / "obs-fixed.json",
                candidate_patch=REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                skip_harness=True, run_trust=False,
            )
            self.assertEqual(result["decision"], "accept")
            self.assertNotIn("stability", result)
            self.assertFalse((Path(tmp) / "loop" / "stability").exists())


class HeldOutBenchStabilityTest(unittest.TestCase):
    """agents.heldout_bench --stability: a check's failure counts only when it held on every replay."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "set"
        (root / "routes").mkdir(parents=True)
        (root / "bugs" / "fam").mkdir(parents=True)
        for name in ("one", "two"):
            (root / "routes" / f"{name}.json").write_text(json.dumps({"name": f"private-route-{name}"}))
        (root / "bugs" / "fam" / "v1.patch").write_text("")
        (root / "manifest.json").write_text(json.dumps({
            "format": "expectrail.held-out-set/v0",
            "routes": [{"name": "private-route-one", "file": "routes/one.json", "minDeltaX": 300},
                       {"name": "private-route-two", "file": "routes/two.json", "minDeltaX": 300}],
            "variants": [{"family": "fam", "id": "v1", "patch": "bugs/fam/v1.patch", "spec": "x"}],
        }))
        self.env = mock.patch.dict(os.environ, {"EXPECTRAIL_HELDOUT_DIR": str(root)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_bench(self, script, stability_runs):
        runner = FakeRunner(script)

        def judge_replay(_trace, _sha, run_dir, *_a):
            return {"engine": judge_by_label(None, run_dir), "gameplay": "pass"}

        with mock.patch.object(hb, "_render", runner), mock.patch.object(hb, "_judge_replay", judge_replay), \
                mock.patch.object(hb, "reference_surfaces", return_value=[[0, 0]]), \
                mock.patch.object(hb, "sam_on", return_value=False), \
                mock.patch.object(hb, "sam_specs", return_value=[]):
            doc = hb.bench("fam/v1", Path(self.tmp.name) / "out", stability_runs=stability_runs)
        return doc, runner

    @staticmethod
    def smoke_flaky_one_falls_two_stands(route, n):
        if route.stem == "smoke":
            return "fall" if n % 2 else "stand"
        return "fall" if route.stem == "one" else "stand"

    def test_a_flaky_route_is_needs_review_and_a_stable_failure_still_counts(self):
        doc, runner = self.run_bench(self.smoke_flaky_one_falls_two_stands, 3)
        per = {row["route"]: row for row in doc["perRoute"]}
        self.assertEqual(per["smoke"]["checks"], {"engine": "needs-review", "gameplay": "needs-review"})
        self.assertEqual(per["smoke"]["stability"]["status"], "flaky")
        self.assertEqual(per["smoke"]["stability"]["firstReplay"]["engine"], "fail")
        self.assertEqual(per["private-route-one"]["checks"], {"engine": "fail", "gameplay": "pass"})
        self.assertEqual(per["private-route-one"]["stability"]["status"], "stable-fail")
        self.assertNotIn("stability", per["private-route-two"])  # it passed: never replayed
        self.assertEqual(doc["checks"]["engine"], {"fail": 1, "needs-review": 1, "pass": 1})
        self.assertEqual(doc["caughtWithSamOff"], "yes")
        self.assertEqual(len(runner.calls), 7)  # smoke 3, one 3, two 1
        self.assertEqual(doc["stability"], {"runs": 3, "routesReplayed": 2, "stable-fail": 1, "stable-pass": 0,
                                            "flaky": 1, "undecided": 0})
        line = hb.annotation(doc)
        self.assertIn("::notice title=Bench stability fam/v1::2 routes with a failing check replayed until 3 "
                      "runs: 1 stable fail, 1 flaky, 0 undecided, 0 stable pass", line)
        self.assertNotIn("private-route", line)

    def test_a_catch_made_only_by_a_flaky_route_is_not_a_catch(self):
        doc, _ = self.run_bench(lambda route, n: ("fall" if n % 2 else "stand") if route.stem == "smoke" else "stand", 3)
        self.assertEqual(doc["caughtWithSamOff"], "needs-review")
        with mock.patch.object(hb, "bench", return_value=doc), redirect_stdout(io.StringIO()):
            self.assertEqual(hb.main(["--variant", "fam/v1", "--stability"]), 1)

    def test_off_by_default_nothing_is_replayed_and_the_output_is_unchanged(self):
        doc, runner = self.run_bench(self.smoke_flaky_one_falls_two_stands, 0)
        self.assertEqual(len(runner.calls), 3)
        self.assertNotIn("stability", doc)
        self.assertTrue(all("stability" not in row for row in doc["perRoute"]))
        self.assertEqual(doc["checks"]["engine"], {"fail": 2, "needs-review": 0, "pass": 1})
        self.assertNotIn("stability", hb.annotation(doc))


if __name__ == "__main__":
    unittest.main()
