"""Optimized fixture setup preserves bytes, replay inputs and per-test isolation."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zlib

from tests import geometry_fixture
from tests.test_jit_sam_observer import _png_bytes, png


class PngFixtureTest(unittest.TestCase):
    def test_cached_png_is_byte_identical_to_the_original_encoder(self):
        # Independent original encoding, including the compression level and CRCs.
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xFFFFFFFF)
        for size, seed in (((1600, 960), 0), ((1600, 960), 169), ((12, 6), 257)):
            with self.subTest(size=size, seed=seed):
                w, h = size
                row = b'\0' + bytes([seed % 256, (seed // 256) % 256, 7]) + b'\0' * (3 * w - 3)
                raw = row + (b'\0' + b'\0' * 3 * w) * (h - 1)
                expected = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                            + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))
                self.assertEqual(_png_bytes(size, seed), expected)

    def test_reusing_bytes_does_not_share_mutable_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp)/'a.png', Path(tmp)/'b.png'
            png(a, (12, 6), 10)
            png(b, (12, 6), 10)
            original = b.read_bytes()
            self.assertEqual(a.read_bytes(), original)
            a.write_bytes(b'corrupt')
            self.assertEqual(b.read_bytes(), original)
            png(a, (12, 6), 11)
            self.assertNotEqual(a.read_bytes(), b.read_bytes())


class GeometryFixtureTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.game = self.root/'game'
        self.game.mkdir()
        (self.game/'main.tscn').write_text('a scene')
        self.route = self.root/'route.json'
        self.route.write_text('{"ticks":215}')
        self.engine = self.root/'godot'
        self.engine.write_text('stand-in engine')
        # Keep any real geometry fixtures collected earlier in discovery intact.
        patcher = mock.patch.object(geometry_fixture, '_traces', {})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.calls = []

    def run_engine(self, route, out, **kw):
        self.calls.append((route, kw))
        out.mkdir(parents=True)
        (out/'trace.json').write_text(json.dumps({'rows': [{'player': [102, 312]}]}))

    def replay(self):
        return geometry_fixture.replay_trace(self.game, self.route, self.root/f'run-{len(self.calls)}', self.engine)

    def test_same_inputs_run_once_but_each_reader_gets_a_fresh_document(self):
        with mock.patch.object(geometry_fixture.hr, 'run', side_effect=self.run_engine):
            first = self.replay()
            first['rows'][0]['player'][0] = -1
            self.assertEqual(self.replay()['rows'][0]['player'], [102, 312])
        self.assertEqual(len(self.calls), 1)
        self.assertIs(self.calls[0][1]['capture_frames'], False)

    def test_changed_scene_route_or_engine_requires_another_real_replay(self):
        with mock.patch.object(geometry_fixture.hr, 'run', side_effect=self.run_engine):
            self.replay()
            (self.game/'main.tscn').write_text('a different scene')
            self.replay()
            self.route.write_text('{"ticks":216}')
            self.replay()
            self.engine.write_text('a different stand-in engine')
            self.replay()
        self.assertEqual(len(self.calls), 4)

    def test_a_failed_replay_is_not_cached(self):
        with mock.patch.object(geometry_fixture.hr, 'run', side_effect=RuntimeError('engine failed')) as run:
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeError, 'engine failed'):
                    self.replay()
        self.assertEqual(run.call_count, 2)


if __name__ == '__main__':
    unittest.main()
