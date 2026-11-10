"""The CI gate's comment step: post or update the one pull request comment that carries the verdict.

    python3 -I .github/actions/expectrail-comment/post.py --evidence "$RUNNER_TEMP/expectrail-evidence"

Runs in a separate, trusted job triggered by ``workflow_run`` after the verify job finishes. That job
holds a token that can write pull request comments, so this module:

- never checks out, imports or runs anything from the pull request, and installs nothing: it is
  standard library only and reads one file, ``findings.json``, from the downloaded artifact;
- treats that file as data (``expectrail.gate.record.read_record``: size cap, no symlink, strict
  JSON, the closed schema, every id, count and decision recomputed);
- finds the pull request from the event GitHub sends (the run's head repository, branch and commit),
  never from the artifact, and refuses a record that names another pull request or commit;
- escapes every string that came from the record before it goes into Markdown, caps the comment's
  size, and builds every link from the event, never from the record;
- writes held-out results as counts only, because the record has no place for anything else.

One comment per pull request: it is found by a hidden marker and by its author (the token's bot),
and updated in place on every push. Finding ids come from the spec, route and failure kind only,
so a failure keeps its id across pushes, and the comment lists the ids new and resolved since the
last update. Standard library only, so it runs on the runner's own Python 3.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from expectrail.gate import record as rec

MARKER = "<!-- expectrail-gate:v0 -->"
TRAILER = re.compile(r"<!-- expectrail-gate:v0 ids=([0-9a-f,]{0,65000}) -->")
BOT = "github-actions[bot]"
REVIEW_DOC = "https://github.com/Expectrail/Expectrail/blob/main/docs/review.md"
GATE_DOC = "https://github.com/Expectrail/Expectrail/blob/main/docs/ci-gate.md"
MAX_BODY = 60000  # GitHub refuses a comment over 65,536 characters
MAX_FINDING_ROWS = 30
MAX_CHECK_ROWS = 100
MAX_REASONS = 5
MAX_TEXT = 200
MAX_PREVIOUS_IDS = 4096
MAX_COMMENT_PAGES = 20
MAX_FILE_PAGES = 30  # the pull request files API lists at most 3,000 files

REPO_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}")
OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
SHA40 = re.compile(r"[0-9a-f]{40}")
RUN_ID = re.compile(r"[0-9]{1,20}")
WORKFLOW_PATH = re.compile(r"\.github/workflows/[A-Za-z0-9._-]{1,100}\.ya?ml")
ARTIFACT_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?")
WATCH_RE = re.compile(r"[A-Za-z0-9._][A-Za-z0-9._/-]{0,200}")
NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
WORDS = {"accept": "accept", "reject": "reject", "needs-review": "needs review"}
RESULT = {"pass": "pass", "fail": "fail", "needs-review": "needs review", "replay-error": "replay error",
          None: "not run"}

Api = Callable[..., object]


# --- Markdown ------------------------------------------------------------------------------------

_BACKSLASH = set("\\`*_{}[]()#+-!|~")
_WORD_JOINER = "⁠"


def md(text, limit: int = MAX_TEXT) -> str:
    """Text from a record, made inert in GitHub Markdown, on one line, at most ``limit`` characters.

    Control and format characters (newlines, zero-width and bidirectional marks) become spaces.
    HTML is entity-escaped, Markdown punctuation is backslash-escaped (so a pipe cannot end a table
    cell and brackets cannot make a link), and a word joiner follows every @ and # and breaks every
    :// and www. so the text cannot mention a person, link an issue or become a link.
    """
    s = "".join(ch if ch.isprintable() else " " for ch in str(text))
    s = " ".join(s.split())
    if len(s) > limit:
        s = s[: max(limit - 1, 0)] + "…"
    s = re.sub(r"(?i)www\.", lambda m: m.group(0)[:3] + _WORD_JOINER + ".", s)
    s = s.replace("://", ":" + _WORD_JOINER + "//")
    out = []
    for ch in s:
        if ch == "&":
            out.append("&amp;")
        elif ch == "<":
            out.append("&lt;")
        elif ch == ">":
            out.append("&gt;")
        elif ch == "@":
            out.append("@" + _WORD_JOINER)
        elif ch == "#":
            out.append("\\#" + _WORD_JOINER)
        elif ch in _BACKSLASH:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def name(text) -> str:
    """A spec id or route name (already schema-checked to [a-z0-9-]); anything else is escaped."""
    return str(text) if NAME_RE.fullmatch(str(text)) else md(text, 64)


# --- the event -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Context:
    repo: str
    run_id: str
    run_event: str
    head_sha: str
    head_repo: str
    head_owner: str
    head_branch: str
    workflow_path: str
    artifact: str
    bot: str

    @property
    def run_url(self) -> str:
        return f"https://github.com/{self.repo}/actions/runs/{self.run_id}"

    @classmethod
    def from_env(cls, env) -> "Context":
        """From the workflow_run event, passed in by the action as environment variables. Every value
        is checked against a strict pattern; the branch is only ever sent URL-encoded."""
        def need(key: str, pattern: re.Pattern | None) -> str:
            value = str(env.get(key) or "")
            if pattern is not None and not pattern.fullmatch(value):
                raise ValueError(f"{key} is missing or malformed")
            return value

        branch = str(env.get("HEAD_BRANCH") or "")
        if not branch or len(branch) > 255 or not branch.isprintable():
            raise ValueError("HEAD_BRANCH is missing or malformed")
        bot = str(env.get("BOT_LOGIN") or BOT)
        return cls(repo=need("REPO", REPO_RE), run_id=need("RUN_ID", RUN_ID),
                   run_event=need("RUN_EVENT", re.compile(r"[a-z_]{1,40}")), head_sha=need("HEAD_SHA", SHA40),
                   head_repo=need("HEAD_REPO", REPO_RE), head_owner=need("HEAD_OWNER", OWNER_RE),
                   head_branch=branch, workflow_path=str(env.get("WORKFLOW_PATH") or ""),
                   artifact=need("ARTIFACT_NAME", ARTIFACT_RE),
                   bot=bot if LOGIN_RE.fullmatch(bot) else BOT)


def http_api(token: str, base: str = "https://api.github.com") -> Api:
    def call(method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(base + path, data=data, method=method, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "expectrail-gate-comment"})
        if data is not None:
            request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read(8 * 1024 * 1024).decode("utf-8")
        return json.loads(text) if text else None
    return call


def find_pull_request(api: Api, ctx: Context) -> dict | None:
    """The open pull request whose head is exactly this run's repository and commit, looked up from
    the event (a fork's run carries no pull request list, and the artifact is not trusted for it)."""
    head = urllib.parse.quote(f"{ctx.head_owner}:{ctx.head_branch}", safe="")
    pulls = api("GET", f"/repos/{ctx.repo}/pulls?state=open&head={head}&per_page=100") or []
    found = [p for p in pulls if (p.get("head") or {}).get("sha") == ctx.head_sha
             and ((p.get("head") or {}).get("repo") or {}).get("full_name") == ctx.head_repo
             and ((p.get("base") or {}).get("repo") or {}).get("full_name", ctx.repo) == ctx.repo]
    return found[0] if len(found) == 1 else None


def find_comment(api: Api, ctx: Context, number: int) -> tuple[dict | None, list[str]]:
    """This gate's comment on the pull request, if any (written by the bot, starting with the marker),
    and the finding ids it listed. A comment anyone else wrote is never picked, whatever it says."""
    for page in range(1, MAX_COMMENT_PAGES + 1):
        items = api("GET", f"/repos/{ctx.repo}/issues/{number}/comments?per_page=100&page={page}") or []
        for item in items:
            body = item.get("body") or ""
            if (item.get("user") or {}).get("login") == ctx.bot and body.startswith(MARKER):
                match = TRAILER.search(body)
                ids = [i for i in (match.group(1).split(",") if match else []) if rec.FINDING_ID.fullmatch(i)]
                return item, ids[:MAX_PREVIOUS_IDS]
        if len(items) < 100:
            break
    return None, []


def touched_files(api: Api, ctx: Context, number: int, watch: list[str]) -> list[str] | None:
    """The watched paths this pull request changes (the workflow that produced the verdict, and any
    path the trusted workflow names). None when the list of files could not be read in full."""
    entries = ([ctx.workflow_path] if WORKFLOW_PATH.fullmatch(ctx.workflow_path) else []) + [
        w for w in watch if WATCH_RE.fullmatch(w) and ".." not in w.split("/")]
    hit: list[str] = []
    for page in range(1, MAX_FILE_PAGES + 1):
        try:
            files = api("GET", f"/repos/{ctx.repo}/pulls/{number}/files?per_page=100&page={page}") or []
        except urllib.error.HTTPError:
            return None
        for item in files:
            for path in (item.get("filename"), item.get("previous_filename")):
                if not isinstance(path, str):
                    continue
                for entry in entries:
                    if entry not in hit and (path == entry or (entry.endswith("/") and path.startswith(entry))):
                        hit.append(entry)
        if len(files) < 100:
            return hit
    return None


# --- the comment ---------------------------------------------------------------------------------

def _n(count: int, word: str, many: str | None = None) -> str:
    return f"{count} {word if count == 1 else (many or word + 's')}"


def _summary(record: dict) -> str:
    counts, held = record["counts"], record["heldOut"]
    total = counts["checks"] + held["checks"]
    failed = counts["failed"] + held["failed"]
    unclear = counts["needsReview"] + held["needsReview"]
    decision = record["decision"]
    if decision == "reject":
        return f"**{failed} of {_n(total, 'check')} {'fails' if failed == 1 else 'fail'} after this change.**"
    if decision == "accept":
        return (f"**{'The' if total == 1 else 'All'} {_n(total, 'check')} {'passes' if total == 1 else 'pass'} after this change.** Accepted means this change passed these "
                "checks on these routes, not that the game is correct.")
    if not total:
        return "**No check ran**, so the gate cannot accept."
    if unclear:
        return (f"**{unclear} of {_n(total, 'check')} could not be decided**, so the gate does not accept. "
                "A person should look.")
    return "**The held-out routes could not be judged**, so the gate does not accept."


def _held_line(held: dict, fork: bool) -> str:
    if held["status"] == "judged":
        return (f"**Held-out routes:** {_n(held['routes'], 'route')}, {_n(held['checks'], 'check')}: {held['passed']} pass, "
                f"{held['failed']} fail, {held['needsReview']} need review. Counts only: the routes stay private.")
    if held["status"] == "unavailable":
        return "**Held-out routes:** configured, but they could not be read or judged (no detail is given here)."
    if fork:
        return "**Held-out routes:** not used. A fork's pull request gets no secrets, so they are never fetched for it."
    return "**Held-out routes:** not used on this run."


def _checks_line(record: dict) -> str:
    pr = record["pullRequest"] or {}
    specs, routes = len(record["specs"]), len(record["routes"])
    if record["checksFrom"] == "base":
        where = f"from the base commit `{(pr.get('baseSha') or '')[:12]}`, so this change cannot edit them"
    else:
        where = "from this pull request's own commit, so a change to them judges itself"
    line = f"**Checks used:** {_n(specs, 'approved spec')} on {_n(routes, 'route')}, {where}."
    changed = record["checksChanged"]
    if changed["specs"] or changed["routes"]:
        line += (f" This pull request edits {_n(changed['specs'], 'spec file')} and {_n(changed['routes'], 'route file')};"
                 " they judge changes once it merges.")
    if record["drafts"]:
        line += (f" {_n(record['drafts'], 'draft spec')} without a person's approval "
                 f"{'was' if record['drafts'] == 1 else 'were'} not used.")
    return line


def _body(record: dict, ctx: Context, *, previous: list[str], touched: list[str] | None, fork: bool,
          finding_rows: int, check_rows: int, show_reasons: bool) -> str:
    decision = record["decision"]
    head = record["pullRequest"]["headSha"]
    lines = [MARKER, f"### Expectrail: {WORDS[decision]}", "", _summary(record)]
    if show_reasons and decision != "accept" and record["reasons"]:
        lines += [""] + [f"- {md(r)}" for r in record["reasons"][:MAX_REASONS]]
    lines.append("")
    if touched:
        shown = ", ".join(f"`{md(t, 120)}`" for t in touched[:10])
        lines += [f"> **Read the workflow change first.** This pull request changes {len(touched)} of the paths "
                  f"this verdict depends on ({shown}). The verify job runs the pull request's own workflow and "
                  "code, so the verdict is only as trustworthy as that change.", ""]
    elif touched is None:
        lines += ["> This pull request's files could not all be listed, so a change to the workflow behind this "
                  "verdict would not be noticed here.", ""]

    findings = record["findings"]
    if findings:
        lines += ["| Finding | Check | Route | Before | After | Comparison | Why |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for f in findings[:finding_rows]:
            lines.append(f"| `{f['id']}` | {name(f['spec'])} | {name(f['route'])} | {RESULT[f['before']]} | "
                         f"{RESULT[f['after']]} | {f['comparison']} | {md(f['reason'])} |")
        if len(findings) > finding_rows:
            lines.append(f"\n{len(findings) - finding_rows} more findings are listed in the artifact's findings.json.")
        lines.append("")
    now = [f["id"] for f in findings]
    new = [i for i in now if previous and i not in previous]
    resolved = [i for i in previous if i not in now]
    if new or resolved:
        bits = []
        if new:
            bits.append("new since the last update: " + ", ".join(f"`{i}`" for i in new[:20])
                        + (f" and {len(new) - 20} more" if len(new) > 20 else ""))
        if resolved:
            bits.append("resolved since the last update: " + ", ".join(f"`{i}`" for i in resolved[:20])
                        + (f" and {len(resolved) - 20} more" if len(resolved) > 20 else ""))
        lines += ["Findings " + "; ".join(bits) + ".", ""]

    checks = record["checks"]
    if checks and check_rows:
        lines += [f"<details><summary>All {_n(len(checks), 'public check')}</summary>", "",
                  "| Check | Route | Before | After | Comparison | Finding |", "| --- | --- | --- | --- | --- | --- |"]
        for c in checks[:check_rows]:
            fid = f"`{c['findingId']}`" if c["findingId"] else ""
            lines.append(f"| {name(c['spec'])} | {name(c['route'])} | {RESULT[c['before']]} | {RESULT[c['after']]} | "
                         f"{c['comparison']} | {fid} |")
        if len(checks) > check_rows:
            lines.append(f"\n{len(checks) - check_rows} more checks are listed in the artifact's findings.json.")
        lines += ["", "</details>", ""]

    lines += [_held_line(record["heldOut"], fork), "", _checks_line(record), ""]
    page = "the review page (`review/index.html`), " if record["reviewPage"] else ""
    lines += [f"**Evidence:** {page}the verdicts and findings.json are in the `{ctx.artifact}` artifact of "
              f"[run {ctx.run_id}]({ctx.run_url}). The comparisons use the review's words: "
              f"[how to read a review]({REVIEW_DOC}). [How this gate works and its limits]({GATE_DOC}).", ""]
    commit = record["expectrail"]["commit"]
    lines.append(f"<sub>Commit `{head[:12]}`. Expectrail {md(record['expectrail']['version'], 32)}"
                 + (f" at `{commit[:12]}`" if commit else "")
                 + ". A finding id is the first 12 hex digits of sha256(spec, route, kind), so a failure keeps "
                 "its id across pushes. The verdict was computed in the pull request's own workflow run; this "
                 "comment was posted by a separate job that only read it.</sub>")
    lines.append(f"<!-- expectrail-gate:v0 ids={','.join(now[:MAX_PREVIOUS_IDS])} -->")
    return "\n".join(lines) + "\n"


def render(record: dict, ctx: Context, *, previous: list[str] | None = None, touched: list[str] | None = (),
           fork: bool = False) -> str:
    """The comment for a checked record, within GitHub's size limit (rows are dropped to fit)."""
    previous = list(previous or [])
    touched = list(touched) if touched is not None else None
    for finding_rows, check_rows, reasons in ((MAX_FINDING_ROWS, MAX_CHECK_ROWS, True),
                                              (MAX_FINDING_ROWS, 0, True), (10, 0, False), (0, 0, False)):
        body = _body(record, ctx, previous=previous, touched=touched, fork=fork, finding_rows=finding_rows,
                     check_rows=check_rows, show_reasons=reasons)
        if len(body) <= MAX_BODY:
            return body
    return body[: MAX_BODY - 200] + "\n\n(cut to fit)\n" + MARKER.replace("v0 -->", "v0 ids= -->") + "\n"


def render_unreadable(problem: str, ctx: Context, *, touched: list[str] | None = ()) -> str:
    """The comment when the evidence cannot be used: says so, so an older verdict does not stand."""
    lines = [MARKER, "### Expectrail: needs review", "",
             f"**The evidence from [run {ctx.run_id}]({ctx.run_url}) could not be used:** {md(problem, 300)}.",
             "", "No verdict is shown for this commit. Look at the verify job's log, and run it again if it "
                 "was interrupted.", ""]
    if touched:
        lines += [f"> This pull request changes {len(touched)} of the paths the verdict depends on "
                  f"({', '.join(f'`{md(t, 120)}`' for t in touched[:10])}).", ""]
    lines += [f"<sub>Commit `{ctx.head_sha[:12]}`. [How this gate works]({GATE_DOC}).</sub>",
              "<!-- expectrail-gate:v0 ids= -->"]
    return "\n".join(lines) + "\n"


# --- the run -------------------------------------------------------------------------------------

def run(api: Api, ctx: Context, evidence: Path | None, watch: list[str] | None = None) -> dict:
    """Post or update the comment. Returns {"action": created|updated|skipped, ...}."""
    if ctx.run_event != "pull_request":
        return {"action": "skipped", "reason": f"the verify run was a {ctx.run_event} run, not a pull request's"}
    pr = find_pull_request(api, ctx)
    if pr is None:
        return {"action": "skipped", "reason": "no open pull request has this run's head commit "
                                               "(a newer push, or the pull request closed)"}
    number = int(pr["number"])
    fork = ((pr.get("head") or {}).get("repo") or {}).get("full_name") != ctx.repo
    problem, record = None, None
    if evidence is None:
        problem = f"no {ctx.artifact} artifact was found for the run"
    else:
        try:
            record = rec.read_record(Path(evidence) / "findings.json")
        except rec.RecordError as exc:
            problem = str(exc)
        except rec.SchemaError as exc:  # the schema itself, not the record
            problem = f"the findings schema cannot be checked ({exc})"
    if record is not None:
        named = record["pullRequest"]
        if named is None or named["number"] != number or named["headSha"] != ctx.head_sha:
            problem, record = "the record names a different pull request or commit than this run", None
    touched = touched_files(api, ctx, number, watch or [])
    comment, previous = find_comment(api, ctx, number)
    body = render(record, ctx, previous=previous, touched=touched, fork=fork) if record is not None \
        else render_unreadable(problem or "unknown", ctx, touched=touched)
    if comment is not None:
        result = api("PATCH", f"/repos/{ctx.repo}/issues/comments/{int(comment['id'])}", {"body": body}) or {}
        action = "updated"
    else:
        result = api("POST", f"/repos/{ctx.repo}/issues/{number}/comments", {"body": body}) or {}
        action = "created"
    return {"action": action, "pullRequest": number, "url": result.get("html_url"),
            "decision": record["decision"] if record else "needs-review", "problem": problem}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--evidence", type=Path, help="the folder the artifact was downloaded into")
    p.add_argument("--watch", default="", help="more paths (a trailing / for a folder) the verdict depends on, "
                                               "one per line")
    args = p.parse_args(argv)
    token = os.environ.get("GH_TOKEN") or ""
    try:
        ctx = Context.from_env(os.environ)
    except ValueError as exc:
        print(f"::error title=Expectrail comment::{exc}")
        return 1
    if not token:
        print("::error title=Expectrail comment::GH_TOKEN is not set")
        return 1
    evidence = args.evidence if args.evidence and args.evidence.is_dir() else None
    watch = [w.strip() for w in args.watch.splitlines() if w.strip()]
    result = run(http_api(token), ctx, evidence, watch)
    print(f"::notice title=Expectrail comment {result['action']}::"
          + (f"pull request {result.get('pullRequest')}: {result.get('decision')}"
             + (f"; evidence unusable: {md(result['problem'], 120)}" if result.get("problem") else "")
             if result["action"] != "skipped" else result["reason"]))
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"action={result['action']}\n")
            if result.get("url") and re.fullmatch(r"https://github\.com/[A-Za-z0-9._/#-]+", str(result["url"])):
                handle.write(f"comment-url={result['url']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
