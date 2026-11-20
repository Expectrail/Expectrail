"""The review page offers the project's images when the player is drawn with none (#688).

Crate Run's player is a filled Polygon2D, so init cannot choose its image. The review page then lists
the project's image files as a separate choice, each labelled as an image the player is not drawn
with in the saved scenes. init itself never binds one.
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail import onboard, onboarding, project_config
from tests.check_onboarding_games import ROOT, contents
from tests.test_init_inspect import command
from tests.test_onboard import Page

CRATE = ROOT / "tests" / "projects" / "crate-run" / "project"
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x04\x00\x00\x00\x04\x08\x06\x00\x00\x00"
       b"\xa9\xf1\x9e~\x00\x00\x00\x0bIDATx\x9cc\xf8\x0f\x00\x01\x01\x01\x00\x18\xdd\x8d\xb0"
       b"\x00\x00\x00\x00IEND\xaeB`\x82")


class ProjectImagesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "crate-run"
        shutil.copytree(CRATE, self.root)
        (self.root / project_config.FILENAME).unlink()
        self.out = Path(tmp.name) / "review.html"

    def init(self, *extra):
        code, msg = command("init", self.root, *extra)
        self.assertEqual(code, 0, msg)
        return msg

    def review(self):
        code, msg = command("onboard", "--project", self.root, "--out", self.out)
        self.assertEqual(code, 0, msg)
        return Page(self.out), self.out.read_text(encoding="utf-8")

    def test_crate_run_review_offers_crate_svg_labelled_as_not_drawn_under_the_player(self):
        said = self.init()
        draft = json.loads((self.root / onboard.PENDING).read_bytes())
        # init never binds a project image: the review draft still has no texture.
        self.assertNotIn("texture", draft["config"]["bindings"]["player"])
        self.assertEqual(draft["textureCandidates"], [])
        self.assertNotIn("projectImages", draft)
        self.assertIn("The review page offers 1 image file in the project", said)
        before = contents(self.root)
        page, html = self.review()
        self.assertEqual(contents(self.root), before)
        self.assertNotIn("No complete choice", html)
        self.assertIn("The saved scenes draw <code>Player</code> with no image file", html)
        self.assertIn("Not drawn under <code>Player</code>", html)
        self.assertEqual(len(page.configs), 1)
        chosen = page.configs[0]
        self.assertEqual(chosen["bindings"]["player"], {"node": "Player", "texture": "res://crate.svg"})
        expected = dict(draft["config"])
        expected["bindings"] = {"player": {"node": "Player", "texture": "res://crate.svg"}}
        self.assertEqual(chosen, expected)
        self.assertTrue(chosen["draft"])
        self.assertNotIn("approvedContracts", chosen)
        self.assertEqual(project_config.validate(chosen, self.root), chosen)
        self.assertTrue(all(image.startswith("data:image/svg+xml") for image in page.images))

    def test_inspect_lists_project_images_only_when_no_sprite_draws_the_player(self):
        info = onboarding.inspect(self.root)
        self.assertEqual(info["textures"], [])
        self.assertEqual(info["projectImages"], ["res://crate.svg"])
        code, msg = command("inspect", self.root)
        self.assertEqual(code, 0, msg)
        self.assertIn("Images in the project, not drawn under the player: res://crate.svg", msg)
        # The bundled game draws its player with a sprite: nothing extra is listed.
        bundled = onboarding.inspect(ROOT / "game" / "platformer")
        self.assertTrue(bundled["textures"])
        self.assertNotIn("projectImages", bundled)

    def test_a_sprite_with_an_unreadable_image_is_not_given_project_images(self):
        # The player is drawn by a sprite whose frames are external: its image is unknown, not absent,
        # so the page must not say the player is drawn with no image.
        scene = self.root / "main.tscn"
        scene.write_text(scene.read_text() + '\n[node name="Look" type="AnimatedSprite2D" parent="Player"]\n'
                         'sprite_frames = ExtResource("9")\n')
        info = onboarding.inspect(self.root)
        self.assertNotIn("projectImages", info)
        self.init()
        _, html = self.review()
        self.assertIn("No complete choice", html)

    def test_several_player_candidates_offer_no_project_image(self):
        scene = self.root / "main.tscn"
        scene.write_text(scene.read_text() + '\n[node name="Other" type="CharacterBody2D" parent="."]\n')
        text = scene.read_text().replace('[node name="Player" type', '[node name="Crate" type')
        scene.write_text(text.replace('parent="Player"', 'parent="Crate"'))
        info = onboarding.inspect(self.root)
        self.assertEqual(len(info["players"]), 2)
        self.assertNotIn("projectImages", info)
        self.init()
        page, html = self.review()
        self.assertEqual(page.configs, [])
        self.assertIn("No complete choice", html)

    def test_listing_skips_hidden_ignored_linked_and_non_image_files_and_caps_the_count(self):
        (self.root / ".godot" / "imported").mkdir(parents=True)
        (self.root / ".godot" / "imported" / "crate.png").write_bytes(PNG)
        (self.root / "ignored").mkdir()
        (self.root / "ignored" / ".gdignore").write_text("")
        (self.root / "ignored" / "x.png").write_bytes(PNG)
        (self.root / "notes.txt").write_text("not an image")
        outside = self.root.parent / "outside.png"
        outside.write_bytes(PNG)
        os.symlink(outside, self.root / "linked.png")
        (self.root / "art").mkdir()
        for n in range(onboarding.PROJECT_IMAGE_LIMIT + 3):
            (self.root / "art" / f"tile{n:02d}.PNG").write_bytes(PNG)
        images, more = onboarding.project_images(self.root)
        self.assertEqual(len(images), onboarding.PROJECT_IMAGE_LIMIT)
        self.assertEqual(more, 4)
        self.assertEqual(images[0], "res://crate.svg")   # top-level files come first
        self.assertTrue(all(i.startswith("res://art/tile") for i in images[1:]))
        for path in images:
            onboarding.resource(self.root, path)
        # init refuses a link that leaves the game, before any listing; remove it for the page.
        (self.root / "linked.png").unlink()
        self.init()
        page, html = self.review()
        self.assertEqual(len(page.configs), onboarding.PROJECT_IMAGE_LIMIT)
        self.assertIn("4 more image files are in the project", html)
        for config in page.configs:
            self.assertEqual(project_config.validate(config, self.root), config)

    def test_the_project_icon_is_named_as_the_icon(self):
        (self.root / "icon.png").write_bytes(PNG)
        settings = self.root / "project.godot"
        settings.write_text(settings.read_text().replace("[application]\n", '[application]\n\nconfig/icon="res://icon.png"\n', 1))
        self.assertIn('config/icon="res://icon.png"', settings.read_text())
        images, _ = onboarding.project_images(self.root)
        self.assertEqual(images, ["res://crate.svg", "res://icon.png"])
        self.init()
        page, html = self.review()
        self.assertEqual([c["bindings"]["player"]["texture"] for c in page.configs],
                         ["res://crate.svg", "res://icon.png"])
        self.assertIn("This is the project's icon", html)


if __name__ == "__main__":
    unittest.main()
