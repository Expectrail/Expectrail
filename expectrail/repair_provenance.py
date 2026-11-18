"""Validate recorded provider-only execution before publishing a repair sample.

This checks historical records locally, never calls a provider, and never declares
a candidate accepted. Run it still invokes the gate on the saved patch.
"""
from decimal import Decimal
import hashlib
from pathlib import Path

from expectrail import fixer_budget
from expectrail.gate import record


def provider_only(path, doc):
    if doc['fixer'] != {'source': 'llm-patch', 'sandboxed': False, 'providerOnly': True}:
        raise ValueError('record does not name controlled provider-only execution')
    cap = doc['budget']['usdCap']
    if cap is None or cap <= 0: raise ValueError('record has no aggregate fixer cap')
    total = 0
    for attempt in doc['attempts']:
        expected = f"attempt-{attempt['n']}/fixer-invocation.json"
        if attempt.get('fixerInvocation') != expected:
            raise ValueError('record has no bound invocation proof')
        try:
            target = record.unlinked_below(Path(path).parent, expected)
        except record.RecordError: raise ValueError('linked invocation proof') from None
        raw = record.read_bytes_capped(target, 2*1024*1024, 'fixer invocation proof')
        if hashlib.sha256(raw).hexdigest() != attempt.get('fixerInvocationSha256'):
            raise ValueError('invocation proof digest differs')
        meter = fixer_budget.read(target)
        if (meter['basis'] != 'token-price' or meter['status'] != 'completed'
                or meter['stopReason'] is not None or not meter['admittedRequests']
                or meter.get('availability', {}).get('status') != 'available'
                or meter['availability']['model'] != meter['pricing']['model']):
            raise ValueError('invocation has no completed priced provider admission')
        for row in meter['requests']:
            usage = row['reportedUsage']
            if (usage is None or usage['outputTokens'] > row['outputTokenCap']
                    or usage['inputTokens'] > row['inputTokenBound']):
                raise ValueError('provider usage proof is absent or violates its reservation')
        total += meter['capNanoUsd']
    if not doc['attempts'] or Decimal(total) > Decimal(str(cap))*10**9:
        raise ValueError('invocation holds exceed the aggregate cap')
    return True


def publishable(path, doc):
    """Only a genuine execution kind; a fixture cannot be relabelled by a bool."""
    source = doc['fixer']['source']
    if source in ('fixture', 'recorded', 'not-run'):
        raise ValueError('this sample needs an original live repair recording')
    if source == 'llm-patch': return provider_only(path, doc)
    if not doc['fixer']['sandboxed'] or doc['fixer'].get('providerOnly'):
        raise ValueError('this sample needs a sandboxed agent or proved provider-only execution')
    return True
