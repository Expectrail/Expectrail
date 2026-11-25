"""The saved-scene reader resolves a selected node's atlas frames for review (#666).

The project here is built to the shape of pinned Breakout's scene: a ``Paddle`` whose
AnimatedSprite2D draws two 47 x 18 AtlasTexture regions of one 94 x 18 PNG, and a ``Ball``
whose Sprite2D draws a whole 4 x 4 PNG. Breakout itself is not fetched here.
"""
import hashlib
import io
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from expectrail import cli, onboarding
from tests import cli_capture

STRIP = "res://break assets/paddle/sp_paddle_long_strip2.png"
BALL = "res://break assets/Misc/sp_ball.png"

PROJECT = """config_version=5

[application]
config/name="Bricks"
run/main_scene="res://game.tscn"

[display]
window/size/viewport_width=360
window/size/viewport_height=640
"""

ATLAS = '''[sub_resource type="AtlasTexture" id="AtlasTexture_a"]
atlas = ExtResource("2_strip")
region = Rect2(0, 0, 47, 18)

[sub_resource type="AtlasTexture" id="AtlasTexture_b"]
atlas = ExtResource("2_strip")
region = Rect2(47, 0, 47, 18)
'''

FRAMES = '''[sub_resource type="SpriteFrames" id="SpriteFrames_p"]
animations = [{
"frames": [{
"duration": 1.0,
"texture": SubResource("AtlasTexture_a")
}, {
"duration": 1.0,
"texture": SubResource("AtlasTexture_b")
}],
"loop": true,
"name": &"default",
"speed": 5.0
}]
'''

PADDLE = '''[gd_scene format=3 uid="uid://paddle0000"]

[ext_resource type="Texture2D" uid="uid://strip0000" path="res://break assets/paddle/sp_paddle_long_strip2.png" id="2_strip"]

{atlas}
{frames}
[node name="Paddle" type="CharacterBody2D"]

[node name="AnimatedSprite2D" type="AnimatedSprite2D" parent="."]
sprite_frames = SubResource("SpriteFrames_p")

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]
'''

GAME = '''[gd_scene format=3 uid="uid://game00000"]

[ext_resource type="PackedScene" uid="uid://paddle0000" path="res://scenes/paddle.tscn" id="1_paddle"]
[ext_resource type="Texture2D" uid="uid://ball00000" path="res://break assets/Misc/sp_ball.png" id="3_ball"]

[node name="Game" type="Node2D"]

[node name="Paddle" parent="." instance=ExtResource("1_paddle")]
position = Vector2(180, 600)

[node name="Ball" type="CharacterBody2D" parent="."]

[node name="Sprite2D" type="Sprite2D" parent="Ball"]
scale = Vector2(2, 2)
texture = ExtResource("3_ball")
'''


def png(width, height):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def command(*args):
    stream = io.StringIO()
    with cli_capture.command_output(stream):
        code = cli.main([str(a) for a in args])
    return code, stream.getvalue()


