"""Approved-art masks and true position failures. Public/offline stand-ins, no model or engine."""
from __future__ import annotations

import base64
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents import template_art
from agents import template_foreground as fg
from agents import template_observations as sensor
from agents import template_regions as regions
from agents import template_sensor_bench as bench
from expectrail.evaluator import evaluate
from expectrail.gate.verify import NoAnswer
from harness.run import tree_digest
from tests.test_template_sensor import Image, np, needs_pixels, replay, SPEC

CONFIG = dict(searchMarginPx=8, sampleSide=12, scales=[1])
VIEW = [1, 0, 0, 1, 0, 0]
POLYGONS = [[[0, 36], [80, 36], [80, 70], [0, 70]]]


def make_art(game):
    game.mkdir()
    (game/'project.godot').write_text('[application]\n')
    values = np.random.default_rng(262).integers(40, 201, (16, 12), dtype=np.uint8)
    array = np.zeros((16, 12, 4), np.uint8)
    array[:, :, :3] = values[:, :, None]
    array[2:14, 2:10, 3] = 255
    image = Image.fromarray(array)
    image.save(game/'robot.png')
    return image


def capture(root, *, game, kind='visible', background=17, count=3, decoy=False):
    tree = tree_digest(game)
    run = replay(root, tree=tree, count=count, patched=kind in ('hidden', 'partial', 'colour', 'fall', 'blip'))
    record = json.loads((root/'replay.json').read_text())
    run['trace']['levelSurfaces'] = copy.deepcopy(POLYGONS)
    with Image.open(game/'robot.png') as source:
        art = source.copy()
    for n in range(count):
        image = Image.new('RGB', (80, 70), (background,)*3)
        part = art.copy()
        if kind == 'partial':
            array = np.asarray(part).copy();array[6:10, :, 3] = 0;part = Image.fromarray(array)
        if kind == 'colour':
            array = np.asarray(part).copy()
            array[:, :, 0] += 30;array[:, :, 1] -= 15
            part = Image.fromarray(array)
        if kind == 'zoom':
            part = part.resize((24, 32), Image.Resampling.NEAREST)
            for row in run['trace']['rows'][2*n:2*n+2]:
                row['body'] = [24, 20, 48, 52]
        y = 20+12*n if kind == 'fall' else 20
        if kind == 'fall':
            for row in run['trace']['rows'][2*n:2*n+2]:
                row['body'] = [24, y, 36, y+16]
        if kind != 'hidden' and not (kind == 'blip' and n == 1):
            image.paste(part, (24, y), part)
        if decoy:
            image.paste(art, (60, 20), art)
        path = root/'frames'/f'f{n:08d}.png';image.save(path);record['frameSha256'][n] = sensor.sha(path)
    (root/'trace.json').write_text(json.dumps(run['trace']))
    record['trace']['sha256'] = sensor.sha(root/'trace.json')
    (root/'replay.json').write_text(json.dumps(record))
    run['replaySha256'] = sensor.sha(root/'replay.json')
    return run


