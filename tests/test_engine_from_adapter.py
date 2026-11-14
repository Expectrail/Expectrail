"""The verify path takes its engine from the adapter registry (#251).

`harness/adapters.py` says, for each engine, whether the verify path can run on it (`verify_run`),
how a project folder is recognised, which folders are the engine's own, and the capture rate. The
gate (`expectrail.gate.verify.run_gate`), its replay and the orchestrator's engines ask the
registry and name no engine themselves.

No live Godot and no model. The second engine here is a stand-in written the way a new engine
would be: one adapter, registered, nothing edited outside it. Its harness writes the position log
the gate reads (the recorded fixture traces the other gate tests use), so the real observations
code, the real evaluator and the real record reader judge it.
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail.gate import record as rec
from expectrail.gate import verify as gv
from expectrail.orchestrator import engines, runner
from expectrail.orchestrator import request as req
from expectrail.orchestrator import store as st
from harness import adapters
from harness import tree
from tests.coverage_replays import complete_trace
from tests.test_ci_gate import FIXTURES, ROUTES, SPEC, FakeReplay, make_repo

REPO = Path(__file__).resolve().parent.parent
NAME = "probe"
MARK = "project.probe"
OWN = "probecache"   # the folder the stand-in engine writes for itself


class Probe:
    """A stand-in engine: its harness and the adapter that names it."""

    def __init__(self):
        self.calls: list[dict] = []
        self.adapter = dataclasses.replace(
            adapters.GODOT, name=NAME, engine=NAME, run=self.plain_run, ignore=(OWN,), verify_run=self.verify_run,
            project_file=MARK, title="Probe", missing=None, capture_fps=60)

    def plain_run(self, route, out, patches=None, *, game=None, fps=None, capture_frames=True):
        raise AssertionError("the verify path asks for verify_run, never the plain run")

    def verify_run(self, route: Path, out: Path, *, game: Path, capture_frames: bool, sandbox=None, within=None) -> dict:
        self.calls.append({"route": Path(route).name, "game": Path(game), "frames": capture_frames,
                           "sandbox": sandbox, "within": within})
        if (Path(game) / "CRASH").exists():
            raise SystemExit("the probe engine stopped")
        name = "trace-fallthrough.json" if (Path(game) / "BUG").exists() else "trace-fixed.json"
        out.mkdir(parents=True, exist_ok=True)
        trace = complete_trace(json.loads((FIXTURES / name).read_text()), json.loads(route.read_text())["ticks"])
        (out / "trace.json").write_text(json.dumps(trace))
        if capture_frames:
            (out / "frames").mkdir(exist_ok=True)
            for n in range(40):
                (out / "frames" / f"f{n:08d}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + f"{name}:{n}".encode())
        document = {"game": {"tree": tree.digest(Path(game), within=within, skip=(OWN,))}, "isolation": None}
        (out / "replay.json").write_text(json.dumps(document), encoding="utf-8")
        return document


def probe_repo(root: Path, *, bug: bool = False) -> Path:
    """A checkout with a probe project in `app/`, the approved spec that ships and one route."""
    (root / "app").mkdir(parents=True)
    (root / "app" / MARK).write_text("probe\n", encoding="utf-8")
    if bug:
        (root / "app" / "BUG").write_text("1", encoding="utf-8")
    (root / "specs").mkdir()
    shutil.copy(SPEC, root / "specs" / SPEC.name)
    (root / "routes").mkdir()
    shutil.copy(ROUTES / "smoke.json", root / "routes" / "smoke.json")
    return root


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="engine-from-adapter-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.n = 0

    def register(self) -> Probe:
        probe = Probe()
        adapters.register(probe.adapter)
        self.addCleanup(adapters.unregister, NAME)
        return probe

    def gate(self, head: Path, base: Path | None = None, **kw) -> dict:
        self.n += 1
        with contextlib.redirect_stdout(io.StringIO()):
            return gv.run_gate(repo=head, game=kw.pop("game", "app"), routes=["routes/*.json"], specs="specs",
                               out=self.tmp / f"out{self.n}", work=self.tmp / f"work{self.n}", base=base, **kw)

    def job(self, head: Path, adapter: str, *, game: str = "app", base: Path | None = None, table=None) -> tuple[dict, st.JobStore]:
        store = st.JobStore(self.tmp / f"jobs{self.n}", lease_seconds=5)
        self.n += 1
        status, _created = store.create(req.build(adapter=adapter, head=head, base=base, game=game,
                                                  routes=["routes/*.json"], specs="specs"))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return runner.work(store, status["id"], engines=table), store


class RegistryTest(Case):
    """What the registry says about the verify path."""

    def test_godot_is_the_one_adapter_with_a_verify_path_today(self):
        self.assertEqual(adapters.verifying(), ("godot",))
        self.assertTrue(adapters.GODOT.can_verify())
        for name in ("web", "unity"):
            self.assertFalse(adapters.get(name).can_verify(), name)
            self.assertIsNone(adapters.get(name).verify_run, name)

    def test_a_project_folder_is_one_that_holds_the_adapters_file(self):
        folder = self.tmp / "game"
        folder.mkdir()
        self.assertFalse(adapters.GODOT.is_project(folder))
        (folder / "project.godot").mkdir()   # a folder with the name is not the file
        self.assertFalse(adapters.GODOT.is_project(folder))
        (folder / "project.godot").rmdir()
        (folder / "project.godot").write_text("[application]\n", encoding="utf-8")
        self.assertTrue(adapters.GODOT.is_project(folder))
        self.assertFalse(adapters.GODOT.is_project(folder / "project.godot"))
        self.assertFalse(adapters.GODOT.is_project(self.tmp / "missing"))

    def test_an_adapter_that_names_no_file_recognises_no_folder(self):
        folder = self.tmp / "site"
        folder.mkdir()
        (folder / "project.godot").write_text("", encoding="utf-8")
        self.assertIsNone(adapters.WEB.project_file)
        self.assertFalse(adapters.WEB.is_project(folder))

    def test_the_godot_verify_replay_is_the_harness_with_the_game_it_was_given(self):
        seen = {}

        def fake_run(route, out, **kwargs):
            seen.update(kwargs, route=route, out=out)
            return {"game": {"tree": "0" * 64}}
        with mock.patch("harness.run.run", fake_run):
            adapters.GODOT.verify_run(self.tmp / "r.json", self.tmp / "out", game=self.tmp / "g", capture_frames=False,
                                      sandbox="require", within=self.tmp)
        self.assertEqual(seen, {"route": self.tmp / "r.json", "out": self.tmp / "out", "game": self.tmp / "g",
                                "fps": None, "capture_frames": False, "sandbox": "require", "within": self.tmp})

    def test_the_godot_verify_replay_has_no_default_game(self):
        with mock.patch("harness.run.run", side_effect=AssertionError("nothing may be replayed")):
            with self.assertRaises(ValueError):
                adapters.GODOT.verify_run(self.tmp / "r.json", self.tmp / "out", game=None, capture_frames=False)
            with self.assertRaises(TypeError):   # and it cannot be left out
                adapters.GODOT.verify_run(self.tmp / "r.json", self.tmp / "out", capture_frames=False)

    def test_the_adapters_digest_takes_the_checkout_a_link_may_lead_into(self):
        checkout = make_repo(self.tmp / "head", routes=("smoke",))
        game = checkout / "game" / "platformer"
        (checkout / "shared").mkdir()
        (checkout / "shared" / "art.txt").write_text("art\n", encoding="utf-8")
        (game / "art").symlink_to(checkout / "shared", target_is_directory=True)
        from harness.run import tree_digest

        self.assertEqual(adapters.GODOT.tree_digest(game, checkout), tree_digest(game, checkout))
        self.assertEqual(gv.game_tree(game, checkout), tree_digest(game, checkout))
        self.assertEqual(req.tree_digest(game, checkout, "godot"), tree_digest(game, checkout))
        with self.assertRaises(tree.TreeProblem):   # without the checkout the link leaves the game
            adapters.GODOT.tree_digest(game)


class EnginesTest(Case):
    """The orchestrator's engines are the registry's adapters that have a verify path."""

    def test_there_is_an_engine_for_godot_and_for_nothing_else(self):
        self.assertEqual(list(engines.ENGINES), ["godot"])
        self.assertEqual(len(engines.ENGINES), 1)
        self.assertIsInstance(engines.ENGINES["godot"], engines.GodotGate)
        self.assertIs(engines.ENGINES["godot"], engines.ENGINES.get("godot"))
        for name in ("web", "unity", "nope", "", "Godot", None, 3):
            self.assertIsNone(engines.ENGINES.get(name), name)
            self.assertNotIn(name, engines.ENGINES)

    def test_a_registered_adapter_with_a_verify_path_has_an_engine_and_loses_it_when_removed(self):
        self.assertIsNone(engines.ENGINES.get(NAME))
        probe = Probe()
        adapters.register(probe.adapter)
        try:
            engine = engines.ENGINES[NAME]
            self.assertEqual((engine.name, engine._rule), (NAME, rec.BOTH))
            self.assertEqual(sorted(engines.ENGINES), ["godot", NAME])
        finally:
            adapters.unregister(NAME)
        self.assertIsNone(engines.ENGINES.get(NAME))
        self.assertEqual(list(engines.ENGINES), ["godot"])

    def test_an_engine_whose_adapter_was_removed_stops_the_job_and_runs_nothing(self):
        probe = Probe()
        adapters.register(probe.adapter)
        engine = engines.ENGINES[NAME]
        adapters.unregister(NAME)
        head = probe_repo(self.tmp / "head")
        status, _store = self.job(head, NAME, table={NAME: engine})
        self.assertEqual((status["phase"], status["decision"]), ("completed", "needs-review"))
        self.assertEqual([d["code"] for d in status["diagnostics"]], ["INPUT_INVALID"])
        self.assertIn(f"no adapter named '{NAME}'", status["diagnostics"][0]["detail"])
        self.assertEqual(probe.calls, [])

    def test_a_job_for_an_adapter_with_no_verify_path_is_needs_review_and_says_which_have_one(self):
        head = make_repo(self.tmp / "head", routes=("smoke",))
        for name, words in (("web", "the adapter 'web' has no verify path yet; those that have one: godot"),
                            ("unity", "the adapter 'unity' has no verify path yet; those that have one: godot"),
                            ("nope", "no adapter named 'nope'")):
            with self.subTest(adapter=name), mock.patch.object(gv, "run_gate", side_effect=AssertionError("ran")):
                status, _store = self.job(head, name, game="game/platformer")
                self.assertEqual((status["phase"], status["decision"]), ("completed", "needs-review"))
                self.assertEqual([d["code"] for d in status["diagnostics"]], ["INPUT_INVALID"])
                self.assertEqual(status["diagnostics"][0]["detail"], words)

    def test_the_godot_engine_asks_the_adapter_what_the_machine_lacks(self):
        godot = dataclasses.replace(adapters.GODOT, missing=lambda: ["no engine here. Fix: fetch it"])
        adapters.register(godot, replace=True)
        self.addCleanup(adapters.register, adapters.GODOT, replace=True)
        found = engines.GodotGate._tools()
        self.assertEqual([(d["code"], d["detail"]) for d in found], [("TOOL_MISSING", "no engine here. Fix: fetch it")])
        head = make_repo(self.tmp / "head", routes=("smoke",))
        with mock.patch.object(gv, "run_gate", side_effect=AssertionError("ran")):
            status, _store = self.job(head, "godot", game="game/platformer",
                                      table={"godot": engines.GodotGate(rule="engine-only")})
        self.assertEqual((status["decision"], [d["code"] for d in status["diagnostics"]]), ("needs-review", ["TOOL_MISSING"]))

    def test_the_adapters_list_for_godot_is_the_doctors(self):
        from expectrail import doctor

        lacking = [doctor._missing("godot", "Godot", "no Godot 4.7.2 was found", "run get_godot.sh", run=True),
                   doctor._ok("patch", "patch", "found")]
        with mock.patch.object(doctor, "for_run", return_value=lacking):
            self.assertEqual(adapters.GODOT.missing(), ["no Godot 4.7.2 was found. Fix: run get_godot.sh"])
        with mock.patch.object(doctor, "for_run", return_value=[]):
            self.assertEqual(adapters.GODOT.missing(), [])


class GateTest(Case):
    """run_gate on the adapter it is given."""

    def test_an_adapter_the_registry_does_not_hold_or_that_cannot_verify_stops_the_gate_before_any_replay(self):
        head = make_repo(self.tmp / "head", routes=("smoke",))
        for name, words in (("nope", "no adapter named 'nope'"), ("web", "has no verify path yet"),
                            ("unity", "has no verify path yet")):
            with self.subTest(adapter=name):
                replay = FakeReplay()
                with self.assertRaises(gv.ConfigError) as caught:
                    self.gate(head, game="game/platformer", adapter=name, replay=replay)
                self.assertIn(words, str(caught.exception))
                self.assertEqual(replay.calls, [])
                self.assertFalse((self.tmp / f"out{self.n}").exists())

    def test_the_gates_own_replay_refuses_an_adapter_that_cannot_verify(self):
        with self.assertRaises(gv.ConfigError):
            gv.harness_replay(self.tmp / "r.json", self.tmp / "g", self.tmp / "out", False, adapter="web")
        self.assertFalse((self.tmp / "out").exists())

    def test_godot_by_name_and_by_default_give_the_same_record(self):
        head = make_repo(self.tmp / "head", routes=("smoke",))
        plain = self.gate(head, game="game/platformer", replay=FakeReplay())
        named = self.gate(head, game="game/platformer", replay=FakeReplay(), adapter="godot")
        drop = lambda d: {k: v for k, v in d.items() if k != "createdAt"}   # noqa: E731
        self.assertEqual(drop(plain), drop(named))
        self.assertEqual((plain["decision"], plain["adapter"]), ("accept", "godot"))

    def test_a_second_engine_is_verified_through_its_own_harness(self):
        probe = self.register()
        head, base = probe_repo(self.tmp / "head"), probe_repo(self.tmp / "base")
        record = self.gate(head, base, adapter=NAME)
        self.assertEqual((record["decision"], record["adapter"]), ("accept", NAME))
        self.assertEqual([c["comparison"] for c in record["checks"]], ["PRESERVED"])
        # Every replay went to the adapter's verify_run, with the game and the checkout it belongs to.
        self.assertEqual([(c["game"], c["within"], c["frames"]) for c in probe.calls],
                         [((head / "app").resolve(), head.resolve(), True), ((base / "app").resolve(), base.resolve(), True)])
        rec.read_record(self.tmp / f"out{self.n}" / "findings.json")   # the reader takes the record

    def test_a_second_engines_bug_is_rejected_and_its_crash_is_not_a_pass(self):
        self.register()
        head, base = probe_repo(self.tmp / "head", bug=True), probe_repo(self.tmp / "base")
        record = self.gate(head, base, adapter=NAME)
        self.assertEqual((record["decision"], [c["comparison"] for c in record["checks"]]), ("reject", ["REGRESSION"]))
        crashed = probe_repo(self.tmp / "crashed")
        (crashed / "app" / "CRASH").write_text("1", encoding="utf-8")
        record = self.gate(crashed, adapter=NAME)
        self.assertEqual((record["decision"], [c["after"] for c in record["checks"]]), ("needs-review", ["replay-error"]))

    def test_the_engines_own_folders_are_the_adapters_and_not_godots(self):
        self.register()
        head = probe_repo(self.tmp / "head")
        first = self.gate(head, adapter=NAME)["game"]["headTree"]
        (head / "app" / OWN).mkdir()
        (head / "app" / OWN / "state").write_text("the engine's own\n", encoding="utf-8")
        self.assertEqual(self.gate(head, adapter=NAME)["game"]["headTree"], first)   # its cache is no part of the game
        (head / "app" / ".godot").mkdir()
        (head / "app" / ".godot" / "file").write_text("to this engine, a file of the game\n", encoding="utf-8")
        self.assertNotEqual(self.gate(head, adapter=NAME)["game"]["headTree"], first)

    def test_a_folder_of_another_engine_is_not_this_engines_project(self):
        self.register()
        godot = make_repo(self.tmp / "godot", routes=("smoke",))
        record = self.gate(godot, game="game/platformer", adapter=NAME)
        self.assertEqual(record["decision"], "needs-review")
        self.assertIn(f"no Probe project ({MARK}) at game/platformer", record["reasons"])
        record = self.gate(probe_repo(self.tmp / "probe"), adapter="godot", replay=FakeReplay())
        self.assertEqual(record["decision"], "needs-review")
        self.assertIn("no Godot project (project.godot) at app", record["reasons"])

    def test_a_replay_of_another_tree_than_the_record_names_is_not_used(self):
        probe = self.register()
        honest = probe.verify_run

        def other_tree(route, out, **kw):
            return dict(honest(route, out, **kw), game={"tree": "f" * 64})
        adapters.register(dataclasses.replace(probe.adapter, verify_run=other_tree), replace=True)
        record = self.gate(probe_repo(self.tmp / "head"), adapter=NAME)
        self.assertEqual((record["decision"], [c["after"] for c in record["checks"]]), ("needs-review", ["replay-error"]))

    def test_the_sandbox_that_is_required_is_asked_of_the_adapters_replay(self):
        probe = self.register()
        with mock.patch("harness.sandbox.probe", return_value=("bwrap", "")):
            self.gate(probe_repo(self.tmp / "head"), adapter=NAME, require_sandbox=True)
        self.assertEqual({c["sandbox"] for c in probe.calls}, {"require"})
        probe.calls.clear()
        self.gate(probe_repo(self.tmp / "again"), adapter=NAME)
        self.assertEqual({c["sandbox"] for c in probe.calls}, {None})

    def test_the_record_takes_an_adapters_name_and_nothing_that_is_not_one(self):
        self.register()
        record = self.gate(probe_repo(self.tmp / "head"), adapter=NAME)
        for name in ("godot", "probe", "unity-6"):
            rec.check_record(dict(record, adapter=name))
        for name in ("Godot", "", "godot harness", "<b>", "9lives", "a" * 33, None, 3, ["godot"]):
            with self.subTest(adapter=name), self.assertRaises(Exception):
                rec.check_record(dict(record, adapter=name))


class CommandLineTest(Case):
    """``python3 -m expectrail.gate.verify --adapter`` reaches the registry, and a run that stops
    records the adapter it asked for, never Godot in its place."""

    def main(self, head: Path, *extra: str) -> tuple[int, dict]:
        self.n += 1
        out = self.tmp / f"cli{self.n}"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = gv.main(["--repo", str(head), "--game", "app", "--routes", "routes/*.json", "--specs", "specs",
                            "--out", str(out), *extra])
        document = json.loads((out / "findings.json").read_text(encoding="utf-8"))
        rec.check_record(document)
        return code, document

    def test_the_command_verifies_on_the_adapter_it_is_given(self):
        probe = self.register()
        head, base = probe_repo(self.tmp / "head"), probe_repo(self.tmp / "base")
        code, document = self.main(head, "--adapter", NAME, "--base", str(base))
        self.assertEqual((document["decision"], document["adapter"], code), ("accept", NAME, gv.EXIT["accept"]))
        self.assertEqual(len(probe.calls), 2)

    def test_the_command_rejects_a_second_engines_bug(self):
        self.register()
        head, base = probe_repo(self.tmp / "head", bug=True), probe_repo(self.tmp / "base")
        code, document = self.main(head, "--adapter", NAME, "--base", str(base))
        self.assertEqual((document["decision"], document["adapter"], code), ("reject", NAME, gv.EXIT["reject"]))

    def test_an_adapter_with_no_verify_path_stops_and_the_record_names_it(self):
        head = probe_repo(self.tmp / "head")
        for name in ("web", "unity"):
            with self.subTest(adapter=name):
                code, document = self.main(head, "--adapter", name)
                self.assertEqual((document["decision"], document["adapter"]), ("needs-review", name))
                self.assertEqual(code, gv.EXIT["needs-review"])
                self.assertTrue(any("has no verify path yet" in r for r in document["reasons"]), document["reasons"])

    def test_a_name_the_registry_does_not_hold_is_recorded_as_unknown_and_not_as_godot(self):
        head = probe_repo(self.tmp / "head")
        for name in ("nope", "Godot", "godot\n", "x" * 60):
            with self.subTest(adapter=name):
                code, document = self.main(head, "--adapter", name)
                self.assertEqual((document["decision"], document["adapter"]), ("needs-review", "unknown"))

    def test_a_stopped_record_names_the_adapter_and_defaults_to_godot(self):
        probe = self.register()
        stop = lambda **kw: gv.stopped_record("x", pr=None, game="app", checks_from="head",  # noqa: E731
                                              expectrail_commit=None, **kw)
        self.assertEqual(stop()["adapter"], "godot")
        self.assertEqual(stop(adapter=NAME)["adapter"], NAME)
        self.assertEqual(stop(adapter=probe.adapter)["adapter"], NAME)
        self.assertEqual(stop(adapter="web")["adapter"], "web")
        for bad in ("nope", None, ["godot"], 3):
            with self.subTest(adapter=bad):
                self.assertEqual(stop(adapter=bad)["adapter"], "unknown")


class WindowTest(unittest.TestCase):
    """A spec's window is counted at the adapter's capture rate, or not at all."""

    SPEC = {"window": {"fromFrame": 0, "toFrame": 119}}

    def test_the_default_is_the_godot_adapters_rate(self):
        self.assertEqual(gv.CAPTURE_FPS, adapters.GODOT.capture_fps)
        trace = {"physicsTicksPerSecond": 120}
        self.assertEqual(gv.window_frames(self.SPEC, 240, trace), gv.window_frames(self.SPEC, 240, trace, 60))
        self.assertEqual(gv.window_frames(self.SPEC, 240, trace), list(range(120)))

    def test_another_rate_gives_another_count(self):
        self.assertEqual(gv.window_frames(self.SPEC, 100, {"physicsTicksPerSecond": 50}, 50), list(range(100)))
        self.assertEqual(gv.window_frames(self.SPEC, 240, {"physicsTicksPerSecond": 120}, 30), list(range(60)))

    def test_no_rate_is_cannot_tell_and_then_nothing_passes_under_both(self):
        trace = {"physicsTicksPerSecond": 120, "rows": [{}] * 240}
        for rate in (None, 0, -60, True, 59.5, "60"):
            with self.subTest(rate=rate):
                self.assertIsNone(gv.window_frames(self.SPEC, 240, trace, rate))
                run = {"trace": trace, "engineObservations": {"frames": [{"frame": i} for i in range(120)]}}
                self.assertEqual(gv.engine_gap(self.SPEC, run, 240, rate),
                                 "the gate cannot tell how many frames this route should have")
                self.assertEqual(gv.visual_gap(self.SPEC, {}, run, 240, rate),
                                 "the gate cannot tell how many frames this route should have")


class OrchestratorTest(Case):
    """A job on a second engine, start to finish, with the engines the registry gives."""

    def test_a_job_names_its_adapter_and_is_verified_on_it(self):
        probe = self.register()
        head, base = probe_repo(self.tmp / "head"), probe_repo(self.tmp / "base")
        status, store = self.job(head, NAME, base=base, table={NAME: engines.Gate(NAME, rule="engine-only")})
        self.assertEqual((status["phase"], status["decision"]), ("completed", "accept"), status)
        record = rec.read_record(store.paths(status["id"]).output / "findings.json")
        self.assertEqual(record["adapter"], NAME)
        self.assertEqual(status["inputs"]["headTree"], record["game"]["headTree"])
        self.assertEqual(len(probe.calls), 2)

    def test_the_jobs_tree_leaves_out_the_adapters_folders_as_the_gate_does(self):
        self.register()
        head = probe_repo(self.tmp / "head")
        (head / "app" / OWN).mkdir()
        (head / "app" / OWN / "state").write_text("the engine's own\n", encoding="utf-8")
        (head / "app" / ".godot").mkdir()
        (head / "app" / ".godot" / "file").write_text("a file of this game\n", encoding="utf-8")
        status, _store = self.job(head, NAME, table={NAME: engines.Gate(NAME, rule="engine-only")})
        # Had the job's tree and the gate's been taken by different lists, the worker would have
        # refused the result as a decision about another tree.
        self.assertEqual((status["phase"], status["decision"]), ("completed", "accept"), status)
        self.assertEqual(status["inputs"]["headTree"], tree.digest(head / "app", within=head, skip=(OWN,)))
        self.assertNotEqual(status["inputs"]["headTree"], tree.digest(head / "app", within=head, skip=tree.GODOT_SKIP))

    def test_a_job_on_the_second_engine_with_a_bug_is_rejected(self):
        self.register()
        status, _store = self.job(probe_repo(self.tmp / "head", bug=True), NAME, base=probe_repo(self.tmp / "base"),
                                  table={NAME: engines.Gate(NAME, rule="engine-only")})
        self.assertEqual((status["phase"], status["decision"]), ("completed", "reject"), status)

    def test_a_folder_that_is_not_the_adapters_project_stops_the_job(self):
        probe = self.register()
        status, _store = self.job(make_repo(self.tmp / "godot", routes=("smoke",)), NAME, game="game/platformer")
        self.assertEqual((status["decision"], [d["code"] for d in status["diagnostics"]]), ("needs-review", ["INPUT_INVALID"]))
        self.assertIn("no Probe project at game/platformer in the head checkout", status["diagnostics"][0]["detail"])
        self.assertEqual(probe.calls, [])

    def test_a_tree_for_an_adapter_the_registry_does_not_hold_covers_every_file(self):
        self.assertEqual(req.engine_folders("godot"), tree.GODOT_SKIP)
        self.assertEqual(req.engine_folders(None), tree.GODOT_SKIP)
        self.assertEqual(req.engine_folders("unity"), adapters.UNITY_IGNORE)
        self.assertEqual(req.engine_folders("nope"), ())


class NoEngineNamedTest(unittest.TestCase):
    """The verify path's own files name no engine's project file and no engine's harness."""

    def test_the_gate_and_the_engines_do_not_name_godots_project_file_or_runner(self):
        for name in ("expectrail/gate/verify.py", "expectrail/orchestrator/engines.py",
                     "expectrail/orchestrator/runner.py"):
            text = (REPO / name).read_text(encoding="utf-8")
            for word in ("project.godot", "from harness.run import", "from harness import run"):
                self.assertNotIn(word, text, f"{name} names {word}")


if __name__ == "__main__":
    unittest.main()
