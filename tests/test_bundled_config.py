"""The bundled game's proposed project config, and the parity check that holds it to today's results (#259).

The config sits beside project.godot at game/platformer/expectrail.project.json (Sean, November 19,
2026). It must be what `expectrail init` proposes for the game, and a copy of the game carrying
it must replay and decide exactly as a copy without it.
"""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail import project_config
from tools import bundled_config_parity as parity

ROOT = Path(__file__).resolve().parent.parent


def _trace(rows=3, **header):
    doc = {"format": "expectrail.trace/v1", "physicsTicksPerSecond": 120, "ticks": rows,
           "capabilities": {"facing": True, "objectBoxes": True},
           "rows": [{"tick": n, "player": [10.0 + n, 20.0], "onFloor": True} for n in range(rows)]}
    doc.update(header)
    return doc


def _configured(plain, config):
    doc = copy.deepcopy(plain)
    doc["bindings"] = config["bindings"]
    doc["viewport"] = [800, 480]
    doc["capabilities"]["roleBoxes"] = True
    for row in doc["rows"]:
        row["roleObjects"] = [{"id": "Level/Player", "role": "player", "box": [0, 0, 1, 1]}]
    return doc


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.config = parity.load_config()

    def test_the_config_is_valid_for_the_bundled_game_and_sits_beside_it(self):
        self.assertEqual(project_config.load(parity.CONFIG, ROOT / "game/platformer"), self.config)
        self.assertEqual(project_config.read_game(ROOT / "game/platformer"), self.config)
        self.assertFalse((ROOT / "harness/godot/platformer.project.json").exists())
        self.assertNotIn("draft", self.config)
        self.assertEqual(self.config["bindings"], {"player": {"node": "Level/Player",
                                                              "texture": "res://player/robot.webp"}})

    def test_it_is_what_init_proposes_for_the_game(self):
        self.assertEqual(parity.declared_mismatches(self.config), [])

    def test_a_declared_setting_the_game_does_not_have_is_named(self):
        for field, value in (("viewport", [640, 360]), ("physicsTicksPerSecond", 60),
                             ("entryScene", "res://game_splitscreen.tscn"),
                             ("bindings", {"player": {"node": "Player", "texture": "res://player/robot.webp"}}),
                             ("inputActions", ["jump", "move_left", "move_right"])):
            with self.subTest(field=field):
                wrong = {**self.config, field: value}
                found = parity.declared_mismatches(wrong)
                self.assertEqual(len(found), 1, found)
                self.assertTrue(found[0].startswith(field + " is "), found)


class TraceDifferencesTest(unittest.TestCase):
    def setUp(self):
        self.config = parity.load_config()
        self.plain = _trace()
        self.conf = _configured(self.plain, self.config)

    def test_only_what_a_config_adds_may_be_added(self):
        self.assertEqual(parity.trace_differences(self.plain, self.conf), [])
        self.assertTrue(parity.config_applied(self.conf, self.config))
        self.assertFalse(parity.config_applied(self.plain, self.config))

    def test_a_changed_row_value_is_a_difference(self):
        self.conf["rows"][1]["player"] = [11.5, 20.0]
        self.assertEqual(parity.trace_differences(self.plain, self.conf), ["row 1: player differs"])

    def test_a_field_the_plain_trace_has_and_the_configured_one_lacks(self):
        del self.conf["rows"][2]["onFloor"]
        self.assertEqual(parity.trace_differences(self.plain, self.conf), ["row 2: onFloor differs"])
        del self.conf["physicsTicksPerSecond"]
        self.assertIn("the configured trace has no 'physicsTicksPerSecond'",
                      parity.trace_differences(self.plain, self.conf))

    def test_an_added_field_a_config_does_not_add(self):
        self.conf["rows"][0]["ground"] = 400
        self.conf["levelArt"] = {}
        found = parity.trace_differences(self.plain, self.conf)
        self.assertIn("the configured trace adds 'levelArt', which a config does not add", found)
        self.assertIn("row 0: adds ground", found)

    def test_capabilities_may_only_gain_role_boxes(self):
        self.conf["capabilities"]["facing"] = False
        self.assertTrue(parity.trace_differences(self.plain, self.conf)[0].startswith("capabilities differ"))
        self.conf = _configured(self.plain, self.config)
        self.conf["capabilities"]["extra"] = 1
        self.assertTrue(parity.trace_differences(self.plain, self.conf)[0].startswith("capabilities differ"))

    def test_a_different_number_of_rows(self):
        self.conf["rows"].pop()
        self.assertEqual(parity.trace_differences(self.plain, self.conf), ["3 rows without the config, 2 with it"])

    def test_not_a_trace(self):
        self.assertEqual(parity.trace_differences([], self.conf), ["a trace is not a JSON object"])
        self.assertEqual(parity.trace_differences({"rows": None}, {"rows": []}), ["a trace has no list of rows"])

    def test_a_trace_missing_role_boxes_on_one_row_was_not_configured(self):
        del self.conf["rows"][1]["roleObjects"]
        self.assertFalse(parity.config_applied(self.conf, self.config))
        self.assertFalse(parity.config_applied({**self.conf, "rows": []}, self.config))


