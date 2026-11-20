"""Opening init's pending binding review reads the saved inputs offline."""
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail import app, input_discovery, onboard, onboarding
from tests.check_onboarding_games import ROOT, contents
from tests.test_init_inspect import command


class SavedRouteReviewTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.game = Path(tmp.name) / "game"
        shutil.copytree(ROOT / "tests/projects/pointer-menu", self.game)
        self.settings = self.game / "project.godot"
        with self.settings.open("a") as settings:
            settings.write('\n[input]\npause={"deadzone":0.5,"events":[]}\n')
        self.out = self.game.parent / "review.html"
        self.info = onboarding.inspect(self.game)
        self.assertTrue(input_discovery.needed(self.info))

    def save(self, event, *, legacy=False):
        doc = {"format": "expectrail.route/v0", "name": "draft", "ticks": 2, "events": [event]}
        docs = onboarding.proposal(self.game, self.info, planned_route=doc)
        if legacy:
            del docs["imageSuggestions"]
        onboarding.publish(self.game, docs, force=True)
        return self.game / docs["config"]["routes"][0]

    def review(self, *, valid):
        before = contents(self.game)
        with mock.patch.object(input_discovery, "probe", side_effect=AssertionError("game probe attempted")) as probe:
            code, msg = command("onboard", "--project", self.game, "--out", self.out)
            probe.assert_not_called()
        self.assertEqual(contents(self.game), before)
        self.assertEqual(code, 0 if valid else 5, msg)
        self.assertEqual(self.out.exists(), valid)
        return self.out.read_text() if valid else msg

    def test_old_action_only_menu_draft_shows_its_saved_input_and_next_step(self):
        self.save({"tick": 1, "action": "pause", "pressed": True}, legacy=True)
        page = self.review(valid=True)
        self.assertIn("<code>pause</code>", page)
        self.assertIn("only uses pause", page)
        self.assertIn("exercise gameplay", page)

    def test_archived_two_player_draft_accepts_only_its_historical_binding_message(self):
        # Reproduce the archived draft's scene candidates and settings without a replay.
        preview = ROOT / "tests/fixtures/breakout-legacy-init.json"
        original = json.loads(preview.read_text())
        scene = self.game / "game.tscn"
        scene.write_text('[gd_scene format=3]\n[node name="Game" type="Node2D"]\n'
                         '[node name="Paddle" type="CharacterBody2D" parent="."]\n'
                         '[node name="Ball" type="RigidBody2D" parent="."]\n')
        self.settings.write_text(self.settings.read_text().replace("main.tscn", scene.name)
                                 .replace("viewport_width=320", "viewport_width=360")
                                 .replace("viewport_height=180", "viewport_height=640"))
        onboarding.publish(self.game, original, force=False)
        self.assertIn("only uses pause", self.review(valid=True))
        with mock.patch.object(input_discovery, "probe", side_effect=AssertionError("game probe attempted")):
            self.assertIn("only uses pause", app.setup_preview(self.game)[0])
        self.out.unlink()
        original["unresolvedBindings"] = ["Supply only an image."]
        onboarding.publish(self.game, original, force=True)
        self.assertIn("current project", self.review(valid=False))
        with self.assertRaisesRegex(ValueError, "current"):
            app.setup_preview(self.game)

    def test_pointer_draft_shows_its_saved_input_and_selected_player(self):
        self.info = onboarding.inspect(self.game, "Player")
        self.save({"tick": 1, "pointer": {"position": [319, 179]}})
        page = self.review(valid=True)
        self.assertIn("<code>pointer move</code>", page)
        self.assertIn("Player node selected for init", page)

    def test_digest_and_event_contract_are_checked_before_showing_inputs(self):
        path = self.save({"tick": 1, "action": "pause", "pressed": True})
        path.write_bytes(path.read_bytes() + b" ")
        self.assertIn("route has changed", self.review(valid=False))
        self.save({"tick": 1, "pointer": None})
        self.assertIn("route", self.review(valid=False))

    def test_readdressing_edited_route_bytes_does_not_make_them_an_init_route(self):
        original = self.save({"tick": 1, "action": "pause", "pressed": True})
        raw = original.read_bytes() + b" "
        name = "routes/draft-first-" + hashlib.sha256(raw).hexdigest()[:16] + ".json"
        (self.game / name).write_bytes(raw)
        pending = self.game / onboard.PENDING
        doc = json.loads(pending.read_bytes())
        doc["config"]["routes"] = [name]
        pending.write_bytes(onboarding.encode(doc))
        self.assertIn("route", self.review(valid=False))
        with self.assertRaisesRegex(ValueError, "route"):
            app.setup_preview(self.game)

    def test_tick_input_and_viewport_bounds_use_the_current_project(self):
        for event, message in [
            ({"tick": 2, "action": "pause", "pressed": True}, "end"),
            ({"tick": 1, "action": "missing", "pressed": True}, "input"),
            ({"tick": 1, "pointer": {"position": [320, 179]}}, "viewport"),
        ]:
            with self.subTest(event=event):
                self.save(event)
                self.assertIn(message, self.review(valid=False))
        self.save({"tick": 1, "pointer": {"position": [319, 179]}})
        self.settings.write_text(self.settings.read_text().replace("viewport_width=320", "viewport_width=240"))
        self.assertIn("viewport", self.review(valid=False))

    def test_changed_binding_candidates_are_refused(self):
        self.save({"tick": 1, "action": "pause", "pressed": True})
        scene = self.game / "main.tscn"
        scene.write_text(scene.read_text().replace('name="Player"', 'name="Paddle"'))
        self.assertIn("current project", self.review(valid=False))

    def test_non_menu_draft_must_match_the_input_map_plan(self):
        scene = self.game / "main.tscn"
        scene.write_text(scene.read_text().split('[node name="Menu"')[0])
        self.settings.write_text(self.settings.read_text().replace("pause=", "move_right="))
        self.info = onboarding.inspect(self.game)
        self.assertFalse(input_discovery.needed(self.info))
        docs = onboarding.proposal(self.game, self.info)
        onboarding.publish(self.game, docs, force=True)
        self.assertIn("<code>move_right</code>", self.review(valid=True))
        self.out.unlink()
        self.save({"tick": 0, "action": "move_right", "pressed": True})
        self.assertIn("current project", self.review(valid=False))
