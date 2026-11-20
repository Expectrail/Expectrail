"""Runtime discovery for `expectrail init --runtime` and `inspect --runtime` (#260).

The record and its reader are tested without an engine. ``RealEngineTest`` starts Godot headless on
copies of Crate Run and the bundled game; it skips where Godot is not installed, and CI sets
EXPECTRAIL_ENGINE_TESTS=required so it cannot skip there.
"""
import copy
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail import cli, contracts, onboarding
from expectrail import runtime_scan as rs
from tests import cli_capture

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "contracts" / "examples" / "runtime-scan.v1.json"
CRATE = ROOT / "tests" / "projects" / "crate-run" / "project"


def raw(nodes, **over):
    doc = {"format": rs.RAW_FORMAT, "ticks": 30, "scene": "res://main.tscn", "nodes": nodes, "truncated": False}
    doc.update(over)
    return json.dumps(doc).encode()


def body(path, **over):
    return {"path": path, "kind": "body", "type": "CharacterBody2D", "className": "", "groups": [], "visible": True, **over}


def sprite(path, images=(), unsaved=0, kind="sprite", atlas=(), **over):
    return {"path": path, "kind": kind, "type": {"sprite": "Sprite2D", "polygon": "Polygon2D",
                                                   "animatedSprite": "AnimatedSprite2D"}[kind],
            "className": "", "groups": [], "visible": True, "images": list(images), "atlasImages": list(atlas), "unsavedImages": unsaved, **over}


def layer(path, cells=10, collides=True):
    return {"path": path, "kind": "tileLayer", "type": "TileMapLayer", "className": "", "groups": [],
            "visible": True, "cells": cells, "collides": collides}


def record(nodes):
    doc = json.loads(EXAMPLE.read_text())
    doc["nodes"] = rs.read_raw(raw(nodes), 30)["nodes"]
    return doc


def static(players=("Player",), textures=(), problems=None):
    if problems is None:
        problems = ([] if textures else ["Player: no saved sprite texture found.",
                                         "Supply one image from the game as a res:// path in bindings.player.texture."])
    return {"entryScene": "res://main.tscn", "scenes": ["res://main.tscn"], "players": list(players),
            "textures": list(textures), "unresolvedBindings": list(problems), "cameras": [], "groundLayers": [],
            "platformBodies": [], "otherCharacters": [], "actions": ["jump", "left", "right"],
            "builtInActions": False, "physicsTicksPerSecond": 60, "viewport": [640, 360]}


class RecordTest(unittest.TestCase):
    def test_the_example_is_a_registered_v1_record_and_reads_cleanly(self):
        self.assertIn(rs.FORMAT, contracts.V1_FORMATS)
        doc = contracts.strict_loads(EXAMPLE.read_text())
        self.assertEqual(rs.problems(doc), [])
        self.assertIn("Floor", [n["path"] for n in doc["nodes"]])

    def test_a_field_on_the_wrong_kind_is_refused_by_the_schema(self):
        doc = json.loads(EXAMPLE.read_text())
        polygon = next(n for n in doc["nodes"] if n["kind"] == "polygon")
        polygon["cells"] = 3
        self.assertTrue(rs.problems(doc))
        doc = json.loads(EXAMPLE.read_text())
        next(n for n in doc["nodes"] if n["kind"] == "tileLayer").pop("collides")
        self.assertTrue(rs.problems(doc))

    def test_a_value_listed_twice_in_groups_or_images_is_a_problem(self):
        doc = json.loads(EXAMPLE.read_text())
        doc["nodes"][0]["groups"] = ["a", "a"]
        self.assertIn("Player: groups lists a value twice", rs.problems(doc))

    def test_the_reader_needs_no_jsonschema(self):
        # An installed Expectrail has no dependencies; CI's capture-smoke job has no jsonschema.
        import sys
        with mock.patch.dict(sys.modules, {"jsonschema": None}):
            doc = json.loads(EXAMPLE.read_text())
            self.assertEqual(rs.problems(doc), [])
            doc["nodes"][0]["kind"] = "light"
            self.assertTrue(rs.problems(doc))

    def test_a_path_listed_twice_is_a_problem(self):
        doc = json.loads(EXAMPLE.read_text())
        doc["nodes"].append(copy.deepcopy(doc["nodes"][0]))
        self.assertIn("a node path is listed twice", rs.problems(doc))

    def test_the_scanner_and_its_reader_agree_on_format_and_kinds(self):
        script = (ROOT / "harness" / "godot" / rs.SCRIPT).read_text()
        self.assertIn(f'const FORMAT := "{rs.RAW_FORMAT}"', script)
        for kind in rs.KINDS:
            self.assertIn(f'return "{kind}"', script)
        self.assertIn(f"const MAX_NODES := {rs.MAX_NODES}", script)


