"""Offline pixels and replay stand-ins for #262. No engine, model, network, or approved spec edits."""
from __future__ import annotations

import copy
import hashlib
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from agents import template_observations as ts
from agents import template_sensor_bench as bench
from agents.unity_observations import agreeing
from expectrail.contracts import digest, validate
from expectrail.evaluator import evaluate
from expectrail.gate.verify import NoAnswer

TREE = 'a'*64
SPEC = bench.SPEC
BOX = [24, 20, 36, 36]
CONFIG = dict(searchMarginPx=8, stridePx=1, scales=[0.75, 1, 1.5], sampleSide=12)


def sprite():
    rng = random.Random(262)
    image = Image.new('L', (12, 16))
    image.putdata([rng.randrange(20, 235) for _ in range(12*16)])
    return image


def picture(*, hidden=False, location=(24, 20), scale=1):
    image = Image.new('L', (80, 70), 17)
    if not hidden:
        part = sprite().resize((12*scale, 16*scale), Image.Resampling.NEAREST)
        image.paste(part, location)
    return image


def replay(root, *, hidden=False, location=(24, 20), scale=1, tree=TREE, patched=False, count=3):
    root.mkdir(parents=True)
    (root/'frames').mkdir()
    rows=[]
    hashes=[]
    box=[24,20,24+12*scale,20+16*scale]
    for n in range(count):
        path=root/'frames'/f'f{n:08d}.png'
        picture(hidden=hidden,location=location,scale=scale).save(path)
        hashes.append(ts.sha(path))
        for tick in (n*2,n*2+1):
            rows.append(dict(tick=tick,body=box,player=[30,30],view=[1,0,0,1,0,0]))
    trace=dict(format='expectrail.trace/v0',ticks=count*2,physicsTicksPerSecond=120,rows=rows)
    (root/'trace.json').write_text(json.dumps(trace))
    document=dict(format='expectrail.replay/v0',route=dict(name=root.name,sha256='c'*64),game=dict(tree=tree,patch='bug.patch' if patched else None,
                  patchSha256='b'*64 if patched else None),capture=dict(fps=60,frames=count),
                  trace=dict(path='trace.json',sha256=ts.sha(root/'trace.json')),frameSha256=hashes)
    (root/'replay.json').write_text(json.dumps(document))
    return dict(trace=trace,framesDir=root/'frames',replaySha256=ts.sha(root/'replay.json'))


class SensorTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.clean=replay(self.root/'clean')
        self.bank=ts.calibrate(self.root/'clean',clean_tree=TREE,frames=[0],config=CONFIG)

    def observe(self, run=None, **kwargs):
        run = run or self.clean
        return ts.from_replay(run['trace'], replay_sha256=run['replaySha256'], frames_dir=run['framesDir'],
                              bank=kwargs.pop('bank',self.bank), spec=SPEC, **kwargs)

    def test_clean_pixels_match_and_the_existing_evaluator_reads_them(self):
        doc=self.observe()
        validate(doc,'observations')
        self.assertEqual(ts.summarize(doc)['agreementRate'],1)
        self.assertEqual(evaluate(SPEC,doc)['result'],'pass')
        self.assertTrue(all(f['objects']['player'][0]['box']==BOX for f in doc['frames']))
        self.assertTrue(all(f['objects']['player'][0]['score']==1 for f in doc['frames']))

    def test_invisible_pixels_fail_even_with_identical_engine_rows(self):
        hidden=replay(self.root/'hidden',hidden=True,patched=True)
        self.assertEqual(hidden['trace'],self.clean['trace'])
        doc=self.observe(hidden)
        self.assertEqual(ts.summarize(doc)['counts']['not-found'],3)
        self.assertEqual(evaluate(SPEC,doc)['result'],'fail')
        self.assertTrue(all(f['objects']['player']==[] for f in doc['frames']))

    def test_camera_zoom_and_multiscale_matching(self):
        run=replay(self.root/'zoom',scale=2)
        doc=self.observe(run)
        self.assertEqual(ts.summarize(doc)['agreementRate'],1)
        self.assertEqual(doc['frames'][0]['objects']['player'][0]['box'],[24,20,48,52])
        self.assertEqual(doc['frames'][0]['sensor']['player']['scale'],2)

    def test_fractional_engine_boxes_do_not_rescale_an_identical_clean_crop(self):
        box=[24.2,20.2,35.2,35.2]
        predicted={n:{'player':box} for n in range(3)}
        bank=ts.calibrate(self.root/'clean',clean_tree=TREE,frames=[0],config=CONFIG,predicted=predicted)
        self.assertEqual(bank['templates'][0]['predictedBox'],box)
        self.assertEqual(bank['templates'][0]['box'],BOX)
        doc=self.observe(bank=bank,predicted=predicted)
        self.assertEqual(doc['frames'][0]['sensor']['player']['score'],1)
        self.assertEqual(doc['frames'][0]['sensor']['player']['rawBox'],BOX)
        self.assertEqual(doc['frames'][0]['sensor']['player']['scale'],1)

    def test_scale_search_is_not_only_the_predicted_size(self):
        bank=copy.deepcopy(self.bank)
        bank['config']['scales']=[1,1.5,2]
        bank['config']['searchMarginPx']=16
        run=replay(self.root/'bigger',scale=2)
        for row in run['trace']['rows']:
            row['body']=BOX
        doc=self.observe(run,bank=bank)
        row=doc['frames'][0]['sensor']['player']
        self.assertEqual(row['scale'],2)
        self.assertEqual(row['rawBox'],[24,20,48,52])
        self.assertEqual(row['status'],'displaced')

    def test_matching_pixels_far_from_the_prediction_are_reported_not_silently_dropped(self):
        bank=copy.deepcopy(self.bank)
        bank['config']['searchMarginPx']=16
        doc=self.observe(replay(self.root/'shift',location=(35,20)),bank=bank)
        row=doc['frames'][0]['sensor']['player']
        self.assertEqual(row['status'],'displaced')
        self.assertEqual(row['rawBox'],[35,20,47,36])
        self.assertEqual(row['score'],1)
        self.assertEqual(doc['frames'][0]['objects']['player'],[])

    def test_search_never_wanders_outside_the_declared_region(self):
        doc=self.observe(replay(self.root/'far',location=(60,40)))
        self.assertEqual(doc['frames'][0]['sensor']['player']['status'],'not-found')
        self.assertEqual(doc['frames'][0]['sensor']['player']['searchBox'],[16,12,44,44])

    def test_existing_agreeing_callback_and_removal_reason(self):
        trace={'rows':[{'frame':n,'objects':[dict(role='player',visible=True,box=BOX)]} for n in range(3)]}
        doc=self.observe(agreeing=agreeing(trace,['player']))
        self.assertEqual(ts.summarize(doc)['agreementRate'],1)
        trace['rows'][0]['objects'][0]['box']=[60,40,72,56]
        doc=self.observe(agreeing=agreeing(trace,['player']))
        self.assertEqual(doc['frames'][0]['objects']['player'],[])
        self.assertEqual(doc['frames'][0]['sensor']['player']['status'],'displaced')
        self.assertEqual(doc['frames'][0]['sensor']['player']['rawBox'],BOX)

    def test_agreement_cannot_invent_a_detection(self):
        def invent(doc):
            doc[0]['player']=[dict(box=[0,0,4,4],score=1)]
            return doc
        with self.assertRaisesRegex(ts.SensorError,'only remove'):
            self.observe(agreeing=invent)

    def test_observer_interface_is_explicit_and_refuses_colour(self):
        observer=ts.TemplateObserver(self.bank)
        self.assertEqual(observer.describe()['provider'],'local')
        self.assertEqual(observer.look(SPEC,self.clean,keep=False),self.observe())
        with self.assertRaisesRegex(NoAnswer,'colour'):
            ts.TemplateObserver(self.bank,required_capabilities=['colour']).look(SPEC,self.clean)
        colour=copy.deepcopy(SPEC)
        colour['assertion']['type']='colour-is'
        with self.assertRaises(NoAnswer):
            observer.look(colour,self.clean)
        self.assertIn('Colour',self.observe()['model']['sensor']['limitations'][0])

    def test_missing_image_is_unknown_not_invisible_or_a_partial_pass(self):
        (self.root/'clean/frames/f00000001.png').unlink()
        doc=self.observe()
        self.assertEqual(ts.summarize(doc)['counts']['unavailable'],1)
        self.assertEqual(ts.summarize(doc)['counts']['not-found'],0)
        with self.assertRaisesRegex(NoAnswer,'not all requested frames'):
            ts.TemplateObserver(self.bank).look(SPEC,self.clean)

    def test_missing_body_camera_and_truncated_trace_never_become_boxes(self):
        for mutation in ('body','view','row'):
            run=copy.deepcopy(self.clean)
            if mutation=='row':
                run['trace']['rows']=run['trace']['rows'][:2]
            elif mutation=='body':
                run['trace']['rows'][1].pop('body')
            else:
                run['trace']['rows'][2].pop('view')
            with self.subTest(mutation=mutation):
                doc=self.observe(run)
                self.assertGreater(ts.summarize(doc)['counts']['unavailable'],0)
                with self.assertRaises(NoAnswer):
                    ts.TemplateObserver(self.bank).look(SPEC,run)

    def test_off_screen_and_empty_windows_are_not_claimed_as_success(self):
        run=copy.deepcopy(self.clean)
        for row in run['trace']['rows']:
            row['body']=[-5,20,7,36]
        doc=self.observe(run)
        self.assertEqual(ts.summarize(doc)['counts']['out-of-frame'],3)
        self.assertIsNone(ts.summarize(doc)['agreementRate'])
        with self.assertRaises(NoAnswer):
            ts.TemplateObserver(self.bank).look(SPEC,run)
        spec=dict(SPEC,window={'fromFrame':20,'toFrame':30})
        with self.assertRaises(NoAnswer):
            ts.TemplateObserver(self.bank).look(spec,self.clean)

    def test_every_document_records_the_frozen_settings_and_alignment(self):
        metadata=self.observe()['model']['sensor']
        self.assertEqual(metadata['config'],self.bank['config'])
        self.assertEqual(metadata['bankSha256'],digest(self.bank))
        self.assertEqual(metadata['clean']['gameTree'],TREE)
        self.assertEqual((metadata['captureFps'],metadata['physicsTicksPerSecond']),(60,120))
        self.assertIn('half-open',metadata['config']['coordinates'])
        broken=self.observe()
        broken['model']['sensor']['config'].pop('matchThreshold')
        with self.assertRaises(Exception):
            validate(broken,'observations')
        with self.assertRaises(ts.SensorError):
            ts.summarize(broken)

    def test_calibration_refuses_candidate_patches_or_an_untrusted_tree(self):
        replay(self.root/'candidate',patched=True)
        with self.assertRaisesRegex(ts.SensorError,'pinned clean'):
            ts.calibrate(self.root/'candidate',clean_tree=TREE,frames=[0])
        with self.assertRaisesRegex(ts.SensorError,'pinned clean'):
            ts.calibrate(self.root/'clean',clean_tree='b'*64,frames=[0])

    def test_calibration_verifies_pixels_and_trace_against_the_replay(self):
        (self.root/'clean/frames/f00000000.png').write_bytes(b'not the clean image')
        with self.assertRaisesRegex(ts.SensorError,'does not match'):
            ts.calibrate(self.root/'clean',clean_tree=TREE,frames=[0])
        (self.root/'clean/trace.json').write_text('{}')
        with self.assertRaisesRegex(ts.SensorError,'trace digest'):
            ts.calibrate(self.root/'clean',clean_tree=TREE,frames=[0])

    def test_candidate_observation_never_changes_or_recalibrates_the_bank(self):
        path=self.root/'bank.json'
        ts.calibrate(self.root/'clean',clean_tree=TREE,frames=[0],config=CONFIG,out=path)
        original=path.read_bytes()
        ts.TemplateObserver(path).look(SPEC,replay(self.root/'candidate',hidden=True,patched=True))
        self.assertEqual(path.read_bytes(),original)
        with self.assertRaises(FileExistsError):
            ts.calibrate(self.root/'clean',clean_tree=TREE,frames=[0],config=CONFIG,out=path)

    def test_flat_templates_tampered_pixels_and_unknown_versions_are_refused(self):
        replay(self.root/'flat',hidden=True)
        with self.assertRaisesRegex(ts.SensorError,'flat template'):
            ts.calibrate(self.root/'flat',clean_tree=TREE,frames=[0])
        for edit in ('pixelsSha256','algorithm','threshold'):
            bank=copy.deepcopy(self.bank)
            if edit=='pixelsSha256':bank['templates'][0][edit]='0'*64
            elif edit=='algorithm':bank['config'][edit]='unknown/v99'
            else:bank['config']['matchThreshold']=float('nan')
            with self.subTest(edit=edit),self.assertRaises(ts.SensorError):
                ts.load_bank(bank)

    def test_duplicate_frames_ticks_and_invalid_capture_rates_are_refused(self):
        path=self.root/'clean/frames/f0.png'
        path.write_bytes((self.root/'clean/frames/f00000000.png').read_bytes())
        with self.assertRaisesRegex(ts.SensorError,'duplicate captured'):
            self.observe()
        path.unlink()
        run=copy.deepcopy(self.clean)
        run['trace']['rows'][1]['tick']=0
        with self.assertRaisesRegex(ts.SensorError,'duplicate trace'):
            self.observe(run)
        with self.assertRaisesRegex(ts.SensorError,'divide'):
            self.observe(fps=59)

    def test_no_network_is_needed_even_when_observer_runs(self):
        with patch('socket.socket',side_effect=AssertionError('no network')):
            doc=ts.TemplateObserver(self.bank).look(SPEC,self.clean)
            self.assertEqual(ts.summarize(doc)['agreementRate'],1)

    def test_transform_uses_all_four_corners_and_next_tick_camera(self):
        trace={'ticks':2,'physicsTicksPerSecond':60,'rows':[
            dict(tick=0,body=[0,0,4,8],view=[1,0,0,1,0,0]),
            dict(tick=1,body=[0,0,4,8],view=[1,1,-1,1,10,20])]}
        self.assertEqual(ts.player_predictions(trace,[0,1],60),
                         {0:{'player':[2,20,14,32]},1:{'player':[2,20,14,32]}})

    def test_reader_refuses_missing_evidence_or_fabricated_detections(self):
        original=self.observe()
        for edit in ('missing','invented','duplicate'):
            doc=copy.deepcopy(original)
            if edit=='missing':doc['frames'][0].pop('sensor')
            elif edit=='invented':doc['frames'][0]['objects']['player'][0]['box']=[0,0,4,4]
            else:doc['frames'].append(copy.deepcopy(doc['frames'][0]))
            with self.subTest(edit=edit),self.assertRaises(ts.SensorError):
                ts.summarize(doc)


