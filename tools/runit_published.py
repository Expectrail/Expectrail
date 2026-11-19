"""Follow a deployed Run it run to its published result, the way the page reads it.

The deployed HTTP smoke (tools/runit_api_smoke.py) stops once a reserved run is running. With
``--follow`` it hands the run to ``follow()`` here, which waits for the service to say
``published`` and then reads what a visitor would be shown, from the same address the page uses:

- ``<results>/<request id>/status.json``: the published result. It must match its schema, name this
  request and sample, have completed, and decide what the sample is expected to decide. An accept
  needs recorded vision answers behind every question; a frame with no recorded answer fails.
- ``findings.json`` when status.json names it: a valid findings record with the same decision.
- ``viewer/evidence.html``: the evidence viewer's one-file page, with its Content-Security-Policy.
- ``<results>/latest.json``: the card index names this run, or a later one, for the sample.

Anything that cannot be read or does not match is a FAIL. "Cannot tell" is never a pass.
Nothing read here is run, and no second run is started.
"""
from __future__ import annotations

import http.client
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:   # run as a script from tools/, the package lives one level up
    sys.path.insert(0, str(ROOT))

from expectrail import runit, runit_site, viewer   # noqa: E402
from expectrail.gate import record as rec          # noqa: E402

RESULTS = "https://raw.githubusercontent.com/Expectrail/Expectrail/run-it-results"
USER_AGENT = "expectrail-runit-nightly/1 (+https://expectrail.tech)"
ID = re.compile(r"[a-z0-9-]{1,40}")
CAPS = {"status.json": runit.MAX_STATUS_BYTES, "findings.json": runit.MAX_FILE_BYTES,
        "viewer/evidence.html": runit.MAX_FILE_BYTES, "latest.json": runit_site.MAX_LATEST_BYTES}


class Missing(Exception):
    """The file is not there (yet): HTTP 404. Raw GitHub content can lag a few minutes."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def results_base(value: str) -> str:
    u = urllib.parse.urlsplit(value)
    if (u.username is not None or u.password is not None or u.query or u.fragment or not u.hostname
            or not (u.scheme == "https" or (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost", "::1")))):
        raise ValueError("Use an HTTPS results URL, without credentials, query or fragment (HTTP only on loopback).")
    return value.rstrip("/")


def fetch(url: str, cap: int, timeout: float = 20) -> bytes:
    """GET one published file: no credentials, cookies, proxy credentials or redirects; at most cap bytes."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    try:
        response = opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as error:
        error.close()
        if error.code == 404:
            raise Missing(url) from None
        raise ValueError(f"HTTP {error.code}") from None
    with response:
        if response.status != 200:
            raise ValueError(f"HTTP {response.status}")
        data = response.read(cap + 1)
    if len(data) > cap:
        raise ValueError("larger than its cap")
    return data


def _no_constant(name):
    raise ValueError(f"{name} is not JSON")


def _no_duplicates(pairs):
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("a key appears twice")
    return dict(pairs)


def strict_json(data: bytes):
    return json.loads(data.decode("utf-8"), parse_constant=_no_constant, object_pairs_hook=_no_duplicates)


def status_problems(status, request_id: str, sample: dict, root: Path = ROOT) -> list[str]:
    """Every reason the published status.json does not show this sample's expected result."""
    found = rec.errors(status, runit._schema(root, runit.RESULT_SCHEMA))
    if found:
        return [f"status.json does not match its schema: {found[0]}"]
    problems = []
    if status["requestId"] != request_id:
        problems.append("status.json is for another request")
    if status["sample"]["id"] != sample["id"]:
        problems.append("status.json is for another sample")
    if status["phase"] != "completed":
        problems.append(f"the job ended {status['phase']}, with no decision")
    v = status["vision"]
    if v["recorded"] is not True:
        problems.append("no recorded vision answers were used")
    elif v["asked"] == 0 or v["answered"] != v["asked"] or v["notRecorded"]:
        problems.append(f"{v['answered']} of {v['asked']} vision questions answered from the recording "
                        f"({v['notRecorded']} with no recorded answer)")
    if status["decision"] == "accept" and (v["recorded"] is not True or v["notRecorded"] or v["answered"] == 0):
        problems.append("an accept without recorded vision answers behind it")
    if status["decision"] != sample["expected"]:
        problems.append(f"decided {status['decision']}; this sample is expected to decide {sample['expected']}")
    if status["asExpected"] is not (status["decision"] == sample["expected"] and v["recorded"] is True):
        problems.append("status.json's asExpected disagrees with its own decision")
    if status["receipt"]["signed"] is not False:
        problems.append("the receipt claims a signature this check cannot verify")
    return problems


