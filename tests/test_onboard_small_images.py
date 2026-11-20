"""Bounded review previews without an image decoder.

Guard: test change intended (#332)
Reason: a new regression for config-lane's SVG art and 360x240 frames;
no existing assertion or test is changed.
"""
import binascii
import builtins
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from expectrail import onboard_page, onboard_review

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><rect width="24" height="24" fill="#e2a33b"/></svg>'


def png(width, height):
    def chunk(name, data):
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', binascii.crc32(name+data) & 0xffffffff)
    row = b'\x00' + b'\xe2\xa3\x3b' * width
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(row * height)) + chunk(b'IEND', b''))


def no_pillow(name, *args, **kwargs):
    if name == 'PIL' or name.startswith('PIL.'):
        raise ImportError('Pillow deliberately absent')
    return ORIGINAL_IMPORT(name, *args, **kwargs)


ORIGINAL_IMPORT = builtins.__import__


class SmallImageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_config_lane_frame_is_kept_at_its_real_size_without_pillow(self):
        data = png(360, 240); path = self.root/'frame.png'; path.write_bytes(data)
        with mock.patch('builtins.__import__', side_effect=no_pillow):
            small = onboard_review.thumbnail(path)
        self.assertIsNotNone(small, 'a tiny valid frame must not disappear because its canvas exceeds the thumbnail side')
        self.assertEqual(small, (data, (360, 240)))

    def test_a_crop_is_never_replaced_with_an_uncropped_image_without_pillow(self):
        path = self.root/'frame.png'; path.write_bytes(png(360, 240))
        with mock.patch('builtins.__import__', side_effect=no_pillow):
            self.assertIsNone(onboard_review.thumbnail(path, crop=[168,108,192,132]))

    def test_large_native_canvas_remains_unavailable_without_a_decoder(self):
        path = self.root/'wide.png'; path.write_bytes(png(1025, 10))
        with mock.patch('builtins.__import__', side_effect=no_pillow):
            self.assertIsNone(onboard_review.thumbnail(path))

    def test_config_lane_svg_is_the_bound_sprite_not_a_crop(self):
        path = self.root/'square.svg'; path.write_bytes(SVG)
        item = onboard_review.native_sprite(self.root, path)
        self.assertIsNotNone(item, 'the bound 24x24 static SVG needs a safe native preview')
        self.assertEqual(item['mime'], 'image/svg+xml')
        self.assertEqual(item['size'], [24,24])
        self.assertEqual(onboard_review.native_sprite_bytes(self.root, item), SVG)
        html = onboard_page.figure(self.root, item, 'Bound square')
        self.assertIn('data:image/svg+xml;base64,', html)
        self.assertNotIn('<script', html)
        (self.root/item['path']).write_bytes(SVG.replace(b'#e2a33b', b'#112233'))
        self.assertIsNone(onboard_review.native_sprite_bytes(self.root, item))

    def test_svg_cannot_introduce_code_external_content_or_unbounded_geometry(self):
        cases = [
            SVG.replace(b'<rect', b'<script/> <rect'),
            SVG.replace(b'<rect', b'<image href="https://example.invalid/a"/> <rect'),
            SVG.replace(b'<rect', b'<foreignObject/> <rect'),
            SVG.replace(b'<rect', b'<use href="#shape"/> <rect'),
            SVG.replace(b'<rect', b'<rect onload="alert(1)"'),
            SVG.replace(b'#e2a33b', b'url(https://example.invalid/a)'),
            SVG.replace(b'#e2a33b', b'url(&#104;ttps://example.invalid/a)'),
            SVG.replace(b'#e2a33b', br'u\72l(https://example.invalid/a)'),
            SVG.replace(b'width="24"', b'width="999999999"', 1),
            b'<!DOCTYPE svg [<!ENTITY a "x">]>' + SVG,
            SVG.replace(b'<rect', b'<?test do-not-run?><rect'),
        ]
        for i, data in enumerate(cases):
            with self.subTest(case=i):
                path = self.root/'bad.svg'; path.write_bytes(data)
                self.assertIsNone(onboard_review.native_sprite(self.root, path))
