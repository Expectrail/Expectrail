"""The private scan's report: post the result as a check on the commit that was scanned.

    python3 -I agents/scan_handoff.py report --repo OWNER/NAME --ref SHA --status success --run-url URL

`private-scan.yml` runs on main when a pull request asks for it (`private-scan-request.yml` starts
it by workflow_dispatch with the pull request's head commit). It checks that commit out as data,
scans it with main's scanner, and calls this to post the result as the check `private-export-scan`
on the commit. The check says passed or failed and links to the run; it never carries what the scan
found.

A check is posted only when the ref is a full commit id. A run a person starts for a branch name
has nowhere to post and says so. Only a clean success is reported as a pass.

Standard library only, so the workflow runs it in Python's isolated mode.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request

CHECK_NAME = "private-export-scan"
_SHA = re.compile(r"[0-9a-f]{40}")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_CONCLUSIONS = {"success": "success", "failure": "failure", "cancelled": "cancelled"}


class HandoffError(Exception):
    """The report cannot be posted as asked."""


def is_commit(ref: str) -> bool:
    return bool(_SHA.fullmatch(ref))


def _check_ids(repo: str, sha: str) -> None:
    if not _REPO.fullmatch(repo):
        raise HandoffError("not a repository name")
    if not is_commit(sha):
        raise HandoffError("not a full commit id")


def _call(url: str, token: str, body: dict | None = None, opener=None) -> dict:
    opener = opener or urllib.request.urlopen   # looked up at call time, so a test can stand in for it
    request = urllib.request.Request(
        url, data=None if body is None else json.dumps(body).encode(), method="GET" if body is None else "POST",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "expectrail-private-scan"})
    with opener(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _api() -> str:
    return os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")


def check_run(sha: str, status: str, run_url: str) -> dict:
    """The check posted on the scanned commit. Anything but a clean success is not a pass."""
    conclusion = _CONCLUSIONS.get(status, "failure")
    passed = conclusion == "success"
    return {
        "name": CHECK_NAME, "head_sha": sha, "status": "completed", "conclusion": conclusion,
        "details_url": run_url,
        "output": {
            "title": "Nothing from the private set, and no key, in this commit's files" if passed
            else "The private scan did not pass",
            "summary": (f"Main's scanner read this commit's `bench`, `docs`, `apps` and `README.md` as data "
                        f"and compared them with the private set. Result: {conclusion}. "
                        f"File names and counts are in the run's log: {run_url}"),
        },
    }


def post_check(repo: str, sha: str, status: str, run_url: str, token: str, opener=None) -> dict:
    _check_ids(repo, sha)
    return _call(f"{_api()}/repos/{repo}/check-runs", token, check_run(sha, status, run_url), opener=opener)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("report", help="post the result as a check run on the scanned commit")
    r.add_argument("--repo", required=True)
    r.add_argument("--ref", required=True, help="what was scanned; a check is posted only for a full commit id")
    r.add_argument("--status", required=True, help="the job's status: success, failure or cancelled")
    r.add_argument("--run-url", required=True)
    args = p.parse_args(argv)
    if not is_commit(args.ref):
        print("::notice title=Private scan::the scanned ref is not a full commit id, so no check is posted")
        return 0
    try:
        post_check(args.repo, args.ref, args.status, args.run_url, os.environ.get("GH_TOKEN", ""))
        print(f"::notice title=Private scan::reported {args.status} on {args.ref}")
    except HandoffError as error:
        print(f"::error title=Private scan::{error}")
        return 1
    except OSError as error:  # the API refused or could not be reached; never print a response body
        print(f"::error title=Private scan::GitHub's API call failed ({type(error).__name__})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
