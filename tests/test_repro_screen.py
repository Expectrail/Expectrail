"""expectrail.repro.screen: what each bench defect changes on the screen, beside the engine's record."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from expectrail.contracts import load_strict
from expectrail.jit.probes import jit_library
from expectrail.repro import bench, screen
from expectrail.repro.__main__ import main
from harness.unity import png_pixels
from tests.test_discovery import PROFILE
from tests.test_repro_bench import PUBLIC, REPO, STUB, Game, Refusals
from tests.test_unity_png_pixels import _chunk, write_png

W, H, FRAMES = 12, 6, 5
BACK = (10, 20, 30)


def picture(marks: dict[tuple[int, int], tuple[int, int, int]] | None = None, channels: int = 3, alpha: int = 255) -> bytes:
    out = bytearray()
    for y in range(H):
        for x in range(W):
            out += bytes((marks or {}).get((x, y), BACK)) + (bytes([alpha]) if channels == 4 else b"")
    return bytes(out)


class Drawn(Game):
    """tests.test_repro_bench.Game, which also draws: FRAMES small frames a replay. The picture shows a
    counter that moves one pixel a frame and nothing of the player, so a defect that only moves the
    player changes the record and no frame. More patches, recognised by file name:

    - sprite-flip: two pixels are another colour on every frame (the record is untouched).
    - late-pixel: one pixel differs on the last frame only.
    - camera-shift (from Game): the record's view moves, and here the counter is drawn one row lower.
    - re-encoded: every frame is the same picture in different bytes.
    - short: one frame fewer.   - bad-frame: the third frame is not a picture.
    ``flicker`` makes frame 1 of one probe differ on the first clean replay only."""

    def __init__(self, jitter=None, flicker=None):
        super().__init__(jitter)
        self.flicker = flicker

    def __call__(self, route_path, run_dir, patches=()):
        stems = {Path(p).stem for p in patches}
        own = ("sprite-flip", "late-pixel", "re-encoded", "short", "bad-frame")
        super().__call__(route_path, run_dir, patches=[p for p in patches if Path(p).stem not in own])
        name = json.loads(Path(route_path).read_text())["name"]
        frames = Path(run_dir) / "frames"
        frames.mkdir(parents=True, exist_ok=True)
        for i in range(FRAMES - (1 if "short" in stems else 0)):
            marks = {(i, 1 if "camera-shift" in stems else 0): (200, 200, 200)}
            if "sprite-flip" in stems:
                marks.update({(3, 3): (0, 255, 0), (8, 4): (0, 255, 0)})
            if "late-pixel" in stems and i == FRAMES - 1:
                marks[(11, 5)] = (10, 20, 31)
            if not stems and name == self.flicker and i == 1 and self.clean_calls[name] == 1:
                marks[(6, 2)] = (1, 2, 3)
            path = frames / f"f{i:08d}.png"
            write_png(path, W, H, picture(marks))
            if "re-encoded" in stems:
                rows = b"".join(b"\x00" + picture(marks)[y * W * 3:(y + 1) * W * 3] for y in range(H))
                path.write_bytes(b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", (W).to_bytes(4, "big") + (H).to_bytes(4, "big")
                                                                 + bytes([8, 2, 0, 0, 0]))
                                 + _chunk(b"IDAT", zlib.compress(rows, 0)) + _chunk(b"IEND", b""))
            if "bad-frame" in stems and i == 2:
                path.write_bytes(b"not a picture")
        (Path(run_dir) / "frames" / "f.wav").write_bytes(b"sound")   # Movie Maker writes one; it is not a frame


class TwoFrames(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="repro-screen-frames-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def png(self, name, marks=None, channels=3, alpha=255, width=W, height=H):
        path = self.tmp / name
        write_png(path, width, height, picture(marks, channels, alpha) if (width, height) == (W, H)
                  else bytes(width * height * channels), channels)
        return path

    def both_decoders(self):
        """Pillow when it is installed, and the standard-library decoder always: CI's test job has no Pillow."""
        yield "as installed", contextlib.nullcontext()
        yield "standard library", mock.patch.object(png_pixels, "_decode", png_pixels.read)

    def test_the_same_picture_has_no_difference(self):
        for name, decoder in self.both_decoders():
            with self.subTest(decoder=name), decoder:
                self.assertEqual(screen.frame_difference(self.png("a.png"), self.png("b.png")),
                                 {"width": W, "height": H, "pixels": 0, "box": None})

    def test_pixels_are_counted_and_boxed(self):
        marks = {(2, 1): (10, 20, 31), (9, 4): (255, 0, 0), (9, 3): (0, 20, 30)}
        for name, decoder in self.both_decoders():
            with self.subTest(decoder=name), decoder:
                self.assertEqual(screen.frame_difference(self.png("a.png"), self.png("b.png", marks)),
                                 {"width": W, "height": H, "pixels": 3, "box": [2, 1, 10, 5]})

    def test_one_pixel_in_each_corner(self):
        for corner, box in (((0, 0), [0, 0, 1, 1]), ((W - 1, 0), [W - 1, 0, W, 1]), ((0, H - 1), [0, H - 1, 1, H]),
                            ((W - 1, H - 1), [W - 1, H - 1, W, H])):
            for name, decoder in self.both_decoders():
                with self.subTest(corner=corner, decoder=name), decoder:
                    for channel in range(3):   # a difference of one, in each of red, green and blue
                        colour = list(BACK)
                        colour[channel] += 1
                        got = screen.frame_difference(self.png("a.png"), self.png("b.png", {corner: tuple(colour)}))
                        self.assertEqual((got["pixels"], got["box"]), (1, box))

    def test_every_pixel_different(self):
        marks = {(x, y): (0, 0, 0) for x in range(W) for y in range(H)}
        got = screen.frame_difference(self.png("a.png"), self.png("b.png", marks))
        self.assertEqual((got["pixels"], got["box"]), (W * H, [0, 0, W, H]))

    def test_alpha_is_not_compared_and_rgb_is_compared_with_rgba(self):
        with mock.patch.object(png_pixels, "_decode", png_pixels.read):   # Pillow would drop the alpha itself
            a = self.png("a.png")
            self.assertEqual(screen.frame_difference(a, self.png("b.png", channels=4, alpha=7))["pixels"], 0)
            got = screen.frame_difference(self.png("c.png", channels=4), self.png("d.png", {(5, 5): (0, 0, 0)}, channels=4, alpha=9))
            self.assertEqual((got["pixels"], got["box"]), (1, [5, 5, 6, 6]))

    def test_two_sizes_differ_everywhere(self):
        got = screen.frame_difference(self.png("a.png"), self.png("b.png", width=4, height=4))
        self.assertEqual((got["pixels"], got["box"]), (W * H, [0, 0, W, H]))

    def test_a_file_that_is_not_a_picture_is_refused(self):
        bad = self.tmp / "bad.png"
        for content in (b"not a picture", b"", b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", bytes(13)) + _chunk(b"IDAT", b"xx")):
            bad.write_bytes(content)
            for name, decoder in self.both_decoders():
                with self.subTest(content=content[:12], decoder=name), decoder:
                    with self.assertRaisesRegex(screen.ScreenError, "cannot be read"):
                        screen.frame_difference(self.png("a.png"), bad)
        with self.assertRaisesRegex(screen.ScreenError, "cannot be read"):
            screen.frame_difference(self.png("a.png"), self.tmp / "missing.png")

    def test_the_sample_keeps_the_first_and_the_last_and_never_more_than_the_limit(self):
        self.assertEqual(screen._sample([4, 9]), [4, 9])
        self.assertEqual(screen._sample(list(range(8))), list(range(8)))
        got = screen._sample(list(range(10, 180)))
        self.assertEqual((len(got), got[0], got[-1]), (screen.MAX_EXAMINED, 10, 179))
        self.assertEqual(got, sorted(set(got)))
        self.assertEqual(screen._sample(list(range(9))), [0, 1, 2, 3, 5, 6, 7, 8])


class Measure(unittest.TestCase):
    NAMES = ["air-jump", "sprite-flip", "camera-shift", "no-change", "late-pixel", "re-encoded", "short", "bad-frame",
             "crash", "script-error"]

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
        self.probes = [p for p in jit_library(self.profile["actions"]) if p["id"] in ("jump-w0-x8", "hold-right")]

    def measure(self, game=None, **kw):
        return screen.measure(self.doc, self.profile, self.probes, self.tmp / "out", runner=game or Drawn(),
                              root=self.tmp, bench_path=self.bench_path, **kw)

    def rows(self, record):
        return {r["id"]: r for r in record["defects"]}

    def test_each_defect_is_sorted_by_what_it_changes_in_the_record_and_on_the_screen(self):
        record = self.measure()
        rows = self.rows(record)
        self.assertEqual({k: v["sees"] for k, v in rows.items()},
                         {"air-jump": "record-only", "sprite-flip": "screen-only", "camera-shift": "record-and-screen",
                          "no-change": "neither", "late-pixel": "screen-only", "re-encoded": "neither",
                          "short": "error", "bad-frame": "error", "crash": "error", "script-error": "error"})
        self.assertEqual(record["totals"], {"defects": 10, "record-and-screen": 1, "screen-only": 2, "record-only": 1,
                                            "neither": 2, "error": 4})
        self.assertEqual(record["frame"], {"width": W, "height": H})
        self.assertEqual((record["unstable"], record["engineRetries"], record["renderer"]), ([], 0, None))
        self.assertEqual(screen.load(self.tmp / "out" / screen.NAME), record)

    def test_a_screen_only_defect_names_the_probe_the_frames_the_size_and_the_place(self):
        flip = self.rows(self.measure())["sprite-flip"]
        self.assertEqual((flip["recordFields"], flip["probesRecordChanged"], flip["probesScreenChanged"]), ([], 0, 2))
        self.assertEqual(flip["screen"], {"probe": "hold-right", "frames": FRAMES, "of": FRAMES, "firstFrame": 0,
                                          "examined": FRAMES, "pixels": 2, "atFrame": 0, "box": [3, 3, 9, 5]})

    def test_one_pixel_one_shade_off_on_the_last_frame_counts_and_says_how_small_it_is(self):
        late = self.rows(self.measure())["late-pixel"]["screen"]
        self.assertEqual(late, {"probe": "hold-right", "frames": 1, "of": FRAMES, "firstFrame": FRAMES - 1,
                                "examined": 1, "pixels": 1, "atFrame": FRAMES - 1, "box": [11, 5, 12, 6]})

    def test_the_record_is_compared_in_the_same_replays(self):
        rows = self.rows(self.measure())
        self.assertEqual(rows["camera-shift"]["recordFields"], ["view"])
        self.assertEqual((rows["camera-shift"]["probesRecordChanged"], rows["camera-shift"]["probesScreenChanged"]), (2, 2))
        self.assertEqual(rows["camera-shift"]["screen"]["box"], [0, 0, FRAMES, 2])
        self.assertEqual(rows["air-jump"]["probesRecordChanged"], 1)       # only the probe that jumps
        self.assertIn("player", rows["air-jump"]["recordFields"])
        self.assertIsNone(rows["air-jump"]["screen"])

    def test_the_same_picture_in_other_bytes_is_not_a_difference(self):
        row = self.rows(self.measure(only=["re-encoded"]))["re-encoded"]
        self.assertEqual((row["sees"], row["screen"], row["probesScreenChanged"]), ("neither", None, 0))

    def test_more_differing_files_than_are_examined_with_no_picture_differing_cannot_be_told(self):
        with mock.patch.object(screen, "MAX_EXAMINED", 2):
            row = self.rows(self.measure(only=["re-encoded"]))["re-encoded"]
        self.assertEqual(row["sees"], "error")
        self.assertIn("cannot be told", row["error"])

    def test_what_cannot_be_compared_is_an_error_row_with_the_reason_never_a_guess(self):
        rows = self.rows(self.measure())
        self.assertIn(f"has {FRAMES - 1} frames and the clean game's has {FRAMES}", rows["short"]["error"])
        self.assertIn("a frame cannot be read", rows["bad-frame"]["error"])
        self.assertIn("could not be replayed in 3 attempts", rows["crash"]["error"])
        self.assertIn("script error", rows["script-error"]["error"])
        for name in ("short", "bad-frame", "crash", "script-error"):
            self.assertEqual((rows[name]["screen"], rows[name]["recordFields"]), (None, []), name)

    def test_a_frame_that_differs_between_two_clean_replays_counts_for_no_defect(self):
        record = self.measure(Drawn(flicker="hold-right"))
        self.assertEqual(record["unstable"], [{"probe": "hold-right", "frames": 1, "fields": []}])
        flip = self.rows(record)["sprite-flip"]["screen"]
        self.assertEqual((flip["probe"], flip["frames"]), ("jump-w0-x8", FRAMES))    # frame 1 of hold-right is left out
        self.assertEqual(self.rows(record)["no-change"]["sees"], "neither")
        self.assertIn("Unstable between two replays of the clean game", screen.render(record))

    def test_a_record_field_that_differs_between_two_clean_replays_counts_for_no_defect(self):
        record = self.measure(Drawn(jitter="hold-right"), only=["camera-shift", "no-change"])
        self.assertEqual(record["unstable"], [{"probe": "hold-right", "frames": 0, "fields": ["view"]}])
        self.assertEqual(self.rows(record)["camera-shift"]["probesRecordChanged"], 1)
        self.assertEqual(self.rows(record)["no-change"]["sees"], "neither")

    def test_clean_replays_of_different_lengths_give_no_record(self):
        class Shrinks(Drawn):
            def __call__(self, route_path, run_dir, patches=()):
                super().__call__(route_path, run_dir, patches=patches)
                if not patches and "hold-right" in str(route_path) and self.clean_calls["hold-right"] == 2:
                    (Path(run_dir) / "frames" / "f00000004.png").unlink()

        with self.assertRaisesRegex(screen.ScreenError, "not repeatable"):
            self.measure(Shrinks())
        self.assertFalse((self.tmp / "out" / screen.NAME).exists())

    def test_a_clean_game_that_cannot_be_replayed_or_writes_no_frames_gives_no_record(self):
        def broken(route_path, run_dir, patches=()):
            raise RuntimeError("no engine")
        with self.assertRaisesRegex(screen.ScreenError, "the clean game could not be replayed"):
            self.measure(broken)
        with self.assertRaisesRegex(screen.ScreenError, "wrote no frames"):
            self.measure(Game())            # the record alone, as the visibility measurement replays it
        self.assertFalse((self.tmp / "out" / screen.NAME).exists())

    def test_an_engine_that_fails_once_is_replayed_again_and_the_retry_is_counted(self):
        class CrashesOnce(Drawn):
            failed = False

            def __call__(self, route_path, run_dir, patches=()):
                if not patches and "hold-right" in str(route_path) and not self.failed:
                    self.failed = True
                    raise SystemExit("godot failed (-11); see godot.log")
                return super().__call__(route_path, run_dir, patches=patches)

        record = self.measure(CrashesOnce(), only=["no-change", "sprite-flip"])
        self.assertEqual(record["engineRetries"], 1)
        self.assertEqual([r["sees"] for r in record["defects"]], ["screen-only", "neither"])
        self.assertIn("Replays made again after the engine failed: 1.", screen.render(record))

    def test_the_same_measurement_twice_gives_the_same_record_and_leaves_no_frames(self):
        first = self.measure()
        self.assertFalse((self.tmp / "out" / "work").exists())
        self.assertEqual(first, self.measure())
        self.measure(only=["no-change"], keep_frames=True)
        self.assertTrue(list((self.tmp / "out" / "work" / "clean-a").rglob("f*.png")))

    def test_a_record_that_disagrees_with_itself_is_refused(self):
        record = self.measure()
        at = {r["id"]: i for i, r in enumerate(record["defects"])}
        flip, none, crash, jump = at["sprite-flip"], at["no-change"], at["crash"], at["air-jump"]
        changes = {
            "totals": lambda r: r["totals"].update(neither=9),
            "screen-only raised to both": lambda r: r["defects"][flip].update(sees="record-and-screen"),
            "screen-only with no screen difference": lambda r: r["defects"][flip].update(screen=None),
            "neither called screen-only": lambda r: r["defects"][none].update(sees="screen-only"),
            "record-only called neither": lambda r: r["defects"][jump].update(sees="neither"),
            "error with no reason": lambda r: r["defects"][crash].pop("error"),
            "reason on a measured row": lambda r: r["defects"][flip].update(error="x"),
            "no probe changed on the screen": lambda r: r["defects"][flip].update(probesScreenChanged=0),
            "more probes than there are": lambda r: r["defects"][flip].update(probesScreenChanged=3),
            "record probes with no field": lambda r: r["defects"][none].update(probesRecordChanged=1),
            "an unknown probe": lambda r: r["defects"][flip]["screen"].update(probe="other"),
            "more frames than captured": lambda r: r["defects"][flip]["screen"].update(frames=FRAMES + 1),
            "first frame past the end": lambda r: r["defects"][flip]["screen"].update(firstFrame=FRAMES),
            "largest before the first": lambda r: r["defects"][flip]["screen"].update(firstFrame=2),
            "more examined than differ": lambda r: r["defects"][flip]["screen"].update(frames=2),
            "more examined than the limit": lambda r: r.update(maxFramesExamined=2),
            "a box outside the frame": lambda r: r["defects"][flip]["screen"].update(box=[3, 3, W + 1, 5]),
            "an empty box": lambda r: r["defects"][flip]["screen"].update(box=[3, 3, 3, 5]),
            "more pixels than the box holds": lambda r: r["defects"][flip]["screen"].update(pixels=13),
            "no pixels": lambda r: r["defects"][flip]["screen"].update(pixels=0),
            "a defect twice": lambda r: r["defects"].append(copy.deepcopy(r["defects"][0])),
            "an extra field": lambda r: r.update(reproductionRate=1.0),
            "a rate on a row": lambda r: r["defects"][flip].update(reproduced=True),
            "one clean replay": lambda r: r["replaysPerBuild"].update(clean=1),
        }
        for name, change in changes.items():
            doc = copy.deepcopy(record)
            change(doc)
            self.assertTrue(screen.problems(doc), name)
            path = self.tmp / "tampered.json"
            path.write_text(json.dumps(doc))
            with self.assertRaises(screen.ScreenError, msg=name):
                screen.load(path)

    def test_a_record_with_a_key_twice_or_too_large_is_refused(self):
        self.measure(only=["no-change"])
        path = self.tmp / "out" / screen.NAME
        text = path.read_text()
        path.write_text(text.replace('"engineRetries": 0,', '"engineRetries": 0, "engineRetries": 0,', 1))
        with self.assertRaisesRegex(screen.ScreenError, "unreadable"):
            screen.load(path)
        path.write_text(text + " " * screen.MAX_BYTES)
        with self.assertRaisesRegex(screen.ScreenError, "over"):
            screen.load(path)

    def test_stale_says_when_the_record_no_longer_describes_the_bench(self):
        record = self.measure()
        self.assertEqual(screen.stale(record, self.doc, self.tmp, self.bench_path), [])
        (self.tmp / "bench" / "no-change.patch").write_text(STUB.replace("+b", "+changed"))
        self.assertEqual(screen.stale(record, self.doc, self.tmp, self.bench_path),
                         ["no-change: the patch changed after it was measured"])

    def test_render_has_a_row_per_defect_and_the_totals_and_claims_no_rate(self):
        text = screen.render(self.measure(), self.doc)
        for name in self.NAMES:
            self.assertIn(f"| `{name}` |", text)
        self.assertIn("Only the screen differs: 2.", text)
        self.assertIn("Could not be measured: 4.", text)
        self.assertIn("| `sprite-flip` | movement-input | both | screen-only | none | `hold-right` (of 2) | "
                      f"{FRAMES} of {FRAMES}, from frame 0 | 2 (frame 0) | 3, 3, 9, 5 |", text)
        self.assertIn("| `air-jump` | movement-input | both | record-only |", text)
        self.assertNotIn("reproduc", text.lower())

    def test_the_commands_measure_and_render_on_the_committed_bench(self):
        # The real bench and all of its probes, with the game stood in for: its patches change nothing here.
        out, err, where = io.StringIO(), io.StringIO(), self.tmp / "cli"
        with mock.patch.object(screen, "_default_runner", lambda: Drawn()), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["screen", "--out", str(where), "--only", "enemy-walks-backwards"])
        self.assertEqual((code, json.loads(out.getvalue())), (0, {"defects": 1, "record-and-screen": 0, "screen-only": 0,
                                                                  "record-only": 0, "neither": 1, "error": 0}), err.getvalue())
        self.assertEqual(len(screen.load(where / screen.NAME)["probes"]), len(jit_library(self.profile["actions"])))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(main(["screen-render", str(where / screen.NAME)]), 0)
        self.assertIn("| `enemy-walks-backwards` | visibility-rendering | screen | neither |", out.getvalue())
        self.assertIn("stale: air-jump: not measured", err.getvalue())
        (where / screen.NAME).write_text("{}")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            self.assertEqual(main(["screen-render", str(where / screen.NAME)]), 1)
        self.assertIn("repro: repro-screen:", err.getvalue())