@needs_pixels
class ForegroundTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name);self.game = self.root/'game';make_art(self.game)
        self.clean = capture(self.root/'train', game=self.game)
        self.validation = capture(self.root/'validation', game=self.game, background=230)
        self.tree = tree_digest(self.game)
        self.bank = self.calibrate()

    def calibrate(self, **kwargs):
        return fg.calibrate_routes([self.root/'train'], self.root/'validation', clean_game=self.game,
                                   clean_tree=self.tree, art={'player': 'robot.png'}, config=CONFIG, **kwargs)

    def observe(self, run):
        return sensor.TemplateObserver(self.bank).look(SPEC, run)

    def test_clean_background_changes_are_excluded_by_frozen_masks(self):
        self.assertEqual(self.bank['format'], fg.FORMAT)
        self.assertEqual(self.bank['calibration']['status'], 'met')
        doc = self.observe(self.validation)
        self.assertEqual(sensor.summarize(doc)['counts']['matched'], 3)
        self.assertEqual(evaluate(SPEC, doc)['result'], 'pass')
        self.assertEqual(doc['model']['name'], fg.ALGORITHM)
        for frame in doc['frames']:
            self.assertEqual(frame['sensor']['player']['components']['foregroundCoverage'], 1)
        self.assertEqual(self.bank['foregroundSources'][0]['sha256'], sensor.sha(self.game/'robot.png'))

    def test_empty_pixels_fail_with_identical_engine_rows_and_no_network(self):
        hidden = capture(self.root/'hidden', game=self.game, kind='hidden', background=230)
        self.assertEqual(hidden['trace'], self.clean['trace'])
        frozen = copy.deepcopy(self.bank)
        with mock.patch('urllib.request.urlopen', side_effect=AssertionError('no network')), \
                mock.patch.object(fg, 'calibrate_routes', side_effect=AssertionError('no candidate learning')):
            doc = self.observe(hidden)
        self.assertEqual(sensor.summarize(doc)['counts']['not-found'], 3)
        self.assertEqual(evaluate(SPEC, doc)['result'], 'fail')
        self.assertEqual(self.bank, frozen)

    def test_a_single_missing_frame_is_never_filled_from_neighbours(self):
        doc = self.observe(capture(self.root/'blip', game=self.game, kind='blip', background=230))
        self.assertEqual([f['sensor']['player']['status'] for f in doc['frames']], ['matched','not-found','matched'])
        self.assertEqual(evaluate(SPEC, doc)['result'], 'fail')

    def test_missing_body_parts_and_luminance_lookalikes_fail(self):
        for kind in ('partial', 'colour'):
            with self.subTest(kind=kind):
                run = capture(self.root/kind, game=self.game, kind=kind, background=230)
                self.assertEqual(sensor.summarize(self.observe(run))['counts']['not-found'], 3)

    def test_zoom_uses_measured_prediction_ratio_and_colour_confirmation(self):
        doc = self.observe(capture(self.root/'zoom', game=self.game, kind='zoom', background=230))
        self.assertEqual(sensor.summarize(doc)['counts']['matched'], 3)
        self.assertEqual(doc['frames'][0]['objects']['player'][0]['box'], [24,20,48,52])

    def test_mask_tampering_is_a_named_stop_even_with_recomputed_hash(self):
        for value in (0, 1, 2):
            bank = copy.deepcopy(self.bank);item = bank['templates'][0]
            raw = bytes([value])*(item['width']*item['height'])
            item['foregroundMask'], item['foregroundMaskSha256'] = fg.encode(raw)
            with self.subTest(value=value), self.assertRaises(sensor.SensorError):
                sensor.load_bank(bank)

    def test_rgb_luminance_and_digest_disagreements_are_refused(self):
        for edit in ('digest', 'luminance', 'version', 'source'):
            bank = copy.deepcopy(self.bank)
            if edit == 'digest':bank['templates'][0]['rgbPixelsSha256'] = '0'*64
            elif edit == 'luminance':
                item=bank['templates'][0];item['pixels'], item['pixelsSha256'] = fg.encode(bytes([127])*(item['width']*item['height']))
            elif edit == 'version':bank['config']['algorithm'] = sensor.ALGORITHM
            else:bank['groundReference']['sourceTraceSha256'] = '0'*64
            with self.subTest(edit=edit), self.assertRaises(sensor.SensorError):sensor.load_bank(bank)

    def test_missing_or_forged_confirmation_cannot_be_a_match(self):
        doc = self.observe(self.validation)
        for edit in ('missing', 'score', 'unconfirmed'):
            bad = copy.deepcopy(doc);row = bad['frames'][0]['sensor']['player']
            if edit == 'missing':row.pop('components')
            elif edit == 'score':row['score'] = .95;bad['frames'][0]['objects']['player'][0]['score'] = .95
            else:row['components']['foregroundCoverage'] = None;row['components']['partCoverage'] = None
            with self.subTest(edit=edit), self.assertRaises(sensor.SensorError):sensor.summarize(bad)

    def test_unreadable_images_are_unknown_and_cannot_certify_a_partial_run(self):
        (self.root/'validation/frames/f00000001.png').unlink()
        with self.assertRaises(NoAnswer):self.observe(self.validation)

    def test_art_paths_and_changed_trusted_tree_are_refused(self):
        with self.assertRaises(sensor.SensorError):
            fg.art_sources(self.game, {'player': '../outside.png'}, self.tree)
        with self.assertRaises(sensor.SensorError):
            fg.art_sources(self.game, {'player': str(self.game/'robot.png')}, self.tree)
        (self.game/'project.godot').write_text('changed')
        with self.assertRaises(sensor.SensorError):self.calibrate()

    def test_patched_training_and_reused_validation_are_refused(self):
        path=self.root/'train/replay.json';doc=json.loads(path.read_text());doc['game']['patch']='candidate.patch';path.write_text(json.dumps(doc))
        with self.assertRaisesRegex(sensor.SensorError, 'unpatched'):self.calibrate()
        # Restore the source and deliberately reuse its replay for validation.
        capture(self.root/'train2', game=self.game)
        with self.assertRaisesRegex(sensor.SensorError, 'separate clean replay'):
            fg.calibrate_routes([self.root/'train2'], self.root/'train2', clean_game=self.game,
                                clean_tree=self.tree, art={'player':'robot.png'}, config=CONFIG)

    def test_negative_validation_matches_cannot_be_ignored(self):
        capture(self.root/'decoys', game=self.game, background=230, decoy=True)
        bank=fg.calibrate_routes([self.root/'train'], self.root/'decoys', clean_game=self.game,
                                clean_tree=self.tree, art={'player':'robot.png'}, config=CONFIG)
        self.assertEqual(bank['calibration']['status'], 'unmet')
        self.assertGreater(bank['calibration']['negativeMatches'], 0)
        self.assertEqual(bank['config']['matchThreshold'], .9)

    def test_configuration_that_cannot_search_is_unknown_not_absence(self):
        bank=copy.deepcopy(self.bank);bank['config'].update(scales=[4], searchMarginPx=0)
        with self.assertRaises(NoAnswer):sensor.TemplateObserver(bank).look(SPEC, self.validation)

    def test_candidate_does_not_need_access_to_clean_art(self):
        (self.game/'robot.png').unlink()
        self.assertEqual(sensor.summarize(self.observe(self.validation))['counts']['matched'], 3)

    def catalogue(self):
        return dict(format='expectrail.foreground-catalogue/v1', objects={'player': dict(
            artPath='robot.png', spriteGrid=[1, 1], poses=[0],
            sourceScene=dict(path='project.godot', sha256=sensor.sha(self.game/'project.godot')))})

    def test_catalogue_poses_are_registered_on_clean_pixels_and_standalone(self):
        self.bank = self.calibrate(catalogue=self.catalogue())
        poses = [item for item in self.bank['templates'] if item['kind'] == 'approved-art-pose']
        self.assertEqual(len(poses), 2)
        for item in poses:
            self.assertEqual(item['artRegistration']['agreement'], 1)
            self.assertEqual(item['artRegistration']['scale'], 1)
            self.assertEqual(item['artRegistration']['offset'], [0, 0])
        (self.game/'robot.png').unlink()
        self.assertEqual(sensor.summarize(self.observe(self.validation))['counts']['matched'], 3)

    def test_catalogue_registration_and_frozen_bytes_cannot_be_forged(self):
        bank = self.calibrate(catalogue=self.catalogue())
        for edit in ('pose', 'offset', 'agreement', 'anchor', 'rgba', 'palette', 'source'):
            bad = copy.deepcopy(bank)
            item = next(t for t in bad['templates'] if t['kind'] == 'approved-art-pose')
            source = bad['foregroundSources'][0]
            if edit == 'pose':item['artRegistration']['pose'] = 1
            elif edit == 'offset':item['artRegistration']['offset'][0] += 1
            elif edit == 'agreement':item['artRegistration']['agreement'] = .99
            elif edit == 'anchor':item['artRegistration']['anchorRgbSha256'] = '0'*64
            elif edit == 'rgba':source['rgbaPixelsSha256'] = '0'*64
            elif edit == 'palette':source['paletteRgb'] = source['paletteRgb'][:-1]
            else:item['object'] = 'unknown'
            with self.subTest(edit=edit), self.assertRaises(sensor.SensorError):sensor.load_bank(bad)

    def test_catalogue_bad_scene_grid_pose_and_path_are_refused(self):
        for edit in ('digest', 'grid', 'pose', 'duplicate', 'path', 'asset'):
            catalogue = self.catalogue();entry = catalogue['objects']['player']
            if edit == 'digest':entry['sourceScene']['sha256'] = '0'*64
            elif edit == 'grid':entry['spriteGrid'] = [5, 1]
            elif edit == 'pose':entry['poses'] = [1]
            elif edit == 'duplicate':entry['poses'] = [0, 0]
            elif edit == 'path':entry['sourceScene']['path'] = '../outside'
            else:entry['artPath'] = 'other.png'
            with self.subTest(edit=edit), self.assertRaises(sensor.SensorError):self.calibrate(catalogue=catalogue)

    def test_catalogue_cannot_register_a_different_pose(self):
        bank = self.calibrate(catalogue=self.catalogue())
        anchor = copy.deepcopy(next(t for t in bank['templates'] if t['kind'] == 'clean-capture'))
        raw = np.frombuffer(base64.b64decode(anchor['rgbPixels']), np.uint8).copy()
        raw[:] = 250
        anchor['rgbPixels'], anchor['rgbPixelsSha256'] = fg.encode(raw.tobytes())
        with self.assertRaisesRegex(sensor.SensorError, 'registered'):
            template_art.register(bank['foregroundSources'][0], anchor)

    def test_foreground_measurement_reports_true_seed_rules_and_rejects_forged_claims(self):
        def standin(route, out, **kwargs):
            kind = 'hidden' if out.name in ('invisible-player','sinking') else ('fall' if out.name == 'fall-through' else 'visible')
            capture(out, game=self.game, kind=kind, background=230)
        report = bench.measure(self.root/'measured', godot=self.root/'unused', game=self.game,
            run_replay=standin, config=CONFIG, foreground_art={'player':'robot.png'}, evidence='offline stand-in')
        self.assertEqual(report['format'], 'expectrail.template-measurement/v1')
        self.assertEqual(report['clean']['falseAlarmRate'], 0)
        self.assertTrue(report['targets']['falseAlarmTargetMet'])
        self.assertTrue(report['targets']['seedDetectionsMet'])
        self.assertEqual(report['seedDetections']['fall-through']['frames'], [2])
        self.assertEqual(next(r for r in report['runs'] if r['name']=='fall-through')['summary']['counts']['matched'], 3)
        for edit in ('crossing', 'seed', 'target', 'unknown'):
            bad = copy.deepcopy(report)
            if edit == 'crossing':bad['runs'][-1]['regionCheck']['crossedFrames'] = []
            elif edit == 'seed':bad['seedDetections']['fall-through']['detected'] = False
            elif edit == 'target':bad['targets']['falseAlarmTargetMet'] = False
            else:bad['groundReference'] = None
            with self.subTest(edit=edit), self.assertRaises(sensor.SensorError):bench.check_report(bad)



