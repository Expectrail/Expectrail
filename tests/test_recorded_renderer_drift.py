"""Renderer readiness: stand-ins always run; the capture check needs a named local renderer."""
import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from expectrail import app, doctor, recorded, renderer
from tests import test_doctor as doctor_tests

ROOT = Path(__file__).resolve().parent.parent
OLD = {'name': 'godot', 'version': '4.7.2.stable.official.ed1daf0bf', 'renderer': 'opengl3',
       'device': 'Mesa - llvmpipe (LLVM 20.1.2, 256 bits)'}
NEW = OLD | {'device': 'Mesa - llvmpipe (LLVM 19.1.7, 256 bits)'}


def answers(environment=OLD):
    doc = json.loads((ROOT / 'contracts/examples/vision-recording.json').read_text())
    doc['renderingEnvironments'] = [environment]
    return doc


def project(root, doc=None):
    from tests.test_app_projects import configured_project
    root = configured_project(root)
    path = root / 'expectrail.project.json'
    config = json.loads(path.read_text())
    config['providers'] = {'vision': 'ref:answers.json', 'vision-calibration': 'ref:calibration.json'}
    path.write_text(json.dumps(config))
    (root / 'answers.json').write_text(json.dumps(answers() if doc is None else doc))
    return root


def probe(environment=NEW):
    return {'environment': environment, 'reason': None, 'fix': None}


class ComparisonTest(unittest.TestCase):
    def test_every_capture_field_is_compared(self):
        self.assertEqual(renderer.compare(answers(), OLD), 'match')
        for key in renderer.FIELDS:
            with self.subTest(key=key):
                changed = OLD | {key: 'different'}
                self.assertEqual(renderer.compare(answers(), changed), 'mismatch')

    def test_old_partial_null_and_mixed_unknown_metadata_cannot_claim_match(self):
        for envs in (None, [], [None], [{}], [OLD, None], [OLD | {'version': None}]):
            with self.subTest(envs=envs):
                doc = answers()
                if envs is None: doc.pop('renderingEnvironments')
                else: doc['renderingEnvironments'] = envs
                self.assertEqual(renderer.compare(doc, OLD), 'unknown')

    def test_all_environments_must_match_not_just_one(self):
        doc = answers(); doc['renderingEnvironments'].append(NEW)
        self.assertEqual(renderer.compare(doc, OLD), 'mismatch')

    def test_message_names_both_versions_implication_and_fix_without_claiming_a_verdict(self):
        report = renderer.recording_report(answers(), NEW)
        for word in ('20.1.2', '19.1.7', 'needs-review', 'will not match', 'reject'):
            self.assertIn(word, report['message'])
        self.assertIn('MODEL_API_KEY', report['fix'])
        self.assertIn('EXPECTRAIL_SAM_USD_CAP', report['fix'])
        self.assertIn('Re-record', report['fix'])
        same = renderer.recording_report(answers(), OLD)
        self.assertFalse(same['warning']); self.assertIsNone(same['fix'])
        self.assertIn('must still match exactly', same['message'])

    def test_machine_uses_empty_doctor_probe_without_download(self):
        engine = doctor._ok('godot','engine','version'); engine.environment = {'name':'godot','version':OLD['version']}
        drawing = doctor._ok('opengl','draw','device'); drawing.environment = {k: OLD[k] for k in ('renderer','device')}
        shown = doctor._ok('display','display','display')
        with mock.patch.object(doctor,'godot',return_value=(engine,Path('/stand-in'))) as find, \
             mock.patch.object(doctor,'display',return_value=shown), mock.patch.object(doctor,'opengl',return_value=drawing) as draw:
            self.assertEqual(renderer.machine(), probe(OLD))
        find.assert_called_once_with(False); draw.assert_called_once_with(Path('/stand-in'),shown)

    def test_missing_tool_or_incomplete_probe_is_not_an_environment(self):
        ok = doctor._ok('ok','ok','ok')
        missing = doctor._missing('display','display','xvfb-run is missing','install xvfb')
        result = renderer.probed(ok,missing,ok)
        self.assertIsNone(result['environment']); self.assertIn('xvfb-run', result['reason'])
        self.assertEqual(renderer.probed(ok,ok,ok)['environment'],None)


class ProjectTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.root = Path(tmp.name)
        self.project = project(self.root/'game')

    def test_app_inspection_names_both_versions_and_starts_no_job_or_model(self):
        with mock.patch.object(renderer,'machine',return_value=probe()), \
             mock.patch.object(app.App,'create',side_effect=AssertionError('job started')), \
             mock.patch('agents.sam_observations.MetaSamClient',side_effect=AssertionError('live model')):
            result = app.inspect_project({'folder':str(self.project),'projectConfig':True})
        self.assertTrue(result['rendering']['warning'])
        self.assertEqual(result['rendering']['recording'],'answers.json')
        self.assertIn('20.1.2',result['rendering']['message']); self.assertIn('19.1.7',result['rendering']['message'])

    def test_missing_renderer_is_named_with_fix(self):
        missing = {'environment':None,'reason':'display: xvfb-run is not installed','fix':'install xvfb'}
        result = renderer.project_report(self.project,missing)
        self.assertTrue(result['warning']); self.assertIn('xvfb-run',result['message']); self.assertIn('install xvfb',result['fix'])

    def test_legacy_recording_is_readable_but_readiness_is_unknown(self):
        doc = answers(); doc.pop('renderingEnvironments')
        (self.project/'answers.json').write_text(json.dumps(doc))
        recorded.read_recording(self.project/'answers.json')
        self.assertEqual(renderer.project_report(self.project,probe())['status'],'unknown')

    def test_unsafe_and_malformed_recordings_do_not_leak_contents(self):
        path = self.project/'answers.json'
        path.write_text('private-value-not-json')
        report = renderer.project_report(self.project,probe())
        self.assertEqual(report['status'],'unreadable'); self.assertNotIn('private-value',str(report))
        path.unlink(); path.symlink_to(ROOT/'contracts/examples/vision-recording.json')
        self.assertEqual(renderer.project_report(self.project,probe())['status'],'unreadable')

    def test_live_project_does_not_claim_a_recording_or_send_anything(self):
        path = self.project/'expectrail.project.json'; config=json.loads(path.read_text()); config.pop('providers'); path.write_text(json.dumps(config))
        report = renderer.project_report(self.project,probe())
        self.assertEqual(report['status'],'live'); self.assertIsNone(report['recording'])
        self.assertIn('MODEL_API_KEY',report['message'])

    def test_check_does_not_mutate_or_relax_recordings(self):
        path = self.project/'answers.json'; before=path.read_bytes()
        renderer.project_report(self.project,probe())
        self.assertEqual(path.read_bytes(),before)


class DoctorProjectTest(doctor_tests.Machine):
    def test_project_json_and_text_name_difference_key_value_never_appears(self):
        root=project(self.tmp/'project')
        self.set_engine(draws=doctor_tests.LLVMPIPE.replace('20.1.2','19.1.7'))
        for extra in ([],['--json']):
            code,out,err=self.run_doctor('--no-fetch','--project',str(root),*extra)
            self.assertEqual(code,3,(out,err)); self.assertIn('20.1.2',out); self.assertIn('19.1.7',out)
            self.assertIn('needs-review',out); self.assertNotIn(doctor_tests.SECRET,out+err)
            if extra:
                doc=json.loads(out); self.assertEqual(doctor.problems(doc),[])
                checks={c['id']:c for c in doc['checks']}
                self.assertFalse(checks['vision-key']['required']); self.assertFalse(checks['vision-cap']['required'])
                self.assertTrue(checks['recorded-renderer']['required'])

    def test_matching_recording_requires_no_live_key_or_cap(self):
        root=project(self.tmp/'project')
        found=doctor.checks(fetch=False,project=root,env={})
        self.assertFalse(doctor.missing(found),doctor.document(found))
        self.assertEqual(doctor.problems(doctor.document(found)),[])
        self.assertNotIn('needs-review',str(doctor.document(found)))
        self.assertIn('no live key or spend cap is required',str(doctor.document(found)))

    def test_default_project_is_current_folder_config(self):
        root=project(self.tmp/'project')
        with mock.patch.object(Path,'cwd',return_value=root):
            found=doctor.checks(fetch=False)
        self.assertIn('recorded-renderer',[c.id for c in found])


