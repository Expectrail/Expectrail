"""Host-owned admission for fixed-price fixtures and controlled text requests.

The repository does not bind Muse Code's model, input tokenizer/context limit,
output/reasoning billing or mode to a verified per-request maximum. A recorded tariff and text-byte bound enable only llm-patch. No environment
variable can turn the fixed-price stand-in into a certified live CLI tariff.
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
    doc = record.read_json(Path(path), cap=2*1024*1024, label='fixer invocation budget')
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
    if doc['basis']=='token-price':
        if cap is None or price is not None or 'pricing' not in doc or 'requests' not in doc:
            raise ValueError('token invocation needs pricing and request reservations')
        rows, tariff = doc['requests'], doc['pricing']
        if len(rows) != doc['admittedRequests'] or sum(r['reservedNanoUsd'] for r in rows) != reserved:
            raise ValueError('token reservations disagree')
        for r in rows:
            if r['reservedNanoUsd'] != r['inputTokenBound']*tariff['inputNanoUsdPerToken'] + r['outputTokenCap']*tariff['outputNanoUsdPerToken']:
                raise ValueError('request maximum disagrees with tariff')
        for field, wire in [('inputTokensObserved','inputTokens'),('outputTokensObserved','outputTokens')]:
            if doc[field] != sum((r['reportedUsage'] or {}).get(wire,0) for r in rows):
                raise ValueError('reported usage totals disagree')
    elif 'pricing' in doc or 'requests' in doc:
        raise ValueError('pricing belongs only to token-priced invocations')
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
        numerator, denominator = value.as_integer_ratio()
        return numerator*fixer_meter.NANO//denominator
    except (InvalidOperation,ValueError,OverflowError):
        return None


def start(path, *, config=None):
    """Refuse CLI fixers; admit only a supported controlled request policy."""
    cap=_cap()
    doc={'format':fixer_meter.FORMAT,'id':uuid.uuid4().hex,'basis':'unavailable',
         'capNanoUsd':cap,'requestMaxNanoUsd':None,'reservedNanoUsd':0,
         'admittedRequests':0,'deniedRequests':0,'inputTokensObserved':0,
         'outputTokensObserved':0,'status':'unavailable','stopReason':None}
    if cap is None:
        stop('fixer-invocation-cap-missing',ENV+' must be a finite nonnegative dollar amount',path,doc)
    if cap == 0:
        stop('fixer-invocation-cap', 'zero-dollar invocation permits no send',path,doc)
    if config is not None:
        return _start_controlled(path, doc, config)
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


def _start_controlled(path, doc, config):
    """Only our text-only llm-patch sender can use a recorded token tariff."""
    try:
        capability = spend.read_provider_capability(resources.ROOT / 'contracts/examples/provider-capabilities' / (config.provider+'.json'))
        price = next(p for p in capability.get('tokenPrices',[]) if p['model']==config.model)
        # A byte bound is supported only for this byte-BPE text model/protocol.
        if (config.provider,config.protocol,config.model) != ('openai','openai','gpt-4o'):
            raise ValueError('unsupported input-token bound')
        if config.api_base != 'https://api.openai.com/v1':
            raise ValueError('unpriced endpoint')
    except (OSError,ValueError,StopIteration) as exc:
        stop('fixer-bound-unavailable','no recorded supported tariff for provider/model/endpoint',path,doc)
    if not os.environ.get(spend.MODEL_LEDGER_ENV,'').strip():
        stop('fixer-month-ledger-required','monthly reservation ledger is required',path,doc)
    # Reserve F against the aggregate role cap and the existing month ledger once.
    # Request reservations below spend this hold; they never hold the same dollars twice.
    spend.hold('muse',live=True,usd=doc['capNanoUsd']/fixer_meter.NANO)
    return TokenMeter(path,doc,config,price)


class TokenMeter(fixer_meter.Meter):
    """Trusted sender's meter; serializes admission, send and response observation.

    One UTF-8 JSON byte per token is an upper bound for text byte-BPE merges.
    We add 1024 tokens plus 64 per message for framing (versus the published
    GPT-4o recipe's 3/message + 3/reply). Full JSON includes roles, escapes and
    schema bytes. This is an upper bound, not a tokenizer estimate or discount.
    Provider billing must honor its documented text tokenization and max_tokens.
    """
    def __init__(self,path,doc,config,price):
        import threading
        self.config={'record':str(path)}
        self.provider_config=config
        self.lock=threading.RLock()
        self.doc={**doc,'basis':'token-price','status':'running','stopReason':None,
                  'pricing':{'provider':config.provider,**{k:v for k,v in price.items() if k!='checkedOn'}},'requests':[]}
        self.persist()

    def persist(self):
        try:
            super().persist()
        except OSError as cause:
            self.doc.update(status='stopped',stopReason='fixer-meter-unavailable')
            exc=spend.BudgetStop('fixer-meter-unavailable: durable counter write failed',role='muse')
            exc.code='fixer-meter-unavailable';exc.invocation_record=Path(self.config['record'])
            spend.note_stop('muse',str(exc))
            raise exc from cause

    def fail(self,code,message):
        stop(code,message,self.config['record'],self.doc)

    def reserve_request(self,config,url,payload,body):
        import hashlib
        with self.lock:
            payload=json.loads(body)  # Price the immutable bytes that the sender forwards.
            if config != self.provider_config or url != config.api_base+'/chat/completions':
                self.fail('fixer-bound-unavailable','request endpoint/config changed')
            if (set(payload)-{'model','messages','max_tokens','temperature','response_format'} or
                    payload.get('model') != config.model or type(payload.get('max_tokens')) is not int or
                    not 1 <= payload['max_tokens'] <= 4096 or not isinstance(payload.get('messages'),list) or
                    not payload['messages'] or any(set(m)!={'role','content'} or
                        m['role'] not in ('system','user','assistant') or not isinstance(m['content'],str)
                        for m in payload['messages'])):
                self.fail('fixer-bound-unavailable','unsupported billable request shape')
            if len(self.doc['requests']) >= 1024:
                self.fail('fixer-invocation-cap','request record limit reached')
            bound=len(body)+1024+64*len(payload['messages'])
            tariff=self.doc['pricing']; amount=bound*tariff['inputNanoUsdPerToken']+payload['max_tokens']*tariff['outputNanoUsdPerToken']
            # Stage row before the shared durable admission writes it. Roll back if denied.
            row={'bodyBytes':len(body),'bodySha256':hashlib.sha256(body).hexdigest(),
                 'inputTokenBound':bound,'outputTokenCap':payload['max_tokens'],
                 'reservedNanoUsd':amount,'reportedUsage':None}
            self.doc['requests'].append(row)
            try:
                status=self.reserve_locked(amount)
            except OSError:
                self.fail('fixer-meter-unavailable','reservation cannot be persisted')
            if status is not None:
                self.doc['requests'].pop()
                self.fail(self.doc['stopReason'] or 'fixer-invocation-cap','request not forwarded')
            return len(self.doc['requests'])-1

    def observe_request(self,index,response):
        with self.lock:
            row=self.doc['requests'][index]
            usage=response.get('usage',{}) if isinstance(response,dict) else {}
            inp,out=usage.get('prompt_tokens'),usage.get('completion_tokens')
            if type(inp) is not int or inp < 0 or type(out) is not int or out < 0:
                self.fail('fixer-provider-violation','provider omitted valid usage; no further sends')
            if row['reportedUsage'] is not None:
                self.fail('fixer-provider-violation','duplicate response accounting')
            row['reportedUsage']={'inputTokens':inp,'outputTokens':out}
            self.doc['inputTokensObserved']+=inp;self.doc['outputTokensObserved']+=out
            self.persist()
            if inp > row['inputTokenBound'] or out > row['outputTokenCap']:
                self.fail('fixer-provider-violation','reported usage exceeds reserved token bound')

    def finish(self):
        with self.lock:
            if self.doc['status']=='running' and self.doc['reservedNanoUsd']==self.doc['capNanoUsd']:
                self.fail('fixer-invocation-cap','invocation cap reached; candidate withheld')
            if self.doc['status']=='running':self.doc['status']='completed'
            self.persist()
            return dict(self.doc)