def digest(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


class AtlasReviewTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.game = Path(tmp.name) / "bricks"
        self.build()

    def build(self, atlas=ATLAS, frames=FRAMES, paddle=None):
        (self.game / "scenes").mkdir(parents=True, exist_ok=True)
        (self.game / "break assets/paddle").mkdir(parents=True, exist_ok=True)
        (self.game / "break assets/Misc").mkdir(parents=True, exist_ok=True)
        (self.game / "project.godot").write_text(PROJECT)
        (self.game / "game.tscn").write_text(GAME)
        (self.game / "scenes/paddle.tscn").write_text(paddle or PADDLE.format(atlas=atlas, frames=frames))
        (self.game / "break assets/paddle/sp_paddle_long_strip2.png").write_bytes(png(94, 18))
        (self.game / "break assets/Misc/sp_ball.png").write_bytes(png(4, 4))

    def test_webp_sheet_dimensions_in_selected_player_review(self):
        scene = self.game / "game.tscn"
        scene.write_text(scene.read_text().replace("sp_ball.png", "sheet.webp"))
        sheet = self.game / "break assets/Misc/sheet.webp"
        # A lossless 512 x 64 image. No optional decoder is needed by setup.
        data = bytes.fromhex(
            "5249464620000000574542505650384c14000000"
            "2fffc10f00071011fd0f0028d2ffff14d1ffd47f"
        )
        sheet.write_bytes(data)
        item, = onboarding.inspect(self.game, "Ball")["imageSuggestions"]
        self.assertEqual(item["imageSize"], [512, 64])
        self.assertIsNone(item["regions"])
        sheet.write_bytes(data[:-1])
        item, = onboarding.inspect(self.game, "Ball")["imageSuggestions"]
        self.assertIsNone(item["imageSize"])

    def test_without_a_selection_neither_body_is_chosen(self):
        info = onboarding.inspect(self.game)
        self.assertCountEqual(info["players"], ["Paddle", "Ball"])
        self.assertEqual(info["textures"], [])
        self.assertTrue(any("no unique player" in p for p in info["unresolvedBindings"]))

    def test_selecting_paddle_offers_its_strip_and_names_the_region_but_binds_nothing(self):
        info = onboarding.inspect(self.game, player="Paddle")
        self.assertEqual(info["players"], ["Paddle"])
        self.assertEqual(info["selectedPlayer"], "Paddle")
        self.assertEqual(info["textures"], [STRIP])
        self.assertEqual(info["imageSuggestions"], [{
            "sprite": "Paddle/AnimatedSprite2D", "property": "sprite_frames", "image": STRIP,
            "imageSize": [94, 18], "regions": [[0, 0, 47, 18], [47, 0, 47, 18]]}])
        joined = "\n".join(info["unresolvedBindings"])
        self.assertIn("47 × 18", joined)
        self.assertIn("94 × 18", joined)
        self.assertIn("AtlasTexture", joined)
        self.assertNotIn(BALL, json.dumps(info))
        docs = onboarding.proposal(self.game, info)
        self.assertEqual(docs["config"]["bindings"], {"player": {"node": "Paddle"}})
        self.assertEqual(docs["textureCandidates"], [STRIP])
        self.assertEqual(docs["imageSuggestions"], info["imageSuggestions"])

    def test_selecting_ball_offers_only_its_own_whole_image(self):
        info = onboarding.inspect(self.game, player="Ball")
        self.assertEqual(info["textures"], [BALL])
        self.assertEqual(info["imageSuggestions"], [{
            "sprite": "Ball/Sprite2D", "property": "texture", "image": BALL,
            "imageSize": [4, 4], "regions": None}])
        self.assertEqual(info["unresolvedBindings"], [])
        docs = onboarding.proposal(self.game, info)
        self.assertEqual(docs["config"]["bindings"]["player"], {"node": "Ball", "texture": BALL})
        self.assertEqual(docs["imageSuggestions"], info["imageSuggestions"])

    def test_the_commands_take_the_selection_and_leave_the_game_unchanged(self):
        before = digest(self.game)
        code, text = command("inspect", self.game, "--player", "Paddle")
        self.assertEqual(code, 0, text)
        for phrase in ("Selected player: Paddle", STRIP + " (94 × 18)",
                       "regions 47 × 18 at (0, 0), 47 × 18 at (47, 0)", "Paddle/AnimatedSprite2D"):
            self.assertIn(phrase, text)
        self.assertNotIn(BALL, text)
        code, raw = command("init", self.game, "--player", "Paddle", "--dry-run")
        self.assertEqual(code, 0, raw)
        draft = json.loads(raw)
        self.assertTrue(draft["draft"])
        self.assertEqual(draft["imageSuggestions"][0]["regions"], [[0, 0, 47, 18], [47, 0, 47, 18]])
        code, raw = command("init", self.game, "--player", "Ball", "--dry-run")
        self.assertEqual(code, 0, raw)
        self.assertEqual(json.loads(raw)["config"]["bindings"]["player"], {"node": "Ball", "texture": BALL})
        self.assertEqual(before, digest(self.game))

    def test_a_selection_that_is_not_a_body_in_the_scene_is_refused(self):
        for node, phrase in (("Bat", "Paddle"), ("Paddle/AnimatedSprite2D", "physics body"), ("", "physics body")):
            with self.subTest(node=node):
                with self.assertRaises(ValueError) as caught:
                    onboarding.inspect(self.game, player=node)
                self.assertIn(phrase, str(caught.exception))
        code, text = command("inspect", self.game, "--player", "Bat")
        self.assertEqual(code, 5, text)
        self.assertIn("Ball", text)

    def test_unsupported_references_are_left_unresolved_with_what_to_supply(self):
        cases = {
            "atlas made of a sub-resource": (ATLAS.replace('atlas = ExtResource("2_strip")', 'atlas = SubResource("x")', 1),
                                             FRAMES, "atlas"),
            "atlas with no region": (ATLAS.replace("region = Rect2(0, 0, 47, 18)\n", ""), FRAMES, "region"),
            "region that is not a number": (ATLAS.replace("Rect2(0, 0, 47, 18)", "Rect2(0, 0, inf, 18)"), FRAMES,
                                            "no readable region"),
            "frame naming an unknown sub-resource": (ATLAS, FRAMES.replace("AtlasTexture_b", "AtlasTexture_z"),
                                                     "no direct external file reference"),
            "region outside the image": (ATLAS.replace("Rect2(47, 0, 47, 18)", "Rect2(60, 0, 47, 18)"), FRAMES,
                                         "outside"),
        }
        for name, (atlas, frames, phrase) in cases.items():
            with self.subTest(name):
                self.build(atlas=atlas, frames=frames)
                info = onboarding.inspect(self.game, player="Paddle")
                joined = "\n".join(info["unresolvedBindings"])
                self.assertIn(phrase, joined)
                self.assertIn("bindings.player.texture", joined)
                self.assertNotIn("texture", onboarding.proposal(self.game, info)["config"]["bindings"]["player"])

    def test_external_frames_and_a_missing_image_are_unresolved(self):
        external = PADDLE.format(atlas="", frames="").replace(
            'sprite_frames = SubResource("SpriteFrames_p")', 'sprite_frames = ExtResource("4_frames")').replace(
            '[ext_resource type="Texture2D"', '[ext_resource type="SpriteFrames" path="res://paddle_frames.tres" id="4_frames"]\n'
            '[ext_resource type="Texture2D"')
        self.build(paddle=external)
        info = onboarding.inspect(self.game, player="Paddle")
        self.assertEqual(info["textures"], [])
        self.assertIn("external", "\n".join(info["unresolvedBindings"]))
        self.build()
        (self.game / "break assets/paddle/sp_paddle_long_strip2.png").unlink()
        info = onboarding.inspect(self.game, player="Paddle")
        self.assertEqual(info["textures"], [])
        self.assertIn("Restore " + STRIP, "\n".join(info["unresolvedBindings"]))

    def test_the_binding_review_keeps_the_source_image_and_its_regions_apart(self):
        from expectrail import onboard

        self.assertEqual(command("init", self.game, "--player", "Paddle")[0], 0)
        draft = json.loads((self.game / "expectrail.project.draft.json").read_text())
        self.assertEqual(draft["selectedPlayer"], "Paddle")
        page = onboard.render(self.game)
        self.assertIn("<code>Paddle/AnimatedSprite2D</code> draws regions 47 × 18 at (0, 0), "
                      "47 × 18 at (47, 0) of this 94 × 18 image.", page)
        self.assertIn("Use break assets/paddle/sp_paddle_long_strip2.png and save", page)
        self.assertNotIn("sp_ball", page)
        self.assertIn("Player node selected for init: <code>Paddle</code>.", page)
        draft["selectedPlayer"] = "Ball"
        (self.game / "expectrail.project.draft.json").write_text(json.dumps(draft))
        with self.assertRaises(ValueError) as caught:
            onboard.render(self.game)
        self.assertIn("differs from the current project", str(caught.exception))

    def test_player_is_not_taken_with_at_tick(self):
        code, text = command("inspect", self.game, "--player", "Ball", "--at-tick", "3")
        self.assertEqual(code, 5, text)
        self.assertIn("--player", text)

    def test_image_size_reads_png_headers_only(self):
        path = self.game / "break assets/Misc/sp_ball.png"
        self.assertEqual(onboarding.image_size(path), [4, 4])
        path.write_bytes(b"RIFF....WEBP")
        self.assertIsNone(onboarding.image_size(path))
        path.write_bytes(png(4, 4)[:20])
        self.assertIsNone(onboarding.image_size(path))


if __name__ == "__main__":
    unittest.main()
