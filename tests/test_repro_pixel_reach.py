"""expectrail.repro.pixel_reach: could an offered pixel check fail on a defect at all? No model, no engine."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail.contracts import load_strict
from expectrail.jit.probes import jit_library
from expectrail.repro import bench, pixel_reach
from expectrail.repro.__main__ import main
from tests import test_repro_bench as repro_bench
from tests.test_discovery import PROFILE
from tests.test_unity_png_pixels import write_png

W, H = 40, 20
BACK = (10, 20, 30)
# The player's logged body box in world pixels; the view is the identity, so the observer's box in the
# frame is this widened by the default 4 game pixels: [0, 0, 12, 12].
BODY = [4.0, 4.0, 8.0, 8.0]
INSIDE, OUTSIDE = (6, 6), (35, 17)


def picture(marks=()) -> bytes:
    out = bytearray()
    for y in range(H):
        for x in range(W):
            out += bytes((200, 0, 0) if (x, y) in marks else BACK)
    return bytes(out)


def write_run(run_dir: Path, ticks: int, marks_for, body=BODY, frames: int | None = None):
    """A replay folder as the harness writes it: trace.json (player, body box, identity view) and frames."""
    run_dir = Path(run_dir)
    (run_dir / "frames").mkdir(parents=True, exist_ok=True)
    rows = [{"tick": t, "player": [6.0, 6.0], "view": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
             **({"body": body} if body else {})} for t in range(ticks)]
    (run_dir / "trace.json").write_text(json.dumps({"physicsTicksPerSecond": 120, "rows": rows}))
    for n in range(ticks // 2 if frames is None else frames):
        write_png(run_dir / "frames" / f"f{n:08d}.png", W, H, picture(marks_for(n)))


class Painted:
    """A stand-in for the harness: draws nothing but the marks a patch's file name asks for.

    - in-box: one pixel inside the player's box on every frame.
    - outside: one pixel in the far corner on every frame.
    - between: one pixel inside the box on frame 1 only, which the observer never plans.
    - crash: the replay fails."""

    def __call__(self, route_path, run_dir, patches=()):
        stems = {Path(p).stem for p in patches}
        if "crash" in stems:
            raise RuntimeError("the engine stopped")
        ticks = json.loads(Path(route_path).read_text())["ticks"]

        def marks(n):
            got = set()
            if "in-box" in stems:
                got.add(INSIDE)
            if "outside" in stems:
                got.add(OUTSIDE)
            if "between" in stems and n == 1:
                got.add(INSIDE)
            return got
        write_run(run_dir, ticks, marks)


class OneProbe(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pixel-reach-probe-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.route = {"ticks": 100}     # 50 frames: the observer plans 0, 10, 20, 30, 40, 49
        write_run(self.tmp / "clean", 100, lambda n: set())

    def reach(self, marks_for, **kw):
        write_run(self.tmp / "defect", 100, marks_for, **kw)
        return pixel_reach.probe_reach(self.tmp / "clean", self.tmp / "defect", self.route)

    def test_a_difference_inside_the_box_on_a_planned_frame_is_counted(self):
        got = self.reach(lambda n: {INSIDE})
        self.assertEqual(got, {"framesAsked": 6, "framesDiffer": 6, "framesDifferInBox": 6, "maxPixelsInBox": 1,
                               "gaps": 0, "boxesMoved": 0})
        self.assertEqual(pixel_reach.reach_of([got]), "inside-a-box")

    def test_a_difference_outside_the_box_is_never_counted_inside(self):
        got = self.reach(lambda n: {OUTSIDE})
        self.assertEqual((got["framesDiffer"], got["framesDifferInBox"], got["maxPixelsInBox"]), (6, 0, 0))
        self.assertEqual(pixel_reach.reach_of([got]), "outside-every-box")

    def test_a_difference_only_between_planned_frames_is_no_difference(self):
        got = self.reach(lambda n: {INSIDE} if n == 1 else set())
        self.assertEqual(got["framesDiffer"], 0)
        self.assertEqual(pixel_reach.reach_of([got]), "no-difference")

    def test_the_box_is_the_observers_own_widened_body_box(self):
        # (12, 6) is one pixel right of the widened box; (11, 6) is its last column.
        self.assertEqual(self.reach(lambda n: {(12, 6)})["framesDifferInBox"], 0)
        self.assertEqual(self.reach(lambda n: {(11, 6)})["framesDifferInBox"], 6)

    def test_a_frame_with_no_body_box_is_a_gap_and_never_counted_inside(self):
        got = self.reach(lambda n: {INSIDE}, body=None)
        self.assertEqual((got["gaps"], got["framesDiffer"], got["framesDifferInBox"]), (6, 6, 0))

    def test_when_the_builds_put_the_box_in_different_places_both_boxes_count(self):
        # The defect build's body is far to the right; its mark sits in its own box, outside the clean one.
        got = self.reach(lambda n: {(30, 6)}, body=[28.0, 4.0, 32.0, 8.0])
        self.assertEqual((got["framesDifferInBox"], got["boxesMoved"]), (6, 6))

    def test_captures_of_different_lengths_are_refused(self):
        write_run(self.tmp / "short", 100, lambda n: set(), frames=40)
        with self.assertRaisesRegex(pixel_reach.PixelReachError, "cannot be compared frame by frame"):
            pixel_reach.probe_reach(self.tmp / "clean", self.tmp / "short", self.route)

    def test_only_the_player_can_be_measured(self):
        self.assertEqual(pixel_reach.offered(), ["player"])
        menu = {"observers": {"sam-3.1-anchor": {"objects": ["player", "bullet"]}}}
        with self.assertRaisesRegex(pixel_reach.PixelReachError, "'bullet'"):
            pixel_reach.offered(menu)
        self.assertEqual(pixel_reach.offered({"observers": {}}), [])


class Measure(unittest.TestCase):
    NAMES = ("in-box", "outside", "between", "crash")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pixel-reach-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "game" / "platformer" / "player").mkdir(parents=True)
        (self.tmp / "game" / "platformer" / "player" / "player.gd").write_text("a\n")
        (self.tmp / "bench").mkdir()
        (self.tmp / "bench" / "report.txt").write_text("It is broken.\n")
        for i, name in enumerate(self.NAMES):
            (self.tmp / "bench" / f"{name}.patch").write_text(repro_bench.STUB.replace("+b", f"+b{i}"))
        self.doc = {"format": "expectrail.repro-bench/v1", "description": "test", "game": "game/platformer",
                    "defects": [repro_bench.Refusals.defect(n, f"bench/{n}.patch") for n in self.NAMES]}
        self.bench_path = self.tmp / "bench" / "defects.json"
        self.bench_path.write_text(json.dumps(self.doc))
        self.assertEqual(bench.problems(self.doc, self.tmp), [])
        self.profile = load_strict(PROFILE, "mechanics-profile")
        self.probes = [p for p in jit_library(self.profile["actions"]) if p["id"] in ("jump-w0-x1", "hold-right")]

    def measure(self, names=None):
        return pixel_reach.measure(self.doc, self.profile, self.probes, self.tmp / "out", names or self.NAMES,
                                   runner=Painted(), root=self.tmp, bench_path=self.bench_path)

    def test_each_defect_is_sorted_by_whether_an_offered_box_ever_shows_its_difference(self):
        record = self.measure()
        rows = {r["id"]: r for r in record["defects"]}
        self.assertEqual({k: v["reach"] for k, v in rows.items()},
                         {"in-box": "inside-a-box", "outside": "outside-every-box", "between": "no-difference",
                          "crash": "error"})
        self.assertEqual(record["totals"], {"defects": 4, "inside-a-box": 1, "outside-every-box": 1,
                                            "no-difference": 1, "error": 1})
        self.assertEqual(([p["probe"] for p in rows["in-box"]["probes"]], rows["in-box"]["probesMeasured"]),
                         (["hold-right", "jump-w0-x1"], 2))
        self.assertEqual((rows["between"]["probes"], rows["between"]["probesMeasured"]), ([], 2))
        self.assertIn("the engine stopped", rows["crash"]["error"])
        self.assertEqual((record["objects"], record["observer"]["name"], record["observer"]["box"]),
                         (["player"], "sam-3.1-anchor", "body"))
        self.assertEqual(pixel_reach.load(self.tmp / "out" / pixel_reach.NAME), record)
        self.assertFalse((self.tmp / "out" / "work").exists())
        self.assertEqual(pixel_reach.stale(record, self.doc, self.tmp, self.bench_path), [])
        table = pixel_reach.render(record)
        self.assertIn("| `in-box` | inside-a-box | 2 of 2 |", table)
        self.assertIn("| `crash` | error |", table)

    def test_a_defect_the_bench_does_not_have_is_refused(self):
        with self.assertRaisesRegex(pixel_reach.PixelReachError, "no defect 'nope'"):
            self.measure(["nope"])

    def test_the_reader_refuses_a_record_that_does_not_agree_with_itself(self):
        record = self.measure(["in-box", "outside"])
        cases = {
            "reach not from its probes": lambda r: r["defects"][1].update(reach="inside-a-box"),
            "totals": lambda r: r["totals"].update({"inside-a-box": 2}),
            "inside more than differ": lambda r: r["defects"][0]["probes"][0].update(framesDifferInBox=99),
            "pixels without a frame": lambda r: r["defects"][1]["probes"][0].update(maxPixelsInBox=3),
            "unknown probe": lambda r: r["defects"][0]["probes"][0].update(probe="wait-long"),
            "probe count": lambda r: r["defects"][0].update(probesMeasured=1),
            "error row with results": lambda r: r["defects"][0].update(reach="error", error="x"),
            "unknown key": lambda r: r.update(approval="me"),
            "two cleans": lambda r: r["replaysPerBuild"].update(clean=2),
        }
        for name, change in cases.items():
            with self.subTest(name):
                bad = copy.deepcopy(record)
                change(bad)
                self.assertTrue(pixel_reach.problems(bad))
                path = self.tmp / "bad.json"
                path.write_text(json.dumps(bad))
                with self.assertRaises(pixel_reach.PixelReachError):
                    pixel_reach.load(path)

    def test_a_changed_patch_makes_the_record_stale(self):
        record = self.measure(["in-box"])
        (self.tmp / "bench" / "in-box.patch").write_text(repro_bench.STUB.replace("+b", "+changed"))
        self.assertEqual(pixel_reach.stale(record, self.doc, self.tmp, self.bench_path),
                         ["in-box: its patch changed since the record was made"])


def write_named_run(run_dir: Path, ticks: int, marks_for, bullet=(28.0, 4.0, 32.0, 8.0), logged=True):
    """A replay folder whose trace also logs one bullet's box (id 5) and no enemy, as the harness has since
    November 15, 2026; ``logged`` False writes a trace from before (no objectBoxes)."""
    write_run(run_dir, ticks, marks_for)
    path = Path(run_dir) / "trace.json"
    doc = json.loads(path.read_text())
    for r in doc["rows"]:
        if logged:
            r["enemyBoxes"], r["projectileBoxes"] = [], ([[5, *bullet]] if bullet else [])
    if logged:
        doc["capabilities"] = {"objectBoxes": True}
    path.write_text(json.dumps(doc))


BULLET = (30, 6)    # inside the bullet's widened box [24, 0, 36, 12], outside the player's [0, 0, 12, 12]


class NamedObjects(unittest.TestCase):
    """Objects the menu does not offer yet, whose boxes the engine logs: measured beside the offered ones."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pixel-reach-named-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.route = {"ticks": 100}
        write_named_run(self.tmp / "clean", 100, lambda n: set())

    def reach(self, marks_for, named=("bullet", "enemy"), **kw):
        write_named_run(self.tmp / "defect", 100, marks_for, **kw)
        return pixel_reach.probe_reach(self.tmp / "clean", self.tmp / "defect", self.route, named=named)

    def test_a_difference_inside_a_bullets_box_counts_for_the_bullet_and_not_the_player(self):
        got = self.reach(lambda n: {BULLET})
        self.assertEqual((got["framesDiffer"], got["framesDifferInBox"]), (6, 0))
        self.assertEqual(got["byObject"], {"bullet": {"framesDifferInBox": 6, "maxPixelsInBox": 1, "gaps": 0},
                                           "enemy": {"framesDifferInBox": 0, "maxPixelsInBox": 0, "gaps": 0}})
        self.assertEqual(pixel_reach.reach_of([got]), "outside-every-box")
        self.assertEqual(pixel_reach.reach_of([got], named=True), "inside-a-box")

    def test_a_box_logged_on_only_one_build_still_counts(self):
        # The clean game logs the bullet; the defect build has none, and draws a pixel where it was.
        got = self.reach(lambda n: {BULLET}, bullet=None)
        self.assertEqual(got["byObject"]["bullet"]["framesDifferInBox"], 6)

    def test_no_object_on_screen_is_not_a_gap_and_a_trace_from_before_is(self):
        got = self.reach(lambda n: {OUTSIDE}, bullet=None)
        self.assertEqual(got["byObject"]["bullet"], {"framesDifferInBox": 0, "maxPixelsInBox": 0, "gaps": 0})
        got = self.reach(lambda n: {BULLET}, logged=False)
        self.assertEqual(got["byObject"]["bullet"]["gaps"], 6)
        # The clean game still logs its bullet, so its box is used; nothing is made up for the other build.
        self.assertEqual(got["byObject"]["bullet"]["framesDifferInBox"], 6)

    def test_without_named_objects_a_probe_is_as_before(self):
        self.assertNotIn("byObject", self.reach(lambda n: {BULLET}, named=()))

    def test_only_objects_the_engine_logs_a_box_for_and_the_menu_does_not_offer_are_named(self):
        self.assertEqual(pixel_reach.named_objects(["player"]), ["bullet", "enemy"])
        self.assertEqual(pixel_reach.named_objects(["player", "bullet"]), ["enemy"])
        self.assertEqual(pixel_reach.named_objects(["player"], []), [])
        with self.assertRaisesRegex(pixel_reach.PixelReachError, "no box for 'coin'"):
            pixel_reach.named_objects(["player"], ["coin"])


