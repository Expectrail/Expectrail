"""Pointer route contract/readers and real Godot input delivery. No image/model imports."""
import copy
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from expectrail import contracts, onboard, route
from expectrail.repro.reach import used_together
from expectrail.trace.normalize import normalize
from harness import run as hr
from harness.unity import run as unity

ROOT = Path(__file__).resolve().parent.parent

def pointer_route():
    return {'format':'expectrail.route/v0','name':'pointer-menu-paddle','ticks':18,'seed':1,
            'events':[{'tick':2,'pointer':{'position':[80,30]}},
                      {'tick':3,'pointer':{'position':[80,30],'button':'left','pressed':True}},
                      {'tick':4,'pointer':{'position':[80,30],'button':'left','pressed':False}},
                      {'tick':6,'pointer':{'position':[40,120]}},
                      {'tick':10,'pointer':{'position':[260,120]}},
                      {'tick':12,'pointer':{'position':[200,120],'button':'right','pressed':True}},
                      {'tick':13,'pointer':{'position':[180,120]}},
                      {'tick':14,'pointer':{'position':[180,120],'button':'right','pressed':False}}]}


class PointerReadersTest(unittest.TestCase):
    def test_contract_accepts_pointer_and_legacy_actions_together(self):
        doc=pointer_route();doc['events'].append({'tick':0,'action':'move_right','pressed':True})
        self.assertEqual(contracts.validate(doc,'route'),'route')

    def test_closed_event_shapes_refuse_ambiguous_or_invalid_inputs(self):
        bad=[{'position':[1,2],'button':'left'}, {'position':[1,2],'pressed':True},
             {'position':[1]}, {'position':[True,2]}, {'position':[-1,2]},
             {'position':[1,2,3]}, {'position':[1,2],'button':'wheel','pressed':True},
             {'position':[1,2],'button':'left','pressed':1}, {'position':[1,2],'world':True}]
        for value in bad:
            with self.subTest(value=value),self.assertRaises(contracts.ContractError):
                doc=pointer_route();doc['events']=[{'tick':1,'pointer':value}];contracts.validate(doc,'route')
        doc=pointer_route();doc['events'][0].update(action='shoot',pressed=True)
        with self.assertRaises(contracts.ContractError):contracts.validate(doc,'route')

    def test_description_names_pointer_positions_and_button_edges(self):
        lines='\n'.join(route.describe(pointer_route(),60,{'rows':[{'player':[0,0]},{'player':[20,0]}]}))
        self.assertIn('viewport',lines);self.assertIn('80',lines)
        self.assertIn('left down',lines);self.assertIn('left up',lines);self.assertIn('tick 3',lines)
        self.assertIn('moved during',lines)

    def test_normalized_episode_keeps_every_pointer_event(self):
        doc=pointer_route();trace={'physicsTicksPerSecond':60,'rows':[{'tick':i,'player':[i,0]} for i in range(18)]}
        episode=normalize(trace,doc,episode_id='pointer')
        self.assertEqual(episode['inputs'],doc['events'])
        self.assertEqual(contracts.validate_v1(episode),'episode')
        episode['inputs'][0]['pointer']['position'][0]=999
        self.assertEqual(doc['events'][0]['pointer']['position'][0],80)

    def test_action_trigger_does_not_treat_pointer_click_as_shoot(self):
        from tests.test_trace_evaluator import episode, rows, spec
        from expectrail.trace.evaluator import evaluate
        op={'type':'event_response','trigger':{'action':'shoot','pressed':True},
            'response':'projectile_spawn','withinSeconds':0.1,'refractorySeconds':0.1}
        ep=episode(rows(30),inputs=pointer_route()['events'])
        verdict=evaluate(spec(op),ep)
        self.assertEqual(verdict['result'],'not_exercised')

    def test_action_pair_reader_preserves_legacy_pairs(self):
        doc=pointer_route();doc['events'] += [{'tick':5,'action':'move_right','pressed':True},
                                             {'tick':6,'action':'shoot','pressed':True}]
        self.assertEqual(used_together(doc),{frozenset(('move_right','shoot'))})

    def test_review_page_names_pointer_inputs(self):
        raw=(json.dumps(pointer_route(),indent=2)+'\n').encode();name='routes/draft-first-'+hashlib.sha256(raw).hexdigest()[:16]+'.json'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'routes').mkdir();(root/name).write_bytes(raw)
            filename,inputs=onboard.inputs(root,{'routes':[name]})
        self.assertEqual(filename,name);self.assertTrue(any('pointer' in s for s in inputs))
        self.assertTrue(any('left' in s for s in inputs))

    def test_unity_refuses_pointer_explicitly(self):
        with self.assertRaisesRegex(SystemExit,'Unity.*pointer'):
            unity.check_route(pointer_route(),{'actions':[]})

    def test_action_catalog_ingestion_refuses_pointer_in_plain_words(self):
        from expectrail.jit import run as jit
        with mock.patch.object(jit.offer_mod,'library',return_value=[]):
            with self.assertRaisesRegex(jit.NothingGenerated,'pointer.*trusted action catalog'):
                jit._pipeline({'actions':['move_right']},'',b'',None,[],None,None,None,None,
                              None,None,1,1,[],{},[],None,report_route=pointer_route())

    def test_playtest_heuristics_ignore_pointer_as_action_hold(self):
        from tools.playtester.producer import anomalies
        doc=pointer_route();trace={'rows':[{'tick':i,'player':[20,30],'facing':1} for i in range(18)]}
        self.assertEqual(anomalies(doc,trace),[])

    def test_invalid_pointer_is_refused_before_engine_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'route.json';doc=pointer_route();doc['events'][0]['pointer']['position'][0]=float('nan')
            p.write_text(json.dumps(doc))
            with mock.patch.object(hr,'find_godot',side_effect=AssertionError('engine started')) as engine:
                with self.assertRaisesRegex(SystemExit,'invalid pointer route'):
                    hr.run(p,root/'out',game=ROOT/'tests/projects/pointer-menu',capture_frames=False)
            engine.assert_not_called()

    def test_pointer_tick_outside_route_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'route.json';doc=pointer_route();doc['events'][0]['tick']=doc['ticks'];p.write_text(json.dumps(doc))
            with mock.patch.object(hr,'find_godot',side_effect=AssertionError('engine started')):
                with self.assertRaisesRegex(SystemExit,'outside.*ticks'):
                    hr.run(p,root/'out',game=ROOT/'tests/projects/pointer-menu',capture_frames=False)

    def test_test_module_loads_without_numpy_or_pillow(self):
        script='''import importlib.abc,sys
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,name,*args):
  if name.split('.')[0] in {'numpy','PIL'}: raise ImportError('blocked '+name)
sys.meta_path.insert(0,Block())
import tests.test_pointer_routes
'''
        p=subprocess.run([sys.executable,'-c',script],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)


class RealPointerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.tool_requirements import godot_binary
        cls.godot=godot_binary()

    def replay(self,root,doc,name):
        contracts.validate(doc,'route')
        p=root/(name+'.json');p.write_text(json.dumps(doc))
        out=root/name
        hr.run(p,out,game=ROOT/'tests/projects/pointer-menu',godot=self.godot,capture_frames=getattr(self,'drawn',False),sandbox='off')
        raw=(out/'trace.json').read_bytes();shutil.rmtree(out/'work')
        return raw,json.loads(raw)

    def test_click_starts_menu_and_pointer_steers_three_identical_replays(self):
        with tempfile.TemporaryDirectory() as tmp:
            values=[self.replay(Path(tmp),pointer_route(),f'run-{i}') for i in range(3)]
        self.assertEqual(values[0][0],values[1][0]);self.assertEqual(values[1][0],values[2][0])
        rows=values[0][1]['rows']
        self.assertEqual(rows[2]['player'],[160,150])
        self.assertEqual(rows[4]['player'],[80,120])
        self.assertEqual(rows[6]['player'],[40,120]);self.assertEqual(rows[9]['player'],[40,120])
        self.assertEqual(rows[10]['player'],[260,120])
        self.assertEqual(rows[12]['player'],[200,130]);self.assertEqual(rows[13]['player'],[180,130])
        self.assertEqual(rows[14]['player'],[180,120]);self.assertEqual(rows[-1]['player'],[180,120])

    def test_same_tick_move_and_button_edges_keep_array_order(self):
        doc=pointer_route();doc['events'][:3]=[
            {'tick':3,'pointer':{'position':[80,30]}},
            {'tick':3,'pointer':{'position':[80,30],'button':'left','pressed':True}},
            {'tick':3,'pointer':{'position':[80,30],'button':'left','pressed':False}}]
        with tempfile.TemporaryDirectory() as tmp:_,trace=self.replay(Path(tmp),doc,'same-tick')
        self.assertEqual(trace['rows'][3]['player'],[80,120]);self.assertEqual(trace['rows'][6]['player'],[40,120])

    def test_outside_viewport_refuses_instead_of_clamping_or_clicking_elsewhere(self):
        doc=pointer_route();doc['events'][0]['pointer']['position']=[900,30]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):self.replay(Path(tmp),doc,'outside')
            log=(Path(tmp)/'outside/godot.log').read_text()
            self.assertIn('outside the game viewport',log)


class RealDrawnPointerTest(unittest.TestCase):
    drawn = True

    @classmethod
    def setUpClass(cls):
        from tests.tool_requirements import godot_binary, display_problem
        cls.godot=godot_binary()
        reason=display_problem()
        if reason:raise unittest.SkipTest(reason)

    def test_scaled_window_queries_and_button_input_replay_identically_three_times(self):
        with tempfile.TemporaryDirectory() as tmp:
            values=[RealPointerTest.replay(self,Path(tmp),pointer_route(),f'drawn-{i}') for i in range(3)]
        self.assertEqual(values[0][0],values[1][0]);self.assertEqual(values[1][0],values[2][0])
        rows=values[0][1]['rows']
        self.assertEqual(rows[2]['player'],[160,150]);self.assertEqual(rows[4]['player'],[80,120])
        self.assertEqual(rows[6]['player'],[40,120]);self.assertEqual(rows[9]['player'],[40,120])
        self.assertEqual(rows[10]['player'],[260,120])
        self.assertEqual(rows[12]['player'],[200,130]);self.assertEqual(rows[13]['player'],[180,130])
        self.assertEqual(rows[14]['player'],[180,120])


if __name__=='__main__':unittest.main()
