"""Public onboarding regressions: no NumPy/Pillow, model, network, or required engine."""
import contextlib
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
from expectrail import cli, doctor, onboarding, project_config, route
from harness import run as hr
from tests import cli_capture

ROOT=Path(__file__).resolve().parent.parent


def command(*args):
    text=io.StringIO()
    with cli_capture.command_output(text):
        code=cli.main([str(a) for a in args])
    return code,text.getvalue()


def menu_project(root):
    game=root/'game';shutil.copytree(ROOT/'tests/projects/config-lane',game)
    p=game/'project.godot';p.write_text(p.read_text().replace('res://main.tscn','res://menu.tscn'))
    (game/'menu.tscn').write_text('[gd_scene format=3]\n[node name="Menu" type="Control"]\n')
    return game


class TrialStopsTest(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name).resolve();self.game=menu_project(self.root);self.out=self.root/'routes/checked.json'

    def config(self):
        return json.loads((self.game/project_config.FILENAME).read_text())

    def intercepted(self,**kwargs):
        calls=[]
        def stop(cmd,**options):
            calls.append(cmd);raise SystemExit('intercepted replay')
        with mock.patch.object(hr,'find_godot',return_value=Path('/unused/godot')), \
             mock.patch.object(hr,'ensure_import_cache',return_value=None),mock.patch.object(hr,'godot_import'), \
             mock.patch.object(hr.box,'choose',return_value=(None,{'sandbox':False})), \
             mock.patch.object(hr.subprocess,'run',side_effect=stop):
            with self.assertRaises(SystemExit) as caught:
                hr.run(self.game/'walk.json',self.root/'replay',game=self.game,capture_frames=False,**kwargs)
        self.assertEqual(str(caught.exception),'intercepted replay')
        return calls[0][:calls[0].index('--')]

    def test_inspect_selects_configured_gameplay(self):
        code,text=command('inspect',self.game,'--json');self.assertEqual(code,0,text)
        report=json.loads(text);self.assertEqual(report['entryScene'],'res://main.tscn')
        self.assertIn('Actors/Avatar',report['players']);self.assertNotIn('res://menu.tscn',report['scenes'])

    def test_init_inspects_the_same_scene(self):
        code,text=command('init',self.game,'--dry-run');self.assertEqual(code,0,text)
        self.assertNotIn('starting scene has no unique player',text)
        self.assertEqual(json.loads(text)['config']['entryScene'],'res://main.tscn')

    def test_replay_selects_configured_scene(self):
        cmd=self.intercepted();self.assertIn('res://main.tscn',cmd);self.assertNotIn('res://menu.tscn',cmd)

    def test_base_scene_wins_over_head_config(self):
        base=self.config();(self.game/project_config.FILENAME).write_text(json.dumps(dict(base,entryScene='res://menu.tscn')))
        cmd=self.intercepted(project=base);self.assertIn('res://main.tscn',cmd);self.assertNotIn('res://menu.tscn',cmd)

    def test_missing_scene_stops_before_engine_lookup(self):
        base=self.config();(self.game/'main.tscn').unlink()
        with mock.patch.object(hr,'find_godot',side_effect=AssertionError('engine started')) as engine:
            with self.assertRaisesRegex(SystemExit,'entryScene.*main.tscn'):
                hr.run(self.game/'walk.json',self.root/'replay',game=self.game,project=base)
        engine.assert_not_called()

    def test_unconfigured_replay_retains_implicit_main_scene(self):
        (self.game/project_config.FILENAME).unlink()
        self.assertFalse(any(a.startswith('res://') for a in self.intercepted()))

    def test_inspect_init_and_route_refuse_csharp_or_csproj(self):
        for name in ['Spaceship.csproj','Controller.cs']:
            p=self.game/name;p.write_text('C# project marker')
            try:
                for args in [('inspect',self.game),('init',self.game,'--dry-run'),
                             ('route','--project',self.game,'--auto','--out',self.out)]:
                    with self.subTest(name=name,args=args),mock.patch.object(hr,'run',side_effect=AssertionError('replay started')):
                        code,text=command(*args);self.assertEqual(code,5,text)
                        self.assertIn(name,text);self.assertIn('only GDScript projects are supported',text)
            finally:p.unlink()
        self.assertFalse(self.out.exists())

    def test_dotnet_metadata_is_refused_without_a_cs_file(self):
        p=self.game/'project.godot';original=p.read_text()
        for added in ['\n[dotnet]\nproject/assembly_name="Ship"\n',
                      '\n[application]\nconfig/features=PackedStringArray("4.1", "C#")\n']:
            with self.subTest(added=added):
                p.write_text(original+added);code,text=command('inspect',self.game)
                self.assertEqual(code,5,text);self.assertIn('only GDScript projects are supported',text)
        p.write_text(original);c=self.config();c['toolchain']={'engine':'godot','version':'4.1-mono'}
        (self.game/project_config.FILENAME).write_text(json.dumps(c))
        code,text=command('inspect',self.game);self.assertEqual(code,5,text);self.assertIn('toolchain',text)

    def test_csharp_scene_reference_is_refused_even_when_script_is_missing(self):
        p=self.game/'main.tscn'
        p.write_text(p.read_text()+'\n[ext_resource type="Script" path="res://Missing.cs" id="csharp"]\n')
        code,text=command('inspect',self.game)
        self.assertEqual(code,5,text);self.assertIn('Missing.cs',text)
        self.assertIn('only GDScript projects are supported',text)

    def test_generated_cache_and_comments_do_not_refuse_gdscript(self):
        (self.game/'.godot').mkdir();(self.game/'.godot/Generated.cs').write_text('unused')
        p=self.game/'project.godot';p.write_text(p.read_text()+'\n; .NET C# project/assembly_name="unused"\n')
        code,text=command('inspect',self.game);self.assertEqual(code,0,text)

    def test_doctor_refuses_before_probe_or_download(self):
        (self.game/'Spaceship.csproj').write_text('<Project/>')
        with mock.patch.object(doctor,'godot',side_effect=AssertionError('engine probed')) as engine:
            code,text=command('doctor','--project',self.game,'--json')
        self.assertEqual(code,3,text);engine.assert_not_called()
        doc=json.loads(text);self.assertEqual(doctor.problems(doc),[]);self.assertFalse(doc['ok'])
        item=next(c for c in doc['checks'] if c['id']=='project-language')
        self.assertTrue(item['required']);self.assertIn('Spaceship.csproj',item['found'])
        self.assertIn('only GDScript projects are supported',item['found']);self.assertTrue(item['fix'])

    def test_doctor_finds_current_project_without_config(self):
        (self.game/project_config.FILENAME).unlink();(self.game/'Ship.csproj').write_text('<Project/>')
        old=Path.cwd()
        try:
            os.chdir(self.game)
            with mock.patch.object(doctor,'godot',side_effect=AssertionError('engine probed')):
                code,text=command('doctor','--no-fetch')
        finally:os.chdir(old)
        self.assertEqual(code,3,text);self.assertIn('Ship.csproj',text)

    def test_direct_replay_refuses_before_engine_lookup(self):
        (self.game/'Ship.csproj').write_text('<Project/>')
        with mock.patch.object(hr,'find_godot',side_effect=AssertionError('engine started')) as engine:
            with self.assertRaisesRegex(SystemExit,'Ship.csproj'):
                hr.run(self.game/'walk.json',self.root/'replay',game=self.game)
        engine.assert_not_called()

    def test_auto_route_keeps_log_and_reports_its_real_path(self):
        old=[]
        def failed(candidate,out,**kw):
            out.mkdir();p=out/'godot.log';p.write_text('specific engine failure\n');old.append(p)
            raise SystemExit(f'engine stopped; see {p}')
        with mock.patch.object(hr,'run',side_effect=failed):
            code,text=command('route','--project',self.game,'--auto','--out',self.out)
        self.assertEqual(code,5,text);self.assertFalse(self.out.exists())
        logs=list(self.out.parent.glob('checked.json.failed-*/1/godot.log'))
        self.assertEqual(len(logs),1,text);self.assertEqual(logs[0].read_text(),'specific engine failure\n')
        self.assertIn(str(logs[0]),text);self.assertNotIn(str(old[0]),text);self.assertFalse(old[0].exists())

    def test_failure_without_log_still_retains_a_diagnostic(self):
        with mock.patch.object(hr,'run',side_effect=SystemExit('engine stopped before logging')):
            code,text=command('route','--project',self.game,'--auto','--out',self.out)
        self.assertEqual(code,5,text);files=list(self.out.parent.glob('checked.json.failed-*/failure.txt'))
        self.assertEqual(len(files),1,text);self.assertIn('engine stopped before logging',files[0].read_text())
        self.assertIn(str(files[0]),text)

    def test_failure_log_cannot_copy_a_symlink_target(self):
        outside=self.root/'unrelated.txt';outside.write_text('unrelated private content')
        def failed(candidate,out,**kw):
            out.mkdir();(out/'godot.log').symlink_to(outside)
            raise SystemExit(f'engine stopped; see {out / "godot.log"}')
        with mock.patch.object(hr,'run',side_effect=failed):
            code,text=command('route','--project',self.game,'--auto','--out',self.out)
        self.assertEqual(code,5,text)
        log=next(self.out.parent.glob('checked.json.failed-*/1/godot.log'))
        self.assertIn('could not be retained',log.read_text())
        self.assertNotIn(outside.read_text(),log.read_text())
        self.assertIn(str(log),text)

    def test_binary_entry_scene_is_refused_consistently(self):
        (self.game/'packed.scn').write_bytes(b'not a text scene')
        c=self.config();c['entryScene']='res://packed.scn'
        (self.game/project_config.FILENAME).write_text(json.dumps(c))
        for args in [('inspect',self.game),('init',self.game,'--dry-run'),
                     ('route','--project',self.game,'--auto','--out',self.out)]:
            with self.subTest(args=args):
                code,text=command(*args);self.assertEqual(code,5,text)
                self.assertIn('.tscn',text)
        with mock.patch.object(hr,'find_godot',side_effect=AssertionError('engine started')):
            with self.assertRaisesRegex(SystemExit,'.tscn'):
                hr.run(self.game/'walk.json',self.root/'replay',game=self.game)

    def test_module_loads_without_numpy_or_pillow(self):
        script='''import importlib.abc,sys
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,name,*args):
  if name.split('.')[0] in {'numpy','PIL'}: raise ImportError('blocked '+name)
sys.meta_path.insert(0,Block())
import tests.test_trial_stops
'''
        p=subprocess.run([sys.executable,'-c',script],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)


class RealSceneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.tool_requirements import godot_binary
        cls.godot=godot_binary()

    def test_gameplay_scene_moves_and_replays_identically_three_times(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);game=menu_project(root);out=root/'route.json';traces=[]
            def replay(candidate,dest,**kwargs):
                result=hr.run(candidate,dest,godot=self.godot,sandbox='off',**kwargs)
                traces.append(json.loads((dest/'trace.json').read_text()));return result
            with contextlib.redirect_stdout(io.StringIO()) as output:code=route.auto_route(game,out,replay=replay)
            self.assertEqual(code,0,output.getvalue());self.assertTrue(out.is_file());self.assertEqual(len(traces),3)
            self.assertEqual(traces[0],traces[1]);self.assertEqual(traces[1],traces[2])
            self.assertGreater(len({tuple(r['player']) for r in traces[0]['rows'] if 'player' in r}),1)
            self.assertEqual(onboarding.inspect(game)['entryScene'],'res://main.tscn')