class HeldBack(unittest.TestCase):
    def test_nothing_generated_checks_run_on_reads_the_screen_measurement(self):
        # The issue asks for the baseline before anything changes: a live run must be the same with
        # or without this module, as with reach.
        for path in sorted((REPO / "expectrail" / "jit").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for word in ("repro.screen", "repro import", "repro-screen", "screen.json"):
                self.assertNotIn(word, text, f"{path.name}: {word}")
        for name in ("jit.yml", "jit-blind.yml"):
            text = (REPO / ".github" / "workflows" / name).read_text(encoding="utf-8")
            self.assertNotIn("repro screen", text, name)

    def test_it_asks_no_observer_and_no_model(self):
        text = (REPO / "expectrail" / "repro" / "screen.py").read_text(encoding="utf-8")
        for word in ("sam_observations", "glimmer", "agents.", "spec_writer", "transport"):
            self.assertNotIn(word, text, word)


class TheRecordedMeasurement(unittest.TestCase):
    """bench/jit/public/screen.json is a recorded run; these hold it to the bench and to the page."""

    def setUp(self):
        self.doc = bench.load()
        self.record = screen.load()

    def test_it_covers_exactly_the_bench_as_it_is_now_with_no_error_row(self):
        self.assertEqual(screen.stale(self.record, self.doc), [])
        self.assertEqual(self.record["totals"]["error"], 0)

    def test_it_used_every_probe_generated_checks_may_use(self):
        profile = load_strict(PROFILE, "mechanics-profile")
        self.assertEqual(self.record["probes"], [p["id"] for p in jit_library(profile["actions"])])

    def test_the_page_shows_the_record_as_rendered_and_nothing_else(self):
        page = (PUBLIC / "README.md").read_text(encoding="utf-8")
        start, end = "<!-- screen:start -->\n", "<!-- screen:end -->\n"
        self.assertIn(start, page)
        shown = page.split(start, 1)[1].split(end, 1)[0]
        self.assertEqual(shown, screen.render(self.record, self.doc))

    def test_the_page_says_what_this_is_not(self):
        page = (PUBLIC / "README.md").read_text(encoding="utf-8")
        section = page.split("## What each defect changes on the screen", 1)[1].split("\n## ", 1)[0]
        self.assertIn("No visual observer was asked anything", section)
        self.assertIn("not a reproduction rate", section)


if __name__ == "__main__":
    unittest.main()
