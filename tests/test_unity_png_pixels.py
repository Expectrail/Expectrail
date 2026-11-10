"""harness.unity.png_pixels: the harness's frames read without an image library, and how far two differ."""
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from harness.unity import png_pixels


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def _filtered(rows: list[bytes], channels: int) -> bytes:
    """Each row with a different PNG filter (0 to 4, in turn), as an encoder may choose."""
    out, prev = bytearray(), bytes(len(rows[0]))
    for y, row in enumerate(rows):
        kind = y % 5
        line = bytearray()
        for x, v in enumerate(row):
            a = row[x - channels] if x >= channels else 0
            b = prev[x]
            c = prev[x - channels] if x >= channels else 0
            if kind == 0:
                pred = 0
            elif kind == 1:
                pred = a
            elif kind == 2:
                pred = b
            elif kind == 3:
                pred = (a + b) >> 1
            else:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else b if pb <= pc else c
            line.append((v - pred) & 0xFF)
        out += bytes([kind]) + line
        prev = row
    return bytes(out)


def write_png(path: Path, width: int, height: int, pixels: bytes, channels: int = 3) -> None:
    rows = [pixels[y * width * channels:(y + 1) * width * channels] for y in range(height)]
    color = {3: 2, 4: 6}[channels]
    data = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(_filtered(rows, channels))) + _chunk(b"IEND", b""))
    path.write_bytes(data)


def _image(width: int, height: int, channels: int = 3) -> bytes:
    return bytes((x * 7 + y * 13 + c * 29) % 256 for y in range(height) for x in range(width) for c in range(channels))


class PngPixels(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_filter_reads_back_exactly(self):
        for channels in (3, 4):
            with self.subTest(channels=channels):
                pixels = _image(9, 10, channels)
                write_png(self.root / "a.png", 9, 10, pixels, channels)
                self.assertEqual(png_pixels.read(self.root / "a.png"), (9, 10, channels, pixels))

    def test_difference_counts_pixels_and_the_largest_channel_gap(self):
        pixels = bytearray(_image(6, 5))
        write_png(self.root / "a.png", 6, 5, bytes(pixels))
        pixels[0] = (pixels[0] + 3) % 256
        pixels[3 * 7 + 2] = (pixels[3 * 7 + 2] + 1) % 256
        write_png(self.root / "b.png", 6, 5, bytes(pixels))
        d = png_pixels.difference(self.root / "a.png", self.root / "b.png")
        self.assertEqual((d["pixels"], d["differ"], d["largest"]), (30, 2, 3))
        self.assertEqual(png_pixels.difference(self.root / "a.png", self.root / "a.png")["differ"], 0)

    def test_not_a_png_is_refused(self):
        (self.root / "x.png").write_bytes(b"nope")
        with self.assertRaises(ValueError):
            png_pixels.read(self.root / "x.png")


if __name__ == "__main__":
    unittest.main()