class MeasurementTest(unittest.TestCase):
    def test_contract_examples_are_synthetic_and_read_by_both_readers(self):
        folder=Path(__file__).resolve().parent.parent/'contracts/examples'
        bank=ts.load_bank(folder/'template-bank.json')
        validate(bank,'template-bank')
        observation=json.loads((folder/'observations-template.json').read_text())
        validate(observation,'observations')
        self.assertEqual(ts.summarize(observation)['counts']['not-found'],3)
        report=json.loads((folder/'template-measurement.json').read_text())
        validate(report,'template-measurement')
        self.assertIn('offline stand-in',bench.render(report))

    def test_linux_measurement_script_with_offline_replay_standins(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            game=root/'game';game.mkdir();(game/'project.godot').write_text('[application]\n')
            tree=bench.harness.tree_digest(game)
            calls=[]
            def standin(route,out,**kwargs):
                calls.append((out.name,kwargs))
                replay(out,hidden=out.name=='invisible-player',tree=tree,patched=bool(kwargs.get('patches')))
            report=bench.measure(root/'out',godot=root/'stand-in',game=game,run_replay=standin,
                                 config=CONFIG,evidence='offline stand-in; not real-engine rates')
            self.assertEqual([name for name,kw in calls],[r['name'] for r in bench.calibration_routes()]+[c[0] for c in bench.CASES])
            self.assertTrue(all(kw['capture_frames'] for _,kw in calls))
            self.assertEqual(report['clean'],dict(measured=9,alarms=0,falseAlarmRate=0))
            self.assertEqual(report['invisiblePlayerAlarms'],3)
            self.assertIn('offline stand-in',bench.render(report))
            self.assertIn('9 measured object-frames',bench.render(report))
            hidden=next(kw for name,kw in calls if name=='invisible-player')
            self.assertEqual([p.name for p in hidden['patches']],['v1.patch','fix-but-hide-player.patch'])
            self.assertTrue((root/'out/template-measurement.json').is_file())
            forged=copy.deepcopy(report)
            forged['clean']['falseAlarmRate']=1
            with self.assertRaisesRegex(ts.SensorError,'aggregate'):
                bench.render(forged)
            forged=copy.deepcopy(report)
            forged['runs'][0]['summary']['agreementRate']=0
            with self.assertRaisesRegex(ts.SensorError,'rates disagree'):
                bench.render(forged)
            with self.assertRaisesRegex(ts.SensorError,'new output'):
                bench.measure(root/'out',godot=root/'stand-in',game=game,run_replay=standin)


if __name__=='__main__':
    unittest.main()
