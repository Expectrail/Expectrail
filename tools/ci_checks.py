"""Publish trusted checks on the candidate head. Incoming artifacts are data only."""
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import replace
from pathlib import Path

from expectrail.gate import comment, intent

CALLER = ".github/workflows/expectrail-verify.yml"
CAPTURE = ".github/workflows/expectrail-capture.yml"
CLEARANCE = "Expectrail clearance"
EVIDENCE = "Expectrail evidence"
REPORT = "expectrail-report"


def identity(pr):
    return {"number": pr["number"], "baseSha": pr["base"]["sha"], "headSha": pr["head"]["sha"]}


def context(event):
    run = event["workflow_run"]
    repo = event["repository"]["full_name"]
    if run["path"] != CALLER or run["event"] != "pull_request" or run["repository"]["full_name"] != repo:
        raise ValueError("unexpected candidate workflow")
    head = run["head_repository"]
    return comment.Context.from_env(dict(REPO=repo, RUN_ID=run["id"], RUN_EVENT=run["event"],
        HEAD_SHA=run["head_sha"], HEAD_REPO=head["full_name"], HEAD_OWNER=head["owner"]["login"],
        HEAD_BRANCH=run["head_branch"], WORKFLOW_PATH=CALLER, ARTIFACT_NAME=REPORT))


def check_source(api, ctx, attempt, pr, default_branch):
    named = identity(pr)
    if pr["base"]["ref"] != default_branch or not re.fullmatch("[0-9a-f]{40}", named["baseSha"]):
        raise ValueError("expected a pull request to the protected default branch")
    # Fork workflow_run events may have no pull_requests. GitHub's recorded local workflow
    # revision must still be this PR's current synthetic merge commit.
    if attempt["pull_requests"] and not any(identity(p) == named for p in attempt["pull_requests"]):
        raise ValueError("the candidate ran on a different PR or base")
    workflows = attempt.get("referenced_workflows") or []
    merge = pr.get("merge_commit_sha") or ""
    if (len(workflows) != 1 or workflows[0]["path"].split("@")[0] not in (CAPTURE, f"{ctx.repo}/{CAPTURE}")
            or not re.fullmatch("[a-f0-9]{40}", merge) or workflows[0]["sha"] != merge):
        raise ValueError("GitHub did not bind the capture workflow to the current merge commit")
    for path in (CALLER, CAPTURE):
        revisions = ((ctx.repo, named["baseSha"]), (ctx.repo, merge), (ctx.head_repo, ctx.head_sha))
        blobs = [api("GET", f"/repos/{repo}/contents/{path}?ref={ref}") for repo, ref in revisions]
        if any(b["type"] != "file" for b in blobs) or len({b["sha"] for b in blobs}) != 1:
            raise ValueError("candidate workflow differs from the trusted base")
    return named


def latest(api, ctx, run):
    listing = api("GET", f"/repos/{ctx.repo}/actions/workflows/{int(run['workflow_id'])}/runs"
                  f"?event=pull_request&head_sha={ctx.head_sha}&per_page=100")
    revisions = [(r["id"], r["run_attempt"]) for r in listing["workflow_runs"]]
    return bool(revisions) and max(revisions) == (run["id"], run["run_attempt"])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def download(api, ctx, run, archive, token):
    from tools.ci_bundle import MAX_BYTES
    name = f"expectrail-{int(run['run_attempt'])}.zip"
    listing = api("GET", f"/repos/{ctx.repo}/actions/runs/{int(ctx.run_id)}/artifacts?name={name}")
    matches = [a for a in listing["artifacts"] if a["name"] == name and not a["expired"]]
    if len(matches) != 1:
        raise ValueError("EVIDENCE_MISMATCH: expected one artifact from this attempt")
    item, = matches
    if (not 0 < item["size_in_bytes"] <= MAX_BYTES
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", item.get("digest") or "")):
        raise ValueError("EVIDENCE_MISMATCH: invalid GitHub artifact size or digest")
    url = f"https://api.github.com/repos/{ctx.repo}/actions/artifacts/{int(item['id'])}/zip"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30):
            raise ValueError("EVIDENCE_MISMATCH: expected a GitHub download redirect")
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location", "")
        if exc.code != 302 or not location.startswith("https://"):
            raise ValueError("EVIDENCE_MISMATCH: capture download unavailable") from None
    # Send only the signed URL to storage. Never forward the repository token there.
    digest, size = hashlib.sha256(), 0
    with urllib.request.urlopen(location, timeout=30) as response, archive.open("xb") as out:
        while chunk := response.read(256 * 1024):
            size += len(chunk)
            if size > item["size_in_bytes"]:
                raise ValueError("EVIDENCE_MISMATCH: download exceeds GitHub's artifact size")
            digest.update(chunk)
            out.write(chunk)
    if size != item["size_in_bytes"] or "sha256:" + digest.hexdigest() != item["digest"]:
        raise ValueError("EVIDENCE_MISMATCH: download differs from GitHub's artifact")


