"""`expectrail trust-check` (#255): the receipt check on the `expectrail` front door.

0 is clearance, 1 is no clearance, 5 is "nothing was checked" (as every `expectrail` command), and a
copy without the `trust` extra says what to install and checks nothing. The check itself is
`expectrail.receipt.check_receipt`, tested in tests/test_receipt.py; here, what the command does with it.
Keys are generated in the test; no real key is written to a file.
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail import cli, receipt
from tests.test_receipt import _base_doc, _key, _store

REPO = Path(__file__).resolve().parent.parent


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TrustCheckCommandTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.private, self.pub = _key()
        self.doc = _base_doc(self.pub)
        self.receipt = self.tmp / "receipt.json"
        self.store = self.tmp / "store.json"
        receipt.write_receipt(self.doc, self.private, self.receipt)
        _store("test-issuer", self.pub, self.store)
        self.expect = ["--repo", "Expectrail/Expectrail", "--expect-head", "b" * 64,
                       "--expect-build", "c" * 64, "--expect-policy", "d" * 64]

    def test_a_receipt_that_shows_everything_is_clearance_exit_0(self):
        code, out, err = run_cli("trust-check", str(self.receipt), "--trust-store", str(self.store), *self.expect)
        self.assertEqual(code, 0, out + err)
        self.assertIn("clearance: yes", out)
        self.assertIn("signature: valid", out)

    def test_the_same_report_as_the_module_command(self):
        args = [str(self.receipt), "--trust-store", str(self.store), *self.expect[:2]]
        code, out, _ = run_cli("trust-check", *args)
        module_out = io.StringIO()
        with contextlib.redirect_stdout(module_out):
            module_code = receipt.main(["trust-check", *args])
        self.assertEqual((code, out), (module_code, module_out.getvalue()))
        self.assertEqual(code, 1)   # head, build and policy not given: not clearance

    def test_without_expectations_it_is_no_clearance_exit_1(self):
        code, out, _ = run_cli("trust-check", str(self.receipt), "--trust-store", str(self.store))
        self.assertEqual(code, 1)
        self.assertIn("clearance: no", out)
        self.assertIn("head not checked", out)

    def test_a_key_only_inside_the_receipt_is_not_trusted(self):
        _, other = _key()
        _store("test-issuer", other, self.store)
        code, out, _ = run_cli("trust-check", str(self.receipt), "--trust-store", str(self.store), *self.expect)
        self.assertEqual(code, 1)
        self.assertIn("clearance: no", out)

    def test_a_receipt_for_another_head_is_no_clearance(self):
        argv = ["trust-check", str(self.receipt), "--trust-store", str(self.store), *self.expect]
        argv[argv.index("b" * 64)] = "9" * 64
        code, out, _ = run_cli(*argv)
        self.assertEqual(code, 1)
        self.assertIn("clearance: no", out)

    def test_nothing_checked_is_exit_5_with_no_report(self):
        not_json = self.tmp / "not.json"
        not_json.write_text("{not json", encoding="utf-8")
        not_text = self.tmp / "binary.json"
        not_text.write_bytes(b"\xff\xfe\x00junk")
        edited = json.loads(self.receipt.read_text(encoding="utf-8"))
        edited["signature"] += "\n"
        not_canonical = self.tmp / "edited.json"
        not_canonical.write_text(json.dumps(edited), encoding="utf-8")
        cases = {
            "no receipt file": [str(self.tmp / "missing.json"), "--trust-store", str(self.store)],
            "not JSON": [str(not_json), "--trust-store", str(self.store)],
            "not UTF-8": [str(not_text), "--trust-store", str(self.store)],
            "signature not canonical": [str(not_canonical), "--trust-store", str(self.store)],
            "store not a store": [str(self.receipt), "--trust-store", str(not_json)],
            "store is a folder": [str(self.receipt), "--trust-store", str(self.tmp)],
            "no store given": [str(self.receipt)],
            "no receipt given": ["--trust-store", str(self.store)],
            "unknown option": [str(self.receipt), "--trust-store", str(self.store), "--frobnicate"],
            "two receipts": [str(self.receipt), str(self.receipt), "--trust-store", str(self.store)],
        }
        for name, args in cases.items():
            with self.subTest(name):
                code, out, err = run_cli("trust-check", *args, *self.expect)
                self.assertEqual((code, out), (5, ""), err)
                self.assertIn("Nothing was checked", err)
                self.assertNotIn("Traceback", err)

    def test_the_module_command_keeps_exit_2_for_nothing_checked(self):
        not_text = self.tmp / "binary.json"
        not_text.write_bytes(b"\xff\xfe\x00junk")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = receipt.main(["trust-check", str(not_text), "--trust-store", str(self.store)])
        self.assertEqual(code, 2)
        self.assertIn("Nothing was checked", err.getvalue())

    def test_an_option_before_the_command_is_refused(self):
        code, out, err = run_cli("--jobs-root", "x", "trust-check", str(self.receipt), "--trust-store", str(self.store))
        self.assertEqual((code, out), (5, ""))
        self.assertIn("Nothing was checked", err)

    def test_help_exits_0_and_names_the_exit_codes(self):
        out = io.StringIO()
        with self.assertRaises(SystemExit) as stop, contextlib.redirect_stdout(out):
            cli.main(["trust-check", "--help"])
        self.assertEqual(stop.exception.code, 0)
        self.assertIn("--trust-store", out.getvalue())
        self.assertIn("1: no clearance", out.getvalue())

    def test_it_is_listed_as_built(self):
        text = cli.usage()
        self.assertIn("trust-check  check a receipt against a trust store", text)
        self.assertNotIn("not built yet", text)
        self.assertNotIn("trust-check", cli.PLANNED)


class MissingExtraTest(unittest.TestCase):
    """A copy without `cryptography` or `jsonschema`: it says what to install and checks nothing."""

    def run_without(self, package: str, *argv: str) -> subprocess.CompletedProcess:
        code = (f"import sys; sys.modules[{package!r}] = None\n"
                "from expectrail import cli\n"
                f"sys.exit(cli.main({list(argv)!r}))\n")
        return subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, timeout=60)

    def test_each_missing_package_is_named_with_the_extra(self):
        for package in cli.TRUST_PACKAGES:
            with self.subTest(package):
                done = self.run_without(package, "trust-check", "r.json", "--trust-store", "s.json")
                self.assertEqual((done.returncode, done.stdout), (5, ""), done.stderr)
                self.assertIn(f"needs the `{package}` package", done.stderr)
                self.assertIn("pip install 'expectrail[trust]'", done.stderr)
                self.assertIn("Nothing was checked", done.stderr)
                self.assertNotIn("Traceback", done.stderr)

    def test_the_extra_in_pyproject_has_what_the_command_asks_for(self):
        import tomllib
        extras = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]
        names = {spec.split(">")[0].split("=")[0].strip() for spec in extras["trust"]}
        self.assertEqual(names, set(cli.TRUST_PACKAGES))

    def test_other_commands_do_not_need_it(self):
        done = self.run_without("cryptography", "--version")
        self.assertEqual(done.returncode, 0, done.stderr)


class PlannedCommandTest(unittest.TestCase):
    """The mechanism for a command that is planned and not built, now that none is: it says so,
    names its issue, prints no verdict and exits 5."""

    def test_a_planned_command_says_so_and_runs_nothing(self):
        with mock.patch.dict(cli.PLANNED, {"frobnicate": ("frobnicate a build", 999)}):
            code, out, err = run_cli("frobnicate", "--anything")
            self.assertIn("frobnicate   not built yet (#999): frobnicate a build", cli.usage())
        self.assertEqual((code, out), (5, ""))
        self.assertIn("not built yet (#999)", err)
        self.assertIn("Nothing was run", err)


if __name__ == "__main__":
    unittest.main()
