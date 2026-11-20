"""Inspect authored scenes without starting the game or approving a check."""
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail import cli, contracts, project_config
from tests import cli_capture

ROOT = Path(__file__).resolve().parents[1]


def command(*args):
    stream = io.StringIO()
    with cli_capture.command_output(stream):
        code = cli.main([str(a) for a in args])
    return code, stream.getvalue()


class SetupTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.game = Path(tmp.name) / "game"
        # A game that has not been onboarded: the bundled game's own config is left out (#259).
        shutil.copytree(ROOT / "game/platformer", self.game, ignore=shutil.ignore_patterns("expectrail.project.json"))

    def test_inspect_and_dry_run_are_read_only_and_match_the_written_drafts(self):
        original = {p.relative_to(self.game): p.read_bytes() for p in self.game.rglob("*") if p.is_file()}
        code, raw = command("inspect", self.game, "--json")
        self.assertEqual(code, 0, raw)
        report = json.loads(raw)
        self.assertEqual(report["players"], ["Level/Player"])
        self.assertIn("Level/Player/Camera", report["cameras"])
        self.assertIn("Level/TileMapLayer", report["groundLayers"])
        self.assertIn("move_right", report["actions"])
        code, raw = command("init", "--project", self.game, "--adapter", "godot", "--dry-run")
        self.assertEqual(code, 0, raw)
        preview = json.loads(raw)
        self.assertEqual(original, {p.relative_to(self.game): p.read_bytes()
                                    for p in self.game.rglob("*") if p.is_file()})
        code, msg = command("init", self.game)
        self.assertEqual(code, 0, msg)
        cfg = project_config.read_game(self.game)
        self.assertEqual(cfg, preview["config"])
        self.assertIs(cfg["draft"], True)
        self.assertEqual(cfg["bindings"]["player"], {"node": "Level/Player", "texture": "res://player/robot.webp"})
        self.assertNotIn("approvedContracts", cfg)
        contracts.validate_v1(cfg, "project")
        route = json.loads((self.game / cfg["routes"][0]).read_text())
        self.assertEqual(route, preview["route"])
        contracts.validate(route)
        self.assertIn("draft", route["name"])
        self.assertEqual(set(cfg["inputActions"]), {event["action"] for event in route["events"]})
        written = {p.relative_to(self.game).as_posix() for p in self.game.rglob("*") if p.is_file()} - {p.as_posix() for p in original}
        self.assertEqual(written, {project_config.FILENAME, cfg["routes"][0]})

    def test_force_reads_the_current_input_map_and_preserves_the_previous_route(self):
        self.assertEqual(command("init", self.game)[0], 0)
        path = self.game / project_config.FILENAME
        old = path.read_bytes()
        previous = self.game / json.loads(old)["routes"][0]
        old_route = previous.read_bytes()
        settings = self.game / "project.godot"
        settings.write_text(settings.read_text().replace("[input]", "[input]\nnew_move={}"))
        code, msg = command("init", self.game)
        self.assertEqual(code, 5, msg)
        self.assertIn("--force", msg)
        self.assertEqual(path.read_bytes(), old)
        self.assertEqual(command("init", self.game, "--force")[0], 0)
        self.assertIn("new_move", project_config.read_game(self.game)["inputActions"])
        self.assertEqual(previous.read_bytes(), old_route)

    def test_two_players_are_listed_and_neither_is_bound(self):
        scene = self.game / "game_singleplayer.tscn"
        scene.write_text(scene.read_text() + '\n[node name="Other" type="Node2D" parent="."]\n'
                         '[node name="Player" parent="Other" instance=ExtResource("4")]\n')
        code, msg = command("inspect", self.game)
        self.assertEqual(code, 0, msg)
        self.assertIn("Level/Player", msg)
        self.assertIn("Other/Player", msg)
        self.assertEqual(command("init", self.game)[0], 0)
        self.assertFalse((self.game / project_config.FILENAME).exists())
        pending = json.loads((self.game / "expectrail.project.draft.json").read_text())
        self.assertEqual(pending["config"]["bindings"], {})
        self.assertCountEqual(pending["playerCandidates"], ["Level/Player", "Other/Player"])

    def test_output_directory_link_is_refused(self):
        (self.game / "routes").symlink_to(self.game.parent, target_is_directory=True)
        code, msg = command("init", self.game)
        self.assertEqual(code, 5, msg)
        self.assertIn("symbolic link", msg)
        self.assertFalse((self.game / project_config.FILENAME).exists())
        self.assertEqual(list(self.game.parent.glob("*.json")), [])

    def test_animated_player_keeps_all_texture_choices_and_writes_review_files(self):
        scene = self.game / "player/player.tscn"
        text = scene.read_text()
        text = text.replace('[node name="Player"', '''
[ext_resource type="Texture2D" path="res://icon.svg" id="alt"]
[sub_resource type="SpriteFrames" id="frames"]
animations = [{
"frames": [{"texture": ExtResource("9")}, {"texture": ExtResource("alt")}],
"name": &"walk"
}]

[node name="Player"''', 1)
        (self.game / "icon.svg").write_text("<svg/>")
        scene.write_text(text.replace('type="Sprite2D"', 'type="AnimatedSprite2D"')
                         .replace('texture = ExtResource("9")', 'sprite_frames = SubResource("frames")'))
        code, msg = command("inspect", self.game)
        self.assertEqual(code, 0, msg)
        for phrase in ("Level/Player/Sprite2D.sprite_frames", "multiple frame textures",
                       "res://icon.svg", "res://player/robot.webp", "bindings.player.texture"):
            self.assertIn(phrase, msg)
        code, msg = command("init", self.game)
        self.assertEqual(code, 0, msg)
        self.assertIsNone(project_config.read_game(self.game))
        pending = self.game / "expectrail.project.draft.json"
        proposal = json.loads(pending.read_bytes())
        self.assertTrue(proposal["draft"])
        self.assertTrue(proposal["unresolvedBindings"])
        self.assertEqual(proposal["config"]["bindings"], {"player": {"node": "Level/Player"}})
        self.assertNotIn("approval", pending.read_text().lower())
        draft_route = json.loads((self.game / proposal["config"]["routes"][0]).read_bytes())
        contracts.validate(draft_route)
        pending.write_text("my edits")
        self.assertEqual(command("init", self.game)[0], 5)
        self.assertEqual(pending.read_text(), "my edits")
        self.assertEqual(command("init", self.game, "--force")[0], 0)
        self.assertEqual(json.loads(pending.read_bytes()), proposal)

    def test_missing_texture_is_reported_and_force_keeps_a_previous_live_config(self):
        self.assertEqual(command("init", self.game)[0], 0)
        active = self.game / project_config.FILENAME
        original = active.read_bytes()
        sprite = self.game / "player/player.tscn"
        sprite.write_text(sprite.read_text().replace("res://player/robot.webp", "res://missing.webp"))
        code, msg = command("inspect", self.game)
        self.assertEqual(code, 0, msg)
        self.assertIn("Level/Player/Sprite2D.texture", msg)
        self.assertIn("Restore res://missing.webp", msg)
        code, msg = command("init", self.game)
        self.assertEqual(code, 5, msg)
        self.assertIn("--force", msg)
        self.assertFalse((self.game / "expectrail.project.draft.json").exists())
        self.assertEqual(command("init", self.game, "--force")[0], 0)
        self.assertTrue((self.game / "expectrail.project.draft.json").is_file())
        self.assertEqual(active.read_bytes(), original)
