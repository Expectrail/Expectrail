"""The release gate's run of the two-job pull-request gate (#254): the candidate's capture and the
trusted judge, each in its own process, as the two workflows run them.

    python3 -m tests.release_gate.bundle capture --base B --head H --routes R [R ...] --pr JSON
                                                 --intent I --out BUNDLE.zip
    python3 -m tests.release_gate.bundle judge   --base B --routes R [R ...] --pr JSON --intent I
                                                 --bundle BUNDLE.zip --out DIR
    python3 -m tests.release_gate.bundle finish  --findings DIR/findings.json --github GITHUB.json

``capture`` is ``tools.ci_bundle.capture`` (the candidate job, ``expectrail-capture.yml``): the base's
checks and routes, every replay in the replay sandbox (``require``), written to one archive with its
manifest. ``judge`` is ``tools.ci_bundle.judge`` (the trusted job's "Evaluate the saved runs from the
base commit" step): it unpacks the archive as data, checks it against the base, and decides with both
observers. The visual observer answers from the "Run it" samples' recorded answers
(``tests.release_gate.worker.recording``) with ``every=1``, as the trusted job builds its own from
``docs/run-it/vision/clean.json``. ``judge`` prints ``{"decision", "problem"}`` and exits with the
gate's code for the decision (``expectrail.gate.verify.EXIT``: 0 is accept and nothing else is); a
bundle the judge refuses (``EVIDENCE_MISMATCH``) exits 3 with no decision.

``finish`` is ``tools.ci_checks.finish``, which completes the two head checks, against a stand-in for
GitHub's API read from ``GITHUB.json``: the pull request as it is now, the candidate workflow's runs
for its head, and the run being finished. It prints the conclusions the checks were given, by name.
Nothing here talks to GitHub.

The game is ``game/platformer`` and the checks ``agents/specs``, as in both workflows; the routes are
given, because the recorded answers cover the smoke route only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from expectrail import recorded
from expectrail.gate import verify
from tests.release_gate.common import GAME, SPECS
from tests.release_gate.worker import recording
from tools import ci_bundle, ci_checks

MISMATCH_EXIT = 3


def policy(routes: list[str]) -> ci_bundle.Policy:
    return ci_bundle.Policy(GAME, SPECS, routes)


def capture(args) -> int:
    ci_bundle.capture(policy(args.routes), args.base.resolve(), args.head.resolve(), json.loads(args.pr),
                      args.intent, args.out.resolve())
    return 0


def judge(args) -> int:
    observer = recorded.RecordedObserver(recording(), every=1)
    try:
        document = ci_bundle.judge(policy(args.routes), args.base.resolve(), json.loads(args.pr), args.intent,
                                   args.bundle.resolve(), args.out.resolve(), observer)
    except ValueError as exc:
        print(json.dumps({"decision": None, "problem": str(exc)}))
        return MISMATCH_EXIT
    print(json.dumps({"decision": document["decision"], "problem": None, "reasons": document.get("reasons")}))
    return verify.EXIT[document["decision"]]


class GitHub:
    """A stand-in for the calls ``finish`` makes. Reads are answered from the given state; check-run
    updates are recorded and are the output."""

    def __init__(self, state: dict):
        self.state = state
        self.checks: dict[str, str] = {}

    def __call__(self, method: str, path: str, body: dict | None = None):
        repo = self.state["repo"]
        if method == "GET" and path.startswith(f"/repos/{repo}/pulls?"):
            return [self.state["pullRequest"]]
        if method == "GET" and path.startswith(f"/repos/{repo}/actions/workflows/"):
            return {"workflow_runs": self.state["candidateRuns"]}
        if method == "PATCH" and path.startswith(f"/repos/{repo}/check-runs/"):
            check = int(path.rsplit("/", 1)[1])
            name = {v: k for k, v in self.state["checkIds"].items()}[check]
            self.checks[name] = body["conclusion"]
            return {}
        raise AssertionError(f"finish made a call the stand-in does not answer: {method} {path}")


def finish(args) -> int:
    state = json.loads(args.github.read_text(encoding="utf-8"))
    document = json.loads(args.findings.read_text(encoding="utf-8"))
    github = GitHub(state)
    run = state["run"]
    ctx = ci_checks.context({"workflow_run": run, "repository": {"full_name": state["repo"]}})
    pr = state["judgedPullRequest"]
    gate_state = {"pr": ci_checks.identity(pr), "intent": state["intent"], "ids": state["checkIds"]}
    ci_checks.finish(github, github, ctx, run, gate_state, document["decision"], document["decision"],
                     ctx.run_url)
    print(json.dumps(github.checks))
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="tests.release_gate.bundle")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--base", type=Path, required=True)
    c.add_argument("--head", type=Path, required=True)
    c.add_argument("--routes", nargs="+", required=True)
    c.add_argument("--pr", required=True)
    c.add_argument("--intent", default="none")
    c.add_argument("--out", type=Path, required=True)
    j = sub.add_parser("judge")
    j.add_argument("--base", type=Path, required=True)
    j.add_argument("--routes", nargs="+", required=True)
    j.add_argument("--pr", required=True)
    j.add_argument("--intent", default="none")
    j.add_argument("--bundle", type=Path, required=True)
    j.add_argument("--out", type=Path, required=True)
    f = sub.add_parser("finish")
    f.add_argument("--findings", type=Path, required=True)
    f.add_argument("--github", type=Path, required=True)
    args = p.parse_args(argv)
    return {"capture": capture, "judge": judge, "finish": finish}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
