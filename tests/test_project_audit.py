"""Audit regressions: fail closed on bad setup; exercise a distinct configured Godot project."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from expectrail import cli, onboarding, project_config
from harness import run as hr

ROOT = Path(__file__).resolve().parent.parent
GAME = ROOT / 'tests/projects/config-lane'


def command(*args):
    output=io.StringIO()
    with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
        code=cli.main([str(a) for a in args])
    return code,output.getvalue()


class ConfigPresenceTest(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)

    def test_directory_config_is_not_absent(self):
        (self.root/project_config.FILENAME).mkdir()
        with self.assertRaisesRegex(project_config.ProjectConfigError,'expectrail.project.json.*regular file'):
            project_config.read_game(self.root)

    def test_broken_link_config_is_not_absent(self):
        (self.root/project_config.FILENAME).symlink_to(self.root/'missing')
        with self.assertRaisesRegex(project_config.ProjectConfigError,'expectrail.project.json.*regular file'):
            project_config.read_game(self.root)

    def test_absent_config_keeps_the_legacy_path(self):
        self.assertIsNone(project_config.read_game(self.root))

    def test_link_to_a_config_is_a_named_error_not_an_implicit_default(self):
        (self.root/'other.json').write_text('{}')
        (self.root/project_config.FILENAME).symlink_to(self.root/'other.json')
        with self.assertRaisesRegex(project_config.ProjectConfigError, 'regular file.*link'):
            project_config.read_game(self.root)


class SceneDiagnosticTest(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.game=Path(tmp.name)/'game';shutil.copytree(GAME,self.game)

    def test_unresolved_scene_instance_names_scene_reference_and_fix(self):
        path=self.game/'main.tscn'
        path.write_text(path.read_text()+'\n[node name="Child" parent="." instance=ExtResource("missing")]\n')
        code,text=command('init','--project',self.game,'--dry-run')
        self.assertEqual(code,5,text)
        for word in ('main.tscn','missing','reference','Fix'):
            self.assertIn(word,text)
        self.assertFalse((self.game/'expectrail.project.draft.json').exists())

    def test_missing_resource_path_names_field_and_fix(self):
        path=self.game/'main.tscn'
        path.write_text(path.read_text().replace(' path="res://square.svg"',''))
        code,text=command('inspect','--project',self.game)
        self.assertEqual(code,5,text)
        for word in ('main.tscn','ext_resource','path','Fix'):
            self.assertIn(word,text)

    def test_malformed_scene_headers_name_the_resource_or_node_and_fix(self):
        path = self.game/'main.tscn'
        original = path.read_text()
        cases = [
            (original.replace(' id="art"', ''), 'ext_resource', 'id'),
            (original.replace('id="art"', 'id="motion"'), 'ext_resource', 'duplicate'),
            (original.replace('id="floor"', 'id="body"'), 'sub_resource', 'duplicate'),
            (original.replace(' name="Actors"', ''), 'node', 'name'),
        ]
        for content, kind, problem in cases:
            with self.subTest(kind=kind, problem=problem):
                path.write_text(content)
                code, text = command('inspect', '--project', self.game)
                self.assertEqual(code, 5, text)
                for word in ('main.tscn', kind, problem, 'Fix'):
                    self.assertIn(word, text)

    def test_dry_run_resolves_a_nonstandard_name_and_keeps_both_similar_sprites(self):
        before={p.name:p.read_bytes() for p in self.game.iterdir() if p.is_file()}
        code,text=command('init','--project',self.game,'--dry-run')
        self.assertEqual(code,0,text);doc=json.loads(text)
        self.assertEqual(doc['config']['bindings']['player'],{'node':'Actors/Avatar','texture':'res://square.svg'})
        self.assertEqual(doc['config']['viewport'],[360,240]);self.assertTrue(doc['config']['draft'])
        self.assertNotIn('approval',json.dumps(doc));self.assertNotIn('approvedContracts',doc['config'])
        nodes,_=onboarding.scene_nodes(self.game,'res://main.tscn')
        self.assertEqual(nodes['Actors/Avatar/Art']['images'],nodes['Lookalike']['images'])
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.game.iterdir() if p.is_file()})


class RealBindingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.tool_requirements import godot_binary
        cls.engine=godot_binary()

    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix='expectrail-binding-audit-');self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.game=self.root/'game';shutil.copytree(GAME,self.game)

    def config(self,binding):
        path=self.game/project_config.FILENAME;doc=json.loads(path.read_text())
        doc['bindings']['player']={'texture':'res://square.svg',**binding};path.write_text(json.dumps(doc))

    def replay(self,name='run'):
        return hr.run(self.game/'walk.json',self.root/name,game=self.game,godot=self.engine,
                      capture_frames=False,sandbox='off',fps=None)

    def test_ambiguous_short_node_refuses_instead_of_picking_first(self):
        scene=self.game/'main.tscn'
        scene.write_text(scene.read_text()+'\n[node name="Other" type="Node2D" parent="."]\n'
                         '[node name="Avatar" type="Node2D" parent="Other"]\n')
        self.config({'node':'Avatar'})
        with self.assertRaises(SystemExit):self.replay()
        log=(self.root/'run/godot.log').read_text()
        for word in ('Avatar','2','ambiguous','full node path'):self.assertIn(word,log)
        self.assertFalse((self.root/'run/trace.json').exists())

    def test_nonspatial_player_node_is_a_named_setup_error(self):
        self.config({'node':'NotSpatial'})
        with self.assertRaises(SystemExit):self.replay()
        log=(self.root/'run/godot.log').read_text()
        self.assertIn('NotSpatial',log);self.assertIn('Node2D',log);self.assertIn('bindings.player',log)
        self.assertFalse((self.root/'run/trace.json').exists())

    def test_full_node_path_and_unique_group_track_the_same_moving_body_and_camera(self):
        traces=[]
        for name,binding in [('path',{'node':'Actors/Avatar'}),('group',{'group':'controlled'})]:
            self.config(binding);record=self.replay(name)
            trace=json.loads((self.root/name/'trace.json').read_text());rows=trace['rows'];traces.append(rows)
            self.assertEqual(len(rows),120);self.assertEqual(trace['physicsTicksPerSecond'],60)
            self.assertEqual(record['capture']['fps'],60)
            self.assertGreater(rows[-1]['player'][0]-rows[0]['player'][0],200)
            self.assertGreater(len({tuple(r['view']) for r in rows}),10)
            self.assertTrue(all(r['playerVisible'] for r in rows))
            self.assertTrue(all(abs(r['body'][2]-r['body'][0]-24)<.01 for r in rows))
            self.assertTrue(all(abs(r['body'][3]-r['body'][1]-24)<.01 for r in rows))
        self.assertEqual(traces[0],traces[1])

    def test_missing_player_and_ambiguous_group_are_setup_errors(self):
        for name,binding,needle in [('missing',{'node':'Absent'},'Absent'),('group',{'group':'controlled'},'controlled')]:
            if name=='group':
                scene=self.game/'main.tscn'
                scene.write_text(scene.read_text()+'\n[node name="Other" type="Node2D" parent="." groups=["controlled"]]\n')
            self.config(binding)
            with self.assertRaises(SystemExit):self.replay(name)
            self.assertIn(needle,(self.root/name/'godot.log').read_text())
            self.assertFalse((self.root/name/'trace.json').exists())


class SelectedVisionPolicyTest(unittest.TestCase):
    """Reuse saved stand-in captures; never start a game or make a model client."""

    def setUp(self):
        from tests.test_outside_vision import CaptureJudgeTest
        CaptureJudgeTest.setUp(self)

    def test_saved_vision_judges_the_selected_check_not_the_bundled_default(self):
        from tools import outside_trial as trial, outside_vision as vision
        self.project['spec'] = 'tests/outside/specs/dodge-play-area.json'
        selected = trial.project_spec(self.project).read_bytes()
        gate = vision.verify.run_gate
        seen = []

        def judge(**kwargs):
            files = list((kwargs['repo'] / 'specs').iterdir())
            self.assertEqual(len(files), 1)
            seen.append(files[0].read_bytes())
            return gate(**kwargs)

        with mock.patch.object(vision.verify, 'run_gate', side_effect=judge), \
                mock.patch('subprocess.Popen', side_effect=AssertionError('judge started a process')):
            rows = vision.judge(self.project, self.data, self.receipt, self.out, self.model.observer())
        self.assertEqual(seen, [selected] * 3)
        self.assertEqual(len(rows), 3)
        for variant in ('pinned', 'broken', 'harmless'):
            found = json.loads((self.out / variant / 'findings.json').read_text())
            self.assertEqual([c['spec'] for c in found['checks']], ['dodge-play-area'])
            # This is a short stand-in route, not evidence for the real Dodge window.
            self.assertNotEqual(found['decision'], 'accept')

    def test_invalid_selected_check_refuses_before_calibration_or_any_model(self):
        from tools import outside_trial as trial, outside_vision as vision
        self.project['spec'] = '../not-a-trusted-check.json'
        with mock.patch.object(vision, 'anchored', side_effect=AssertionError('calibration was asked')):
            with self.assertRaises(trial.TrialError):
                vision.judge(self.project, self.data, self.receipt, self.out)
