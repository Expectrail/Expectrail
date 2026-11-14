"""A game that reads its input as events is driven by a route, on the tick the route names.

`tests/projects/event-input` reads input four ways and writes each into the player's position:
polled in a tick, an event in `_input`, an event in `_unhandled_input`, and a button's shortcut.
Until November 12, 2026 the harness pressed actions with `Input.action_press`, which sets the
action's state and sends no event: the same route left that player where it started, the replay
ended with exit 0 and nothing said so.

The engine tests run where Godot is; CI sets EXPECTRAIL_ENGINE_TESTS=required in the job
`capture-smoke`, so a skip there is a failure. Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.tool_requirements import require_tool
from harness import run as hr

REPO = Path(__file__).resolve().parent.parent
PROJECT = REPO / "tests" / "projects" / "event-input"
SCRIPT = REPO / "harness" / "godot" / "expectrail_harness.gd"
REQUIRED = os.environ.get("EXPECTRAIL_ENGINE_TESTS") == "required"


def real_godot() -> Path:
    named = os.environ.get("EXPECTRAIL_GODOT")
    found = [Path(named)] if named else sorted((REPO / "tools" / "godot").glob("Godot_v*"))
    found = [p for p in found if p.is_file()]
    if not found:
        if REQUIRED:
            raise AssertionError("this job must have Godot: run harness/get_godot.sh first")
        raise unittest.SkipTest("Godot is not downloaded (harness/get_godot.sh)")
    return found[0]


class HarnessScriptTest(unittest.TestCase):
    def test_every_press_is_sent_as_an_event(self):
        code = "\n".join(line.split("#", 1)[0] for line in SCRIPT.read_text(encoding="utf-8").splitlines())
        # The calls that set an action's state and send no event.
        self.assertEqual(re.findall(r"Input\.action_(?:press|release)\s*\(", code), [])
        self.assertEqual(len(re.findall(r"Input\.parse_input_event\s*\(", code)), 1)
        # Held by the engine until the next drawn frame unless sent on at once.
        self.assertRegex(code, r"Input\.parse_input_event\([^\n]*\)\s*\n\s*Input\.flush_buffered_events\(\)")

    def test_the_project_binds_keys_to_two_actions_and_none_to_the_others(self):
        # What the engine test relies on: a key for start and menu, nothing for hop and right.
        text = (PROJECT / "project" / "project.godot").read_text(encoding="utf-8")
        bound = {m.group(1): "InputEventKey" in m.group(2)
                 for m in re.finditer(r'^(\w+)=\{\n"deadzone": [\d.]+,\n"events": \[(.*?)\]\n\}', text, re.M | re.S)}
        self.assertEqual(bound, {"start": True, "hop": False, "right": False, "menu": True})
        route = json.loads((PROJECT / "routes" / "events.json").read_text(encoding="utf-8"))
        self.assertEqual({e["action"] for e in route["events"]}, set(bound))


class EventInputTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_tool('xvfb-run')
        godot = real_godot()
        cls.tmp = Path(tempfile.mkdtemp(prefix="expectrail-event-input-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        cls.runs = {}
        for name, frames in (("drawn", True), ("headless", False)):   # as the gate replays, and as discovery does
            hr.run(PROJECT / "routes" / "events.json", cls.tmp / name, game=PROJECT / "project", godot=godot,
                   capture_frames=frames)
            trace = json.loads((cls.tmp / name / "trace.json").read_text(encoding="utf-8"))
            cls.runs[name] = {row["tick"]: row["player"] for row in trace["rows"]}
        cls.at = cls.runs["drawn"]

    def test_drawn_and_headless_replays_agree(self):
        self.assertEqual(len(self.at), 70)
        self.assertEqual(self.runs["headless"], self.at)

    def test_nothing_moves_before_the_game_is_started(self):
        # right is held from tick 2; the game ignores it until start arrives.
        self.assertEqual([self.at[t] for t in (0, 2, 9)], [[100.0, 100.0]] * 3)

    def test_a_bound_key_reaches_unhandled_input_on_its_tick(self):
        # start (Enter) at tick 10: the game is started in that tick and right, already held, moves
        # the player 2 px in it.
        self.assertEqual(self.at[10], [102.0, 100.0])
        self.assertEqual(self.at[11], [104.0, 100.0])

    def test_an_action_with_no_key_reaches_input_on_its_tick(self):
        # hop at ticks 20 and 30, 8 px each; a release does nothing.
        self.assertEqual([self.at[t][1] for t in (19, 20, 22, 29, 30, 49)], [100.0, 92.0, 92.0, 92.0, 84.0, 84.0])

    def test_a_polled_action_is_held_and_released_on_its_ticks(self):
        # right from tick 2 (counted from the start at 10) to its release at 40: 30 ticks, 60 px.
        self.assertEqual([self.at[t][0] for t in (39, 40, 41, 69)], [160.0, 160.0, 160.0, 160.0])
        self.assertEqual(self.at[38][0], 158.0)

    def test_a_bound_key_presses_the_button_whose_shortcut_it_is(self):
        # menu (M) at tick 50 is the shortcut of a button; its press drops the player to y = 300.
        self.assertEqual(self.at[49], [160.0, 84.0])
        self.assertEqual(self.at[50], [160.0, 300.0])
        self.assertEqual(self.at[69], [160.0, 300.0])


if __name__ == "__main__":
    unittest.main()
