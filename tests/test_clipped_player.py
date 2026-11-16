"""Visible player geometry at screen edges; no image libraries, engine or model calls."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from agents.observations import _frame_box
from expectrail import anchored, recorded
from expectrail.contracts import validate
from expectrail.evaluator import evaluate
from unittest import mock
from tests.test_sam import png_bytes

ROOT = Path(__file__).resolve().parent.parent
RULES_BEFORE = {'found':0.9,'size':0.9,'stable':0.9,'sizeTolerance':0.25,'sizeFloorPx':4.0,
                'stableFloorPx':3.0,'nudgePx':3.0,'minFrames':8}
SPEC = {'format':'expectrail.test-spec/v0','id':'edge-player','instruction':'The player stays in the play area.',
        'objects':{'player':{'prompt':'player'}},'assertion':{'type':'inside-region','object':'player',
        'region':{'box':[0,0,480,720]}},'window':{'fromFrame':0,'toFrame':2}}


def calibration():
    rows = [dict(frame=n,asked=True,body=[54,68],size=[54,68],nudgedSize=[54,68],found=True,
                 sizeAgrees=True,stable=True) for n in range(9)]
    return anchored.judge_calibration({'name':'stand-in-edge','commit':'a'*40},'b'*64,rows,
        RULES_BEFORE,model='STAND-IN',provider='STAND-IN-NOT-VISION')


class Boxes:
    model,provider = 'STAND-IN','STAND-IN-NOT-VISION'
    def __init__(self,run,*,clip=True,change=None):
        self.run,self.clip,self.change=run,clip,change
        self.calls=0
    def segment_at(self,png,points):
        self.calls+=1
        n=int(Path(png).stem[1:]);row=self.run['trace']['rows'][n]
        box=_frame_box(row['view'],row['body'])
        if self.clip:box=[max(0,box[0]),max(0,box[1]),min(480,box[2]),min(720,box[3])]
        if self.change:box=self.change(box)
        return [None if box is None else {'box':box,'score':0.99} for _ in points]


def recorded_findings(observer_type):
    from tests.test_outside_vision import CaptureJudgeTest
    from harness.run import _replay_record
    from tools import outside_vision as vision
    fixture=CaptureJudgeTest('test_saved_gate_runs_no_process_and_records_the_real_trees_and_both_observers')
    fixture.setUp()
    try:
        project={**fixture.project,'changes':[]}
        for case in ('broken','harmless'):shutil.rmtree(fixture.data/case)
        repo=vision.trial.REPO;images=repo/'tests/fixtures/recorded-renderer';bank=repo/'tests/outside/recordings/kinematic-character'
        source=json.loads((images/'source.json').read_bytes());folder=fixture.data/'pinned'/fixture.route.stem
        trace=json.loads((folder/'trace.json').read_bytes())
        for row in trace['rows']:
            for key,value in source['traceRow'].items():
                if key not in ('tick','frame'):row[key]=copy.deepcopy(value)
        (folder/'trace.json').write_text(json.dumps(trace))
        cal=json.loads((bank/'calibration.json').read_bytes());output={}
        for name in ('recorded.png','tinted.png','hidden.png'):
            for png in (folder/'frames').iterdir():shutil.copyfile(images/name,png)
            replay=json.loads((folder/'replay.json').read_bytes())
            _replay_record(fixture.route,folder,replay['game']['tree'],60,[],json.loads(fixture.route.read_bytes()),'',folder/'frames',replay['isolation'])
            client=recorded.RecordedClient(recorded.read_recording(bank/'vision-recording.json'))
            observer=recorded.with_recorded_diagnostics(observer_type(client,cal))
            out=fixture.root/('output-'+name)
            with mock.patch.object(vision.verify,'_now',return_value='2026-11-15T00:00:00Z'),mock.patch.dict('os.environ',{'GITHUB_SHA':'c'*40}):
                vision.judge(project,fixture.data,vision.capture_id(project,fixture.data),out,observer=observer)
            output[name]=(out/'pinned/findings.json').read_text()
        return output
    finally:fixture.doCleanups()

class ClippedPlayerTest(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.frames=self.root/'frames';self.frames.mkdir()
        for n in range(3):(self.frames/f'f{n:08d}.png').write_bytes(png_bytes(480,720,n+1))
    def run_at(self,body,*,view=None):
        row={'body':body,'player':[(body[0]+body[2])/2,(body[1]+body[3])/2],
             'view':view or [1,0,0,1,0,0],'playerVisible':True}
        return {'trace':{'physicsTicksPerSecond':60,'rows':[dict(row,tick=n) for n in range(3)]},
                'framesDir':self.frames,'replaySha256':'c'*64}
    def observe(self,run,**kw):
        client=Boxes(run,**kw)
        seen=anchored.AnchoredObserver(client,calibration()).look(SPEC,run)
        validate(seen,'observations')
        return seen,evaluate(SPEC,seen)
    def test_visible_part_on_every_edge_corner_and_centre_outside_can_pass(self):
        for body in ([-27,416,27,484],[453,416,507,484],[213,-34,267,34],
                     [213,686,267,754],[-27,-34,27,34],[453,686,507,754],
                     [-40,416,14,484],[470,416,524,484],[-27,700,27,768]):
            for clip in (False,True):
                with self.subTest(body=body,clippedAnswer=clip):
                    seen,verdict=self.observe(self.run_at(body),clip=clip)
                    self.assertEqual(verdict['result'],'pass',verdict['reason'])
                    self.assertTrue(all(f['objects']['player'] for f in seen['frames']))
                    self.assertTrue(all('notDrawn' not in f for f in seen['frames']))
    def test_hidden_partly_visible_player_is_still_three_frame_failure(self):
        seen,v=self.observe(self.run_at([453,416,507,484]),change=lambda box:None)
        self.assertEqual(v['result'],'fail');self.assertEqual(v['firstFrame'],0)
        self.assertTrue(all(f['notDrawn']['player']['reason']=='no-match' for f in seen['frames']))
    def test_wrong_visible_width_and_height_are_caught_with_original_floors(self):
        run=self.run_at([453,416,507,484])
        for change in (lambda b:[b[0]+12,b[1],b[2],b[3]],lambda b:[b[0],b[1]+24,b[2],b[3]]):
            seen,v=self.observe(run,change=change)
            self.assertEqual(v['result'],'fail')
            negative=seen['frames'][0]['notDrawn']['player']
            self.assertEqual(negative['reason'],'size-mismatch')
            self.assertEqual(negative['expectedSize'],[27,68])
            self.assertEqual((negative['sizeTolerance'],negative['sizeFloorPx']),(0.25,4))
    def test_same_sized_answer_at_wrong_place_never_passes(self):
        run=self.run_at([453,416,507,484])
        seen,v=self.observe(run,change=lambda b:[b[0]-40,b[1],b[2]-40,b[3]])
        self.assertEqual(v['result'],'fail')
        self.assertEqual(seen['frames'][0]['notDrawn']['player']['reason'],'place-mismatch')
        self.assertFalse(any(f['objects']['player'] for f in seen['frames']))
        # An actual point segmenter returns no object at the question point when the player moved away.
        _,v=self.observe(run,change=lambda b:None)
        self.assertEqual(v['result'],'fail')
    def test_wholly_outside_or_touching_view_is_not_exercised_without_a_request(self):
        for body in ([-54,416,0,484],[480,416,534,484],[213,-68,267,0],[213,720,267,788]):
            run=self.run_at(body);client=Boxes(run)
            for kind in ('inside-region','visible'):
                spec=copy.deepcopy(SPEC)
                if kind=='visible':spec['assertion']={'type':'visible','object':'player'}
                with self.subTest(body=body,kind=kind):
                    seen=anchored.AnchoredObserver(client,calibration()).look(spec,run)
                    validate(seen,'observations')
                    self.assertTrue(all(f['notExercised']=={'player':'outside-view'} for f in seen['frames']))
                    verdict=evaluate(spec,seen)
                    self.assertEqual(verdict['result'],'needs-review')
                    self.assertEqual(verdict['coverage']['semanticResult'],'not_exercised')
                    self.assertEqual(verdict['framesJudged'],0)
            self.assertEqual(client.calls,0)
    def test_one_wholly_outside_frame_cannot_be_dropped_to_manufacture_a_pass(self):
        run=self.run_at([213,416,267,484]);run['trace']['rows'][2]['body']=[480,416,534,484]
        client=Boxes(run)
        seen=anchored.AnchoredObserver(client,calibration()).look(SPEC,run)
        self.assertEqual(seen['frames'][2]['notExercised'],{'player':'outside-view'})
        self.assertEqual(evaluate(SPEC,seen)['result'],'needs-review')
        self.assertEqual(client.calls,2)
    def test_changed_collision_size_cannot_redefine_calibrated_sprite_size(self):
        # A body twice as wide still expects the clean 54-pixel sprite; it must not accept 108.
        seen,v=self.observe(self.run_at([186,416,294,484]))
        self.assertEqual(v['result'],'fail')
        self.assertEqual(seen['frames'][0]['notDrawn']['player']['expectedSize'],[54,68])
    def test_a_wrong_place_still_holding_the_point_is_a_failure(self):
        run=self.run_at([453,416,507,484])
        seen,v=self.observe(run,change=lambda b:[b[0],b[1]+20,b[2],b[3]+20])
        self.assertEqual(v['result'],'fail')
        self.assertEqual(seen['frames'][0]['notDrawn']['player']['reason'],'place-mismatch')
    def test_visible_size_limits_and_floors_are_unchanged_at_the_boundary(self):
        for body,width,delta in (([453,416,507,484],27,6.75),([472,416,526,484],8,4)):
            for extra,result in ((0,'pass'),(0.01,'fail')):
                with self.subTest(width=width,extra=extra):
                    _,v=self.observe(self.run_at(body),change=lambda b:[480-width-delta-extra,b[1],480,b[3]])
                    self.assertEqual(v['result'],result)
    def test_outside_frames_do_not_erase_an_earlier_counterexample(self):
        run=self.run_at([453,416,507,484])
        # Three real negative answers followed by an off-screen frame still fail. The latter
        # is unjudged and cannot replace the earlier counterexample with a no-answer exception.
        run['trace']['rows'].append(dict(run['trace']['rows'][0],tick=3,body=[480,416,534,484]))
        (self.frames/'f00000003.png').write_bytes(png_bytes(480,720,4))
        spec=copy.deepcopy(SPEC);spec['window']['toFrame']=3
        seen=anchored.AnchoredObserver(Boxes(run,change=lambda b:None),calibration()).look(spec,run)
        self.assertEqual(evaluate(spec,seen)['result'],'fail')
        self.assertEqual(seen['frames'][3]['notExercised'],{'player':'outside-view'})
    def test_place_evidence_obeys_confidence_and_three_frame_rule(self):
        run=self.run_at([453,416,507,484])
        seen,v=self.observe(run,change=lambda b:[b[0],b[1]+20,b[2],b[3]+20])
        for n in (1,2):
            self.assertEqual(evaluate(SPEC,dict(seen,frames=seen['frames'][:n]))['result'],'needs-review')
        for frame in seen['frames']:frame['notDrawn']['player']['answer']['score']=0.1
        self.assertEqual(evaluate(SPEC,seen)['result'],'needs-review')

    def test_rules_and_on_screen_recorded_answers_are_byte_identical(self):
        self.assertEqual(anchored.RULES,RULES_BEFORE)
        fixture=ROOT/'tests/fixtures/recorded-renderer'
        before=json.loads((ROOT/'tests/fixtures/clipped-player/kinematic-before.json').read_bytes())
        source=json.loads((fixture/'source.json').read_bytes())
        bank=ROOT/'tests/outside/recordings/kinematic-character'
        cal=json.loads((bank/'calibration.json').read_bytes())
        for frame in self.frames.iterdir():frame.unlink()
        run={'trace':{'physicsTicksPerSecond':120,'rows':[source['traceRow']]*224},
             'framesDir':self.frames,'replaySha256':'a'*64}
        for name,expected in before['cases'].items():
            shutil.copyfile(fixture/name,self.frames/'f00000111.png')
            observer=anchored.AnchoredObserver(recorded.RecordedClient(recorded.read_recording(bank/'vision-recording.json')),cal)
            seen=observer.look(before['spec'],run)
            actual={'observations':seen,'verdict':evaluate(before['spec'],seen)}
            self.assertEqual(json.dumps(actual,sort_keys=True).encode(),json.dumps(expected,sort_keys=True).encode(),name)


    def test_one_outside_frame_cannot_pass_a_fractional_visible_assertion(self):
        run=self.run_at([213,416,267,484]);run['trace']['rows'][2]['body']=[480,416,534,484]
        spec=copy.deepcopy(SPEC);spec['assertion']={'type':'visible','object':'player','minFraction':0.5}
        seen=anchored.AnchoredObserver(Boxes(run),calibration()).look(spec,run)
        v=evaluate(spec,seen)
        self.assertEqual(v['result'],'needs-review');self.assertIn('not-exercised',v['reason'])
    def test_clipped_expected_dimensions_use_camera_scale_and_translation(self):
        for scale in (0.5,1.5,2.0):
            with self.subTest(scale=scale):
                body=[73,416,127,484];view=[scale,0,0,scale,480-100*scale,450-450*scale]
                _,v=self.observe(self.run_at(body,view=view))
                self.assertEqual(v['result'],'pass',v['reason'])
    def test_clipped_contract_example_and_closed_reader(self):
        from expectrail.contracts import ContractError
        example=json.loads((ROOT/'contracts/examples/observations-clipped-player.json').read_bytes())
        validate(example,'observations')
        spec=copy.deepcopy(SPEC);spec['window']['toFrame']=3
        self.assertEqual(evaluate(spec,example)['result'],'fail')
        for change in ('missing-box','unknown-outside','unknown-reason'):
            bad=copy.deepcopy(example)
            if change=='missing-box':del bad['frames'][0]['notDrawn']['player']['expectedVisibleBox']
            elif change=='unknown-outside':bad['frames'][3]['notExercised']['player']='hidden'
            else:bad['frames'][0]['notDrawn']['player']['reason']='provider-failed'
            with self.subTest(change=change),self.assertRaises(ContractError):validate(bad,'observations')

    def test_complete_kinematic_findings_are_byte_identical_with_recorded_answers(self):
        before=json.loads((ROOT/'tests/fixtures/clipped-player/kinematic-findings-before.json').read_bytes())
        actual=recorded_findings(anchored.AnchoredObserver)
        for name in before:
            self.assertEqual(actual[name].encode(),before[name].encode(),name)
