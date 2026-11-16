"""Trusted admission with a real stand-in HTTP server; never a live model or CLI."""
import contextlib
import http.client
import http.server
import json
import os
from pathlib import Path
from types import SimpleNamespace
import socket
import tempfile
import threading
import unittest
from unittest import mock

from agents import fixer_meter, muse_gateway_addon as addon, sandbox
from expectrail import contracts, fixer_budget, spend
from tests import test_repair_command as repairs


class Headers(dict):
    def get_all(self,key):return [self[key]]
    def set_all(self,key,values):self[key]=', '.join(values)


class Response:
    @staticmethod
    def make(status,body,headers):
        return SimpleNamespace(status_code=status,raw_content=body,stream=None)


class InvocationCap(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        spend.reset_for_tests();self.addCleanup(spend.reset_for_tests)
        env=mock.patch.dict(os.environ,{'EXPECTRAIL_MUSE_USD_CAP':'1',
            'EXPECTRAIL_MODEL_MONTH_LEDGER':str(self.root/'month.json')},clear=True)
        env.start();self.addCleanup(env.stop)
        module=mock.patch.dict('sys.modules',{'mitmproxy':SimpleNamespace(http=SimpleNamespace(Response=Response))})
        module.start();self.addCleanup(module.stop)
        log=mock.patch.object(addon,'LOG',str(self.root/'proxy.jsonl'));log.start();self.addCleanup(log.stop)

    def meter(self,cap=300_000_000,price=100_000_000):
        return fixer_budget.fixture(self.root/'invocation.json',cap_nano=cap,request_nano=price)

    def server(self,handler):
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),handler)
        server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return server.server_address[1]

    def proxy(self,meter):
        counts=[]
        class Model(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length','0')))
                counts.append(self.path)
                body=json.dumps({'usage':{'input_tokens':7,'output_tokens':3}}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def log_message(self,*a):pass
        upstream=self.server(Model);gateway=addon.Gateway(meter=meter)
        class Proxy(http.server.BaseHTTPRequestHandler):
            def do_POST(self):self.handle_model()
            def do_GET(self):self.handle_model()
            def handle_model(self):
                body=self.rfile.read(int(self.headers.get('Content-Length','0')))
                host=self.headers.get('Host','').split(':')[0]
                flow=SimpleNamespace(request=SimpleNamespace(pretty_host=host,method=self.command,
                    path=self.path,port=443,scheme='https',headers=Headers({'authorization':'Bearer fixture'}),raw_content=body),
                    response=None,metadata={})
                gateway.request(flow)
                if flow.response is None:
                    conn=http.client.HTTPConnection('127.0.0.1',upstream,timeout=5)
                    conn.request('POST',self.path,body=body);answer=conn.getresponse();data=answer.read();conn.close()
                    flow.response=Response.make(answer.status,data,{})
                    gateway.response(flow)
                self.send_response(flow.response.status_code);self.send_header('Content-Length',str(len(flow.response.raw_content)));self.end_headers();self.wfile.write(flow.response.raw_content)
            def log_message(self,*a):pass
        return self.server(Proxy),counts

    def send(self,port,path='/v1/responses',host='api.meta.ai',method='POST'):
        conn=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
        conn.request(method,path,body=b'{"input":"stand-in"}',headers={'Host':host})
        reply=conn.getresponse();reply.read();status=reply.status;conn.close();return status

    def test_fixed_price_standin_cut_off_at_cap_no_send_after_stop(self):
        meter=self.meter();port,upstream=self.proxy(meter)
        self.assertEqual([self.send(port) for _ in range(3)],[200]*3)
        self.assertEqual([self.send(port) for _ in range(5)],[429]*5)
        self.assertEqual(len(upstream),3)
        doc=fixer_budget.read(self.root/'invocation.json')
        self.assertEqual(doc['admittedRequests'],3);self.assertEqual(doc['reservedNanoUsd'],300_000_000)
        self.assertEqual((doc['inputTokensObserved'],doc['outputTokensObserved']),(21,9))
        self.assertEqual(doc['stopReason'],'fixer-invocation-cap')
        self.assertEqual(doc['basis'],'fixed-price-fixture')

    def test_other_hosts_methods_and_paths_get_nothing_even_before_quota(self):
        meter=self.meter();port,upstream=self.proxy(meter)
        for args in [('/v1/other','api.meta.ai','POST'),('/v1/responses?x=1','api.meta.ai','POST'),
                     ('/v1/responses','evil.example','POST'),('/v1/responses','x.meta.ai','POST'),
                     ('/v1/responses','api.meta.ai','GET')]:
            self.assertEqual(self.send(port,*args),403)
        self.assertEqual(upstream,[]);self.assertEqual(fixer_budget.read(self.root/'invocation.json')['admittedRequests'],0)

    def test_real_bwrap_has_only_the_capped_socket_route(self):
        from tests.tool_requirements import require_tool
        require_tool('Bubblewrap')
        import shutil
        from agents import gateway
        meter=self.meter();port,upstream=self.proxy(meter)
        directory=self.root/'bridge';directory.mkdir()
        shutil.copyfile(gateway.BRIDGE,directory/'bridge.py')
        (directory/'ca.pem').write_text('fixture, not used by the HTTP stand-in')
        bridge=gateway.UnixBridge(directory/'gw.sock',port);self.addCleanup(bridge.close)
        gw=gateway.Gateway(proxy='http://127.0.0.1:'+str(port),ca=directory/'ca.pem',
            placeholder='fixture',real='fixture',dir=directory,log=self.root/'log')
        workspace=self.root/'workspace';workspace.mkdir()
        client="""import socket,http.client
try:
 open(PRIVATE_COUNTER, 'r').read()
except OSError:pass
else:raise SystemExit('host meter was mounted into fixer')
try:
 s=socket.create_connection(('127.0.0.1',UPSTREAM),timeout=1)
except OSError:pass
else:raise SystemExit('direct host route escaped namespace')
for want,path in [(200,'/v1/responses')]*3+[(429,'/v1/responses'),(403,'/other')]:
 c=http.client.HTTPConnection('127.0.0.1',8899,timeout=5)
 c.request('POST',path,body=b'{}',headers={'Host':'api.meta.ai'})
 r=c.getresponse();assert r.status==want,(r.status,want);r.read();c.close()
print('only capped proxy route was reachable')
""".replace('UPSTREAM',str(port)).replace('PRIVATE_COUNTER',repr(str(self.root/'invocation.json')))
        # A host listener unreachable inside the network namespace, independent of
        # the bridge port. No remote IP, model or credential is involved.
        proc,_=sandbox.run_sandboxed(['/usr/bin/python3','-c',client],work=workspace,
            env={'PATH':'/usr/bin:/bin'},network=True,kind='bwrap',timeout=20,gateway=gw)
        self.assertEqual(proc.returncode,0,proc.stderr);self.assertEqual(len(upstream),3)

    def test_concurrent_admission_cannot_overspend_one_invocation(self):
        meter=self.meter();answers=[]
        threads=[threading.Thread(target=lambda:answers.append(meter.admit(host='api.meta.ai',method='POST',path='/v1/responses'))) for _ in range(20)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(answers.count(None),3)
        self.assertEqual(fixer_budget.read(self.root/'invocation.json')['reservedNanoUsd'],300_000_000)

    def test_streamed_usage_does_not_release_or_double_reserve_credit(self):
        meter=self.meter();gateway=addon.Gateway(meter=meter)
        self.assertIsNone(meter.admit(host='api.meta.ai',method='POST',path='/v1/responses'))
        flow=SimpleNamespace(response=Response.make(200,b'',{}),metadata={})
        gateway.responseheaders(flow)
        chunks=[b'data: {"usage":{"input_',b'tokens":7,"output_tokens":3}}\n\n',b'']
        self.assertEqual(b''.join(flow.response.stream(c) for c in chunks),b''.join(chunks))
        gateway.response(flow)
        doc=fixer_budget.read(self.root/'invocation.json')
        self.assertEqual(doc['inputTokensObserved'],7);self.assertEqual(doc['reservedNanoUsd'],100_000_000)

    def test_connect_tunnels_and_raw_tcp_cannot_bypass_http_admission(self):
        meter=self.meter();gateway=addon.Gateway(meter=meter)
        for host,port in [('evil.example',443),('api.meta.ai',444)]:
            flow=SimpleNamespace(request=SimpleNamespace(host=host,port=port),response=None)
            gateway.http_connect(flow);self.assertEqual(flow.response.status_code,403)
        raw=SimpleNamespace(kill=mock.Mock());gateway.tcp_start(raw);raw.kill.assert_called_once()
        self.assertEqual(fixer_budget.read(self.root/'invocation.json')['admittedRequests'],0)

    def test_gateway_config_disables_eager_connect_and_raw_tcp(self):
        # Check the real proxy process launch, not a flag suggested to the fixer.
        from agents import gateway
        meter=self.meter();conf=self.root/'conf';conf.mkdir()
        (conf/'mitmproxy-ca-cert.pem').write_text('fixture CA')
        proc=mock.Mock();proc.poll.return_value=None
        with mock.patch.object(gateway.subprocess,'Popen',return_value=proc) as launch, \
             mock.patch.object(gateway.socket,'create_connection'):
            gateway.start_mitmdump('fixture-mitm',conf,self.root/'log','fixture-key','fixture-placeholder','.meta.ai',invocation=meter)
        argv=launch.call_args.args[0]
        self.assertIn('connection_strategy=lazy',argv);self.assertIn('rawtcp=false',argv)
        config=Path(launch.call_args.kwargs['env']['MUSE_GATEWAY_METER_CONFIG'])
        self.assertEqual(json.loads(config.read_text()),meter.config)

    def test_missing_usage_or_server_error_never_refunds_a_request(self):
        meter=self.meter()
        self.assertIsNone(meter.admit(host='api.meta.ai',method='POST',path='/v1/responses'))
        meter.observe(b'not a usage record')
        self.assertEqual(fixer_budget.read(self.root/'invocation.json')['reservedNanoUsd'],100_000_000)

    def test_invocation_holds_full_cap_and_existing_month_covers_each_hold(self):
        self.meter();self.meter()
        self.assertAlmostEqual(spend.METER.snapshot_roles()['muse']['reserved'],0.6)
        month=spend.read_model_month(self.root/'month.json')
        self.assertEqual(month['spentUsd'],1.0)  # PR #521 reserves whole aggregate role cap once.
        self.assertEqual(len(month['entries']),1)
        self.meter()
        with self.assertRaises(spend.BudgetStop):self.meter()
        self.assertAlmostEqual(spend.METER.snapshot_roles()['muse']['reserved'],0.9)

    def test_month_ledger_required_and_corruption_never_sends(self):
        with mock.patch.dict(os.environ,{'EXPECTRAIL_MODEL_MONTH_LEDGER':''}):
            with self.assertRaisesRegex(spend.BudgetStop,'month-ledger-required'):self.meter()
        (self.root/'month.json').write_text('broken')
        with self.assertRaises(spend.BudgetStop):self.meter()
        self.assertFalse((self.root/'invocation.json').exists())

    def test_live_start_refuses_missing_invalid_zero_and_unprovable_cap(self):
        for raw,code in [('', 'fixer-invocation-cap-missing'),('nan','fixer-invocation-cap-missing'),
                         ('-1','fixer-invocation-cap-missing'),('0','fixer-invocation-cap'),('0.3','fixer-bound-unavailable')]:
            with self.subTest(raw=raw),mock.patch.dict(os.environ,{fixer_budget.ENV:raw}),mock.patch.object(sandbox,'warm_muse') as warm,mock.patch('agents.gateway.muse_gateway') as gateway,mock.patch.object(sandbox,'run_sandboxed') as process:
                with self.assertRaisesRegex(spend.BudgetStop,code):
                    sandbox.run_muse_sandboxed('fix',work=self.root/'work',timeout=5)
                warm.assert_not_called();gateway.assert_not_called();process.assert_not_called()
                doc=fixer_budget.read(self.root/'fixer-invocation.json')
                self.assertEqual(doc['admittedRequests'],0);self.assertEqual(doc['stopReason'],code)

    def test_parent_reads_proxy_counters_not_its_initial_empty_instance(self):
        meter=self.meter()
        def process(*args,**kw):
            proxy=fixer_meter.Meter(meter.config)
            for _ in range(4):proxy.admit(host='api.meta.ai',method='POST',path='/v1/responses')
            self.assertTrue(kw['require_sandbox']);self.assertTrue(kw['provider_only'])
            return (None,{})
        with mock.patch.object(fixer_budget,'start',return_value=meter),mock.patch.object(sandbox,'run_muse',side_effect=process):
            with self.assertRaisesRegex(spend.BudgetStop,'fixer-invocation-cap'):
                sandbox.run_muse_sandboxed('fix',work=self.root/'work',timeout=5)
        self.assertEqual(fixer_budget.read(self.root/'invocation.json')['admittedRequests'],3)

    def test_timeout_after_proxy_stop_is_a_budget_stop(self):
        import subprocess
        for requests in (3, 4):
            with self.subTest(requests=requests):
                meter=self.meter()
                def process(*a,**kw):
                    for _ in range(requests):meter.admit(host='api.meta.ai',method='POST',path='/v1/responses')
                    raise subprocess.TimeoutExpired('stand-in',5)
                with mock.patch.object(fixer_budget,'start',return_value=meter),mock.patch.object(sandbox,'run_muse',side_effect=process):
                    with self.assertRaisesRegex(spend.BudgetStop,'fixer-invocation-cap'):
                        sandbox.run_muse_sandboxed('fix',work=self.root/'work',timeout=5)

    def test_counter_write_failure_never_forwards_and_stays_closed(self):
        meter=self.meter();port,upstream=self.proxy(meter)
        with mock.patch.object(meter,'persist',side_effect=OSError('stand-in full disk')):
            self.assertEqual(self.send(port),503)
        self.assertEqual(self.send(port),503);self.assertEqual(upstream,[])
        self.assertEqual(fixer_budget.read(self.root/'invocation.json')['stopReason'],'fixer-meter-unavailable')

    def test_unreadable_counter_is_budget_stop_not_a_fixer_failure(self):
        meter=self.meter()
        with mock.patch.object(fixer_budget,'start',return_value=meter),mock.patch.object(sandbox,'run_muse',return_value=(None,{})):
            (self.root/'invocation.json').write_text('broken')
            with self.assertRaisesRegex(spend.BudgetStop,'fixer-meter-unavailable'):
                sandbox.run_muse_sandboxed('fix',work=self.root/'work',timeout=5)

    def test_another_valid_invocation_counter_cannot_be_substituted(self):
        meter=self.meter()
        wrong=dict(meter.doc,id='a'*32)
        fixer_meter.write(self.root/'invocation.json',wrong)
        with mock.patch.object(fixer_budget,'start',return_value=meter),mock.patch.object(sandbox,'run_muse',return_value=(None,{})):
            with self.assertRaisesRegex(spend.BudgetStop,'fixer-meter-unavailable'):
                sandbox.run_muse_sandboxed('fix',work=self.root/'work',timeout=5)

    def test_raw_fixer_sender_has_no_live_retry_or_schema_fallback(self):
        from expectrail import providers
        cfg=providers.ProviderConfig('meta','openai','https://api.meta.ai/v1','fixture','fake')
        with mock.patch('urllib.request.urlopen') as send:
            with self.assertRaisesRegex(spend.BudgetStop,'fixer-bound-unavailable'):
                providers.chat_completion([{'role':'user','content':'fix'}],role='FIXER',config=cfg)
            send.assert_not_called()

    def test_gateway_cannot_be_disabled_for_an_invocation_and_network_is_unshared(self):
        from agents import gateway
        meter=self.meter()
        with self.assertRaises(gateway.GatewayError),gateway.muse_gateway({},invocation=meter):pass
        fake=SimpleNamespace(dir=self.root,bridge_argv=lambda args:args)
        with mock.patch.object(sandbox,'muse_install_files',return_value=[]):
            cmd=sandbox._bwrap_cmd(self.root,['fixture'],network=True,gateway=fake)
        self.assertIn('--unshare-net',cmd)
        self.assertIn(str(self.root),cmd)

    def test_byo_cannot_bypass_live_refusal(self):
        from agents import byo_fixer
        with mock.patch.object(byo_fixer,'chat_completion') as send,mock.patch('agents.sandbox.run_sandboxed') as process:
            with self.assertRaises(spend.BudgetStop):byo_fixer.run_byo_agent('fix',self.root,self.root,agent='codex')
            with self.assertRaises(spend.BudgetStop):byo_fixer.run_llm_patch_fixer('fix',self.root,self.root/'patch')
            send.assert_not_called();process.assert_not_called()

    def test_schema_reader_and_writer_reject_tampered_or_unknown_record(self):
        doc=contracts.load_strict(Path(__file__).resolve().parents[1]/'contracts/examples/fixer-invocation.json','fixer-invocation')
        doc['reservedNanoUsd']+=1
        fixer_meter.write(self.root/'bad.json',doc)
        with self.assertRaises(ValueError):fixer_budget.read(self.root/'bad.json')
        doc['extra']=True;fixer_meter.write(self.root/'bad.json',doc)
        with self.assertRaises(ValueError):fixer_budget.read(self.root/'bad.json')


class RepairBudgetStop(unittest.TestCase):
    def setUp(self):repairs.RepairCommandTest.setUp(self)

    def test_no_live_bound_stops_as_review_before_a_fixer_or_child(self):
        from expectrail import repair
        from agents import fixer
        with mock.patch.dict(os.environ,{'EXPECTRAIL_MUSE_USD_CAP':'1',fixer_budget.ENV:'0.3'}), \
             mock.patch.object(fixer,'muse_code_ready',return_value=True),mock.patch.object(fixer,'muse_subprocess_env',return_value={}), \
             mock.patch.object(fixer,'detect_sandbox',return_value='bwrap'),mock.patch.object(sandbox,'warm_muse') as warm, \
             mock.patch('agents.gateway.muse_gateway') as gateway,mock.patch.object(repair,'_child') as child:
            path,doc=repair.repair(self.jobs,self.parent)
        self.assertEqual(doc['result']['decision'],'needs-review');self.assertEqual(doc['stop']['reason'],'spend-cap')
        self.assertEqual(len(doc['attempts']),1);self.assertEqual(doc['attempts'][0]['budgetStop'],'fixer-bound-unavailable')
        warm.assert_not_called();gateway.assert_not_called();child.assert_not_called()
        budget=fixer_budget.read(path.parent/doc['attempts'][0]['fixerInvocation'])
        self.assertEqual(budget['admittedRequests'],0)
        self.assertEqual(self.jobs.status(self.parent)['decision'],'reject')

    def test_mid_invocation_stop_discards_patch_and_never_verifies_or_retries(self):
        from expectrail import repair
        from agents import fixer
        def stopped(req,folder,**kw):
            folder.mkdir(parents=True)
            (folder/'candidate.patch').write_text(repairs.FIX.read_text())
            meter=fixer_meter.Meter({'id':'f'*32,'capNanoUsd':1,'requestMaxNanoUsd':1,'host':'api.meta.ai','path':'/v1/responses','record':str(folder/'fixer-invocation.json')})
            meter.admit(host='api.meta.ai',method='POST',path='/v1/responses')
            meter.admit(host='api.meta.ai',method='POST',path='/v1/responses')
            fixer_budget.stop('fixer-invocation-cap','stand-in exhausted its cap',folder/'fixer-invocation.json',meter.doc)
        with mock.patch.dict(os.environ,{'EXPECTRAIL_MUSE_USD_CAP':'1'}),mock.patch.object(fixer,'run_fixer',side_effect=stopped) as called,mock.patch.object(repair,'_child') as child:
            path,doc=repair.repair(self.jobs,self.parent,attempts=3)
        self.assertEqual(doc['stop']['reason'],'spend-cap');self.assertEqual(doc['result']['decision'],'needs-review')
        called.assert_called_once();child.assert_not_called();self.assertIsNone(doc['result']['patch'])
        self.assertEqual(doc['attempts'][0]['budgetStop'],'fixer-invocation-cap')
        self.assertEqual(fixer_budget.read(path.parent/doc['attempts'][0]['fixerInvocation'])['admittedRequests'],1)


class LegacyLoopStop(unittest.TestCase):
    def test_budget_stop_is_review_in_demo_loop_too(self):
        from agents import loop
        from tests import test_escalation as escalation
        with tempfile.TemporaryDirectory() as tmp, mock.patch('agents.loop.run_fixer',side_effect=spend.BudgetStop('fixer-invocation-cap',role='muse')) as fixer, \
             mock.patch('agents.loop.verify') as verify,mock.patch('agents.loop.render_report',return_value=None):
            result=loop.one_run(Path(tmp)/'loop',use_muse=True,offline_triage=True,
                observations=escalation.FIXTURES/'obs-fixed.json',candidate_patch=None,
                skip_harness=True,require_sandbox=False,run_trust=False)
        self.assertEqual(result['decision'],'needs-review');fixer.assert_called_once();verify.assert_not_called()