class ForegroundContractTest(unittest.TestCase):
    def test_published_foreground_examples_have_consistent_writer_reader_contracts(self):
        from expectrail.contracts import digest
        folder = Path(__file__).resolve().parents[1]/'contracts/examples'
        bank = json.loads((folder/'template-bank-foreground.json').read_text())
        sensor.validate(bank, 'template-bank')
        doc = json.loads((folder/'observations-template-foreground.json').read_text())
        self.assertEqual(doc['model']['sensor']['bankSha256'], digest(bank))
        self.assertEqual(sensor.summarize(doc)['counts']['matched'], 3)
        report = bench.check_report(json.loads((folder/'template-measurement-foreground.json').read_text()))
        self.assertEqual(report['bankSha256'], digest(bank))
        self.assertTrue(report['targets']['seedDetectionsMet'])
        catalogue = template_art.read_catalogue(folder/'template-foreground-catalogue.json')
        self.assertEqual(catalogue['objects']['player']['spriteGrid'], [8, 8])
        bad = copy.deepcopy(bank);bad['format'] = 'expectrail.template-bank/v0'
        with self.assertRaises(sensor.SensorError):sensor.validate(bad, 'template-bank')

    def test_seed_claims_need_exactly_one_run_for_each_seed(self):
        folder = Path(__file__).resolve().parents[1]/'contracts/examples'
        report = json.loads((folder/'template-measurement-foreground.json').read_text())
        for rows in (report['runs'][:-1], report['runs']+[report['runs'][-1]]):
            bad = dict(report, runs=rows)
            with self.assertRaises(sensor.SensorError):bench.check_report(bad)


