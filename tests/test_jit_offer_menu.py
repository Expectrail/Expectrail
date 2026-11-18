"""The menu setting (expectrail/jit/offer.py, ``MENU``; issue #285): the generator is offered the menu probes.

The #285 audit found that the two counter defects (``coin-counts-twice``, ``coin-counter-stuck``) are drawn
only on the pause menu, that the menu probes reach them, and that no offer of the generator had them. Under
``signals-reach-evidence-menu`` the probe list is the evidence setting's, then the menu probes made from the
reviewed profile's ``menuActions``. Only those probes press the menu action. Offline: a simulated game, no
engine, no model and no key."""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from harness.run import needs_ui_integers

from expectrail.contracts import ContractError, load_strict, validate_v1
from expectrail.discovery.route_compiler import ProgramError, compile_route
from expectrail.jit import intent, measure, offer
from expectrail.jit.run import generate
from expectrail.repro import menu
from tests.jit_fixtures import PROFILE, Case, JitGame, Transport, reply

REPO = Path(__file__).resolve().parents[1]
PROF = load_strict(PROFILE, "mechanics-profile")
NO_FIX = REPO / "bench" / "jit" / "public" / "no-fix.patch"
MENU_IDS = ["hold-right-then-toggle-pause", "hold-left-then-toggle-pause", "reverse-then-toggle-pause"]
REPORT = "The coin counter on the pause menu stays at zero however many coins I pick up."
COUNTER = {"type": "signal_compare", "leftSignal": "coins_collected", "rightSignal": "ui_integer_at_end",
           "comparator": "eq", "toleranceAbs": 0}


def lib(which, profile=PROF, **kw):
    return offer.library(profile["actions"], which, REPORT, profile=profile, **kw)


class CounterGame(JitGame):
    """JitGame, plus coins and a counter label. The player picks up one coin every 30 ticks it moves; once a
    route has pressed toggle_pause, the last rows carry the pause menu's one integer label: the coins picked up,
    or 0 on a build with ``counter-stuck``. A route that never opens the menu has no label at all. Like the
    harness, the labels are recorded only when a check evaluated on the replay reads them."""

    def __call__(self, route_path, run_dir, patches=(), trace_specs=()):
        out = super().__call__(route_path, run_dir, patches=[p for p in patches if Path(p).stem != "counter-stuck"])
        stuck = any(Path(p).stem == "counter-stuck" for p in patches)
        route = json.loads(Path(route_path).read_text())
        paused = [e["tick"] for e in route["events"] if e["action"] == "toggle_pause" and e["pressed"]]
        trace_path = Path(run_dir) / "trace.json"
        trace = json.loads(trace_path.read_text())
        coins, last_x = [[i, 600.0 + 20 * i] for i in range(40)], None
        for row in trace["rows"]:
            x = row["player"][0]
            if last_x is not None and x != last_x and row["tick"] % 30 == 0 and coins:
                coins.pop()
            last_x = x
            row["coins"] = [list(c) for c in coins]
            if needs_ui_integers(trace_specs):
                row["uiIntegers"] = []
            if paused and row["tick"] > paused[0] + 30 and needs_ui_integers(trace_specs):
                row["uiIntegers"] = [0 if stuck else 40 - len(coins)]
        trace_path.write_text(json.dumps(trace))
        return out