class RawReaderTest(unittest.TestCase):
    """What the running game wrote is untrusted: anything that does not read cleanly is refused."""

    def refused(self, data, ticks=30):
        with self.assertRaises(rs.RuntimeScanError) as caught:
            rs.read_raw(data, ticks)
        return str(caught.exception)

    def test_a_clean_file_reads_and_the_root_is_spelled_dot(self):
        got = rs.read_raw(raw([body("."), layer("Floor")]), 30)
        self.assertEqual([n["path"] for n in got["nodes"]], [".", "Floor"])
        self.assertIsNone(got["nodes"][0]["className"])

    def test_each_unreadable_file_is_refused_with_cannot_tell(self):
        cases = {
            "not json": b"{",
            "duplicate key": b'{"format": "x", "format": "y"}',
            "not a scan": json.dumps({"format": "other"}).encode(),
            "extra top field": raw([], extra=1),
            "ticks differ": raw([], ticks=29),
            "unknown kind": raw([{**body("A"), "kind": "light"}]),
            "unknown node field": raw([{**body("A"), "texture": "res://a.png"}]),
            "missing field": raw([{k: v for k, v in layer("A").items() if k != "cells"}]),
            "image outside res": raw([sprite("A", ["user://a.png"])]),
            "atlas outside res": raw([sprite("A", atlas=["/tmp/a.png"])]),
            "bare res root": raw([sprite("A", ["res://"])]),
            "no atlas field": raw([{k: v for k, v in sprite("A").items() if k != "atlasImages"}]),
            "absolute path": raw([body("/root/A")]),
            "parent path": raw([body("../A")]),
            "control character": raw([body("A\nB")]),
            "duplicate path": raw([body("A"), body("A")]),
            "boolean count": raw([layer("A", cells=True)]),
            "too large": b" " * (rs.MAX_RAW_BYTES + 1),
        }
        for name, data in cases.items():
            with self.subTest(name):
                self.assertIn("cannot tell", self.refused(data))

    def test_a_game_with_no_current_scene_names_what_to_check(self):
        text = self.refused(raw([], error="no current scene"))
        self.assertIn("starting scene loads", text)


