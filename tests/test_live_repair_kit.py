"""Current model admission and spend-free kit planning; no live calls."""
import http.server
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
from unittest import mock

from expectrail import fixer_budget,providers,spend
from tools import live_repair_kit as kit


class CurrentModel(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        spend.reset_for_tests();self.addCleanup(spend.reset_for_tests)
        p=mock.patch.dict(os.environ,{'EXPECTRAIL_FIXER_INVOCATION_USD_CAP':'6','EXPECTRAIL_MUSE_USD_CAP':'20',
            'EXPECTRAIL_MODEL_MONTH_LEDGER':str(self.root/'month.json')},clear=True);p.start();self.addCleanup(p.stop)
        self.cfg=providers.ProviderConfig('openai','openai','https://api.openai.com/v1',kit.MODEL,'offline-only')
        self.events=[];self.get_status=200;self.post_status=200;self.output=3
        owner=self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                owner.events.append(('GET',None));self.answer(owner.get_status,{'id':owner.cfg.model})
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.events.append(('POST',data));self.answer(owner.post_status,{'choices':[{'message':{'content':'patch'}}],
                    'usage':{'prompt_tokens':5,'completion_tokens':owner.output}})
            def answer(self,status,doc):
                data=json.dumps(doc).encode();self.send_response(status);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        s=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);s.daemon_threads=True
        threading.Thread(target=s.serve_forever,daemon=True).start();self.addCleanup(s.server_close);self.addCleanup(s.shutdown)
        real=urllib.request.build_opener
        def build(*handlers):
            opener=real(*handlers);old=opener.open
            def local(req,**kwargs):
                clone=urllib.request.Request(f'http://127.0.0.1:{s.server_address[1]}',data=req.data,method=req.get_method())
                return old(clone,**kwargs)
            opener.open=local;return opener
        p=mock.patch.object(urllib.request,'build_opener',side_effect=build);p.start();self.addCleanup(p.stop)
    def start(self):return fixer_budget.start(self.root/'invocation.json',config=self.cfg)
    def send(self,meter):return providers.chat_completion([{'role':'user','content':'floor bug'}],role='FIXER',config=self.cfg,invocation=meter)

    def test_current_model_has_explicit_inclusive_output_limit_and_standard_tier(self):
        meter=self.start();self.send(meter);meter.finish()
        self.assertEqual([e[0] for e in self.events],['GET','POST'])
        body=self.events[1][1];self.assertEqual(body['max_completion_tokens'],4096)
        self.assertEqual(body['service_tier'],'default');self.assertNotIn('max_tokens',body);self.assertNotIn('temperature',body)
        doc=fixer_budget.read(self.root/'invocation.json');row=doc['requests'][0]
        self.assertEqual(row['inputTokenBound'],1050000)
        self.assertLess(row['byteTokenBound'],row['inputTokenBound'])
        self.assertEqual(row['reservedNanoUsd'],5842584000)
        self.assertEqual(doc['availability']['status'],'available')

    def test_known_deprecated_model_refuses_without_any_network(self):
        self.cfg=providers.ProviderConfig('openai','openai','https://api.openai.com/v1','gpt-4o','offline-only')
        with self.assertRaises(spend.BudgetStop) as c:self.start()
        self.assertEqual(c.exception.code,'fixer-model-unavailable');self.assertEqual(self.events,[])

    def test_recorded_withdrawal_refuses_before_any_send(self):
        reader=spend.read_provider_capability
        def withdrawn(path):
            doc=reader(path)
            for price in doc['tokenPrices']:price['status']='withdrawn'
            return doc
        with mock.patch.object(spend,'read_provider_capability',side_effect=withdrawn):
            with self.assertRaises(spend.BudgetStop) as c:self.start()
        self.assertEqual(c.exception.code,'fixer-model-unavailable');self.assertEqual(self.events,[])

    def test_remote_withdrawal_metadata_refuses_before_any_inference(self):
        self.get_status=404
        with self.assertRaises(spend.BudgetStop) as c:self.start()
        self.assertEqual(c.exception.code,'fixer-model-unavailable')
        self.assertEqual(self.events,[('GET',None)])
        self.assertEqual(fixer_budget.read(self.root/'invocation.json')['admittedRequests'],0)

    def test_withdrawal_race_never_retries_or_falls_back(self):
        meter=self.start();self.post_status=404
        with self.assertRaises(spend.BudgetStop) as c:self.send(meter)
        self.assertEqual(c.exception.code,'fixer-model-unavailable')
        self.assertEqual([x[0] for x in self.events],['GET','POST'])
        self.assertEqual(fixer_budget.read(self.root/'invocation.json')['admittedRequests'],1)

    def test_stale_record_refuses_before_any_send(self):
        reader=spend.read_provider_capability
        def expired(path):
            doc=reader(path)
            for price in doc['tokenPrices']:price['validUntil']='2000-01-01'
            return doc
        with mock.patch.object(spend,'read_provider_capability',side_effect=expired):
            with self.assertRaises(spend.BudgetStop) as c:self.start()
        self.assertEqual(c.exception.code,'fixer-model-unavailable');self.assertEqual(self.events,[])

    def test_no_ledger_or_cap_means_no_metadata_or_inference_send(self):
        del os.environ['EXPECTRAIL_MODEL_MONTH_LEDGER']
        with self.assertRaises(spend.BudgetStop):self.start()
        self.assertEqual(self.events,[])

    def test_usage_violation_prevents_later_send(self):
        meter=self.start();self.output=4097
        for _ in range(2):
            with self.assertRaises(spend.BudgetStop) as c:self.send(meter)
            self.assertEqual(c.exception.code,'fixer-provider-violation')
        self.assertEqual([e[0] for e in self.events],['GET','POST'])


