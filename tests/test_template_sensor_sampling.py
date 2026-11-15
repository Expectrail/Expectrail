"""Fine clean art sampling and verified saved-pixel comparisons (#262)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agents import template_observations as sensor
from agents import template_sensor_bench as bench
from tests.test_template_sensor import TREE, SPEC, Image, np, needs_pixels, replay


@needs_pixels
class BackgroundCalibrationTest(unittest.TestCase):
    def test_clean_border_changes_match_but_absent_pixels_still_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            box = [24, 20, 36, 36]
            core = sensor._calibration_crop(box, 0.1)
            pixels = np.random.default_rng(262).integers(20, 200, (core[3]-core[1], core[2]-core[0]), dtype=np.uint8)
            runs = []
            for name, background, visible in [('train', 0, True), ('validation', 255, True), ('hidden', 255, False)]:
                folder = root/name
                run = replay(folder)
                record = json.loads((folder/'replay.json').read_text())
                for n in range(3):
                    image = Image.new('L', (80, 70), background)
                    if visible:
                        image.paste(Image.fromarray(pixels), tuple(core[:2]))
                    path = folder/'frames'/f'f{n:08d}.png'
                    image.save(path)
                    record['frameSha256'][n] = sensor.sha(path)
                (folder/'replay.json').write_text(json.dumps(record))
                run['replaySha256'] = sensor.sha(folder/'replay.json')
                runs.append(run)
            config = dict(searchMarginPx=8, scales=[1], sampleSide=12)
            full = sensor.calibrate(root/'train', clean_tree=TREE, frames=[0], config=config)
            original = sensor.TemplateObserver(full).look(SPEC, runs[1])
            self.assertEqual(sensor.summarize(original)['counts']['not-found'], 3)
            bank = sensor.calibrate_routes([root/'train'], root/'validation', clean_tree=TREE, config=config)
            self.assertEqual(bank['config']['matchThreshold'], 0.93)
            self.assertEqual(bank['templates'][0]['box'], core)
            self.assertEqual(bank['templates'][0]['predictedBox'], box)
            self.assertGreaterEqual(sensor._iou(core, box), bank['config']['agreementIoU'])
            frozen = json.loads(json.dumps(bank))
            observer = sensor.TemplateObserver(bank)
            self.assertEqual(sensor.summarize(observer.look(SPEC, runs[1]))['counts']['matched'], 3)
            self.assertEqual(sensor.summarize(observer.look(SPEC, runs[2]))['counts']['not-found'], 3)
            self.assertEqual(runs[0]['trace'], runs[2]['trace'])
            self.assertEqual(bank, frozen)


class CaptureReuseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'source'
        replay(self.source/'clean', frame_bytes=b'opaque test PNG; never decoded')
        self.route = self.root/'route.json'
        # Reuse validates the actual route digest, independent of an output folder's name.
        self.route.write_text('{}')
        path = self.source/'clean/replay.json'
        record = json.loads(path.read_text())
        record['route']['sha256'] = sensor.sha(self.route)
        path.write_text(json.dumps(record))
        self.runner = bench.reuse_captures(self.source, clean_tree=TREE)

    def test_reuse_keeps_exact_trace_metadata_and_png_bytes_without_pixel_dependencies(self):
        target = self.root/'comparison/clean'
        self.runner(self.route, target, patches=[])
        for name in ('trace.json', 'replay.json', 'frames/f00000000.png'):
            self.assertEqual((target/name).read_bytes(), (self.source/'clean'/name).read_bytes())
        (target/'frames/f00000000.png').write_bytes(b'edited comparison')
        self.assertEqual((self.source/'clean/frames/f00000000.png').read_bytes(), b'opaque test PNG; never decoded')

    def test_changed_game_route_patch_trace_or_pixels_are_refused(self):
        for kind in ('game', 'route', 'patch', 'trace', 'pixels'):
            with self.subTest(kind=kind):
                root = self.root/kind
                replay(root/'clean', frame_bytes=b'opaque')
                path = root/'clean/replay.json'
                record = json.loads(path.read_text())
                record['route']['sha256'] = sensor.sha(self.route)
                if kind == 'game':
                    record['game']['tree'] = 'b'*64
                if kind == 'route':
                    record['route']['sha256'] = 'b'*64
                if kind == 'patch':
                    record['game']['patch'] = 'candidate.patch'
                    record['game']['patchSha256'] = 'b'*64
                path.write_text(json.dumps(record))
                if kind == 'trace':
                    (root/'clean/trace.json').write_text('{}')
                if kind == 'pixels':
                    (root/'clean/frames/f00000000.png').write_bytes(b'edited')
                with self.assertRaises(sensor.SensorError):
                    bench.reuse_captures(root, clean_tree=TREE)(self.route, self.root/'target'/kind/'clean', patches=[])


if __name__ == '__main__':
    unittest.main()
