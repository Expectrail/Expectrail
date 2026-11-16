"""Fail closed until a fixer invocation has a provable dollar bound.

The repository does not bind Muse Code's model, input tokenizer/context limit,
output/reasoning billing or mode to a verified per-request maximum. No environment
variable can turn the fixed-price stand-in into a certified live tariff.
"""
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import json
import os
from pathlib import Path
import uuid

from agents import fixer_meter
from expectrail import resources, spend
from expectrail.gate import record

ENV = 'EXPECTRAIL_FIXER_INVOCATION_USD_CAP'


def read(path):
    doc = record.read_json(Path(path), cap=65536, label='fixer invocation budget')
    schema = json.loads((resources.ROOT/'contracts/fixer-invocation.v1.schema.json').read_text())
    record.validate(doc,schema)
    cap, reserved, price = doc['capNanoUsd'],doc['reservedNanoUsd'],doc['requestMaxNanoUsd']
    if (doc['status'] in ('stopped','unavailable')) != (doc['stopReason'] is not None):
        raise ValueError('invocation stop reason disagrees with status')
    if doc['basis']=='fixed-price-fixture' and cap is None:
        raise ValueError('a fixture invocation needs its cap')
    if doc['basis']=='unavailable' and (doc['status']!='unavailable' or price is not None):
        raise ValueError('no live pricing policy is supported')
    if cap is not None and reserved > cap:raise ValueError('invocation reservation exceeds its cap')
    if doc['basis']=='fixed-price-fixture' and (price is None or reserved != price*doc['admittedRequests']):
        raise ValueError('invocation request reservations disagree')
    if doc['basis']=='unavailable' and (reserved or doc['admittedRequests']):
        raise ValueError('an unavailable live bound cannot forward requests')
    return doc


def stop(code, message, path, doc):
    doc.update(status='unavailable' if doc['basis']=='unavailable' else 'stopped',stopReason=code)
    try:
        fixer_meter.write(path,doc)
    except OSError:
        code, message = 'fixer-meter-unavailable', 'invocation counter cannot be written; no live send allowed'
    exc=spend.BudgetStop(code+': '+message,role='muse')
    exc.code=code;exc.invocation_record=Path(path)
    spend.note_stop('muse',str(exc))
    raise exc


def _cap():
    try:
        value=Decimal(os.environ.get(ENV,'').strip())
        if not value.is_finite() or value < 0:raise InvalidOperation
        return int((value*fixer_meter.NANO).to_integral_value(rounding=ROUND_FLOOR))
    except (InvalidOperation,ValueError,OverflowError):
        return None


def start(path):
    """Production admission. No live dollar tariff is presently supported."""
    cap=_cap()
    doc={'format':fixer_meter.FORMAT,'id':uuid.uuid4().hex,'basis':'unavailable',
         'capNanoUsd':cap,'requestMaxNanoUsd':None,'reservedNanoUsd':0,
         'admittedRequests':0,'deniedRequests':0,'inputTokensObserved':0,
         'outputTokensObserved':0,'status':'unavailable','stopReason':None}
    if cap is None:
        stop('fixer-invocation-cap-missing',ENV+' must be a finite nonnegative dollar amount',path,doc)
    if cap == 0:
        stop('fixer-invocation-cap', 'zero-dollar invocation permits no send',path,doc)
    # Do not start a CLI, warm its launcher, construct a gateway or read a key.
    stop('fixer-bound-unavailable','no verified maximum billable charge per Muse/BYO request; live fixer disabled',path,doc)


def fixture(path, *, cap_nano, request_nano, host='api.meta.ai', route='/v1/responses'):
    """Trusted offline harness only. Not reachable by a live CLI/configuration flag.

    Hold the entire invocation before its first request; the aggregate Muse role
    cap and existing locked monthly reservation cover it. A missing month ledger
    refuses admission. The price is the stand-in server's maximum, not a vendor price.
    """
    if not os.environ.get(spend.MODEL_LEDGER_ENV,'').strip():
        raise spend.BudgetStop('fixer-month-ledger-required',role='muse')
    spend.hold('muse',live=True,usd=cap_nano/fixer_meter.NANO)
    return fixer_meter.Meter({'id':uuid.uuid4().hex,'capNanoUsd':cap_nano,
        'requestMaxNanoUsd':request_nano,'host':host,'path':route,'record':str(path)})


def counter(path, *, expected=None):
    """A lost/corrupt proxy counter is a budget stop, never a failed repair."""
    try:
        doc = read(path)
        if expected is not None and (doc['basis'] != 'fixed-price-fixture' or
                any(doc[key] != expected[key] for key in ('id', 'capNanoUsd', 'requestMaxNanoUsd'))):
            raise ValueError('counter does not belong to the admitted invocation')
        return doc
    except (OSError, ValueError) as cause:
        exc=spend.BudgetStop('fixer-meter-unavailable: invocation counter is unreadable',role='muse')
        exc.code='fixer-meter-unavailable'
        spend.note_stop('muse',str(exc))
        raise exc from cause