class NamedPainted(Painted):
    """Painted, with a bullet logged in every replay and a patch "bullet" that draws inside its box."""

    def __call__(self, route_path, run_dir, patches=()):
        stems = {Path(p).stem for p in patches}
        if "crash" in stems:
            raise RuntimeError("the engine stopped")
        ticks = json.loads(Path(route_path).read_text())["ticks"]
        write_named_run(run_dir, ticks, lambda n: ({INSIDE} if "in-box" in stems else set())
                        | ({BULLET} if "bullet" in stems else set()) | ({OUTSIDE} if "outside" in stems else set()))


class MeasureNamed(Measure):
    NAMES = ("in-box", "outside", "bullet", "crash")

    def measure(self, names=None, named=None):
        return pixel_reach.measure(self.doc, self.profile, self.probes, self.tmp / "out", names or self.NAMES,
                                   runner=NamedPainted(), root=self.tmp, bench_path=self.bench_path, named=named)

    def test_each_defect_is_sorted_by_whether_an_offered_box_ever_shows_its_difference(self):
        record = self.measure()
        rows = {r["id"]: r for r in record["defects"]}
        self.assertEqual({k: (v["reach"], v.get("reachIfNamed")) for k, v in rows.items()},
                         {"in-box": ("inside-a-box", "inside-a-box"), "outside": ("outside-every-box", "outside-every-box"),
                          "bullet": ("outside-every-box", "inside-a-box"), "crash": ("error", None)})
        self.assertEqual(record["named"], ["bullet", "enemy"])
        self.assertEqual(record["totalsIfNamed"], {"defects": 4, "inside-a-box": 2, "outside-every-box": 1,
                                                   "no-difference": 0, "error": 1})
        self.assertEqual(pixel_reach.load(self.tmp / "out" / pixel_reach.NAME), record)
        table = pixel_reach.render(record)
        self.assertIn("If a pixel check could also name bullet, enemy", table)
        self.assertIn("| `bullet` | inside-a-box | 24 (2) | 1 | 0 | 0 (0) | 0 | 0 |", table)

    def test_named_none_writes_a_record_as_before(self):
        record = self.measure(["bullet"], named=[])
        self.assertNotIn("named", record)
        self.assertNotIn("reachIfNamed", record["defects"][0])
        self.assertEqual(record["defects"][0]["reach"], "outside-every-box")

    def test_the_reader_refuses_a_record_whose_named_parts_do_not_agree(self):
        record = self.measure(["in-box", "bullet", "crash"])
        cases = {
            "reachIfNamed not from its probes": lambda r: r["defects"][1].update(reachIfNamed="no-difference"),
            "totalsIfNamed": lambda r: r["totalsIfNamed"].update({"inside-a-box": 0}),
            "totalsIfNamed without named": lambda r: r.pop("named"),
            "named without totalsIfNamed": lambda r: r.pop("totalsIfNamed"),
            "a row without reachIfNamed": lambda r: r["defects"][0].pop("reachIfNamed"),
            "an error row with reachIfNamed": lambda r: r["defects"][2].update(reachIfNamed="no-difference"),
            "a probe missing a named object": lambda r: r["defects"][1]["probes"][0]["byObject"].pop("enemy"),
            "a probe with an object not named": lambda r: r["defects"][1]["probes"][0]["byObject"].update(
                coin={"framesDifferInBox": 0, "maxPixelsInBox": 0, "gaps": 0}),
            "a named object offered too": lambda r: r.update(named=["bullet", "player"]),
            "a named object with no logged box": lambda r: r.update(named=["coin"]),
            "inside more than differ": lambda r: r["defects"][1]["probes"][0]["byObject"]["bullet"].update(
                framesDifferInBox=99),
            "pixels without a frame": lambda r: r["defects"][1]["probes"][0]["byObject"]["enemy"].update(maxPixelsInBox=2),
            "gaps over the frames asked": lambda r: r["defects"][1]["probes"][0]["byObject"]["enemy"].update(gaps=99),
        }
        for name, change in cases.items():
            with self.subTest(name):
                bad = copy.deepcopy(record)
                change(bad)
                self.assertTrue(pixel_reach.problems(bad))
                path = self.tmp / "bad.json"
                path.write_text(json.dumps(bad))
                with self.assertRaises(pixel_reach.PixelReachError):
                    pixel_reach.load(path)

    def test_a_defect_the_bench_does_not_have_is_refused(self):
        super().test_a_defect_the_bench_does_not_have_is_refused()

    def test_a_changed_patch_makes_the_record_stale(self):
        super().test_a_changed_patch_makes_the_record_stale()


