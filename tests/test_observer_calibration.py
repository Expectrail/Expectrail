"""Offline loop and stale-art gate tests. All observers/data here are throwaway test doubles.
Guard: test change intended (#330)
No approval is written or changed: the gate test copies an existing approved check unchanged.
"""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from expectrail import calibration as c
from expectrail.contracts import digest
from expectrail.gate.verify import NoAnswer


class StandIn:
    minimum_floor = 0.0
    bank = {'testDouble': 'offline loop, not vision evidence'}

    def __init__(self, miss=None, gap=None):
        self.miss, self.gap = miss, gap

    def describe(self):
        return dict(identity={'name':'template','model':'throwaway-test-double','provider':'local'},
                    evidence='stand-in', sourceSha256=digest(self.bank))

    def detect(self, prompt, frame):
        if frame['case'] == self.gap:
            raise NoAnswer('stand-in has no recorded answer')
        good = dict(box=frame['expectedBox'], score=0.95)
        if prompt == 'small robot character':
            return [good, dict(box=[40,40,50,50], score=0.99)]
        if frame['case'] in ('selection','clean',self.miss):
            return [good]
        if frame['case'] == 'shifted-off-body':
            return [dict(box=[40,10,50,20], score=0.99)]
        return []


class LoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.game = self.root/'game';self.game.mkdir()
        (self.game/'texture.png').write_bytes(b'throwaway texture')
        self.selection = self.frames('selection')
        self.clean = self.frames('clean')
        self.broken = [dict(name=name,patchSha256=hashlib.sha256(name.encode()).hexdigest(),frames=self.frames(name)) for name in c.BROKEN]

    def frames(self, case):
        rows=[]
        for n in range(8):
            png=self.root/f'{case}-{n}.png';png.write_bytes(f'throwaway stand-in {case} {n}'.encode())
            rows.append(dict(frame=n,png=png,expectedBox=[10,10,20,20],replaySha256='a'*64,case=case))
        return rows

    def run_loop(self, adapter=None):
        return c.calibrate(adapter=adapter or StandIn(), candidates=['small robot character','blue robot'],
                           selection=self.selection,clean=self.clean,broken=self.broken,game=self.game,textures=['texture.png'])

    def test_unique_player_wins_and_the_enemy_phrase_is_rejected(self):
        doc=self.run_loop()
        self.assertEqual(doc['selected'],'blue robot');self.assertTrue(doc['enabled'])
        self.assertEqual(doc['missed'],[])
        self.assertTrue(all(c.status(r,0.9)=='fail' for r in doc['candidates'][0]['rows']))
        self.assertTrue(all(any(c.status(r,0.9)=='fail' for r in v['rows']) for v in doc['broken']))

    def test_a_missed_copy_is_named_and_disables_the_calibration(self):
        doc=self.run_loop(StandIn(miss='behind-scenery'))
        self.assertFalse(doc['enabled']);self.assertEqual(doc['missed'],['behind-scenery'])

    def test_missing_answers_are_not_negative_pixel_evidence(self):
        doc=self.run_loop(StandIn(gap='hidden'))
        self.assertFalse(doc['enabled']);self.assertEqual(doc['missed'],['hidden'])
        self.assertTrue(all(c.status(r,0.9)=='unavailable' for r in doc['broken'][0]['rows']))

    def test_proof_cannot_change_the_prompt_or_floor_and_clean_failure_disables(self):
        doc=self.run_loop(StandIn(gap='clean'))
        self.assertEqual(doc['selected'],'blue robot');self.assertEqual(doc['candidates'][1]['floor'],0.9)
        self.assertFalse(doc['enabled']);self.assertIn('clean proof',doc['why'][0])

    def test_proof_pixels_cannot_be_selection_pixels_even_with_other_frame_numbers(self):
        self.clean[0]['png']=self.selection[3]['png']
        with self.assertRaisesRegex(c.CalibrationError,'proof pixels'):
            self.run_loop()

    def test_record_round_trip_schema_and_recomputed_results(self):
        doc=self.run_loop();p=c.write(self.root/'record.json',doc)
        self.assertEqual(c.read(p),doc)
        for change in ('enabled','floor','box','digest','duplicate','omitted-copy','false-negative'):
            bad=copy.deepcopy(doc)
            if change=='enabled':bad['enabled']=False
            elif change=='floor':bad['candidates'][1]['floor']=0.1
            elif change=='box':bad['clean'][0]['expectedBox']=[20,10,10,20]
            elif change=='digest':bad['artSha256']='0'*64
            elif change=='duplicate':bad['clean'].append(bad['clean'][0])
            elif change=='omitted-copy':bad['broken'].pop()
            else:bad['clean'][0]['error']='not-recorded'
            with self.subTest(change=change),self.assertRaises(c.CalibrationError):c.check(bad)

    def test_no_candidate_is_explicitly_unobservable_with_all_copies_named(self):
        class Empty(StandIn):
            def detect(self,prompt,frame):return []
        doc=self.run_loop(Empty())
        self.assertIsNone(doc['selected']);self.assertFalse(doc['enabled'])
        self.assertEqual(set(doc['missed']),set(c.BROKEN))

    def test_texture_paths_and_reader_refuse_escapes_links_and_duplicate_json(self):
        for name in ('../texture.png','/texture.png','./texture.png'):
            with self.subTest(name=name),self.assertRaises(c.CalibrationError):c.art_digests(self.game,[name])
        (self.game/'link.png').symlink_to(self.game/'texture.png')
        with self.assertRaises(c.CalibrationError):c.art_digests(self.game,['link.png'])
        p=self.root/'bad.json';p.write_text('{"format":1,"format":2}')
        with self.assertRaises(c.CalibrationError):c.read(p)

    def test_stand_in_can_never_enable_a_real_verification(self):
        doc=self.run_loop()
        class Delegate:
            bank=StandIn.bank
            def describe(inner):return doc['observer']['identity']
        wrapped=c.CalibratedObserver(Delegate(),doc,self.game)
        with self.assertRaisesRegex(NoAnswer,'stand-in'):wrapped.describe()

    def test_changed_texture_stops_before_the_delegate_can_judge(self):
        # Test double for the local pixel adapter, not a SAM recording or real calibration claim.
        doc=self.run_loop();doc['observer']['evidence']='no-model'
        class Delegate:
            bank=StandIn.bank
            calls=0
            def describe(inner):return doc['observer']['identity']
            def look(inner,*a,**kw):inner.calls+=1;return {'frames':[]}
            def segmenter(inner):return 'test-only segmenter'
        delegate=Delegate();wrapped=c.CalibratedObserver(delegate,doc,self.game)
        self.assertEqual(wrapped.look({},{}),{'frames':[]})
        self.assertEqual(wrapped.segmenter(),'test-only segmenter')
        (self.game/'texture.png').write_bytes(b'changed texture')
        with self.assertRaisesRegex(NoAnswer,'stale: texture digest changed'):wrapped.look({},{})
        with self.assertRaisesRegex(NoAnswer,'stale: texture digest changed'):wrapped.segmenter()
        self.assertEqual(delegate.calls,1)

    def test_wrong_bank_and_observer_are_refused(self):
        doc=self.run_loop();doc['observer']['evidence']='no-model'
        class Delegate:
            bank={'different':True}
            def describe(inner):return doc['observer']['identity']
        with self.assertRaisesRegex(NoAnswer,'another recording or template bank'):
            c.CalibratedObserver(Delegate(),doc,self.game).describe()
        doc['observer']['identity']['model']='different'
        old=copy.deepcopy(doc);old['observer']['identity']['model']='throwaway-test-double'
        with self.assertRaisesRegex(NoAnswer,'another observer/version'):
            c.CalibratedObserver(Delegate(),old,self.game).describe()

    def test_stale_calibration_yields_needs_review_in_the_real_gate(self):
        import contextlib,io,shutil
        from agents.observations import from_trace_synthetic
        from expectrail.gate import record,verify
        from tests.test_ci_gate import make_repo,HEAD
        from tests.test_two_observers import Game
        repo=self.root/'repo';make_repo(repo,routes=('smoke',))
        game=repo/'game/platformer';shutil.copy2(self.game/'texture.png',game/'texture.png')
        doc=self.run_loop();doc['observer']['evidence']='no-model'
        class Delegate:
            bank=StandIn.bank
            def describe(inner):return doc['observer']['identity']
            def look(inner,spec,run,**kw):return from_trace_synthetic(run['trace'],run['replaySha256'])
        wrapped=c.CalibratedObserver(Delegate(),doc,game)
        def gate(suffix):
            with contextlib.redirect_stdout(io.StringIO()):
                return verify.run_gate(repo=repo,game='game/platformer',routes=['routes/smoke.json'],specs='specs',
                    out=self.root/f'out-{suffix}',work=self.root/f'work-{suffix}',
                    pr={'number':7,'headSha':HEAD,'baseSha':None},replay=Game().replay,rule=record.BOTH,visual=wrapped)
        fresh=gate('fresh');self.assertEqual(fresh['decision'],'accept',fresh['reasons'])
        (game/'texture.png').write_bytes(b'changed texture')
        stale=gate('stale');self.assertEqual(stale['decision'],'needs-review')
        self.assertTrue(any('stale: texture digest changed' in why for why in stale['reasons']),stale['reasons'])


