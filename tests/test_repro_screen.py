"""What each bench defect changes on the screen (issue #285, for #286): frames compared with the clean
game's, beside the engine's record. Offline: a simulated game that also paints small frames; no engine,
no model, no key. The recorded measurement at the end was made on the real engine and is only read here."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from expectrail.contracts import load_strict
from expectrail.jit.probes import jit_library
from expectrail.repro import bench, screen, visibility
from expectrail.repro.__main__ import main
from harness.unity import png_pixels
from tests.test_discovery import PROFILE
from tests.test_repro_bench import PUBLIC, REPO, STUB, Game, Refusals

W, H = 32, 20
BACK, PLAYER, ODD = (10, 10, 10), (250, 250, 250), (250, 0, 0)


def png(path: Path, pixels: dict, width: int = W, height: int = H, alpha: bool = False) -> None:
    """A small PNG: the background, and ``pixels`` {(x, y): (r, g, b)} on it."""
    rows = b""
    for y in range(height):
        row = b"".join(bytes(pixels.get((x, y), BACK)) + (b"\xff" if alpha else b"") for x in range(width))
        rows += b"\0" + row

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


class Painter(Game):
    """The bench tests' simulated game, which also paints a frame every second tick: the player as one
    pixel, moved by the camera. More patches, recognised by file name:

    - red-player: the player is painted red; the record is the same (screen only).
    - corner: the top left pixel is painted red on every frame; the record is the same.
    - short: the last frame is not written.  - wide: the frames are one pixel wider.
    - no-frames: nothing is painted.

    Bullets are never painted, so gun-cooldown changes the record and no frame (record only).
    ``flicker`` names a probe whose top left pixel is red on frame 3 of the first clean replay only."""

    def __init__(self, jitter: str | None = None, flicker: str | None = None):
        super().__init__(jitter)
        self.flicker, self.replays, self.painted = flicker, [], {}

    def __call__(self, route_path, run_dir, patches=()):
        stems = {Path(p).stem for p in patches}
        mine = ("red-player", "corner", "short", "wide", "no-frames")
        super().__call__(route_path, run_dir, patches=[p for p in patches if Path(p).stem not in mine])
        run_dir = Path(run_dir)
        name = json.loads(Path(route_path).read_text())["name"]
        self.replays.append((name, tuple(sorted(stems))))
        n = self.painted[name] = self.painted.get(name, 0) + (0 if stems else 1)
        rows = json.loads((run_dir / "trace.json").read_text())["rows"]
        frames = run_dir / "frames"
        frames.mkdir(parents=True, exist_ok=True)
        if "no-frames" in stems:
            return
        shown = rows[::2][:-1] if "short" in stems else rows[::2]
        for i, row in enumerate(shown):
            x = int((row["player"][0] + row["view"][4]) / 25) % W
            y = max(0, min(H - 1, int(row["player"][1] / 40)))
            pixels = {(x, y): ODD if "red-player" in stems else PLAYER}
            if "corner" in stems or (not stems and name == self.flicker and n == 1 and i == 3):
                pixels[(0, 0)] = ODD
            png(frames / f"f{i:08d}.png", pixels, width=W + 1 if "wide" in stems else W)


def rgb(pixels: dict, width: int = W, height: int = H) -> bytes:
    return b"".join(bytes(pixels.get((x, y), BACK)) for y in range(height) for x in range(width))


class TwoFrames(unittest.TestCase):
    def test_the_same_frame_differs_nowhere(self):
        a = rgb({(3, 4): PLAYER})
        self.assertEqual(screen.extent(screen.differing(a, a), W), (0, None))

    def test_every_pixel_that_differs_is_counted_and_boxed(self):
        a = rgb({(3, 4): PLAYER})
        b = rgb({(7, 9): PLAYER})
        self.assertEqual(screen.extent(screen.differing(a, b), W), (2, [3, 4, 8, 10]))

    def test_one_channel_one_level_apart_is_a_difference(self):
        for channel in range(3):
            colour = list(BACK)
            colour[channel] += 1
            mask = screen.differing(rgb({}), rgb({(5, 6): tuple(colour)}))
            self.assertEqual(screen.extent(mask, W), (1, [5, 6, 6, 7]), channel)

    def test_the_corners_and_the_edges(self):
        for x, y in ((0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)):
            mask = screen.differing(rgb({}), rgb({(x, y): ODD}))
            self.assertEqual(screen.extent(mask, W), (1, [x, y, x + 1, y + 1]), (x, y))
        both = screen.differing(rgb({}), rgb({(0, 0): ODD, (W - 1, H - 1): ODD}))
        self.assertEqual(screen.extent(both, W), (2, [0, 0, W, H]))

    def test_a_whole_frame(self):
        mask = screen.differing(rgb({}), bytes(b ^ 1 for b in rgb({})))
        self.assertEqual(screen.extent(mask, W), (W * H, [0, 0, W, H]))

    def test_ignored_pixels_are_cleared_and_no_others(self):
        mask = screen.differing(rgb({}), rgb({(1, 1): ODD, (2, 2): ODD}))
        ignore = screen.differing(rgb({}), rgb({(1, 1): PLAYER, (9, 9): PLAYER}))
        self.assertEqual(screen.extent(screen.without(mask, ignore), W), (1, [2, 2, 3, 3]))
        self.assertEqual(screen.without(mask, None), mask)

    def test_a_union_keeps_both(self):
        a = screen.differing(rgb({}), rgb({(1, 1): ODD}))
        b = screen.differing(rgb({}), rgb({(4, 5): ODD}))
        self.assertEqual(screen.extent(screen.union(a, b), W), (2, [1, 1, 5, 6]))
        self.assertEqual(screen.union(None, b), b)

    def test_a_frame_with_alpha_reads_as_the_same_picture(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain, alpha = Path(tmp) / "a.png", Path(tmp) / "b.png"
            png(plain, {(3, 4): PLAYER, (0, 0): ODD})
            png(alpha, {(3, 4): PLAYER, (0, 0): ODD}, alpha=True)
            self.assertEqual(screen.decode(plain), (W, H, rgb({(3, 4): PLAYER, (0, 0): ODD})))
            self.assertEqual(screen.decode(alpha), screen.decode(plain))
            # the standard-library reader, which decodes where Pillow is not installed, agrees
            w, h, channels, pixels = png_pixels.read(plain)
            self.assertEqual((w, h, channels, pixels), (W, H, 3, screen.decode(plain)[2]))


class TwoReplays(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="repro-screen-frames-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def frames(self, name, pictures, **kw):
        folder = self.tmp / name
        folder.mkdir()
        for i, pixels in enumerate(pictures):
            png(folder / f"f{i:08d}.png", pixels, **kw)
        return folder

    def test_the_same_frames(self):
        a = self.frames("a", [{(1, 1): PLAYER}] * 4)
        b = self.frames("b", [{(1, 1): PLAYER}] * 4)
        self.assertEqual(screen.compare_frames(a, b), {"frames": 4, "size": [W, H], "differing": 0, "first": None,
                                                       "maxPixels": 0, "box": None})

    def test_the_first_frame_the_count_the_most_pixels_and_the_box_over_all_frames(self):
        a = self.frames("a", [{}] * 5)
        b = self.frames("b", [{}, {}, {(2, 3): ODD}, {}, {(8, 9): ODD, (9, 9): ODD}])
        self.assertEqual(screen.compare_frames(a, b), {"frames": 5, "size": [W, H], "differing": 2, "first": 2,
                                                       "maxPixels": 2, "box": [2, 3, 10, 10]})

    def test_a_difference_on_the_very_first_frame(self):
        a = self.frames("a", [{}] * 2)
        b = self.frames("b", [{(0, 0): ODD}, {}])
        found = screen.compare_frames(a, b)
        self.assertEqual((found["first"], found["differing"]), (0, 1))

    def test_ignored_pixels_do_not_make_a_frame_differ(self):
        a = self.frames("a", [{}] * 3)
        b = self.frames("b", [{}, {(0, 0): ODD}, {(0, 0): ODD, (5, 5): ODD}])
        ignore = screen.differing(rgb({}), rgb({(0, 0): ODD}))
        found = screen.compare_frames(a, b, ignore)
        self.assertEqual((found["differing"], found["first"], found["maxPixels"], found["box"]), (1, 2, 1, [5, 5, 6, 6]))

    def test_the_mask_of_everything_that_differed(self):
        a = self.frames("a", [{}] * 3)
        b = self.frames("b", [{(1, 1): ODD}, {}, {(4, 4): ODD}])
        found = screen.compare_frames(a, b, keep_mask=True)
        self.assertEqual(screen.extent(found["mask"], W), (2, [1, 1, 5, 5]))
        self.assertIsNone(screen.compare_frames(a, a, keep_mask=True)["mask"])

    def test_another_number_of_frames_cannot_be_compared(self):
        a = self.frames("a", [{}] * 3)
        b = self.frames("b", [{}] * 2)
        with self.assertRaisesRegex(screen.ScreenError, "2 frames against the clean game's 3"):
            screen.compare_frames(a, b)
        with self.assertRaisesRegex(screen.ScreenError, "3 frames against the clean game's 2"):
            screen.compare_frames(b, a)

    def test_another_size_cannot_be_compared(self):
        a = self.frames("a", [{}] * 2)
        b = self.frames("b", [{}] * 2, width=W + 1)
        with self.assertRaisesRegex(screen.ScreenError, "frames of two sizes"):
            screen.compare_frames(a, b)

    def test_a_clean_replay_with_no_frames_cannot_be_compared(self):
        a = self.frames("a", [])
        with self.assertRaisesRegex(screen.ScreenError, "no frames"):
            screen.compare_frames(a, a)


class Measurement(unittest.TestCase):
    NAMES = ["camera-shift", "red-player", "gun-cooldown", "no-change", "corner", "crash", "script-error", "short",
             "wide", "no-frames"]

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="repro-screen-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "game" / "platformer" / "player").mkdir(parents=True)
        (self.tmp / "game" / "platformer" / "player" / "player.gd").write_text("a\n")
        (self.tmp / "bench").mkdir()
        (self.tmp / "bench" / "report.txt").write_text("It is broken.\n")
        for i, name in enumerate(self.NAMES):
            (self.tmp / "bench" / f"{name}.patch").write_text(STUB.replace("+b", f"+b{i}"))
        self.doc = {"format": "expectrail.repro-bench/v1", "description": "test", "game": "game/platformer",
                    "defects": [Refusals.defect(n, f"bench/{n}.patch") for n in self.NAMES]}
        self.bench_path = self.tmp / "bench" / "defects.json"
        self.bench_path.write_text(json.dumps(self.doc))
        self.assertEqual(bench.problems(self.doc, self.tmp), [])
        self.profile = load_strict(PROFILE, "mechanics-profile")
        self.probes = [p for p in jit_library(self.profile["actions"])
                       if p["id"] in ("jump-w0-x2", "shoot-right-every12", "hold-right")]

    def measure(self, game=None, out="out", **kw):
        return screen.measure(self.doc, self.profile, self.probes, self.tmp / out, runner=game or Painter(),
                              root=self.tmp, bench_path=self.bench_path, **kw)

    def test_each_defect_is_sorted_by_what_it_changes_in_the_record_and_on_the_screen(self):
        record = self.measure()
        rows = {r["id"]: r for r in record["defects"]}
        self.assertEqual({k: v["shows"] for k, v in rows.items()},
                         {"camera-shift": "record-and-screen", "red-player": "screen-only", "gun-cooldown": "record-only",
                          "no-change": "neither", "corner": "screen-only", "crash": "error", "script-error": "error",
                          "short": "error", "wide": "error", "no-frames": "error"})
        self.assertEqual(record["totals"], {"defects": 10, "record-and-screen": 1, "screen-only": 2, "record-only": 1,
                                            "neither": 1, "error": 5})
        self.assertEqual(record["capture"]["width"], W)
        self.assertEqual(record["capture"]["height"], H)
        self.assertEqual(record["unstable"], [])
        self.assertEqual(screen.load(self.tmp / "out" / screen.NAME), record)

    def test_a_screen_only_defect_says_where_and_from_which_frame_on_every_probe(self):
        rows = {r["id"]: r for r in self.measure(only=["red-player", "corner"])["defects"]}
        red = rows["red-player"]
        self.assertEqual(red["recordFields"], [])
        self.assertEqual([p["probe"] for p in red["probes"]], sorted(p["id"] for p in self.probes))
        for p in red["probes"]:
            self.assertEqual((p["recordFields"], p["recordFirstTick"]), ([], None))
            self.assertEqual((p["screenFrames"], p["screenFirstFrame"], p["maxPixels"]), (p["frames"], 0, 1))
        for p in rows["corner"]["probes"]:
            self.assertEqual((p["screenFrames"], p["box"]), (p["frames"], [0, 0, 1, 1]))

    def test_a_record_only_defect_lists_the_record_and_no_frame(self):
        gun = {r["id"]: r for r in self.measure(only=["gun-cooldown"])["defects"]}["gun-cooldown"]
        self.assertEqual(gun["recordFields"], ["projectiles"])
        self.assertEqual([p["probe"] for p in gun["probes"]], ["shoot-right-every12"])
        p = gun["probes"][0]
        self.assertEqual((p["screenFrames"], p["screenFirstFrame"], p["maxPixels"], p["box"]), (0, None, 0, None))
        self.assertGreater(p["recordFirstTick"], 0)

    def test_the_record_and_the_screen_each_get_their_own_first_moment(self):
        cam = {r["id"]: r for r in self.measure(only=["camera-shift"])["defects"]}["camera-shift"]
        self.assertEqual(cam["recordFields"], ["view"])
        for p in cam["probes"]:
            self.assertEqual((p["recordFirstTick"], p["screenFirstFrame"], p["screenFrames"]), (0, 0, p["frames"]))
            self.assertEqual(p["maxPixels"], 2)        # the player's pixel where it was, and where it is now

    def test_a_build_that_cannot_be_compared_is_an_error_with_its_reason_never_a_guess(self):
        rows = {r["id"]: r for r in self.measure()["defects"]}
        self.assertIn("could not be replayed in 3 attempts", rows["crash"]["error"])
        self.assertIn("script error", rows["script-error"]["error"])
        self.assertIn("cannot be compared frame for frame", rows["short"]["error"])
        self.assertIn("frames of two sizes", rows["wide"]["error"])
        self.assertIn("no frame was captured", rows["no-frames"]["error"])
        for name in ("crash", "script-error", "short", "wide", "no-frames"):
            self.assertEqual((rows[name]["probes"], rows[name]["recordFields"]), ([], []), name)

    def test_what_differs_between_the_two_clean_replays_is_not_counted(self):
        record = self.measure(Painter(jitter="hold-right", flicker="jump-w0-x2"), only=["corner", "camera-shift", "red-player"])
        # a camera one pixel off moves no painted pixel here, so hold-right is unstable in the record alone
        self.assertEqual(record["unstable"], [{"probe": "hold-right", "fields": ["view"], "frames": 0, "pixels": 0},
                                              {"probe": "jump-w0-x2", "fields": [], "frames": 1, "pixels": 1}])
        rows = {r["id"]: r for r in record["defects"]}
        # the corner pixel flickered on jump-w0-x2, so a defect that only paints that pixel is not seen there
        self.assertNotIn("jump-w0-x2", [p["probe"] for p in rows["corner"]["probes"]])
        self.assertIn("shoot-right-every12", [p["probe"] for p in rows["corner"]["probes"]])
        # the player's pixel is not the corner, so the red player still shows on that probe
        self.assertIn("jump-w0-x2", [p["probe"] for p in rows["red-player"]["probes"]])
        # the view was unstable on hold-right, so the camera defect's record does not count there
        cam = {p["probe"]: p for p in rows["camera-shift"]["probes"]}
        self.assertEqual(cam["shoot-right-every12"]["recordFields"], ["view"])
        self.assertEqual(cam.get("hold-right", {"recordFields": []})["recordFields"], [])

    def test_clean_replays_that_cannot_be_compared_stop_the_measurement(self):
        class ShortOnce(Painter):
            def __call__(self, route_path, run_dir, patches=()):
                super().__call__(route_path, run_dir, patches=patches)
                if not patches and len([r for r in self.replays if not r[1]]) == 1:
                    sorted((Path(run_dir) / "frames").glob("f*.png"))[-1].unlink()

        with self.assertRaisesRegex(screen.ScreenError, "two replays of the clean game cannot be compared"):
            self.measure(ShortOnce())
        self.assertFalse((self.tmp / "out" / screen.NAME).exists())

    def test_a_clean_game_that_cannot_be_replayed_stops_the_measurement(self):
        class Dead(Painter):
            def __call__(self, route_path, run_dir, patches=()):
                raise RuntimeError("godot exited with code 1")

        with self.assertRaisesRegex(screen.ScreenError, "the clean game could not be replayed"):
            self.measure(Dead())

    def test_an_engine_that_fails_once_is_replayed_again_and_the_retry_is_counted(self):
        class CrashesOnce(Painter):
            failed = False

            def __call__(self, route_path, run_dir, patches=()):
                if patches and not self.failed:
                    self.failed = True
                    raise RuntimeError("signal 11")
                super().__call__(route_path, run_dir, patches=patches)

        record = self.measure(CrashesOnce(), only=["red-player"])
        self.assertEqual(record["engineRetries"], 1)
        self.assertEqual(record["defects"][0]["shows"], "screen-only")

    def test_a_stopped_measurement_goes_on_from_the_builds_it_finished(self):
        game = Painter()
        first = self.measure(game, only=["red-player"])
        made = len(game.replays)
        self.assertEqual(made, 3 * len(self.probes))
        again = self.measure(game, only=["red-player", "no-change"])
        self.assertEqual(len(game.replays) - made, len(self.probes))          # only the new build was replayed
        self.assertEqual({r[1] for r in game.replays[made:]}, {("no-change",)})
        self.assertEqual(again["defects"][0], first["defects"][0])

    def test_a_build_that_failed_is_tried_again_and_not_remembered(self):
        game = Painter()
        self.assertEqual(self.measure(game, only=["crash"])["defects"][0]["shows"], "error")
        made = len(game.replays)
        self.measure(game, only=["crash"])
        self.assertEqual(len(game.replays), made)       # the simulated crash is raised before a replay is counted
        self.assertFalse((self.tmp / "out" / "work" / "done" / "crash.json").exists())

    def test_work_left_by_other_probes_or_another_bench_is_refused(self):
        self.measure(only=["no-change"])
        self.probes = self.probes[:2]
        with self.assertRaisesRegex(screen.ScreenError, "another bench or other probes"):
            self.measure(only=["no-change"])

    def test_no_frames_are_left_behind_but_the_clean_games(self):
        self.measure(only=["red-player"])
        left = sorted(p.parent.relative_to(self.tmp / "out" / "work").parts[0] for p in (self.tmp / "out").rglob("f*.png"))
        self.assertEqual(set(left), {"clean-frames"})

    def test_probes_are_chosen_by_name_in_the_library_order_and_an_unknown_name_is_refused(self):
        library = jit_library(self.profile["actions"])
        self.assertEqual(screen.choose(library, []), library)
        self.assertEqual([p["id"] for p in screen.choose(library, ["reverse", "wait-long", "reverse"])], ["wait-long", "reverse"])
        with self.assertRaisesRegex(screen.ScreenError, "not a library probe: 'nope'"):
            screen.choose(library, ["hold-right", "nope"])


class TheRecord(unittest.TestCase):
    """A record is data: one whose parts do not agree is refused."""

    def setUp(self):
        probe = {"probe": "hold-right", "recordFields": ["view"], "recordFirstTick": 4, "frames": 10, "screenFrames": 3,
                 "screenFirstFrame": 7, "maxPixels": 6, "box": [1, 2, 4, 4]}
        quiet = {"probe": "reverse", "recordFields": [], "recordFirstTick": None, "frames": 10, "screenFrames": 10,
                 "screenFirstFrame": 0, "maxPixels": 1, "box": [0, 0, 1, 1]}
        self.record = {
            "format": screen.FORMAT, "benchSha256": "a" * 64, "engine": "Godot test", "probes": ["hold-right", "reverse"],
            "capture": {"fps": 60, "width": 32, "height": 20, "frames": 20},
            "replaysPerBuild": {"clean": 2, "defect": 1}, "engineRetries": 0, "unstable": [],
            "defects": [{"id": "one", "patchSha256": "b" * 64, "shows": "record-and-screen", "recordFields": ["view"],
                         "probes": [probe]},
                        {"id": "two", "patchSha256": "c" * 64, "shows": "screen-only", "recordFields": [], "probes": [quiet]},
                        {"id": "three", "patchSha256": "d" * 64, "shows": "neither", "recordFields": [], "probes": []},
                        {"id": "four", "patchSha256": "e" * 64, "shows": "error", "recordFields": [], "probes": [],
                         "error": "ScreenError: probe x: 2 frames against the clean game's 3"}],
            "totals": {"defects": 4, "record-and-screen": 1, "screen-only": 1, "record-only": 0, "neither": 1, "error": 1}}

    def refused(self, change, why):
        record = copy.deepcopy(self.record)
        change(record)
        found = screen.problems(record)
        self.assertTrue(found, why)
        self.assertIn(why, " ".join(found))

    def test_the_fixture_is_clean_and_renders(self):
        self.assertEqual(screen.problems(self.record), [])
        page = screen.render(self.record)
        self.assertIn("The record and the screen both differ: 1. Only the screen differs: 1.", page)
        self.assertIn("| `one` |  |  | record-and-screen | 1 (`view`) | 1 | `hold-right`, 3 of 10, from 7, 6, 1,2 to 4,4 |", page)
        self.assertIn("| `three` |  |  | neither | none | none |  |", page)
        self.assertIn("| `four` |  |  | error |", page)
        self.assertIn("Could not be measured: 1.", page)

    def test_a_label_that_does_not_follow_from_the_probes(self):
        for i, label in ((0, "screen-only"), (1, "record-and-screen"), (2, "record-only"), (1, "neither")):
            self.refused(lambda r, i=i, label=label: r["defects"][i].update(shows=label), "does not follow from its probes")

    def test_an_error_row_with_a_measurement_or_without_a_reason(self):
        self.refused(lambda r: r["defects"][3].pop("error"), "an error row carries a reason")
        self.refused(lambda r: r["defects"][3].update(recordFields=["view"]), "an error row carries a reason")
        self.refused(lambda r: r["defects"][2].update(error="x"), "does not follow from its probes")

    def test_a_probe_row_that_disagrees_with_itself(self):
        p = lambda r: r["defects"][0]["probes"][0]  # noqa: E731
        self.refused(lambda r: p(r).update(screenFirstFrame=None), "do not agree")
        self.refused(lambda r: p(r).update(box=None), "do not agree")
        self.refused(lambda r: p(r).update(maxPixels=0), "do not agree")
        self.refused(lambda r: p(r).update(screenFrames=11), "do not agree")
        self.refused(lambda r: p(r).update(recordFirstTick=None), "the first tick does not agree")
        self.refused(lambda r: p(r).update(screenFirstFrame=8), "cannot be right for the capture")      # 8 + 3 > 10
        self.refused(lambda r: p(r).update(box=[1, 2, 33, 4]), "cannot be right for the capture")
        self.refused(lambda r: p(r).update(box=[4, 2, 1, 4]), "cannot be right for the capture")
        self.refused(lambda r: p(r).update(maxPixels=7), "cannot be right for the capture")            # the box holds 6
        self.refused(lambda r: r["defects"][1]["probes"][0].update(screenFrames=0, screenFirstFrame=None, maxPixels=0, box=None),
                     "listed, and nothing differs")

    def test_fields_probes_totals_and_ids_must_agree(self):
        self.refused(lambda r: r["defects"][0].update(recordFields=[]), "recordFields is not what its probes list")
        self.refused(lambda r: r["defects"][0]["probes"][0].update(probe="wait-long"), "not one of the record's")
        self.refused(lambda r: r["defects"][0]["probes"].append(copy.deepcopy(r["defects"][0]["probes"][0])), "listed twice")
        self.refused(lambda r: r["totals"].update(neither=2), "the totals do not match")
        self.refused(lambda r: r["defects"][1].update(id="one"), "a defect is listed twice")
        self.refused(lambda r: r["unstable"].append({"probe": "hold-right", "fields": [], "frames": 0, "pixels": 0}),
                     "does not agree with itself")
        self.refused(lambda r: r["unstable"].append({"probe": "hold-right", "fields": [], "frames": 2, "pixels": 0}),
                     "does not agree with itself")

    def test_the_schema_refuses_what_it_does_not_name(self):
        self.refused(lambda r: r.update(note="x"), "Additional properties")
        self.refused(lambda r: r["defects"][0].update(shows="mostly"), "is not one of")
        self.refused(lambda r: r["replaysPerBuild"].update(clean=1), "2 was expected")
        self.refused(lambda r: r["defects"][0]["probes"][0].update(box=[1, 2, 4]), "box")
        self.refused(lambda r: r["defects"][0]["probes"][0].update(screenFrames=-1), "screenFrames")

    def test_a_file_that_is_not_a_record_is_refused_with_a_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            for text, why in (("{", "unreadable"), ('{"format": 1, "format": 2}', "unreadable"),
                              (json.dumps({"format": screen.FORMAT}), "repro-screen:"),
                              (" " * (screen.MAX_BYTES + 1), "over")):
                path.write_text(text)
                with self.assertRaisesRegex(screen.ScreenError, why):
                    screen.load(path)

    def test_the_probe_a_reader_is_pointed_at(self):
        row = {"probes": [dict(probe="b", screenFrames=5, screenFirstFrame=2), dict(probe="a", screenFrames=5, screenFirstFrame=2),
                          dict(probe="c", screenFrames=5, screenFirstFrame=1), dict(probe="d", screenFrames=0, screenFirstFrame=None)]}
        self.assertEqual(screen.clearest(row)["probe"], "c")
        self.assertIsNone(screen.clearest({"probes": row["probes"][3:]}))


class Commands(unittest.TestCase):
    def test_a_record_that_cannot_be_read_is_an_error_and_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            path.write_text("{}")
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["screen-render", str(path)]), 1)
            self.assertIn("repro: repro-screen:", err.getvalue())

    def test_an_unknown_probe_is_refused_before_anything_is_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["screen", "--out", str(Path(tmp) / "out"), "--probe", "nope"]), 1)
            self.assertIn("not a library probe", err.getvalue())
            self.assertFalse((Path(tmp) / "out").exists())

    def test_nothing_under_jit_reads_the_screen_measurement(self):
        """A live run on the bench, the baseline included, is the same with or without this module."""
        for path in sorted((REPO / "expectrail" / "jit").glob("*.py")) + [REPO / ".github" / "workflows" / "jit.yml"]:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("repro.screen", text, path.name)
            self.assertNotIn("repro import screen", text, path.name)
            self.assertNotIn("screen.json", text, path.name)


if __name__ == "__main__":
    unittest.main()
