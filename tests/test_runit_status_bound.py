"""Bounded Run it polling and its optional pinned workerd lane; all transports stay local."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools import runit_api_smoke as smoke

ROOT = Path(__file__).resolve().parents[1]
EDGE = ROOT / 'apps/run-it-edge'


def node_environment():
    # The runtime receives test bindings only, never account/provider keys from the host.
    return {key: os.environ[key] for key in ('PATH', 'NODE_PATH', 'TMPDIR', 'EXPECTRAIL_WORKER_TESTS') if key in os.environ}


def node_binary():
    node = shutil.which('node')
    if node is None:
        reason = 'Node is not installed; the local Worker tests require Node'
        if os.environ.get('EXPECTRAIL_WORKER_TESTS') == 'required':
            raise AssertionError('EXPECTRAIL_WORKER_TESTS=required: '+reason)
        raise unittest.SkipTest(reason)
    return node


def check_node_case(case, filename, timeout, expected_tests):
    from expectrail import runit_site
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)/'bodies.json'
        env = dict(node_environment(), BODIES_OUT=str(out))
        result = subprocess.run([node_binary(), '--test', '--test-reporter=tap', str(EDGE/'test'/filename)],
                                cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
        case.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        case.assertIn('# fail 0', result.stdout)
        case.assertIn('# skipped 0', result.stdout)
        case.assertIn('# tests '+str(expected_tests)+'\n', result.stdout)
        bodies = json.loads(out.read_text())
    case.assertGreater(len(bodies), 5)
    for body in bodies:
        case.assertEqual(runit_site.api_errors(body), [], body)


class ServiceBoundTest(unittest.TestCase):
    def test_deadlines_coalescing_bodies_and_admission_with_contract_bodies(self):
        check_node_case(self, 'status.test.mjs', 60, 6)


class WorkerdRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        probe = subprocess.run([node_binary(), str(EDGE/'test/runtime-check.mjs')], env=node_environment(),
                               capture_output=True, text=True, timeout=30)
        if probe.returncode == 3:
            reason = json.loads(probe.stdout)['missing']
            if os.environ.get('EXPECTRAIL_WORKER_TESTS') == 'required':
                raise AssertionError('EXPECTRAIL_WORKER_TESTS=required: '+reason)
            raise unittest.SkipTest(reason)
        if probe.returncode:
            raise AssertionError('Installed workerd runtime could not be checked: '+probe.stdout+probe.stderr)
        info = json.loads(probe.stdout)
        if info.get('miniflare') != '4.20260730.0' or info.get('workerd') != '1.20260730.1':
            raise AssertionError('Unexpected runtime version: '+probe.stdout)

    def test_actual_worker_on_cloudflare_runtime_with_fake_github_and_contract_bodies(self):
        check_node_case(self, 'runtime.test.mjs', 240, 5)


class SmokeBoundTest(unittest.TestCase):
    def check_timeout(self, wait):
        seen = []
        def send(url, method='GET', body=None, origin=smoke.ORIGIN, **kwargs):
            headers = {'Access-Control-Allow-Origin': smoke.ORIGIN}
            doc = {'format': smoke.FORMAT}
            if url.endswith('/health'):
                doc.update(kind='health', open=True, standIn=False)
            elif origin != smoke.ORIGIN:
                return 403, {}, dict(doc, kind='refused', reason='bad-request')
            elif method == 'POST':
                return 202, headers, dict(doc, kind='accepted', sample='fall-through-bug', requestId='local-test')
            else:
                seen.append(kwargs['timeout'])
                doc.update(kind='status', requestId='local-test', sample='fall-through-bug', state='running', standIn=False)
            return 200, headers, doc
        self.assertEqual(smoke.smoke('https://worker.invalid', send=send, clock=lambda:0,
                                     wait=wait, emit=lambda text:None), 0)
        return seen

    def test_status_timeout_has_margin_over_the_workers_two_second_refresh_budget(self):
        self.assertEqual(self.check_timeout(180), [5])

    def test_status_timeout_never_extends_the_overall_wait(self):
        self.assertEqual(self.check_timeout(2.5), [2.5])
