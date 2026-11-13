"""Menu probes (issue #285, step 3): a library walk, then the game's menu opened and looked at.
Offline: no engine, no model and no key. The two recorded measurements at the end were made on the real
engine (bench/jit/public/menu-evidence-*.json) and are only read here."""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail.contracts import load_strict
from expectrail.discovery.route_compiler import MAX_TICKS, compile_route
from expectrail.jit.probes import jit_library
from expectrail.repro import bench, evidence, menu
from expectrail.repro.__main__ import main

REPO = Path(__file__).resolve().parents[1]
PUBLIC = REPO / "bench" / "jit" / "public"
PROFILE = REPO / "discovery" / "platformer.profile.json"
GAME_PROJECT = REPO / "game" / "platformer" / "project.godot"
ACTIONS = ["move_left", "move_right", "jump", "shoot"]
DECLARED = ["jump", "move_left", "move_right", "shoot", "toggle_pause"]
IDS = ["hold-right-then-toggle-pause", "hold-left-then-toggle-pause", "reverse-then-toggle-pause"]


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class DeclaredActions(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="expectrail-menu-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, text: str) -> Path:
        path = self.tmp / "project.godot"
        path.write_text(text, encoding="utf-8")
        return path

    def test_the_bundled_game_declares_its_pause_action(self):
        found = menu.declared_actions(GAME_PROJECT)
        self.assertIn("toggle_pause", found)
        self.assertTrue(set(ACTIONS) <= set(found))

    def test_only_the_input_section_counts(self):
        path = self.write('[application]\n\nfake={\n}\n\n[input]\n\npause={\n"deadzone": 0.5,\n"events": []\n}\n'
                          'right={\n"deadzone": 0.5,\n"events": []\n}\n\n[rendering]\n\nother={\n}\n')
        self.assertEqual(menu.declared_actions(path), ["pause", "right"])

    def test_no_project_file_is_an_error(self):
        with self.assertRaises(menu.MenuError):
            menu.declared_actions(self.tmp / "missing.godot")

    def test_a_huge_project_file_is_refused(self):
        path = self.write("[input]\n" + "x" * (menu.MAX_PROJECT_BYTES + 1))
        with self.assertRaises(menu.MenuError):
            menu.declared_actions(path)


class MenuProbes(unittest.TestCase):
    def setUp(self):
        self.library = jit_library(ACTIONS)
        self.made = menu.menu_probes(self.library, ["toggle_pause"], ACTIONS, DECLARED)

    def test_one_per_walk_of_the_library_in_library_order(self):
        self.assertEqual([p["id"] for p in self.made], IDS)
        self.assertEqual({p["family"] for p in self.made}, {"menu"})

    def test_each_is_its_walk_then_the_menu(self):
        by_id = {p["id"]: p for p in self.library}
        names = [*ACTIONS, "toggle_pause"]
        for probe in self.made:
            base = by_id[probe["id"].removesuffix("-then-toggle-pause")]
            walk = compile_route(base["program"], name=base["id"], description=base["description"], actions=ACTIONS)
            got = compile_route(probe["program"], name=probe["id"], description=probe["description"], actions=names)
            self.assertLessEqual(got["ticks"], MAX_TICKS)
            # Every press of the walk, on the same tick, before the menu.
            self.assertEqual([e for e in got["events"] if e["action"] != "toggle_pause"], walk["events"])
            taps = [e for e in got["events"] if e["action"] == "toggle_pause"]
            self.assertEqual([e["pressed"] for e in taps], [True, False])
            last_walk_tick = max(e["tick"] for e in walk["events"])
            self.assertGreaterEqual(taps[0]["tick"], last_walk_tick + menu.SETTLE_TICKS)
            self.assertEqual(taps[1]["tick"] - taps[0]["tick"], menu.TAP_TICKS)
            # The menu stays open to the end: at least OPEN_TICKS after its tap is released.
            self.assertGreaterEqual(got["ticks"] - taps[1]["tick"], menu.OPEN_TICKS)

    def test_the_bundled_menu_opens_on_tick_310(self):
        # Frame 155 at 60 frames and 120 ticks a second: where the recorded frames start to differ.
        for probe in self.made:
            got = compile_route(probe["program"], name=probe["id"], description=probe["description"],
                                actions=[*ACTIONS, "toggle_pause"])
            self.assertEqual([e["tick"] for e in got["events"] if e["action"] == "toggle_pause"], [310, 314])

    def test_the_library_is_not_changed(self):
        self.assertEqual(self.library, jit_library(ACTIONS))

    def test_refusals(self):
        for actions, why in ((["nope"], "declares no input action"),
                             (["jump"], "already in the action catalog"),
                             (["toggle_pause", "toggle_pause"], "named twice"),
                             (["Toggle Pause"], "plain action name"),
                             ([], "no menu action"),
                             (["a", "b", "c"], "max 2")):
            with self.subTest(actions=actions):
                with self.assertRaisesRegex(menu.MenuError, why):
                    menu.menu_probes(self.library, actions, ACTIONS, [*DECLARED, "a", "b", "c"])

    def test_a_library_with_no_walk_is_an_error_not_an_empty_set(self):
        no_walks = [p for p in self.library if p["family"] not in menu.FAMILIES]
        with self.assertRaisesRegex(menu.MenuError, "no probe of the families"):
            menu.menu_probes(no_walks, ["toggle_pause"], ACTIONS, DECLARED)

    def test_too_many_is_an_error(self):
        many = self.library + [{**p, "id": p["id"] + "-again"} for p in self.library if p["family"] in menu.FAMILIES]
        with self.assertRaisesRegex(menu.MenuError, "max 6"):
            menu.menu_probes(many, ["toggle_pause", "jump_p1"], ACTIONS, [*DECLARED, "jump_p1"])

    def test_a_probe_the_compiler_refuses_is_an_error(self):
        long_walk = [{"id": "hold-right", "family": "hold", "description": "Hold right.",
                      "program": {"op": "sequence", "steps": [{"op": "hold", "action": "move_right",
                                                               "durationTicks": MAX_TICKS}]}}]
        with self.assertRaisesRegex(menu.MenuError, "hold-right-then-toggle-pause"):
            menu.menu_probes(long_walk, ["toggle_pause"], ACTIONS, DECLARED)

    def test_with_menu_actions_copies_the_profile(self):
        profile = load_strict(PROFILE, "mechanics-profile")
        before = json.dumps(profile, sort_keys=True)
        made = menu.with_menu_actions(profile, ["toggle_pause"])
        self.assertEqual(made["actions"], [*ACTIONS, "toggle_pause"])
        self.assertEqual(json.dumps(profile, sort_keys=True), before)


class TheCommands(unittest.TestCase):
    def test_menu_prints_the_probes(self):
        code, out, _err = run_cli("menu", "--menu-action", "toggle_pause")
        self.assertEqual(code, 0)
        self.assertEqual([p["id"] for p in json.loads(out)], IDS)

    def test_menu_refuses_an_action_the_game_does_not_declare(self):
        code, _out, err = run_cli("menu", "--menu-action", "open_inventory")
        self.assertEqual(code, 1)
        self.assertIn("declares no input action open_inventory", err)

    def test_evidence_with_the_menu_only(self):
        seen = {}

        def fake(profile, probes, patches, out, **kw):
            seen.update(actions=profile["actions"], probes=[p["id"] for p in probes], patches=patches)
            return {"totals": {"error": 0}}

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(evidence, "evidence", fake):
            code, _out, err = run_cli("evidence", "--defect", "coin-counter-stuck", "--menu-action", "toggle_pause",
                                      "--menu-only", "--out", tmp)
        self.assertEqual(code, 0, err)
        self.assertEqual(seen["actions"], [*ACTIONS, "toggle_pause"])
        self.assertEqual(seen["probes"], IDS)
        self.assertEqual(seen["patches"], [PUBLIC / "coin-counter-stuck" / "defect.patch"])

    def test_evidence_with_the_menu_and_the_library(self):
        seen = {}

        def fake(profile, probes, patches, out, **kw):
            seen.update(probes=[p["id"] for p in probes])
            return {"totals": {"error": 0}}

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(evidence, "evidence", fake):
            code, _out, err = run_cli("evidence", "--defect", "coin-counter-stuck", "--menu-action", "toggle_pause",
                                      "--reach", "--out", tmp)
        self.assertEqual(code, 0, err)
        library = [p["id"] for p in jit_library(ACTIONS)]
        self.assertEqual(seen["probes"][:len(library)], library)
        self.assertEqual(seen["probes"][-3:], IDS)
        self.assertTrue(any(p.startswith("reach-") for p in seen["probes"]))

    def test_menu_only_needs_a_menu_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _out, err = run_cli("evidence", "--defect", "coin-counter-stuck", "--menu-only", "--out", tmp)
        self.assertEqual(code, 1)
        self.assertIn("--menu-only needs", err)


class NotOfferedToTheGenerator(unittest.TestCase):
    """The menu probes are for measurement. No offer of the generator reads them, and the mechanics
    profile's catalog, which every offer's prompt is built from, does not name the menu action."""

    def test_nothing_under_jit_reads_the_menu_module(self):
        for path in sorted((REPO / "expectrail" / "jit").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for word in ("repro.menu", "repro import menu", "menu_probes", "toggle_pause"):
                self.assertNotIn(word, text, f"{path.name}: {word}")

    def test_the_profile_does_not_name_the_menu_action(self):
        self.assertEqual(load_strict(PROFILE, "mechanics-profile")["actions"], ACTIONS)

    def test_no_offer_imports_the_menu_module(self):
        code = ("import sys\n"
                "from expectrail.jit import offer\n"
                "for o in offer.OFFERS:\n"
                "    offer.library(['move_left', 'move_right', 'jump', 'shoot'], o, 'the pause menu says 0')\n"
                "print('expectrail.repro.menu' in sys.modules)\n")
        got = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, check=True)
        self.assertEqual(got.stdout.strip(), "False")


class TheRecordedMenuEvidence(unittest.TestCase):
    """bench/jit/public/menu-evidence-<defect>.json: the menu probes replayed on the real engine on
    November 13, 2026 (Godot 4.7.2, no model). Named apart from evidence-*.json, which holds records
    of probes the generator may use."""

    NAMES = ("coin-counter-stuck", "coin-counts-twice")

    def setUp(self):
        self.patches = {d["id"]: REPO / d["patch"] for d in bench.load()["defects"]}
        self.paths = {p.stem.removeprefix("menu-evidence-"): p for p in sorted(PUBLIC.glob("menu-evidence-*.json"))}
        self.records = {n: evidence.load(p, base_patches=[self.patches[n]]) for n, p in self.paths.items()}

    def test_one_for_each_coin_counter_defect(self):
        self.assertEqual(sorted(self.records), list(self.NAMES))
        self.assertFalse(set(PUBLIC.glob("evidence-*.json")) & set(self.paths.values()))

    def test_the_probes_are_the_menu_probes_of_today(self):
        made = [p["id"] for p in menu.menu_probes(jit_library(ACTIONS), ["toggle_pause"], ACTIONS,
                                                   menu.declared_actions(GAME_PROJECT))]
        for name, record in self.records.items():
            self.assertEqual(record["probes"], made, name)
            self.assertEqual(record["totals"]["error"], 0, name)
            self.assertIsNone(record["observer"], name)

    def test_the_counter_changes_on_screen_only_once_the_menu_is_open(self):
        for name, record in self.records.items():
            rows = {r["probe"]: r for r in record["rows"]}
            for walk in ("hold-right-then-toggle-pause", "reverse-then-toggle-pause"):
                row = rows[walk]
                self.assertEqual(row["sees"], "screen-only", (name, walk))
                self.assertIsNone(row["record"], (name, walk))
                self.assertEqual(row["screen"]["firstFrame"], 310 * record["framesPerSecond"]
                                 // record["ticksPerSecond"], (name, walk))
                self.assertEqual(row["screen"]["frames"], row["screen"]["of"] - row["screen"]["firstFrame"], (name, walk))
                left, top, right, bottom = row["screen"]["box"]
                self.assertTrue(right <= 400 and bottom <= 200, (name, walk))     # the top-left corner
                self.assertEqual(row["unstable"]["frames"], 0, (name, walk))
            self.assertEqual(rows["hold-left-then-toggle-pause"]["sees"], "neither", name)

    def test_the_page_shows_each_record_as_rendered(self):
        page = (PUBLIC / "README.md").read_text(encoding="utf-8")
        for name, record in self.records.items():
            start, end = f"<!-- menu-evidence:{name}:start -->\n", f"<!-- menu-evidence:{name}:end -->"
            self.assertIn(start, page, name)
            self.assertEqual(page.split(start, 1)[1].split(end, 1)[0], evidence.render(record), name)


if __name__ == "__main__":
    unittest.main()
