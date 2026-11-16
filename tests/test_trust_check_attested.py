"""trust-check with a GitHub attestation in place of a trust-store key (#255).

No attestation has been made by a real workflow yet (that needs `id-token: write`, Sean's), so gh's
output here is written by the tests in the shape `gh attestation verify --format json` prints, as in
tests/test_attestation.py.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail import attestation as at
from expectrail import receipt as rc
from tests.test_receipt import _base_doc, _expect, _key

ROOT = Path(__file__).resolve().parent.parent
REPO = "Expectrail/Expectrail"
WORKFLOW = "Expectrail/Expectrail/.github/workflows/expectrail-comment.yml"


def gh_result(data: bytes, doc: dict, **cert_changes) -> dict:
    """One verified result as gh prints it, for this receipt file attested by WORKFLOW on main."""
    cert = {
        "issuer": at.OIDC_ISSUER,
        "buildSignerURI": f"https://github.com/{WORKFLOW}@refs/heads/main",
        "runnerEnvironment": "github-hosted",
        "sourceRepositoryURI": f"https://github.com/{REPO}",
        "sourceRepositoryRef": "refs/heads/main",
    }
    cert.update(cert_changes)
    return {"verificationResult": {
        "statement": {"subject": [{"name": "receipt.json", "digest": {"sha256": hashlib.sha256(data).hexdigest()}}],
                      "predicateType": at.PREDICATE_TYPE, "predicate": at.predicate_for(data, doc)},
        "signature": {"certificate": cert}}}


def signed_receipt(folder: Path, **changes) -> tuple[Path, dict]:
    """A receipt signed by a throwaway key that is in no trust store."""
    private, pub = _key()
    doc = _base_doc(pub, kid="ci-ephemeral")
    doc.update(changes)
    path = folder / "receipt.json"
    signed = rc.write_receipt(doc, private, path)
    return path, signed


def expect_args(doc: dict) -> list[str]:
    return ["--repo", doc["repository"], "--expect-head", doc["headSha256"], "--expect-build", doc["buildSha256"],
            "--expect-policy", doc["policySha256"]]


class FakeGh:
    """Stands in for `gh attestation verify`: records the command, answers with a given exit and output."""

    def __init__(self, results=None, code=0, err="", before=None):
        self.results, self.code, self.err, self.before = results, code, err, before
        self.calls: list[list[str]] = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        if self.before is not None:
            self.before()
        out = self.results if isinstance(self.results, str) else json.dumps(self.results or [])
        return subprocess.CompletedProcess(cmd, self.code, out, self.err)


def run_cli(argv: list[str], gh: FakeGh, *, entry: str = "module") -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(at, "_default_runner", gh), contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(err):
        if entry == "module":
            code = rc.main(["trust-check", *argv])
        else:
            from expectrail import cli
            code = cli.main(["trust-check", *argv])
    return code, out.getvalue(), err.getvalue()


class AttestedTrustCheckTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def mkdir(self, name: str) -> Path:
        folder = self.tmp / name
        folder.mkdir()
        return folder

    def attested(self, path: Path) -> FakeGh:
        data = path.read_bytes()
        return FakeGh([gh_result(data, json.loads(data))])

    def test_an_attested_receipt_clears_with_every_expectation_and_no_trust_store(self):
        path, doc = signed_receipt(self.tmp)
        gh = self.attested(path)
        code, out, err = run_cli([str(path), "--attested-by", WORKFLOW, *expect_args(doc)], gh)
        self.assertEqual(code, 0, out + err)
        self.assertIn(f"  issuer: attested (by {WORKFLOW} at refs/heads/main)", out)
        self.assertIn("  clearance: yes", out)
        self.assertIn(f"attested by {WORKFLOW} at refs/heads/main; signed with the key the receipt carries", out)
        # gh was asked with every pin the attestation check has.
        self.assertEqual(len(gh.calls), 1)
        cmd = gh.calls[0]
        self.assertEqual(cmd[:4], ["gh", "attestation", "verify", str(path)])
        for flag, value in (("--repo", REPO), ("--signer-workflow", WORKFLOW), ("--source-ref", "refs/heads/main"),
                            ("--predicate-type", at.PREDICATE_TYPE)):
            self.assertEqual(cmd[cmd.index(flag) + 1], value)
        self.assertIn("--deny-self-hosted-runners", cmd)

    def test_the_installed_command_takes_the_same_options_and_exits_5_on_nothing_checked(self):
        path, doc = signed_receipt(self.tmp)
        code, out, err = run_cli([str(path), "--attested-by", WORKFLOW, *expect_args(doc)], self.attested(path),
                                 entry="cli")
        self.assertEqual(code, 0, out + err)
        code, out, err = run_cli([str(path), "--attested-by", WORKFLOW, *expect_args(doc)], FakeGh("not json"),
                                 entry="cli")
        self.assertEqual(code, 5, out + err)
        self.assertEqual(out, "")
        self.assertIn("Nothing was checked.", err)

    def test_gh_refusing_is_no_clearance_and_says_not_attested(self):
        path, doc = signed_receipt(self.tmp)
        gh = FakeGh([], code=1, err="Error: verifying with issuer \"sigstore.dev\"\nno matching attestation found\n")
        code, out, err = run_cli([str(path), "--attested-by", WORKFLOW, *expect_args(doc)], gh)
        self.assertEqual(code, 1, out + err)
        self.assertIn(f"  issuer: NOT ATTESTED (by {WORKFLOW} at refs/heads/main)", out)
        self.assertIn("  signature: INVALID", out)
        self.assertIn("  clearance: no", out)
        self.assertIn("attestation: gh attestation verify refused it (exit 1): no matching attestation found", out)

    def test_every_pin_the_attestation_check_refuses_is_no_clearance(self):
        path, doc = signed_receipt(self.tmp)
        data = path.read_bytes()
        for name, changes in {"other workflow": {"buildSignerURI": f"https://github.com/{REPO}/.github/workflows/"
                                                                   "ci.yml@refs/heads/main"},
                              "self-hosted": {"runnerEnvironment": "self-hosted"},
                              "fork": {"sourceRepositoryURI": "https://github.com/someone/fork"},
                              "pull request ref": {"sourceRepositoryRef": "refs/pull/1/merge"}}.items():
            with self.subTest(name):
                gh = FakeGh([gh_result(data, doc, **changes)])
                code, out, err = run_cli([str(path), "--attested-by", WORKFLOW, *expect_args(doc)], gh)
                self.assertEqual(code, 1, out + err)
                self.assertIn("  issuer: NOT ATTESTED", out)
                self.assertIn("  clearance: no", out)

    def test_an_attested_file_whose_own_signature_does_not_hold_is_refused(self):
        # The workflow attested these exact bytes, but the receipt inside them is not intact: the
        # attestation does not repair it.
        path, doc = signed_receipt(self.tmp)
        tampered = dict(doc, decision="accept", headSha256="f" * 64)
        path.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")
        gh = self.attested(path)
        args = [str(path), "--attested-by", WORKFLOW, *expect_args(tampered)]
        code, out, err = run_cli(args, gh)
        self.assertEqual(code, 1, out + err)
        self.assertIn("  issuer: attested", out)
        self.assertIn("  signature: INVALID", out)
        self.assertIn("signature does not verify with the key the receipt carries", out)
        self.assertIn("  clearance: no", out)

    def test_every_other_condition_still_applies(self):
        path, doc = signed_receipt(self.tmp)
        gh = self.attested(path)
        # Nothing asked about head, build or policy: not a pass.
        code, out, _ = run_cli([str(path), "--attested-by", WORKFLOW, "--repo", REPO], gh)
        self.assertEqual(code, 1)
        self.assertIn("  identity: not checked", out)
        self.assertIn("  policy: not checked", out)
        # Another head than the one asked for.
        args = expect_args(doc)
        args[args.index("--expect-head") + 1] = "9" * 64
        code, out, _ = run_cli([str(path), "--attested-by", WORKFLOW, *args], self.attested(path))
        self.assertEqual(code, 1)
        self.assertIn("  identity: mismatch", out)
        # A reject, attested by the right workflow, is no clearance.
        rejected_path, rejected = signed_receipt(self.mkdir("reject"), decision="reject")
        code, out, _ = run_cli([str(rejected_path), "--attested-by", WORKFLOW, *expect_args(rejected)],
                               self.attested(rejected_path))
        self.assertEqual(code, 1)
        self.assertIn("decision is 'reject', not accept", out)
        # A stale receipt, attested, is no clearance.
        stale_path, stale = signed_receipt(self.mkdir("stale"), issuedAt="2026-01-01T00:00:00+00:00",
                                           expiresAt="2026-01-08T00:00:00+00:00")
        code, out, _ = run_cli([str(stale_path), "--attested-by", WORKFLOW, *expect_args(stale)],
                               self.attested(stale_path))
        self.assertEqual(code, 1)
        self.assertIn("  fresh: no", out)

    def test_a_receipt_about_another_repository_is_refused(self):
        path, doc = signed_receipt(self.tmp, repository="someone/fork")
        code, out, err = run_cli([str(path), "--attested-by", WORKFLOW, *expect_args(dict(doc, repository=REPO))],
                                 self.attested(path))
        self.assertEqual(code, 1, out + err)
        self.assertIn("  issuer: NOT ATTESTED", out)
        self.assertIn("the receipt is about someone/fork, not Expectrail/Expectrail", out)

    def test_a_file_that_changes_while_gh_reads_it_checks_nothing(self):
        path, doc = signed_receipt(self.tmp)
        gh = self.attested(path)
        gh.before = lambda: path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        code, out, err = run_cli([str(path), "--attested-by", WORKFLOW, *expect_args(doc)], gh)
        self.assertEqual(code, 2, out + err)
        self.assertEqual(out, "")
        self.assertIn("changed while it was being checked", err)

    def test_no_gh_checks_nothing(self):
        path, doc = signed_receipt(self.tmp)

        def missing(cmd):
            raise FileNotFoundError("gh")

        code, out, err = run_cli([str(path), "--attested-by", WORKFLOW, *expect_args(doc)], missing)
        self.assertEqual(code, 2, out + err)
        self.assertEqual(out, "")
        self.assertIn("gh is not installed", err)

    def test_command_lines_that_cannot_be_used_check_nothing_and_never_call_gh(self):
        path, doc = signed_receipt(self.tmp)
        store = self.tmp / "store.json"
        store.write_text(json.dumps({"format": "expectrail.trust-store/v1",
                                     "keys": [{"id": doc["issuerKeyId"], "publicKey": doc["publicKey"]}]}),
                         encoding="utf-8")
        cases = {
            "both issuers": [str(path), "--trust-store", str(store), "--attested-by", WORKFLOW, *expect_args(doc)],
            "neither issuer": [str(path), *expect_args(doc)],
            "attested without --repo": [str(path), "--attested-by", WORKFLOW, "--expect-head", "b" * 64],
            "--bundle with a trust store": [str(path), "--trust-store", str(store), "--bundle", str(path),
                                            *expect_args(doc)],
            "--source-ref with a trust store": [str(path), "--trust-store", str(store), "--source-ref",
                                                "refs/heads/main", *expect_args(doc)],
            "a workflow of another repository": [str(path), "--attested-by",
                                                 "someone/fork/.github/workflows/expectrail-comment.yml",
                                                 *expect_args(doc)],
            "not a workflow path": [str(path), "--attested-by", "expectrail-comment.yml", *expect_args(doc)],
            "a pull request ref": [str(path), "--attested-by", WORKFLOW, "--source-ref", "refs/pull/1/merge",
                                   *expect_args(doc)],
        }
        for name, argv in cases.items():
            with self.subTest(name):
                gh = self.attested(path)
                code, out, err = run_cli(argv, gh)
                self.assertEqual(code, 2, out + err)
                self.assertEqual(out, "")
                self.assertIn("Nothing was checked.", err)
                self.assertEqual(gh.calls, [])

    def test_the_trust_store_path_is_unchanged(self):
        # The same receipt by a trust store that holds its key clears; gh is never called.
        path, doc = signed_receipt(self.tmp)
        store = self.tmp / "store.json"
        store.write_text(json.dumps({"format": "expectrail.trust-store/v1",
                                     "keys": [{"id": doc["issuerKeyId"], "publicKey": doc["publicKey"]}]}),
                         encoding="utf-8")
        gh = self.attested(path)
        code, out, err = run_cli([str(path), "--trust-store", str(store), *expect_args(doc)], gh)
        self.assertEqual(code, 0, out + err)
        self.assertIn("  issuer: known", out)
        self.assertEqual(gh.calls, [])


class CheckReceiptWithAttestationTest(unittest.TestCase):
    """The library call: an attestation report stands in for the trust store, and fails closed."""

    def setUp(self):
        private, pub = _key()
        self.doc = rc.write_receipt(_base_doc(pub, kid="ci-ephemeral"), private)
        self.data = (json.dumps(self.doc, indent=2) + "\n").encode("utf-8")
        self.digest = hashlib.sha256(self.data).hexdigest()

    def report(self, receipt_sha256="same", expect_repo=REPO, **changes):
        found = at.check_attestation(self.data, self.doc, 0, json.dumps([gh_result(self.data, self.doc)]), "",
                                     repo=REPO, signer_workflow=WORKFLOW)
        self.assertTrue(found["attested"], found["reasons"])
        found.update(changes)
        asked = dict(_expect(self.doc), expect_repo=expect_repo)
        digest = self.digest if receipt_sha256 == "same" else receipt_sha256
        return rc.check_receipt(self.doc, {}, attestation=found, receipt_sha256=digest, **asked)

    def test_a_good_report_clears(self):
        report = self.report()
        self.assertTrue(report["clearance"], report["reasons"])
        self.assertEqual(report["issuer_kind"], "attestation")

    def test_a_report_that_is_not_attested_or_not_for_this_file_or_repository_is_not_an_issuer(self):
        for name, changes in {
            "not attested": {"attested": False},
            "attested is not exactly True": {"attested": "yes"},
            "no digest given": {"receipt_sha256": None},
            "another file's digest": {"receiptSha256": "f" * 64},
            "checked for another repository": {"repository": "someone/fork"},
            "no repository asked": {"expect_repo": None},
        }.items():
            with self.subTest(name):
                report = self.report(**changes)
                self.assertFalse(report["known_issuer"])
                self.assertFalse(report["valid_signature"])
                self.assertFalse(report["clearance"])
                self.assertIn("issuer identity", report["does_not_establish"])

    def test_the_trust_store_is_not_read_when_an_attestation_is_given(self):
        # A trust store that revokes nothing and holds the key is ignored: the attestation decides.
        found = {"attested": False, "reasons": ["gh attestation verify refused it (exit 1): no"],
                 "repository": REPO, "signerWorkflow": WORKFLOW, "sourceRef": "refs/heads/main",
                 "receiptSha256": self.digest}
        store = {"ci-ephemeral": self.doc["publicKey"]}
        report = rc.check_receipt(self.doc, store, attestation=found, receipt_sha256=self.digest,
                                  **_expect(self.doc))
        self.assertFalse(report["clearance"])
        self.assertIn("not attested by the named workflow", report["reasons"])


class ProcessTest(unittest.TestCase):
    def test_the_module_command_with_a_stand_in_gh_on_the_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path, doc = signed_receipt(tmp)
            data = path.read_bytes()
            (tmp / "out.json").write_text(json.dumps([gh_result(data, doc)]), encoding="utf-8")
            fake = tmp / "gh"
            fake.write_text("#!/usr/bin/env python3\nimport sys, pathlib\n"
                            f"sys.stdout.write(pathlib.Path({str(tmp / 'out.json')!r}).read_text())\n",
                            encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            env = dict(os.environ, PATH=f"{tmp}{os.pathsep}{os.environ.get('PATH', '')}")
            done = subprocess.run([sys.executable, "-m", "expectrail.receipt", "trust-check", str(path),
                                   "--attested-by", WORKFLOW, *expect_args(doc)],
                                  capture_output=True, text=True, cwd=ROOT, env=env, timeout=60)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertIn("  clearance: yes", done.stdout)


if __name__ == "__main__":
    unittest.main()
