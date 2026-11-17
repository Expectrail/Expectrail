"""Unity's host-owned replay boundary; unit transports only, no Editor or model."""
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest import mock

from expectrail.contracts import ContractError, validate
from harness import sandbox as box
from harness.unity import run as unity
from tests import test_unity_harness as fixtures


class UnitySandboxWiring(fixtures.FakePlayerCase):
    def test_require_refuses_before_copy_or_player_when_bubblewrap_is_missing(self):
        with mock.patch.object(box, 'probe', return_value=(None, 'bubblewrap missing')), \
             mock.patch.object(unity, '_copy_game') as copied, \
             mock.patch.object(unity, 'player_cmd') as command:
            with self.assertRaisesRegex(SystemExit, 'sandboxed replay was required'):
                self.replay(sandbox='require')
        copied.assert_not_called(); command.assert_not_called()

    def test_every_player_start_uses_readonly_runtime_inputs_and_private_display(self):
        tool=box.Tool('/bwrap', 'test-only')
        seen=[]
        def spawn(actual, argv, **kw):
            self.assertEqual(actual,tool);seen.append((argv,kw))
            # Translate only this unit stand-in's documented mount paths. This
            # does NOT test OS containment; real-process cases live separately.
            translated=[]
            mapping={box.GAME:kw['game'],box.OUT:kw['out']}
            mapping.update({box.INPUTS+'/'+k:v for k,v in kw['inputs'].items()})
            for arg in argv[4:]:
                for inner,outer in sorted(mapping.items(),key=lambda x:-len(x[0])):
                    if arg==inner or arg.startswith(inner+'/'):
                        arg=str(outer)+arg[len(inner):];break
                translated.append(arg)
            return subprocess.run(translated,env=kw['env'],capture_output=True,text=True)
        with mock.patch.object(box,'probe',return_value=(tool,None)), \
             mock.patch.object(box,'run',side_effect=spawn):
            doc=self.replay(sandbox='require')
        self.assertEqual(doc['isolation']['network'],'none')
        self.assertEqual(doc['isolation']['mode'],'require')
        argv,kw=seen[0]
        self.assertEqual(argv[:4],['xvfb-run','-a','-s','-screen 0 1920x1080x24'])
        self.assertEqual(argv[4],'/in/player/game.x86_64')
        self.assertEqual(set(kw['inputs']),{'player','route.json','map.json'})
        self.assertNotIn('DISPLAY',kw['env'])
        self.assertNotEqual(kw['out'],self.tmp/'out')
        self.assertFalse((self.tmp/'out'/'player-output').exists())

    def test_auto_fallback_names_why_and_off_never_probes(self):
        with mock.patch.object(box,'probe',return_value=(None,'kernel refuses namespaces')):
            doc=self.replay(sandbox='auto')
        self.assertEqual(doc['isolation']['reason'],'kernel refuses namespaces')
        self.assertEqual(doc['isolation']['network'],'host')

    def test_require_failure_is_never_an_unsandboxed_retry(self):
        tool=box.Tool('/bwrap','test-only')
        with mock.patch.object(box,'probe',return_value=(tool,None)), \
             mock.patch.object(box,'run',side_effect=box.DiskBoundError('fixture disk stop')) as run, \
             mock.patch.object(unity.subprocess,'run') as plain:
            with self.assertRaisesRegex(SystemExit,'fixture disk stop'):self.replay(sandbox='require')
        self.assertEqual(run.call_count,1);plain.assert_not_called()
        self.assertFalse((self.tmp/'out'/'replay.json').exists())

    def test_hostile_output_links_are_not_followed_even_in_diagnostic_mode(self):
        target=self.tmp/'canary';target.write_text('test-only')
        for field in ('trace.json','run.json','frames'):
            if (self.tmp/'players').exists():
                import shutil;shutil.rmtree(self.tmp/'players')
            def malicious(*args,**kwargs):
                output=self.tmp/'out'/'player-output';output.mkdir(exist_ok=True)
                (output/field).symlink_to(target)
                return subprocess.CompletedProcess(args[0],0,'','')
            with mock.patch.object(unity.subprocess,'run',side_effect=malicious):
                with self.assertRaisesRegex(SystemExit,'plain|link'):self.replay(sandbox='off')
            self.assertEqual(target.read_text(),'test-only')
            self.assertFalse((self.tmp/'out'/'replay.json').exists())

    def test_a_player_path_cannot_mount_a_verifier_or_leave_its_build(self):
        folder=fixtures.player(self.tmp)
        metadata=folder/'build.json';doc=json.loads(metadata.read_text())
        for name in ('../verifier','/usr/bin/python3','game.x86_64','expectrail/repair.py','project/Assets/game.x86_64',None,42):
            metadata.write_text(json.dumps(doc|{'player':name}))
            with self.assertRaisesRegex(SystemExit,'player path'):
                unity.run(fixtures.route(self.tmp),self.tmp/'out',player=folder,sandbox='off')
        target=folder/unity.PLAYER;target.unlink();target.symlink_to(fixtures.FAKE)
        metadata.write_text(json.dumps(doc))
        with self.assertRaisesRegex(SystemExit,'links'):
            unity.run(fixtures.route(self.tmp),self.tmp/'out',player=folder,sandbox='off')

    def test_linked_build_metadata_is_refused_before_copy_or_player(self):
        folder=fixtures.player(self.tmp)
        metadata=folder/'build.json';canary=self.tmp/'synthetic-account'
        metadata.rename(canary);metadata.symlink_to(canary)
        with mock.patch.object(unity,'_copy_game') as copied:
            with self.assertRaisesRegex(SystemExit,'build account was refused'):
                unity.run(fixtures.route(self.tmp),self.tmp/'out',player=folder,sandbox='off')
        copied.assert_not_called()
        self.assertFalse((self.tmp/'out'/'replay.json').exists())

    def test_namespace_paths_are_not_resolved_against_the_host(self):
        with mock.patch.object(Path,'resolve',side_effect=AssertionError('host path resolution')):
            command=unity.player_cmd(Path('/in/player/game.x86_64'),Path('/in/route.json'),
                Path('/in/map.json'),Path('/out'),7,fixtures.MAP,True,isolated=True)
        self.assertIn('/in/player/game.x86_64',command)
        self.assertIn('/in/route.json',command)

    def test_native_probe_patch_applies_without_changing_game_source(self):
        from tests.unity_sandbox_cases import PATCH
        original=unity.tree_digest(fixtures.GAME)
        unity.prepare_build(self.tmp/'build',[PATCH])
        source=(self.tmp/'build/project/Assets/ExpectrailSandboxProbe.cs').read_text()
        for field in ('socket','write','policy','secret','inputs'):
            self.assertIn('c.mode == "'+field+'"',source)
        self.assertIn('Application.Quit(73)',source)
        self.assertEqual(unity.tree_digest(fixtures.GAME),original)

    def test_player_sandbox_flag_cannot_silently_start_an_unsandboxed_editor(self):
        with mock.patch.object(unity,'build') as build:
            with self.assertRaises(SystemExit):
                unity.main(['--build','--unity','unused','--out',str(self.tmp/'build'),'--sandbox','require'])
        build.assert_not_called()