class AdapterTest(unittest.TestCase):
    def test_recorded_adapter_has_no_live_fallback_and_proposes_from_names(self):
        from agents.calibration_observers import RecordedSam
        from expectrail.recorded import read_recording
        repo=Path(__file__).resolve().parents[1]
        adapter=RecordedSam(read_recording(repo/'docs/run-it/vision/clean.json'))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);png=root/'not-recorded.png';png.write_bytes(b'not a recorded frame')
            self.assertEqual(set(adapter.propose(root,['player/robot.webp'])),{'blue robot','player','robot'})
            with self.assertRaisesRegex(NoAnswer,'not-recorded'):adapter.detect('blue robot',{'png':png})
            self.assertEqual((adapter.client.calls,adapter.client.not_recorded),(1,1))

    def test_recorded_verification_cannot_read_a_general_sam_answer_cache(self):
        from unittest.mock import patch
        from agents.calibration_observers import RecordedSam
        from expectrail.recorded import read_recording
        repo=Path(__file__).resolve().parents[1]
        adapter=RecordedSam(read_recording(repo/'docs/run-it/vision/clean.json'))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'f00000000.png').write_bytes((repo/'tests/fixtures/recorded-renderer/recorded.png').read_bytes())
            spec={'objects':{'player':{'prompt':'blue robot'}},'assertion':{'type':'visible','object':'player'},'window':{'fromFrame':0,'toFrame':0}}
            run={'framesDir':root,'trace':{'ticks':2,'physicsTicksPerSecond':120,'rows':[]},'replaySha256':'a'*64}
            with patch('agents.sam_observations.default_cache_dir',side_effect=AssertionError('general cache must not be opened')):
                with self.assertRaisesRegex(NoAnswer,'not-recorded'):adapter.observer.look(spec,run)
        # The bound recording can be identified by the gate wrapper's public source seam.
        self.assertEqual(digest(adapter.observer.client.recording),adapter.describe()['sourceSha256'])

    def test_broken_copies_are_patches_and_original_game_bytes_do_not_change(self):
        import shutil
        from agents.calibration_copies import write_patches
        from harness.run import apply_patches
        repo=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);game=root/'game';(game/'player').mkdir(parents=True)
            for rel in ('player/player.tscn','game_singleplayer.tscn'):
                shutil.copy2(repo/'game/platformer'/rel,game/rel)
            original={str(p.relative_to(game)):p.read_bytes() for p in game.rglob('*.tscn')}
            patches=write_patches(game,root/'patches')
            self.assertEqual(set(patches),set(c.BROKEN))
            for name,path in patches.items():
                target=root/name;shutil.copytree(game,target);apply_patches(target,[path])
                self.assertTrue(any((target/p).read_bytes()!=raw for p,raw in original.items()),name)
            self.assertEqual(original,{str(p.relative_to(game)):p.read_bytes() for p in game.rglob('*.tscn')})
            with self.assertRaises(ValueError):write_patches(game,game/'patches')

    def test_example_validates_with_the_generic_registry_and_semantic_reader(self):
        from expectrail.contracts import validate_v1
        p=Path(__file__).resolve().parents[1]/'contracts/examples/observer-calibration.json'
        doc=c.read(p);self.assertEqual(validate_v1(doc),'observer-calibration')
        self.assertEqual(doc['observer']['evidence'],'stand-in')


