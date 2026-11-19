"""Engine menu evidence and pointer planning; no image packages or live providers."""
import contextlib
import copy
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
from expectrail import onboarding, route
from harness import run as hr

ROOT=Path(__file__).resolve().parent.parent

def report():
 return {'tick':9,'viewport':[320,180],'paused':True,'truncated':False,'buttons':[
  {'path':'Menu/Start','text':'Start','box':[40,10,120,50],'visible':True,'enabled':True,
   'connections':[{'signal':'pressed','target':'Player','method':'start_play'}]}]}


class PlanTest(unittest.TestCase):
 def test_inspect_reports_pointer_script_and_menu_without_running_game(self):
  with mock.patch.object(hr,'run',side_effect=AssertionError('game ran')):
   info=onboarding.inspect(ROOT/'tests/projects/pointer-menu')
  self.assertTrue(info['inputHints']['pointer'])
  self.assertEqual(info['inputHints']['startControls'],['Menu/Start'])

 def test_init_uses_measured_button_and_sweeps_without_pause(self):
  from expectrail import input_discovery as d
  info=onboarding.inspect(ROOT/'tests/projects/pointer-menu')
  with mock.patch.object(d,'probe',return_value=report()) as probe:
   doc=onboarding.proposal(ROOT/'tests/projects/pointer-menu',info)['route']
  probe.assert_called_once()
  clicks=[e for e in doc['events'] if e.get('pointer',{}).get('button')=='left']
  self.assertEqual([e['pointer']['pressed'] for e in clicks],[True,False])
  self.assertEqual(clicks[0]['pointer']['position'],[80,30])
  self.assertGreater(len({tuple(e['pointer']['position']) for e in doc['events'] if 'pointer' in e}),50)
  self.assertFalse(any(e.get('action')=='pause' for e in doc['events']))

 def test_ambiguous_unconnected_disabled_and_truncated_menu_refuse(self):
  from expectrail import input_discovery as d
  variants=[]
  p=report();p['buttons'].append(dict(p['buttons'][0],path='Menu/OtherStart'));variants.append(p)
  p=report();p['buttons'][0]['connections']=[];variants.append(p)
  p=report();p['buttons'][0]['enabled']=False;variants.append(p)
  p=report();p['truncated']=True;variants.append(p)
  p=report();p['buttons'][0]['connections'][0]['method']='quit_game';variants.append(p)
  for p in variants:
   with self.subTest(p=p),self.assertRaisesRegex(ValueError,'cannot tell.*Menu/Start'):
    d.choose_start(p,menu_expected=True)

 def test_hidden_menu_is_not_clicked_when_game_is_already_running(self):
  from expectrail import input_discovery as d
  p=report();p['paused']=False;p['buttons'][0]['visible']=False
  self.assertIsNone(d.choose_start(p,menu_expected=True))

 def test_pause_only_is_refused_and_names_actions_and_found_controls(self):
  from expectrail import input_discovery as d
  info=onboarding.inspect(ROOT/'tests/projects/pointer-menu')
  info.update(actions=['pause'],builtInActions=False,inputHints={'pointer':[],'startControls':[],'menus':[]})
  p=report();p['buttons']=[];p['paused']=False
  with mock.patch.object(d,'probe',return_value=p),self.assertRaisesRegex(ValueError,'pause.*no.*control'):
   d.plan(ROOT/'tests/projects/pointer-menu',info)

 def test_pointer_mentions_in_comments_or_strings_are_not_evidence(self):
  from expectrail import input_discovery as d
  self.assertFalse(d.pointer_reads('# get_mouse_position()\nvar s="get_global_mouse_position()"\n'))
  self.assertTrue(d.pointer_reads('var x=get_viewport().get_mouse_position().x # steering\n'))

 def test_legacy_action_plan_is_byte_equivalent_without_engine_probe(self):
  from expectrail import input_discovery as d
  info=onboarding.inspect(ROOT/'game/platformer')
  with mock.patch.object(d,'probe',side_effect=AssertionError('unneeded probe')):
   doc=d.plan(ROOT/'game/platformer',info)
  self.assertEqual(doc,route.make_route(info['actions'],info['physicsTicksPerSecond']))

 def test_normal_replays_do_not_request_probe(self):
  source=(ROOT/'harness/run.py').read_text()
  self.assertIn('input_probe: bool = False',source)

 def test_pending_pointer_review_does_not_run_the_game(self):
  from expectrail import input_discovery as d, onboard
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'game';shutil.copytree(ROOT/'tests/projects/pointer-menu',root)
   info=onboarding.inspect(root)
   with mock.patch.object(d,'probe',return_value=report()):
    docs=onboarding.proposal(root,info);name=onboarding.publish(root,docs,False)
   with mock.patch.object(d,'probe',side_effect=AssertionError('game executed by offline review')):
    page=onboard.render(root,name)
   self.assertIn('pointer left',page)

 def test_probe_failure_log_is_retained(self):
  from expectrail import input_discovery as d
  kept=[]
  def fail(candidate,out,**kw):
   out.mkdir();(out/'godot.log').write_text('specific probe failure')
   kept.append(out.parent);raise SystemExit('specific probe failure')
  try:
   with self.assertRaisesRegex(ValueError,'diagnostics kept'):
    d.probe(ROOT/'tests/projects/pointer-menu',{},replay=fail)
   self.assertEqual((kept[0]/'replay/godot.log').read_text(),'specific probe failure')
  finally:
   for p in kept:shutil.rmtree(p)

 def test_init_cli_refuses_ambiguity_without_writing_a_draft(self):
  from expectrail import input_discovery as d, cli
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'game';shutil.copytree(ROOT/'tests/projects/pointer-menu',root)
   p=report();p['buttons'].append(dict(p['buttons'][0],path='Menu/OtherStart'))
   with mock.patch.object(d,'probe',return_value=p),contextlib.redirect_stderr(io.StringIO()) as err:
    code=cli.main(['init',str(root)])
   self.assertEqual(code,5);self.assertIn('cannot tell',err.getvalue())
   self.assertFalse(list(root.glob('expectrail.project*.json')))

 def test_unmoved_pointer_replay_is_not_published(self):
  from expectrail import input_discovery as d
  def replay(candidate,out,**kwargs):
   doc=json.loads(candidate.read_text());out.mkdir()
   trace={'format':'expectrail.trace/v0','ticks':doc['ticks'],'physicsTicksPerSecond':60,
          'rows':[{'tick':i,'player':[160,150]} for i in range(doc['ticks'])]}
   (out/'trace.json').write_text(json.dumps(trace));return {'game':{'tree':'same'}}
  with tempfile.TemporaryDirectory() as tmp,mock.patch.object(d,'probe',return_value=report()):
   out=Path(tmp)/'new.json'
   with contextlib.redirect_stdout(io.StringIO()) as text:code=route.auto_route(ROOT/'tests/projects/pointer-menu',out,replay=replay)
   self.assertEqual(code,2);self.assertFalse(out.exists());self.assertIn('did not demonstrate',text.getvalue())

 def test_module_loads_without_numpy_or_pillow(self):
  script='''import importlib.abc,sys
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,name,*args):
  if name.split('.')[0] in {'numpy','PIL'}: raise ImportError(name)
sys.meta_path.insert(0,Block())
import tests.test_menu_routes
'''
  p=subprocess.run([sys.executable,'-c',script],cwd=ROOT,capture_output=True,text=True)
  self.assertEqual(p.returncode,0,p.stderr)


class RealMenuTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from tests.tool_requirements import godot_binary
  cls.godot=godot_binary()

 def test_probe_measures_menu_then_auto_route_moves_three_identical_times(self):
  from expectrail import input_discovery as d
  root=ROOT/'tests/projects/pointer-menu';traces=[]
  def replay(candidate,out,**kwargs):
   result=hr.run(candidate,out,godot=self.godot,sandbox='off',**kwargs)
   traces.append((out/'trace.json').read_bytes());return result
  with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ,EXPECTRAIL_GODOT=str(self.godot)):
   p=d.probe(root,onboarding.inspect(root));self.assertEqual(p['buttons'][0]['box'],[40,10,120,50])
   self.assertEqual(p['buttons'][0]['connections'][0]['method'],'start_play')
   out=Path(tmp)/'route.json'
   with contextlib.redirect_stdout(io.StringIO()) as output:code=route.auto_route(root,out,replay=replay)
   self.assertEqual(code,0,output.getvalue());self.assertTrue(out.exists())
  self.assertEqual(len(traces),3);self.assertEqual(traces[0],traces[1]);self.assertEqual(traces[1],traces[2])
  rows=json.loads(traces[0])['rows'];self.assertGreater(len({tuple(r['player']) for r in rows}),40)
  self.assertNotIn('inputProbe',json.loads(traces[0]))

 def test_pointer_only_project_generates_a_replayable_sweep(self):
  from expectrail import input_discovery as d
  root=ROOT/'tests/projects/pointer-paddle';traces=[]
  def replay(candidate,out,**kwargs):
   result=hr.run(candidate,out,godot=self.godot,sandbox='off',**kwargs)
   traces.append((out/'trace.json').read_bytes());return result
  with tempfile.TemporaryDirectory() as tmp,mock.patch.dict(os.environ,EXPECTRAIL_GODOT=str(self.godot)):
   with contextlib.redirect_stdout(io.StringIO()) as output:
    code=route.auto_route(root,Path(tmp)/'route.json',replay=replay)
   self.assertEqual(code,0,output.getvalue())
  self.assertEqual(traces[0],traces[1]);self.assertEqual(traces[1],traces[2])
  self.assertGreater(len({tuple(r['player']) for r in json.loads(traces[0])['rows']}),40)


 def test_init_cli_writes_a_starting_pointer_draft(self):
  from expectrail import cli
  with tempfile.TemporaryDirectory() as tmp,mock.patch.dict(os.environ,EXPECTRAIL_GODOT=str(self.godot)):
   root=Path(tmp)/'game';shutil.copytree(ROOT/'tests/projects/pointer-menu',root)
   with contextlib.redirect_stdout(io.StringIO()) as text:code=cli.main(['init',str(root)])
   self.assertEqual(code,0,text.getvalue())
   pending=json.loads((root/'expectrail.project.draft.json').read_text());self.assertTrue(pending['draft'])
   candidate=root/pending['config']['routes'][0]
   replay=hr.run(candidate,Path(tmp)/'replay',game=root,godot=self.godot,capture_frames=False,sandbox='off')
   rows=json.loads((Path(tmp)/'replay/trace.json').read_text())['rows']
   self.assertGreater(len({tuple(row['player']) for row in rows}),40)


if __name__=='__main__':unittest.main()
