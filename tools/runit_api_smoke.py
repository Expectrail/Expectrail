"""Check a deployed Run it service without credentials or dispatch retries.

python3 tools/runit_api_smoke.py https://api.expectrail.tech --expect-open false
python3 tools/runit_api_smoke.py https://api.expectrail.tech --expect-open true
Only the second command can start one recorded-vision sample (no model call).
python3 -m tools.runit_api_smoke https://api.expectrail.tech --expect-open true --follow --wait 900
also follows that run to ``published`` and reads the published result as the page does
(tools/runit_published.py): the decision, the vision answers, findings, the evidence and latest.json.
"""
from __future__ import annotations

import argparse
import http.client
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

FORMAT = "expectrail.run-it-api/v1"
ORIGIN = "https://expectrail.tech"
SAMPLES = ("clean", "fall-through-bug", "fall-through-repair")
# Cloudflare's browser integrity check refuses the default Python-urllib agent (error 1010).
USER_AGENT = "expectrail-runit-smoke/1 (+https://expectrail.tech)"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def base_url(value):
    u = urllib.parse.urlsplit(value)
    if (u.username is not None or u.password is not None or u.query or u.fragment
            or u.path.rstrip("/") not in ("", "/api")
            or not u.hostname
            or not (u.scheme == "https" or (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost", "::1")))):
        raise ValueError("Use an HTTPS service URL, without credentials, query or fragment (HTTP is allowed only on loopback).")
    return value.rstrip("/")


def request(url, method="GET", body=None, origin=ORIGIN, timeout=10):
    # No credentials, cookies, environment keys, redirects, or proxy credentials.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    headers = {"Origin": origin, "Accept": "application/json", "User-Agent": USER_AGENT}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers=headers, method=method)
    try:
        response = opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("Service response exceeded 64 KiB")
        doc = json.loads(raw)
        if not isinstance(doc, dict) or doc.get("format") != FORMAT:
            raise ValueError("Response is not expectrail.run-it-api/v1")
        return response.status, dict(response.headers.items()), doc


def smoke(url, *, expect_open="auto", sample="fall-through-bug", wait=180, poll=10,
          allow_stand_in=False, follow=None, send=request, clock=time.monotonic, sleep=time.sleep, emit=print):
    """Return 0 only if every requested check passes; clocks/transports are injectable offline.

    With ``follow`` (a callable taking the request id and the sample), progress waits for the
    service to say ``published`` and the result is what ``follow`` returns; without it, progress
    passes once the run is running, which is not a verdict check."""
    def check(ok, name, detail):
        emit(f'{"PASS" if ok else "FAIL"} {name}: {detail}')
        return ok

    stage = "health"
    try:
        url = base_url(url)
        if sample not in SAMPLES or wait <= 0 or poll <= 0:
            raise ValueError("Choose a recorded sample and positive wait/poll seconds")
        code, headers, health = send(url + "/health")
        cors = lambda h: next((v for k, v in h.items() if k.lower() == "access-control-allow-origin"), None)
        ok = (code == 200 and health.get("kind") == "health" and type(health.get("open")) is bool
              and type(health.get("standIn")) is bool and cors(headers) == ORIGIN)
        if not check(ok, stage, "health and page-origin access" if ok else "unusable health or CORS response"):
            return 1
        if health["standIn"] and not allow_stand_in:
            check(False, stage, "stand-in service; this is not a deployed game run")
            return 1
        stage = "disallowed origin"
        code, headers, doc = send(url + "/run", "POST", {"sample": "smoke-invalid-sample"},
                                  origin="https://disallowed.invalid")
        ok = code == 403 and doc.get("kind") == "refused" and doc.get("reason") == "bad-request" and cors(headers) is None
        if not check(ok, stage, "refused without CORS access" if ok else "origin was not refused correctly"):
            return 1
        stage = "RUN_IT_OPEN"
        expected = {"auto": health["open"], "true": True, "false": False}[expect_open]
        if not check(health["open"] == expected, stage,
                     f'health says {"open" if health["open"] else "closed"}; expected {expect_open}'):
            return 1
        if not health["open"]:
            check(True, "sample start", "not attempted: service closed; zero valid start requests sent")
            check(True, "progress", "not applicable while closed")
            return 0
        stage = "sample start"
        code, headers, doc = send(url + "/run", "POST", {"sample": sample})
        rid = doc.get("requestId", "")
        ok = (code == 202 and doc.get("kind") == "accepted" and doc.get("sample") == sample
              and isinstance(rid, str) and re.fullmatch(r"[a-z0-9-]{1,40}", rid) is not None
              and cors(headers) == ORIGIN)
        if not check(ok, stage, f'reservation {rid}' if ok else f'HTTP {code}, {doc.get("reason", "invalid response")}; no retry'):
            return 1
        stage = "progress"
        deadline = clock() + wait
        while clock() < deadline:
            code, headers, doc = send(url + "/status/" + rid, timeout=min(10, max(.01, deadline - clock())))
            if (code != 200 or doc.get("kind") != "status" or doc.get("requestId") != rid
                    or doc.get("sample") != sample or cors(headers) != ORIGIN
                    or doc.get("standIn") is not health["standIn"]):
                raise ValueError("status does not match the reserved run or page access")
            state = doc.get("state")
            if follow is not None and state == "published":
                check(True, stage, f"{rid}: published")
                return follow(rid, sample)
            if follow is not None and state in ("queued", "running", "publishing"):
                sleep(min(poll, max(0, deadline - clock())))
                continue
            if state in ("running", "publishing", "published"):
                check(True, stage, f'{rid}: {state}; {"stand-in only" if health["standIn"] else "this is not a verdict check"}')
                return 0
            if state != "queued":
                check(False, stage, f"run reports {state}; no verdict confirmed; no second start sent")
                return 1
            sleep(min(poll, max(0, deadline - clock())))
        check(False, stage, f"{rid}: still {state} after {wait:g} seconds; no second start sent")
        return 1
    except (OSError, ValueError, KeyError, http.client.HTTPException, urllib.error.URLError) as error:
        # Avoid reflecting server bodies or arbitrary transport exception strings into logs.
        check(False, stage, f"{type(error).__name__}; could not complete check; no start retry")
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("api_url")
    parser.add_argument("--expect-open", choices=("auto", "true", "false"), default="auto")
    parser.add_argument("--sample", choices=SAMPLES, default="fall-through-bug")
    parser.add_argument("--wait", type=float, default=180)
    parser.add_argument("--poll", type=float, default=10)
    parser.add_argument("--allow-stand-in", action="store_true", help="offline testing only")
    parser.add_argument("--follow", action="store_true",
                        help="wait for the run to be published and read its published result")
    parser.add_argument("--results-url", default=None, help="where the page reads published runs")
    parser.add_argument("--publish-wait", type=float, default=360,
                        help="seconds to wait for the published files after the service says published")
    args = parser.parse_args(argv)
    follow = None
    if args.follow:
        try:
            from tools import runit_published as published
        except ImportError:   # run as a script: the repository root is one level up
            import os
            import sys
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from tools import runit_published as published
        results = args.results_url or published.RESULTS
        follow = lambda rid, sample: published.follow(rid, sample, results=results, wait=args.publish_wait,
                                                     poll=args.poll)
    return smoke(args.api_url, expect_open=args.expect_open, sample=args.sample, wait=args.wait,
                 poll=args.poll, allow_stand_in=args.allow_stand_in, follow=follow)


if __name__ == "__main__":
    raise SystemExit(main())
