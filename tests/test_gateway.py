"""The Muse key gateway in production (agents/gateway.py, agents/gateway_bridge.py, agents/sandbox.py).

mitmproxy, bubblewrap and Muse Code are not needed: a fake mitmdump listens and writes a CA file,
a fake muse prints what it was given, and the bridge is exercised with real sockets. The real
programs run in CI (fix-matrix.yml with the gateway on).
"""
import contextlib
import io
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests.tool_requirements import require_tool
from agents import gateway as gw
from agents import sandbox
from harness.run import REPO

REAL = "msk-" + "R" * 44

FAKE_MITMDUMP = f"""#!{sys.executable}
import os, socket, sys, threading
args = sys.argv[1:]
port = int(args[args.index("--listen-port") + 1])
conf = [a.split("=", 1)[1] for a in args if a.startswith("confdir=")][0]
assert os.environ["MUSE_GATEWAY_KEY"].startswith("msk-")  # the proxy, and only the proxy, has the key
assert "META_API_KEY" not in os.environ
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", port)); srv.listen(8)
open(os.path.join(conf, "mitmproxy-ca-cert.pem"), "w").write("FAKE CA")
def echo(c):
    data = c.recv(1024)
    c.sendall(b"proxy saw:" + data); c.close()
while True:
    c, _ = srv.accept()
    threading.Thread(target=echo, args=(c,), daemon=True).start()
"""

FAKE_MUSE = """#!/bin/sh
if [ "$1" = "--version" ]; then echo "Muse Code 0.0.0-test"; exit 0; fi
echo "key=$META_API_KEY proxy=$HTTPS_PROXY ca=$SSL_CERT_FILE"
"""


