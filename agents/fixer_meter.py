"""Host-owned admission meter. Fixed-price fixtures only; no live tariff is certified.

No token/billing inference: response usage is diagnostic. Only an independently
bounded per-request charge could justify the pre-send reservation this meter uses.
Standard library only so the existing isolated mitmproxy process can load it.
"""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import threading

FORMAT = 'expectrail.fixer-invocation/v1'
NANO = 1_000_000_000


def write(path, doc):
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(doc, sort_keys=True, allow_nan=False) + '\n'
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.fixer-meter-', delete=False) as f:
        temporary = Path(f.name)
        f.write(data)
    try:temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


class Meter:
    """One trusted proxy process, serial admission including concurrent requests.

    The config is written outside the fixer's mount. There is deliberately no
    production price/model policy: fixture prices must never be used for Muse.
    """
    def __init__(self, config):
        if set(config) != {'id','capNanoUsd','requestMaxNanoUsd','host','path','record'}:
            raise ValueError('unknown or missing invocation configuration field')
        self.config = dict(config)
        cap, price = config['capNanoUsd'], config['requestMaxNanoUsd']
        if type(cap) is not int or type(price) is not int or cap < 0 or price <= 0:
            raise ValueError('invalid fixed-price fixture reservation')
        self.lock = threading.Lock()
        self.doc = {'format':FORMAT,'id':config['id'],'basis':'fixed-price-fixture',
                    'capNanoUsd':cap,'requestMaxNanoUsd':price,'reservedNanoUsd':0,
                    'admittedRequests':0,'deniedRequests':0,'inputTokensObserved':0,
                    'outputTokensObserved':0,'status':'running','stopReason':None}
        self.persist()

    def persist(self):write(self.config['record'],self.doc)

    def admit(self, *, host, method, path, port=443, scheme='https'):
        with self.lock:
            if (host != self.config['host'] or method != 'POST' or path != self.config['path']
                    or port != 443 or scheme != 'https'):
                self.doc['deniedRequests'] += 1;self.persist();return 403
            if self.doc['status'] != 'running':
                self.doc['deniedRequests'] += 1;self.persist()
                return 503 if self.doc['stopReason']=='fixer-meter-unavailable' else 429
            if self.doc['reservedNanoUsd'] + self.config['requestMaxNanoUsd'] > self.doc['capNanoUsd']:
                self.doc.update(status='stopped',stopReason='fixer-invocation-cap')
                self.doc['deniedRequests'] += 1;self.persist();return 429
            self.doc['reservedNanoUsd'] += self.config['requestMaxNanoUsd']
            self.doc['admittedRequests'] += 1
            self.persist()  # A failed write raises before a request can be forwarded.
            return None

    def observe(self, content):
        # Usage received after a request cannot make that request affordable retroactively.
        # Never refund a reservation, including errors, disconnects or missing usage.
        if not isinstance(content, bytes) or len(content) > 1024*1024:return
        records=[]
        for line in content.splitlines():
            if line.startswith(b'data:'):line=line[5:].strip()
            try:records.append(json.loads(line))
            except (ValueError,UnicodeError):pass
        if not records:
            try:records=[json.loads(content)]
            except (ValueError,UnicodeError):return
        usage=next((r['usage'] for r in reversed(records) if isinstance(r,dict) and isinstance(r.get('usage'),dict)),{})
        with self.lock:
            for field,wire in [('inputTokensObserved','input_tokens'),('outputTokensObserved','output_tokens')]:
                value=usage.get(wire)
                if type(value) is int and value >= 0:self.doc[field]+=value
            self.persist()

    def finish(self):
        with self.lock:
            if self.doc['reservedNanoUsd'] == self.doc['capNanoUsd']:
                self.doc.update(status='stopped',stopReason='fixer-invocation-cap')
            elif self.doc['status']=='running':self.doc['status']='completed'
            self.persist()
            return dict(self.doc)