class RegionTest(unittest.TestCase):
    def setUp(self):
        self.reference=dict(polygons=copy.deepcopy(POLYGONS))

    def test_visible_below_floor_is_a_position_failure_not_absence(self):
        proof=[dict(frame=n, box=[24,20+12*n,36,36+12*n], view=VIEW) for n in range(3)]
        checked=regions.check(proof,self.reference)
        self.assertEqual(checked['crossedFrames'],[2])
        self.assertEqual(checked['unavailableFrames'],[])

    def test_candidate_ground_body_and_surface_claims_do_not_supply_the_reference(self):
        boxes=[[24,20+12*n,36,36+12*n] for n in range(3)]
        doc={'model':{'sensor':{'captureFps':60}},'frames':[{'frame':n,'objects':{'player':[{'box':box,'score':1}]}} for n,box in enumerate(boxes)]}
        trace={'ticks':3,'physicsTicksPerSecond':60,'levelSurfaces':[],'rows':[{'tick':n,'view':VIEW,'body':[0,0,1,1],'ground':999999} for n in range(3)]}
        first=regions.from_observations(doc,trace,self.reference)
        for row in trace['rows']:row.update(body=[-99,-99,-10,-10],ground=-999)
        trace['levelSurfaces']=[[[0,999],[80,999],[80,1000],[0,1000]]]
        self.assertEqual(regions.from_observations(doc,trace,self.reference),first)
        self.assertEqual(first['crossedFrames'],[2])

    def test_missing_pixels_camera_or_reference_remain_unavailable(self):
        proof=[dict(frame=0,box=None,view=VIEW),dict(frame=1,box=[24,20,36,36],view=None)]
        self.assertEqual(regions.check(proof,self.reference)['unavailableFrames'],[0,1])
        self.assertEqual(regions.check([dict(frame=0,box=[24,20,36,36],view=VIEW)],None)['unavailableFrames'],[0])
        with self.assertRaises(sensor.SensorError):regions.check(proof+proof,self.reference)

    def test_leaving_a_region_or_missing_pixels_does_not_infer_a_crossing_on_return(self):
        first = dict(frame=0, box=[24,20,36,36], view=VIEW)
        below = dict(frame=2, box=[24,44,36,60], view=VIEW)
        for gap in (dict(frame=1,box=[90,20,102,36],view=VIEW), dict(frame=1,box=None,view=VIEW)):
            with self.subTest(gap=gap):
                result = regions.check([first, gap, below], self.reference)
                self.assertEqual(result['crossedFrames'], [])

    def test_overhead_platform_is_not_armed_from_below(self):
        proof=[dict(frame=n,box=[24,20+12*n,36,36+12*n],view=VIEW) for n in range(3)]
        above={'polygons':[[[0,10],[80,10],[80,15],[0,15]]]}
        self.assertEqual(regions.check(proof,above)['crossedFrames'],[])


if __name__ == '__main__':unittest.main()
