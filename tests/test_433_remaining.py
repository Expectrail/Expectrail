"""Remaining repair boundaries using public, synthetic fixtures only; no live calls."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from agents import fixer
from expectrail import app, auto_fix, contracts, repair, runit
from expectrail.orchestrator import request, runner, engines
from tests import test_auto_fix as auto_tests, test_repair_command as repairs
from tests import test_visible_repair as visible
from tests import test_app as app_tests

ROOT = Path(__file__).resolve().parents[1]


class BoundedAutoFix(unittest.TestCase):
    setUp = auto_tests.AutoFixTest.setUp
    verify = auto_tests.AutoFixTest.verify

    def test_explicit_bounded_agent_reaches_the_shared_loop_and_fresh_gate(self):
        from expectrail import spend
        spend.reset_for_tests(); self.addCleanup(spend.reset_for_tests)
        env = mock.patch.dict(os.environ, {'EXPECTRAIL_MUSE_USD_CAP': '6'})
        env.start(); self.addCleanup(env.stop)
        replay = self.engine._replay
        def isolated(*args):
            result = replay(*args)
            result['isolation'] = json.loads((ROOT / 'contracts/examples/replay.json').read_text())['isolation']
            result['isolation']['sandbox']['version'] = 'test-only-fixture'
            return result
        self.engine._replay = isolated
        real = fixer.run_fixer
        def fixture(req, out, **kw):
            self.assertEqual(kw['agent'], 'llm-patch')
            return real(req, out, **(kw | {'candidate_patch': auto_tests.FIX}))
        with mock.patch.object(fixer, 'run_fixer', side_effect=fixture) as calls, \
             mock.patch('harness.sandbox.probe', return_value=(object(), None)):
            code, parent = self.verify('--auto-fix', '--auto-fix-agent', 'llm-patch',
                                       '--auto-fix-usd-cap', '6')
        self.assertEqual(code, 1, parent)
        self.assertEqual(parent['decision'], 'reject')
        self.assertEqual(parent['repair']['decision'], 'accept')
        self.assertEqual(self.jobs.request(parent['id'])['autoFix']['source'], 'llm-patch')
        self.assertEqual(calls.call_count, 1)

    def test_agent_option_is_not_a_cap_or_an_optin_and_legacy_default_is_unchanged(self):
        with self.assertRaisesRegex(ValueError, 'require --auto-fix'):
            auto_fix.configure(False, agent='llm-patch')
        with self.assertRaisesRegex(ValueError, 'cap'):
            auto_fix.configure(True, agent='llm-patch')
        self.assertEqual(auto_fix.configure(True, cap=1)[0]['source'], 'muse')
        with self.assertRaises(ValueError): auto_fix.configure(True, cap=1, agent='custom-cmd')


class AppAgent(unittest.TestCase):
    setUp, close, start, http = (app_tests.HTTPTest.setUp, app_tests.HTTPTest.close,
                               app_tests.HTTPTest.start, app_tests.HTTPTest.http)

    def test_visible_choice_is_saved_without_changing_caps_or_starting_a_model(self):
        with mock.patch.object(auto_fix, 'launch', return_value=None):
            code, job, _ = self.http('POST', '/api/jobs', self.body | {
                'autoFix': True, 'attempts': 1, 'usdCap': 6, 'repairAgent': 'llm-patch'})
        self.assertEqual(code, 201, job)
        self.assertEqual(self.store.request(job['id'])['autoFix'],
                         {'attempts': 1, 'usdCap': 6, 'source': 'llm-patch'})
        self.store.cancel(job['id'])
        self.assertIn('id="fix-agent"', app.app_page.PAGE)
        self.assertIn('llm-patch', app.app_page.PAGE)


class HeldOutChildren(unittest.TestCase):
    setUp, invoke, record = (repairs.RepairCommandTest.setUp,
                            repairs.RepairCommandTest.invoke, repairs.RepairCommandTest.record)

    def configure(self):
        # A synthetic route is authored here. No actual held-out checkout is used.
        from expectrail.orchestrator import private_context as heldout
        self.context = self.tmp / 'synthetic-suite'; self.context.mkdir()
        route = json.loads((self.bug / 'harness/routes/smoke.json').read_text())
        route['name'] = 'synthetic-canary'
        (self.context / 'not-to-fixer.json').write_text(json.dumps(route))
        (self.context / 'manifest.json').write_text(json.dumps({'routes': [{'file': 'not-to-fixer.json'}]}))
        patcher = mock.patch.dict(os.environ, {heldout.ROOT_ENV: str(self.context), heldout.VISION_ENV: '1'})
        patcher.start(); self.addCleanup(patcher.stop)
        req = heldout.bind(self.jobs.request(self.parent))
        self.binding = req['heldOut']
        original = self.game.replay
        def replay(route, game, out, frames):
            look = self.game.look_of
            if Path(route).name == 'not-to-fixer.json': self.game.look_of = lambda _: 'BUG'
            try: return original(route, game, out, frames)
            finally: self.game.look_of = look
        self.engines = {'godot': engines.GodotGate(replay=replay, visual=self.game.observer())}
        self.parent = self.jobs.create(req)[0]['id']
        self.assertEqual(runner.work(self.jobs, self.parent, self.engines)['decision'], 'reject')

    def test_fresh_children_keep_the_suite_and_heldout_veto_never_enters_a_retry(self):
        self.configure()
        with mock.patch.object(fixer, 'run_fixer', wraps=fixer.run_fixer) as calls:
            code, output = self.invoke('--attempts', '2')
        self.assertEqual(code, 2, output)
        _, doc = self.record()
        self.assertEqual([a['decision'] for a in doc['attempts']], ['reject', 'reject'])
        for attempt in doc['attempts']:
            self.assertEqual(self.jobs.request(attempt['job'])['heldOut'], self.binding)
        self.assertEqual(calls.call_count, 2)
        self.assertEqual(calls.call_args_list[1].kwargs['prior_reject']['failing'], [])
        for call in calls.call_args_list:
            sent = json.dumps([call.args[0], call.kwargs['prior_reject']])
            for secret in ('synthetic-canary', 'not-to-fixer', str(self.context), 'heldOut'):
                self.assertNotIn(secret, sent)
            self.assertFalse(any('not-to-fixer' in p.name for p in Path(call.kwargs['game']).rglob('*')))

    def test_changed_or_absent_context_refuses_before_fixer_construction(self):
        self.configure()
        (self.context / 'not-to-fixer.json').write_text('{}')
        with mock.patch.object(fixer, 'run_fixer') as calls:
            code, output = self.invoke()
        self.assertEqual(code, 5, output); calls.assert_not_called()
        self.assertNotIn('not-to-fixer', output)


    def test_missing_context_and_withdrawn_visual_consent_stop_before_a_fixer(self):
        self.configure()
        from expectrail.orchestrator import private_context
        for setting in ({private_context.ROOT_ENV:''},{private_context.VISION_ENV:'0'}):
            with mock.patch.dict(os.environ,setting), mock.patch.object(fixer,'run_fixer') as calls:
                self.assertEqual(self.invoke()[0],5)
                calls.assert_not_called()

    def test_context_is_part_of_request_identity_and_not_a_client_path(self):
        self.configure()
        first=self.jobs.request(self.parent);other=copy.deepcopy(first)
        other['heldOut']['framesToVisual']=False
        self.assertNotEqual(request.inputs(first)['requestDigest'],request.inputs(other)['requestDigest'])
        other=copy.deepcopy(first);other['heldOut']['path']=str(self.context)
        with self.assertRaises(ValueError):request.check(other)


class ProviderOnlySample(visible.Case):
    save = visible.RepairTest.save

    def setUp(self):
        super().setUp()
        manifest = runit.read_manifest(self.root)
        runit.find_sample(manifest, 'recorded-fix')['repairRecorded'] = True
        (self.root / runit.MANIFEST).write_text(json.dumps(manifest))
        self.path = self.root / 'docs/run-it/repair/repair-run.json'
        self.patch = self.path.parent / 'attempt-1/candidate.patch'
        self.patch.parent.mkdir(parents=True)
        self.doc = json.loads((ROOT / 'contracts/examples/repair-run.v1.json').read_text())
        from expectrail.orchestrator import sample
        bug = sample.checkout(self.tmp / 'original', bug=True, root=self.root)
        self.doc['parent']['headTree'] = request.tree_digest(bug / sample.GAME, bug, 'godot')

    def prepare(self):
        self.doc['budget']['usdCap'] = 6
        self.doc['fixer'] = {'source': 'llm-patch', 'sandboxed': False, 'providerOnly': True}
        counter = (ROOT / 'contracts/examples/fixer-invocation-current-model.json').read_bytes()
        path = self.path.parent / 'attempt-1/fixer-invocation.json'; path.write_bytes(counter)
        self.doc['attempts'][0].update(fixerInvocation='attempt-1/fixer-invocation.json',
            fixerInvocationSha256=hashlib.sha256(counter).hexdigest())
        self.save()
        answers = self.record('fall-through-repair')
        answers['sample'] = 'recorded-fix'
        (self.root / 'docs/run-it/vision/recorded-fix.json').write_text(json.dumps(answers))
        self.game.replays.clear()

    def test_metered_provider_only_record_is_replayed_without_claiming_a_sandboxed_agent(self):
        self.prepare()
        result, _ = self.run_sample('recorded-fix')
        self.assertEqual(result['decision'], 'accept')
        self.assertFalse(self.doc['fixer']['sandboxed'])

    def test_missing_changed_or_stopped_meter_never_starts_a_replay(self):
        self.prepare(); counter = self.path.parent / 'attempt-1/fixer-invocation.json'
        for data in (None, b'{}', (ROOT / 'contracts/examples/fixer-invocation.json').read_bytes()):
            if data is None: counter.unlink(missing_ok=True)
            else: counter.write_bytes(data)
            with self.assertRaises(runit.RunItError): self.run_sample('recorded-fix')
        self.assertEqual(self.game.replays, [])

    def test_valid_digest_cannot_hide_a_stopped_or_over_usage_counter(self):
        self.prepare()
        target = self.path.parent / 'attempt-1/fixer-invocation.json'
        original = json.loads(target.read_bytes())
        for kind in ('stopped', 'over-usage'):
            counter = copy.deepcopy(original)
            if kind == 'stopped':
                counter['status'] = 'stopped'
                counter['stopReason'] = 'fixer-invocation-cap'
            else:
                row = counter['requests'][0]
                row['reportedUsage']['outputTokens'] = row['outputTokenCap'] + 1
            raw = (json.dumps(counter) + '\n').encode()
            target.write_bytes(raw)
            self.doc['attempts'][0]['fixerInvocationSha256'] = hashlib.sha256(raw).hexdigest()
            self.save()
            with self.assertRaises(runit.RunItError): self.run_sample('recorded-fix')
        self.assertEqual(self.game.replays, [])