class MergeTest(unittest.TestCase):
    def test_a_floor_built_in_code_is_listed_as_found_only_at_runtime(self):
        doc = record([body("Player"), sprite("Player/Body", kind="polygon"), layer("Floor")])
        merged = rs.merge(static(), doc, ["", "Player", "Player/Body"])
        self.assertEqual(merged["runtime"]["groundLayers"], ["Floor"])
        self.assertEqual(merged["runtime"]["onlyAtRuntime"], ["Floor"])
        self.assertEqual(merged["groundLayers"], [], "a saved-scene finding is never replaced")

    def test_an_empty_or_non_solid_layer_is_not_ground(self):
        doc = record([body("Player"), layer("Empty", cells=0), layer("Art", collides=False)])
        runtime = rs.merge(static(), doc, [""])["runtime"]
        self.assertEqual(runtime["groundLayers"], [])
        self.assertEqual(runtime["emptyOrNonSolidLayers"], ["Art", "Empty"])

    def test_the_one_image_drawn_under_the_player_is_taken_and_said_so(self):
        doc = record([body("Player"), sprite("Player/Sprite", ["res://crate.svg"])])
        merged = rs.merge(static(), doc, ["", "Player"])
        self.assertEqual(merged["textures"], ["res://crate.svg"])
        self.assertEqual(merged["unresolvedBindings"], [])
        self.assertEqual(merged["textureFrom"], "runtime")
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(CRATE, tmp, dirs_exist_ok=True)
            (Path(tmp) / "expectrail.project.json").unlink()
            docs = onboarding.proposal(Path(tmp), merged)
        self.assertEqual(docs["config"]["bindings"]["player"], {"node": "Player", "texture": "res://crate.svg"})
        self.assertEqual(docs["textureFrom"], "runtime")
        self.assertNotIn("unresolvedBindings", docs)
        self.assertIs(docs["config"]["draft"], True, "init still proposes a draft for a person to review")

    def test_no_image_is_guessed(self):
        cases = {
            "a filled polygon": ([body("Player"), sprite("Player/Body", kind="polygon")], "draws no image file"),
            "an image made in code": ([body("Player"), sprite("Player/S", unsaved=1)], "made in code"),
            "atlas regions of one file": ([body("Player"), sprite("Player/S", kind="animatedSprite",
                                                                  atlas=["res://paddle.png"])],
                                          "regions of res://paddle.png through an AtlasTexture"),
            "a whole image and an atlas": ([body("Player"), sprite("Player/A", ["res://a.png"]),
                                            sprite("Player/B", atlas=["res://a.png"])], "AtlasTexture"),
            "two images": ([body("Player"), sprite("Player/A", ["res://a.png"]), sprite("Player/B", ["res://b.png"])],
                           "several images"),
            "a file and a code image": ([body("Player"), sprite("Player/A", ["res://a.png"]), sprite("Player/B", unsaved=2)],
                                        "made in code"),
        }
        for name, (nodes, said) in cases.items():
            with self.subTest(name):
                merged = rs.merge(static(), record(nodes), ["", "Player"])
                self.assertEqual(merged["textures"], [])
                self.assertNotIn("textureFrom", merged)
                self.assertTrue(any(said in p for p in merged["unresolvedBindings"]), merged["unresolvedBindings"])
                self.assertTrue(merged["unresolvedBindings"][-1].startswith("Supply one image"))

    def test_an_image_under_another_body_is_not_the_players(self):
        doc = record([body("Player"), body("Player/Pet"), sprite("Player/Pet/S", ["res://pet.png"])])
        merged = rs.merge(static(), doc, ["", "Player", "Player/Pet"])
        self.assertEqual(merged["runtime"]["playerImages"], [])
        self.assertEqual(merged["textures"], [])

    def test_two_running_players_or_a_saved_duplicate_bind_nothing(self):
        doc = record([body("A/Player"), body("B/Player"), sprite("A/Player/S", ["res://a.png"])])
        merged = rs.merge(static(players=()), doc, [""])
        self.assertIn("several player candidates", merged["runtime"]["playerProblem"])
        self.assertEqual(merged["textures"], [])
        doc = record([body("Player"), sprite("Player/S", ["res://a.png"])])
        two = static(players=("Player", "Other"), problems=["Supply the player node path and its res:// image."])
        merged = rs.merge(two, doc, ["", "Player", "Other"])
        self.assertEqual(merged["players"], ["Player", "Other"])
        self.assertEqual(merged["textures"], [])

    def test_a_player_that_exists_only_at_runtime_is_bound_with_its_image(self):
        doc = record([body("Level/Player"), sprite("Level/Player/S", ["res://p.png"])])
        none = static(players=(), problems=["Supply the player node path and its res:// image in bindings.player; "
                                            "the starting scene has no unique player."])
        merged = rs.merge(none, doc, [""])
        self.assertEqual(merged["players"], ["Level/Player"])
        self.assertEqual(merged["textures"], ["res://p.png"])

    def test_a_saved_texture_is_kept_even_when_the_running_game_draws_another(self):
        doc = record([body("Player"), sprite("Player/S", ["res://other.png"])])
        merged = rs.merge(static(textures=("res://saved.png",)), doc, ["", "Player"])
        self.assertEqual(merged["textures"], ["res://saved.png"])
        self.assertNotIn("textureFrom", merged)
        self.assertEqual(merged["runtime"]["playerImages"], ["res://other.png"])

    def test_groups_and_classes_are_listed(self):
        doc = record([body("Player", groups=["hero"]), body("Coins/Coin", className="Coin", groups=["pickups"])])
        runtime = rs.merge(static(), doc, [""])["runtime"]
        self.assertEqual(runtime["groups"], {"hero": ["Player"], "pickups": ["Coins/Coin"]})
        self.assertEqual(runtime["classes"], {"Coin": ["Coins/Coin"]})

    def test_an_unreadable_record_is_refused(self):
        doc = record([body("Player")])
        doc["nodes"][0]["cells"] = 1
        with self.assertRaises(rs.RuntimeScanError):
            rs.merge(static(), doc, [""])


