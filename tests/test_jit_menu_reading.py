"""The menu probes' replays before the proposal read the pause menu's counter (issue #285).

Under ``signals-reach-evidence-menu`` the generator is offered the menu probes so a check can read the coin
counter the pause menu draws (``ui_integer_at_end``). The harness records that counter only when asked. Until
this change the measure step and the evidence asked for it on no replay: on Godot 4.7.2 the measure step read
``ui_integer_at_end`` as no reading on every menu probe, on the clean game and on ``coin-counts-twice`` alike,
so the proposer was shown nothing about the counter on the routes that open the menu.

Now the measure step's and the evidence's replays of a menu probe, and of no other probe, ask for it
(``offer.replay_options``). The checks' own replays are unchanged: they ask when a check reads the counter."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness import run as hr
from harness import sandbox as box

from expectrail.contracts import load_strict
from expectrail.jit import intent, measure, offer
from expectrail.repro import screen
from tests import test_project_config as fixtures
from tests.jit_fixtures import PROFILE
from tests.test_jit_offer_menu import MENU_IDS, REPORT, CounterGame
from tests.test_ui_recording_request import PLAIN

REPO = Path(__file__).resolve().parents[1]
PROF = load_strict(PROFILE, "mechanics-profile")


def menu_lib():
    return offer.library(PROF["actions"], offer.MENU, REPORT, profile=PROF)


class Recording(CounterGame):
    """CounterGame that also notes, per replay, whether the UI integers were asked for."""

    def __init__(self):
        super().__init__()
        self.asked: list[tuple[str, bool]] = []

    def __call__(self, route_path, run_dir, patches=(), trace_specs=(), ui_integers=False):
        name = json.loads(Path(route_path).read_text())["name"]
        self.asked.append((name, bool(ui_integers)))
        return super().__call__(route_path, run_dir, patches=patches, trace_specs=trace_specs,
                                ui_integers=ui_integers)


class TheHarnessArgument(unittest.TestCase):
    def capture(self, **kw):
        fixture = fixtures.SandboxValuesTest("test_the_sandbox_is_given_values_and_not_the_config_path")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        route = fixture.tmp / "route.json"
        route.write_text(json.dumps({"format": "expectrail.route/v0", "name": "t", "seed": 1,
                                     "ticks": 1, "events": []}))
        engine = fixture.tmp / "godot"
        engine.write_bytes(b"not an engine")
        with mock.patch.object(box, "probe", return_value=(fixtures.FAKE, None)), \
             mock.patch.object(box, "run", side_effect=fixture.engine), \
             mock.patch.object(hr.subprocess, "run", side_effect=AssertionError("started outside")):
            hr.run(route, fixture.tmp / "out", game=fixtures.CRATE, godot=engine,
                   sandbox="require", capture_frames=False, **kw)
        return [a for a in fixture.calls[-1] if a.startswith("--ui-integers=")]

    def test_asking_by_name_sends_the_existing_argument_once(self):
        self.assertEqual(self.capture(ui_integers=True), ["--ui-integers=true"])
        from tests.test_ui_recording_request import UI
        self.assertEqual(self.capture(ui_integers=True, trace_specs=[UI]), ["--ui-integers=true"])

    def test_not_asking_sends_nothing(self):
        self.assertEqual(self.capture(), [])
        self.assertEqual(self.capture(ui_integers=False, trace_specs=[PLAIN]), [])


class WhichReplaysAsk(unittest.TestCase):
    def test_only_a_menu_probe_asks(self):
        for p in menu_lib():
            self.assertEqual(offer.replay_options(p), {"ui_integers": True} if p["family"] == "menu" else {},
                             p["id"])

    def test_no_other_setting_has_a_probe_that_asks(self):
        for which in offer.ALL:
            if which != offer.MENU:
                probes = offer.library(PROF["actions"], which, REPORT, profile=PROF)
                self.assertFalse([p["id"] for p in probes if offer.replay_options(p)], which)


class TheMeasureStep(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="expectrail-menu-reading-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.patch = self.tmp / "counter-stuck.patch"
        self.patch.write_text("fake\n", encoding="utf-8")

    def test_the_menu_probes_carry_the_counter_on_both_builds_and_the_walks_do_not(self):
        probes = [p for p in menu_lib() if p["id"] in ("hold-right", *MENU_IDS)]
        game = Recording()
        doc = measure.measure(PROF, [self.patch], self.tmp / "out", probes=probes, runner=game)
        self.assertEqual(sorted(set(game.asked)),
                         sorted({("hold-right", False), *((pid, True) for pid in MENU_IDS)}))
        menu_row = doc["probes"]["hold-right-then-toggle-pause"]
        self.assertGreater(menu_row["clean"]["coins_collected"], 0)
        self.assertEqual(menu_row["clean"]["ui_integer_at_end"], menu_row["clean"]["coins_collected"])
        self.assertEqual(menu_row["bugBuild"]["ui_integer_at_end"], 0)
        walk = doc["probes"]["hold-right"]
        self.assertIsNone(walk["clean"]["ui_integer_at_end"])
        self.assertIsNone(walk["bugBuild"]["ui_integer_at_end"])

    def test_the_prompt_shows_the_counter_on_the_menu_probe(self):
        from expectrail.jit.cli import attach_measurements

        probes = [p for p in menu_lib() if p["id"] in ("hold-right", MENU_IDS[0])]
        measure.measure(PROF, [self.patch], self.tmp / "out", probes=probes, runner=Recording())
        self.assertEqual(attach_measurements(probes, self.tmp / "out" / measure.NAME, [self.patch]), [])
        body = json.loads(intent.prompt(REPORT, "", {"files": [], "claims": [], "probeIds": [p["id"] for p in probes]},
                                        PROF, probes, offer=offer.MENU))
        shown = {p["id"]: p.get("measured") for p in body["probesAvailable"]}
        self.assertEqual(shown[MENU_IDS[0]]["bugBuild"]["ui_integer_at_end"], 0)
        self.assertIn("ui_integer_at_end", shown[MENU_IDS[0]]["clean"])
        self.assertNotIn("ui_integer_at_end", shown["hold-right"]["clean"])


class TheEvidenceReplays(unittest.TestCase):
    def test_a_menu_probe_is_captured_with_the_counter_and_a_walk_without(self):
        tmp = Path(tempfile.mkdtemp(prefix="expectrail-menu-capture-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        asked = []

        def runner(route_path, run_dir, patches=(), **kw):
            asked.append((json.loads(Path(route_path).read_text())["name"], kw))
            raise SystemExit("no engine here")

        probes = {p["id"]: p for p in menu_lib()}
        for pid in ("hold-right", MENU_IDS[0]):
            with self.assertRaises(screen.ScreenError):
                screen.capture_probe(PROF, probes[pid], [], tmp / pid, runner)
        self.assertEqual({name: kw for name, kw in asked},
                         {"hold-right": {}, MENU_IDS[0]: {"ui_integers": True}})


class OnTheEngine(unittest.TestCase):
    """The measure step's menu probes on Godot 4.7.2 and the bundled game, for the two counter defects."""

    @classmethod
    def setUpClass(cls):
        from tests.tool_requirements import godot_binary

        godot = godot_binary(switch="EXPECTRAIL_ENGINE_TESTS")
        cls.tmp = tempfile.TemporaryDirectory(prefix="expectrail-menu-reading-engine-")
        cls.addClassCleanup(cls.tmp.cleanup)
        from functools import partial

        runner = partial(hr.run, capture_frames=False, godot=godot)
        probes = [p for p in menu_lib() if p["id"] in ("hold-right", MENU_IDS[0])]
        cls.docs = {}
        for name in ("coin-counts-twice", "coin-counter-stuck"):
            patch = REPO / "bench" / "jit" / "public" / name / "defect.patch"
            cls.docs[name] = measure.measure(PROF, [patch], Path(cls.tmp.name) / name, probes=probes, runner=runner)

    def test_the_counter_is_read_on_the_menu_probe_and_differs_on_both_defects(self):
        got = {name: {b: doc["probes"][MENU_IDS[0]][b]["ui_integer_at_end"] for b in ("clean", "bugBuild")}
               for name, doc in self.docs.items()}
        self.assertEqual(got, {"coin-counts-twice": {"clean": 5, "bugBuild": 10},
                               "coin-counter-stuck": {"clean": 5, "bugBuild": 0}})
        for doc in self.docs.values():
            self.assertEqual(doc["probes"][MENU_IDS[0]]["clean"]["coins_collected"], 5)
            self.assertIsNone(doc["probes"]["hold-right"]["clean"]["ui_integer_at_end"])
        print("Menu probe counter readings on the engine (measure step, not a reproduction rate):", got)


if __name__ == "__main__":
    unittest.main()
