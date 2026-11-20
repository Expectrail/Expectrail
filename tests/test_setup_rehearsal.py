"""The setup rehearsal (#260): from a game with no config to a verdict, as a new developer gets there.

The offline tests hold the record and the safety of the environment. ``RealGodotTest`` runs the whole
rehearsal on Crate Run with the engine (about a minute); without Godot and a virtual display it is
skipped, unless ``EXPECTRAIL_ENGINE_TESTS=required``. The bundled game's rehearsal takes about ten
minutes and is run by hand (docs/new-work/2026-11-20-setup-rehearsal.md has its record).
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import setup_rehearsal as sr


class OfflineTest(unittest.TestCase):
    def test_no_vision_setting_reaches_a_command_it_runs(self):
        with mock.patch.dict(os.environ, MODEL_API_KEY="secret-looking", EXPECTRAIL_SAM_USD_CAP="5"):
            env = sr._environment()
        self.assertNotIn("MODEL_API_KEY", env)
        self.assertNotIn("EXPECTRAIL_SAM_USD_CAP", env)
        self.assertEqual(env["PYTHONPATH"].split(os.pathsep)[0], str(sr.REPO))

    def test_what_it_keeps_has_no_progress_line_and_no_local_path(self):
        text = ("job abc: queued\njob abc: observing\njob abc: completed\njob abc: completed, reject\n"
                "  1 of 1 public checks fail after the change\n  Budget record: file:///home/x/job-budget.json\n")
        self.assertEqual(sr._said(text), ["job abc: completed, reject", "  1 of 1 public checks fail after the change"])

    def test_a_step_that_ended_differently_is_marked_in_the_record(self):
        result = {"project": "crate-run", "initWrote": sr.PENDING, "route": {"ticks": 243, "events": 10}, "steps": [
            {"step": "verify, seeded bug", "command": "expectrail verify --project head", "exit": 2,
             "expectedExit": 1, "seconds": 20.0, "said": ["job a: completed, needs-review"], "ok": False,
             "problem": "exit 2, expected 1"},
            {"step": "the person's step (taken by this rehearsal on the copy)", "did": ["chose res://crate.svg"], "ok": True}]}
        text = sr.markdown(result)
        self.assertIn("| 2 (1) **exit 2, expected 1** |", text)
        self.assertIn("chose res://crate.svg", text)

    def test_every_project_names_a_game_that_exists_and_a_bug(self):
        for name, project in sr.PROJECTS.items():
            self.assertTrue((project["source"] / "project.godot").is_file(), name)
            self.assertTrue(callable(project["bug"]), name)
        self.assertTrue(sr.APPROVED.is_file())

    def test_a_bug_that_no_longer_applies_stops_the_rehearsal(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "player.gd").write_text("extends Node\n", encoding="utf-8")
            with self.assertRaises(sr.RehearsalError):
                sr._crate_bug(Path(tmp))


class ReviewPageChoiceTest(unittest.TestCase):
    """The person's image comes from the review page's own download link (#688), not a scripted edit."""

    def test_crate_run_choice_is_the_page_download_labelled_as_not_drawn_under_the_player(self):
        import json
        import shutil
        from tests.test_init_inspect import command
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "game"
            shutil.copytree(sr.PROJECTS["crate-run"]["source"], game)
            (game / sr.CONFIG).unlink()
            self.assertEqual(command("init", game)[0], 0)
            page = Path(tmp) / "review.html"
            self.assertEqual(command("onboard", "--project", game, "--out", page)[0], 0)
            config, card = sr.page_choice(page, "res://crate.svg")
            draft = json.loads((game / sr.PENDING).read_text())["config"]
        self.assertEqual(config["bindings"]["player"], {"node": "Player", "texture": "res://crate.svg"})
        self.assertEqual({k: v for k, v in config.items() if k != "bindings"},
                         {k: v for k, v in draft.items() if k != "bindings"})
        self.assertIn("Not drawn under Player", card)

    def test_a_page_that_does_not_offer_the_image_once_stops_the_rehearsal(self):
        import base64
        import json
        link = lambda texture: ('<article><p>x</p><a download="expectrail.project.json" href="data:application/json;base64,'
                                + base64.b64encode(json.dumps({"bindings": {"player": {"node": "P", "texture": texture}}})
                                                   .encode()).decode() + '">Use</a></article>')
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "review.html"
            for body in ("", link("res://a.png"), link("res://crate.svg") * 2):
                page.write_text("<main>" + body + "</main>", encoding="utf-8")
                with self.assertRaises(sr.RehearsalError):
                    sr.page_choice(page, "res://crate.svg")
            page.write_text('<article><a download="expectrail.project.json" href="https://example.invalid/x">Use</a>'
                            "</article>", encoding="utf-8")
            with self.assertRaises(sr.RehearsalError):
                sr.page_choice(page, "res://crate.svg")


class RealGodotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.tool_requirements import godot_binary, require_tool
        engine = godot_binary()
        require_tool("xvfb-run")
        configured = mock.patch.dict(os.environ, EXPECTRAIL_GODOT=str(engine))
        configured.start()
        cls.addClassCleanup(configured.stop)

    def test_crate_run_goes_from_no_config_to_a_reject_of_its_seeded_bug(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = sr.rehearse("crate-run", Path(tmp))
        self.assertTrue(result["ok"], sr.markdown(result))
        self.assertEqual(result["initWrote"], sr.PENDING)   # the crate is a polygon: a person chooses its image
        # init, its refusal, the review page (#688), the person's step, needs-review, reject.
        self.assertEqual([s.get("exit") for s in result["steps"]], [0, 0, 5, 0, None, 2, 1])
        person = result["steps"][4]["did"][0]
        self.assertIn("on the review page", person)
        self.assertIn("Not drawn under Player", person)


if __name__ == "__main__":
    unittest.main()
