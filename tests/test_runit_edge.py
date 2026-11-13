""""Run it" (#265, slice 3): the edge function (apps/run-it-edge/) and the scripted burst.

The edge function's own tests are in JavaScript (apps/run-it-edge/test/service.test.mjs, a fake
GitHub and a clock the test moves). This file runs them with Node, checks every body they produced
against contracts/run-it-api.v1.schema.json, and runs the burst script (tools/runit_burst.py) over
HTTP against both the local stub of slice 2 and the edge function served locally with a pretend
GitHub. No network, no account, no token: nothing here reaches GitHub.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

import yaml

from expectrail import runit, runit_site
from tools import runit_burst, runit_stub

REPO = Path(__file__).resolve().parent.parent
EDGE = REPO / "apps" / "run-it-edge"
SERVICE = (EDGE / "service.js").read_text(encoding="utf-8")
NODE = shutil.which("node")


def schema_reasons() -> list[str]:
    doc = json.loads((REPO / runit_site.API_SCHEMA).read_text())
    refused = next(b for b in doc["oneOf"] if b["properties"]["kind"].get("const") == "refused")
    return refused["properties"]["reason"]["enum"]


class SourceTest(unittest.TestCase):
    """What the edge function's source must keep, read as text."""

    def test_it_sends_only_reasons_the_contract_names(self):
        sent = set(re.findall(r'refusal\("([a-z-]+)"', SERVICE))
        self.assertTrue(sent)
        self.assertLessEqual(sent, set(schema_reasons()))

    def test_the_page_has_words_for_every_reason(self):
        script = (REPO / "docs" / "run-it" / "run-it.js").read_text()
        for reason in schema_reasons():
            if reason != "unknown-request":   # a status poll's answer, not a start's
                self.assertIn(f'"{reason}":', script, reason)

    def test_it_calls_only_github_and_only_for_run_it(self):
        urls = re.findall(r"https://[^\s`\"']+", SERVICE)
        for url in urls:
            self.assertRegex(url, r"^https://(api\.github\.com/repos/\$\{REPO\}/actions|raw\.githubusercontent\.com/\$\{REPO\}/run-it-results/|expectrail\.tech|api\.expectrail\.tech)")
        self.assertIn('export const REPO = "Expectrail/Expectrail";', SERVICE)
        self.assertIn('export const WORKFLOW = "run-it.yml";', SERVICE)
        self.assertIn('export const REF = "main";', SERVICE)
        self.assertNotIn("/cancel", SERVICE)

    def test_the_samples_are_the_manifests(self):
        listed = json.loads(re.search(r"export const SAMPLES = (\[[^\]]*\]);", SERVICE).group(1))
        manifest = runit.read_manifest(REPO)
        self.assertEqual(listed, [s["id"] for s in manifest["samples"]])

    def test_run_it_names_its_runs_as_the_function_looks_for_them(self):
        doc = yaml.safe_load((REPO / ".github" / "workflows" / "run-it.yml").read_text())
        self.assertEqual(doc["run-name"], "Run it ${{ inputs.request_id }}")
        self.assertIn("w.display_title === `Run it ${requestId}`", SERVICE)

    def test_no_secret_is_in_the_folder(self):
        example = (EDGE / "wrangler.toml.example").read_text()
        self.assertNotRegex(example, r"(?m)^\s*(GITHUB_TOKEN|VISITOR_SALT)\s*=")
        self.assertIn('RUN_IT_OPEN = "false"', example)
        for path in EDGE.rglob("*"):
            if path.is_file():
                self.assertNotRegex(path.read_text(), r"(ghp_|github_pat_)[A-Za-z0-9_]{10,}", path.name)


@unittest.skipIf(NODE is None, "Node is not installed (the ubuntu-24.04 runners have it)")
class EdgeFunctionTest(unittest.TestCase):
    def test_its_own_tests_pass_and_every_body_it_sent_is_in_the_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "bodies.json"
            proc = subprocess.run([NODE, "--test", str(EDGE / "test" / "service.test.mjs")], cwd=REPO,
                                  env={"PATH": str(Path(NODE).parent), "BODIES_OUT": str(out)},
                                  capture_output=True, text=True, timeout=300)
            self.assertEqual(proc.returncode, 0, proc.stdout[-4000:] + proc.stderr[-2000:])
            self.assertRegex(proc.stdout, r"# fail 0")
            bodies = json.loads(out.read_text())
        self.assertGreater(len(bodies), 500)
        for body in bodies:
            self.assertEqual(runit_site.api_errors(body), [], body)
        kinds = {b["kind"] for b in bodies}
        self.assertEqual(kinds, {"health", "accepted", "refused", "status"})
        reasons = {b["reason"] for b in bodies if b["kind"] == "refused"}
        self.assertEqual(reasons, set(schema_reasons()))
        self.assertEqual({b["state"] for b in bodies if b["kind"] == "status"},
                         {"queued", "running", "publishing", "published", "failed", "cancelled"})

    def test_a_burst_over_http_starts_one_run(self):
        proc = subprocess.Popen([NODE, str(EDGE / "local.mjs"), "--port", "0", "--run-seconds", "30"], cwd=REPO,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(proc.wait, 10)
        self.addCleanup(proc.kill)
        line = proc.stdout.readline()
        port = re.search(r"127\.0\.0\.1:(\d+)", line).group(1)
        result = runit_burst.burst(f"http://127.0.0.1:{port}", 60, "fall-through-bug")
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["tally"], {"accepted": 1, "refused: busy": 59})
        # Another origin is refused, and still in the contract.
        other = runit_burst.burst(f"http://127.0.0.1:{port}", 3, "clean", origin="https://evil.example")
        self.assertEqual(other["problems"], [])
        self.assertEqual(other["tally"], {"refused: bad-request": 3})


class StubBurstTest(unittest.TestCase):
    """The same burst against slice 2's stub, which holds the same limits in Python."""

    def test_a_burst_against_the_stub_starts_one_run(self):
        release = threading.Event()
        ran = []

        def runner(sample, out, request_id):
            ran.append(request_id)
            release.wait(30)
            raise RuntimeError("the test's run ends here, unpublished")

        with tempfile.TemporaryDirectory() as tmp:
            service = runit_stub.Service(Path(tmp) / "results", runner, REPO)
            service.log = lambda message: None
            server = runit_stub.serve(service, 0)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                result = runit_burst.burst(f"http://127.0.0.1:{server.server_address[1]}/api", 40, "clean")
            finally:
                release.set()
                server.shutdown()
                server.server_close()
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["tally"], {"accepted": 1, "refused: busy": 39})
        self.assertEqual(len(ran), 1)

    def test_the_script_fails_on_two_accepted_or_a_body_outside_the_contract(self):
        answers = iter([(202, {"format": runit_site.API_FORMAT, "kind": "accepted", "requestId": "a", "sample": "clean"}),
                        (202, {"format": runit_site.API_FORMAT, "kind": "accepted", "requestId": "b", "sample": "clean"}),
                        (200, {"kind": "accepted", "verdict": "accept"}),
                        (502, "not JSON")])
        lock = threading.Lock()

        def fake_post(*a, **kw):
            with lock:
                return next(answers)

        original = runit_burst.post
        runit_burst.post = fake_post
        try:
            result = runit_burst.burst("http://127.0.0.1:9", 4, "clean", timeout=5)
        finally:
            runit_burst.post = original
        text = "\n".join(result["problems"])
        self.assertIn("runs were accepted at once", text)
        self.assertIn("not a body of the contract", text)
        self.assertIn("not JSON", text)


if __name__ == "__main__":
    unittest.main()
