"""A route that pauses the game keeps running to its last tick, and can unpause it.

`tests/projects/pause-input` pauses its whole scene tree on a key, as the bundled game's pause menu
does (`game/platformer/game.gd`, `toggle_pause`). Until November 13, 2026 the harness, an autoload,
inherited the root's process mode and was paused with the game: the press that would unpause was
never sent, no more rows were recorded, and the replay never reached its last tick (measured: no
trace after two minutes on a 70-tick route). So no route could reach the bundled game's pause menu,
the only place its coin counter is drawn (#285: two of the public bench's misses).

The engine tests run where Godot is; CI sets EXPECTRAIL_ENGINE_TESTS=required in the job
`capture-smoke`, so a skip there is a failure. Standard library only.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.tool_requirements import require_tool
from harness import run as hr
from tests.test_event_input import real_godot

REPO = Path(__file__).resolve().parent.parent
PROJECT = REPO / "tests" / "projects" / "pause-input"
SCRIPT = REPO / "harness" / "godot" / "expectrail_harness.gd"


class HarnessScriptTest(unittest.TestCase):
    def test_the_harness_runs_while_the_tree_is_paused(self):
        code = "\n".join(line.split("#", 1)[0] for line in SCRIPT.read_text(encoding="utf-8").splitlines())
        ready = code.split("func _ready() -> void:", 1)[1].split("\nfunc ", 1)[0]
        self.assertEqual(re.findall(r"process_mode\s*=\s*([\w.]+)", ready), ["Node.PROCESS_MODE_ALWAYS"])
        # Set only on a harness run: after the early return for a run with no route.
        self.assertLess(ready.index('if not args.has("route")'), ready.index("process_mode"))
        # The recorder is a child and inherits it; nothing sets it back.
        self.assertEqual(len(re.findall(r"process_mode\s*=", code)), 1)

    def test_the_project_pauses_from_a_root_that_always_runs(self):
        scene = (PROJECT / "project" / "main.tscn").read_text(encoding="utf-8")
        self.assertRegex(scene, r'\[node name="Main" type="Node2D"\]\nprocess_mode = 3\n')
        self.assertRegex(scene, r'\[node name="Player" type="Node2D" parent="\."\]\nprocess_mode = 1\n')
        route = json.loads((PROJECT / "routes" / "pause.json").read_text(encoding="utf-8"))
        self.assertEqual({e["action"] for e in route["events"]}, {"right", "pause"})


class PauseInputTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_tool('xvfb-run')
        godot = real_godot()
        cls.tmp = Path(tempfile.mkdtemp(prefix="expectrail-pause-input-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        cls.runs = {}
        for name, frames in (("drawn", True), ("headless", False)):
            hr.run(PROJECT / "routes" / "pause.json", cls.tmp / name, game=PROJECT / "project", godot=godot,
                   capture_frames=frames)
            trace = json.loads((cls.tmp / name / "trace.json").read_text(encoding="utf-8"))
            cls.runs[name] = {row["tick"]: row["player"] for row in trace["rows"]}
        cls.at = cls.runs["drawn"]

    def test_the_route_reaches_its_last_tick(self):
        self.assertEqual(sorted(self.at), list(range(70)))
        self.assertEqual(self.runs["headless"], self.at)

    def test_the_player_walks_until_the_pause(self):
        # right from tick 2: 2 px a tick, up to tick 19.
        self.assertEqual([self.at[t][0] for t in (0, 2, 3, 19)], [100.0, 102.0, 104.0, 136.0])

    def test_rows_are_recorded_while_paused_and_nothing_moves(self):
        # pause at tick 20: the harness presses before the game moves, so tick 20 is already still.
        self.assertEqual({self.at[t][0] for t in range(20, 40)}, {136.0})

    def test_a_press_while_paused_unpauses(self):
        # the second pause press at tick 40 is sent although the tree is paused, and the walk goes on
        # until right is released at 60.
        self.assertEqual([self.at[t][0] for t in (40, 41, 59, 60, 69)], [138.0, 140.0, 176.0, 176.0, 176.0])


if __name__ == "__main__":
    unittest.main()