def rendering_note(vision: dict) -> str:
    """The rendering environment beside the recording's, when the result names it (#265, #515). It is
    reported, never judged: a run whose every question was answered from the recording already passed."""
    rendering = vision.get("rendering")
    if not isinstance(rendering, dict):
        return "; rendering environment not in this result"
    from expectrail import recorded
    return f"; rendering {rendering.get('status')}: {recorded.rendering_sentence(rendering)}"


def follow(request_id: str, sample_id: str, *, results: str = RESULTS, wait: float = 360, poll: float = 15,
           get=fetch, clock=time.monotonic, sleep=time.sleep, emit=print, root: Path = ROOT) -> int:
    """Read the published run. Return 0 only if every published file shows the expected result."""
    def check(ok, name, detail):
        emit(f'{"PASS" if ok else "FAIL"} {name}: {detail}')
        return ok

    stage = "published result"
    try:
        if not ID.fullmatch(request_id or "") or not ID.fullmatch(sample_id or ""):
            raise ValueError("not a plain request or sample id")
        base = results_base(results)
        sample = runit.find_sample(runit.read_manifest(root), sample_id)
        deadline = clock() + wait

        def until_there(path):
            cap = CAPS[path if path == "latest.json" else path.split("/", 1)[1]]
            while True:
                try:
                    return get(f"{base}/{path}", cap)
                except Missing:
                    if clock() >= deadline:
                        raise
                    sleep(min(poll, max(0, deadline - clock())))

        status = strict_json(until_there(f"{request_id}/status.json"))
        problems = status_problems(status, request_id, sample, root)
        if not check(not problems, stage, "; ".join(problems) if problems else
                     f"{status['decision']}, as {sample_id} is expected to decide; "
                     f"{status['vision']['answered']} of {status['vision']['asked']} vision answers from the recording "
                     f"of {status['vision']['recordedAt']}; receipt {status['receipt']['why']}"
                     + rendering_note(status["vision"])):
            return 1

        stage = "findings"
        if status["findings"] is None:
            if not check(status["decision"] != "accept", stage, "an accept with no findings record"
                         if status["decision"] == "accept" else "none published, and none is needed for this decision"):
                return 1
        else:
            record = strict_json(until_there(f"{request_id}/findings.json"))
            try:
                rec.check_record(record)
            except rec.RecordError as exc:
                check(False, stage, f"not a valid findings record ({str(exc)[:120]})")
                return 1
            if not check(record["decision"] == status["decision"], stage,
                         f"findings.json decides {record['decision']}" if record["decision"] == status["decision"]
                         else "findings.json and status.json disagree about the decision"):
                return 1

        stage = "evidence"
        html = until_there(f"{request_id}/viewer/evidence.html").decode("utf-8")
        csp = f'<meta http-equiv="Content-Security-Policy" content="{viewer.CSP}">'
        if not check(html.lower().startswith("<!doctype html>") and csp in html[:4096], stage,
                     f"the evidence viewer is published ({len(html)} characters)"
                     if html.lower().startswith("<!doctype html>") and csp in html[:4096]
                     else "not the viewer's page (its Content-Security-Policy is not at the top)"):
            return 1

        stage = "latest"
        while True:
            latest = strict_json(until_there("latest.json"))
            found = rec.errors(latest, runit._schema(root, runit_site.LATEST_SCHEMA))
            if found:
                check(False, stage, f"latest.json does not match its schema: {found[0]}")
                return 1
            row = latest["samples"].get(sample_id)
            if row and (row["requestId"] == request_id or row["finishedAt"] > status["finishedAt"]):
                check(True, stage, f"the {sample_id} card names {row['requestId']}"
                      + ("" if row["requestId"] == request_id else ", a later run"))
                return 0
            if clock() >= deadline:
                check(False, stage, f"latest.json does not name {request_id} for {sample_id} "
                      f"after {wait:g} seconds; the card would show an earlier run")
                return 1
            sleep(min(poll, max(0, deadline - clock())))
    except Missing:
        check(False, stage, f"not published after {wait:g} seconds; cannot tell what a visitor sees")
        return 1
    except (OSError, ValueError, KeyError, UnicodeDecodeError, runit.RunItError,
            http.client.HTTPException, urllib.error.URLError) as error:
        # Never reflect a published body or a transport string into the log.
        check(False, stage, f"{type(error).__name__}; cannot tell what a visitor sees")
        return 1
