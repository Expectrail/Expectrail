"""A second Godot project through the one verify path (#251).

``tests/projects/crate-run`` is a small Godot project that shares no file with the bundled game: a
crate (a node named ``Player``) on a flat tile floor, one route, and one draft spec nobody approved.

What these tests hold, with no game started (the gate tests' stand-in replay):
- the project, its route and its draft spec are what the verify path reads;
- the verify path replays the game its arguments name, and no module on it names the bundled game;
- a project whose only spec is a draft is needs-review, never accept.

With ``EXPECTRAIL_ENGINE_TESTS=required`` (the CI job that has Godot sets it), real Godot replays
through the one command, ``python3 -m expectrail.orchestrator verify``:
- the bundled game: accept;
- the second project, given by path: accept, and the evidence names that project's tree;
- the second project with its collision broken, compared with it as it is: reject;
- the second project with only its own draft spec: needs-review.

The approved spec that judges the second project in these tests is the bundled one
(``agents/specs/player-stays-above-ground.json``), copied unchanged, as ``tests/test_ci_gate.py`` and
the sample do. Nobody has approved a spec written for this project.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema

from expectrail.gate import verify as gate
from expectrail.orchestrator import engines, runner
from expectrail.orchestrator import request as req
from expectrail.orchestrator import sample as smp
from expectrail.orchestrator import store as st
from tests.test_ci_gate import FakeReplay

REPO = Path(__file__).resolve().parent.parent
PROJECT = REPO / "tests" / "projects" / "crate-run"
APPROVED = REPO / "agents" / "specs"
BUNDLED = "plat" + "former"   # spelt in two parts so this file can search for it
ENGINE_TESTS = os.environ.get("EXPECTRAIL_ENGINE_TESTS", "")
# What breaks the crate: it stops colliding, so it falls through the floor.
SOLID, BROKEN = "\tmove_and_slide()\n", "\tposition += velocity * delta\n"


def checkout(target: Path, *, specs: Path = APPROVED, broken: bool = False) -> Path:
    """A checkout of the second project: its game and routes, and a folder of specs."""
    shutil.copytree(PROJECT / "project", target / "project")
    shutil.copytree(PROJECT / "routes", target / "routes")
    shutil.copytree(specs, target / "specs")
    if broken:
        script = target / "project" / "player.gd"
        text = script.read_text(encoding="utf-8")
        if text.count(SOLID) != 1:
            raise AssertionError("player.gd no longer has the one line this test breaks")
        script.write_text(text.replace(SOLID, BROKEN), encoding="utf-8")
    return target


def _schema(name: str) -> dict:
    return json.loads((REPO / "contracts" / f"{name}.schema.json").read_text(encoding="utf-8"))


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="second-project-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)


class ProjectFilesTest(Case):
    def test_it_is_a_godot_project_with_a_route_and_a_draft_spec(self):
        self.assertTrue((PROJECT / "project" / "project.godot").is_file())
        settings = (PROJECT / "project" / "project.godot").read_text(encoding="utf-8")
        self.assertIn('run/main_scene="res://main.tscn"', settings)
        self.assertTrue((PROJECT / "project" / "main.tscn").is_file())
        route = json.loads((PROJECT / "routes" / "walk.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(_schema("route")).validate(route)
        specs = sorted((PROJECT / "specs").glob("*.json"))
        self.assertEqual([p.name for p in specs], ["crate-stays-above-floor.json"])
        spec = json.loads(specs[0].read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(_schema("test-spec")).validate(spec)

    def test_its_own_spec_is_a_draft_nobody_approved(self):
        for path in (PROJECT / "specs").glob("*.json"):
            self.assertNotIn("approval", json.loads(path.read_text(encoding="utf-8")), path.name)
        approved, drafts, problems = gate.load_specs(PROJECT / "specs", "specs")
        self.assertEqual((approved, drafts, problems), ([], 1, []))

    def test_it_shares_nothing_with_the_bundled_game(self):
        for path in PROJECT.rglob("*"):
            if path.is_file():
                self.assertFalse(path.is_symlink(), path)
                self.assertNotIn(BUNDLED, path.read_text(encoding="utf-8").lower(), path)
        actions = {event["action"] for event in
                   json.loads((PROJECT / "routes" / "walk.json").read_text(encoding="utf-8"))["events"]}
        settings = (PROJECT / "project" / "project.godot").read_text(encoding="utf-8")
        for action in actions:   # the route presses this project's own input actions
            self.assertIn(f"\n{action}={{", settings)


class VerifyPathTest(Case):
    """The orchestrator's godot engine and the gate, with the stand-in replay."""

    def run_job(self, head: Path, base: Path | None = None) -> tuple[dict, FakeReplay]:
        replay = FakeReplay()
        store = self.store = st.JobStore(self.tmp / "jobs")
        request = req.build(adapter="godot", head=head, base=base, game="project", routes=["routes/*.json"],
                            specs="specs")
        status, _ = store.create(request)
        return runner.work(store, status["id"], engines={"godot": engines.GodotGate(replay=replay)}), replay

    def test_the_game_replayed_is_the_one_the_arguments_name(self):
        head = checkout(self.tmp / "head")
        status, replay = self.run_job(head)
        self.assertEqual((status["phase"], status["decision"]), ("completed", "accept"), status)
        self.assertEqual([(route, frames) for route, _, frames in replay.calls], [("walk.json", True)])
        for _, game, _ in replay.calls:
            self.assertEqual(Path(game).resolve(), (head / "project").resolve())
            self.assertNotIn(BUNDLED, game)

    def test_the_base_replayed_is_the_base_the_arguments_name(self):
        head, base = checkout(self.tmp / "head"), checkout(self.tmp / "base")
        (head / "project" / "BUG").write_text("1", encoding="utf-8")   # the stand-in's fall-through
        status, replay = self.run_job(head, base)
        self.assertEqual((status["phase"], status["decision"]), ("completed", "reject"), status)
        self.assertEqual({Path(game).resolve() for _, game, _ in replay.calls},
                         {(head / "project").resolve(), (base / "project").resolve()})

    def test_a_project_with_only_a_draft_spec_is_needs_review_and_nothing_is_replayed(self):
        head = checkout(self.tmp / "head", specs=PROJECT / "specs")
        status, replay = self.run_job(head)
        self.assertEqual((status["phase"], status["decision"]), ("completed", "needs-review"), status)
        # The reason does not yet say that a draft is waiting for a person; the record's count does.
        self.assertEqual(status["reasons"], ["no checks ran"])
        found = json.loads((self.store.paths(status["id"]).output / "findings.json").read_text(encoding="utf-8"))
        self.assertEqual((found["drafts"], found["checks"]), (1, []))
        self.assertEqual(replay.calls, [])

    def test_no_module_on_the_verify_path_names_the_bundled_game(self):
        # The command's own file is left out: its usage text gives the bundled game as an example,
        # and `sample` is by definition about the bundled game.
        for name in ("expectrail/gate/verify.py", "expectrail/gate/record.py", "expectrail/orchestrator/engines.py",
                     "expectrail/orchestrator/request.py", "expectrail/orchestrator/runner.py",
                     "expectrail/orchestrator/store.py"):
            self.assertNotIn(BUNDLED, (REPO / name).read_text(encoding="utf-8"), name)

    def test_the_gates_replay_hands_the_harness_the_game_it_was_given(self):
        seen = {}

        def fake_run(route, out, **kwargs):
            seen.update(kwargs, route=route)
            out.mkdir(parents=True, exist_ok=True)
            (out / "trace.json").write_text(json.dumps({"rows": []}), encoding="utf-8")
            (out / "replay.json").write_text("{}", encoding="utf-8")
            return {"game": {"tree": "0" * 64}}
        head = checkout(self.tmp / "head")
        with unittest.mock.patch("harness.run.run", fake_run):
            gate.harness_replay(head / "routes" / "walk.json", head / "project", self.tmp / "out", False,
                                checkouts=(head,))
        self.assertEqual(seen["game"], head / "project")
        self.assertEqual(seen["within"], head.resolve())