class ReplayIdentity(unittest.TestCase):
    def test_explicit_uid_and_gid_are_the_identity_in_the_replay_contract(self):
        with mock.patch.object(box.os,'getuid',return_value=1234),mock.patch.object(box.os,'getgid',return_value=5678):
            tool=box.Tool('/bwrap','test-only');account=box.describe(tool,'require',None)
            cmd=box.command(tool,['true'],game=Path('/game-copy'),out=Path('/output'))
        self.assertEqual(cmd[cmd.index('--uid')+1],'1234')
        self.assertEqual(cmd[cmd.index('--gid')+1],'5678')
        self.assertEqual((account['uid'],account['gid']),(1234,5678))
        example=json.loads((fixtures.EXAMPLES/'replay.json').read_text())
        for invalid in (-1,True,'1234'):
            with self.assertRaises(ContractError):validate(example|{'isolation':account|{'uid':invalid}},'replay')
        self.assertEqual(validate(example|{'isolation':account},'replay'),'replay')
        self.assertEqual(validate(example,'replay'),'replay')


class WorkflowProposal(unittest.TestCase):
    def test_manual_main_only_licensed_build_and_unlicensed_required_replay_are_separate(self):
        import yaml
        root=Path(__file__).resolve().parents[1]
        doc=yaml.safe_load((root/'docs/proposals/253-unity-sandbox.yml.txt').read_text())
        self.assertEqual(set(doc.get('on',doc.get(True))),{'workflow_dispatch'})
        self.assertEqual(doc['permissions'],{'contents':'read'})
        build,replay=doc['jobs']['build'],doc['jobs']['replay']
        self.assertIn('refs/heads/main',build['if'])
        self.assertIn('inputs.confirm',build['if'])
        self.assertEqual(build['environment'],'unity')
        self.assertNotIn('environment',replay)
        self.assertEqual(replay['needs'],'build')
        self.assertEqual(replay['runs-on'],'ubuntu-24.04')
        text=json.dumps(doc)
        for forbidden in ('secrets.','pull_request_target','workflow_run','MODEL_API_KEY','id-token'):
            self.assertNotIn(forbidden,text)
        required=[s for s in replay['steps'] if 'EXPECTRAIL_UNITY_SANDBOX_TESTS' in s.get('env',{})]
        self.assertEqual(len(required),1)
        self.assertEqual(required[0]['env']['EXPECTRAIL_UNITY_SANDBOX_TESTS'],'required')
        self.assertIn('NativeUnityBoundaryTest',required[0]['run'])
