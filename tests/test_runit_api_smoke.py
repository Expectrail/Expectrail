"""Deployment smoke checks over loopback only; no GitHub, model, or real run."""
import contextlib
import io
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from tools import runit_api_smoke as smoke
from expectrail import runit_site


class Stub:
    def __init__(self, **settings):
        self.open = True
        self.stand_in = False
        self.origin_filter = True
        self.state = "running"
        self.refuse = False
        self.redirect = False
        self.requests = []
        self.bodies = []
        self.__dict__.update(settings)

    def handle(self, handler):
        raw = handler.rfile.read(int(handler.headers.get("Content-Length", 0)))
        body = json.loads(raw) if raw else None
        self.requests.append((handler.command, handler.path, dict(handler.headers), body))
        origin = handler.headers.get("Origin")
        code = 200
        doc = {"format": smoke.FORMAT}
        if handler.path == "/health":
            doc.update(kind="health", open=self.open, standIn=self.stand_in)
        elif handler.path == "/run":
            if origin != smoke.ORIGIN and self.origin_filter:
                code = 403
                doc.update(kind="refused", reason="bad-request", detail="Origin refused", resetsAt=None, retryAfterSeconds=None)
            elif self.refuse or not self.open:
                code = 503
                doc.update(kind="refused", reason="disabled", detail="Closed", resetsAt=None, retryAfterSeconds=None)
            else:
                code = 202
                doc.update(kind="accepted", sample=body["sample"], requestId="smoke-1")
        else:
            doc.update(kind="status", sample="fall-through-bug", requestId="smoke-1", state=self.state,
                       standIn=self.stand_in, updatedAt="2026-11-15T00:00:00Z")
        self.bodies.append(doc)
        encoded = json.dumps(doc).encode()
        handler.send_response(302 if self.redirect else code)
        if self.redirect:
            handler.send_header("Location", "/redirected")
        if origin == smoke.ORIGIN:
            handler.send_header("Access-Control-Allow-Origin", smoke.ORIGIN)
        handler.send_header("Content-Length", str(len(encoded)))
        handler.end_headers()
        handler.wfile.write(encoded)

    @contextlib.contextmanager
    def server(self):
        stub = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self): stub.handle(self)
            def do_POST(self): stub.handle(self)
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def starts(self):
        return [r for r in self.requests if r[0] == "POST" and r[3]["sample"] in smoke.SAMPLES]


class SmokeTest(unittest.TestCase):
    def run_smoke(self, stub, **kwargs):
        output = io.StringIO()
        with stub.server() as url, contextlib.redirect_stdout(output):
            result = smoke.smoke(url, **kwargs)
        return result, output.getvalue()

    def test_open_starts_once_reports_progress_and_sends_no_credentials(self):
        stub = Stub()
        with patch.dict("os.environ", {"GITHUB_TOKEN": "do-not-send", "MODEL_API_KEY": "do-not-send", "HTTPS_PROXY": "http://user:secret@invalid"}):
            code, output = self.run_smoke(stub, expect_open="true")
        self.assertEqual(code, 0, output)
        self.assertEqual(len(stub.starts()), 1)
        self.assertIn("PASS progress: smoke-1: running", output)
        for method, path, headers, body in stub.requests:
            self.assertNotIn("Authorization", headers)
            self.assertNotIn("Cookie", headers)
            self.assertNotIn("do-not-send", json.dumps([headers, body]))
        for body in stub.bodies:
            self.assertEqual(runit_site.api_errors(body), [], body)

    def test_closed_sends_no_valid_start_and_no_progress_poll(self):
        stub = Stub(open=False)
        code, output = self.run_smoke(stub, expect_open="false")
        self.assertEqual(code, 0, output)
        self.assertFalse(stub.starts())
        self.assertEqual([r[1] for r in stub.requests], ["/health", "/run"])
        self.assertIn("zero valid start requests", output)
        self.assertIn("not applicable while closed", output)

    def test_expected_closed_but_open_never_starts(self):
        stub = Stub()
        code, output = self.run_smoke(stub, expect_open="false")
        self.assertEqual(code, 1)
        self.assertIn("FAIL RUN_IT_OPEN", output)
        self.assertFalse(stub.starts())

    def test_expected_open_but_closed_never_starts(self):
        stub = Stub(open=False)
        code, output = self.run_smoke(stub, expect_open="true")
        self.assertEqual(code, 1)
        self.assertFalse(stub.starts())

    def test_broken_origin_filter_never_starts_a_valid_sample(self):
        stub = Stub(origin_filter=False)
        code, output = self.run_smoke(stub)
        self.assertEqual(code, 1)
        self.assertIn("FAIL disallowed origin", output)
        self.assertFalse(stub.starts())

    def test_refusal_is_not_retried(self):
        stub = Stub(refuse=True)
        code, output = self.run_smoke(stub)
        self.assertEqual(code, 1)
        self.assertIn("HTTP 503, disabled; no retry", output)
        self.assertEqual(len(stub.starts()), 1)

    def test_failed_run_is_not_success(self):
        for state in ("failed", "cancelled"):
            with self.subTest(state=state):
                stub = Stub(state=state)
                code, output = self.run_smoke(stub)
                self.assertEqual(code, 1)
                self.assertIn("FAIL progress", output)
                self.assertEqual(len(stub.starts()), 1)

    def test_queue_timeout_uses_injected_clock_without_retry(self):
        clock = [0]
        stub = Stub(state="queued")
        code, output = self.run_smoke(stub, wait=20, poll=10, clock=lambda: clock[0],
                                      sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds))
        self.assertEqual(code, 1)
        self.assertIn("FAIL progress", output)
        self.assertEqual(clock[0], 20)
        self.assertEqual(len(stub.starts()), 1)

    def test_redirects_are_never_followed(self):
        stub = Stub(redirect=True)
        code, output = self.run_smoke(stub)
        self.assertEqual(code, 1)
        self.assertEqual([r[1] for r in stub.requests], ["/health"])

    def test_stand_in_is_never_presented_as_live(self):
        stub = Stub(stand_in=True)
        code, output = self.run_smoke(stub)
        self.assertEqual(code, 1)
        self.assertFalse(stub.starts())
        self.assertIn("not a deployed game run", output)
        code, output = self.run_smoke(Stub(stand_in=True), allow_stand_in=True)
        self.assertEqual(code, 0, output)
        self.assertIn("stand-in only", output)

    def test_bad_urls_never_make_a_request(self):
        for url in ("http://example.com", "https://user:password@example.com", "https://example.com?token=x",
                    "https://example.com/#x", "https://example.com/other"):
            with self.subTest(url=url):
                with patch.object(smoke, "request", side_effect=AssertionError("network")):
                    self.assertEqual(smoke.smoke(url, send=smoke.request, emit=lambda _: None), 1)

    def test_cli_returns_failure_for_unreachable_service(self):
        with patch.object(smoke.urllib.request.OpenerDirector, "open", side_effect=OSError("offline")):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(smoke.main(["https://api.expectrail.tech"]), 1)
        self.assertIn("FAIL health", output.getvalue())

    def test_malformed_http_prints_fail_instead_of_crashing(self):
        output = []
        def broken(*args, **kwargs):
            raise smoke.http.client.BadStatusLine("not HTTP")
        self.assertEqual(smoke.smoke("https://api.expectrail.tech", send=broken, emit=output.append), 1)
        self.assertEqual(len(output), 1)
        self.assertIn("FAIL health", output[0])
