"""`expectrail inspect --at-tick N` (#260): the bound objects at one tick of a headless replay.

Offline tests replay with a stand-in that writes a configured trace; the real-engine tests replay the
config-lane and crate-run fixtures in Godot and compare with a direct harness replay of the same route.
"""
import copy
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail import cli, inspection
from tests import cli_capture

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "contracts" / "examples" / "inspection.json"


def role(ident, name, box, visible=True, source="drawing"):
    return {"id": ident, "role": name, "worldBox": box, "box": box, "visible": visible, "boundsSource": source}


def stand_in_trace(ticks=4):
    rows = []
    for t in range(ticks):
        objects = [role("Actors/Avatar", "player", [68 + t, 104, 92 + t, 128])]
        if t >= 2:  # the coin spawns at tick 2, and a second one at the same path replaces the first at tick 3
            objects.append(role("Coins/Coin" if t == 2 else "Coins/Coin#2", "coin", [30, 20, 36, 30], visible=t == 2))
        rows.append({"tick": t, "player": [80 + t, 116], "view": [1, 0, 0, 1, 0, 0], "roleObjects": objects})
    return {"format": "expectrail.trace/v0", "ticks": ticks, "physicsTicksPerSecond": 60, "viewport": [360, 240],
            "capabilities": {"roleBoxes": True}, "bindings": {}, "rows": rows}


class StandIn:
    def __init__(self, trace=None, error=None):
        self.trace, self.error, self.calls = trace if trace is not None else stand_in_trace(), error, []

    def __call__(self, route, out, **options):
        self.calls.append((route, options))
        if self.error:
            raise self.error
        out.mkdir(parents=True)
        (out / "trace.json").write_text(json.dumps(self.trace), encoding="utf-8")
        return {"game": {"tree": "f" * 64}}


class Fixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="expectrail-inspect-test-")
        self.addCleanup(tmp.cleanup)
        self.game = Path(tmp.name) / "game"
        shutil.copytree(ROOT / "tests/projects/config-lane", self.game)
        self.config_path = self.game / "expectrail.project.json"
        self.bind({"coin": {"group": "coin", "texture": "res://square.svg"}})

    def bind(self, extra=None, **fields):
        doc = json.loads(self.config_path.read_text())
        doc["bindings"].update(extra or {})
        doc.update(fields)
        self.config_path.write_text(json.dumps(doc))

    def refused(self, needle, *args, **kwargs):
        with self.assertRaises(inspection.InspectionError) as caught:
            inspection.document(self.game, *args, **kwargs)
        self.assertIn(needle, str(caught.exception))
        return str(caught.exception)