class CommandTest(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with cli_capture.command_output(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def test_runtime_and_at_tick_together_are_refused_before_anything_runs(self):
        with mock.patch.object(rs, "scan", side_effect=AssertionError("scanned")):
            code, said = self.run_cli("inspect", str(CRATE), "--runtime", "--at-tick", "3")
        self.assertEqual(code, 5)
        self.assertIn("Use one of them", said)

    def test_a_scan_that_cannot_be_made_is_exit_5_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(CRATE, tmp, dirs_exist_ok=True)
            (Path(tmp) / "expectrail.project.json").unlink()
            before = sorted(p.name for p in Path(tmp).iterdir())
            with mock.patch.object(rs, "scan", side_effect=rs.RuntimeScanError("the game stopped; cannot tell")):
                code, said = self.run_cli("init", tmp, "--runtime")
            self.assertEqual(code, 5)
            self.assertIn("cannot tell", said)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), before)

    def test_inspect_runtime_prints_the_running_game_beside_the_saved_scenes(self):
        doc = record([body("Player"), sprite("Player/Body", kind="polygon"), layer("Floor")])
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(CRATE, tmp, dirs_exist_ok=True)
            (Path(tmp) / "expectrail.project.json").unlink()
            with mock.patch.object(rs, "scan", return_value=doc):
                code, said = self.run_cli("inspect", tmp, "--runtime")
                self.assertEqual(code, 0)
                code, listed = self.run_cli("inspect", tmp, "--runtime", "--json")
        self.assertIn("Solid tile layers with tiles: Floor", said)
        self.assertIn("Found only at runtime: Floor", said)
        self.assertIn("Polygon2D draws no image file", said)
        self.assertIn("Ground candidates found", said)
        self.assertIn("not evidence for a verdict", said)
        self.assertEqual(json.loads(listed)["runtime"]["groundLayers"], ["Floor"])

    def test_without_runtime_nothing_is_started(self):
        with mock.patch.object(rs, "scan", side_effect=AssertionError("scanned")):
            code, said = self.run_cli("inspect", str(CRATE))
        self.assertEqual(code, 0)
        self.assertNotIn("Running game", said)


