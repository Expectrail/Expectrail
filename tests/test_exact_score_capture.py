"""The gate asks Godot to record exact Label paths without changing other replays."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from expectrail.discovery.route_compiler import compile_route
from expectrail.gate import verify
from expectrail.jit import offer
from harness import adapters
from harness import run as hr
from harness import sandbox as box
from tests import test_project_config as fixtures
from tools import ci_bundle

REPO = Path(__file__).resolve().parents[1]
SCORE = "InterfaceLayer/PauseMenu/ColorRect/CoinsCounter/Label"
TITLE = "InterfaceLayer/PauseMenu/ColorRect/CenterContainer/VBoxContainer/Label"


def exact_spec(spec_id, label_path, route="menu"):
    return {"id": spec_id, "coverage": {"routes": [route]},
            "assertion": {"type": "exact-ui-integer", "object": "score", "labelPath": label_path,
                          "expected": 5, "routeTicks": 464}}


class RequestArguments(unittest.TestCase):
    def capture(self, **kwargs):
        fixture = fixtures.SandboxValuesTest("test_the_sandbox_is_given_values_and_not_the_config_path")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        route = fixture.tmp / "route.json"
        route.write_text(json.dumps({"format": "expectrail.route/v0", "name": "t", "seed": 1,
                                     "ticks": 1, "events": []}), encoding="utf-8")
        engine = fixture.tmp / "godot"
        engine.write_bytes(b"not an engine")
        with mock.patch.object(box, "probe", return_value=(fixtures.FAKE, None)), \
             mock.patch.object(box, "run", side_effect=fixture.engine), \
             mock.patch.object(hr.subprocess, "run", side_effect=AssertionError("started outside")):
            hr.run(route, fixture.tmp / "out", game=fixtures.CRATE, godot=engine,
                   sandbox="require", capture_frames=False, **kwargs)
        return [arg for arg in fixture.calls[-1] if arg.startswith(("--ui-label-paths=", "--ui-integers="))]

    def test_bound_paths_are_distinct_sorted_and_separate_from_anonymous_capture(self):
        args = self.capture(label_paths=(SCORE, TITLE, SCORE), ui_integers=True)
        self.assertIn("--ui-integers=true", args)
        paths = [arg.split("=", 1)[1] for arg in args if arg.startswith("--ui-label-paths=")]
        self.assertEqual([json.loads(arg) for arg in paths], [[TITLE, SCORE]])

    def test_ordinary_replay_requests_no_label_capture(self):
        self.assertEqual(self.capture(), [])

    def test_bad_paths_are_refused_before_replay(self):
        bad_paths = ["", "/root/Score", "Menu/../Score", "Menu//Score", "Menu/Score:", "Menu/Score\n",
                     "Menu/ WithSpace", "Menu/Scöré", "Menu/Score/", "a" * 513, None]
        with mock.patch.object(hr, "find_godot", side_effect=AssertionError("started an engine")):
            for path in bad_paths:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    hr.run(Path("route.json"), Path("out"), label_paths=(path,))
            with self.assertRaises(ValueError):
                hr.run(Path("route.json"), Path("out"), label_paths=SCORE)
            with self.assertRaises(ValueError):
                hr.run(Path("route.json"), Path("out"), label_paths=tuple(f"Menu/Score{i}" for i in range(17)))


class GateReplay(unittest.TestCase):
    def test_gate_requests_all_and_only_applicable_exact_score_paths(self):
        seen = []

        def replay(route, game, out, frames, *, label_paths=()):
            seen.append(label_paths)
            return {"trace": {}, "replaySha256": "a" * 64}

        exact = [exact_spec("z", SCORE), exact_spec("a", TITLE), exact_spec("y", SCORE),
                 exact_spec("elsewhere", "Decoy/Label", "different-route")]
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(verify, "observations", return_value={}), \
             mock.patch.object(verify, "judge_run", side_effect=lambda *args, **kwargs: {"result": "pass"}), \
             mock.patch.object(verify.viewer, "check_series", return_value={}):
            folder = Path(tmp)
            route = folder / "menu.json"
            route.write_text(json.dumps({"ticks": 464}), encoding="utf-8")
            rows = verify.judge_arm(folder, [("menu", route, "a" * 64)], exact, folder, replay, label="head")
        self.assertEqual(seen, [(TITLE, SCORE)])
        self.assertEqual(rows[("elsewhere", "menu")]["result"], "not-applicable")

    def test_gate_godot_adapter_forwards_label_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "trace.json").write_text("{}", encoding="utf-8")
            (folder / "replay.json").write_text("{}", encoding="utf-8")
            with mock.patch.object(adapters._godot, "run", return_value={"game": {"tree": "a" * 64}}) as run:
                verify.harness_replay(folder / "menu.json", folder, folder, False, label_paths=(SCORE, TITLE))
            self.assertEqual(run.call_args.kwargs["label_paths"], (SCORE, TITLE))


class SplitGateReplay(unittest.TestCase):
    def test_bundle_requests_approved_base_paths_for_each_route_digest(self):
        def checks(specs):
            return SimpleNamespace(problems=[], routes=[("menu", b"{}", "a" * 64),
                                                        ("alias", b"{}", "a" * 64),
                                                        ("walk", b"[]", "b" * 64)],
                                   specs=specs, spec_entries={}, route_entries={}, digest="c" * 64)

        seen = []

        def replay(route, game, folder, frames, *, sandbox, checkouts, label_paths=()):
            seen.append((game.parent.name, route.stem, label_paths))
            (folder / "frames").mkdir(parents=True)
            (folder / "trace.json").write_text("{}", encoding="utf-8")
            (folder / "replay.json").write_text("{}", encoding="utf-8")

        base_checks = checks([exact_spec("counter", SCORE), exact_spec("title", TITLE, "alias")])
        head_checks = checks([exact_spec("decoy", "Decoy/Label")])
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(verify, "read_checks", side_effect=[base_checks, head_checks]), \
             mock.patch.object(verify, "game_tree", return_value="d" * 64), \
             mock.patch.object(ci_bundle.export_scan, "scan", return_value=[]), \
             mock.patch.object(ci_bundle.contracts, "validate"), \
             mock.patch.object(ci_bundle.evidence, "saved_run", side_effect=lambda folder, route: {
                 "tree": "d" * 64, "framesDir": folder / "frames", "replaySha256": "e" * 64}):
            root = Path(tmp)
            ci_bundle.capture(ci_bundle.Policy("game", "specs", []), root / "base", root / "head",
                              {"baseSha": "f" * 40}, "change", root / "capture.zip", replay=replay)
        self.assertEqual(seen, [(side, digest, paths) for side in ("base", "head")
                                for digest, paths in (("a" * 64, (TITLE, SCORE)), ("b" * 64, ()))])

    def test_saved_bundle_replay_accepts_request_for_an_already_recorded_trace(self):
        from hashlib import sha256

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            route = root / "menu.json"
            route.write_bytes(b"{}")
            recorded = {"trace": {"rows": [{"tick": 0, "uiLabelIntegers": {SCORE: 5}}]}}
            saved = verify.SavedReplays({}, {(root, sha256(b"{}").hexdigest()): recorded})
            attempts = ci_bundle.Attempts({}, {"head-2": saved})
            self.assertIs(attempts(route, root, root / "head-run2/menu", True, label_paths=(SCORE,)), recorded)


class OnTheEngine(unittest.TestCase):
    def test_integer_range_and_visibility_are_checked_for_each_bound_label(self):
        from tests.tool_requirements import godot_binary

        godot = godot_binary(switch="EXPECTRAIL_ENGINE_TESTS")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "game"
            game.mkdir()
            scene = ['[gd_scene format=3]', '[node name="Game" type="Node"]']
            labels = {"First": ("-1000000000", -1000000000), "Second": ("1000000000", 1000000000),
                      "Overflow": ("1000000001", None), "Hidden": ("7", None), "Decimal": ("5.0", None)}
            for name, (text, _) in labels.items():
                scene.extend((f'[node name="{name}" type="Label" parent="."]', f'text = "{text}"'))
                if name == "Hidden":
                    scene.append('visible = false')
            (game / "game.tscn").write_text("\n\n".join(scene) + "\n", encoding="utf-8")
            (game / "project.godot").write_text(
                'config_version=5\n[application]\nrun/main_scene="res://game.tscn"\n', encoding="utf-8")
            route = root / "idle.json"
            route.write_text(json.dumps({"format": "expectrail.route/v0", "name": "idle", "seed": 1,
                                         "ticks": 2, "events": []}), encoding="utf-8")
            hr.run(route, root / "out", game=game, godot=godot, capture_frames=False, label_paths=tuple(labels))
            trace = json.loads((root / "out/trace.json").read_text(encoding="utf-8"))
        self.assertEqual(trace["rows"][-1]["uiLabelIntegers"], {name: value for name, (_, value) in labels.items()})

    def test_stock_pause_probe_resolves_the_counter_by_full_path_at_runtime(self):
        from tests.tool_requirements import godot_binary

        godot = godot_binary(switch="EXPECTRAIL_ENGINE_TESTS")
        profile = json.loads((REPO / "discovery/platformer.profile.json").read_text(encoding="utf-8"))
        probe = next(p for p in offer.library(profile["actions"], offer.MENU, profile=profile)
                     if p["id"] == "hold-right-then-toggle-pause")
        route = compile_route(probe["program"], name=probe["id"], description=probe["description"],
                              actions=offer.route_actions(profile, probe))
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            path = folder / "menu.json"
            path.write_text(json.dumps(route), encoding="utf-8")
            hr.run(path, folder / "out", godot=godot, capture_frames=False, ui_integers=True,
                   label_paths=("Label", SCORE, TITLE, "InterfaceLayer/PauseMenu/ColorRect/CoinsCounter"))
            trace = json.loads((folder / "out/trace.json").read_text(encoding="utf-8"))
        expected = {"Label": None, SCORE: 5, TITLE: None, "InterfaceLayer/PauseMenu/ColorRect/CoinsCounter": None}
        self.assertEqual([row["tick"] for row in trace["rows"]], list(range(route["ticks"])))
        self.assertEqual(trace["rows"][0]["uiLabelIntegers"], dict.fromkeys(expected))
        self.assertEqual(trace["rows"][-1]["uiLabelIntegers"], expected)
        self.assertEqual(trace["rows"][-1]["uiIntegers"], [5])


if __name__ == "__main__":
    unittest.main()