class WriterTest(Fixture):
    def test_each_bound_object_at_the_tick_with_its_node_box_and_visibility(self):
        replay = StandIn()
        doc = inspection.document(self.game, 1, replay=replay)
        self.assertEqual(inspection.problems(doc), [])
        self.assertEqual(doc["tick"], 1)
        self.assertEqual(doc["lastTick"], 3)
        self.assertEqual(doc["objects"], [{"role": "player", "node": "Actors/Avatar", "generation": 1,
                                           "box": [69, 104, 93, 128], "worldBox": [69, 104, 93, 128],
                                           "visible": True, "onScreen": True, "boundsSource": "drawing"}])
        self.assertEqual(doc["absent"], [{"role": "coin", "selector": "group:coin"}])
        self.assertEqual(doc["route"]["from"], "config")
        self.assertEqual(doc["route"]["name"], "config-lane")
        self.assertEqual(len(doc["project"]["configSha256"]), 64)
        # The replay used the config read here, its capture rate and no frames.
        route, options = replay.calls[0]
        self.assertEqual(route, (self.game / "walk.json").resolve())
        self.assertIs(options["capture_frames"], False)
        self.assertIsNone(options["fps"])
        self.assertEqual(options["project"]["bindings"]["coin"]["group"], "coin")

    def test_a_spawned_hidden_and_replaced_object_is_reported_as_recorded(self):
        at2 = inspection.document(self.game, 2, replay=StandIn())
        coin = [o for o in at2["objects"] if o["role"] == "coin"][0]
        self.assertEqual((coin["node"], coin["generation"], coin["visible"]), ("Coins/Coin", 1, True))
        at3 = inspection.document(self.game, 3, replay=StandIn())
        coin = [o for o in at3["objects"] if o["role"] == "coin"][0]
        self.assertEqual((coin["node"], coin["generation"], coin["visible"]), ("Coins/Coin", 2, False))
        self.assertEqual(at3["absent"], [])
        self.assertIn("hidden", "\n".join(inspection.describe(at3)))

    def test_identity_reading(self):
        self.assertEqual(inspection.split_identity("Actors/Avatar"), ("Actors/Avatar", 1))
        self.assertEqual(inspection.split_identity("Coins/Coin#3"), ("Coins/Coin", 3))
        self.assertEqual(inspection.split_identity("Odd##2"), ("Odd#2", 1))   # a '#' in the name itself
        self.assertEqual(inspection.split_identity("Odd##2#2"), ("Odd#2", 2))
        for bad in ("", "#2", "Coin#0", None, 7):
            with self.subTest(bad=bad), self.assertRaises(inspection.InspectionError):
                inspection.split_identity(bad)

    def test_off_screen_is_computed_from_the_box(self):
        trace = stand_in_trace()
        trace["rows"][0]["roleObjects"][0]["box"] = [400, 10, 424, 34]
        doc = inspection.document(self.game, 0, replay=StandIn(trace))
        self.assertIs(doc["objects"][0]["onScreen"], False)
        self.assertIs(doc["objects"][0]["visible"], True)
        self.assertIn("visible, off screen", "\n".join(inspection.describe(doc)))

    def test_a_given_route_is_used_and_named(self):
        other = self.game / "other.json"
        other.write_text(json.dumps({"format": "expectrail.route/v0", "name": "other", "ticks": 4, "events": []}))
        replay = StandIn()
        doc = inspection.document(self.game, 0, other, replay=replay)
        self.assertEqual(doc["route"], {"name": "other", "sha256": inspection._sha256(other), "from": "argument"})
        self.assertEqual(replay.calls[0][0], other)


class RefusalTest(Fixture):
    """Every refusal names what to change; none gives a box."""

    def test_no_config_names_init(self):
        self.config_path.unlink()
        self.refused("expectrail init --project GAME", 0, replay=StandIn())

    def test_no_project_file(self):
        (self.game / "project.godot").unlink()
        self.refused("has no project.godot", 0, replay=StandIn())

    def test_empty_bindings(self):
        doc = json.loads(self.config_path.read_text()); doc["bindings"] = {}
        self.config_path.write_text(json.dumps(doc))
        # The config reader refuses it first, naming the field; the inspector's own check is the fallback.
        with self.assertRaises(ValueError) as caught:
            inspection.document(self.game, 0, replay=StandIn())
        self.assertIn("bindings must name at least one object", str(caught.exception))

    def test_no_route_names_the_route_command_and_option(self):
        doc = json.loads(self.config_path.read_text()); doc.pop("routes")
        self.config_path.write_text(json.dumps(doc))
        message = self.refused("--route ROUTE", 0, replay=StandIn())
        self.assertIn("expectrail route --project GAME --auto", message)

    def test_a_config_route_that_is_missing_or_a_link_out_of_the_project(self):
        (self.game / "walk.json").unlink()
        self.refused("does not exist", 0, replay=StandIn())
        outside = self.game.parent / "outside.json"
        outside.write_text(json.dumps({"ticks": 4}))
        (self.game / "walk.json").symlink_to(outside)
        self.refused("leads outside the project", 0, replay=StandIn())

    def test_a_given_route_that_does_not_exist(self):
        self.refused("no such route file", 0, self.game / "nope.json", replay=StandIn())

    def test_a_tick_past_the_route_is_refused_before_any_replay(self):
        replay = StandIn()
        self.refused("choose --at-tick from 0 to 119", 120, replay=replay)
        self.assertEqual(replay.calls, [])

    def test_a_tick_past_the_recorded_rows(self):
        self.refused("recorded ticks 0 to 3", 10, replay=StandIn())

    def test_a_negative_or_non_whole_tick(self):
        for bad in (-1, 1.5, True, "3"):
            with self.subTest(bad=bad):
                self.refused("whole number", bad, replay=StandIn())

    def test_a_trace_without_role_boxes_is_cannot_tell(self):
        for change in ("capability", "rows", "row-tick", "row-objects", "unbound-role", "bad-id", "bad-box"):
            trace = stand_in_trace()
            if change == "capability":
                trace["capabilities"] = {}
            elif change == "rows":
                trace["rows"] = []
            elif change == "row-tick":
                trace["rows"][1]["tick"] = 7
            elif change == "row-objects":
                trace["rows"][1].pop("roleObjects")
            elif change == "unbound-role":
                trace["rows"][1]["roleObjects"].append(role("Boss", "boss", [0, 0, 1, 1]))
            elif change == "bad-id":
                trace["rows"][1]["roleObjects"][0]["id"] = "#9"
            else:
                trace["rows"][1]["roleObjects"][0]["box"] = [10, 10, 5, 5]
            with self.subTest(change=change):
                self.refused("annot", 1, replay=StandIn(trace))

    def test_a_replay_that_fails_is_reported_with_its_reason(self):
        message = self.refused("the replay could not finish", 0,
                               replay=StandIn(error=SystemExit('configured replay refused: "bindings.coin ambiguous"')))
        self.assertIn("bindings.coin ambiguous", message)

    def test_a_failure_does_not_point_into_the_removed_replay_folder(self):
        class Failing(StandIn):
            def __call__(inner, route, out, **options):
                raise SystemExit(f"godot failed (1); see {out / 'godot.log'}; copy at {out}/work")
        message = self.refused("godot failed (1)", 0, replay=Failing())
        self.assertNotIn("godot.log", message)
        self.assertIn("<removed replay folder>/work", message)

    def test_a_config_changed_during_the_replay_is_refused(self):
        class Editing(StandIn):
            def __call__(inner, route, out, **options):
                self.config_path.write_text(self.config_path.read_text() + " ")
                return super().__call__(route, out, **options)
        self.refused("changed during the replay", 0, replay=Editing())


