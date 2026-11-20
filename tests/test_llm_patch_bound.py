"""Controlled FIXER sender against a local HTTP server. No model calls."""
import concurrent.futures
import hashlib
import http.server
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from expectrail import fixer_budget, providers, spend


class LlmPatchBound(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        spend.reset_for_tests();self.addCleanup(spend.reset_for_tests)
        env=mock.patch.dict(os.environ,{'EXPECTRAIL_FIXER_INVOCATION_USD_CAP':'.25',
            'EXPECTRAIL_MUSE_USD_CAP':'1','EXPECTRAIL_MODEL_MONTH_LEDGER':str(self.root/'month.json')},clear=True)
        env.start();self.addCleanup(env.stop)
        self.cfg=providers.ProviderConfig('openai','openai','https://api.openai.com/v1','gpt-4o','stand-in')
        self.messages=[{'role':'user','content':'fix the floor; café 🐈'}]
        real_capability=spend.read_provider_capability
        def historical_fixture(path):
            doc=real_capability(path)
            for price in doc.get('tokenPrices',[]):
                if price['model']=='gpt-4o':price['status']='active'
            return doc
        patch=mock.patch.object(spend,'read_provider_capability',side_effect=historical_fixture)
        patch.start();self.addCleanup(patch.stop)
        self.received=[];self.actions=[];self.output=3;self.input=7;self.omit_usage=False
        self.reply='--- a/player.gd\n+++ b/player.gd\n@@ -1 +1 @@\n-broken\n+fixed\n'
        owner=self
        class Model(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                data=json.dumps({'id':owner.cfg.model}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def do_POST(self):
                body=self.rfile.read(int(self.headers['Content-Length']));owner.received.append(body)
                status=owner.actions.pop(0) if owner.actions else 200
                result={'choices':[{'message':{'content':owner.reply}}]}
                if not owner.omit_usage:result['usage']={'prompt_tokens':owner.input,'completion_tokens':owner.output}
                if status==400:result={'error':'response_format json_schema rejected'}
                data=json.dumps(result).encode();self.send_response(status)
                if status==302:self.send_header('Location','https://unpriced.invalid/stolen')
                self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def log_message(self,*args):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Model)
        server.daemon_threads=True
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        # Trusted test harness reroutes only the socket; admission sees the production
        # provider/model/URL and the server receives the identical serialized bytes.
        real_build=urllib.request.build_opener
        port=server.server_address[1]
        def build(*handlers):
            opener=real_build(*handlers)
            real_open=opener.open
            def local_open(req,timeout):
                local=urllib.request.Request(f'http://127.0.0.1:{port}/v1/chat/completions',
                    data=req.data,headers=dict(req.header_items()),method=req.method)
                return real_open(local,timeout=timeout)
            opener.open=local_open
            return opener
        patch=mock.patch.object(providers.urllib.request,'build_opener',side_effect=build)
        patch.start();self.addCleanup(patch.stop)
        patch=mock.patch.object(providers.time,'sleep');patch.start();self.addCleanup(patch.stop)

    def meter(self):return fixer_budget.start(self.root/'invocation.json',config=self.cfg)
    def send(self,meter,**kwargs):
        return providers.chat_completion(self.messages,role='FIXER',config=self.cfg,invocation=meter,**kwargs)
    def read(self):return fixer_budget.read(self.root/'invocation.json')
    def price(self):
        _,_,p=providers.build_http_payload(self.cfg,self.messages)
        return (len(json.dumps(p).encode())+1024+64)*2500+4096*10000

    def test_exact_body_bound_explicit_output_cap_and_usage_beside_reservation(self):
        meter=self.meter();self.send(meter);meter.finish();doc=self.read();row=doc['requests'][0]
        self.assertEqual(row['bodySha256'],hashlib.sha256(self.received[0]).hexdigest())
        self.assertEqual(row['bodyBytes'],len(self.received[0]))
        self.assertEqual(row['inputTokenBound'],len(self.received[0])+1024+64)
        self.assertEqual(json.loads(self.received[0])['max_tokens'],4096)
        self.assertEqual(row['reservedNanoUsd'],self.price())
        self.assertEqual(row['reportedUsage'],{'inputTokens':7,'outputTokens':3})
        self.assertEqual(spend.METER.snapshot_roles()['muse']['reserved'],.25)
        self.assertEqual(spend.read_model_month(self.root/'month.json')['spentUsd'],1)

    def test_maximum_exceeds_remaining_nothing_sent_and_no_refund(self):
        os.environ[fixer_budget.ENV]=str(self.price()/1e9)
        meter=self.meter();self.send(meter)
        for _ in range(2):
            with self.assertRaises(spend.BudgetStop) as caught:self.send(meter)
            self.assertEqual(caught.exception.code,'fixer-invocation-cap')
        doc=self.read();self.assertEqual(len(self.received),1)
        self.assertEqual(doc['reservedNanoUsd'],self.price());self.assertEqual(doc['admittedRequests'],1)

    def test_first_request_too_expensive_never_sent(self):
        os.environ[fixer_budget.ENV]='0.000001';meter=self.meter()
        with self.assertRaises(spend.BudgetStop):self.send(meter)
        self.assertEqual(self.received,[]);self.assertEqual(self.read()['admittedRequests'],0)

    def test_missing_cap_and_unknown_model_refused(self):
        del os.environ[fixer_budget.ENV]
        with self.assertRaises(spend.BudgetStop):self.meter()
        os.environ[fixer_budget.ENV]='.25'
        self.cfg=providers.ProviderConfig('openai','openai','https://api.openai.com/v1','unknown','stand-in')
        with self.assertRaises(spend.BudgetStop) as caught:self.meter()
        self.assertEqual(caught.exception.code,'fixer-bound-unavailable');self.assertEqual(self.received,[])

    def test_unpriced_endpoint_refused(self):
        self.cfg=providers.ProviderConfig('openai','openai','https://elsewhere.invalid/v1','gpt-4o','stand-in')
        with self.assertRaises(spend.BudgetStop):self.meter()
        self.assertEqual(self.received,[])

    def test_provider_output_violation_recorded_and_stops_future_sends(self):
        self.output=4097;meter=self.meter()
        for _ in range(2):
            with self.assertRaises(spend.BudgetStop) as caught:self.send(meter)
            self.assertEqual(caught.exception.code,'fixer-provider-violation')
        doc=self.read();self.assertEqual(doc['outputTokensObserved'],4097)
        self.assertEqual(doc['requests'][0]['reportedUsage']['outputTokens'],4097)
        self.assertEqual(len(self.received),1)

    def test_input_violation_and_missing_usage_stop(self):
        meter=self.meter();self.input=1000000
        with self.assertRaises(spend.BudgetStop):self.send(meter)
        self.assertEqual(self.read()['stopReason'],'fixer-provider-violation')

    def test_missing_usage_stops(self):
        self.omit_usage=True;meter=self.meter()
        with self.assertRaises(spend.BudgetStop):self.send(meter)
        self.assertIsNone(self.read()['requests'][0]['reportedUsage'])

    def test_concurrent_requests_cannot_overshoot(self):
        os.environ[fixer_budget.ENV]=str(2*self.price()/1e9);meter=self.meter()
        barrier=threading.Barrier(6)
        def attempt(_):
            barrier.wait()
            try:self.send(meter);return True
            except spend.BudgetStop:return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(attempt,range(6)))
        self.assertEqual(sum(results),2);self.assertEqual(len(self.received),2)
        doc=self.read();self.assertEqual(doc['reservedNanoUsd'],2*self.price())
        self.assertLessEqual(doc['reservedNanoUsd'],doc['capNanoUsd'])

    def test_retry_reserves_again_without_refund(self):
        self.actions=[500,200];meter=self.meter();self.send(meter)
        doc=self.read();self.assertEqual(len(self.received),2)
        self.assertEqual(doc['reservedNanoUsd'],2*self.price())
        self.assertEqual(doc['inputTokensObserved'],14)

    def test_retry_refused_when_remainder_insufficient(self):
        os.environ[fixer_budget.ENV]=str(self.price()/1e9)
        self.actions=[500,200];meter=self.meter()
        with self.assertRaises(spend.BudgetStop):self.send(meter)
        self.assertEqual(len(self.received),1)

    def test_schema_fallback_is_another_reservation(self):
        self.actions=[400,200];meter=self.meter();self.send(meter,json_schema={'type':'object'})
        doc=self.read();self.assertEqual(doc['admittedRequests'],2)
        self.assertIn('response_format',json.loads(self.received[0]))
        self.assertNotIn('response_format',json.loads(self.received[1]))
        self.assertGreater(doc['requests'][0]['reservedNanoUsd'],doc['requests'][1]['reservedNanoUsd'])
        self.assertIsNone(doc['requests'][0]['reportedUsage'])

    def test_redirect_cannot_forward_an_unmetered_request(self):
        self.actions=[302];meter=self.meter()
        with self.assertRaises(RuntimeError):self.send(meter)
        self.assertEqual(len(self.received),1)

    def test_sender_without_admission_refuses(self):
        with self.assertRaises(spend.BudgetStop):
            providers.chat_completion(self.messages,role='FIXER',config=self.cfg)
        self.assertEqual(self.received,[])

    def test_multimodal_request_is_refused(self):
        meter=self.meter();self.messages=[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,AA=='}}]}]
        with self.assertRaises(spend.BudgetStop):self.send(meter)
        self.assertEqual(self.received,[])

    def test_llm_patch_entry_uses_controlled_admission(self):
        from agents import byo_fixer
        work=self.root/'game';work.mkdir();(work/'player.gd').write_text('broken\n')
        with mock.patch.object(byo_fixer,'resolve_provider',return_value=self.cfg):
            result=byo_fixer.run_llm_patch_fixer('floor bug',work,self.root/'candidate.patch')
        self.assertEqual(result['agent'],'llm-patch');self.assertEqual(len(self.received),1)
        # The entrypoint record lives beside its output patch.
        doc=fixer_budget.read(self.root/'fixer-invocation.json')
        self.assertEqual(doc['status'],'completed');self.assertEqual(doc['admittedRequests'],1)

    def test_tariff_contract_round_trip_and_unknown_fields_refused(self):
        source=Path(__file__).resolve().parents[1]/'contracts/examples/provider-capabilities/openai.json'
        doc=spend.read_provider_capability(source)
        spend.write_provider_capability(doc,self.root/'capability.json')
        self.assertEqual(spend.read_provider_capability(self.root/'capability.json'),doc)
        doc['tokenPrices'][0]['invented']=1
        with self.assertRaises(ValueError):spend.write_provider_capability(doc)

    def test_record_tampering_is_refused(self):
        from agents.fixer_meter import write
        meter=self.meter();self.send(meter);doc=self.read()
        doc['requests'][0]['reservedNanoUsd']+=1
        write(self.root/'invocation.json',doc)
        with self.assertRaises(ValueError):self.read()

    def test_failed_durable_admission_never_sends(self):
        meter=self.meter()
        with mock.patch.object(meter,'persist',side_effect=OSError('stand-in write failure')):
            with self.assertRaises(spend.BudgetStop) as caught:self.send(meter)
        self.assertEqual(caught.exception.code,'fixer-meter-unavailable')
        self.assertEqual(self.received,[])

    def test_missing_month_ledger_and_aggregate_cap_refuse_before_send(self):
        del os.environ[spend.MODEL_LEDGER_ENV]
        with self.assertRaises(spend.BudgetStop):self.meter()
        os.environ[spend.MODEL_LEDGER_ENV]=str(self.root/'month.json')
        os.environ['EXPECTRAIL_MUSE_USD_CAP']='.01'
        with self.assertRaises(spend.BudgetStop):self.meter()
        self.assertEqual(self.received,[])

    def test_provider_violation_in_existing_repair_loop_never_verifies_or_retries(self):
        from tests import test_repair_command as repairs
        from expectrail import repair
        from agents import fixer
        case=repairs.RepairCommandTest();case.setUp();self.addCleanup(case.doCleanups)
        def attempt(req,folder,**kw):
            self.assertEqual(kw['agent'],'llm-patch')
            meter=fixer_budget.start(folder/'fixer-invocation.json',config=self.cfg)
            self.output=4097
            self.send(meter)
            self.fail('provider violation must stop before a candidate')
        with mock.patch.object(fixer,'run_fixer',side_effect=attempt) as transport, mock.patch.object(repair,'_child') as child:
            path,doc=repair.repair(case.jobs,case.parent,agent='llm-patch')
        self.assertEqual(transport.call_count,1);child.assert_not_called()
        self.assertEqual(doc['result']['decision'],'needs-review')
        self.assertEqual(doc['attempts'][0]['budgetStop'],'fixer-provider-violation')
        self.assertEqual(doc['fixer'],{'source':'llm-patch','sandboxed':False,'providerOnly':True})
        proof=path.parent/doc['attempts'][0]['fixerInvocation']
        self.assertEqual(hashlib.sha256(proof.read_bytes()).hexdigest(),doc['attempts'][0]['fixerInvocationSha256'])
        counter=fixer_budget.read(proof)
        self.assertEqual(counter['outputTokensObserved'],4097)

    def test_ingest_cli_has_trusted_agent_option(self):
        from expectrail.orchestrator import cli
        import contextlib
        import io
        out=io.StringIO()
        with contextlib.redirect_stdout(out),self.assertRaises(SystemExit) as caught:
            cli.main(['ingest','--help'])
        self.assertEqual(caught.exception.code,0)
        self.assertIn('--repair-agent {muse-code,llm-patch}',out.getvalue())

    def test_existing_repair_loop_uses_llm_patch_and_retains_completed_counter(self):
        from tests import test_repair_command as repairs
        from expectrail import repair
        from agents import byo_fixer
        case=repairs.RepairCommandTest();case.setUp();self.addCleanup(case.doCleanups)
        self.reply=repairs.FIX.read_text()
        child={**case.jobs.status(case.parent),'decision':'needs-review'}
        with mock.patch.object(byo_fixer,'resolve_provider',return_value=self.cfg), mock.patch.object(repair,'_child',return_value=child) as verify:
            path,doc=repair.repair(case.jobs,case.parent,agent='llm-patch')
        self.assertEqual(len(self.received),1);self.assertEqual(verify.call_count,1)
        self.assertTrue(verify.call_args.kwargs['require_isolation'])
        self.assertEqual(doc['result']['decision'],'needs-review')
        self.assertEqual(doc['attempts'][0]['gateDecision'],'needs-review')
        self.assertEqual(doc['fixer'],{'source':'llm-patch','sandboxed':False,'providerOnly':True})
        proof=path.parent/doc['attempts'][0]['fixerInvocation']
        self.assertEqual(hashlib.sha256(proof.read_bytes()).hexdigest(),doc['attempts'][0]['fixerInvocationSha256'])
        counter=fixer_budget.read(proof)
        self.assertEqual(counter['status'],'completed')
        self.assertEqual(counter['admittedRequests'],1)

    def test_exactly_exhausted_invocation_is_review_stop_before_patch_is_returned(self):
        from agents import byo_fixer
        work=self.root/'game';work.mkdir();(work/'player.gd').write_text('broken\n')
        # First record the exact controlled request maximum using the same prompt.
        with mock.patch.object(byo_fixer,'resolve_provider',return_value=self.cfg):
            byo_fixer.run_llm_patch_fixer('floor bug',work,self.root/'candidate.patch')
        amount=fixer_budget.read(self.root/'fixer-invocation.json')['reservedNanoUsd']
        (self.root/'candidate.patch').unlink()
        os.environ[fixer_budget.ENV]=str(amount/1e9)
        with mock.patch.object(byo_fixer,'resolve_provider',return_value=self.cfg):
            with self.assertRaises(spend.BudgetStop) as caught:
                byo_fixer.run_llm_patch_fixer('floor bug',work,self.root/'candidate.patch')
        self.assertEqual(caught.exception.code,'fixer-invocation-cap')
        self.assertFalse((self.root/'candidate.patch').exists())
        self.assertEqual(fixer_budget.read(self.root/'fixer-invocation.json')['status'],'stopped')

    def test_ingest_opt_in_selects_controlled_sender_after_approved_reproduction(self):
        from tests import test_ingest_repair as intake
        from expectrail import repair
        from agents import byo_fixer
        case=intake.IngestRepair();case.setUp();self.addCleanup(case.doCleanups);case.broken()
        self.reply=case.fix.read_text()
        def candidate(st,original,checkout,inputs,**kwargs):
            self.assertTrue(kwargs['require_isolation'])
            return {**st.status(case.created[0]),'decision':'needs-review'}
        with mock.patch.object(byo_fixer,'resolve_provider',return_value=self.cfg),mock.patch.object(repair,'_child',side_effect=candidate) as gate:
            code,text=case.invoke('--repair','--repair-agent','llm-patch')
        self.assertEqual(code,2,text);doc=json.loads(text)
        self.assertEqual(doc['reproduction']['kind'],'approved')
        self.assertTrue(doc['repairAttempted'])
        self.assertEqual(doc['fixer']['source'],'llm-patch')
        self.assertEqual(doc['result']['decision'],'needs-review')
        self.assertEqual(len(self.received),1);self.assertEqual(gate.call_count,1)