class ReportTest(unittest.TestCase):
    def test_equal_needs_every_case_and_no_declared_mismatch(self):
        t = [{"route": "smoke", "rows": 3, "configApplied": True, "equal": True, "differences": []}]
        d = [{"sample": "clean", "equal": True, "differences": [],
              "configured": {"decision": "accept", "answered": 120, "asked": 120, "replays": 1, "configApplied": 1}}]
        self.assertTrue(parity.report(t, d, [])["equal"])
        self.assertFalse(parity.report(t, d, ["viewport is ..."])["equal"])
        self.assertFalse(parity.report([], None, [])["equal"], "nothing compared is not parity")
        self.assertFalse(parity.report(t, [{**d[0], "equal": False, "differences": ["x"]}], [])["equal"])
        said = parity.lines(parity.report(t, None, []))
        self.assertIn("decisions: not compared (--traces-only)", said)
        self.assertEqual(said[-1], "parity: every case is the same")

    def test_no_engine_is_cannot_tell_exit_5(self):
        with mock.patch("harness.run.find_godot", return_value=Path("/nonexistent/godot")), \
                mock.patch("sys.stderr"), mock.patch.dict("os.environ", {}):
            self.assertEqual(parity.main(["--traces-only"]), 5)


class RealEngineTest(unittest.TestCase):
    """In Godot: the configured copy replays the smoke route and decides the clean sample as the plain copy."""

    @classmethod
    def setUpClass(cls):
        from tests.tool_requirements import display_problem, executable, godot_binary
        cls.engine = godot_binary()
        executable("patch")
        problem = display_problem()
        if problem:
            if os.environ.get("EXPECTRAIL_ENGINE_TESTS") == "required":
                raise AssertionError(f"EXPECTRAIL_ENGINE_TESTS=required: {problem}")
            raise unittest.SkipTest(problem)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="expectrail-bundled-config-")
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name)
        env = mock.patch.dict("os.environ", {"EXPECTRAIL_SANDBOX": "off", "EXPECTRAIL_GODOT": str(self.engine)})
        env.start()
        self.addCleanup(env.stop)
        self.config = parity.load_config()

    def test_smoke_trace_and_clean_sample_are_the_same_with_the_config(self):
        (trace,) = parity.compare_traces(self.work, self.config, routes=("smoke",))
        self.assertTrue(trace["configApplied"])
        self.assertEqual(trace["differences"], [])
        self.assertEqual(trace["rows"], 240)
        (sample,) = parity.compare_decisions(self.work, self.config, samples=("clean",))
        self.assertEqual(sample["differences"], [])
        self.assertEqual(sample["configured"]["configApplied"], sample["configured"]["replays"])
        self.assertGreaterEqual(sample["configured"]["replays"], 1)
        self.assertEqual(sample["plain"]["phase"], "completed")

    def test_a_wrong_texture_is_still_the_same_replay_so_parity_alone_is_not_enough(self):
        # Why declared_mismatches exists: a binding's texture does not change the trace.
        wrong = json.loads(json.dumps(self.config))
        wrong["bindings"]["player"]["texture"] = "res://player/bullet.webp"
        (trace,) = parity.compare_traces(self.work, wrong, routes=("smoke",))
        self.assertTrue(trace["configApplied"])
        self.assertEqual(trace["differences"], [])
        self.assertEqual(len(parity.declared_mismatches(wrong)), 1)


if __name__ == "__main__":
    unittest.main()
