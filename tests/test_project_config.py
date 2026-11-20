"""expectrail.project/v1: the config, and the verify path reading it (#259).

No engine is started. A config that is present and wrong stops the run and names the field.
Sizes are not in the config. A row's ``body`` gives the player's width and height; the bottom
of the box stays at the feet, so a sunk sprite is still below the ground. The bundled game has
no config; that is deliberate and covered here.
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
from expectrail.contracts import ContractError, load as load_spec, validate_v1
from expectrail.evaluator import evaluate
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
        # The bundled game carries its config beside project.godot (Sean, November 19, 2026; #259).
        bundled = json.loads(find(BUNDLED).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(_schema()).validate(bundled)

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
    def test_the_crate_and_the_bundled_game_load_their_configs(self):
        doc = load(CRATE / FILENAME, CRATE)
        self.assertEqual(read_game(CRATE), doc)
        self.assertEqual(read_game(BUNDLED), load(BUNDLED / FILENAME, BUNDLED))
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
    def test_body_gives_the_size_and_the_feet_stay_the_bottom(self):
        plain = from_trace_synthetic(_trace())
        box = plain["frames"][0]["objects"]["player"][0]["box"]
        feet = 200.0 + FEET_OFFSET
        self.assertEqual(box, [100.0 - PLAYER_HALF_W, feet - PLAYER_H, 100.0 + PLAYER_HALF_W, feet])
        body = [90.0, 170.0, 122.0, 202.0]
        used = from_trace_synthetic(_trace(body))["frames"][0]["objects"]["player"][0]["box"]
        height = body[3] - body[1]
        self.assertEqual(used, [body[0], feet - height, body[2], feet])
        self.assertNotEqual(used[3], body[3])

    def test_a_sunk_collision_fails_the_ground_check_and_the_clean_game_passes(self):
        # The bundled robot's collision is 42.5 by 54.5 and its bottom is FEET_OFFSET below the
        # origin (tests/test_body_box.py). bugs/sinking/v1.patch lifts that collision 26 px, so the
        # body rests on the ground while the origin, and the feet, are 26 px lower. The ground
        # check allows 20 px. sinking v2 moves only the sprite, so this trace is unchanged.
        spec = load_spec(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec")
        half_w, height, ground = 21.25, 54.5, 213.25

        def trace(origin_y: float, body_bottom: float) -> dict:
            # Four frames: the spec's coverage minimum is two, and one frame is needs-review.
            rows = []
            for tick in range(4):
                rows.append({
                    "tick": tick, "player": [100.0, origin_y], "ground": ground, "onFloor": True,
                    "view": [1, 0, 0, 1, 0, 0],
                    "body": [100.0 - half_w, body_bottom - height, 100.0 + half_w, body_bottom]})
            return {"format": "expectrail.trace/v0", "physicsTicksPerSecond": 60, "rows": rows}

        clean = trace(ground - FEET_OFFSET, ground)
        sunk = trace(ground - (FEET_OFFSET - 26.0), ground)
        self.assertEqual(evaluate(spec, from_trace_synthetic(clean))["result"], "pass")
        self.assertEqual(evaluate(spec, from_trace_synthetic(sunk))["result"], "fail")
        sunk_box = from_trace_synthetic(sunk)["frames"][0]["objects"]["player"][0]["box"]
        self.assertEqual(sunk_box[0], 100.0 - half_w)
        self.assertAlmostEqual(sunk_box[2] - sunk_box[0], half_w * 2)
        self.assertAlmostEqual(sunk_box[3] - sunk_box[1], height)
        self.assertAlmostEqual(sunk_box[3] - ground, 26.0)

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
