"""expectrail.project/v1: the config, and the verify path reading it (#259).

No engine is started. A config that is present and wrong stops the run and names the field.
Sizes are not in the config: observations use a row's ``body`` when the harness logged one.
The bundled game has no config; that is deliberate and covered here.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import jsonschema

from agents.observations import FEET_OFFSET, PLAYER_H, PLAYER_HALF_W, from_trace_synthetic
from expectrail.contracts import ContractError, validate_v1
from expectrail.gate import verify as gate
from expectrail.project_config import (
    FILENAME, ProjectConfigError, find, harness_arguments, load, read_game,
)
from expectrail import route
from harness import run as hr
from harness import sandbox as box

REPO = Path(__file__).resolve().parent.parent
SCHEMA = REPO / "contracts" / "project.v1.schema.json"
EXAMPLE = REPO / "contracts" / "examples" / "project.json"
CRATE = REPO / "tests" / "projects" / "crate-run" / "project"
BUNDLED = REPO / "game" / "platformer"
FAKE = box.Tool("/usr/bin/bwrap", "0.9.0")


def _schema():
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _trace(body=None) -> dict:
    row = {"tick": 0, "player": [100.0, 200.0], "ground": 250.0, "onFloor": True,
           "view": [1, 0, 0, 1, 0, 0]}
    if body is not None:
        row["body"] = body
    return {"format": "expectrail.trace/v0", "physicsTicksPerSecond": 60, "rows": [row]}


class SchemaTest(unittest.TestCase):
    def test_the_example_and_the_crate_match_and_validate(self):
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        crate = json.loads((CRATE / FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(example, crate)
        jsonschema.Draft202012Validator(_schema()).validate(example)
        self.assertEqual(validate_v1(example, "project"), "project")
        self.assertIsNone(find(BUNDLED))

    def test_unknown_fields_sizes_and_ambiguous_bindings_are_refused(self):
        validator = jsonschema.Draft202012Validator(_schema())
        doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        for change in (
            lambda d: d.__setitem__("halfWidth", 20),
            lambda d: d["bindings"]["player"].__setitem__("halfWidth", 20),
            lambda d: d["bindings"]["player"].__setitem__("group", "players"),
            lambda d: d["bindings"]["player"].pop("node"),
            lambda d: d.__setitem__("providers", {"vision": "sk-live-secret"}),
        ):
            broken = json.loads(json.dumps(doc))
            change(broken)
            with self.subTest(broken=sorted(broken)[:3]), self.assertRaises(jsonschema.ValidationError):
                validator.validate(broken)


class ReaderTest(unittest.TestCase):
    def test_the_crate_loads_and_the_bundled_game_has_no_config(self):
        doc = load(CRATE / FILENAME, CRATE)
        self.assertEqual(read_game(CRATE), doc)
        self.assertIsNone(read_game(BUNDLED))
        self.assertEqual(doc["bindings"]["player"], {"node": "Player", "texture": "res://crate.svg"})
        self.assertNotIn("halfWidth", doc["bindings"]["player"])
        self.assertEqual(harness_arguments(doc), [
            '--bindings={"player":{"node":"Player","texture":"res://crate.svg"}}'])

    def test_a_present_config_that_is_wrong_names_the_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tscn").write_text("", encoding="utf-8")
            (root / "crate.svg").write_bytes(b"<svg xmlns='http://www.w3.org/2000/svg'/>")
            cases = {
                "unknown field 'sizes'": {"sizes": [32, 32]},
                'unknown field \'halfWidth\'': {"bindings": {"player": {
                    "node": "Player", "texture": "res://crate.svg", "halfWidth": 16}}},
                'both "node" and "group"': {"bindings": {"player": {
                    "node": "Player", "group": "players", "texture": "res://crate.svg"}}},
                "needs a \"node\" path or a \"group\"": {"bindings": {"player": {"texture": "res://crate.svg"}}},
                "leaves the project root": {"entryScene": "res://../main.tscn"},
                "never an inline secret": {"providers": {"vision": "sk-live-secret"}},
            }
            base = json.loads((CRATE / FILENAME).read_text(encoding="utf-8"))
            for needle, change in cases.items():
                doc = json.loads(json.dumps(base))
                doc.update(change)
                path = root / FILENAME
                path.write_text(json.dumps(doc), encoding="utf-8")
                with self.subTest(needle=needle), self.assertRaises(ProjectConfigError) as caught:
                    load(path, root)
                self.assertIn(needle, str(caught.exception))

    def test_input_map_uses_the_config_and_does_not_ignore_a_bad_one(self):
        actions, rate, fallback = route.input_map(CRATE)
        self.assertEqual((actions, rate, fallback), (["jump", "left", "right"], 60, False))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "project.godot").write_text("[input]\nshoot={}\n", encoding="utf-8")
            (root / FILENAME).write_text('{"format": "expectrail.project/v1", "nope": true}\n', encoding="utf-8")
            with self.assertRaises(route.RouteError) as caught:
                route.input_map(root)
            self.assertIn("unknown field 'nope'", str(caught.exception))


class BodyBoxTest(unittest.TestCase):
    def test_body_is_the_player_box_and_the_constants_remain_without_it(self):
        plain = from_trace_synthetic(_trace())
        box = plain["frames"][0]["objects"]["player"][0]["box"]
        feet = 200.0 + FEET_OFFSET
        self.assertEqual(box, [100.0 - PLAYER_HALF_W, feet - PLAYER_H, 100.0 + PLAYER_HALF_W, feet])
        body = [90.0, 170.0, 122.0, 202.0]
        used = from_trace_synthetic(_trace(body))
        self.assertEqual(used["frames"][0]["objects"]["player"][0]["box"], body)

    def test_the_verify_path_takes_the_crate_rate_and_refuses_a_bad_config(self):
        from harness.adapters import get

        self.assertEqual(gate.capture_rate(get("godot"), CRATE), 60)
        self.assertEqual(gate.capture_rate(get("godot"), BUNDLED), 60)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "project.godot").write_text("[application]\n", encoding="utf-8")
            (root / FILENAME).write_text("{", encoding="utf-8")
            with self.assertRaises(gate.ConfigError) as caught:
                gate.capture_rate(get("godot"), root)
            self.assertIn("not valid JSON", str(caught.exception))


class SandboxValuesTest(unittest.TestCase):
    """The bindings travel as arguments. A host path would not exist inside the sandbox."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="expectrail-project-config-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.calls = []
        env = mock.patch.dict(os.environ, {"EXPECTRAIL_GODOT_CACHE": str(self.tmp / "cache")})
        env.start()
        self.addCleanup(env.stop)

    def engine(self, tool, argv, *, timeout, game, out, inputs=None, engine=None, env=None):
        self.calls.append(list(argv))
        (Path(game) / ".godot" / "imported").mkdir(parents=True, exist_ok=True)
        if "--import" not in argv:
            (Path(out) / "trace.json").write_text('{"physicsTicksPerSecond": 60, "rows": []}', encoding="utf-8")
        return __import__("subprocess").CompletedProcess(argv, 0, "Godot Engine v4.7.stable\nUsing Device: fake\n", "")

    def test_the_sandbox_is_given_values_and_not_the_config_path(self):
        route_path = self.tmp / "route.json"
        route_path.write_text(json.dumps({"format": "expectrail.route/v0", "name": "t", "seed": 1, "ticks": 1,
                                          "events": []}), encoding="utf-8")
        godot = self.tmp / "godot"
        godot.write_bytes(b"not an engine")
        with mock.patch.object(box, "probe", return_value=(FAKE, None)), \
                mock.patch.object(box, "run", side_effect=self.engine), \
                mock.patch.object(hr.subprocess, "run", side_effect=AssertionError("started outside")):
            hr.run(route_path, self.tmp / "out", game=CRATE, godot=godot, sandbox="require", capture_frames=False)
        capture = self.calls[-1]
        blob = next(arg for arg in capture if arg.startswith("--bindings="))
        self.assertEqual(json.loads(blob[len("--bindings="):]),
                         {"player": {"node": "Player", "texture": "res://crate.svg"}})
        host = str((CRATE / FILENAME).resolve())
        for arg in capture:
            self.assertNotIn(host, arg)
            self.assertNotIn(str(self.tmp), arg)
        self.assertTrue((self.tmp / "out" / "work" / FILENAME).is_file())


class ContractKindTest(unittest.TestCase):
    def test_a_project_record_of_the_wrong_kind_is_refused(self):
        doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        doc["format"] = "expectrail.project/v0"
        with self.assertRaises(ContractError):
            validate_v1(doc, "project")


if __name__ == "__main__":
    unittest.main()
