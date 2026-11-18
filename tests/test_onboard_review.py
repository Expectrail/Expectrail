"""Human review on throwaway, invented specs only. No committed spec is ever approved."""
import base64
import hashlib
import json
import shutil
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from expectrail import approval, onboard, onboard_page, onboard_review as review
from expectrail.contracts import validate_v1
from expectrail.gate.verify import read_checks

ROOT = Path(__file__).resolve().parents[1]


def png(width=64, height=40):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    pixels = (b'\0' + b'\x67\x99\x55' * width) * height
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB',width,height,8,2,0,0,0)) + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b'')


class HumanReviewTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name); self.root = self.tmp / 'invented-game'; self.root.mkdir()
        (self.root/'project.godot').write_text('[application]\nrun/main_scene="res://main.tscn"\n')
        (self.root/'main.tscn').write_text('[gd_scene format=3]\n[node name="Test" type="Node2D"]\n')
        (self.root/'sprite.png').write_bytes(png())
        (self.root/'routes').mkdir(); (self.root/'checks').mkdir()
        route = {'format':'expectrail.route/v0','name':'invented-review','ticks':4,'seed':1,'events':[]}
        (self.root/'routes/test.json').write_bytes(review.encoded(route))
        config = {'format':'expectrail.project/v1','adapter':'godot','draft':True,'entryScene':'res://main.tscn',
                  'viewport':[64,40],'physicsTicksPerSecond':60,'captureFps':60,'inputActions':[],
                  'bindings':{'player':{'node':'Player','texture':'res://sprite.png'}},'routes':['routes/test.json']}
        (self.root/'expectrail.project.json').write_bytes(review.encoded(config))
        # Entirely synthetic sentence, object and assertion, never a real project check.
        spec = {'format':'expectrail.test-spec/v0','id':'throwaway-review-only','instruction':'The test square stays in the test canvas.',
                'objects':{'player':{'prompt':'invented green test square'}},
                'assertion':{'type':'inside-region','object':'player','region':{'box':[0,0,64,40]},'tolerancePx':0},
                'window':{'fromFrame':0,'toFrame':2}}
        self.spec_path=self.root/'checks/invented.json'; self.spec_path.write_bytes(review.encoded(spec))
        self.capture=self.tmp/'capture'; self.make_capture(self.capture)
        self.broken=self.tmp/'broken'; self.make_capture(self.broken, broken=True)
        self.state=self.tmp/'review'; self.state.mkdir()
        self.record,self.details=review.prepare(self.root,self.state,evidence=self.capture,broken=[('invented broken',self.broken)])
        self.manifest=self.state/'review.json'; self.manifest.write_bytes(review.encoded(self.record))

    def make_capture(self, folder, broken=False):
        (folder/'frames').mkdir(parents=True)
        rows=[]
        for i in range(4):
            box=[50,10,70,20] if broken and i>=1 else [10,10,20,20]
            rows.append({'tick':i,'roleObjects':[{'role':'player','id':1,'visible':True,'box':box,'worldBox':box}]})
            (folder/'frames'/f'f{i:08d}.png').write_bytes(png())
        trace={'format':'expectrail.trace/v0','physicsTicksPerSecond':60,'viewport':[64,40],
               'bindings':{'player':{'node':'Player'}},'capabilities':{'roleBoxes':True},'rows':rows}
        (folder/'trace.json').write_bytes(review.encoded(trace))
        (folder/'replay.json').write_bytes(review.encoded({'capture':{'fps':60}}))

    def answers(self, **changes):
        doc={'format':'expectrail.onboard-answers/v1','reviewFile':str(self.manifest),
             'reviewSha256':review.sha(self.manifest.read_bytes()),'person':'Synthetic Test Person',
             'openedAt':'2026-11-16T00:00:00Z','answeredAt':'2026-11-16T00:01:00Z',
             'objects':{'player':True},'checks':{'throwaway-review-only':True}}
        doc.update(changes); path=self.tmp/'synthetic-answers.json'; path.write_bytes(review.encoded(doc)); return path

    def test_page_has_three_engine_boxes_plain_checks_broken_frame_and_no_network(self):
        page=onboard_page.render(self.record,self.details,self.state,self.manifest,review.sha(self.manifest.read_bytes()))
        self.assertEqual(len(self.details['objects'][0]['samples']),3)
        self.assertTrue(self.record['objects'][0]['reviewable'])
        self.assertIn('First failing frame: 1', page)
        for text in ('The test square stays','Region or condition','Window and coverage','Pass looks like','Fail looks like',
                     'connect-src &#x27;none&#x27;', 'data-kind="objects"', 'data-kind="checks"', 'engine diagnostic; not vision evidence'):
            self.assertIn(text,page)
        self.assertNotIn('src="http',page); self.assertNotIn('fetch(',page)
        self.assertNotIn('localStorage',page); self.assertNotIn('FileSystem',page)
        self.assertNotIn(' checked',page); self.assertNotIn('approval',json.dumps(self.record['config']))
        self.assertLess(len(page.encode()),review.MAX_PAGE_BYTES)
        self.assertIn('<use href="#review-raster-',page)
        self.assertLessEqual(page.count('<image '),2)  # screenshot and optional sprite crop, reused across rows
        self.assertGreater(page.count('<image '),0)
        expected=base64.b64encode(hashlib.sha256(onboard_page.JS.encode()).digest()).decode()
        self.assertIn(expected,page)
        self.assertIn('observer tuning',page); self.assertIn('skipped',page)

    def test_synthetic_human_answers_use_shared_content_binding_and_gate_reader(self):
        before=read_checks(self.root,'checks',['routes/*.json']); self.assertEqual(before.drafts,1)
        with patch.object(approval,'approve',wraps=approval.approve) as shared:
            result=review.approve_answers(self.answers())
        shared.assert_called_once()
        doc=json.loads(self.spec_path.read_bytes()); self.assertEqual(approval.state(doc),approval.BOUND)
        self.assertEqual(doc['approval']['by'],'Synthetic Test Person')
        self.assertEqual(doc['approval']['at'],result['timing']['approvedAt'])
        checked=read_checks(self.root,'checks',['routes/*.json'])
        self.assertEqual(checked.drafts,0); self.assertEqual(len(checked.specs),1); self.assertFalse(checked.problems)
        cfg=json.loads((self.root/'expectrail.project.json').read_bytes()); self.assertNotIn('draft',cfg)
        self.assertEqual(cfg['approvedContracts'],['checks/invented.json'])
        timing=json.loads((self.state/'timing.json').read_bytes()); validate_v1(timing,'onboard-timing')
        self.assertGreaterEqual(timing['humanSeconds'],60); self.assertGreaterEqual(timing['machineSeconds'],0)
        doc['assertion']['tolerancePx']=1; self.assertEqual(approval.state(doc),approval.MISMATCH)

    def test_missing_name_refused_before_any_write(self):
        original=self.spec_path.read_bytes()
        for name in ('','   ','person\nother'):
            with self.subTest(name=name), self.assertRaises(ValueError):review.approve_answers(self.answers(person=name))
            self.assertEqual(self.spec_path.read_bytes(),original)
        self.assertEqual(onboard.main(['--approve',str(self.answers(person=''))]),5)

    def test_no_is_preserved_and_unconfirmed_objects_cannot_approve(self):
        original=self.spec_path.read_bytes()
        with self.assertRaisesRegex(ValueError,'Confirm'):review.approve_answers(self.answers(objects={'player':False}))
        review.approve_answers(self.answers(objects={'player':False},checks={'throwaway-review-only':False}))
        self.assertEqual(self.spec_path.read_bytes(),original)
        self.assertTrue(json.loads((self.root/'expectrail.project.json').read_bytes())['draft'])

    def test_stale_spec_input_review_unknown_answer_and_symlink_refused(self):
        original=self.spec_path.read_bytes(); path=self.answers()
        self.spec_path.write_bytes(original+b' ')
        with self.assertRaisesRegex(ValueError,'changed'):review.approve_answers(path)
        self.spec_path.write_bytes(original)
        project=self.root/'project.godot'; raw=project.read_bytes();project.write_bytes(raw+b' ')
        with self.assertRaisesRegex(ValueError,'changed'):review.approve_answers(path)
        project.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'match'):review.approve_answers(self.answers(checks={'another':True}))
        (self.state/'timing.json').symlink_to(self.tmp/'outside.json')
        with self.assertRaisesRegex(ValueError,'symbolic'):review.approve_answers(self.answers())
        self.assertEqual(self.spec_path.read_bytes(),original); self.assertFalse((self.tmp/'outside.json').exists())

    def test_missing_frames_are_named_and_yes_is_disabled(self):
        shutil.rmtree(self.capture/'frames')
        state=self.tmp/'missing';state.mkdir()
        record,details=review.prepare(self.root,state,evidence=self.capture)
        self.assertFalse(record['objects'][0]['reviewable'])
        page=onboard_page.render(record,details,state,self.manifest,'0'*64)
        self.assertIn('value="yes" disabled',page); self.assertIn('Measured frame unavailable',page)

    def test_cli_writes_page_and_state_but_preserves_game_and_existing_page(self):
        before={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        out=self.tmp/'page.html'
        code=onboard.main(['--project',str(self.root),'--evidence',str(self.capture),'--broken','synthetic='+str(self.broken),'--out',str(out)])
        self.assertEqual(code,0); self.assertIn('First failing frame: 1',out.read_text())
        self.assertEqual(onboard.main(['--project',str(self.root),'--out',str(out)]),5)
        after={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_contract_examples_validate_and_read_only_example_cannot_export(self):
        for kind in ('onboard-review','onboard-answers','onboard-timing'):
            validate_v1(json.loads((ROOT/'contracts/examples'/f'{kind}.v1.json').read_bytes()),kind)
        page=onboard_page.render(self.record,self.details,self.state,self.manifest,'0'*64,example=True)
        self.assertIn('"example":true',page);self.assertIn('This example cannot approve',page)

    def test_exact_recorded_answers_draw_cyan_box_and_missing_answers_stay_missing(self):
        from expectrail import recorded
        class StandIn:
            model,provider='test-stand-in','offline'
            def segment(self,png,prompt):return [{'box':[11,11,19,19],'score':.93}]
        recorder=recorded.RecordingClient(StandIn())
        recorder.segment(self.capture/'frames/f00000000.png','invented green test square')
        path=self.tmp/'test-observer.json'
        recorded.write_recording(path,recorder.recording(sample='throwaway',recorded_at='2026-11-16',run='synthetic-test-only'))
        state=self.tmp/'recorded';state.mkdir()
        record,details=review.prepare(self.root,state,evidence=self.capture,recording=path)
        self.assertTrue(all(f['score']==.93 for f in details['objects'][0]['samples']))
        page=onboard_page.render(record,details,state,self.manifest,'0'*64)
        self.assertIn('observer box',page);self.assertIn('Recorded observer score 0.930',page)
        body=json.loads(path.read_bytes());body['answers'][0]['prompt']='different question'
        path.write_bytes(review.encoded(body))
        other=self.tmp/'not-recorded';other.mkdir()
        _,details=review.prepare(self.root,other,evidence=self.capture,recording=path)
        self.assertTrue(all(f['score'] is None for f in details['objects'][0]['samples']))

    def test_valid_active_config_can_be_reviewed_without_changing_it(self):
        path=self.root/'expectrail.project.json';doc=json.loads(path.read_bytes());doc.pop('draft')
        path.write_bytes(review.encoded(doc));before=path.read_bytes()
        state=self.tmp/'active';state.mkdir()
        record,_=review.prepare(self.root,state,evidence=self.capture)
        self.assertNotIn('draft',record['config']);self.assertEqual(path.read_bytes(),before)

    def test_invalid_timing_refuses_before_signing(self):
        before=self.spec_path.read_bytes()
        for changes in ({'openedAt':'2026-11-17T00:00:00Z'}, {'openedAt':'2026-11-16T00:00:00'},
                        {'answeredAt':'not-a-date'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):review.approve_answers(self.answers(**changes))
            self.assertEqual(self.spec_path.read_bytes(),before)

    def test_a_spec_changed_during_the_import_cannot_be_signed(self):
        original_writer=approval.approve
        def changed(path,by,**kwargs):
            body=json.loads(path.read_bytes());body['instruction']='This changed while importing.'
            path.write_bytes(review.encoded(body))
            return original_writer(path,by,**kwargs)
        with patch.object(approval,'approve',side_effect=changed), self.assertRaisesRegex(ValueError,'changed since review'):
            review.approve_answers(self.answers())
        self.assertNotIn('approval',json.loads(self.spec_path.read_bytes()))

    def test_review_uses_physical_png_dimensions_without_rewriting_logical_trace(self):
        path=self.capture/'trace.json';trace=json.loads(path.read_bytes());trace['viewport']=[32,20]
        for row in trace['rows']:
            row['roleObjects'][0]['box']=[10,25,20,35]
        path.write_bytes(review.encoded(trace));before=path.read_bytes()
        state=self.tmp/'physical';state.mkdir();record,details=review.prepare(self.root,state,evidence=self.capture)
        self.assertTrue(record['objects'][0]['reviewable'])
        self.assertEqual(len(details['objects'][0]['samples']),3)
        self.assertEqual(details['objects'][0]['samples'][0]['engineBox'],[10,25,20,35])
        self.assertEqual(path.read_bytes(),before)

    def test_sprite_is_bound_art_rather_than_an_unverified_replay_crop(self):
        sprite=self.details['objects'][0]['sprite']
        self.assertEqual(sprite['sha256'],review.sha((self.root/'sprite.png').read_bytes()))

    def test_valid_visible_default_is_rendered_as_every_checked_frame(self):
        body=json.loads(self.spec_path.read_bytes());body['assertion']={'type':'visible','object':'player'}
        self.spec_path.write_bytes(review.encoded(body));state=self.tmp/'visible';state.mkdir()
        _,details=review.prepare(self.root,state,evidence=self.capture)
        self.assertIn('100%',details['checks'][0]['condition'])
        self.assertEqual(details['checks'][0]['results'][0]['result'],'pass')

    def test_diagnostic_respects_the_capture_route_identity(self):
        body=json.loads(self.spec_path.read_bytes());body['coverage']={'routes':['another-route']}
        self.spec_path.write_bytes(review.encoded(body))
        path=self.capture/'replay.json';doc=json.loads(path.read_bytes());doc['route']={'name':'invented-review'}
        path.write_bytes(review.encoded(doc));state=self.tmp/'scoped';state.mkdir()
        _,details=review.prepare(self.root,state,evidence=self.capture)
        self.assertEqual(details['checks'][0]['results'][0]['result'],'not-applicable')
        self.assertIn('another-route',details['checks'][0]['window'])

    def test_words_include_open_window_relative_margin_overlap_and_every_checkpoint_kind(self):
        body=json.loads(self.spec_path.read_bytes());body['window']={'fromFrame':8}
        body['assertion']['region']={'relativeTo':'ground','marginPx':-3}
        body['coverage']={'minFrames':4,'minFraction':.75,'reached':[
            {'type':'on-floor','fromTick':9},{'type':'coin-count-change','fromTick':10},
            {'type':'position-at-tick','tick':11,'object':'player','x':12,'y':13,'tolerancePx':2}]}
        words=review.check_words(body)
        self.assertIn('shrunk by 3',words['condition'])
        for text in ('From frame 8','75%','4 exercised','touch the floor','coin count','exactly tick 11','(12, 13)'):
            self.assertIn(text,words['window'])
        body['assertion']={'type':'never-crosses','object':'player','boundary':{'relativeTo':'ground','edge':'top','side':'above'}}
        self.assertIn('horizontal overlap',review.check_words(body)['condition'])