def start(api, ctx, run, details, publisher):
    key = f"expectrail/{ctx.run_id}/{run['run_attempt']}"
    ids = {}
    for name in (CLEARANCE, EVIDENCE):
        query = urllib.parse.urlencode({"check_name": name, "filter": "all", "per_page": 100})
        found = api("GET", f"/repos/{ctx.repo}/commits/{ctx.head_sha}/check-runs?{query}")
        existing = [c for c in found["check_runs"] if c["external_id"] == key and c["app"]["slug"] == publisher]
        if existing:
            ids[name] = existing[0]["id"]
            continue
        body = dict(name=name, head_sha=ctx.head_sha, external_id=key, details_url=details, status="in_progress")
        if name == EVIDENCE:
            body.update(status="completed", conclusion="neutral",
                        output={"title": "Awaiting capture", "summary": "Open Details for the run."})
        ids[name] = api("POST", f"/repos/{ctx.repo}/check-runs", body)["id"]
    return ids


def current(api, ctx, run, state):
    pr = comment.find_pull_request(api, ctx)
    return (pr and identity(pr) == state["pr"] and intent.of_pull_request(pr).intent == state["intent"]
            and latest(api, ctx, run))


def finish(api, publisher, ctx, run, state, decision, summary, details):
    if not current(api, ctx, run, state):
        decision, summary = "needs-review", "Superseded capture or pull request"
    cleared = decision == "accept" and run["conclusion"] == "success"
    for name, conclusion in ((EVIDENCE, "success"), (CLEARANCE, "success" if cleared else "failure")):
        publisher("PATCH", f"/repos/{ctx.repo}/check-runs/{int(state['ids'][name])}",
                  dict(status="completed", conclusion=conclusion, details_url=details,
                       output={"title": name, "summary": comment.md(summary, 450)}))


def report_problem(report, problem, ctx):
    report.mkdir()
    (report / "report.md").write_text(comment.render_unreadable(problem, ctx))


def main(mode):
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())
    ctx = context(event)
    run = event["workflow_run"]
    report_ctx = replace(ctx, run_id=os.environ["GITHUB_RUN_ID"], trusted_report=True)
    temp = Path(os.environ["RUNNER_TEMP"])
    report, state_file = temp / REPORT, temp / "gate-state.json"
    api = comment.http_api(os.environ.get("GH_TOKEN", ""))
    if mode == "start":
        pr = comment.find_pull_request(api, ctx)
        if not pr or not latest(api, ctx, run):
            return
        ids = start(comment.http_api(os.environ["CHECKS_TOKEN"]), ctx, run, report_ctx.run_url, os.environ["CHECKS_APP"])
        if event["action"] != "completed":
            return
        state = {"pr": identity(pr), "intent": intent.of_pull_request(pr).intent, "ids": ids}
        base = None
        try:
            if run["conclusion"] != "success":
                raise ValueError(f"candidate job ended {run['conclusion']}")
            attempt = api("GET", f"/repos/{ctx.repo}/actions/runs/{int(ctx.run_id)}/attempts/{int(run['run_attempt'])}")
            check_source(api, ctx, attempt, pr, event["repository"]["default_branch"])
            base = state["pr"]["baseSha"]
        except (LookupError, OSError, ValueError) as exc:
            reason = str(exc)[:350]
            (temp / "problem.txt").write_text(reason)
            report_problem(report, reason, report_ctx)
        state_file.write_text(json.dumps(state))
        with open(os.environ["GITHUB_OUTPUT"], "a") as outputs:
            print("matched=true", file=outputs)
            if base:
                print("base=" + base, file=outputs)
        return
    if not state_file.exists():
        return
    state = json.loads(state_file.read_bytes())
    if mode == "download":
        download(api, ctx, run, temp / "capture.zip", os.environ["GH_TOKEN"])
    elif mode == "judge":
        import tempfile
        from agents import export_scan
        from expectrail.recorded import RecordedObserver, read_recording
        from tools import ci_bundle
        recording = Path(os.environ["RECORDING"])
        visual = RecordedObserver(read_recording(recording), every=1) if recording.is_file() else None
        with tempfile.TemporaryDirectory(dir=temp) as tmp:
            staged = Path(tmp) / "result"
            ci_bundle.judge(ci_bundle.Policy.configured(), Path.cwd(), state["pr"], state["intent"],
                            temp / "capture.zip", staged, visual)
            if any(row["level"] == "error" for row in export_scan.scan([staged])):
                raise ValueError("report failed the public export scan")
            staged.rename(report)
    elif mode == "finish":
        decision = "needs-review"
        problem = temp / "problem.txt"
        summary = problem.read_text() if problem.is_file() else "Trusted judgment or report upload did not finish"
        if current(api, ctx, run, state):
            if os.environ.get("REPORT_READY") == "true":
                result = comment.run(api, report_ctx, report)
                decision = result.get("decision", decision)
                summary = result.get("problem") or decision
            else:
                comment.run(api, report_ctx, None, problem_message=summary)
        finish(api, comment.http_api(os.environ["CHECKS_TOKEN"]), ctx, run, state, decision, summary,
               os.environ.get("REPORT_URL") or report_ctx.run_url)


if __name__ == "__main__":
    import sys
    try:
        main(sys.argv[1])
    except Exception as exc:
        if sys.argv[1] in ("download", "judge"):
            reason = str(exc) if isinstance(exc, ValueError) else "EVIDENCE_MISMATCH: saved capture unavailable"
            temp = Path(os.environ["RUNNER_TEMP"])
            (temp / "problem.txt").write_text(reason[:350])
            event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())
            report_problem(temp / REPORT, reason[:350], replace(context(event), run_id=os.environ["GITHUB_RUN_ID"]))
            sys.exit("Saved evidence could not be judged. See the head checks.")
        raise