# Importing this test module still works when either optional imaging package is absent.
from tests.test_template_sensor import needs_pixels


class PixelAdapterTest(unittest.TestCase):
    @needs_pixels
    def test_frozen_pixel_adapter_runs_the_same_loop_and_never_changes_its_bank(self):
        from PIL import Image
        from agents.calibration_observers import Template
        from tests.test_template_sensor import replay,TREE,CONFIG,ts
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);game=root/'game';game.mkdir();(game/'texture.png').write_bytes(b'test-only art binding')
            source=root/'bank-source';replay(source,count=8)
            bank=ts.calibrate(source,clean_tree=TREE,frames=[0],config=CONFIG)
            adapter=Template(bank);frozen=digest(adapter.bank)
            def frames(case):
                target=root/case
                replay(target,count=8,hidden=case in c.BROKEN and case!='shifted-off-body',
                       location=(38,20) if case=='shifted-off-body' else (24,20))
                rows=[]
                for n in range(8):
                    p=target/'frames'/f'f{n:08d}.png'
                    with Image.open(p) as raw:image=raw.copy()
                    image.putpixel((0,0),10+list(('selection','clean',*c.BROKEN)).index(case)*10+n)
                    image.save(p)
                    rows.append(dict(frame=n,png=p,expectedBox=[24,20,36,36],replaySha256='b'*64))
                return rows
            broken=[dict(name=n,patchSha256=hashlib.sha256(n.encode()).hexdigest(),frames=frames(n)) for n in c.BROKEN]
            doc=c.calibrate(adapter=adapter,candidates=adapter.propose(game,['texture.png']),selection=frames('selection'),
                            clean=frames('clean'),broken=broken,game=game,textures=['texture.png'])
            self.assertTrue(doc['enabled'],doc['why']);self.assertEqual(doc['missed'],[])
            self.assertEqual(digest(adapter.bank),frozen)


