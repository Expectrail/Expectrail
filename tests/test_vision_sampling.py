"""Opt-in outside vision sampling, with no game engine, network or paid model."""
import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from agents.sam_observations import SamError, sample
from expectrail import anchored, recorded
from expectrail.contracts import validate
from expectrail.gate import record, verify
from tests import test_outside_vision as fixture
from tests.test_sam import H, W, png_bytes
from tools import outside_vision as vision


class SamplingTest(unittest.TestCase):
    setUp = fixture.CaptureJudgeTest.setUp

    def hidden(self):
        self.project['changes'].append({'name': 'invisible', 'what': 'player sprite hidden', 'expect': 'reject'})
        folder = self.data / 'invisible' / self.route.stem
        shutil.copytree(self.data / 'pinned' / self.route.stem, folder)
        for frame in (folder / 'frames').glob('*.png'):
            frame.write_bytes(png_bytes(W, H, 19000 + int(frame.stem[1:])))
        replay = json.loads((folder / 'replay.json').read_text())
        fixture._replay_record(self.route, folder, hashlib.sha256(b'invisible').hexdigest(), 60, [],
                              json.loads(self.route.read_text()), '', folder / 'frames', replay['isolation'])
        self.receipt = vision.capture_id(self.project, self.data)

    def run_judge(self, name, every=None, *, client=None):
        out = self.root / name
        kwargs = {} if every is None else {'vision_every': every}
        with mock.patch('subprocess.Popen', side_effect=AssertionError('a process was launched')), \
             mock.patch('agents.sam_observations.MetaSamClient', side_effect=AssertionError('live model')):
            rows = vision.judge(self.project, self.data, self.receipt, out,
                                client=client if client is not None else fixture.Sees(), **kwargs)
        docs = {r['change'] or 'pinned': record.read_record(out / (r['change'] or 'pinned') / 'findings.json')
                for r in rows}
        return out, rows, docs

    def test_default_and_explicit_one_have_identical_evidence_and_decisions(self):
        a, ar, ad = self.run_judge('default')
        b, br, bd = self.run_judge('one', 1)
        self.assertEqual({k:d['decision'] for k,d in ad.items()},
                         {'pinned':'accept','broken':'reject','harmless':'accept'})
        for case in ad:
            for key in ('decision','checks','findings','observers','anchor','counts','reasons'):
                self.assertEqual(ad[case].get(key), bd[case].get(key), (case,key))
            self.assertEqual(ad[case]['observers'].get('visionEvery',1),1)
        self.assertEqual(json.loads((a/'calibration.json').read_text()), json.loads((b/'calibration.json').read_text()))

    def test_stride_four_asks_quarter_of_window_and_keeps_engine_complete(self):
        full, _, all_docs = self.run_judge('full')
        sparse, rows, docs = self.run_judge('four',4)
        self.assertEqual({k:d['decision'] for k,d in docs.items()},
                         {'pinned':'accept','broken':'reject','harmless':'accept'})
        full_obs = json.loads(next((full/'pinned/observations/head').rglob('*.visual.json')).read_text())
        sampled = json.loads(next((sparse/'pinned/observations/head').rglob('*.visual.json')).read_text())
        indices = [f['frame'] for f in full_obs['frames']]
        self.assertEqual([f['frame'] for f in sampled['frames']],sample(indices,4))
        self.assertLessEqual(len(sampled['frames']),len(indices)/4+1)
        self.assertEqual(sampled['analysis']['framesInWindow'],len(indices))
        self.assertEqual(sampled['analysis']['every'],4)
        self.assertEqual(sampled['analysis']['framesAnalyzed'],len(sampled['frames']))
        validate(sampled,'observations')
        for case,d in docs.items():
            self.assertEqual(d['observers']['visionEvery'],4)
            self.assertIn('every 4 frames',record.observers_words(d))
            if 'anchor' in d:
                self.assertEqual(d['anchor'],all_docs[case]['anchor'])
            engines = sorted(p for p in (sparse/case/'verdicts').rglob('*.json') if not p.name.endswith('.visual.json'))
            self.assertTrue(engines)
            for path in engines:
                self.assertEqual(path.read_bytes(),(full/path.relative_to(sparse)).read_bytes())
        self.assertTrue(all(r['visionEvery']==4 for r in rows))
        self.assertIn('shorter than 4 frames may be missed',(sparse/'outside-trial.md').read_text())
        self.assertEqual(json.loads((full/'calibration.json').read_text()),json.loads((sparse/'calibration.json').read_text()))

    def test_observer_stride_four_makes_only_the_selected_point_requests(self):
        run=vision.saved_run(self.data/'pinned'/self.route.stem,self.route)
        cal=anchored.calibrate({'name':'stand','commit':'a'*40},run,fixture.Sees())
        spec=json.loads(vision.trial.SPEC.read_text())
        for every in (1,4):
            client=fixture.Sees()
            seen=anchored.AnchoredObserver(client,cal,every=every).look(spec,run)
            indices=sample(list(range(spec['window']['fromFrame'],spec['window']['toFrame']+1)),every)
            self.assertEqual(client.calls,len(indices))
            self.assertEqual([f['frame'] for f in seen['frames']],indices)

    def test_hidden_player_rejects_after_refining_consecutive_sampled_frames(self):
        self.hidden()
        class Missing(fixture.Sees):
            empty = True
            def segment_at(self,png,points):
                if 'invisible' in Path(png).parts:
                    self.calls+=1
                    return [None if self.empty else {'box':[x-32,y-32,x+32,y+32],'score':0.95} for x,y in points]
                return super().segment_at(png,points)
        for every,empty in ((1,True),(4,True),(4,False)):
            Missing.empty=empty
            out,rows,docs=self.run_judge('hidden-'+str(every)+'-'+str(empty),every,client=Missing())
            self.assertEqual({k:d['decision'] for k,d in docs.items()},
                             {'pinned':'accept','broken':'reject','harmless':'accept','invisible':'reject'})
            reason='\n'.join(f['reason'] for f in docs['invisible']['findings'])
            self.assertIn('did not find player drawn at its place',reason)
            self.assertNotIn('past the boundary',reason)
            if every==4:
                self.assertIn('frames 0, 1, 2',reason)
                self.assertNotIn('consecutive samples',reason)
                seen=json.loads(next((out/'invisible/observations/head').rglob('*.visual.json')).read_text())
                self.assertEqual(seen['analysis']['framesAnalyzed'],seen['analysis']['framesInWindow'])
                self.assertEqual(seen['analysis']['every'],1)
                self.assertTrue(seen['analysis']['refined'])

    def test_short_defect_can_be_missed_only_with_explicit_sampling(self):
        class Blip(fixture.Sees):
            def segment_at(self,png,points):
                if int(Path(png).stem[1:]) in (1,2,3):
                    self.calls+=1
                    return [None for _ in points]
                return super().segment_at(png,points)
        _,_,full=self.run_judge('brief-full',client=Blip())
        _,_,sampled=self.run_judge('brief-sampled',4,client=Blip())
        self.assertEqual(full['pinned']['decision'],'reject')
        self.assertEqual(sampled['pinned']['decision'],'accept')

    def test_two_missing_samples_do_not_satisfy_three_sample_rule(self):
        class Two(fixture.Sees):
            def segment_at(self,png,points):
                if int(Path(png).stem[1:]) in (4,8):
                    self.calls+=1
                    return [None for _ in points]
                return super().segment_at(png,points)
        _,_,docs=self.run_judge('two-samples',4,client=Two())
        self.assertEqual(docs['pinned']['decision'],'needs-review')
        self.assertNotIn('did not find player drawn',' '.join(f['reason'] for f in docs['pinned']['findings']))

    def test_sampled_observer_cannot_relax_default_gate_or_explicit_coverage(self):
        run=vision.saved_run(self.data/'pinned'/self.route.stem,self.route)
        client=fixture.Sees()
        cal=anchored.calibrate({'name':'stand','commit':'a'*40},run,client)
        observer=anchored.AnchoredObserver(client,cal,every=4)
        spec=json.loads(vision.trial.SPEC.read_text())
        run['engineObservations']=verify.observations(run['trace'],run['replaySha256'])
        kw={'ticks':verify.route_ticks(self.route),'rule':record.BOTH,'visual':observer}
        self.assertEqual(verify.judge_run(spec,run,**kw)['result'],'needs-review')
        self.assertEqual(verify.judge_run(spec,run,vision_every=4,**kw)['result'],'pass')
        stronger=copy.deepcopy(spec);stronger['coverage']={'minFraction':0.9}
        # The shared plan now makes the anchored observer inspect every frame for coverage.
        # An observer that still supplies the sparse answer must remain refused.
        sparse=observer.look(spec,run)
        with mock.patch.object(observer,'look',return_value=sparse):
            self.assertEqual(verify.judge_run(stronger,run,vision_every=4,**kw)['result'],'needs-review')
        self.assertEqual(verify.judge_run(stronger,run,vision_every=4,**kw)['result'],'pass')
        # Missing a captured frame is not excused even if it was not scheduled for a vision question.
        frame=run['framesDir']/'f00000001.png';saved=frame.read_bytes();frame.unlink()
        self.assertEqual(verify.judge_run(spec,run,vision_every=4,**kw)['result'],'needs-review')
        frame.write_bytes(saved)
        # The engine's evidence still must cover the full route, not just the sampled frames.
        run['trace']['rows']=run['trace']['rows'][:20]
        run['engineObservations']=verify.observations(run['trace'],run['replaySha256'])
        self.assertEqual(verify.judge_run(spec,run,vision_every=4,**kw)['result'],'needs-review')

    def test_cache_does_not_change_stand_in_decisions_or_findings(self):
        a,_,ad=self.run_judge('cached')
        original=recorded.RecordingClient
        def without_cache(inner,**kw):return original(inner,reuse=False)
        with mock.patch.object(recorded,'RecordingClient',side_effect=without_cache):
            b,_,bd=self.run_judge('uncached')
        for case in ad:
            for key in ('decision','checks','findings','anchor','reasons','observers'):
                self.assertEqual(ad[case].get(key),bd[case].get(key),(case,key))

    def test_stride_cli_and_recording_replay_are_keyless(self):
        client=recorded.RecordingClient(fixture.Sees())
        first,_,ad=self.run_judge('source',4,client=client)
        path=self.root/'answers.json'
        recorded.write_recording(path,client.recording(sample=self.project['name'],run='stand-in',recorded_at='2026-11-15'))
        out=self.root/'replayed'
        cli=fixture.CaptureJudgeTest.cli(self,out,'--recording',str(path),'--vision-every','4')
        with mock.patch('agents.sam_observations.MetaSamClient',side_effect=AssertionError('live model')), \
             mock.patch.dict('os.environ',{'MODEL_API_KEY':'','EXPECTRAIL_SAM_USD_CAP':''}):
            self.assertEqual(vision.main(cli),0)
        for case,d in ad.items():
            replayed=record.read_record(out/case/'findings.json')
            self.assertEqual(replayed['decision'],d['decision'])
            self.assertEqual(replayed['findings'],d['findings'])
            self.assertEqual(replayed['observers']['visionEvery'],4)
        for value in ('0','-1','1.5','NaN'):
            with self.subTest(value=value),self.assertRaises(SystemExit):
                vision.main(fixture.CaptureJudgeTest.cli(self,self.root/'bad','--vision-every',value))

    def test_schema_and_reader_name_the_opt_in_and_refuse_invalid_stride(self):
        doc=record.read_record(vision.trial.REPO/'contracts/examples/findings-sampled-vision.json')
        self.assertIn('every 4 frames',record.observers_words(doc))
        for stride in (0,-1,True,1.5):
            with self.subTest(stride=stride):
                bad=copy.deepcopy(doc);bad['observers']['visionEvery']=stride
                with self.assertRaises(record.RecordError):record.validate(bad,record.schema())
                with self.assertRaises(ValueError):anchored.AnchoredObserver(fixture.Sees(),{},every=stride)
                with self.assertRaises(ValueError):vision.judge(self.project,self.data,self.receipt,self.out,vision_every=stride)


