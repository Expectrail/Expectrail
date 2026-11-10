"""harness.unity.trace_diff: where two replays of one Unity route differ, field by field."""
import json
import tempfile
import unittest
from pathlib import Path

from harness.unity import trace_diff


def _run(root: Path, name: str, rows: list[dict], frames: list[str], settle: dict, machine: str | None = None,
         surfaces=None, fade_starts=()) -> Path:
    run = root / name / "run-00"
    run.mkdir(parents=True)
    trace = {"format": "expectrail.trace/v0", "ticks": len(rows), "levelSurfaces": surfaces or [[[0, 0], [10, 0]]],
             "rows": rows}
    (run / "trace.json").write_text(json.dumps(trace))
    hazards = [{"kind": "real-time-fade", "detail": "x", "tick": None}] + [
        {"kind": "real-time-fade-during-route", "detail": "x", "tick": t} for t in fade_starts]
    (run / "replay.json").write_text(json.dumps({"frameSha256": frames, "settle": settle, "trace": {"sha256": name},
                                                 "hazards": hazards}))
    if machine:
        (root / name / "machine.txt").write_text(machine + "\n")
    return run


def _rows(n: int, nudge_from: int | None = None, by: float = 0.0) -> list[dict]:
    return [{"tick": i, "frame": i, "player": [10.0 + i + (by if nudge_from is not None and i >= nudge_from else 0.0), 50.0],
             "ground": 60.0, "objects": [{"id": "Player", "role": "player", "box": [0, 0, 4, 4], "visible": True}]}
            for i in range(n)]