class FloorTest(unittest.TestCase):
    setUp = LoopTest.setUp
    frames = LoopTest.frames
    run_loop = LoopTest.run_loop

    def test_verification_uses_the_selected_floor_not_the_original_spec_default(self):
        doc=self.run_loop();doc['observer']['evidence']='no-model'
        class Delegate:
            bank=StandIn.bank
            def describe(inner):return doc['observer']['identity']
            def look(inner,*args,**kw):return {'frames':[{'objects':{'player':[
                {'box':[10,10,20,20],'score':0.89},{'box':[10,10,20,20],'score':0.95}]}}]}
        wrapped=c.CalibratedObserver(Delegate(),doc,self.game)
        self.assertEqual([d['score'] for d in wrapped.look({}, {})['frames'][0]['objects']['player']],[0.95])


class RecordedEvidenceTest(unittest.TestCase):
    def test_published_proofs_validate_and_sam_gaps_stay_unknown(self):
        folder=Path(__file__).resolve().parents[1]/'docs/calibration-330'
        pixel=c.read(folder/'template.json');sam=c.read(folder/'sam-recorded.json')
        self.assertTrue(pixel['enabled']);self.assertEqual(pixel['missed'],[])
        self.assertEqual(len(pixel['clean']),12)
        for variant in pixel['broken']:
            self.assertEqual(len(variant['rows']),13)
            self.assertTrue(all(c.status(row,0.949981)=='fail' for row in variant['rows']))
        self.assertEqual(sam['selected'],'blue robot');self.assertFalse(sam['enabled'])
        ambiguous=next(candidate for candidate in sam['candidates'] if candidate['prompt']=='small robot character')
        self.assertEqual(len(ambiguous['rows']),13)
        self.assertTrue(all(c.status(row,ambiguous['floor'])=='unavailable' for row in ambiguous['rows']))
        self.assertEqual(set(sam['missed']),set(c.BROKEN))

    def test_each_committed_record_traces_to_its_frozen_source_manifest(self):
        folder=Path(__file__).resolve().parents[1]/'docs/calibration-330'
        source=json.loads((folder/'source.json').read_text())
        for name,want in source['records'].items():
            with self.subTest(name=name):self.assertEqual(hashlib.sha256((folder/name).read_bytes()).hexdigest(),want)