class ExactCacheTest(unittest.TestCase):
    def test_one_request_per_kind_bytes_and_prompt_and_copies_do_not_mutate_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'a.png';b=Path(tmp)/'b.png';a.write_bytes(png_bytes(W,H,1));b.write_bytes(a.read_bytes())
            inner=mock.Mock(model='stand',provider='stand',base='')
            inner.segment_at.return_value=[{'box':[0,0,10,10],'score':0.9}]
            inner.segment_in.return_value=[None]
            client=recorded.RecordingClient(inner,reuse=True)
            with ThreadPoolExecutor(max_workers=4) as pool:
                answers=list(pool.map(lambda _:client.segment_at(a,[(5,5)]),range(8)))
            self.assertEqual(inner.segment_at.call_count,1)
            answers[0][0]['box'][0]=-999
            self.assertEqual(client.segment_at(b,[(5,5)])[0]['box'][0],0)
            client.segment_at(a,[(6,5)])
            self.assertEqual(inner.segment_at.call_count,2)
            client.segment_in(a,[(0,0,10,10)]);client.segment_in(b,[(0,0,10,10)])
            self.assertEqual(inner.segment_in.call_count,1)
            b.write_bytes(png_bytes(W,H,2));client.segment_at(b,[(5,5)])
            self.assertEqual(inner.segment_at.call_count,3)
            self.assertEqual(len(client.recording(sample='stand',run='test',recorded_at='2026-11-15')['answers']),4)

    def test_errors_are_retried_but_successful_empty_answers_are_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            png=Path(tmp)/'f.png';png.write_bytes(png_bytes(W,H,1))
            inner=mock.Mock(model='stand',provider='stand',base='')
            inner.segment_at.side_effect=[SamError('not recorded',kind='not-recorded'),[None]]
            client=recorded.RecordingClient(inner,reuse=True)
            with self.assertRaises(SamError):client.segment_at(png,[(5,5)])
            self.assertEqual(client.segment_at(png,[(5,5)]),[None])
            self.assertEqual(client.segment_at(png,[(5,5)]),[None])
            self.assertEqual(inner.segment_at.call_count,2)