def _write_exec(path: Path, text: str) -> Path:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class GatewayTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.mitm = _write_exec(self.tmp / "mitmdump", FAKE_MITMDUMP)
        self.env = {"EXPECTRAIL_MUSE_GATEWAY": "on", "EXPECTRAIL_MITMDUMP": str(self.mitm), "META_API_KEY": REAL,
                    "EXPECTRAIL_MUSE_USD_CAP": "1000",
                    "PATH": os.environ["PATH"]}

    def test_off_unless_turned_on(self):
        self.assertFalse(gw.enabled({}))
        self.assertTrue(gw.enabled({"EXPECTRAIL_MUSE_GATEWAY": "on"}))
        with gw.muse_gateway({}) as g:
            self.assertIsNone(g)

    def test_on_without_the_key_or_the_proxy_is_an_error_never_a_fallback(self):
        with self.assertRaises(gw.GatewayError), gw.muse_gateway(dict(self.env, META_API_KEY="")):
            pass
        with self.assertRaises(gw.GatewayError), gw.muse_gateway(dict(self.env, EXPECTRAIL_MITMDUMP=str(self.tmp / "nope"),
                                                                        PATH="/nonexistent")):
            pass

    def test_muse_gets_the_placeholder_and_the_proxy_never_the_key(self):
        require_tool('AF_UNIX')
        with mock.patch.dict(os.environ, self.env), gw.muse_gateway() as g:
            host = g.muse_env({"PATH": "/usr/bin", "META_API_KEY": REAL, "NO_PROXY": "meta.ai"}, in_sandbox=False)
            box = g.muse_env({"PATH": "/usr/bin", "META_API_KEY": REAL}, in_sandbox=True)
            directory = g.dir
            self.assertTrue((directory / "ca.pem").is_file() and (directory / "bridge.py").is_file())
        for env in (host, box):
            self.assertNotIn(REAL, json.dumps(env))
            self.assertEqual(len(env["META_API_KEY"]), len(REAL))
            self.assertNotIn("NO_PROXY", env)
        self.assertEqual(host["HTTPS_PROXY"], g.proxy)
        self.assertEqual(box["HTTPS_PROXY"], f"http://127.0.0.1:{gw.SANDBOX_PORT}")
        self.assertEqual(box["SSL_CERT_FILE"], "/gateway/ca.pem")
        self.assertFalse(directory.exists())  # stopped and cleaned up on exit

    def test_the_unix_socket_reaches_the_proxy(self):
        require_tool('AF_UNIX')
        with (mock.patch.dict(os.environ, self.env), gw.muse_gateway() as g,
              socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c):
            c.settimeout(5)
            c.connect(str(g.socket))
            c.sendall(b"CONNECT api.meta.ai:443")
            self.assertEqual(c.recv(1024), b"proxy saw:CONNECT api.meta.ai:443")

    def test_the_bridge_runs_the_command_behind_a_local_port(self):
        require_tool('AF_UNIX')
        sock_path = self.tmp / "s.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        server.listen(1)

        def echo():
            c, _ = server.accept()
            c.sendall(b"via-socket:" + c.recv(64))
            c.close()
        threading.Thread(target=echo, daemon=True).start()
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        client = ("import socket,sys,time\n"
                  "for _ in range(50):\n"
                  "    try:\n"
                  f"        c=socket.create_connection(('127.0.0.1',{port}),timeout=2); break\n"
                  "    except OSError: time.sleep(0.05)\n"
                  "c.sendall(b'hello'); sys.exit(0 if c.recv(64)==b'via-socket:hello' else 3)")
        proc = subprocess.run([sys.executable, str(REPO / "agents" / "gateway_bridge.py"), "--port", str(port),
                               "--socket", str(sock_path), "--", sys.executable, "-c", client],
                              capture_output=True, text=True, timeout=30, check=False)
        server.close()
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_muse_on_the_host_sees_only_the_placeholder_through_run_muse(self):
        require_tool('AF_UNIX')
        bindir = self.tmp / "bin"
        bindir.mkdir()
        _write_exec(bindir / "muse", FAKE_MUSE)
        env = dict(self.env, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}")
        with mock.patch.dict(os.environ, env):
            sandbox._WARMED.clear()
            proc, meta = sandbox.run_muse("hi", work=self.tmp, env={"PATH": env["PATH"], "META_API_KEY": REAL},
                                          timeout=30, sandboxed=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn(REAL, proc.stdout)
        self.assertIn("key=[placeholder] proxy=http://127.0.0.1:", proc.stdout)  # the placeholder is redacted too
        self.assertEqual((meta["kind"], meta["gateway"]["mode"]), ("none", "on"))

    def test_without_the_gateway_run_muse_is_unchanged(self):
        bindir = self.tmp / "bin"
        bindir.mkdir()
        _write_exec(bindir / "muse", FAKE_MUSE)
        with mock.patch.dict(os.environ, {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
                                          "EXPECTRAIL_MUSE_GATEWAY": "off",
                                          "EXPECTRAIL_MUSE_USD_CAP": "1000"}):
            proc, meta = sandbox.run_muse("hi", work=self.tmp, env={"META_API_KEY": "k", "PATH": os.environ["PATH"]},
                                          timeout=30, sandboxed=False)
        self.assertIn("key=k proxy= ", proc.stdout)
        self.assertEqual(meta["gateway"], {"mode": "off"})


class EvidenceTest(unittest.TestCase):
    def test_every_muse_run_is_counted_and_a_run_without_the_gateway_shows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a" / "attempt-1").mkdir(parents=True)
            (root / "a" / "attempt-1" / "sandbox.json").write_text(json.dumps({"kind": "bwrap", "gateway": {
                "mode": "on", "requests": 19, "hosts": ["api.meta.ai"], "blockedHosts": [],
                "swappedHeaders": ["authorization"]}}))
            (root / "b").mkdir()
            (root / "b" / "judge.json").write_text(json.dumps({"sandbox": {"gateway": {"mode": "off"}}}))
            e = gw.evidence(root)
        self.assertEqual((e["museRuns"], e["throughGateway"], e["requests"]), (2, 1, 19))
        self.assertEqual((e["hosts"], e["swappedHeaders"]), (["api.meta.ai"], ["authorization"]))


class TimeoutTest(unittest.TestCase):
    def test_a_run_that_times_out_keeps_what_the_gateway_saw(self):
        require_tool('AF_UNIX')
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bindir = tmp / "bin"
            bindir.mkdir()
            _write_exec(bindir / "muse", "#!/bin/sh\n[ \"$1\" = \"--version\" ] && exit 0\nsleep 5\n")
            mitm = _write_exec(tmp / "mitmdump", FAKE_MITMDUMP)
            env = {"EXPECTRAIL_MUSE_GATEWAY": "on", "EXPECTRAIL_MITMDUMP": str(mitm), "META_API_KEY": REAL,
                   "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "EXPECTRAIL_MUSE_USD_CAP": "1000"}
            with mock.patch.dict(os.environ, env):
                sandbox._WARMED.clear()
                with self.assertRaises(subprocess.TimeoutExpired) as caught:
                    sandbox.run_muse("hi", work=tmp, env={"PATH": env["PATH"], "META_API_KEY": REAL},
                                     timeout=1, sandboxed=False)
        self.assertEqual(caught.exception.sandbox_meta["gateway"]["mode"], "on")

    def test_a_run_with_no_gateway_record_still_counts_as_a_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").mkdir()
            (root / "a" / "sandbox.json").write_text(json.dumps({"kind": "bwrap", "timedOut": True}))
            (root / "b").mkdir()
            (root / "b" / "sandbox.json").write_text(json.dumps({"kind": "bwrap", "gateway": {"mode": "on", "requests": 3}}))
            e = gw.evidence(root)
        self.assertEqual((e["museRuns"], e["throughGateway"]), (2, 1))  # reported, so the gap shows


    def test_a_job_the_pre_run_check_stopped_says_why_there_was_no_muse_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "run-01").mkdir()
            (root / "run-01" / "result.json").write_text(json.dumps({"decision": "needs-review",
                                                                     "preflight": {"kind": "credit"}}))
            self.assertEqual(gw.evidence(root)["stoppedBeforeFixer"], 1)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                gw.main(["--evidence", str(root)])
        self.assertTrue(out.getvalue().startswith("::notice title=Muse key gateway::no Muse run: the pre-run"))

    def test_a_job_with_no_muse_run_and_no_reason_still_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "run-01").mkdir()
            (root / "run-01" / "result.json").write_text(json.dumps({"decision": "reject"}))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                gw.main(["--evidence", str(root)])
        self.assertTrue(out.getvalue().startswith("::warning title=Muse key gateway::0 of 0"))

class SandboxCommandTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()  # macOS: /var -> /private/var, as _bwrap_cmd resolves it
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for name in ("muse", "muse-bin-1.4.14-R1", ".muse-version", ".muse-release-info.json",
                     ".muse-update-checked-at", ".muse-launcher.Ab12", "other-tool"):
            _write_exec(self.bin / name, "x")

    def test_the_installed_program_is_bound_not_downloaded(self):
        names = [p.name for p in sandbox.muse_install_files(str(self.bin / "muse"))]
        self.assertEqual(names, [".muse-release-info.json", ".muse-update-checked-at", ".muse-version", "muse",
                                 "muse-bin-1.4.14-R1"])  # not the installer's leftovers, not other tools
        with mock.patch.object(sandbox.shutil, "which", return_value=None):
            self.assertEqual(sandbox.muse_install_files(), [])  # no muse installed: nothing to bind

    def test_with_the_gateway_the_sandbox_has_no_network_and_runs_behind_the_bridge(self):
        gdir = self.tmp / "gw"
        gdir.mkdir()
        g = gw.Gateway(proxy="http://127.0.0.1:1", ca=gdir / "ca.pem", placeholder="p", real="r", dir=gdir)
        with mock.patch.object(sandbox.shutil, "which", return_value=str(self.bin / "muse")):
            cmd = sandbox._bwrap_cmd(self.tmp, ["muse", "exec", "x"], network=True, gateway=g)
            plain = sandbox._bwrap_cmd(self.tmp, ["muse", "exec", "x"], network=True)
        self.assertIn("--unshare-net", cmd)
        self.assertNotIn("--unshare-net", plain)
        i = cmd.index(str(gdir))
        self.assertEqual(cmd[i - 1:i + 2], ["--ro-bind", str(gdir), "/gateway"])
        tail = cmd[cmd.index("--") + 1:]
        self.assertEqual(tail[:2], ["/usr/bin/python3", "/gateway/bridge.py"])
        self.assertEqual(tail[-3:], ["muse", "exec", "x"])
        program = str(self.bin / "muse-bin-1.4.14-R1")
        self.assertIn(program, cmd)
        self.assertEqual(cmd[cmd.index(program) - 1], "--ro-bind")


if __name__ == "__main__":
    unittest.main()
