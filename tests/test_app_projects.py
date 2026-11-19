"""Configured projects use the same request and worker in the local app and CLI."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from expectrail import app_kinematic, cli, project_job, recorded
from expectrail.contracts import validate
from expectrail.orchestrator import engines, request, runner
from expectrail.orchestrator.store import JobStore
from tests import test_app as app_tests
from tests.test_ci_gate import SPEC, ROUTES
from tests.test_two_observers import Game

ROOT = Path(__file__).resolve().parent.parent


def configured_project(root, *, name='crate-lane', draft=False):
    root.mkdir(parents=True)
    (root/'project.godot').write_text('[application]\nconfig/name="'+name+'"\n')
    (root/'entry.tscn').write_text('[gd_scene format=3]\n[node name="Pawn" type="Node2D"]\n')
    (root/'pawn.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    (root/'inputs').mkdir();(root/'checks/nested').mkdir(parents=True)
    shutil.copyfile(ROUTES/'smoke.json',root/'inputs/first.json')
    shutil.copyfile(SPEC,root/'checks/nested/floor.json')
    config={'format':'expectrail.project/v1','adapter':'godot','entryScene':'res://entry.tscn',
            'viewport':[160,96],'physicsTicksPerSecond':120,'captureFps':60,
            'inputActions':['move_right','jump'],'bindings':{'player':{'node':'Pawn','texture':'res://pawn.svg'}},
            'routes':['inputs/first.json'],'approvedContracts':['checks/nested/floor.json']}
    if draft:config['draft']=True
    (root/'expectrail.project.json').write_text(json.dumps(config))
    return root


class ConfiguredAppTest(unittest.TestCase):
    setUp, close, start, http, finished = app_tests.HTTPTest.setUp, app_tests.HTTPTest.close, app_tests.HTTPTest.start, app_tests.HTTPTest.http, app_tests.HTTPTest.finished

    def pair(self, *, draft=False):
        before=configured_project(self.root/'other-before',draft=draft)
        after=self.root/'other-after';shutil.copytree(before,after)
        game=Game();self.engine=engines.GodotGate(replay=game.replay,visual=game.observer())
        return {'before':str(before),'after':str(after),'projectConfig':True}

    def test_second_project_lists_its_configured_policy_and_app_cli_have_same_inputs_and_accept(self):
        body=self.pair()
        code,info,_=self.http('POST','/api/inspect',body|{'folder':body['before']})
        self.assertEqual(code,200,info)
        self.assertEqual((info['routes'],info['checks']),(1,1))
        self.assertEqual(info['routeNames'],['smoke'])
        self.assertEqual(info['checkNames'],['player-stays-above-ground'])
        code,job,_=self.http('POST','/api/jobs',body);self.assertEqual(code,201,job)
        shown=self.finished(job['id']);self.assertEqual(shown['state'],'accept',shown)
        other=JobStore(self.root/'cli-jobs')
        def spawn(store,key):
            t=threading.Thread(target=runner.work,args=(store,key),kwargs={'engines':{'godot':self.engine}})
            t.start();self.workers.append(t)
        with mock.patch.object(runner,'spawn',side_effect=spawn),redirect_stdout(io.StringIO()) as stdout:
            code=cli.main(['verify','--project',body['after'],'--base',body['before'],'--jobs-root',str(other.root),'--json'])
        self.assertEqual(code,0,stdout.getvalue())
        printed=json.loads(stdout.getvalue());self.assertEqual(printed['decision'],'accept')
        self.assertEqual(self.store.status(job['id'])['inputs'],printed['inputs'])
        self.assertEqual(self.store.request(job['id'])['project'],other.request(printed['id'])['project'])
        self.assertEqual(request.tree_digest(Path(body['after'])),printed['inputs']['headTree'])
        self.assertFalse((Path(body['after'])/'specs').exists())

    def test_draft_config_never_accepts_even_when_engine_and_vision_pass(self):
        body=self.pair(draft=True)
        info=self.http('POST','/api/inspect',body|{'folder':body['before']})[1]
        self.assertTrue(info['configDraft']);self.assertIn('cannot give an accept',info['help'])
        code,job,_=self.http('POST','/api/jobs',body);self.assertEqual(code,201,job)
        result=self.finished(job['id']);self.assertEqual(result['state'],'needs-review',result)
        self.assertIn('draft',' '.join(result['reasons']))

    def test_head_cannot_choose_new_routes_or_drop_the_base_check(self):
        body=self.pair();path=Path(body['after'])/'expectrail.project.json'
        doc=json.loads(path.read_text());doc['approvedContracts']=[];path.write_text(json.dumps(doc))
        code,job,_=self.http('POST','/api/jobs',body);self.assertEqual(code,201,job)
        result=self.finished(job['id']);self.assertEqual(result['state'],'needs-review',result)
        saved=self.store.request(job['id']);self.assertEqual(len(request.read_checks(saved).specs),1)
        self.assertIn('config differs',' '.join(result['reasons']))

    def test_check_folders_previews_current_and_saved_setups_without_starting_a_job(self):
        from expectrail import onboarding

        game = self.root / 'My game'
        shutil.copytree(ROOT / 'tests/projects/crate-run/project', game)
        (game / 'expectrail.project.json').unlink()
        body = {'before': str(game), 'after': str(game), 'folder': str(game)}
        for saved in (False, True):
            with self.subTest(saved=saved):
                if saved:
                    onboarding.publish(game, onboarding.proposal(game, onboarding.inspect(game)), False)
                digest = request.tree_digest(game)
                code, error, _ = self.http('POST', '/api/inspect', body)
                self.assertEqual(code, 400)
                detail = error['detail']
                self.assertIn('res://main.tscn', detail)
                self.assertIn('Player', detail)
                self.assertIn('no saved sprite texture', detail)
                self.assertIn('Saved draft' if saved else 'Setup preview', detail)
                self.assertEqual(self.http('POST', '/api/jobs', body)[0], 400)
                self.assertEqual(request.tree_digest(game), digest)
        self.assertEqual(self.server.app.history()['jobs'], [])

        pending = game / 'expectrail.project.draft.json'
        route = game / json.loads(pending.read_text())['config']['routes'][0]
        route.write_text('{}')
        code, error, _ = self.http('POST', '/api/inspect', body)
        self.assertEqual(code, 400)
        self.assertIn('route', error['detail'])
        self.assertNotIn('Saved draft preview', error['detail'])

        pending.write_text('{}')
        code, error, _ = self.http('POST', '/api/inspect', body)
        self.assertEqual(code, 400)
        self.assertIn(pending.name, error['detail'])
        self.assertNotIn('Saved draft preview', error['detail'])

    def test_missing_or_invalid_config_is_named_and_no_job_is_started(self):
        body=self.pair();path=Path(body['before'])/'expectrail.project.json';path.unlink()
        for value in (None,'{broken'):
            if value is not None:path.write_text(value)
            code,error,_=self.http('POST','/api/jobs',body)
            self.assertEqual(code,400);self.assertIn('config',error['detail'])
        self.assertFalse(list((self.store.root/'jobs').glob('*')))


class ProjectRequestTest(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.source=configured_project(self.root/'source')
        self.store=JobStore(self.root/'jobs')

    def test_bundled_example_only_prepares_a_normal_config_and_copies_existing_check_bytes(self):
        source = self.root / 'example-source'; (source / 'player').mkdir(parents=True)
        (source / 'project.godot').write_text('[application]\n')
        (source / 'world.tscn').write_text('[gd_scene format=3]\n')
        (source / 'player/player.png').write_bytes((ROOT / 'tests/fixtures/recorded-pixel-mismatch/recorded.png').read_bytes())
        dest = app_kinematic.prepare(source, self.root / 'example-copy')
        info = project_job.inspect(dest)
        self.assertEqual((info['routes'], info['checks']), (1, 1))
        self.assertEqual(info['routeNames'], ['walk'])
        self.assertEqual((dest / 'checks' / app_kinematic.SPEC.name).read_bytes(), app_kinematic.SPEC.read_bytes())
        self.assertFalse((source / 'expectrail.project.json').exists())
        doc = project_job.prepare(self.store, dest)
        self.assertEqual(doc['project']['visual']['type'], 'anchored-recorded')
        with self.assertRaisesRegex(ValueError, 'new destination'):
            app_kinematic.prepare(source, dest)
        self.assertTrue((dest / 'expectrail.project.json').is_file())

    def test_request_example_and_recorded_paths_validate_and_cannot_escape_game(self):
        doc=json.loads((ROOT/'contracts/examples/verify-request-recorded.json').read_text())
        request.check(doc)
        for value in ('../secret.json','/tmp/secret.json','other/answers.json'):
            bad=copy.deepcopy(doc);bad['project']['visual']['recording']=value
            with self.assertRaises(request.RequestError):request.check(bad)

    def test_selected_checks_keep_exact_bytes_without_adding_unlisted_checks(self):
        (self.source/'checks/extra.json').write_text('not a selected check')
        doc=project_job.prepare(self.store,self.source)
        self.assertEqual(len(request.read_checks(doc).specs),1)
        staged=Path(doc['head']['checkout'])
        self.assertEqual((staged/'specs/000.json').read_bytes(),SPEC.read_bytes())
        self.assertEqual(request.tree_digest(staged/'project'),request.tree_digest(self.source))

    def test_recorded_provider_uses_base_files_and_never_live_fallback(self):
        path=self.source/'expectrail.project.json';config=json.loads(path.read_text())
        config['providers']={'vision':'ref:vision/answers.json','vision-calibration':'ref:vision/cal.json'}
        path.write_text(json.dumps(config));(self.source/'vision').mkdir()
        shutil.copyfile(app_kinematic.RECORDING/'vision-recording.json',self.source/'vision/answers.json')
        shutil.copyfile(app_kinematic.RECORDING/'calibration.json',self.source/'vision/cal.json')
        head=self.root/'changed';shutil.copytree(self.source,head)
        (head/'vision/answers.json').write_text('unusable head file')
        doc=project_job.prepare(self.store,head,self.source)
        with mock.patch('agents.sam_observations.MetaSamClient',side_effect=AssertionError('live model')):
            observer=project_job.observer(doc)
            self.assertIn('recorded',observer.describe()['provider'])
        self.assertEqual(doc['project']['visual']['type'],'anchored-recorded')

    def test_malformed_recording_is_needs_review_not_a_worker_crash_or_live_call(self):
        path=self.source/'expectrail.project.json';config=json.loads(path.read_text())
        config['providers']={'vision':'ref:answers.json','vision-calibration':'ref:cal.json'}
        path.write_text(json.dumps(config));(self.source/'answers.json').write_text('{}');(self.source/'cal.json').write_text('{}')
        doc=project_job.prepare(self.store,self.source)
        status,_=self.store.create(doc);game=Game()
        with mock.patch('agents.sam_observations.MetaSamClient',side_effect=AssertionError('live model')):
            runner.work(self.store,status['id'],engines={'godot':engines.GodotGate(replay=game.replay)})
        result=self.store.status(status['id']);self.assertEqual(result['decision'],'needs-review',result)
        self.assertTrue(any(d['code']=='PROVIDER_FAILED' for d in result['diagnostics']))

    def test_normal_worker_uses_configured_recorded_answers_without_a_key(self):
        from expectrail import anchored
        from tests.test_anchored_observer import GAME, SPEC as CHECK, Sees, make_run
        run = make_run(self.root / 'capture', speed=0.3)
        run['trace']['unknownActions'] = []
        calibration = anchored.calibrate(GAME, run, Sees(run))
        capture = recorded.RecordingClient(Sees(run))
        anchored.AnchoredObserver(capture, calibration).look(CHECK, run)
        path = self.source / 'expectrail.project.json'
        config = json.loads(path.read_text())
        config['providers'] = {'vision': 'ref:vision/answers.json', 'vision-calibration': 'ref:vision/cal.json'}
        path.write_text(json.dumps(config)); (self.source / 'vision').mkdir()
        recorded.write_recording(self.source / 'vision/answers.json', capture.recording(
            sample='stand-in', recorded_at='2026-11-15', run='offline-test'))
        (self.source / 'vision/cal.json').write_text(json.dumps(calibration))
        doc = project_job.prepare(self.store, self.source)
        status, _ = self.store.create(doc)
        with mock.patch('agents.sam_observations.MetaSamClient', side_effect=AssertionError('live model')):
            runner.work(self.store, status['id'], engines={'godot': engines.GodotGate(replay=lambda *a, **k: run)})
        result = self.store.status(status['id'])
        self.assertEqual(result['decision'], 'accept', result)
        self.assertIn('recorded', result['observers']['visual']['provider'])
        self.assertFalse(result['diagnostics'])

    def test_linked_configured_policy_is_refused_by_inspect_and_submission(self):
        original = self.source / 'checks/nested/floor.json'
        saved = self.source / 'floor-copy.json'; original.rename(saved); original.symlink_to(saved)
        for action in (lambda: project_job.inspect(self.source), lambda: project_job.prepare(self.store, self.source)):
            with self.assertRaisesRegex(ValueError, 'symlink'):
                action()
        self.assertFalse(self.store.root.exists())

    def test_missing_recorded_request_is_an_image_change_not_a_new_point_prompt(self):
        from agents.sam_observations import SamError
        folder=ROOT/'tests/fixtures/recorded-pixel-mismatch'
        facts=json.loads((folder/'question.json').read_text())
        client=recorded.RecordedClient(recorded.read_recording(app_kinematic.RECORDING/'vision-recording.json'))
        answer=client.segment_at(folder/'recorded.png',[(488,329)])
        self.assertIsNotNone(answer[0]);self.assertEqual(client.answered,1)
        with self.assertRaises(SamError) as caught:client.segment_at(folder/'replayed.png',[(488,329)])
        self.assertEqual(caught.exception.kind,'not-recorded')
        self.assertEqual((client.calls,client.answered,client.not_recorded),(2,1,1))
        import hashlib
        self.assertEqual(hashlib.sha256((folder/'recorded.png').read_bytes()).hexdigest(),facts['oldPngSha256'])
        self.assertEqual(hashlib.sha256((folder/'replayed.png').read_bytes()).hexdigest(),facts['newPngSha256'])
