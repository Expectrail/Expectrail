"""Real Worker admission, immutable earlier results and the #255 receipt entry point, offline."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import threading
from urllib.parse import urlsplit

from tests import tool_requirements as tools

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'docs/run-it/earlier'
PANEL = ROOT / 'docs/run-it/receipt-panel.js'


def receipt_fixture():
    # Test-only issuer, generated in memory. No private key is written or shipped.
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ModuleNotFoundError:
        raise unittest.SkipTest('cryptography is not installed; signed receipt fixture needs Ed25519')
    from tests.test_verify_receipt_page import base_doc, public_b64, sign, store_text
    key = Ed25519PrivateKey.generate()
    now = datetime.now(timezone.utc)
    doc = base_doc(key, kid='throwaway-test-issuer')
    doc.update(issuedAt=(now-timedelta(minutes=1)).isoformat(), expiresAt=(now+timedelta(hours=1)).isoformat(),
               repository='Expectrail/Expectrail', headSha256='b'*64, buildSha256='c'*64, policySha256='d'*64)
    store = store_text({'throwaway-test-issuer': public_b64(key)})
    opts = dict(expectRepo='Expectrail/Expectrail', expectHead='b'*64, expectBuild='c'*64, expectPolicy='d'*64)
    return sign(doc, key), store, opts, key, sign


class SnapshotTest(unittest.TestCase):
    def test_every_saved_byte_matches_the_pinned_public_source_inventory(self):
        meta = json.loads((CACHE/'source.json').read_text())
        self.assertEqual(meta['repository'], 'Expectrail/Expectrail')
        self.assertEqual(meta['ref'], '3adf65eca0883c0af97ff9e4c526f815a21a1c15')
        self.assertEqual(len(meta['files']), 7)
        for name, record in meta['files'].items():
            self.assertNotIn('..', Path(name).parts)
            path = CACHE/name
            self.assertFalse(path.is_symlink())
            raw = path.read_bytes()
            self.assertEqual(len(raw), record['bytes'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), record['sha256'])
            self.assertEqual(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(), record['gitBlob'])

    def test_snapshots_keep_the_merged_contracts_and_unsigned_state(self):
        import jsonschema
        status_schema = json.loads((ROOT/'contracts/run-it-result.v1.schema.json').read_text())
        latest_schema = json.loads((ROOT/'contracts/run-it-latest.v1.schema.json').read_text())
        latest = json.loads((CACHE/'latest.json').read_text())
        jsonschema.Draft202012Validator(latest_schema).validate(latest)
        self.assertEqual(set(latest['samples']), {'clean', 'fall-through-bug', 'fall-through-repair'})
        for sample, row in latest['samples'].items():
            status = json.loads((CACHE/row['requestId']/'status.json').read_text())
            jsonschema.Draft202012Validator(status_schema).validate(status)
            self.assertEqual(status['requestId'], row['requestId'])
            self.assertEqual(status['sample']['id'], sample)
            self.assertEqual(status['finishedAt'], row['finishedAt'])
            self.assertFalse(status['receipt']['signed'])
            findings = json.loads((CACHE/row['requestId']/'findings.json').read_text())
            self.assertEqual(findings['decision'], status['decision'])
            self.assertEqual(findings['observers']['rule'], 'both')
            self.assertEqual(findings['counts']['checks'], len(findings['checks']))


class WorkerBurstTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tools.executable('node')

    def test_actual_worker_burst_command_holds_visitor_daily_and_breaker_limits(self):
        got = subprocess.run(['node', str(ROOT/'apps/run-it-edge/burst.mjs')], cwd=ROOT,
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(got.returncode, 0, got.stdout+got.stderr)
        result = json.loads(got.stdout)
        self.assertEqual(result['limits'], dict(perVisitor=3, daily=40, consecutiveFailures=3))
        self.assertEqual(result['totalPostRequests'], 2804)
        self.assertEqual(result['realExternalRequests'], 0)
        for scope, accepted, reason in [('perVisitor', 3, 'visitorQuota'), ('daily', 40, 'dailyCap'), ('breaker', 3, 'circuitOpen')]:
            self.assertEqual(result[scope]['accepted'], accepted)
            self.assertEqual(result[scope][reason], 200)
        self.assertTrue(result['perVisitor']['restartPreservedQuota'])
        self.assertTrue(result['daily']['restartPreservedQuota'])
        self.assertTrue(result['breaker']['restartPreservedBreaker'])
        self.assertTrue(result['breaker']['midnightDoesNotReset'])
        self.assertEqual(result['breaker']['epochResetAccepted'], 1)


class ReceiptEntryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tools.executable('node')

    def test_entry_point_uses_the_real_255_reader_and_never_trusts_an_embedded_key(self):
        doc, store, opts, key, sign = receipt_fixture()
        altered = copy.deepcopy(doc); altered['headSha256'] = 'e'*64
        stale = copy.deepcopy(doc); stale['issuedAt'] = '2020-01-01T00:00:00Z'; stale['expiresAt'] = '2020-01-02T00:00:00Z'; stale = sign(stale, key)
        unknown = json.loads(store); unknown['keys'][0]['id'] = 'other-test-issuer'
        cases = [
            dict(receipt='', store='', opts=opts),
            dict(receipt=json.dumps(doc), store=store, opts=opts),
            dict(receipt=json.dumps(doc), store=json.dumps(unknown), opts=opts),
            dict(receipt=json.dumps(doc), store='', opts=opts),
            dict(receipt=json.dumps(altered), store=store, opts=opts),
            dict(receipt=json.dumps(stale), store=store, opts=opts),
            dict(receipt=json.dumps(doc), store=store, opts={}),
            dict(receipt='{"format":"expectrail.rc/v0"}', store=store, opts=opts),
        ]
        code = '''const panel = require(process.argv[1]); let data='';
process.stdin.on('data', d => data += d);
process.stdin.on('end', async () => {
 const result=[]; for (const c of JSON.parse(data)) result.push(await panel.checkTexts(c.receipt,c.store,c.opts));
 process.stdout.write(JSON.stringify(result));
});'''
        got = subprocess.run(['node', '-e', code, str(PANEL)], input=json.dumps(cases), capture_output=True, text=True, timeout=60)
        self.assertEqual(got.returncode, 0, got.stderr)
        result = json.loads(got.stdout)
        self.assertEqual([r['outcome'] for r in result], ['unavailable','clearance','no-clearance','invalid','no-clearance','no-clearance','no-clearance','invalid'])
        self.assertIn('unknown issuer', ' '.join(result[2]['report']['reasons']))
        self.assertTrue(result[1]['report']['valid_signature'])
        self.assertTrue(result[1]['report']['complete'])


class OfflineBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tools.require_tool('Playwright Chromium')

    @contextmanager
    def page(self, mode='disabled', *, javascript=True, corrupt=None):
        from playwright.sync_api import sync_playwright
        from harness.web.run import CHROMIUM_ARGS, game_env
        release = threading.Event()
        posts, external, errors = [], [], []

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(ROOT/'docs'), **kwargs)

            def log_message(self, *args):
                pass

            def do_POST(self):
                posts.append(self.path)
                self.send_error(500, 'No run or upload is permitted by this offline test')

            def do_GET(self):
                if self.path == '/api/health':
                    if mode == 'unreachable':
                        self.close_connection = True
                        return
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    if mode == 'body-hangs':
                        self.wfile.write(b'{'); self.wfile.flush()
                        release.wait(20)
                    else:
                        self.wfile.write(b'{"format":"expectrail.run-it-api/v1","kind":"health","open":false}')
                    return
                if self.path == '/run-it/earlier/builder1-recorded-clean/findings.json' and corrupt:
                    doc = json.loads((CACHE/'builder1-recorded-clean/findings.json').read_text())
                    if corrupt == 'counts':
                        doc['counts']['passed'] += 1
                    else:
                        doc['checks'][0]['observed']['after']['engine'] = 'fail'
                    raw = json.dumps(doc).encode()
                    self.send_response(200); self.send_header('Content-Type', 'application/json')
                    self.end_headers(); self.wfile.write(raw)
                    return
                super().do_GET()

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(args=CHROMIUM_ARGS, env=game_env())
                context = browser.new_context(java_script_enabled=javascript, viewport={'width': 1280, 'height': 900})

                def local_only(route):
                    if urlsplit(route.request.url).hostname != '127.0.0.1':
                        external.append(route.request.url); route.abort()
                    else:
                        route.continue_()

                context.route('**/*', local_only)
                page = context.new_page()
                page.on('pageerror', lambda exc: errors.append(str(exc)))
                page.goto(f'http://127.0.0.1:{server.server_port}/run-it/#local', wait_until='domcontentloaded')
                try:
                    yield page
                    self.assertEqual(errors, [])
                    self.assertEqual(external, [])
                    self.assertEqual(posts, [])
                finally:
                    browser.close()
        finally:
            release.set(); server.shutdown(); server.server_close()

    def show(self, page, sample, verdict):
        button = page.locator(f'button[data-show="{sample}"]')
        button.wait_for(state='visible')
        self.assertIn('saved earlier', button.inner_text())
        button.click()
        page.wait_for_function('(title) => document.querySelector("#verdict-title").textContent === title', arg=verdict)
        self.assertIn('Earlier saved run, from 2026-11-13', page.locator('#run-when').text_content())
        self.assertTrue(page.locator('#saved-findings').is_visible())
        self.assertGreater(page.locator('#saved-findings tr').count(), 1)
        self.assertFalse(page.locator('#viewer').is_visible())
        self.assertIn('not yet available', page.locator('#receipt-availability').inner_text())
        self.assertTrue(page.locator('#receipt-check').is_disabled())

    def test_disabled_and_unreachable_worker_show_all_three_saved_results_on_desktop_and_phone(self):
        for mode in ('disabled', 'unreachable'):
            with self.subTest(mode=mode), self.page(mode) as page:
                page.wait_for_selector('#service[data-open="no"]')
                self.assertTrue(page.locator('#earlier').is_visible())
                for sample, title in [('clean', 'Accepted'), ('fall-through-bug', 'Rejected'), ('fall-through-repair', 'Accepted')]:
                    self.show(page, sample, title)
                self.assertEqual(page.locator('button[data-run]:enabled').count(), 0)
                page.set_viewport_size({'width': 375, 'height': 812})
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 375)

    def test_timeout_covers_a_worker_that_sends_headers_but_never_finishes_its_body(self):
        with self.page('body-hangs') as page:
            # Evidence is usable while the service check is still waiting.
            self.show(page, 'fall-through-bug', 'Rejected')
            page.wait_for_selector('#service[data-open="no"]', timeout=9000)
            self.assertIn('not reachable', page.locator('#service').inner_text())

    def test_inconsistent_saved_findings_never_show_a_green_accept(self):
        for corrupt in ('counts', 'observers'):
            with self.subTest(corrupt=corrupt), self.page(corrupt=corrupt) as page:
                page.locator('button[data-show="clean"]').wait_for(state='visible')
                page.locator('button[data-show="clean"]').click()
                page.wait_for_function('() => document.querySelector("#verdict-title").textContent === "Cannot tell"')
                self.assertEqual(page.locator('#verdict').get_attribute('data-tone'), 'review')

    def test_without_javascript_static_earlier_evidence_is_still_labelled_and_linked(self):
        with self.page(javascript=False) as page:
            self.assertTrue(page.locator('#earlier').is_visible())
            self.assertEqual(page.locator('#earlier a[href$="findings.json"]').count(), 3)
            self.assertFalse(page.locator('#service').is_visible())
            self.assertFalse(page.locator('#samples').is_visible())
            self.assertIn('not yet available', page.locator('#receipt-availability').inner_text())

    def test_receipt_file_clearance_never_becomes_a_receipt_for_the_saved_run(self):
        doc, store, opts, key, sign = receipt_fixture()
        with self.page() as page:
            self.show(page, 'fall-through-bug', 'Rejected')
            page.locator('#receipt-tools summary').click()

            def upload(selector, text):
                page.locator(selector).set_input_files(dict(name='test-only.json', mimeType='application/json', buffer=text.encode()))

            upload('#receipt-file', json.dumps(doc))
            upload('#receipt-store', store)
            for name in ('head', 'build', 'policy'):
                page.locator('#receipt-'+name).fill(opts['expect'+name.title()])
            page.locator('#receipt-check').click()
            page.wait_for_selector('#receipt-outcome[data-tone="pass"]:not([hidden])')
            self.assertIn('selected file', page.locator('#receipt-title').inner_text())
            self.assertIn('not yet available', page.locator('#receipt-availability').inner_text())
            self.assertEqual(page.locator('#verdict-title').inner_text(), 'Rejected')
            page.locator('#receipt-head').fill('e'*64)
            self.assertFalse(page.locator('#receipt-outcome').is_visible())
            page.locator('#receipt-check').click()
            page.wait_for_selector('#receipt-outcome[data-tone="review"]:not([hidden])')
            self.assertIn('No clearance', page.locator('#receipt-title').inner_text())
            page.locator('#receipt-head').fill('b'*64)
            upload('#receipt-file', '{"format":"expectrail.rc/v0"}')
            page.locator('#receipt-check').click()
            page.wait_for_selector('#receipt-outcome[data-tone="review"]:not([hidden])')
            self.show(page, 'clean', 'Accepted')
            self.assertFalse(page.locator('#receipt-outcome').is_visible())
