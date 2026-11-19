"""Correct-fix pressure replays counting pixel checks (#271, #286).

Before this change a counting pixel check stopped both pressure dispatches (``pixel-checks-not-replayed``),
because they replayed trace checks only. Now correct pressure replays each counting pixel check judged by
the no-model ``visual-sensor`` on every correct fix: the probe is replayed with frames three times, the
observer is asked about the same planned frames inside the check's window, and ``pixel.judge`` decides. The
bank must be the one the frozen check was judged with (its digest is in the signed source run). A check for
another observer, a dispatch with no bank, and the adversary still stop.

The frozen bundle is the committed enemy stand-in made counting (``passing``) and signed here with a
throwaway key. The game and the observer are stand-ins: no engine, no frames, no model. What the sensor
sees on the real engine is measured elsewhere (docs/jit.md, "Which way the enemy faces")."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail.discovery.probes import library
from expectrail.discovery.route_compiler import compile_route
from expectrail.jit import pixel, pressure
from tests.test_jit_pixel_counting import ENEMY_REPORT, passing
from tests.test_jit_pixel_envelope import trusted

REPO = Path(__file__).resolve().parents[1]
DEFECT = "enemy-walks-backwards"


class FakeSensor:
    """Answers like the visual-sensor, from a marker the fake game wrote: which build ran."""

    name = "visual-sensor"
    every, first = 10, None

    def __init__(self, setting):
        self._setting = dict(setting)
        self.calls = []

    def setting(self):
        return dict(self._setting)

    def frames(self, route):
        return list(range(0, 300, 10))

    def most_images(self, route, objects=(), player=True, windows=None):
        return 0

    def __call__(self, run_dir, route, objects=(), player=True, windows=None):
        self.calls.append((Path(run_dir).name, tuple(objects), player, windows))
        planned = pixel.planned(self, route, windows)
        build = (Path(run_dir) / "build.txt").read_text()
        run = {"run": build, "route": {"name": route["name"], "sha256": None}, "framesProbed": planned,
               "frames": [{"frame": n, "asked": False, "note": pixel.NOT_ASKED_PLAYER} for n in planned],
               "objects": {role: [{"frame": n, "boxes": []} for n in planned] for role in objects},
               "facing": list(objects)}
        return {"setting": self.setting(), "run": run, "images": 0}


def fake_judge(results):
    """pixel.judge for the fake runs: the result the test sets for the build the run names."""
    def judge(check, run, bindings=None):
        return {"result": results(check, run["run"]), "reason": "stand-in", "framesJudged": 1, "gaps": []}
    return judge


def frozen_bundle(root: Path, doc=None):
    """A frozen, authenticated bundle for the public enemy defect, its trust store and context."""
    from tests.test_receipt import _store
    envelope, trust = trusted(doc or passing())
    folder = root / "bundles" / DEFECT
    (folder / "jit-routes").mkdir(parents=True)
    (folder / "generated-counting.json").write_text(json.dumps(envelope))
    profile = json.loads((REPO / "discovery/platformer.profile.json").read_text())
    wanted = {p["check"]["probe"] for p in envelope["sourceRun"]["pixelChecks"]}
    for probe in library(profile["actions"]):
        if probe["id"] in wanted:
            route = compile_route(probe["program"], name=probe["id"], description=probe["description"],
                                  actions=profile["actions"])
            (folder / "jit-routes" / f"jit-{probe['id']}.json").write_text(json.dumps(route))
    return envelope, trust, folder


def setting_of(envelope):
    return envelope["sourceRun"]["pixelChecks"][0]["setting"]


class FrozenPixelChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.envelope, self.trust, self.folder = frozen_bundle(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_with_the_judging_bank_every_counting_pixel_check_is_frozen_with_its_route(self):
        _env, entries, routes, pixels = pressure.frozen(self.folder, self.trust, FakeSensor(setting_of(self.envelope)))
        self.assertEqual(entries, [])
        self.assertEqual([p["check"]["id"] for p in pixels],
                         [p["check"]["id"] for p in self.envelope["sourceRun"]["pixelChecks"]])
        self.assertEqual(sorted(routes), ["hold-right", "move-fire-right", "reverse"])

    def test_with_no_observer_it_still_stops(self):
        with self.assertRaisesRegex(pressure.Stop, "pixel-checks-not-replayed"):
            pressure.frozen(self.folder, self.trust)

    def test_another_bank_stops_before_any_replay(self):
        other = dict(setting_of(self.envelope), bankSha256="0" * 64)
        with self.assertRaisesRegex(pressure.Stop, "pixel-setting-mismatch"):
            pressure.frozen(self.folder, self.trust, FakeSensor(other))

    def test_a_check_for_another_observer_stops(self):
        sensor = FakeSensor(setting_of(self.envelope))
        sensor.name = "sam-3.1-anchor"
        with self.assertRaisesRegex(pressure.Stop, "pixel-checks-not-replayed: .* judged by visual-sensor"):
            pressure.frozen(self.folder, self.trust, sensor)

    def test_a_route_file_that_is_not_the_signed_route_stops(self):
        path = self.folder / "jit-routes" / "jit-reverse.json"
        route = json.loads(path.read_text())
        route["description"] = "changed"
        path.write_text(json.dumps(route))
        with self.assertRaisesRegex(pressure.Stop, "route-digest-mismatch"):
            pressure.frozen(self.folder, self.trust, FakeSensor(setting_of(self.envelope)))

    def test_an_unsigned_change_to_the_source_check_is_refused_on_read(self):
        envelope = json.loads((self.folder / "generated-counting.json").read_text())
        envelope["sourceRun"]["pixelChecks"][0]["check"]["window"]["fromFrame"] = 290
        (self.folder / "generated-counting.json").write_text(json.dumps(envelope))
        with self.assertRaises(ValueError):
            pressure.frozen(self.folder, self.trust, FakeSensor(setting_of(self.envelope)))


class CorrectPressureReplaysPixelChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.envelope, self.trust, self.folder = frozen_bundle(self.root)
        from tests.test_receipt import _store
        contexts = self.root / "contexts"
        contexts.mkdir()
        (contexts / f"{DEFECT}.json").write_text(json.dumps(self.trust.document()))
        self.contexts, self.store = contexts, self.root / "store.json"
        _store("test-issuer", self.trust.store["test-issuer"], self.store)
        manifest = pressure.bench.public_cases()
        manifest["defects"] = [d for d in manifest["defects"] if d["id"] == DEFECT]
        self.manifest = manifest
        self.replays = []

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, route, out, patches, sandbox, capture_frames=False):
        self.assertEqual(sandbox, "require")
        self.replays.append((Path(route).name, [Path(p).name for p in patches], capture_frames))
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "build.txt").write_text("+".join(Path(p).name for p in patches))

    def run_pressure(self, results, observer=None, kind="correct"):
        sensor = observer or FakeSensor(setting_of(self.envelope))
        with mock.patch.object(pressure.bench, "public_cases", return_value=self.manifest), \
                mock.patch.object(pixel, "judge", side_effect=fake_judge(results)):
            result = pressure.execute(kind, self.root / "bundles", self.contexts, self.store, self.root / "out",
                                      replay_cap=64, runner=self.runner,
                                      observer=None if kind != "correct" else sensor)
        return result, sensor

    def test_each_correct_fix_replays_each_pixel_check_three_times_with_frames(self):
        result, sensor = self.run_pressure(lambda check, build: "pass")
        self.assertEqual(result["status"], "complete", result["reason"])
        self.assertEqual(result["expectedCases"], 1)
        # Three probes, three replays each, of the one correct fix (the public exact undo); all with frames.
        self.assertEqual(result["replays"], 9)
        self.assertEqual(len(self.replays), 9)
        self.assertTrue(all(frames for _r, _p, frames in self.replays))
        self.assertTrue(all(patches[-1] == f"{DEFECT}-undo.patch" for _r, patches, _f in self.replays))
        self.assertEqual({r["specId"] for r in result["rows"]},
                         {p["check"]["id"] for p in self.envelope["sourceRun"]["pixelChecks"]})
        self.assertTrue(all(r["kind"] == "pixel" and r["outcomes"] == ["pass"] * 3 for r in result["rows"]))
        self.assertEqual(result["pixelObserver"], {"name": "visual-sensor", "setting": setting_of(self.envelope),
                                                   "every": 10, "first": None})
        # Asked about the enemy only, inside each check's window, as the judging run was.
        self.assertTrue(all(objects == ("enemy",) and player is False for _n, objects, player, _w in sensor.calls))
        self.assertIn([{"fromFrame": 130}], [w for *_x, w in sensor.calls])
        self.assertEqual(pressure.read(self.root / "out" / "pressure.json"), result)

    def test_one_failed_run_on_a_correct_fix_fails_the_campaign(self):
        seen = []

        def results(check, build):
            seen.append(check["id"])
            return "fail" if check["probe"] == "reverse" and seen.count(check["id"]) == 2 else "pass"
        result, _ = self.run_pressure(results)
        self.assertEqual(result["status"], "failed")
        row = next(r for r in result["rows"] if r["specId"].endswith("reverse"))
        self.assertEqual(row["outcomes"], ["pass", "fail", "pass"])

    def test_an_undecided_run_is_never_a_pass(self):
        result, _ = self.run_pressure(lambda check, build: "needs-review")
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(all(r["outcomes"] == ["insufficient_observation"] * 3 for r in result["rows"]))

    def test_an_answer_under_another_setting_is_not_judged(self):
        class Drifting(FakeSensor):
            def __call__(self, run_dir, route, **kwargs):
                answer = super().__call__(run_dir, route, **kwargs)
                answer["setting"] = dict(answer["setting"], bankSha256="1" * 64)
                return answer
        result, _ = self.run_pressure(lambda check, build: "pass", Drifting(setting_of(self.envelope)))
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(all(r["outcomes"] == ["insufficient_observation"] * 3 for r in result["rows"]))

    def test_an_observer_that_fails_is_an_undecided_run(self):
        class Broken(FakeSensor):
            def __call__(self, run_dir, route, **kwargs):
                raise RuntimeError("no frames")
        result, _ = self.run_pressure(lambda check, build: "pass", Broken(setting_of(self.envelope)))
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(all(r["outcomes"] == ["insufficient_observation"] * 3 for r in result["rows"]))

    def test_the_replay_cap_still_holds(self):
        with mock.patch.object(pressure.bench, "public_cases", return_value=self.manifest), \
                mock.patch.object(pixel, "judge", side_effect=fake_judge(lambda c, b: "pass")):
            result = pressure.execute("correct", self.root / "bundles", self.contexts, self.store, self.root / "out",
                                      replay_cap=4, runner=self.runner, observer=FakeSensor(setting_of(self.envelope)))
        self.assertEqual(result["status"], "blocked")
        self.assertIn("replay-cap", result["reason"])
        self.assertEqual(result["replays"], 4)

    def test_correct_pressure_with_no_bank_stops_before_any_replay(self):
        with mock.patch.object(pressure.bench, "public_cases", return_value=self.manifest):
            result = pressure.execute("correct", self.root / "bundles", self.contexts, self.store, self.root / "out",
                                      replay_cap=64, runner=self.runner)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("pixel-checks-not-replayed", result["reason"])
        self.assertEqual(self.replays, [])
        self.assertNotIn("pixelObserver", result)

    def test_the_adversary_is_never_given_an_observer(self):
        with self.assertRaisesRegex(ValueError, "only correct pressure"):
            pressure.execute("adversary", self.root / "bundles", self.contexts, self.store, self.root / "out",
                             replay_cap=64, runner=self.runner, observer=FakeSensor(setting_of(self.envelope)))


class PressureRecord(unittest.TestCase):
    def example(self):
        return json.loads((REPO / "contracts/examples/jit-pressure-pixel.json").read_text())

    def test_the_pixel_example_reads(self):
        doc = self.example()
        self.assertEqual(pressure.check(doc), doc)

    def test_pixel_rows_need_the_observer_that_judged_them(self):
        doc = self.example()
        doc["pixelObserver"] = None
        with self.assertRaisesRegex(ValueError, "observer and bank"):
            pressure.check(doc)
        del doc["pixelObserver"]
        with self.assertRaisesRegex(ValueError, "observer and bank"):
            pressure.check(doc)

    def test_only_correct_pressure_carries_an_observer(self):
        doc = self.example()
        doc.update(kind="adversary", status="blocked", reason="stopped", apiCapUsd=6, rows=[])
        with self.assertRaisesRegex(ValueError, "only correct pressure"):
            pressure.check(doc)

    def test_a_pixel_row_that_hides_a_failure_does_not_read_as_complete(self):
        doc = self.example()
        doc["rows"][0]["outcomes"] = ["pass", "fail", "pass"]
        with self.assertRaisesRegex(ValueError, "status differs"):
            pressure.check(doc)

    def test_the_committed_rehearsal_reads_and_names_the_stand_ins_bank(self):
        doc = pressure.read(REPO / "docs/measurements/271-pixel-pressure.json")
        self.assertEqual(doc["status"], "complete")
        self.assertEqual(doc["replays"], 9)
        stand_in = json.loads((REPO / "bench/jit/stand-in/enemy-walks-backwards-faces-motion/jit-run.json").read_text())
        self.assertEqual(doc["pixelObserver"]["setting"], stand_in["pixelChecks"][0]["setting"])
        self.assertEqual({r["specId"] for r in doc["rows"]}, {p["check"]["id"] for p in stand_in["pixelChecks"]})

    def test_the_old_example_without_an_observer_still_reads(self):
        doc = json.loads((REPO / "contracts/examples/jit-pressure.json").read_text())
        self.assertNotIn("pixelObserver", doc)
        pressure.check(doc)


class Command(unittest.TestCase):
    def test_the_plan_names_the_pixel_rule(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(pressure.main(["correct"]), 0)
        self.assertIn("--sensor-bank", out.getvalue())

    def test_the_adversary_takes_no_bank(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            pressure.main(["adversary", "--preflight", "--sensor-bank", "bank.json"])


if __name__ == "__main__":
    unittest.main()
