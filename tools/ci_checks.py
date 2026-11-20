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


def download(api, ctx, run, archive, token, *, artifact_name=None, max_bytes=None):
    from tools.ci_bundle import MAX_BYTES
    name = artifact_name or f"expectrail-{int(run['run_attempt'])}.zip"
    bound = MAX_BYTES if max_bytes is None else min(MAX_BYTES, max_bytes)
    listing = api("GET", f"/repos/{ctx.repo}/actions/runs/{int(ctx.run_id)}/artifacts?name={name}")
    matches = [a for a in listing["artifacts"] if a["name"] == name and not a["expired"]]
    if len(matches) != 1:
        raise ValueError("EVIDENCE_MISMATCH: expected one artifact from this attempt")
    item, = matches
    if (not 0 < item["size_in_bytes"] <= bound
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
    key = key_of(ctx, run)
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


SUPERSEDED = "Superseded capture or pull request"
STALE = (SUPERSEDED + ": this commit is no longer the head of the open pull request, or a newer capture "
         "ran. This commit is not cleared; the current head needs its own clearance.")


def close_stale(publisher_api, ctx, run, publisher):
    """Conclude this attempt's checks that were started but never finished, because the pull request
    moved on before the capture completed. Clearance ends failed, evidence neutral: nothing was judged."""
    key = f"expectrail/{ctx.run_id}/{run['run_attempt']}"
    for name, conclusion in ((CLEARANCE, "failure"), (EVIDENCE, "neutral")):
        query = urllib.parse.urlencode({"check_name": name, "filter": "all", "per_page": 100})
        found = publisher_api("GET", f"/repos/{ctx.repo}/commits/{ctx.head_sha}/check-runs?{query}")
        for check in found["check_runs"]:
            if check["external_id"] == key and check["app"]["slug"] == publisher and check["status"] != "completed":
                publisher_api("PATCH", f"/repos/{ctx.repo}/check-runs/{int(check['id'])}",
                              dict(status="completed", conclusion=conclusion,
                                   output={"title": name, "summary": STALE}))


STARTED = "gate-started.json"
UNFINISHED = ("The trusted job stopped before it judged this capture. This commit is not cleared; "
              "re-run the Expectrail verify workflow for a clearance.")


def key_of(ctx, run):
    return f"expectrail/{ctx.run_id}/{run['run_attempt']}"


def close_unfinished(publisher_api, ctx, run, started, publisher=None):
    """Conclude this attempt's checks that are still open when the trusted job ends without a judging
    state (its start step crashed after creating them). Clearance ends failed, evidence neutral.

    The ids ``start`` recorded are used first. A check with no recorded id (start crashed between
    creating the two) is found by its external id, as ``close_stale`` does; without the publisher's
    name, a check another app owns is left alone, because GitHub refuses the update."""
    key = key_of(ctx, run)
    ids = started.get("ids", {}) if isinstance(started, dict) and started.get("key") == key else {}
    for name, conclusion in ((CLEARANCE, "failure"), (EVIDENCE, "neutral")):
        if isinstance(ids.get(name), int):
            checks = [publisher_api("GET", f"/repos/{ctx.repo}/check-runs/{int(ids[name])}")]
        else:
            query = urllib.parse.urlencode({"check_name": name, "filter": "all", "per_page": 100})
            checks = publisher_api("GET", f"/repos/{ctx.repo}/commits/{ctx.head_sha}/check-runs?{query}")["check_runs"]
        for check in checks:
            if check.get("external_id") != key or check.get("status") == "completed":
                continue
            if publisher and (check.get("app") or {}).get("slug") != publisher:
                continue
            try:
                publisher_api("PATCH", f"/repos/{ctx.repo}/check-runs/{int(check['id'])}",
                              dict(status="completed", conclusion=conclusion,
                                   output={"title": name, "summary": UNFINISHED}))
            except urllib.error.HTTPError as exc:
                if publisher or exc.code not in (403, 404):
                    raise


KEY = re.compile(r"expectrail/([0-9]+)/([0-9]+)")


def close_superseded(publisher_api, ctx, run, publisher):
    """Conclude this publisher's open checks on this head from earlier captures (a lower run id, or the
    same run's earlier attempt). Call it only for the latest capture of the head.

    An earlier capture can never clear: ``finish`` refuses any capture that is not the latest, so this
    concludes only what would otherwise stay ``in_progress`` for ever when its trusted job's runner was
    lost (#254). Clearance ends failed, evidence neutral. A check whose key cannot be read, another
    app's check, and a completed check are left alone. Returns the ids GitHub refused to update."""
    mine = (int(ctx.run_id), int(run["run_attempt"]))
    newer = key_of(ctx, run)
    summary = (f"{SUPERSEDED}: a newer capture of this commit ran ({newer}), and the trusted job for this "
               "earlier one never concluded its checks. This commit is not cleared by it.")
    refused = []
    for name, conclusion in ((CLEARANCE, "failure"), (EVIDENCE, "neutral")):
        query = urllib.parse.urlencode({"check_name": name, "filter": "all", "per_page": 100})
        found = publisher_api("GET", f"/repos/{ctx.repo}/commits/{ctx.head_sha}/check-runs?{query}")
        for check in found["check_runs"]:
            match = KEY.fullmatch(check.get("external_id") or "")
            if (not match or check.get("status") == "completed"
                    or (check.get("app") or {}).get("slug") != publisher
                    or (int(match[1]), int(match[2])) >= mine):
                continue
            try:
                publisher_api("PATCH", f"/repos/{ctx.repo}/check-runs/{int(check['id'])}",
                              dict(status="completed", conclusion=conclusion,
                                   output={"title": name, "summary": summary}))
            except urllib.error.URLError:
                refused.append(check["id"])
    return refused


EARLIER_HEADS = 20  # the newest commits of the pull request looked at, besides its head
OPEN_PULL_PAGES = 10  # up to 1,000 open pull requests; more and the sweep cannot tell, so it skips


def open_heads(api, ctx):
    """The head commits of every open pull request in the repository. Raises ValueError when the list
    cannot be read in full: a commit that heads another open pull request must never be swept."""
    heads = set()
    for page in range(1, OPEN_PULL_PAGES + 1):
        items = api("GET", f"/repos/{ctx.repo}/pulls?state=open&per_page=100&page={page}")
        if not isinstance(items, list):
            raise ValueError("cannot tell: the open pull requests could not be read")
        for item in items:
            sha = (item.get("head") or {}).get("sha") if isinstance(item, dict) else None
            if not isinstance(sha, str) or not re.fullmatch("[0-9a-f]{40}", sha):
                raise ValueError("cannot tell: an open pull request has no readable head")
            heads.add(sha)
        if len(items) < 100:
            return heads
    raise ValueError("cannot tell: more open pull requests than the sweep reads")


def close_earlier_heads(api, publisher_api, ctx, pr, publisher, limit=EARLIER_HEADS):
    """Conclude this publisher's open checks on the pull request's earlier commits, which a lost runner
    left ``in_progress`` after the head moved on (#254). Call it only for the latest capture of the
    current head.

    An earlier head can never clear: ``finish`` judges only the current head of the open pull request.
    A commit that is the head of any open pull request (this one's, or a stacked branch's) is never
    touched, and if the open pull requests cannot be read in full nothing is swept (ValueError). A head
    that was force-pushed away is no longer among the pull request's commits and is not reached.
    Clearance ends failed, evidence neutral. Returns the ids GitHub refused to update."""
    commits = []
    for page in range(1, 4):  # GitHub lists at most 250 commits of a pull request
        items = api("GET", f"/repos/{ctx.repo}/pulls/{int(pr['number'])}/commits?per_page=100&page={page}")
        if not isinstance(items, list):
            raise ValueError("cannot tell: the pull request's commits could not be read")
        commits += [c.get("sha") for c in items if isinstance(c, dict)]
        if len(items) < 100:
            break
    # Read after the commits, so a head pushed meanwhile is among the excluded ones.
    excluded = open_heads(api, ctx) | {ctx.head_sha}
    earlier = [s for s in commits if isinstance(s, str) and re.fullmatch("[0-9a-f]{40}", s) and s not in excluded]
    earlier = list(dict.fromkeys(reversed(earlier)))[:limit]  # newest first
    summary = (f"{SUPERSEDED}: the pull request's head moved on to {ctx.head_sha[:12]}, and the trusted job "
               "for this commit never concluded its checks. This commit is not cleared.")
    refused = []
    for sha in earlier:
        for name, conclusion in ((CLEARANCE, "failure"), (EVIDENCE, "neutral")):
            query = urllib.parse.urlencode({"check_name": name, "filter": "all", "per_page": 100})
            found = publisher_api("GET", f"/repos/{ctx.repo}/commits/{sha}/check-runs?{query}")
            for check in found["check_runs"]:
                if (not KEY.fullmatch(check.get("external_id") or "") or check.get("status") == "completed"
                        or check.get("name", name) != name
                        or (check.get("app") or {}).get("slug") != publisher):
                    continue
                try:
                    publisher_api("PATCH", f"/repos/{ctx.repo}/check-runs/{int(check['id'])}",
                                  dict(status="completed", conclusion=conclusion,
                                       output={"title": name, "summary": summary}))
                except urllib.error.URLError:
                    refused.append(check["id"])
    return refused


def current(api, ctx, run, state):
    pr = comment.find_pull_request(api, ctx)
    return (pr and intent.pull_request_metadata(pr) == state["pr"] and intent.of_pull_request(pr).intent == state["intent"]
            and latest(api, ctx, run))


def finish(api, publisher, ctx, run, state, decision, summary, details):
    if not current(api, ctx, run, state):
        decision, summary = "needs-review", SUPERSEDED
    cleared = decision == "accept" and run["conclusion"] == "success"
    for name, conclusion in ((EVIDENCE, "success"), (CLEARANCE, "success" if cleared else "failure")):
        publisher("PATCH", f"/repos/{ctx.repo}/check-runs/{int(state['ids'][name])}",
                  dict(status="completed", conclusion=conclusion, details_url=details,
                       output={"title": name, "summary": comment.md(summary, 450)}))


def report_problem(report, problem, ctx):
    report.mkdir()
    (report / "report.md").write_text(comment.render_unreadable(problem, ctx))


def recorded_observer(path):
    """The base checkout's recording bank, with its configured primary first; no model fallback."""
    from expectrail.recorded import RecordedBankObserver, read_recording, RecordingError

    path = Path(path)
    paths = [path, *sorted(p for p in path.parent.glob("*.json") if p != path)]
    docs = []
    for source in paths:
        if source.exists() or source.is_symlink():
            doc = read_recording(source)
            if source.stem != doc["sample"]:
                raise RecordingError(f"{source.name} is not a {source.stem} recording")
            docs.append(doc)
    return RecordedBankObserver(docs, every=1) if docs else None


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
            if event["action"] == "completed":
                # The trusted job never judges a superseded capture, but it must not leave the
                # clearance it started on the in_progress event dangling (#254's hosted trial).
                close_stale(comment.http_api(os.environ["CHECKS_TOKEN"]), ctx, run, os.environ["CHECKS_APP"])
            return
        ids = start(comment.http_api(os.environ["CHECKS_TOKEN"]), ctx, run, report_ctx.run_url, os.environ["CHECKS_APP"])
        # Before anything else can fail: finish concludes these if no judging state follows.
        (temp / STARTED).write_text(json.dumps({"key": key_of(ctx, run), "ids": ids}))
        # Housekeeping only: a lost runner's earlier attempts. It never decides anything about this one.
        try:
            refused = close_superseded(comment.http_api(os.environ["CHECKS_TOKEN"]), ctx, run,
                                       os.environ["CHECKS_APP"])
            if refused:
                print(f"::warning::Could not conclude superseded checks {refused}; they stay in progress "
                      "and are not cleared.")
        except (OSError, LookupError, TypeError, ValueError) as exc:
            print(f"::warning::Could not look for superseded checks ({type(exc).__name__}); "
                  "any stay in progress and are not cleared.")
        # The same for the pull request's earlier heads. A failure only warns; it fails closed.
        try:
            refused = close_earlier_heads(api, comment.http_api(os.environ["CHECKS_TOKEN"]), ctx, pr,
                                          os.environ["CHECKS_APP"])
            if refused:
                print(f"::warning::Could not conclude checks on earlier heads {refused}; they stay in "
                      "progress and are not cleared.")
        except (OSError, LookupError, TypeError, ValueError) as exc:
            print(f"::warning::Could not sweep earlier heads ({type(exc).__name__}: {str(exc)[:120]}); "
                  "any open checks there stay in progress and are not cleared.")
        if event["action"] != "completed":
            return
        state = {"pr": intent.pull_request_metadata(pr), "intent": intent.of_pull_request(pr).intent, "ids": ids}
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
        if mode == "finish" and event["action"] == "completed" and os.environ.get("CHECKS_TOKEN"):
            started = temp / STARTED
            close_unfinished(comment.http_api(os.environ["CHECKS_TOKEN"]), ctx, run,
                             json.loads(started.read_bytes()) if started.is_file() else {},
                             os.environ.get("CHECKS_APP") or None)
        return
    state = json.loads(state_file.read_bytes())
    if mode == "download":
        download(api, ctx, run, temp / "capture.zip", os.environ["GH_TOKEN"])
    elif mode == "judge":
        import tempfile
        from agents import export_scan
        from tools import ci_bundle
        recording = Path(os.environ["RECORDING"])
        visual = recorded_observer(recording)
        with tempfile.TemporaryDirectory(dir=temp) as tmp:
            staged = Path(tmp) / "result"
            ci_bundle.judge(ci_bundle.Policy.configured(), Path.cwd(), state["pr"], state["intent"],
                            temp / "capture.zip", staged, visual, head_checkout=Path(os.environ["HEAD_CHECKOUT"]))
            if any(row["level"] == "error" for row in export_scan.scan([staged])):
                raise ValueError("report failed the public export scan")
            staged.rename(report)
    elif mode == "finish":
        decision = "needs-review"
        problem = temp / "problem.txt"
        summary = problem.read_text() if problem.is_file() else "Trusted judgment or report upload did not finish"
        failed = None
        try:
            if current(api, ctx, run, state):
                if os.environ.get("REPORT_READY") == "true":
                    result = comment.run(api, report_ctx, report)
                    decision = result.get("decision", decision)
                    summary = result.get("problem") or decision
                else:
                    comment.run(api, report_ctx, None, problem_message=summary)
        except Exception as exc:  # the checks are concluded first, then the error is raised
            failed, decision = exc, "needs-review"
            summary = f"The pull request comment could not be posted ({type(exc).__name__}). Not cleared."
        finish(api, comment.http_api(os.environ["CHECKS_TOKEN"]), ctx, run, state, decision, summary,
               os.environ.get("REPORT_URL") or report_ctx.run_url)
        if failed is not None:
            raise failed


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