class KitPlan(unittest.TestCase):
    def test_default_plan_is_ten_dollars_and_makes_no_request(self):
        with mock.patch('urllib.request.urlopen',side_effect=AssertionError('no network')):
            args=kit.parser().parse_args([]);doc=kit.plan(args)
        self.assertEqual(doc['totalEnvelopeUsd'],'10');self.assertEqual(doc['paidCallsMadeByPlan'],0)
        self.assertEqual(doc['attempts'],1);self.assertEqual(doc['model'],kit.MODEL)
    def test_unpriced_extra_roles_and_bad_caps_refused(self):
        for argv in [['--spec','1'],['--attempts','4'],['--fixer-invocation','7','--fixer-total','6']]:
            with self.subTest(argv=argv),self.assertRaises(ValueError):kit.plan(kit.parser().parse_args(argv))
    def test_live_environment_forces_full_vision_and_an_isolated_fresh_cache(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ,{
                'EXPECTRAIL_MODEL_MONTH_LEDGER':tmp+'/models.json',
                'EXPECTRAIL_VISION_MONTH_LEDGER':tmp+'/vision.json',
                'EXPECTRAIL_SAM_CONFIRM':'0','EXPECTRAIL_KEYFRAMES_ONLY':'1',
                'EXPECTRAIL_SAM_CACHE':'old-shared-cache'},clear=True):
            args=kit.parser().parse_args(['--out',tmp+'/new-run'])
            env=kit.environment(args)
            self.assertEqual(env['EXPECTRAIL_SAM_CONFIRM'],'1')
            self.assertEqual(env['EXPECTRAIL_KEYFRAMES_ONLY'],'0')
            # The kit resolves --out; on macOS every temporary folder is reached through a link (#378).
            self.assertEqual(env['EXPECTRAIL_SAM_CACHE'],os.path.realpath(tmp)+'/new-run/sam-cache')
    def test_existing_fixer_context_contains_the_real_fault_and_ground_layer(self):
        from agents.byo_fixer import _collect_candidate_files
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'public-report';project=kit.prepare(root)
            text=_collect_candidate_files(project)
            self.assertIn('=== FILE: project.godot ===',text)
            self.assertIn('2d_physics/layer_5="ground"',text)
            self.assertIn('=== FILE: player/player.tscn ===',text)
            self.assertIn('collision_mask = 14',text)
            self.assertLessEqual(text.count('=== FILE:'),12)
    def test_command_is_the_real_isolated_ingest_opt_in(self):
        args=kit.parser().parse_args([]);cmd=kit.command(Path('artifact'),args)
        self.assertIn('expectrail.cli',cmd);self.assertIn('ingest',cmd)
        self.assertIn('--repair-agent',cmd);self.assertIn('llm-patch',cmd);self.assertIn('isolated',cmd)
        self.assertNotIn('--propose',cmd)


class RecordedRealRehearsal(unittest.TestCase):
    """Optional checks of the real command evidence produced by the rehearsal tool."""
    def check(self,ending):
        root=os.environ.get('EXPECTRAIL_REHEARSAL_EVIDENCE')
        if not root:self.skipTest('real Godot localhost rehearsal evidence not selected')
        from tools.live_repair_rehearsal import verify_evidence
        return verify_evidence(Path(root)/ending,ending)
    def test_real_accepted_repair_by_both_observers(self):self.check('accept')
    def test_real_candidate_rejected_by_the_gate(self):self.check('reject')
    def test_real_mid_run_budget_stop_no_candidate_or_retry(self):self.check('cap')
