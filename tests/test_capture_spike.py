"""The capture spike's analysis (#246, tools/capture_spike). No engine, display or second user here:
the spike's own runs are recorded in docs/capture-spike.md. The header test needs nothing; the pixel
tests need NumPy and Pillow, which the spike itself needs, and skip without them."""
from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from tools.capture_spike import spike

np = spike.np
needs_pixels = unittest.skipIf(spike.np is None or spike.Image is None, "the spike's pixel analysis needs NumPy and Pillow")


def xwd_bytes(pixels: list[list[tuple[int, int, int]]], ncolors: int = 3, name: bytes = b"Xvfb\0",
              pad: int = 8) -> bytes:
    """A 32-bit little-endian XWD file the way Xvfb -fbdir writes one, with rows padded."""
    height, width = len(pixels), len(pixels[0])
    bytes_per_line = width * 4 + pad
    header_size = 100 + len(name)
    fields = [header_size, 7, 2, 24, width, height, 0, 0, 32, 0, 32, 32, bytes_per_line, 4,
              0xFF0000, 0x00FF00, 0x0000FF, 8, 256, ncolors, width, height, 0, 0, 0]
    body = b"".join(
        b"".join(struct.pack("<I", (r << 16) | (g << 8) | b) for r, g, b in row) + b"\xAA" * pad for row in pixels)
    return struct.pack(">25I", *fields) + name + b"\0" * (12 * ncolors) + body


class LayoutTest(unittest.TestCase):
    def test_the_header_names_where_the_pixels_start_and_the_masks(self):
        data = xwd_bytes([[(1, 2, 3)] * 4] * 2, ncolors=256)
        lay = spike.xwd_layout(data[:100])
        self.assertEqual((lay["width"], lay["height"]), (4, 2))
        self.assertEqual(lay["offset"], 105 + 256 * 12)
        self.assertEqual(lay["masks"], (0xFF0000, 0x00FF00, 0x0000FF))
        self.assertTrue(lay["littleEndian"])

    def test_a_header_that_is_not_32_bits_a_pixel_is_refused(self):
        data = bytearray(xwd_bytes([[(0, 0, 0)]]))
        data[44:48] = struct.pack(">I", 16)
        with self.assertRaises(ValueError):
            spike.xwd_layout(bytes(data[:100]))

    def test_a_short_header_is_refused(self):
        with self.assertRaises(ValueError):
            spike.xwd_layout(b"\0" * 40)


@needs_pixels
class ReadScreenTest(unittest.TestCase):
    def test_the_crop_is_rgb_in_the_right_order_and_skips_row_padding(self):
        pixels = [[(10, 20, 30), (40, 50, 60), (70, 80, 90)],
                  [(1, 2, 3), (4, 5, 6), (7, 8, 9)]]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Xvfb_screen0"
            path.write_bytes(xwd_bytes(pixels))
            got = spike.read_xwd(path, 2, 2)
        self.assertEqual(got.tolist(), [[[10, 20, 30], [40, 50, 60]], [[1, 2, 3], [4, 5, 6]]])

    def test_a_crop_larger_than_the_screen_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Xvfb_screen0"
            path.write_bytes(xwd_bytes([[(0, 0, 0)] * 2] * 2))
            with self.assertRaises(ValueError):
                spike.read_xwd(path, 3, 2)


def frame(value: int, size: int = 4):
    return np.full((size, size, 3), value, dtype=np.uint8)


