"""A scripted burst against a Run it service (#265, slice 3): the local stub, the edge function on a
local runtime, or the deployed one.

    python3 -m tools.runit_burst http://127.0.0.1:8765/api --count 50
    python3 -m tools.runit_burst https://api.expectrail.tech --count 20      (starts at most one real run)

It sends ``--count`` requests to start a run at the same moment, from one machine, and reports what
came back. It fails (exit 1) when more than one run was accepted, when any answer is not a body of the
contract (``expectrail.run-it-api/v1``), or when a refusal does not say which limit. Against the
deployed service it uses up one of this machine's visitor runs and, at most, one run of the day.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import urllib.error
import urllib.request
from collections import Counter

from expectrail import runit_site


def post(url: str, body: bytes, origin: str, timeout: float) -> tuple[int, object]:
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Origin": origin,
                                          "User-Agent": "expectrail-runit-burst"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read()
    except (urllib.error.URLError, OSError) as e:
        return 0, f"no answer ({type(e).__name__})"
    try:
        return code, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return code, "not JSON"


def burst(base: str, count: int, sample: str, origin: str = "https://expectrail.tech", timeout: float = 30.0) -> dict:
    """Send ``count`` start requests at once; return the tally and every problem found."""
    url = base.rstrip("/") + "/run"
    body = json.dumps({"sample": sample}).encode("utf-8")
    answers: list[tuple[int, object]] = []
    lock = threading.Lock()
    gate = threading.Barrier(count)

    def one():
        try:
            gate.wait(timeout=timeout)
        except threading.BrokenBarrierError:
            pass
        answer = post(url, body, origin, timeout)
        with lock:
            answers.append(answer)

    threads = [threading.Thread(target=one, daemon=True) for _ in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout + 5)
    tally: Counter = Counter()
    problems: list[str] = []
    accepted: list[str] = []
    for code, doc in answers:
        if not isinstance(doc, dict):
            tally["no body"] += 1
            problems.append(f"HTTP {code}: {doc}")
            continue
        found = runit_site.api_errors(doc)
        if found:
            problems.append(f"HTTP {code}: not a body of the contract: {found[0]}")
        if doc.get("kind") == "accepted":
            tally["accepted"] += 1
            accepted.append(str(doc.get("requestId")))
        elif doc.get("kind") == "refused":
            tally[f"refused: {doc.get('reason')}"] += 1
        else:
            tally[f"other: {doc.get('kind')}"] += 1
            problems.append(f"HTTP {code}: a start answered with {doc.get('kind')!r}")
    if len(answers) < count:
        problems.append(f"{count - len(answers)} requests got no answer in time")
    if len(accepted) > 1:
        problems.append(f"{len(accepted)} runs were accepted at once: {', '.join(accepted)}")
    return {"sent": count, "tally": dict(tally), "accepted": accepted, "problems": problems}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m tools.runit_burst", description=__doc__.split("\n\n")[0])
    parser.add_argument("base", help="the service's address, e.g. http://127.0.0.1:8765/api or https://api.expectrail.tech")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--sample", default="clean")
    parser.add_argument("--origin", default="https://expectrail.tech")
    args = parser.parse_args(argv)
    if not 1 <= args.count <= 500:
        parser.error("--count is from 1 to 500")
    result = burst(args.base, args.count, args.sample, args.origin)
    print(f"sent {result['sent']} at once")
    for key, n in sorted(result["tally"].items()):
        print(f"    {key}: {n}")
    for p in result["problems"]:
        print(f"problem: {p}", file=sys.stderr)
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
