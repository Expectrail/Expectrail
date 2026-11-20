"""Offline verification of a connected project's published receipt and findings."""
from dataclasses import dataclass
import hashlib
import re

from expectrail import receipt
from expectrail.gate import record

MAX_RECEIPT_BYTES = 1024 * 1024
FINDINGS_NAME = 'report/findings.json'


class ReceiptRefused(ValueError):
    """The receipt cannot authenticate a verdict for this repository and run."""


class EvidenceUnavailable(ValueError):
    """The run did not provide usable, bound findings."""


@dataclass(frozen=True)
class PublishedRun:
    decision: str
    findings: dict


def verify_published(receipt_bytes, findings_bytes, trust_store, *, repository, commit, now=None):
    """Read only in-memory published data and verify it anew with the caller's current trust store.

    Repository and commit come from the authorized repository and run metadata.
    Signature, issuer, freshness and those pins authenticate the published verdict.
    This display does not grant clearance or independently establish build or policy.
    """
    if receipt_bytes is None:
        raise ReceiptRefused('receipt is missing')
    if len(receipt_bytes) > MAX_RECEIPT_BYTES:
        raise ReceiptRefused('receipt exceeds the size limit')
    try:
        signed = receipt.strict_loads(receipt_bytes.decode('utf-8'))
        if not isinstance(signed, dict):
            raise ValueError('receipt must be an object')
        receipt._validate_receipt(signed)
        for field in ('issuedAt', 'expiresAt'):
            receipt.check_timestamp(signed[field], field)
    except (ValueError, RecursionError):
        raise ReceiptRefused('receipt is malformed') from None
    if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ReceiptRefused('the run has no usable commit')
    head = hashlib.sha256(commit.encode('ascii')).hexdigest()
    checked = receipt.check_receipt(signed, trust_store, expect_repo=repository, expect_head=head, now=now)
    if not checked['known_issuer'] or not checked['valid_signature']:
        raise ReceiptRefused(checked['reasons'][0])
    if not repository or signed['repository'] != repository:
        raise ReceiptRefused('repository mismatch')
    if signed['headSha256'] != head:
        raise ReceiptRefused('head digest mismatch')
    if not checked['fresh']:
        raise ReceiptRefused('stale, not yet valid, or invalid receipt lifetime')

    if findings_bytes is None:
        raise EvidenceUnavailable('published findings are missing')
    if len(findings_bytes) > record.MAX_RECORD_BYTES:
        raise EvidenceUnavailable('published findings exceed the size limit')
    expected = signed['evidence']['artifacts'].get(FINDINGS_NAME)
    if expected is None:
        raise EvidenceUnavailable('receipt does not bind the published findings')
    if hashlib.sha256(findings_bytes).hexdigest() != expected:
        raise EvidenceUnavailable('published findings digest does not match the receipt')
    try:
        findings = record.strict_loads(findings_bytes.decode('utf-8'))
        record.check_record(findings)
    except (ValueError, RecursionError):
        raise EvidenceUnavailable('published findings are unusable') from None
    if findings['decision'] != signed['decision']:
        raise EvidenceUnavailable('receipt and published findings decisions disagree')
    return PublishedRun(signed['decision'], findings)
