"""Say so when main is red: open an issue on the first failing CI run on main, comment while it
stays red, and close the issue when CI on main passes again.

    python3 -m agents.main_health --run-id 123            # the Main health workflow passes the run that finished
    python3 -m agents.main_health --run-id 123 --dry-run  # say what it would do, write nothing

Only the CI workflow's runs on main count (pushes, the daily schedule and dispatches), never a pull
request's. Some CI jobs (the private routes) run only on main, so main is where they fail first.

A run that a newer finished run on main supersedes changes nothing, so runs that finish out of order
cannot open or close the issue wrongly. The issue is assigned to the repository's owner, so opening
it notifies them, and the pull request that merged the failing commit gets a comment linking it.

Standard library only: the job that runs this holds a token that can write issues, and installs
nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Callable

TITLE = "Main is red"
BOT = "github-actions[bot]"
CI_PATH = ".github/workflows/ci.yml"
RED = frozenset({"failure", "timed_out", "startup_failure"})
GREEN = frozenset({"success"})

Api = Callable[..., object]


def http_api(token: str, base: str = "https://api.github.com") -> Api:
    def call(method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(base + path, data=data, method=method, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "expectrail-main-health"})
        if data is not None:
            request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8")
        return json.loads(text) if text else None
    return call


def counts(run: dict) -> bool:
    """A CI run on main that is not a pull request's (a fork's branch can also be named main)."""
    return (run.get("path") == CI_PATH and run.get("head_branch") == "main"
            and run.get("event") != "pull_request")


def superseded(run: dict, runs: list[dict]) -> bool:
    """A newer CI run on main has finished green or red, so this run says nothing about main now."""
    return any(r.get("id") != run.get("id") and counts(r) and r.get("created_at", "") > run.get("created_at", "")
               and r.get("status") == "completed" and r.get("conclusion") in RED | GREEN for r in runs)


def decide(run: dict, runs: list[dict], issue: dict | None) -> str:
    """open, comment, close, or nothing to do: ignore (not main's CI), superseded, none."""
    if not counts(run):
        return "ignore"
    if superseded(run, runs):
        return "superseded"
    conclusion = run.get("conclusion")
    if conclusion in GREEN:
        return "close" if issue else "none"
    if conclusion in RED:
        return "comment" if issue else "open"
    return "none"  # cancelled, skipped, neutral, still running: no news about main


def find_issue(api: Api, repo: str) -> dict | None:
    """The open main-is-red issue this workflow opened; never one a person wrote."""
    for item in api("GET", f"/repos/{repo}/issues?state=open&per_page=100") or []:
        if ("pull_request" not in item and item.get("title", "").startswith(TITLE)
                and (item.get("user") or {}).get("login") == BOT):
            return item
    return None


def failed_jobs(api: Api, repo: str, run_id: int) -> list[tuple[str, str]]:
    jobs = (api("GET", f"/repos/{repo}/actions/runs/{run_id}/jobs?per_page=100") or {}).get("jobs", [])
    return [(j["name"], j["html_url"]) for j in jobs if j.get("conclusion") in RED]


def _where(run: dict) -> str:
    return f"`{run['head_sha'][:7]}` ({run['event']}): [run {run['id']}]({run['html_url']})"


def _job_lines(jobs: list[tuple[str, str]]) -> str:
    return "\n".join(f"- [{name}]({url})" for name, url in jobs) or "- none reported as failed (see the run)"


def open_body(run: dict, jobs: list[tuple[str, str]]) -> str:
    message = ((run.get("head_commit") or {}).get("message") or "").splitlines()
    commit = f"\nCommit: {message[0]}\n" if message else ""
    return (f"CI failed on main at {_where(run)}.\n{commit}\nFailed jobs:\n{_job_lines(jobs)}\n\n"
            "Some jobs (the private routes) run only on main, so main is where they fail first. Fix it "
            "on a branch and merge; this issue closes itself when CI on main passes again.\n")


def run_check(api: Api, repo: str, run_id: int, owner: str, *, dry_run: bool = False,
              out: Callable[[str], None] = print) -> str:
    run = api("GET", f"/repos/{repo}/actions/runs/{run_id}")
    runs = (api("GET", f"/repos/{repo}/actions/workflows/ci.yml/runs?branch=main&per_page=30") or {}).get(
        "workflow_runs", [])
    issue = find_issue(api, repo)
    action = decide(run, runs, issue)
    issue_note = f"; open issue #{issue['number']}" if issue else ""
    out(f"::notice title=Main health::run {run_id} {run.get('conclusion')} at {run['head_sha'][:7]}: "
        f"{action}{issue_note}{' (dry run)' if dry_run else ''}")
    if dry_run or action in ("ignore", "superseded", "none"):
        return action
    sha = run["head_sha"][:7]
    if action == "open":
        jobs = failed_jobs(api, repo, run_id)
        issue_doc = {"title": f"{TITLE}: CI failed at {sha}", "body": open_body(run, jobs), "assignees": [owner]}
        try:
            new = api("POST", f"/repos/{repo}/issues", issue_doc)
        except urllib.error.HTTPError as exc:
            # GitHub refuses an assignee it cannot assign (422), such as an organisation: since the move
            # to the Expectrail org, the repository's owner is one. Saying main is red matters more
            # than who it is assigned to, so open it unassigned and say why.
            if exc.code != 422:
                raise
            out(f"::warning title=Main health::could not assign the issue to {owner!r} (422); opening it "
                "unassigned. Set the repository variable MAIN_HEALTH_ASSIGNEE to a person's login.")
            new = api("POST", f"/repos/{repo}/issues", {k: v for k, v in issue_doc.items() if k != "assignees"})
        out(f"::warning title=Main is red::opened issue #{new['number']}")
        try:
            pulls = api("GET", f"/repos/{repo}/commits/{run['head_sha']}/pulls") or []
        except urllib.error.HTTPError as exc:
            pulls = []
            out(f"::warning title=Main health::could not list the merged pull request ({exc.code})")
        for pull in pulls:
            if not pull.get("merged_at"):
                continue
            try:
                api("POST", f"/repos/{repo}/issues/{pull['number']}/comments",
                    {"body": f"CI on main failed after this merge: #{new['number']}."})
            except urllib.error.HTTPError as exc:
                out(f"::warning title=Main health::could not comment on #{pull['number']} ({exc.code})")
    elif action == "comment":
        jobs = failed_jobs(api, repo, run_id)
        api("POST", f"/repos/{repo}/issues/{issue['number']}/comments",
            {"body": f"Still red at {_where(run)}.\n\nFailed jobs:\n{_job_lines(jobs)}\n"})
    elif action == "close":
        api("POST", f"/repos/{repo}/issues/{issue['number']}/comments",
            {"body": f"Green again at {_where(run)}. Closing."})
        api("PATCH", f"/repos/{repo}/issues/{issue['number']}", {"state": "closed", "state_reason": "completed"})
    return action


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run-id", type=int, required=True)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo, owner = os.environ.get("REPO") or os.environ.get("GITHUB_REPOSITORY"), os.environ.get("OWNER")
    if not (token and repo and owner):
        print("::error title=Main health::GH_TOKEN, REPO and OWNER must be set")
        return 2
    api = http_api(token, os.environ.get("GITHUB_API_URL") or "https://api.github.com")
    run_check(api, repo, args.run_id, owner, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