class TheLibrary(unittest.TestCase):
    def test_the_menu_setting_is_the_evidence_library_and_the_three_menu_probes(self):
        evidence, menu_lib = lib(offer.EVIDENCE), lib(offer.MENU)
        self.assertEqual(menu_lib[:len(evidence)], evidence)
        self.assertEqual([p["id"] for p in menu_lib[len(evidence):]], MENU_IDS)
        self.assertTrue(all(p["family"] == "menu" for p in menu_lib[len(evidence):]))

    def test_no_other_setting_has_a_menu_probe(self):
        for which in offer.ALL:
            if which != offer.MENU:
                self.assertFalse([p for p in lib(which) if p.get("family") == "menu"], which)

    def test_every_setting_but_menu_ignores_the_profile(self):
        bare = {k: v for k, v in PROF.items() if k != "menuActions"}
        for which in offer.ALL:
            if which != offer.MENU:
                self.assertEqual(lib(which, bare), offer.library(PROF["actions"], which, REPORT), which)

    def test_the_bundled_profile_names_the_pause_action_and_it_validates(self):
        self.assertEqual(PROF["menuActions"], ["toggle_pause"])
        self.assertNotIn("toggle_pause", PROF["actions"])

    def test_a_profile_without_menu_actions_cannot_be_run_under_the_menu_setting(self):
        bare = {k: v for k, v in PROF.items() if k != "menuActions"}
        with self.assertRaisesRegex(offer.OfferError, "menuActions"):
            lib(offer.MENU, bare)
        with self.assertRaisesRegex(offer.OfferError, "menuActions"):
            offer.library(PROF["actions"], offer.MENU, REPORT)

    def test_a_menu_action_the_game_does_not_declare_is_refused(self):
        tmp = Path(tempfile.mkdtemp(prefix="expectrail-menu-offer-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "project.godot").write_text('[input]\n\njump={\n}\nmove_left={\n}\nmove_right={\n}\nshoot={\n}\n',
                                           encoding="utf-8")
        with self.assertRaisesRegex(offer.OfferError, "declares no input action toggle_pause"):
            lib(offer.MENU, game=tmp)
        with self.assertRaisesRegex(offer.OfferError, "no project file"):
            lib(offer.MENU, game=tmp / "nowhere")

    def test_a_menu_action_already_in_the_catalog_is_refused(self):
        bad = copy.deepcopy(PROF)
        bad["menuActions"] = ["shoot"]
        with self.assertRaisesRegex(offer.OfferError, "already in the action catalog"):
            lib(offer.MENU, bad)

    def test_a_catalog_that_is_not_the_profiles_is_refused(self):
        with self.assertRaisesRegex(offer.OfferError, "not the profile's"):
            offer.library(["move_left", "move_right"], offer.MENU, REPORT, profile=PROF)

    def test_the_schema_holds_menu_actions_to_plain_names_and_at_most_two(self):
        for value in ([], ["Toggle Pause"], ["a", "b", "c"], ["x", "x"], "toggle_pause"):
            bad = copy.deepcopy(PROF)
            bad["menuActions"] = value
            with self.subTest(value=value), self.assertRaises(ContractError):
                validate_v1(bad, "mechanics-profile")


class Claims:
    """An intent whose answer's probes, after the parser let them through, say they are menu probes and press
    the menu action: what run.generate must still refuse on its own."""

    def __init__(self, inner):
        self.inner = inner
        self.offer, self.model, self.system = inner.offer, inner.model, inner.system

    def __call__(self, *args):
        answer = self.inner(*args)
        for p in answer.get("probes", []):
            p["family"] = "menu"
            p["program"] = {"op": "tap", "action": "toggle_pause", "durationTicks": 4}
        return answer


class WhoMayPressIt(unittest.TestCase):
    def test_only_a_menu_probe_compiles_with_the_menu_action(self):
        probes = lib(offer.MENU)
        for p in probes:
            names = offer.route_actions(PROF, p)
            self.assertEqual("toggle_pause" in names, p["family"] == "menu", p["id"])
            compile_route(p["program"], name=p["id"], description=p["description"], actions=names)
        a_menu_probe = next(p for p in probes if p["family"] == "menu")
        with self.assertRaises(ProgramError):
            compile_route(a_menu_probe["program"], name="x", description="x", actions=PROF["actions"])

    def test_the_family_named_here_is_the_menu_modules(self):
        self.assertEqual(offer.MENU_FAMILY, menu.FAMILY)

    def test_the_catalog_widened_for_the_menu_experiments_is_not_doubled(self):
        wide = menu.with_menu_actions(PROF, ["toggle_pause"])
        probe = lib(offer.MENU)[-1]
        self.assertEqual(offer.route_actions(wide, probe), wide["actions"])

    def test_a_probe_the_model_writes_cannot_press_the_menu_action_even_if_it_says_it_is_a_menu_probe(self):
        case = Case()
        self.addCleanup(shutil.rmtree, case.dir, ignore_errors=True)
        ans = json.dumps({"probes": [{"id": "open-menu", "description": "Open the menu.", "family": "menu",
                                      "program": {"op": "tap", "action": "jump", "durationTicks": 4}}],
                          "candidates": [{"id": "counter", "statement": "The counter shows the coins.",
                                          "claimId": "player.jump", "class": "player", "operation": COUNTER,
                                          "appliesTo": "all"}]})
        doc = generate(PROFILE, REPORT, case.patch("fix-wrong", NO_FIX.read_text(encoding="utf-8")),
                       [case.patch("counter-stuck")], case.dir / "out", runner=CounterGame(),
                       variants_fn=case.variants(), intent=Claims(intent.spark_intent(transport=Transport(reply(ans)),
                                                                                       offer=offer.MENU)),
                       offer=offer.MENU)
        validate_v1(doc, "jit-run")
        self.assertIn("probe jit-open-menu refused by the route compiler", " ".join(doc["diagnostics"]))
        self.assertNotIn("jit-open-menu", [p["id"] for p in doc["probes"]])


class ThePrompt(unittest.TestCase):
    def test_only_the_menu_setting_says_so_and_the_evidence_prompt_is_unchanged(self):
        for which in offer.ALL:
            self.assertEqual(intent.MENU_TEXT in intent.system_for(which), which == offer.MENU, which)
        self.assertEqual(intent.system_for(offer.MENU).replace(intent.MENU_TEXT, "", 1),
                         intent.system_for(offer.EVIDENCE))

    def test_the_menu_setting_offers_the_counter_reading_and_the_comparison(self):
        self.assertIn("ui_integer_at_end", offer.meanings(offer.MENU))
        self.assertTrue(offer.shows_evidence(offer.MENU))
        self.assertFalse(offer.offers_pixel(offer.MENU))
        self.assertTrue(offer.offers_menu(offer.MENU))

    def test_the_prompt_lists_the_menu_probes_and_the_catalog_alone(self):
        probes = lib(offer.MENU)
        text = intent.prompt(REPORT, "", {"files": [], "claims": [], "probeIds": [p["id"] for p in probes]},
                             PROF, probes, offer=offer.MENU)
        body = json.loads(text)
        self.assertEqual(body["actions"], PROF["actions"])
        self.assertTrue(set(MENU_IDS) <= {p["id"] for p in body["probesAvailable"]})


class TheRun(unittest.TestCase):
    def run_counter(self, which=offer.MENU, applies=("hold-right-then-toggle-pause",)):
        case = Case()
        self.addCleanup(shutil.rmtree, case.dir, ignore_errors=True)
        ans = json.dumps({"candidates": [{"id": "counter-shows-coins",
                                          "statement": "After a walk the pause menu's counter shows the coins picked up.",
                                          "claimId": "player.jump", "class": "player", "operation": COUNTER,
                                          "appliesTo": list(applies)}]})
        return generate(PROFILE, REPORT, case.patch("fix-wrong", NO_FIX.read_text(encoding="utf-8")),
                        [case.patch("counter-stuck")], case.dir / "out", runner=CounterGame(),
                        variants_fn=case.variants(),
                        intent=intent.spark_intent(transport=Transport(reply(ans)), offer=which), offer=which)

    def test_a_counter_check_on_a_menu_probe_is_kept_and_recorded_as_menu(self):
        doc = self.run_counter()
        validate_v1(doc, "jit-run")
        self.assertEqual(doc["status"], "complete", doc["reason"])
        self.assertEqual(doc["settings"]["offer"], offer.MENU)
        self.assertEqual([(p["id"], p["source"]) for p in doc["probes"]], [("hold-right-then-toggle-pause", "menu")])
        self.assertEqual([v["valid"] for v in doc["validity"]], [True])

    def test_the_same_check_on_a_walk_that_never_opens_the_menu_is_not_kept(self):
        doc = self.run_counter(applies=("hold-right",))
        validate_v1(doc, "jit-run")
        self.assertFalse([v for v in doc["validity"] if v["valid"]])

    def test_under_the_evidence_setting_a_check_on_a_menu_probe_applies_to_nothing(self):
        doc = self.run_counter(which=offer.EVIDENCE)
        validate_v1(doc, "jit-run")
        self.assertEqual(doc["status"], "nothing-generated")
        self.assertEqual(doc["probes"], [])

    def test_a_menu_run_with_a_profile_without_menu_actions_generates_nothing(self):
        tmp = Path(tempfile.mkdtemp(prefix="expectrail-menu-profile-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        bare = tmp / "profile.json"
        bare.write_text(json.dumps({k: v for k, v in PROF.items() if k != "menuActions"}), encoding="utf-8")
        case = Case()
        self.addCleanup(shutil.rmtree, case.dir, ignore_errors=True)
        t = Transport(reply(json.dumps({"candidates": []})))
        doc = generate(bare, REPORT, case.patch("fix-wrong", NO_FIX.read_text(encoding="utf-8")),
                       [case.patch("counter-stuck")], case.dir / "out", runner=CounterGame(),
                       variants_fn=case.variants(), intent=intent.spark_intent(transport=t, offer=offer.MENU),
                       offer=offer.MENU)
        validate_v1(doc, "jit-run")
        self.assertEqual(doc["status"], "nothing-generated")
        self.assertIn("menuActions", doc["reason"])
        self.assertEqual(t.bodies, [])


class TheExample(unittest.TestCase):
    def test_the_example_is_a_menu_run_that_validates(self):
        doc = load_strict(REPO / "contracts" / "examples" / "jit-run-menu.json", "jit-run")
        self.assertEqual(doc["settings"]["offer"], offer.MENU)
        self.assertEqual({p["source"] for p in doc["probes"]}, {"menu"})
        self.assertEqual(doc["proposed"][0]["spec"]["operation"], COUNTER)


class TheMeasureStep(unittest.TestCase):
    def test_the_menu_probes_are_measured_with_their_menu_action(self):
        tmp = Path(tempfile.mkdtemp(prefix="expectrail-menu-measure-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        patch = tmp / "counter-stuck.patch"
        patch.write_text("fake\n", encoding="utf-8")
        probes = [p for p in lib(offer.MENU) if p["family"] == "menu"]
        doc = measure.measure(PROF, [patch], tmp / "out", probes=probes, runner=CounterGame())
        self.assertEqual(sorted(doc["probes"]), sorted(MENU_IDS))
        route = json.loads((tmp / "out" / "jit-measure-replays" / "routes" / f"{MENU_IDS[0]}.json").read_text())
        self.assertIn("toggle_pause", {e["action"] for e in route["events"]})


if __name__ == "__main__":
    unittest.main()
