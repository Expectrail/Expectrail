"""Exercise the installed command's CLI path using saved init drafts."""
import base64
import json
import shutil
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from expectrail import project_config
from tests.check_onboarding_games import ROOT, contents
from tests.test_init_inspect import command


class Page(HTMLParser):
    def __init__(self, path):
        super().__init__(convert_charrefs=True)
        self.configs, self.images, self.tags = [], [], []
        self.rasters = {}
        self.payload = None
        self.in_payload = False
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append(tag)
        if tag == "script" and attrs.get("id") == "review-data":
            self.in_payload = True
        if tag == "a":
            assert attrs["download"] == project_config.FILENAME
            prefix, encoded = attrs["href"].split(",", 1)
            assert prefix == "data:application/json;base64"
            self.configs.append(json.loads(base64.b64decode(encoded, validate=True)))
        if tag == "img":
            self.images.append(attrs.get("src", attrs.get("srcset")))
        if tag == "image":
            self.rasters[attrs["id"]] = attrs["href"]
            self.images.append(attrs["href"])
        if tag == "use":
            self.images.append(self.rasters[attrs["href"].removeprefix("#")])

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_payload = False

    def handle_data(self, data):
        if self.in_payload:
            self.payload = json.loads(data)
            manifest = json.loads(Path(self.payload["reviewFile"]).read_bytes())
            self.configs.append(manifest["config"])


class ReviewTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "platformer"
        shutil.copytree(ROOT / "game/platformer", self.root)
        self.assertEqual(command("init", self.root)[0], 0)
        self.out = self.root.parent / "review.html"

    def render(self):
        return command("onboard", "--project", self.root, "--out", self.out)

    def test_download_preserves_every_binding_and_the_game(self):
        path = self.root / project_config.FILENAME
        config = json.loads(path.read_bytes())
        config["bindings"]["coin"] = {"group": "coins", "texture": "res://player/robot.webp"}
        path.write_text(json.dumps(config))
        before = contents(self.root)
        code, msg = self.render()
        self.assertEqual(code, 0, msg)
        page = Page(self.out)
        self.assertEqual(page.configs, [config])
        self.assertEqual(project_config.validate(page.configs[0], self.root), config)
        self.assertNotIn("approval", json.dumps(config))
        self.assertEqual(page.tags.count("script"), 2)
        self.assertIn("connect-src &#x27;none&#x27;", self.out.read_text())
        self.assertTrue(all(image.startswith("data:image/") for image in page.images))
        self.assertEqual(len(page.images), 2)
        self.assertIn("coins", self.out.read_text())
        self.assertEqual(contents(self.root), before)
        self.assertEqual(self.render()[0], 5)

    def test_a_missing_route_or_invalid_config_never_offers_a_download(self):
        path = self.root / project_config.FILENAME
        config = json.loads(path.read_bytes())
        (self.root / config["routes"][0]).unlink()
        self.assertEqual(self.render()[0], 5)
        self.assertFalse(self.out.exists())
        config["draft"] = False
        path.write_text(json.dumps(config))
        code, msg = self.render()
        self.assertEqual(code, 5, msg)
        self.assertIn("draft", msg)
        self.assertFalse(self.out.exists())

    def test_changed_route_and_conflicting_sources_are_explained(self):
        doc = project_config.read_game(self.root)
        path = self.root / doc["routes"][0]
        path.write_bytes(path.read_bytes() + b" ")
        code, msg = self.render()
        self.assertEqual(code, 5)
        self.assertIn("route has changed", msg)
        (self.root / "expectrail.project.draft.json").write_text("{}")
        code, msg = self.render()
        self.assertEqual(code, 5)
        self.assertIn("--source", msg)
        self.assertFalse(self.out.exists())

    def test_ambiguous_player_cannot_be_exported_and_markup_is_escaped(self):
        scene = self.root / "game_singleplayer.tscn"
        scene.write_text(scene.read_text() + '\n[node name="<Other>" type="Node2D" parent="."]\n'
                         '[node name="Player" parent="<Other>" instance=ExtResource("4")]\n')
        self.assertEqual(command("init", self.root, "--force")[0], 0)
        code, msg = command("onboard", "--project", self.root, "--source", "expectrail.project.draft.json",
                            "--out", self.out)
        self.assertEqual(code, 0, msg)
        self.assertEqual(Page(self.out).configs, [])
        self.assertIn("&lt;Other&gt;/Player", self.out.read_text())
        self.assertIn("No complete choice", self.out.read_text())
