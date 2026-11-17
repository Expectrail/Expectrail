"""Gate fixture repair on a published clearance for the labeled pull request."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request

from expectrail import contracts, repair
from expectrail.gate import intent, record, verify
from expectrail.orchestrator import request, runner, store
from tools import ci_checks
from tools.ci_bundle import Policy


def published_reject(event, app_id, public, permission):
    """All remote reads precede checkout or execution of candidate code."""
    pr = event["pull_request"]
    repo = event["repository"]["full_name"]
    root = f"/repos/{repo}"
    if (event["action"] != "labeled" or event["label"]["name"] != "expectrail-autofix"
            or pr["base"]["ref"] != event["repository"]["default_branch"]):
        raise ValueError("expected the auto-fix label on a pull request to the default branch")
    actor = urllib.parse.quote(event["sender"]["login"], safe="")
    if permission(f"{root}/collaborators/{actor}/permission")["permission"] not in ("admin", "maintain", "write"):
        raise ValueError("the person adding the label needs repository write access")
    current = public(f"{root}/pulls/{int(pr['number'])}")
    if (current["state"] != "open" or ci_checks.identity(current) != ci_checks.identity(pr)
            or current["head"]["repo"]["full_name"] != pr["head"]["repo"]["full_name"]
            or intent.of_pull_request(current).intent != intent.of_pull_request(pr).intent
            or not any(label["name"] == "expectrail-autofix" for label in current["labels"])):
        raise ValueError("the labeled pull request changed")
    head = pr["head"]["sha"]
    query = urllib.parse.urlencode({"check_name": ci_checks.CLEARANCE, "app_id": app_id,
                                    "filter": "all", "per_page": 100})
    listing = public(f"{root}/commits/{head}/check-runs?{query}")
    checks = listing["check_runs"]
    if not checks or len(checks) != listing["total_count"]:
        raise ValueError("no unambiguous clearance history on this head")
    attempts = {}
    for check in checks:
        match = re.fullmatch(r"expectrail/([1-9][0-9]*)/([1-9][0-9]*)", check.get("external_id") or "")
        if (not match or check["app"]["id"] != app_id or check["head_sha"] != head
                or check["name"] != ci_checks.CLEARANCE):
            raise ValueError("unexpected clearance publisher, head or capture identity")
        key = tuple(map(int, match.groups()))
        if key in attempts:
            raise ValueError("duplicate clearance for a capture attempt")
        attempts[key] = check
    run_id, attempt = max(attempts)
    check = attempts[run_id, attempt]
    if (check["status"] != "completed" or check["conclusion"] != "failure"
            or (check.get("output") or {}).get("summary") != "reject"):
        raise ValueError("the latest clearance on this head has no published reject")
    run = public(f"{root}/actions/runs/{run_id}/attempts/{attempt}")
    if (run["id"] != run_id or run["run_attempt"] != attempt or run["head_sha"] != head
            or run["path"] != ci_checks.CALLER or run["event"] != "pull_request"
            or run["head_repository"]["full_name"] != pr["head"]["repo"]["full_name"]
            or run["head_branch"] != pr["head"]["ref"] or run["conclusion"] != "success"):
        raise ValueError("clearance belongs to a different capture")
    if run["pull_requests"]:
        if not any(ci_checks.identity(p) == ci_checks.identity(pr) for p in run["pull_requests"]):
            raise ValueError("clearance belongs to a different pull request or base")
    else:
        # Fork captures may have no attached PR. Match the capture's merge revision, as the judge does.
        refs = run.get("referenced_workflows") or []
        merge = current.get("merge_commit_sha") or ""
        if (not re.fullmatch("[a-f0-9]{40}", merge) or len(refs) != 1 or refs[0]["sha"] != merge
                or refs[0]["path"].split("@")[0] not in (ci_checks.CAPTURE, f"{repo}/{ci_checks.CAPTURE}")):
            raise ValueError("capture cannot be tied to this pull request and base")
    return head


def authorize():
    if os.environ["GITHUB_EVENT_NAME"] != "pull_request":
        raise ValueError("expected a pull request")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())
    def get(path, token=None):
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request("https://api.github.com" + path, headers=headers)
        with urllib.request.build_opener(ci_checks.NoRedirect).open(req, timeout=30) as response:
            return json.load(response)
    head = published_reject(event, int(os.environ["CHECKS_APP_ID"]), get,
                            lambda path: get(path, os.environ["PERMISSION_TOKEN"]))
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as out:
        print("head=" + head, "decision=reject", "intent=" + intent.of_pull_request(event["pull_request"]).intent,
              sep="\n", file=out)


def publish(path, out, summary, game, parent):
    doc = contracts.load_strict(path, "repair-run")
    result = doc["result"]
    lines = ["## Expectrail auto-fix", "", "Original verdict: reject",
             f"Repair outcome: {result['decision']}", f"Stop reason: {doc['stop']['reason']}", "",
             "Artifact record: `repair-run.json`."]
    if doc["parent"]["job"] != parent:
        raise ValueError("repair record names a different parent")
    out.mkdir()
    if result["decision"] == "accept":
        attempt = doc["attempts"][-1]
        patch = f"attempt-{attempt['n']}/candidate.patch"
        if (doc["stop"]["reason"] != "accepted" or result["patch"] != patch or attempt["patch"] != patch
                or result["job"] != attempt["job"] or attempt["decision"] != "accept"):
            raise ValueError("winning patch and accepted attempt disagree")
        src = path.parent / patch
        if src.parent.is_symlink():
            raise ValueError("unexpected patch folder link")
        data = record.read_bytes_capped(src, label="winning patch")
        if hashlib.sha256(data).hexdigest() != attempt["patchSha256"]:
            raise ValueError("winning patch digest differs")
        target = out / patch
        target.parent.mkdir()
        target.write_bytes(data)
        lines += ["", doc["review"], "", "Review the diff. From the rejected checkout, set ARTIFACT to the",
                  "absolute path of the unpacked artifact, then run:", "", "```sh",
                  f'patch --dry-run -d "./{game}" -p1 < "$ARTIFACT/{patch}"',
                  f'patch -d "./{game}" -p1 < "$ARTIFACT/{patch}"', "```"]
    else:
        lines.append("There is no accepted patch to apply.")
    for attempt in doc['attempts']:
        if 'fixerInvocation' not in attempt:
            continue
        name = f"attempt-{attempt['n']}/fixer-invocation.json"
        if attempt['fixerInvocation'] != name:
            raise ValueError('unexpected invocation proof path')
        source = path.parent / name
        if source.resolve() != source.absolute():
            raise ValueError('linked invocation proof')
        raw = record.read_bytes_capped(source, 2*1024*1024, 'invocation proof')
        if hashlib.sha256(raw).hexdigest() != attempt.get('fixerInvocationSha256'):
            raise ValueError('invocation proof digest differs')
        from expectrail.fixer_budget import read
        read(source)
        target = out / name; target.parent.mkdir(exist_ok=True); target.write_bytes(raw)
    (out / "repair-run.json").write_bytes(contracts.canonical_v1(doc) + b"\n")
    with summary.open("a", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def spawn_recorded(jobs, job):
    return runner.spawn(jobs, job, [sys.executable, "-m", "tools.ci_autofix", "worker", str(jobs.root), job])


def recorded_worker(root, job):
    from expectrail.recorded import RecordedObserver, read_recording
    from expectrail.orchestrator.engines import GodotGate

    jobs = store.JobStore(Path(root))
    if jobs.request(job)["executionClass"] != "isolated":
        raise ValueError("CI repair requires isolated replay")
    path = Path(__file__).resolve().parents[1] / "docs/run-it/vision/clean.json"
    engine = GodotGate(rule="both", visual=RecordedObserver(read_recording(path), every=1))
    runner.work(jobs, job, {"godot": engine}, own_group=True)


def run_fixture():
    env = os.environ
    temp = Path(env["RUNNER_TEMP"])
    base = Path(env["BASE_CHECKOUT"]).resolve()
    fixture = base / verify.safe_relative(env["FIXTURE"], "fixture")
    if fixture.suffix != ".patch" or fixture.resolve() != fixture or not fixture.is_file():
        raise ValueError("expected a fixture .patch file in the base checkout without links")
    attempts = int(env["ATTEMPTS"])
    if not 1 <= attempts <= 10:
        raise ValueError("attempts must be between 1 and 10")
    policy = Policy.configured()
    jobs = store.JobStore(temp / "repair-jobs")
    req = request.build(adapter="godot", head=temp / "head", head_commit=env["HEAD_SHA"], base=base,
                        base_commit=env["BASE_SHA"], game=policy.game, specs=policy.specs, routes=policy.routes,
                        execution_class="isolated", intent="fix" if env["INTENT"] == "fix" else None)
    parent, _ = jobs.create(req)
    job = parent["id"]
    result = runner.wait(jobs, job, spawn_recorded(jobs, job))
    if (result["phase"], result["decision"]) != ("completed", "reject"):
        raise ValueError("isolated replay did not reproduce the published reject")
    path, _ = repair.repair(jobs, job, attempts=attempts, fixture=fixture, spawn_worker=spawn_recorded)
    publish(path, temp / "repair-artifact", Path(env["GITHUB_STEP_SUMMARY"]), policy.game, job)


if __name__ == "__main__":
    if sys.argv[1:] == ["authorize"]:
        authorize()
    elif sys.argv[1:] == ["repair"]:
        run_fixture()
    elif len(sys.argv) == 4 and sys.argv[1] == "worker":
        recorded_worker(*sys.argv[2:])
    else:
        sys.exit("expected authorize, repair or worker")