@needs_pixels
class TornTest(unittest.TestCase):
    def setUp(self):
        self.before, self.after = frame(10), frame(200)

    def test_part_of_one_frame_and_part_of_the_next_is_a_tear(self):
        grab = self.before.copy()
        grab[2:] = self.after[2:]
        grab[1, 3] = self.after[1, 3]  # the edge is ragged, not a clean line
        self.assertTrue(spike.torn_between(grab, self.before, self.after))

    def test_a_whole_frame_is_not_a_tear(self):
        self.assertFalse(spike.torn_between(self.before.copy(), self.before, self.after))
        self.assertFalse(spike.torn_between(self.after.copy(), self.before, self.after))

    def test_a_pixel_in_neither_frame_is_not_a_tear(self):
        grab = self.before.copy()
        grab[2:] = self.after[2:]
        grab[0, 0] = (99, 99, 99)
        self.assertFalse(spike.torn_between(grab, self.before, self.after))

    def test_two_equal_frames_cannot_tear(self):
        self.assertFalse(spike.torn_between(self.before.copy(), self.before, self.before.copy()))


@needs_pixels
class ClassifyTest(unittest.TestCase):
    def test_every_kind_of_grab(self):
        movie = [frame(10), frame(20), frame(30), frame(40)]
        torn = movie[0].copy()
        torn[:2] = movie[1][:2]
        images = [frame(0), movie[0], torn, movie[1], frame(77), movie[3], frame(0)]
        rows = spike.classify_samples(images, movie)
        self.assertEqual([r["kind"] for r in rows],
                         ["before", "frame", "torn", "frame", "unexplained", "frame", "after"])
        self.assertEqual(rows[4]["between"], [1, 3])
        summary = spike.sample_summary(rows)
        self.assertEqual(summary["unexplained"], 1)
        self.assertEqual(summary["unexplainedBetween"], [[1, 3]])
        self.assertEqual(summary["movieFramesSeen"], 3)

    def test_a_grab_between_frames_that_are_not_neighbours_is_never_excused_as_a_tear(self):
        # A grab of the true frame where the movie kept a forged one: the grabs on either side match
        # frames two apart, so no tear between neighbours can explain it.
        movie = [frame(10), frame(10), frame(30)]  # frame 1 was overwritten with frame 0
        true_frame_1 = frame(20)
        rows = spike.classify_samples([movie[0], true_frame_1, movie[2]], movie)
        self.assertEqual(rows[1]["kind"], "unexplained")

    def test_a_forged_movie_frame_shows_as_a_run_of_unexplained_grabs(self):
        movie = [frame(v) for v in (10, 20, 30, 40, 50)]
        forged = list(movie)
        forged[2] = movie[0].copy()
        images = [movie[0], movie[1], movie[2], movie[2], movie[3], movie[4]]
        rows = spike.classify_samples(images, forged)
        self.assertEqual([r["kind"] for r in rows], ["frame", "frame", "unexplained", "unexplained", "frame", "frame"])
        self.assertEqual(spike.sample_summary(rows)["unexplainedBetween"], [[1, 3]])

    def test_no_grab_matched_means_nothing_is_called_a_frame(self):
        rows = spike.classify_samples([frame(1), frame(2)], [frame(10)])
        self.assertEqual([r["kind"] for r in rows], ["before", "before"])


class StepSummaryTest(unittest.TestCase):
    def test_a_rewritten_movie_frame_shows_as_a_grab_that_differs_at_its_index(self):
        # Movie frame 1 was overwritten with frame 0's picture: grab 0 matches movie frames 0 and 1,
        # and grab 1 (the true frame 1) matches nothing the movie kept.
        rows = [{"heldMs": 20.0, "first": [0, 1], "settled": [0, 1], "firstEqualsSettled": True},
                {"heldMs": 22.0, "first": [], "settled": [], "firstEqualsSettled": True},
                {"heldMs": 24.0, "first": [2], "settled": [2], "firstEqualsSettled": True}]
        summary = spike._step_summary(rows, 3, 0.0)
        self.assertEqual(summary["settledDiffersFromMovieFrameSameIndex"], [1])
        self.assertEqual(summary["settledEqualsMovieFrameSameIndex"], 2)
        self.assertEqual(summary["offsetsSettled"], {0: 2, 1: 1})


if __name__ == "__main__":
    unittest.main()