@unittest.skipUnless(ENGINE_TESTS == "required", "set EXPECTRAIL_ENGINE_TESTS=required to replay with real Godot")
class RealGodotTest(Case):
    """Real replays through the one command. Each test starts Godot at least once."""

    def verify(self, head: Path, *, game: str, routes: str, specs: str, base: Path | None = None) -> tuple[int, dict]:
        command = [sys.executable, "-m", "expectrail.orchestrator", "--jobs-root", str(self.tmp / "jobs"), "verify",
                   "--head", str(head), "--game", game, "--routes", routes, "--specs", specs, "--json"]
        if base is not None:
            command += ["--base", str(base)]
        done = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=900)
        try:
            return done.returncode, json.loads(done.stdout)
        except ValueError:
            self.fail(f"verify printed no status (exit {done.returncode}): {done.stdout[-400:]} {done.stderr[-400:]}")

    def findings(self, status: dict) -> dict:
        store = st.JobStore(self.tmp / "jobs")
        return json.loads((store.paths(status["id"]).output / "findings.json").read_text(encoding="utf-8"))

    def test_the_bundled_game_is_accepted(self):
        head = smp.checkout(self.tmp / "bundled", bug=False)
        code, status = self.verify(head, game=smp.GAME, routes=smp.ROUTE, specs=smp.SPECS)
        self.assertEqual((code, status["phase"], status["decision"]), (0, "completed", "accept"), status)

    def test_the_second_project_is_accepted_and_the_evidence_names_its_tree(self):
        from harness.run import tree_digest

        head = checkout(self.tmp / "second")
        code, status = self.verify(head, game="project", routes="routes/walk.json", specs="specs")
        self.assertEqual((code, status["phase"], status["decision"]), (0, "completed", "accept"), status)
        found = self.findings(status)
        self.assertEqual(found["game"]["headTree"], tree_digest(head / "project", head))
        self.assertEqual([(check["spec"], check["route"], check["after"]) for check in found["checks"]],
                         [("player-stays-above-ground", "walk", "pass")])

    def test_the_second_project_broken_is_rejected_against_itself_as_it_is(self):
        base = checkout(self.tmp / "base")
        head = checkout(self.tmp / "head", broken=True)
        code, status = self.verify(head, base=base, game="project", routes="routes/walk.json", specs="specs")
        self.assertEqual((code, status["phase"], status["decision"]), (1, "completed", "reject"), status)
        found = self.findings(status)
        self.assertEqual([(check["before"], check["after"]) for check in found["checks"]], [("pass", "fail")])

    def test_the_second_project_with_only_its_draft_spec_is_needs_review(self):
        head = checkout(self.tmp / "draft", specs=PROJECT / "specs")
        code, status = self.verify(head, game="project", routes="routes/walk.json", specs="specs")
        self.assertEqual((code, status["phase"], status["decision"]), (2, "completed", "needs-review"), status)


if __name__ == "__main__":
    unittest.main()
