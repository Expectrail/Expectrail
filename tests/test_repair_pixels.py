"""The repair CLI fixture answers its visual questions from the captured PNG alone."""
import tempfile
import unittest
from pathlib import Path

from tests.repair_cli_fixture import RobotPixels
from tests.test_unity_png_pixels import write_png


class RepairPixelsTest(unittest.TestCase):
    def test_moving_or_hiding_the_paint_changes_both_visual_answers(self):
        client = RobotPixels()
        with tempfile.TemporaryDirectory() as tmp:
            frame = Path(tmp) / 'f00000000.png'
            regions = [(0, 0, 2, 1), (2, 0, 4, 1)]
            for x in (0, 3, None):
                with self.subTest(x=x):
                    pixels = bytearray(4 * 3)
                    if x is not None:
                        pixels[x * 3:x * 3 + 3] = bytes((59, 93, 201))
                    write_png(frame, 4, 1, pixels)
                    hit = {'box': [x, 0, x + 1, 1], 'score': 1.0} if x is not None else None
                    self.assertEqual(client.segment(frame, 'blue robot'), [hit] if hit else [])
                    self.assertEqual(client.segment_in(frame, regions),
                                     [hit if x == 0 else None, hit if x == 3 else None])
