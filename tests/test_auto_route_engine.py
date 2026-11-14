"""Opt-in real Godot checks; the same command decisions always run offline in test_auto_route.

Run EXPECTRAIL_ENGINE_TESTS=required python3 -m unittest tests.test_auto_route_engine -v.
No display or rendered frames are needed. No model is called.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail.route import auto_route
from harness import run as harness

REPO = Path(__file__).resolve().parent.parent


@unittest.skipUnless(os.environ.get("EXPECTRAIL_ENGINE_TESTS") == "required",
                     "set EXPECTRAIL_ENGINE_TESTS=required to run the real Godot auto-route checks")
class AutoRouteEngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="expectrail-auto-route-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / "route.json"
        self.traces = []
        self.records = []

    def replay(self, candidate, out, **kwargs):
        record = harness.run(candidate, out, **kwargs)
        self.records.append(record)
        self.traces.append(json.loads((out / "trace.json").read_text()))
        return record

    def run_route(self, project):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = auto_route(project, self.out, replay=self.replay)
        # Leave a useful record in the verbose test log, including the actual engine version.
        print(output.getvalue())
        print("Engine:", self.records[0]["engine"])
        return code, output.getvalue()

    def check_moving(self, project):
        code, output = self.run_route(project)
        self.assertEqual(code, 0, output)
        self.assertTrue(self.out.is_file())
        self.assertEqual(len(self.traces), 3)
        self.assertEqual(self.traces[0], self.traces[1])
        self.assertEqual(self.traces[0], self.traces[2])
        positions = [row["player"] for row in self.traces[0]["rows"] if "player" in row]
        self.assertGreater(len({tuple(p) for p in positions}), 1)
        self.assertGreater(max(p[0] for p in positions) - min(p[0] for p in positions), 1.0)
        self.assertIn("player (Player) moved", output)

    def test_bundled_game(self):
        self.check_moving(REPO / "game/platformer")

    def test_crate_run(self):
        self.check_moving(REPO / "tests/projects/crate-run/project")

    def test_unseeded_random_source_reports_ticks_without_writing_route(self):
        project = self.root / "random-project"
        shutil.copytree(REPO / "tests/projects/crate-run/project", project)
        # A local RNG explicitly randomized from entropy, unaffected by the harness's global seed.
        (project / "player.gd").write_text('''extends CharacterBody2D
var rng := RandomNumberGenerator.new()
func _ready() -> void:
    rng.randomize()
func _physics_process(_delta: float) -> void:
    position.x = rng.randf_range(10.0, 10000.0)
''')
        code, output = self.run_route(project)
        self.assertEqual(code, 2)
        self.assertFalse(self.out.exists())
        self.assertEqual(len(self.traces), 3)
        differing = [i for i, row in enumerate(self.traces[0]["rows"])
                     if any(row != trace["rows"][i] for trace in self.traces[1:])]
        self.assertTrue(differing)
        self.assertIn("Differing ticks", output)
        self.assertIn("not yet deterministic under the harness", output)

    def test_pause_and_resume_keep_clock_running_and_game_obeys_pause(self):
        project = self.root / "pause-project"
        project.mkdir()
        (project / "project.godot").write_text('''config_version=5
[application]
run/main_scene="res://main.tscn"
[input]
right={"events": []}
toggle_pause={"events": []}
[rendering]
renderer/rendering_method="gl_compatibility"
''')
        (project / "main.tscn").write_text('''[gd_scene load_steps=3 format=3]
[ext_resource type="Script" path="res://main.gd" id="1"]
[ext_resource type="Script" path="res://player.gd" id="2"]
[node name="Main" type="Node2D"]
process_mode = 3
script = ExtResource("1")
[node name="Player" type="Node2D" parent="."]
process_mode = 1
script = ExtResource("2")
''')
        (project / "main.gd").write_text('''extends Node2D
func _input(event: InputEvent) -> void:
    if event.is_action_pressed("toggle_pause"):
        get_tree().paused = not get_tree().paused
''')
        (project / "player.gd").write_text('''extends Node2D
func _physics_process(_delta: float) -> void:
    position.x += 1.0
''')
        self.check_moving(project)
        doc = json.loads(self.out.read_text())
        pauses = [e["tick"] for e in doc["events"] if e["action"] == "toggle_pause" and e["pressed"]]
        rows = self.traces[0]["rows"]
        self.assertEqual(len(pauses), 3)
        self.assertEqual(rows[pauses[0]]["player"], rows[pauses[1] - 1]["player"])
        self.assertGreater(rows[pauses[2] - 1]["player"][0], rows[pauses[1]]["player"][0])
        self.assertEqual(rows[pauses[2]]["player"], rows[-1]["player"])
