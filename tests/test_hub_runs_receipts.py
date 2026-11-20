"""Offline tests for displaying a connected project's signed verdict."""
from datetime import datetime, timezone
import base64
import hashlib
import json
from pathlib import Path
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from expectrail import receipt, viewer
from hub.receipts import MAX_RECEIPT_BYTES, EvidenceUnavailable, ReceiptRefused, verify_published

EXAMPLES = Path(__file__).resolve().parents[1] / 'contracts/examples'
NOW = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
COMMIT = '1' * 40
REPOSITORY = 'studio/game'


class PublishedReceiptTest(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.trust = {'fixture': base64.b64encode(self.key.public_key().public_bytes_raw()).decode()}

    def fixture(self, decision='reject'):
        file = {'accept': 'findings-both-observers.json', 'reject': 'findings.json',
                'needs-review': 'findings-coverage.json'}[decision]
        evidence = (EXAMPLES / file).read_bytes()
        draft = json.loads((EXAMPLES / 'receipt.v1.json').read_bytes())
        del draft['signature']
        draft['publicKey'] = self.trust['fixture']
        draft.update(repository=REPOSITORY, issuerKeyId='fixture', decision=decision,
                     headSha256=hashlib.sha256(COMMIT.encode()).hexdigest(),
                     issuedAt='2026-11-20T00:00:00Z', expiresAt='2026-11-21T00:00:00Z')
        draft['evidence']['artifacts'] = {'report/findings.json': hashlib.sha256(evidence).hexdigest()}
        return draft, evidence

    def signed(self, draft, key=None):
        return json.dumps(receipt.write_receipt(draft, key or self.key)).encode()

    def verify(self, signed, evidence, **options):
        return verify_published(signed, evidence, self.trust,
                                **(dict(repository=REPOSITORY, commit=COMMIT, now=NOW) | options))

    def test_each_signed_decision_is_shown_verbatim(self):
        for decision in ('accept', 'reject', 'needs-review'):
            with self.subTest(decision=decision):
                draft, evidence = self.fixture(decision)
                # A valid non-accept or partial receipt can preserve a verdict without granting clearance.
                draft['evidence']['grade'] = 'partial'
                verified = self.verify(self.signed(draft), evidence)
                self.assertEqual(verified.decision, decision)
                page = viewer.render_published(verified.findings, verified.decision)
                self.assertIn(f'<h1>{decision}</h1>', page)
                self.assertIn('Expectrail evidence viewer', page)
                self.assertIn('Every check', page)
                self.assertNotIn('href="evidence.html"', page)
                self.assertNotIn('<script', page)

    def test_bad_signature_cannot_expose_an_accept_verdict(self):
        draft, evidence = self.fixture('accept')
        signed = json.loads(self.signed(draft))
        signed['decision'] = 'reject'
        with self.assertRaisesRegex(ReceiptRefused, 'signature does not verify'):
            self.verify(json.dumps(signed).encode(), evidence)

    def test_unknown_and_revoked_issuers_are_refused_on_each_read(self):
        draft, evidence = self.fixture()
        signed = self.signed(draft)
        self.assertEqual(self.verify(signed, evidence).decision, 'reject')
        key = self.trust['fixture']
        self.trust = receipt.parse_trust_store(json.dumps({
            'format': 'expectrail.trust-store/v2',
            'keys': [{'id': 'fixture', 'publicKey': key, 'validFrom': '2026-11-19T00:00:00Z',
                      'revoked': {'at': '2026-11-20T01:00:00Z', 'reason': 'Test revocation'}}],
        }))
        with self.assertRaisesRegex(ReceiptRefused, 'revoked'):
            self.verify(signed, evidence)
        self.trust.clear()
        with self.assertRaisesRegex(ReceiptRefused, 'unknown issuer'):
            self.verify(signed, evidence)

    def test_expiry_and_wrong_run_or_repository_are_refused(self):
        draft, evidence = self.fixture()
        signed = self.signed(draft)
        for fields, reason in [
            ({'now': datetime(2026, 11, 21, tzinfo=timezone.utc)}, 'stale'),
            ({'commit': '2' * 40}, 'head digest mismatch'),
            ({'repository': 'studio/other'}, 'repository mismatch'),
        ]:
            with self.subTest(reason=reason), self.assertRaisesRegex(ReceiptRefused, reason):
                self.verify(signed, evidence, **fields)

    def test_malformed_receipt_and_absent_or_changed_findings_are_distinct(self):
        draft, evidence = self.fixture()
        for raw in (b'false', b'{"decision":"accept","decision":"reject"}', b'\xff', b'{}'):
            with self.subTest(raw=raw), self.assertRaisesRegex(ReceiptRefused, 'malformed'):
                self.verify(raw, evidence)
        with self.assertRaisesRegex(ReceiptRefused, 'missing'):
            self.verify(None, evidence)
        with self.assertRaisesRegex(ReceiptRefused, 'size limit'):
            self.verify(b' ' * (MAX_RECEIPT_BYTES + 1), evidence)
        with self.assertRaisesRegex(EvidenceUnavailable, 'missing'):
            self.verify(self.signed(draft), None)
        with self.assertRaisesRegex(EvidenceUnavailable, 'digest'):
            self.verify(self.signed(draft), evidence + b'\n')
        draft['evidence']['artifacts'] = {}
        with self.assertRaisesRegex(EvidenceUnavailable, 'does not bind'):
            self.verify(self.signed(draft), evidence)

    def test_signed_bytes_cannot_swap_the_verdict_or_bypass_the_findings_reader(self):
        draft, evidence = self.fixture()
        draft['decision'] = 'accept'
        with self.assertRaisesRegex(EvidenceUnavailable, 'decisions disagree'):
            self.verify(self.signed(draft), evidence)
        broken = json.loads(evidence)
        broken['checks'] = None
        raw = json.dumps(broken).encode()
        draft['evidence']['artifacts']['report/findings.json'] = hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(EvidenceUnavailable, 'unusable'):
            self.verify(self.signed(draft), raw)