class DriftFilesTest(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.root=Path(tmp.name)
        self.samples=self.root/'docs/run-it/vision'; self.samples.mkdir(parents=True)
        self.outside=self.root/'tests/outside/recordings/game'; self.outside.mkdir(parents=True)

    def write(self,path,doc):
        path.write_text(json.dumps(doc))

    def test_each_recording_is_named_and_both_versions_are_reported(self):
        self.write(self.samples/'clean.json',answers()); self.write(self.outside/'another-name.json',answers())
        self.write(self.outside/'calibration.json',{'format':'expectrail.anchor-calibration/v1'})
        problems=renderer.drift_problems(self.root,NEW)
        self.assertEqual(len(problems),2)
        self.assertIn('docs/run-it/vision/clean.json',problems[0])
        self.assertIn('tests/outside/recordings/game/another-name.json',problems[1])
        for problem in problems:
            self.assertIn('20.1.2',problem); self.assertIn('19.1.7',problem)
        self.assertEqual(renderer.drift_problems(self.root,OLD),[])

    def test_missing_metadata_and_invalid_recordings_cannot_pass(self):
        doc=answers();doc.pop('renderingEnvironments')
        self.write(self.samples/'old.json',doc);self.write(self.outside/'vision-recording.json',{})
        problems=renderer.drift_problems(self.root,OLD)
        self.assertEqual(len(problems),2)
        self.assertIn('does not identify',problems[0]);self.assertIn('unreadable',problems[1])

    def test_empty_collection_is_not_green(self):
        self.assertIn('No checked-in',renderer.drift_problems(self.root,OLD)[0])


class CaptureRendererTest(unittest.TestCase):
    def test_checked_in_recordings_match_the_capture_renderer(self):
        from tests.tool_requirements import godot_binary, require_tool
        import os
        # These helpers skip only missing prerequisites and fail in the required capture job.
        engine=godot_binary(); require_tool('xvfb-run')
        with mock.patch.dict(os.environ,{'EXPECTRAIL_GODOT':str(engine)}):
            result=renderer.machine()
        if result['environment'] is None:
            if os.environ.get('EXPECTRAIL_ENGINE_TESTS') == 'required':
                self.fail(result['reason'])
            self.skipTest(result['reason'])
        report=renderer.drift_report(ROOT,result['environment'])
        if report['problems']:
            message='recorded-renderer-'+report['status']+':\n'+'\n'.join(report['problems'])
            # This is a compatibility prerequisite, not a game verdict. Required
            # capture CI stays strict; corrupt/empty evidence always fails.
            if (os.environ.get('EXPECTRAIL_ENGINE_TESTS') != 'required'
                    and report['status'] in ('mismatch', 'unknown')):
                self.skipTest(message)
            self.fail(message)


class AppBrowserTest(unittest.TestCase):
    def test_warning_precedes_job_even_without_check_folders_and_resets_when_inputs_change(self):
        import shutil
        import threading
        from expectrail.orchestrator.store import JobStore
        try:
            from playwright.sync_api import sync_playwright, expect
        except ImportError:
            self.skipTest('Playwright is not installed; renderer warning UI needs Chromium')
        binary=shutil.which('chromium')
        if not binary:
            from tests.tool_requirements import require_tool
            require_tool('Playwright Chromium')
        with tempfile.TemporaryDirectory() as tmp:
            server=app.create_server(JobStore(Path(tmp)/'jobs'))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with sync_playwright() as p:
                    browser=p.chromium.launch(executable_path=binary,args=['--no-sandbox','--disable-background-networking'])
                    base=f'http://127.0.0.1:{server.server_port}'
                    for width,height in ((1440,900),(390,844)):
                        page=browser.new_page(viewport={'width':width,'height':height})
                        errors=[];jobs=[];inspections=[]
                        page.on('pageerror',lambda error:errors.append(str(error)))
                        state={'environment':NEW}
                        def route(request):
                            url=request.request.url
                            if url==base+'/api/inspect':
                                body=request.request.post_data_json;inspections.append(body)
                                report=renderer.recording_report(answers(),state['environment'])
                                data={'rendering':report,'godot':True,'routes':1,'checks':1,'drafts':0,'problems':[],'help':''}
                                request.fulfill(json=data)
                            elif url==base+'/api/jobs':
                                jobs.append(request.request.post_data_json)
                                request.fulfill(status=400,json={'detail':f'Stand-in request {len(jobs)}: no game is run'})
                            elif url.startswith(base):request.continue_()
                            else:request.abort()
                        page.route('**/*',route)
                        page.goto(base+'/?token='+server.token)
                        page.locator('#before').fill('/unchanged');page.locator('#after').fill('/changed')
                        page.locator('#verify').click()
                        expect(page.locator('#verify')).to_have_text('Verify with this warning')
                        expect(page.locator('#rendering')).to_contain_text('20.1.2')
                        expect(page.locator('#rendering')).to_contain_text('19.1.7')
                        self.assertFalse(jobs);self.assertEqual(inspections[-1]['folder'],'/unchanged')
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                        page.locator('#after').fill('/another-change')
                        page.locator('#verify').click();expect(page.locator('#verify')).to_have_text('Verify with this warning')
                        self.assertFalse(jobs)
                        page.locator('#verify').click();expect(page.locator('#error')).to_have_text('Stand-in request 1: no game is run')
                        self.assertEqual(len(jobs),1)
                        # A matching renderer starts on the first click, and says exact answers are still required.
                        state['environment']=OLD
                        page.locator('#verify').click();expect(page.locator('#error')).to_have_text('Stand-in request 2: no game is run')
                        expect(page.locator('#rendering')).to_contain_text('Images and questions must still match exactly')
                        self.assertEqual(len(jobs),2);self.assertFalse(errors,errors)
                        page.close()
                    browser.close()
            finally:
                server.shutdown();server.server_close();thread.join()


class CapturePrerequisiteTest(unittest.TestCase):
    def test_unavailable_renderer_skips_by_name_but_required_ci_fails(self):
        missing={'environment':None,'reason':'opengl: the engine could not draw a frame (missing Mesa driver)','fix':'install Mesa'}
        case=CaptureRendererTest('test_checked_in_recordings_match_the_capture_renderer')
        import os
        with mock.patch('tests.tool_requirements.godot_binary',return_value=Path('/stand-in')), \
             mock.patch('tests.tool_requirements.require_tool'), mock.patch.object(renderer,'machine',return_value=missing):
            with mock.patch.dict(os.environ,{'EXPECTRAIL_ENGINE_TESTS':''}), self.assertRaisesRegex(unittest.SkipTest,'opengl.*Mesa'):
                case.test_checked_in_recordings_match_the_capture_renderer()
            with mock.patch.dict(os.environ,{'EXPECTRAIL_ENGINE_TESTS':'required'}), self.assertRaisesRegex(AssertionError,'opengl.*Mesa'):
                case.test_checked_in_recordings_match_the_capture_renderer()

    def test_required_renderer_drift_is_a_failure_never_a_skip(self):
        import os
        case=CaptureRendererTest('test_checked_in_recordings_match_the_capture_renderer')
        with mock.patch('tests.tool_requirements.godot_binary',return_value=Path('/stand-in')), \
             mock.patch('tests.tool_requirements.require_tool'), mock.patch.object(renderer,'machine',return_value=probe()), \
             mock.patch.dict(os.environ,{'EXPECTRAIL_ENGINE_TESTS':'required'}), \
             mock.patch.object(renderer,'drift_report',return_value={'status':'mismatch',
                 'problems':['sample.json: LLVM 20.1.2 versus 19.1.7']}), \
             self.assertRaisesRegex(AssertionError,'sample.json.*20.1.2.*19.1.7'):
            case.test_checked_in_recordings_match_the_capture_renderer()