class TraceDiff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_different_settle_alone_leaves_the_route_identical(self):
        a = _run(self.root, "a", _rows(5), ["f"] * 5, {"ticks": 77, "frozenFrames": 23}, "copy a: CPU x")
        b = _run(self.root, "b", _rows(5), ["f"] * 5, {"ticks": 77, "frozenFrames": 37}, "copy b: CPU y")
        d = trace_diff.diff(a, b)
        self.assertTrue(d["routeIdentical"])
        self.assertEqual(d["machines"], ["copy a: CPU x", "copy b: CPU y"])
        self.assertIn("route identical", trace_diff.summary(d))
        self.assertIn("23 held vs 77 ticks/37 held", trace_diff.summary(d))
        self.assertEqual(trace_diff.main([str(a), str(b)]), 0)

    def test_a_drifting_field_is_named_with_its_first_tick_count_and_gap(self):
        a = _run(self.root, "a", _rows(6), ["f"] * 6, {"ticks": 1, "frozenFrames": 0})
        b = _run(self.root, "b", _rows(6, nudge_from=3, by=0.25), ["f", "f", "f", "g", "g", "g"],
                 {"ticks": 1, "frozenFrames": 0})
        d = trace_diff.diff(a, b)
        self.assertFalse(d["routeIdentical"])
        player = d["rows"]["fields"]["player"]
        self.assertEqual((player["firstTick"], player["ticksDiffer"]), (3, 3))
        self.assertAlmostEqual(player["largestGap"], 0.25)
        self.assertEqual(list(d["rows"]["fields"]), ["player"])
        self.assertEqual((d["frames"]["differ"], d["frames"]["first"]), (3, 3))
        self.assertEqual(trace_diff.main([str(a), str(b)]), 1)

    def test_objects_are_compared_by_id_and_level_sections_are_named(self):
        rows_b = _rows(2)
        rows_b[1]["objects"][0]["box"] = [0, 0, 5, 4]
        a = _run(self.root, "a", _rows(2), ["f", "f"], {"ticks": 0, "frozenFrames": 0})
        b = _run(self.root, "b", rows_b, ["f", "f"], {"ticks": 0, "frozenFrames": 0}, surfaces=[[[0, 1], [10, 1]]])
        d = trace_diff.diff(a, b)
        self.assertEqual(d["rows"]["fields"]["objects"]["first"], {"tick": 1, "ids": ["Player"]})
        self.assertEqual(d["sectionsDiffer"], ["levelSurfaces"])
        out = self.root / "diff.json"
        self.assertEqual(trace_diff.main([str(a), str(b), "--json", str(out)]), 1)
        self.assertFalse(json.loads(out.read_text())["routeIdentical"])

    def test_a_different_level_alone_fails(self):
        a = _run(self.root, "a", _rows(2), ["f", "f"], {"ticks": 0, "frozenFrames": 0})
        b = _run(self.root, "b", _rows(2), ["f", "f"], {"ticks": 0, "frozenFrames": 0}, surfaces=[[[0, 1], [10, 1]]])
        d = trace_diff.diff(a, b)
        self.assertTrue(d["routeIdentical"])
        self.assertEqual(trace_diff.main([str(a), str(b)]), 1)


    def test_a_frame_on_a_fades_first_tick_may_differ_when_both_saw_the_same_fades(self):
        a = _run(self.root, "a", _rows(4), ["f", "f", "x", "f"], {"ticks": 0, "frozenFrames": 0}, fade_starts=[2])
        b = _run(self.root, "b", _rows(4), ["f", "f", "y", "f"], {"ticks": 0, "frozenFrames": 0}, fade_starts=[2])
        d = trace_diff.diff(a, b)
        self.assertTrue(d["routeIdentical"])
        self.assertEqual((d["frames"]["atFadeStarts"], d["frames"]["unexplained"]), (1, 0))
        self.assertEqual(trace_diff.main([str(a), str(b)]), 0)

    def test_any_other_frame_or_different_fade_starts_fail(self):
        a = _run(self.root, "a", _rows(4), ["f", "f", "x", "q"], {"ticks": 0, "frozenFrames": 0}, fade_starts=[2])
        b = _run(self.root, "b", _rows(4), ["f", "f", "y", "f"], {"ticks": 0, "frozenFrames": 0}, fade_starts=[2])
        self.assertEqual(trace_diff.diff(a, b)["frames"]["unexplained"], 1)
        self.assertEqual(trace_diff.main([str(a), str(b)]), 1)
        c = _run(self.root, "c", _rows(4), ["f", "f", "x", "f"], {"ticks": 0, "frozenFrames": 0}, fade_starts=[2])
        e = _run(self.root, "e", _rows(4), ["f", "f", "x", "f"], {"ticks": 0, "frozenFrames": 0}, fade_starts=[3])
        self.assertFalse(trace_diff.diff(c, e)["routeIdentical"])


    def test_differing_frames_are_measured_pixel_by_pixel(self):
        from tests.test_unity_png_pixels import _image, write_png
        a = _run(self.root, "a", _rows(2), ["f", "x"], {"ticks": 0, "frozenFrames": 0})
        b = _run(self.root, "b", _rows(2), ["f", "y"], {"ticks": 0, "frozenFrames": 0})
        for run, nudge in ((a, 0), (b, 4)):
            (run / "frames").mkdir()
            pixels = bytearray(_image(4, 3))
            pixels[5] = (pixels[5] + nudge) % 256
            write_png(run / "frames" / "f00000001.png", 4, 3, bytes(pixels))
        d = trace_diff.diff(a, b)
        self.assertFalse(d["routeIdentical"])  # 4 of 255 is beyond the tolerance
        self.assertEqual(d["pixels"]["beyondTolerance"], [1])
        self.assertEqual(d["pixels"]["sampled"], [1])
        self.assertEqual((d["pixels"]["mostPixelsDiffering"], d["pixels"]["largestChannelGap"]), (1, 4))
        self.assertIn("by at most 4 of 255", trace_diff.summary(d))
        self.assertEqual(trace_diff.sample(list(range(100)), 4), [0, 33, 66, 99])


    def _frames(self, run, name, nudge, count, side=10):
        from tests.test_unity_png_pixels import _image, write_png
        (run / "frames").mkdir(exist_ok=True)
        pixels = bytearray(_image(side, side))
        for k in range(count):
            pixels[k * 3] = (pixels[k * 3] + nudge) % 256
        write_png(run / "frames" / name, side, side, bytes(pixels))

    def test_a_frame_within_tolerance_passes_when_the_trace_is_identical(self):
        a = _run(self.root, "a", _rows(2), ["f", "x"], {"ticks": 0, "frozenFrames": 0})
        b = _run(self.root, "b", _rows(2), ["f", "y"], {"ticks": 0, "frozenFrames": 0})
        # 1 of 400 pixels (0.25%) differs, by 2 of 255: within the tolerance.
        self._frames(a, "f00000001.png", 0, 1, side=20)
        self._frames(b, "f00000001.png", 2, 1, side=20)
        d = trace_diff.diff(a, b)
        self.assertEqual((d["pixels"]["mostPixelsDiffering"], d["pixels"]["largestChannelGap"]), (1, 2))
        self.assertTrue(d["routeIdentical"])
        self.assertEqual(d["frames"]["withinTolerance"], 1)

    def test_too_many_pixels_or_too_large_a_gap_fails(self):
        # 1 of 100 pixels (1%) is over the 0.5% share.
        a = _run(self.root, "a", _rows(2), ["f", "x"], {"ticks": 0, "frozenFrames": 0})
        b = _run(self.root, "b", _rows(2), ["f", "y"], {"ticks": 0, "frozenFrames": 0})
        self._frames(a, "f00000001.png", 0, 1)
        self._frames(b, "f00000001.png", 2, 1)
        self.assertFalse(trace_diff.diff(a, b)["routeIdentical"])

    def test_tolerance_needs_the_frame_measured_and_the_trace_identical(self):
        m = {"pixels": 1000, "differ": 5, "largest": 2}
        self.assertTrue(trace_diff.within_tolerance(m))
        self.assertFalse(trace_diff.within_tolerance({**m, "largest": 3}))
        self.assertFalse(trace_diff.within_tolerance({**m, "differ": 6}))
        # Frames that differ but cannot be measured (no frame folders) are never tolerated.
        a = _run(self.root, "a", _rows(2), ["f", "x"], {"ticks": 0, "frozenFrames": 0})
        b = _run(self.root, "b", _rows(2), ["f", "y"], {"ticks": 0, "frozenFrames": 0})
        self.assertFalse(trace_diff.diff(a, b)["routeIdentical"])
        # A trace difference fails even when every frame is within tolerance.
        c = _run(self.root, "c", _rows(2), ["f", "x"], {"ticks": 0, "frozenFrames": 0})
        e = _run(self.root, "e", _rows(2, nudge_from=1, by=0.5), ["f", "y"], {"ticks": 0, "frozenFrames": 0})
        self._frames(c, "f00000001.png", 0, 0)
        self._frames(e, "f00000001.png", 0, 0)
        self.assertFalse(trace_diff.diff(c, e)["routeIdentical"])

    def test_without_pillow_only_a_sample_is_measured_and_the_rest_fail(self):
        frames = list(range(30))
        a = _run(self.root, "a", _rows(30), ["f"] * 30, {"ticks": 0, "frozenFrames": 0})
        b = _run(self.root, "b", _rows(30), ["g"] * 30, {"ticks": 0, "frozenFrames": 0})
        for i in frames:
            self._frames(a, f"f{i:08d}.png", 0, 0)
            self._frames(b, f"f{i:08d}.png", 0, 0)
        part = trace_diff.measure_frames(a, b, frames, every=False)
        self.assertFalse(part["all"])
        self.assertEqual(len(part["sampled"]), trace_diff.SAMPLE_FRAMES)
        self.assertTrue(trace_diff.measure_frames(a, b, frames, every=True)["all"])


if __name__ == "__main__":
    unittest.main()
