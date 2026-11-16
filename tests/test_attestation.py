"""The receipt attestation's predicate and its reader (#255).

No attestation has been made by a real workflow yet (that needs `id-token: write`, Sean's), so gh's
output here is written by the tests in the shape `gh attestation verify --format json` prints.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema

from expectrail import attestation as at

ROOT = Path(__file__).resolve().parent.parent
RECEIPT = ROOT / "contracts" / "examples" / "receipt.v1.json"
EXAMPLE = ROOT / "contracts" / "examples" / "receipt-attestation.v1.json"
REPO = "Expectrail/Expectrail"
WORKFLOW = "Expectrail/Expectrail/.github/workflows/expectrail-comment.yml"
DATA = RECEIPT.read_bytes()
DOC = json.loads(DATA)
DIGEST = hashlib.sha256(DATA).hexdigest()


def gh_result(**cert_changes) -> dict:
    """One verified result as gh prints it, for the example receipt signed by WORKFLOW on main."""
    cert = {
        "issuer": at.OIDC_ISSUER,
        "subjectAlternativeName": f"https://github.com/{WORKFLOW}@refs/heads/main",
        "buildSignerURI": f"https://github.com/{WORKFLOW}@refs/heads/main",
        "buildSignerDigest": "0" * 40,
        "runnerEnvironment": "github-hosted",
        "sourceRepositoryURI": f"https://github.com/{REPO}",
        "sourceRepositoryRef": "refs/heads/main",
    }
    cert.update(cert_changes)
    return {
        "attestation": {"bundle": {"mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json"}},
        "verificationResult": {
            "mediaType": "application/vnd.dev.sigstore.verificationresult+json;version=0.1",
            "statement": {
                "_type": "https://in-toto.io/Statement/v1",
                "subject": [{"name": "receipt.json", "digest": {"sha256": DIGEST}}],
                "predicateType": at.PREDICATE_TYPE,
                "predicate": at.predicate_for(DATA, DOC),
            },
            "signature": {"certificate": cert},
        },
    }


def decide(results, *, code=0, err="", doc=DOC, data=DATA, **kw) -> dict:
    out = results if isinstance(results, str) else json.dumps(results)
    return at.check_attestation(data, doc, code, out, err, repo=kw.get("repo", REPO),
                                signer_workflow=kw.get("workflow", WORKFLOW),
                                source_ref=kw.get("ref", at.DEFAULT_REF))


class PredicateTest(unittest.TestCase):
    def test_the_example_is_what_the_writer_makes_for_the_example_receipt(self):
        self.assertEqual(json.loads(EXAMPLE.read_text(encoding="utf-8")), at.write_predicate(RECEIPT))
        jsonschema.Draft202012Validator(at.SCHEMA).validate(json.loads(EXAMPLE.read_text(encoding="utf-8")))

    def test_the_predicate_is_the_files_digest_and_copies_of_the_compared_fields(self):
        p = at.predicate_for(DATA, DOC)
        self.assertEqual(p["receiptSha256"], DIGEST)
        self.assertEqual(set(p), {"format", "receiptSha256", *at.COPIED})
        for k in at.COPIED:
            self.assertEqual(p[k], DOC[k])

    def test_the_schema_refuses_an_extra_field_and_a_bad_digest(self):
        validator = jsonschema.Draft202012Validator(at.SCHEMA)
        good = at.predicate_for(DATA, DOC)
        self.assertFalse(validator.is_valid(dict(good, clearance=True)))
        self.assertFalse(validator.is_valid(dict(good, receiptSha256="sha256:" + DIGEST)))
        self.assertFalse(validator.is_valid({k: v for k, v in good.items() if k != "decision"}))

    def test_an_unreadable_receipt_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad, out = Path(tmp) / "r.json", Path(tmp) / "p.json"
            bad.write_text('{"format": "expectrail.receipt/v1"}', encoding="utf-8")
            with self.assertRaises(at.CannotCheck):
                at.write_predicate(bad, out)
            self.assertFalse(out.exists())


class CheckTest(unittest.TestCase):
    def test_a_matching_attestation_is_verified_and_says_it_is_not_clearance(self):
        report = decide([gh_result()])
        self.assertTrue(report["attested"], report["reasons"])
        self.assertEqual(report["reasons"], [])
        self.assertIn("clearance (that is trust-check's)", report["does_not_establish"])
        self.assertNotIn("clearance", " ".join(report["establishes"]))

    def assertRefused(self, report, reason_part):
        self.assertFalse(report["attested"])
        self.assertIn("who wrote the receipt", report["does_not_establish"])
        self.assertTrue(any(reason_part in r for r in report["reasons"]), report["reasons"])

    def test_every_pin_refuses_when_it_differs(self):
        def with_statement(**changes):
            r = gh_result()
            r["verificationResult"]["statement"].update(changes)
            return r

        def with_predicate(**changes):
            r = gh_result()
            r["verificationResult"]["statement"]["predicate"].update(changes)
            return r

        other = "f" * 64
        cases = {
            "predicate type": (with_statement(predicateType="https://slsa.dev/provenance/v1"), "predicate type"),
            "subject digest": (with_statement(subject=[{"name": "r", "digest": {"sha256": other}}]), "no subject"),
            "no subject": (with_statement(subject=[]), "no subject"),
            "predicate names another file": (with_predicate(receiptSha256=other), "another receipt file"),
            "predicate extra field": (with_predicate(clearance=True), "is not expectrail.receipt-attestation/v1"),
            "predicate not an object": (with_statement(predicate="accept"), "is not expectrail"),
            "other repository": (gh_result(sourceRepositoryURI="https://github.com/someone/fork"), "signed for"),
            "other workflow": (gh_result(buildSignerURI=f"https://github.com/{REPO}/.github/workflows/ci.yml@refs/heads/main"),
                               "signed by"),
            "same path in another repository": (
                gh_result(buildSignerURI="https://github.com/someone/fork/.github/workflows/expectrail-comment.yml"
                                         "@refs/heads/main"), "signed by"),
            "signer on another ref": (gh_result(buildSignerURI=f"https://github.com/{WORKFLOW}@refs/heads/dev"),
                                      "signed by"),
            "signer workflow file in another case": (
                gh_result(buildSignerURI=f"https://github.com/{REPO}/.github/workflows/Expectrail-Comment.yml"
                                         "@refs/heads/main"), "signed by"),
            "source on another ref": (gh_result(sourceRepositoryRef="refs/pull/1/merge"), "source ref"),
            "self-hosted runner": (gh_result(runnerEnvironment="self-hosted"), "runners"),
            "another certificate issuer": (gh_result(issuer="https://example.com"), "certificate issuer"),
            "signer cannot be read": (gh_result(buildSignerURI="nowhere"), "cannot be read"),
        }
        for k in at.COPIED:
            value = "reject" if k == "decision" else ("someone/fork" if k == "repository" else
                                                       ("2026-11-14T00:00:01Z" if k.endswith("At") else other))
            cases[f"predicate's {k}"] = (with_predicate(**{k: value}), f"the predicate's {k} is not the receipt's")
        for name, (result, part) in cases.items():
            with self.subTest(name):
                self.assertRefused(decide([result]), part)

    def test_a_missing_field_in_ghs_output_is_refused_not_skipped(self):
        for path in (("verificationResult",), ("verificationResult", "statement"),
                     ("verificationResult", "signature", "certificate", "buildSignerURI"),
                     ("verificationResult", "signature", "certificate", "runnerEnvironment"),
                     ("verificationResult", "statement", "predicate")):
            with self.subTest(path):
                r = gh_result()
                target = r
                for name in path[:-1]:
                    target = target[name]
                del target[path[-1]]
                self.assertRefused(decide([r]), "cannot be read")

    def test_repository_names_match_without_case_and_nothing_else_does(self):
        r = gh_result(sourceRepositoryURI="https://github.com/expectrail/expectrail",
                      buildSignerURI="https://github.com/expectrail/expectrail/.github/workflows/expectrail-comment.yml"
                                     "@refs/heads/main")
        self.assertTrue(decide([r])["attested"])
        self.assertTrue(decide([gh_result()], repo="expectrail/EXPECTRAIL")["attested"])

    def test_a_receipt_about_another_repository_is_not_verified_even_when_attested(self):
        doc = dict(DOC, repository="someone/fork")
        r = gh_result()
        r["verificationResult"]["statement"]["predicate"]["repository"] = "someone/fork"
        self.assertRefused(decide([r], doc=doc), "the receipt is about someone/fork")

    def test_one_good_result_among_bad_ones_is_enough(self):
        bad = gh_result(runnerEnvironment="self-hosted")
        self.assertTrue(decide([bad, gh_result()])["attested"])
        self.assertRefused(decide([bad, copy.deepcopy(bad)]), "attestation 2:")

    def test_gh_refusing_is_not_verified_whatever_it_printed(self):
        report = decide([gh_result()], code=1, err="Error: verifying with issuer \"sigstore.dev\"\n\n")
        self.assertRefused(report, "gh attestation verify refused it (exit 1): Error: verifying with issuer")

    def test_gh_output_that_cannot_be_read_checks_nothing(self):
        for out in ("not json", "[]", "{}", "null"):
            with self.subTest(out), self.assertRaises(at.CannotCheck):
                decide(out)


class CommandTest(unittest.TestCase):
    def test_gh_is_asked_for_every_pin(self):
        cmd = at.gh_command(RECEIPT, repo=REPO, signer_workflow=WORKFLOW, source_ref="refs/heads/main",
                            bundle=Path("b.jsonl"))
        self.assertEqual(cmd[:4], ["gh", "attestation", "verify", str(RECEIPT)])
        pairs = dict(zip(cmd[4::1], cmd[5::1]))
        self.assertEqual(pairs["--repo"], REPO)
        self.assertEqual(pairs["--signer-workflow"], WORKFLOW)
        self.assertEqual(pairs["--source-ref"], "refs/heads/main")
        self.assertEqual(pairs["--predicate-type"], at.PREDICATE_TYPE)
        self.assertEqual(pairs["--cert-oidc-issuer"], at.OIDC_ISSUER)
        self.assertEqual(pairs["--bundle"], "b.jsonl")
        self.assertIn("--deny-self-hosted-runners", cmd)

    def test_a_command_line_it_cannot_use_checks_nothing(self):
        def never(cmd):
            raise AssertionError("gh must not run")

        for kw in ({"repo": "Expectrail"}, {"signer_workflow": "ci.yml"},
                   {"signer_workflow": "someone/fork/.github/workflows/expectrail-comment.yml"},
                   {"source_ref": "main"}):
            with self.subTest(kw), self.assertRaises(at.CannotCheck):
                at.check(RECEIPT, **{"repo": REPO, "signer_workflow": WORKFLOW, **kw}, runner=never)

    def test_no_gh_checks_nothing(self):
        def missing(cmd):
            raise FileNotFoundError("gh")

        with self.assertRaises(at.CannotCheck) as caught:
            at.check(RECEIPT, repo=REPO, signer_workflow=WORKFLOW, runner=missing)
        self.assertIn("gh is not installed", str(caught.exception))

    def test_a_receipt_that_changes_while_gh_reads_it_checks_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            path.write_bytes(DATA)

            def swap(cmd):
                path.write_bytes(DATA + b"\n")
                return subprocess.CompletedProcess(cmd, 0, json.dumps([gh_result()]), "")

            with self.assertRaises(at.CannotCheck):
                at.check(path, repo=REPO, signer_workflow=WORKFLOW, runner=swap)

    def run_module(self, *args, gh_out: str, gh_code: int = 0) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "gh"
            log = Path(tmp) / "args.json"
            (Path(tmp) / "out.json").write_text(gh_out, encoding="utf-8")
            fake.write_text("#!/usr/bin/env python3\nimport json, sys, pathlib\n"
                            f"pathlib.Path({str(log)!r}).write_text(json.dumps(sys.argv[1:]))\n"
                            f"sys.stdout.write(pathlib.Path({str(Path(tmp) / 'out.json')!r}).read_text())\n"
                            f"sys.exit({gh_code})\n", encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            env = dict(os.environ, PATH=f"{tmp}{os.pathsep}{os.environ.get('PATH', '')}")
            done = subprocess.run([sys.executable, "-m", "expectrail.attestation", *args], capture_output=True,
                                  text=True, cwd=ROOT, env=env, timeout=60)
            done.gh_args = json.loads(log.read_text()) if log.exists() else None
            return done

    def test_the_module_command_with_gh_on_the_path(self):
        args = ("check", str(RECEIPT), "--repo", REPO, "--signer-workflow", WORKFLOW)
        done = self.run_module(*args, gh_out=json.dumps([gh_result()]))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn(f"attestation: VERIFIED (by {WORKFLOW} at refs/heads/main)", done.stdout)
        self.assertIn("does not establish: clearance (that is trust-check's)", done.stdout)
        self.assertEqual(done.gh_args[:3], ["attestation", "verify", str(RECEIPT)])
        done = self.run_module(*args, gh_out=json.dumps([gh_result(runnerEnvironment="self-hosted")]))
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("attestation: NOT VERIFIED", done.stdout)
        self.assertIn("reason: attestation 1: run on 'self-hosted' runners, not GitHub's", done.stdout)
        done = self.run_module(*args, gh_out="[]")
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("Nothing was checked.", done.stderr)
        self.assertEqual(done.stdout, "")
        done = self.run_module("check", str(RECEIPT), "--repo", REPO, gh_out="[]")
        self.assertEqual(done.returncode, 2)
        self.assertIsNone(done.gh_args)


if __name__ == "__main__":
    unittest.main()