class ReaderTest(unittest.TestCase):
    def test_the_example_is_valid(self):
        self.assertEqual(inspection.problems(json.loads(EXAMPLE.read_text())), [])

    def test_the_reader_recomputes_rather_than_trusting_the_record(self):
        good = json.loads(EXAMPLE.read_text())
        self.assertTrue(good["objects"], "the example measures at least one object")
        cases = {
            "onScreen": lambda d: d["objects"][0].update(onScreen=not d["objects"][0]["onScreen"]),
            "tick past last": lambda d: d.update(tick=d["lastTick"] + 1),
            "both lists": lambda d: d["absent"].append({"role": d["objects"][0]["role"], "selector": "group:x"}),
            "absent twice": lambda d: d["absent"].extend([{"role": "z", "selector": "group:z"}] * 2),
            "inverted box": lambda d: d["objects"][0].update(worldBox=[5, 5, 1, 1]),
            "unknown field": lambda d: d.update(verdict="accept"),
            "format": lambda d: d.update(format="expectrail.inspection/v0"),
            "bounds source": lambda d: d["objects"][0].update(boundsSource="pixels"),
            "visible text": lambda d: d["objects"][0].update(visible="yes"),
            "generation": lambda d: d["objects"][0].update(generation=0),
        }
        for name, change in cases.items():
            doc = copy.deepcopy(good)
            change(doc)
            with self.subTest(name=name):
                self.assertNotEqual(inspection.problems(doc), [])


