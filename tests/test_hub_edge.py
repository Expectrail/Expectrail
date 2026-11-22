"""The hub on the Worker runtime (#785): its JavaScript tests, inside the required `test` job.

`apps/hub-edge/` is JavaScript, so its tests are `.mjs` files that `python3 -m unittest discover`
would never see. Without this file the signed-cookie verifier and the GitHub client — which decide
who is signed in and which repositories a signed-in developer may see — could be broken by a later
change while every required check stayed green. The merge guard found exactly that on #789.

So this file runs every `apps/hub-edge/test/*.test.mjs` with Node, by glob, which puts each later
hub-edge slice's tests in the required job the moment they are written. It also checks that the
JavaScript signer and the Python signer in `hub/session.py` still agree byte for byte, because a
port that silently drifts from its reference is the one failure this slice cannot survive.

Node is required, not conditional. A machine without it cannot build or run this Worker at all, and
a quietly passed-over verifier test is a smaller version of the hole the guard asked us to close, so
a missing Node fails here and says to install it. The run-it harness next door is gentler; this is
the stricter of the two on purpose.

No network, no account, no credential: `apps/hub-edge/fixtures/stub.mjs` stands in for GitHub.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from hub import session

REPO = Path(__file__).resolve().parent.parent
EDGE = REPO / "apps" / "hub-edge"
TESTS = sorted(EDGE.glob("test/*.test.mjs"))
NODE = shutil.which("node")
SECRET = re.compile(r"(ghp_|gho_|ghu_|ghs_|ghr_|github_pat_)[A-Za-z0-9_]{10,}")


def node_env() -> dict:
    """Node with nothing from this environment but the interpreter's own folder."""
    return {"PATH": str(Path(NODE).parent)}


class FolderTest(unittest.TestCase):
    """What must hold whether or not Node is installed."""

    def test_there_are_javascript_tests_to_run(self):
        # Without this, a renamed folder would leave every test below passing on nothing.
        self.assertTrue(TESTS, f"no test/*.test.mjs under {EDGE}")

    def test_node_is_installed(self):
        self.assertIsNotNone(
            NODE, "Node is needed to run the hub-edge tests; the ubuntu-24.04 runners have it")

    def test_no_credential_is_in_the_folder(self):
        for path in EDGE.rglob("*"):
            if path.is_file():
                self.assertNotRegex(path.read_text(encoding="utf-8"), SECRET, path.name)


class EdgeTest(unittest.TestCase):
    def setUp(self):
        if NODE is None:
            self.fail("Node is not installed; install Node 22 or later to run the hub-edge tests")

    def test_every_javascript_test_passes(self):
        proc = subprocess.run([NODE, "--test", "--test-reporter=tap", *[str(p) for p in TESTS]],
                              cwd=REPO, env=node_env(), capture_output=True, text=True, timeout=300)
        said = proc.stdout[-6000:] + proc.stderr[-2000:]
        self.assertEqual(proc.returncode, 0, said)
        # --test-reporter=tap: from Node 24 the runner prints its own summary instead of TAP, so
        # "# fail 0" is simply absent and a failing suite reads as a pass (#365, 2026-11-13).
        self.assertRegex(proc.stdout, r"# fail 0", said)
        passed = re.search(r"# pass (\d+)", proc.stdout)
        self.assertIsNotNone(passed, said)
        # At least one test per file: "0 collected" exits 0 and must not count as a pass.
        self.assertGreaterEqual(int(passed.group(1)), len(TESTS), said)

    def test_the_javascript_signer_and_hub_session_agree(self):
        """A token Python signed reads in JavaScript, expires at the same tick, and signs the same."""
        key, purpose = "k" * 32, "session"
        payload = {"uid": 7, "login": "dev", "exp": 500}
        token = session.sign(key, purpose, payload)
        script = (
            "const m = await import(process.env.SESSION_JS);\n"
            "const now = Number(process.env.EXPIRES_AT);\n"
            "process.stdout.write(JSON.stringify({\n"
            "  read: await m.verify(process.env.KEY, process.env.PURPOSE, process.env.TOKEN, 1),\n"
            "  at_exp: await m.verify(process.env.KEY, process.env.PURPOSE, process.env.TOKEN, now),\n"
            "  signed: await m.sign(process.env.KEY, process.env.PURPOSE, JSON.parse(process.env.PAYLOAD)),\n"
            "  tampered: await m.verify(process.env.KEY, process.env.PURPOSE, process.env.TAMPERED, 1),\n"
            "}));\n"
        )
        env = node_env() | {
            "SESSION_JS": (EDGE / "session.js").as_uri(),
            "KEY": key,
            "PURPOSE": purpose,
            "TOKEN": token,
            "TAMPERED": token[:-1] + ("A" if token[-1] != "A" else "B"),
            "PAYLOAD": json.dumps(payload),
            "EXPIRES_AT": str(payload["exp"]),
        }
        proc = subprocess.run([NODE, "--input-type=module", "--eval", script],
                              cwd=REPO, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-2000:])
        out = json.loads(proc.stdout)
        self.assertEqual(out["read"], payload)          # Python's token reads in JavaScript
        self.assertIsNone(out["at_exp"])                # expiry is exclusive on both sides
        self.assertEqual(out["signed"], token)          # and JavaScript produces the same bytes
        self.assertIsNone(out["tampered"])              # a changed signature is signed out, not an error
        # And the other way: Python reads back what JavaScript signed, and refuses it at its expiry.
        self.assertEqual(session.verify(key, purpose, out["signed"], 1), payload)
        self.assertIsNone(session.verify(key, purpose, out["signed"], payload["exp"]))


if __name__ == "__main__":
    unittest.main()
