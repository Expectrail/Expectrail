"""Auto-route decisions without Godot; real harness runs are in test_auto_route_engine."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from expectrail import cli, contracts, route

REPO = Path(__file__).resolve().parent.parent
CRATE = REPO / "tests/projects/crate-run/project"
BUNDLED = REPO / "game/platformer"


class Replay:
    """Offline harness stand-in: input holds move a point; every call writes a complete trace."""
    def __init__(self, alter=None):
        self.calls = []
        self.alter = alter
        self.traces = []

    def __call__(self, candidate, out, **kwargs):
        doc = json.loads(candidate.read_text())
        self.calls.append((doc, kwargs))
        _, rate, _ = route.input_map(kwargs["game"])
        pressed, x, rows = set(), 0, []
        for tick in range(doc["ticks"]):
            for event in doc["events"]:
                if event["tick"] == tick:
                    if event["pressed"]:
                        pressed.add(event["action"])
                    else:
                        pressed.remove(event["action"])
            x += sum(1 for action in pressed if route.is_movement(action))
            rows.append({"tick": tick, "frame": 0, "player": [x, 0], "enemies": []})
        trace = {"format": "expectrail.trace/v0", "ticks": doc["ticks"],
                 "physicsTicksPerSecond": rate, "rows": rows}
        if self.alter:
            self.alter(trace, len(self.calls))
        self.traces.append(trace)
        out.mkdir()
        (out / "trace.json").write_text(json.dumps(trace))
        return {"game": {"tree": "same-project"}}


class AutoRouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / "new/route.json"

    def project(self, text):
        project = self.root / "project"
        project.mkdir(exist_ok=True)
        (project / "project.godot").write_text(text)
        return project

    def run_route(self, project=CRATE, replay=None):
        replay = replay or Replay()
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = route.auto_route(project, self.out, replay=replay)
        return code, stream.getvalue(), replay

    def test_crate_and_bundled_maps_are_checked_three_times_offline(self):
        for project in (CRATE, BUNDLED):
            with self.subTest(project=project):
                code, text, replay = self.run_route(project)
                self.assertEqual(code, 0)
                self.assertEqual(len(replay.calls), 3)
                doc = json.loads(self.out.read_text())
                contracts.validate(doc, "route")
                self.assertTrue(all(call[0] == doc for call in replay.calls))
                self.assertTrue(all(call[1] == {"game": project.resolve(), "capture_frames": False}
                                    for call in replay.calls))
                actions, _, fallback = route.input_map(project)
                self.assertFalse(fallback)
                self.assertEqual({e["action"] for e in doc["events"]}, set(actions))
                self.assertIn("Three complete traces are identical", text)
                self.assertIn("player (Player) moved", text)
                self.assertEqual(replay.traces[0], replay.traces[2])
                self.out.unlink()

    def test_no_custom_actions_uses_builtins(self):
        for text in ('[application]\nconfig/name="Empty"\n', '[input]\n; no actions yet\n'):
            with self.subTest(text=text):
                code, summary, replay = self.run_route(self.project(text))
                self.assertEqual(code, 0)
                doc = replay.calls[0][0]
                self.assertEqual({e["action"] for e in doc["events"]}, set(route.FALLBACK_ACTIONS))
                self.assertIn("No custom input actions", summary)
                self.out.unlink()

    def test_explicit_ui_actions_are_preserved_without_adding_fallbacks(self):
        actions, rate, fallback = route.input_map(self.project('[input]\nui_left={}\nshoot={}\n'))
        self.assertEqual((actions, rate, fallback), (["shoot", "ui_left"], 60, False))

    def test_parser_handles_nested_events_comments_quoted_names_and_section_like_strings(self):
        project = self.project('''; ignore [input]
[application]
config/description="[input];not an action"
[input]
"move left"={ ; pause comment
"deadzone": 0.2,
"events": [Object(InputEventKey,"unicode":91,"label":"escaped \\\";[x]"),
Object(InputEventKey,"unicode":93)]
}
shoot={"events": []} ; trailing comment
[physics]
common/physics_ticks_per_second=120
''')
        self.assertEqual(route.input_map(project), (["move left", "shoot"], 120, False))

    def test_invalid_map_never_silently_falls_back(self):
        for text in ('[input]\nleft={', '[input]\nleft={"events": [)}', '[input]\nleft="bad"',
                     '[input]\nleft={}\nleft={}', '[physics]\ncommon/physics_ticks_per_second=0',
                     '[input]\n"unfinished={}'):
            with self.subTest(text=text), self.assertRaises(route.RouteError):
                route.input_map(self.project(text))

    def test_fixed_pattern_is_balanced_with_pauses_and_uses_physics_rate(self):
        doc = route.make_route(["jump", "moveRight", "left"], 120)
        self.assertEqual(doc, route.make_route(["left", "jump", "moveRight"], 120))
        self.assertEqual(doc["seed"], 1)
        pairs = list(zip(doc["events"][::2], doc["events"][1::2]))
        self.assertEqual([a["action"] for a, _ in pairs], ["left", "moveRight", "jump", "jump", "jump"])
        self.assertEqual([b["tick"] - a["tick"] for a, b in pairs], [120, 120, 12, 12, 12])
        for press, release in pairs:
            self.assertTrue(press["pressed"])
            self.assertFalse(release["pressed"])
            self.assertEqual(press["action"], release["action"])
            self.assertLess(release["tick"], doc["ticks"])
        self.assertEqual(pairs[0][0]["tick"], 30)
        self.assertTrue(all(b[0]["tick"] - a[1]["tick"] == 30 for a, b in zip(pairs, pairs[1:])))

    def test_third_run_difference_reports_exact_ticks_and_writes_nothing(self):
        def alter(trace, n):
            if n == 3:
                for tick in (2, 3, 5):
                    trace["rows"][tick]["player"][0] += 1
        code, text, replay = self.run_route(replay=Replay(alter))
        self.assertEqual(code, 2)
        self.assertEqual(len(replay.calls), 3)
        self.assertIn("not yet deterministic under the harness", text)
        self.assertIn("2-3, 5", text)
        self.assertFalse(self.out.exists())

    def test_non_player_fields_and_header_are_compared(self):
        def alter(trace, n):
            if n == 2:
                trace["rows"][8]["enemies"] = [[1, 10, 20]]
                trace["levelSurfaces"] = []
        code, text, _ = self.run_route(replay=Replay(alter))
        self.assertEqual(code, 2)
        self.assertIn("inclusive): 8.", text)
        self.assertIn("Differing trace metadata: levelSurfaces", text)
        self.assertFalse(self.out.exists())

    def test_stationary_and_unbound_players_are_not_called_useful(self):
        for present in (False, True):
            def alter(trace, n):
                for row in trace["rows"]:
                    if present:
                        row["player"] = [0, 0]
                    else:
                        del row["player"]
            code, text, _ = self.run_route(replay=Replay(alter))
            self.assertEqual(code, 0)
            self.assertIn("did not move at all" if present else "movement is unknown", text)
            self.assertIn("not demonstrated useful", text)
            self.out.unlink()

    def test_empty_route_is_explicit_even_if_gravity_moves_player(self):
        doc = route.make_route([], 60)
        text = "\n".join(route.describe(doc, 60, {"rows": [{"player": [0, 0]}, {"player": [0, 1]}]}))
        self.assertIn("Empty route: no actions were pressed", text)
        self.assertIn("Movement alone does not prove", text)

    def test_returning_to_start_still_counts_as_moving(self):
        text = "\n".join(route.describe(route.make_route(["right"], 60), 60,
                                       {"rows": [{"player": [0, 0]}, {"player": [1, 0]}, {"player": [0, 0]}]}))
        self.assertIn("player (Player) moved", text)

    def test_summary_names_actions_durations_and_pauses(self):
        _, text, _ = self.run_route()
        self.assertIn("left: 1 press(es), 60 ticks (1 seconds) each", text)
        self.assertIn("jump: 3 press(es), 6 ticks (0.1 seconds) each", text)
        self.assertIn("Pauses: 15 ticks (0.25 seconds)", text)

    def test_incomplete_or_malformed_trace_does_not_publish(self):
        def bad_length(trace, n):
            trace["rows"].pop()
        def bad_tick(trace, n):
            trace["rows"][4]["tick"] = 3
        def bad_rate(trace, n):
            trace["physicsTicksPerSecond"] = 120
        def bad_point(trace, n):
            trace["rows"][0]["player"] = [float("nan"), 0]
        for alteration in (bad_length, bad_tick, bad_rate, bad_point):
            with self.subTest(alteration=alteration), self.assertRaises(route.RouteError):
                self.run_route(replay=Replay(alteration))
            self.assertFalse(self.out.exists())

    def test_changed_project_is_not_certified(self):
        replay = Replay()
        def changing(*args, **kwargs):
            result = replay(*args, **kwargs)
            result["game"]["tree"] = str(len(replay.calls))
            return result
        with self.assertRaisesRegex(route.RouteError, "project changed"):
            self.run_route(replay=changing)
        self.assertFalse(self.out.exists())

    def test_failed_replay_does_not_publish(self):
        with patch("harness.run.run", side_effect=SystemExit("engine stopped")), contextlib.redirect_stderr(io.StringIO()) as err:
            code = cli.main(["route", "--project", str(CRATE), "--auto", "--out", str(self.out)])
        self.assertEqual(code, 5)
        self.assertIn("engine stopped", err.getvalue())
        self.assertFalse(self.out.exists())

    def test_existing_output_is_never_overwritten_or_replayed(self):
        self.out.parent.mkdir()
        self.out.write_text("keep this")
        replay = Replay()
        with self.assertRaisesRegex(route.RouteError, "already exists"):
            self.run_route(replay=replay)
        self.assertEqual(self.out.read_text(), "keep this")
        self.assertEqual(replay.calls, [])

    def test_output_created_during_replays_is_never_clobbered(self):
        replay = Replay()
        def concurrent(*args, **kwargs):
            result = replay(*args, **kwargs)
            if len(replay.calls) == 3:
                self.out.parent.mkdir()
                self.out.write_text("someone else's route")
            return result
        with self.assertRaises(FileExistsError):
            self.run_route(replay=concurrent)
        self.assertEqual(self.out.read_text(), "someone else's route")
        self.assertEqual(list(self.out.parent.glob(".expectrail-route-*")), [])

    def test_publish_failure_leaves_no_partial_route(self):
        with patch("expectrail.route.os.link", side_effect=OSError("disk unavailable")):
            with self.assertRaisesRegex(OSError, "disk unavailable"):
                self.run_route()
        self.assertFalse(self.out.exists())
        self.assertEqual(list(self.out.parent.glob(".expectrail-route-*")), [])

    def test_command_dispatch_and_invalid_options(self):
        with patch("harness.run.run", Replay()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["route", "--project", str(CRATE), "--auto", "--out", str(self.out)]), 0)
        for args in (["route"], ["--jobs-root", "jobs", "route"],
                     ["route", "--project", str(CRATE), "--out", str(self.out)]):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(args), 5)

    def test_example_is_the_same_route_the_command_generates(self):
        example = json.loads((REPO / "contracts/examples/auto-route.json").read_text())
        self.assertEqual(example, route.make_route(["left", "right", "jump"], 60))
        contracts.validate(example, "route")

    def test_pause_clock_is_kept_running_in_the_harness(self):
        source = (REPO / "harness/godot/expectrail_harness.gd").read_text()
        self.assertIn("process_mode = Node.PROCESS_MODE_ALWAYS", source)
        self.assertIn("add_child(_recorder)", source)  # recorder inherits its parent's process mode
