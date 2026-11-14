"""NumPy calibration, accuracy floor, and resumable evidence. No engine or model in these tests."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image
from agents import template_observations as ts
from agents import template_sensor_bench as bench
from tests.test_template_sensor import BOX,CONFIG,TREE,replay,SPEC


def poses(root, *, mirror=False, decoy=False, unseen=False):
    run=replay(root)
    record=json.loads((root/'replay.json').read_text())
    for n in range(3):
        patch_pixels=np.random.default_rng(262+n+(90 if unseen else 0)).integers(20,235,(16,12),dtype=np.uint8)
        if mirror:patch_pixels=patch_pixels[:,::-1]
        image=Image.new('L',(80,70),17)
        sprite=Image.fromarray(patch_pixels)
        image.paste(sprite,(24,20))
        if decoy:image.paste(sprite,(60,20))
        path=root/'frames'/f'f{n:08d}.png';image.save(path);record['frameSha256'][n]=ts.sha(path)
    (root/'replay.json').write_text(json.dumps(record))
    run['replaySha256']=ts.sha(root/'replay.json')
    return run


class CalibrationTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_every_clean_pose_is_considered_and_has_a_mirrored_partner(self):
        poses(self.root/'train');poses(self.root/'validate')
        bank=ts.calibrate_routes([self.root/'train'],self.root/'validate',clean_tree=TREE,config=CONFIG)
        self.assertEqual(len(bank['templates']),6)
        self.assertEqual({t['frame'] for t in bank['templates']},{0,1,2})
        self.assertEqual(sum(t['mirrorX'] for t in bank['templates']),3)
        self.assertEqual(bank['calibration']['status'],'met')
        self.assertGreaterEqual(bank['config']['matchThreshold'],.9)
        run=poses(self.root/'measured-mirrored',mirror=True)
        before=copy.deepcopy(bank)
        result=ts.TemplateObserver(bank).look(SPEC,run)
        self.assertEqual(ts.summarize(result)['counts']['matched'],3)
        self.assertEqual(bank,before)

    def test_unseen_clean_validation_poses_do_not_lower_the_threshold(self):
        poses(self.root/'train');poses(self.root/'validate',unseen=True)
        bank=ts.calibrate_routes([self.root/'train'],self.root/'validate',clean_tree=TREE,config=CONFIG)
        self.assertEqual(bank['calibration']['status'],'unmet')
        self.assertEqual(bank['config']['matchThreshold'],.9)
        self.assertLess(bank['calibration']['positiveMatches'],3)
        with self.assertRaisesRegex(ts.SensorError,'floor'):
            ts.calibrate_routes([self.root/'train'],self.root/'validate',clean_tree=TREE,config=dict(CONFIG,matchThreshold=.89))

    def test_negative_calibration_regions_cannot_be_ignored_to_claim_calibration_success(self):
        poses(self.root/'train');poses(self.root/'validate',decoy=True)
        bank=ts.calibrate_routes([self.root/'train'],self.root/'validate',clean_tree=TREE,config=CONFIG)
        self.assertEqual(bank['calibration']['status'],'unmet')
        self.assertGreater(bank['calibration']['negativeMatches'],0)
        self.assertGreaterEqual(bank['config']['matchThreshold'],.9)

    def test_validation_refuses_a_patched_source(self):
        poses(self.root/'train');replay(self.root/'candidate',patched=True)
        with self.assertRaisesRegex(ts.SensorError,'unpatched clean'):
            ts.calibrate_routes([self.root/'train'],self.root/'candidate',clean_tree=TREE,config=CONFIG)

    def test_numpy_scores_match_an_independent_scalar_correlation(self):
        run=replay(self.root/'clean')
        bank=ts.calibrate(self.root/'clean',clean_tree=TREE,frames=[0],config=dict(CONFIG,sampleSide=4,scales=[1],searchMarginPx=0))
        image=ts._image(run['framesDir']/'f00000000.png')
        # A fixed perturbation: compute area-bin NCC independently, not via the NumPy helper.
        changed=image.copy();changed.putpixel((25,22),200)
        def values(pic):
            return [sum(pic.getpixel((24+x,20+y)) for x in range(i*3,(i+1)*3) for y in range(j*4,(j+1)*4))/12
                    for j in range(4) for i in range(4)]
        a,b=values(image),values(changed)
        am,bm=sum(a)/16,sum(b)/16
        want=sum((x-am)*(y-bm) for x,y in zip(a,b))/(sum((x-am)**2 for x in a)*sum((y-bm)**2 for y in b))**.5
        found,_=ts.match(changed,bank['templates'],BOX,bank['config'])
        self.assertAlmostEqual(found['score'],want,places=5)


class ResumeTest(unittest.TestCase):
    def test_interrupt_resume_reuses_frozen_bank_captures_and_completed_frames(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);game=root/'game';game.mkdir();(game/'project.godot').write_text('[application]\n')
            tree=bench.harness.tree_digest(game);calls=[]
            def standin(route,out,**kwargs):
                calls.append(out.name)
                replay(out,hidden=out.name=='invisible-player',tree=tree,patched=bool(kwargs.get('patches')))
            original=bench.atomic_json
            def interrupt(path,doc):
                original(path,doc)
                if Path(path).parent.name=='clean-smoke' and Path(path).name=='sensor-progress.json' and len(doc['frames'])==1:
                    raise KeyboardInterrupt()
            options=dict(godot=root/'stand-in',game=game,run_replay=standin,config=CONFIG,evidence='offline stand-in')
            with patch.object(bench,'atomic_json',interrupt),self.assertRaises(KeyboardInterrupt):
                bench.measure(root/'out',**options)
            bank=(root/'out/templates.json').read_bytes()
            checkpoint=json.loads((root/'out/clean-smoke/sensor-progress.json').read_text())
            with patch.object(ts,'calibrate_routes',side_effect=AssertionError('frozen bank must be reused')):
                report=bench.measure(root/'out',resume=True,**options)
            after=json.loads((root/'out/clean-smoke/sensor-progress.json').read_text())
            self.assertEqual(after['seconds']['0'],checkpoint['seconds']['0'])
            self.assertEqual((root/'out/templates.json').read_bytes(),bank)
            self.assertEqual(len(calls),len(bench.calibration_routes())+len(bench.CASES))
            self.assertEqual(report['clean']['falseAlarmRate'],0)
            with patch.object(ts.Matcher,'match',side_effect=AssertionError('completed pixels must not be searched again')):
                second=bench.measure(root/'out',resume=True,**options)
            self.assertEqual(report,second)
            with self.assertRaisesRegex(ts.SensorError,'configuration changed'):
                bench.measure(root/'out',resume=True,**dict(options,config=dict(CONFIG,matchThreshold=.91)))
            (root/'out/clean-smoke/frames/f00000000.png').write_bytes(b'changed')
            with self.assertRaisesRegex(ts.SensorError,'pixels changed'):
                bench.measure(root/'out',resume=True,**options)

    def test_target_reader_refuses_a_success_claim_for_missed_targets(self):
        path=Path(__file__).resolve().parent.parent/'contracts/examples/template-measurement.json'
        doc=json.loads(path.read_text())
        doc['targets']['accuracyMet']=False
        with self.assertRaisesRegex(ts.SensorError,'target claims'):
            bench.check_report(doc)


if __name__=='__main__':unittest.main()
