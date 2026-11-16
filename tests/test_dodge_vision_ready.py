"""Dodge readiness: real engine vectors with synthetic PNGs and an explicit engine-box stand-in."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
import urllib.error

from agents import sam_observations as sam
from expectrail import anchored, recorded
from expectrail.gate import record
from harness.run import _replay_record
from tests.test_sam import png_bytes, box_token
from tools import outside_trial as trial, outside_vision as vision, outside_vision_plan as plan
from tools import outside_vision_dry_run as dry

FIXTURES = Path(__file__).resolve().parent/'fixtures/dodge-vision'


def fixture_captures(root):
    source = json.loads((FIXTURES/'frame-aliases.json').read_bytes())['replays']
    hashes = sorted({sha for run in source.values() for sha in run['frameSha256']})
    pngs = {sha:png_bytes(480,720,n+1) for n,sha in enumerate(hashes)}
    project = next(p for p in trial.load_list() if p['name']=='dodge-the-creeps')
    route = next((trial.REPO/project['routes']).glob('*.json'))
    for case in ('pinned','broken','harmless'):
        folder = root/case/route.stem
        frames = folder/'frames'
        frames.mkdir(parents=True)
        trace = json.loads((FIXTURES/(('pinned' if case=='harmless' else case)+'-trace.json')).read_bytes())
        (folder/'trace.json').write_text(json.dumps(trace))
        for n,sha in enumerate(source[case]['frameSha256']):
            (frames/f'f{n:08d}.png').write_bytes(pngs[sha])
        engine = source[case]['engine']
        log = f"Godot Engine v{engine['version']}\nUsing Device: {engine['device']}\n"
        _replay_record(route,folder,source[case]['game']['tree'],60,[],json.loads(route.read_bytes()),
                       log,frames,source[case]['isolation'])
    return project


class DodgeReadinessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory(prefix='expectrail-dodge-stand-in-')
        cls.original = Path(cls.fixture.name)/'captures'
        cls.project = fixture_captures(cls.original)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = shutil.copytree(self.original,self.root/'data')
        self.digest = vision.capture_id(self.project,self.data)

    def preflight(self):
        return vision.preflight(self.project,self.data,self.digest)

    def rewrite(self,case,change):
        folder = self.data/case/'dodge'
        path = folder/'replay.json'
        replay = json.loads(path.read_bytes())
        change(folder,replay)
        path.write_text(json.dumps(replay))
        self.digest = vision.capture_id(self.project,self.data)

    def test_exact_route_clock_visibility_calibration_and_cost_plan(self):
        _path,spec,runs = self.preflight()
        doc = plan.plan(self.project,spec,runs)
        self.assertEqual([r['frames'] for r in doc['runs']],[300]*3)
        self.assertEqual([r['visibleFrames'] for r in doc['runs']],[183,242,183])
        self.assertEqual(doc['calibration']['frames'],list(range(10,91,10)))
        self.assertEqual(doc['calibration']['pointQuestions'],18)
        self.assertEqual((doc['pointQuestions'],doc['boxQuestions']),(750,67))
        self.assertEqual((doc['requests'],doc['images']),(188,188))
        self.assertEqual((doc['listPriceUsd'],doc['worstRetryListPriceUsd']),(0.47,1.88))
        self.assertEqual(doc['maxAttemptsPerQuestion'],sam.MetaSamClient().retries+1)
        self.assertEqual(next(p for p in doc['phases'] if p['phase']=='broken/dodge.json/head')['questions'],0)

    def test_conditional_calibration_uses_real_tick_ids_and_unchanged_rules(self):
        _path,spec,runs = self.preflight()
        client = plan.QuestionClient(dry.EngineBoxes(),conditional=True)
        out = self.root/'calibration'
        vision.anchored(self.project,self.data,client,out,spec=spec,run=runs['pinned','dodge.json'])
        doc = anchored.check_calibration(json.loads((out/'calibration.json').read_bytes()))
        self.assertEqual(doc['rules'],anchored.RULES)
        self.assertEqual(doc['frames'],{'listed':9,'asked':9,'found':9})
        self.assertEqual([r['frame'] for r in doc['rows']],list(range(10,91,10)))
        self.assertTrue(doc['enabled'])
        self.assertIn('STAND-IN',doc['observer']['model'])
        self.assertEqual(doc['drawnSize'],{'width':54.0,'height':68.0})

    def test_real_client_is_never_instantiated_in_stand_in_round_trip(self):
        with mock.patch.object(sam,'MetaSamClient',side_effect=AssertionError('live client')), \
                mock.patch('urllib.request.urlopen',side_effect=AssertionError('network')):
            with mock.patch('sys.stdout',new=io.StringIO()):
                summary = dry.dry_run(self.project,self.data,self.digest,self.root/'out')
        self.assertEqual(summary['verdicts'],{'pinned':'accept','broken':'reject','harmless':'accept'})
        self.assertEqual(summary['recordedReplayVerdicts'],summary['verdicts'])
        self.assertEqual((summary['standInQuestions'],summary['recordingAnswers'],summary['recordedAnswers']),(188,188,188))
        self.assertEqual((summary['modelRequestsSent'],summary['actualSpendUsd']),(0,0))
        self.assertFalse(summary['visionEvidence'])
        doc = recorded.read_recording(self.root/'out/stand-in-vision-recording.json')
        self.assertIn('stand-in',doc['model']['provider'])
        for stage in ('stand-in','recorded-stand-in'):
            self.assertIn('NOT VISION EVIDENCE',(self.root/'out'/stage/'outside-trial.md').read_text())
            for case in ('pinned','broken','harmless'):
                row = record.read_record(self.root/'out'/stage/case/'findings.json')
                self.assertIn('stand-in',row['observers']['visual']['provider'])

    def test_clipped_body_stand_in_preserves_clean_edges_without_rule_changes(self):
        with mock.patch('sys.stdout',new=io.StringIO()):
            summary = dry.dry_run(self.project,self.data,self.digest,self.root/'clip',clip=True)
        self.assertTrue(summary['calibrationEnabled'])
        self.assertEqual(summary['verdicts'],{'pinned':'accept','broken':'reject','harmless':'accept'})
        self.assertEqual(summary['rules'],anchored.RULES)
        self.assertFalse(summary['visionEvidence'])
        row = record.read_record(self.root/'clip/stand-in/pinned/findings.json')
        self.assertEqual(row['decision'],'accept')
        self.assertEqual(row['findings'],[])

    def test_invalid_later_variant_stops_before_any_calibration_question(self):
        frame = self.data/'harmless/dodge/frames/f00000299.png'
        frame.write_bytes(frame.read_bytes()+b'changed after capture')
        client = dry.EngineBoxes()
        with self.assertRaisesRegex(ValueError,'frame 299'):
            vision.judge(self.project,self.data,self.digest,self.root/'invalid',client=client)
        self.assertEqual(client.calls,0)

    def test_fewer_than_eight_unclipped_calibration_samples_stops_before_questions(self):
        def change(folder,replay):
            path=folder/'trace.json';trace=json.loads(path.read_bytes())
            for n in (10,20):trace['rows'][n]['body']=[-87,416,-33,484]
            path.write_text(json.dumps(trace));replay['trace']['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        self.rewrite('pinned',change)
        client=dry.EngineBoxes()
        with self.assertRaisesRegex(ValueError,'fewer than eight'):
            vision.judge(self.project,self.data,self.digest,self.root/'seven',client=client)
        self.assertEqual(client.calls,0)

    def test_renderer_version_and_cross_variant_device_mismatch_stop_before_questions(self):
        for field,value in [('renderer','vulkan'),('version','4.6.3.stable'),('device','different GPU')]:
            with self.subTest(field=field):
                original = (self.data/'broken/dodge/replay.json').read_bytes()
                self.rewrite('broken',lambda _f,r:r['engine'].__setitem__(field,value))
                client = dry.EngineBoxes()
                with self.assertRaisesRegex(ValueError,'renderer|rendering'):
                    vision.judge(self.project,self.data,self.digest,self.root/'bad-renderer',client=client)
                self.assertEqual(client.calls,0)
                (self.data/'broken/dodge/replay.json').write_bytes(original)
                self.digest = vision.capture_id(self.project,self.data)

    def test_unknown_or_insufficient_lifecycle_stops_before_questions(self):
        for unknown in (True,False):
            with self.subTest(unknown=unknown):
                original_trace = (self.data/'pinned/dodge/trace.json').read_bytes()
                original_replay = (self.data/'pinned/dodge/replay.json').read_bytes()
                def change(folder,replay):
                    trace=json.loads(original_trace)
                    for row in trace['rows']:
                        if unknown:row.pop('playerVisible',None)
                        else:row['playerVisible']=False
                    path=folder/'trace.json';path.write_text(json.dumps(trace))
                    replay['trace']['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
                self.rewrite('pinned',change)
                client=dry.EngineBoxes()
                with self.assertRaisesRegex(ValueError,'visibility|in-play'):
                    vision.judge(self.project,self.data,self.digest,self.root/'bad-lifecycle',client=client)
                self.assertEqual(client.calls,0)
                (self.data/'pinned/dodge/trace.json').write_bytes(original_trace)
                (self.data/'pinned/dodge/replay.json').write_bytes(original_replay)
                self.digest=vision.capture_id(self.project,self.data)

    def test_incomplete_capture_refuses_even_when_its_manifest_is_consistent(self):
        def change(folder,replay):
            (folder/'frames/f00000299.png').unlink()
            replay['frameSha256'].pop();replay['capture']['frames']=299
        self.rewrite('harmless',change)
        client=dry.EngineBoxes()
        with self.assertRaisesRegex(ValueError,'incomplete route'):
            vision.judge(self.project,self.data,self.digest,self.root/'short',client=client)
        self.assertEqual(client.calls,0)

    def test_unknown_input_action_and_duplicate_tick_stop_before_questions(self):
        for problem in ('action','tick'):
            with self.subTest(problem=problem):
                original_trace=(self.data/'pinned/dodge/trace.json').read_bytes()
                original_replay=(self.data/'pinned/dodge/replay.json').read_bytes()
                def change(folder,replay):
                    trace=json.loads(original_trace)
                    if problem=='action':trace['unknownActions']=['missing-action']
                    else:trace['rows'][170]['tick']=169
                    path=folder/'trace.json';path.write_text(json.dumps(trace))
                    replay['trace']['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
                self.rewrite('pinned',change)
                client=dry.EngineBoxes()
                with self.assertRaisesRegex(ValueError,'input map|incomplete route'):
                    vision.judge(self.project,self.data,self.digest,self.root/'bad-clock',client=client)
                self.assertEqual(client.calls,0)
                (self.data/'pinned/dodge/trace.json').write_bytes(original_trace)
                (self.data/'pinned/dodge/replay.json').write_bytes(original_replay)
                self.digest=vision.capture_id(self.project,self.data)

    def test_changed_approved_check_is_not_used_or_sent_to_a_model(self):
        spec=json.loads(trial.project_spec(self.project).read_bytes())
        spec['instruction']='changed without a new personal decision'
        path=self.root/'invalid-spec.json';path.write_text(json.dumps(spec))
        client=dry.EngineBoxes()
        with mock.patch.object(trial,'project_spec',return_value=path), self.assertRaisesRegex(ValueError,'approved check'):
            vision.judge(self.project,self.data,self.digest,self.root/'bad-policy',client=client)
        self.assertEqual(client.calls,0)

    def test_hidden_frame_is_not_asked_or_recorded_and_successful_answers_are_reused_exactly(self):
        inner=dry.EngineBoxes();recorder=recorded.RecordingClient(inner);client=plan.QuestionClient(recorder,conditional=True)
        hidden=self.data/'pinned/dodge/frames/f00000000.png'
        with self.assertRaisesRegex(sam.SamError,'in-play'):
            client.segment_at(hidden,[(0,0)])
        self.assertEqual(inner.calls,0)
        png=self.data/'pinned/dodge/frames/f00000010.png'
        first=client.segment_at(png,[(240,450)]);first[0]['box'][0]=-999
        second=client.segment_at(png,[(240,450)])
        self.assertNotEqual(second[0]['box'][0],-999)
        self.assertEqual(inner.calls,1)
        client.segment_at(png,[(243,450)])
        self.assertEqual(inner.calls,2)
        self.assertEqual(len(recorder.recording(sample='dodge-the-creeps',recorded_at='2026-11-16',run='stand-in')['answers']),2)

    def test_errors_are_not_cached_and_retries_are_charged_inside_the_client_cap(self):
        png=self.data/'pinned/dodge/frames/f00000010.png'
        attempts=[]
        def transport(_body):
            attempts.append(True)
            if len(attempts)<4:
                raise urllib.error.HTTPError('https://stand-in.invalid',503,'stand-in',{},io.BytesIO())
            text='<0f>'+box_token(1,(213,395,267,464),0.9,size=(480,720))
            return json.dumps({'output':[{'type':'message','content':[{'type':'output_text','text':text}]}]}).encode(),'application/json'
        zeros=dict(requests=0,images=0,videoFrames=0,reservedUsd=0.0)
        with mock.patch.dict(os.environ,{'EXPECTRAIL_SAM_USD_CAP':'0.01'}), mock.patch.dict(sam._usage,zeros,clear=True):
            client=plan.QuestionClient(sam.MetaSamClient(transport=transport,sleep=lambda _:None))
            client.segment_at(png,[(240,450)])
            self.assertEqual(len(attempts),4)
            self.assertAlmostEqual(sam.sam_usage()['reservedUsd'],0.01)
            client.segment_at(png,[(240,450)])
            self.assertEqual(len(attempts),4)
            with self.assertRaisesRegex(sam.SamError,'cap'):
                client.segment_at(png,[(243,450)])
            self.assertEqual(len(attempts),4)
        failing=mock.Mock(model='stand-in',provider='stand-in')
        failing.segment_at.side_effect=sam.SamError('stand-in',kind='server')
        client=plan.QuestionClient(failing)
        for _ in range(2):
            with self.assertRaises(sam.SamError):client.segment_at(png,[(240,450)])
        self.assertEqual(failing.segment_at.call_count,2)