class CommandTest(Fixture):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with cli_capture.command_output(out, err):
            code = cli.main(["inspect", *args])
        return code, out.getvalue(), err.getvalue()

    def test_json_and_text(self):
        with mock.patch("harness.run.run", StandIn()):
            code, out, err = self.run_cli("--project", str(self.game), "--at-tick", "2", "--json")
        self.assertEqual((code, err), (0, ""))
        doc = json.loads(out)
        self.assertEqual(inspection.problems(doc), [])
        self.assertEqual(sorted(o["role"] for o in doc["objects"]), ["coin", "player"])
        with mock.patch("harness.run.run", StandIn()):
            code, out, err = self.run_cli(str(self.game), "--at-tick", "1")
        self.assertEqual(code, 0, err)
        self.assertIn("player: Actors/Avatar, box 69,104 to 93,128 px, visible, on screen", out)
        self.assertIn("coin: no object at this tick (group:coin)", out)
        self.assertIn("not what a camera image shows", out)

    def test_refusals_exit_5_and_print_no_measurement(self):
        with mock.patch("harness.run.run", StandIn()):
            for args, needle in (((str(self.game), "--at-tick", "500"), "choose --at-tick"),
                                 ((str(self.game), "--route", "walk.json"), "--route is used with --at-tick"),
                                 ((str(self.game), "--at-tick", "x"), "invalid int value")):
                with self.subTest(args=args):
                    code, out, err = self.run_cli(*args)
                    self.assertEqual(code, 5)
                    self.assertEqual(out, "")
                    self.assertIn(needle, err)

    def test_without_at_tick_inspect_still_reads_saved_scenes_only(self):
        with mock.patch("harness.run.run", side_effect=AssertionError("no replay without --at-tick")):
            code, out, err = self.run_cli(str(self.game), "--json")
        self.assertEqual(code, 0, err)
        self.assertIn("players", json.loads(out))


class RealEngineTest(unittest.TestCase):
    """The numbers match a direct harness replay of the same route, and they move as the route says."""

    @classmethod
    def setUpClass(cls):
        from tests.tool_requirements import godot_binary
        cls.engine = godot_binary()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="expectrail-inspect-real-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        patcher = mock.patch.dict("os.environ", {"EXPECTRAIL_SANDBOX": "off"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def direct(self, game, route):
        from harness import run as hr
        hr.run(route, self.root / "direct", game=game, godot=self.engine, capture_frames=False, sandbox="off", fps=None)
        return json.loads((self.root / "direct" / "trace.json").read_text())

    def test_config_lane_player_matches_the_harness_trace_and_walks_right(self):
        game = self.root / "game"
        shutil.copytree(ROOT / "tests/projects/config-lane", game)
        first = inspection.document(game, 0, godot=self.engine)
        later = inspection.document(game, 90, godot=self.engine)
        trace = self.direct(game, game / "walk.json")
        for doc in (first, later):
            self.assertEqual(inspection.problems(doc), [])
            self.assertEqual(doc["lastTick"], len(trace["rows"]) - 1)
            (player,) = doc["objects"]
            self.assertEqual(player["node"], "Actors/Avatar")
            recorded = trace["rows"][doc["tick"]]["roleObjects"][0]
            self.assertEqual((player["box"], player["worldBox"], player["visible"], player["boundsSource"]),
                             (recorded["box"], recorded["worldBox"], recorded["visible"], recorded["boundsSource"]))
            self.assertTrue(player["visible"] and player["onScreen"])
        # move_right is held from tick 0: the drawing moves right in the world.
        self.assertGreater(later["objects"][0]["worldBox"][0], first["objects"][0]["worldBox"][0] + 10)

    def test_a_binding_never_found_is_a_named_setup_error_without_a_removed_path(self):
        game = self.root / "game"
        shutil.copytree(ROOT / "tests/projects/config-lane", game)
        path = game / "expectrail.project.json"
        doc = json.loads(path.read_text()); doc["bindings"]["coin"] = {"group": "coin", "texture": "res://square.svg"}
        path.write_text(json.dumps(doc))
        with self.assertRaises(inspection.InspectionError) as caught:
            inspection.document(game, 5, godot=self.engine)
        message = str(caught.exception)
        self.assertIn("bindings.coin coin not found on any tick", message)
        self.assertNotIn("expectrail-inspect-", message)
        self.assertNotIn("godot.log", message)

    def test_crate_run_with_a_given_route(self):
        game = self.root / "crate"
        shutil.copytree(ROOT / "tests/projects/crate-run/project", game)
        route = ROOT / "tests/projects/crate-run/routes/walk.json"
        doc = inspection.document(game, 60, route, godot=self.engine)
        self.assertEqual(inspection.problems(doc), [])
        self.assertEqual(doc["route"]["from"], "argument")
        self.assertEqual(doc["viewport"], [640, 360])
        (player,) = doc["objects"]
        trace = self.direct(game, route)
        self.assertEqual(player["box"], trace["rows"][60]["roleObjects"][0]["box"])


if __name__ == "__main__":
    unittest.main()
