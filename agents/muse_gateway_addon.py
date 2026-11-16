"""mitmproxy addon: the Muse Code key gateway (experiment; see agents/muse_gateway.py).

Muse Code is given a placeholder key and this proxy as HTTPS_PROXY. For hosts on the allowlist
(Meta's API, ``*.meta.ai`` by default) the proxy replaces the placeholder, wherever it appears in a
request header, with the real key, which only this process holds. Every other host is refused, so
the agent can reach nothing else through it. Header values are never logged: each flow is recorded
as host, method, path, status and the names of the headers that carried the placeholder.

Loaded by mitmdump (``mitmdump -s agents/muse_gateway_addon.py``) in mitmproxy's own environment,
so it imports only the standard library and mitmproxy, and mitmproxy only inside the hooks.
"""
from __future__ import annotations

import json
import os
import time

PLACEHOLDER = os.environ.get("MUSE_GATEWAY_PLACEHOLDER", "")
REAL_KEY = os.environ.get("MUSE_GATEWAY_KEY", "")
ALLOW = tuple(s.strip().lower() for s in os.environ.get("MUSE_GATEWAY_HOSTS", ".meta.ai").split(",") if s.strip())
LOG = os.environ.get("MUSE_GATEWAY_LOG", "gateway-log.jsonl")


def host_allowed(host: str, allow: tuple[str, ...] = ALLOW) -> bool:
    """``.meta.ai`` allows meta.ai and every subdomain; ``api.example.com`` allows that host only."""
    host = (host or "").lower().rstrip(".")
    for rule in allow:
        if rule.startswith("."):
            if host == rule[1:] or host.endswith(rule):
                return True
        elif host == rule:
            return True
    return False


def swap(headers: list[tuple[str, str]], placeholder: str, real: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Headers with every occurrence of the placeholder replaced by the real key; and which names had it."""
    if not placeholder or not real:
        return list(headers), []
    out, names = [], []
    for name, value in headers:
        if placeholder in value:
            value = value.replace(placeholder, real)
            if name.lower() not in names:
                names.append(name.lower())
        out.append((name, value))
    return out, names


def _record(entry: dict) -> None:
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


class Gateway:
    def __init__(self, meter=None):
        self.meter = meter
        config = os.environ.get('MUSE_GATEWAY_METER_CONFIG')
        if meter is None and config:
            # mitmdump has its own environment; load only our sibling stdlib module.
            import importlib.util
            from pathlib import Path
            source = Path(__file__).with_name('fixer_meter.py')
            spec = importlib.util.spec_from_file_location('expectrail_fixer_meter', source)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.meter = module.Meter(json.loads(Path(config).read_text()))

    def http_connect(self, flow) -> None:
        # CONNECT is not an HTTP model call. Refuse other destinations before a
        # tunnel can become a path around the request hook.
        if self.meter is not None:
            from mitmproxy import http
            if flow.request.host != self.meter.config['host'] or flow.request.port != 443:
                flow.response = http.Response.make(403, b'fixer tunnel refused', {})

    def tcp_start(self, flow) -> None:
        if self.meter is not None:
            flow.kill()  # No generic TCP passthrough, even to an allowed hostname.

    def request(self, flow) -> None:
        from mitmproxy import http

        host = flow.request.pretty_host
        entry = {"t": round(time.time(), 3), "host": host, "method": flow.request.method,
                 "path": flow.request.path.split("?", 1)[0][:200]}
        if not host_allowed(host):
            flow.response = http.Response.make(403, b"blocked by the Muse key gateway: host not allowed",
                                               {"content-type": "text/plain"})
            entry.update(status=403, blocked=True)
            _record(entry)
            return
        if self.meter is not None:
            if flow.request.headers.get('upgrade'):
                flow.response = http.Response.make(403, b'fixer upgrade refused', {})
                return
            try:
                refusal = self.meter.admit(host=host, method=flow.request.method,
                    path=flow.request.path, port=flow.request.port, scheme=flow.request.scheme)
            except Exception:
                # A counter/write failure is a closed connection, never unmetered forwarding.
                self.meter.doc.update(status='stopped', stopReason='fixer-meter-unavailable')
                refusal = 503
            if refusal is not None:
                flow.response = http.Response.make(refusal, b'fixer invocation admission refused',
                                                   {'content-type': 'text/plain'})
                entry.update(status=refusal, blocked=True)
                _record(entry)
                return
        keys = list(dict.fromkeys(k.lower() for k in flow.request.headers))  # get_all ignores case
        pairs = [(k, v) for k in keys for v in flow.request.headers.get_all(k)]
        new, names = swap(pairs, PLACEHOLDER, REAL_KEY)
        if names:
            for name in names:
                flow.request.headers.set_all(name, [v for k, v in new if k.lower() == name])
        entry["swapped"] = names
        entry["placeholderInBody"] = bool(PLACEHOLDER) and PLACEHOLDER.encode() in (flow.request.raw_content or b"")
        flow.metadata["gateway"] = entry

    def responseheaders(self, flow) -> None:
        if self.meter is None:
            flow.response.stream = True  # legacy non-fixer gateway
        else:
            # Keep only a bounded tail for diagnostic usage. This does not claim to
            # stop upstream billing: affordability was reserved BEFORE forwarding.
            tail = bytearray()
            def stream(chunk):
                tail.extend(chunk)
                if len(tail) > 1024*1024:del tail[:-1024*1024]
                if not chunk:
                    self.meter.observe(bytes(tail))
                    flow.metadata['meterObserved'] = True
                return chunk
            flow.response.stream = stream

    def response(self, flow) -> None:
        if self.meter is not None and not flow.metadata.get('meterObserved'):
            self.meter.observe(flow.response.raw_content or b'')
            flow.metadata['meterObserved'] = True
        entry = flow.metadata.get("gateway")
        if entry is not None:
            entry["status"] = flow.response.status_code
            _record(entry)

    def error(self, flow) -> None:
        entry = flow.metadata.get("gateway") or {"host": flow.request.pretty_host if flow.request else None}
        entry["error"] = str(flow.error)[:200] if flow.error else "unknown"
        _record(entry)


addons = [Gateway()]