class RealEngineTest(unittest.TestCase):
    """In Godot, without the sandbox (the sandboxed path needs bubblewrap; CI's job decides)."""

    @classmethod
    def setUpClass(cls):
        from tests.tool_requirements import godot_binary
        cls.engine = godot_binary()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="expectrail-runtime-scan-")
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"EXPECTRAIL_SANDBOX": "off", "EXPECTRAIL_GODOT": str(self.engine)})
        env.start()
        self.addCleanup(env.stop)

    def copy(self, source, keep_config=False):
        game = self.work / source.name
        shutil.copytree(source, game)
        if not keep_config:
            (game / "expectrail.project.json").unlink(missing_ok=True)
        return game

    def test_crate_run_shows_the_floor_its_script_builds(self):
        game = self.copy(CRATE)
        doc = rs.scan(game)
        self.assertEqual(rs.problems(doc), [])
        nodes = {n["path"]: n for n in doc["nodes"]}
        self.assertEqual(nodes["Floor"]["kind"], "tileLayer")
        self.assertTrue(nodes["Floor"]["collides"])
        self.assertEqual(nodes["Floor"]["cells"], 72, "main.gd fills x from -8 to 63 on one row")
        self.assertEqual(nodes["Player/Body"]["images"], [])
        self.assertFalse(doc["isolation"]["sandbox"])
        self.assertEqual(sorted(p.name for p in game.iterdir()), sorted(p.name for p in CRATE.iterdir()
                                                                         if p.name != "expectrail.project.json"),
                         "the scan writes nothing into the game")
        info = onboarding.with_runtime(game, onboarding.inspect(game))
        self.assertEqual(info["runtime"]["onlyAtRuntime"], ["Floor"])
        self.assertTrue(any("Polygon2D draws no image file" in p for p in info["unresolvedBindings"]))

    def test_crate_run_with_its_config_runs_the_configured_scene(self):
        game = self.copy(CRATE, keep_config=True)
        doc = rs.scan(game, ticks=5)
        self.assertEqual(doc["project"]["entryScene"], "res://main.tscn")
        self.assertRegex(doc["project"]["configSha256"], "^[0-9a-f]{64}$")
        self.assertEqual(doc["ticks"], 5)

    def test_the_bundled_game_lists_its_player_image_and_its_classes(self):
        game = self.copy(ROOT / "game" / "platformer")
        info = onboarding.with_runtime(game, onboarding.inspect(game))
        runtime = info["runtime"]
        self.assertEqual(runtime["players"], ["Level/Player"])
        self.assertEqual(runtime["playerImages"], ["res://player/robot.webp"])
        self.assertEqual(runtime["groundLayers"], ["Level/TileMapLayer"])
        self.assertEqual(runtime["onlyAtRuntime"], [])
        self.assertEqual(len(runtime["classes"]["Coin"]), 21)
        self.assertEqual(info["textures"], ["res://player/robot.webp"])
        self.assertNotIn("textureFrom", info)

    def test_atlas_regions_a_tres_texture_and_a_code_image_are_never_bindable_images(self):
        # #666: Breakout's paddle draws AtlasTexture regions of one PNG. A region is not the image.
        game = self.copy(CRATE)
        (game / "atlas.tres").write_text('[gd_resource type="AtlasTexture" load_steps=2 format=3]\n\n'
                                         '[ext_resource type="Texture2D" path="res://crate.svg" id="1"]\n\n'
                                         '[resource]\natlas = ExtResource("1")\nregion = Rect2(0, 0, 16, 16)\n')
        script = game / "main.gd"
        script.write_text(script.read_text().replace("\tadd_child(ground)\n", (
            "\tadd_child(ground)\n"
            "\tvar player := get_node(\"Player\")\n"
            "\tvar region := AtlasTexture.new()\n"
            "\tregion.atlas = load(\"res://crate.svg\")\n"
            "\tregion.region = Rect2(0, 0, 16, 16)\n"
            "\tfor pair in [[\"Region\", region], [\"Saved\", load(\"res://atlas.tres\")],\n"
            "\t\t\t[\"Code\", ImageTexture.create_from_image(image)], [\"Whole\", load(\"res://crate.svg\")]]:\n"
            "\t\tvar s := Sprite2D.new()\n"
            "\t\ts.name = pair[0]\n"
            "\t\ts.texture = pair[1]\n"
            "\t\tplayer.add_child(s)\n"), 1))
        nodes = {n["path"]: n for n in rs.scan(game)["nodes"]}
        self.assertEqual((nodes["Player/Region"]["images"], nodes["Player/Region"]["atlasImages"]), ([], ["res://crate.svg"]))
        self.assertEqual((nodes["Player/Saved"]["images"], nodes["Player/Saved"]["atlasImages"]), ([], ["res://crate.svg"]))
        self.assertEqual((nodes["Player/Code"]["images"], nodes["Player/Code"]["unsavedImages"]), ([], 1))
        self.assertEqual(nodes["Player/Whole"]["images"], ["res://crate.svg"])
        info = onboarding.with_runtime(game, onboarding.inspect(game))
        self.assertEqual(info["textures"], [], "a whole image beside an atlas region is still not guessed")
        self.assertTrue(any("through an AtlasTexture" in p for p in info["unresolvedBindings"]))

    def test_a_game_that_quits_before_the_scan_says_so(self):
        game = self.copy(CRATE)
        script = game / "main.gd"
        script.write_text(script.read_text().replace("func _ready() -> void:\n",
                                                     "func _ready() -> void:\n\tget_tree().quit(7)\n", 1))
        with self.assertRaises(rs.RuntimeScanError) as caught:
            rs.scan(game)
        self.assertIn("stopped before the scan was written (exit 7)", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