class Committed(unittest.TestCase):
    """The committed record and the contract example are read by the reader, and the record describes the bench."""

    def test_the_example_is_read(self):
        example = Path(pixel_reach.REPO / "contracts" / "examples" / "repro-pixel-reach.json")
        self.assertEqual(pixel_reach.problems(json.loads(example.read_text())), [])

    def test_the_committed_record_is_read_and_is_not_stale(self):
        record = pixel_reach.load()
        self.assertEqual(pixel_reach.stale(record, bench.load()), [])
        self.assertEqual(record["objects"], pixel_reach.offered())

    def test_the_named_example_is_read(self):
        example = Path(pixel_reach.REPO / "contracts" / "examples" / "repro-pixel-reach-named.json")
        doc = json.loads(example.read_text())
        self.assertEqual(pixel_reach.problems(doc), [])
        self.assertEqual(doc["named"], ["bullet", "enemy"])

    def test_the_committed_record_measures_the_enemy_and_the_bullet_and_the_page_shows_it(self):
        record = pixel_reach.load()
        self.assertEqual(record["named"], pixel_reach.named_objects(record["objects"]))
        rows = {r["id"]: r for r in record["defects"]}
        frames = {did: {role: sum(p["byObject"][role]["framesDifferInBox"] for p in r["probes"]) for role in record["named"]}
                  for did, r in rows.items()}
        self.assertEqual(frames["enemy-walks-backwards"]["enemy"], 230)
        self.assertEqual(frames["bullet-behind-scenery"]["bullet"],
                         sum(p["framesDiffer"] for p in rows["bullet-behind-scenery"]["probes"]))
        page = (pixel_reach.REPO / "bench" / "jit" / "public" / "README.md").read_text(encoding="utf-8")
        start, end = "<!-- pixel-reach:start -->\n", "<!-- pixel-reach:end -->"
        self.assertEqual(page[page.index(start) + len(start):page.index(end)], pixel_reach.render(record))

    def test_the_command_line_renders_the_committed_record(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["pixel-reach-render", str(pixel_reach.RECORD)]), 0)
        self.assertIn("No model, nothing asked.", out.getvalue())

    def test_the_command_line_refuses_an_unknown_probe(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main(["pixel-reach", "--out", "/nonexistent-never-made", "--probe", "nope"]), 1)
        self.assertIn("no probe 'nope'", err.getvalue())


if __name__ == "__main__":
    unittest.main()
