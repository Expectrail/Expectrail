"""Run `expectrail verify` on Godot projects the team did not write, and write down what happened.

    python -m tools.outside_trial --fetch --out runs/outside        # in CI: fetch at the pinned commits
    python -m tools.outside_trial --source <clone> --out runs/outside   # a clone that is already there

The list is `tests/outside/projects.json`: a repository, a full commit, a folder in it, a licence and
our own routes for it. A project is fetched at its commit and never copied into this repository. For
each one a checkout is laid out (the project as `project/`, our routes, the bundled approved spec
copied unchanged, as the tests of a second project do) and the installed command is run on it as a
stranger would run it. Nothing is approved here and no model is called.

This is a trial, not a test: it does not fail when a verdict is needs-review or reject. It fails
when a project cannot be fetched at its commit, or when the command ends with a code that is no
verdict (3 failed, 4 cancelled, 5 could not be carried out, 6 not finished). What it writes
(`outside-trial.json`, `outside-trial.md`) is the record docs/outside-projects.md quotes.

The projects' code is not ours: it is only ever started by the harness, and CI runs this with the
replay sandbox required, no secret and a read-only token. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LIST = REPO / "tests" / "outside" / "projects.json"
SPEC = REPO / "agents" / "specs" / "player-stays-above-ground.json"
FORMAT = "expectrail.outside-projects/v0"
VERDICTS = {0: "accept", 1: "reject", 2: "needs-review"}
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]{0,200}$")


class TrialError(Exception):
    """The list is not usable, or a project could not be fetched as pinned."""


def load_list(path: Path = LIST) -> list[dict]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("format") != FORMAT or not isinstance(doc.get("projects"), list) or not doc["projects"]:
        raise TrialError(f"{path.name}: not a {FORMAT} list with projects")
    seen = set()
    for p in doc["projects"]:
        missing = [k for k in ("name", "repository", "commit", "path", "licence", "kind", "routes") if not isinstance(p.get(k), str)]
        if missing:
            raise TrialError(f"a project lacks {', '.join(missing)}")
        if not _NAME.match(p["name"]) or p["name"] in seen:
            raise TrialError(f"project name {p['name']!r} is not a plain name used once")
        seen.add(p["name"])
        if not _COMMIT.match(p["commit"]):
            raise TrialError(f"{p['name']}: the commit must be all 40 characters, so the code that runs is the code that was read")
        if not p["repository"].startswith("https://github.com/") or not p["repository"].endswith(".git"):
            raise TrialError(f"{p['name']}: the repository must be an https://github.com/ address ending in .git")
        for key in ("path", "routes"):
            if not _PATH.match(p[key]) or ".." in p[key].split("/"):
                raise TrialError(f"{p['name']}: {key} must be a plain path inside its repository")
        if not p["routes"].startswith("tests/outside/"):
            raise TrialError(f"{p['name']}: routes are ours and live under tests/outside/")
    return doc["projects"]


def git(*args: str, cwd: Path) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=300,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if done.returncode:
        raise TrialError(f"git {' '.join(args[:2])} failed: {done.stderr.strip()[-300:]}")
    return done.stdout.strip()


def fetch(project: dict, into: Path) -> Path:
    """The project's folder from a clone made at exactly its commit (only that folder is checked out)."""
    clone = into / f"{project['commit'][:12]}-{hashlib.sha256(project['repository'].encode()).hexdigest()[:8]}"
    if not (clone / ".git").is_dir():
        clone.mkdir(parents=True)
        git("init", "-q", cwd=clone)
        git("remote", "add", "origin", project["repository"], cwd=clone)
        git("config", "core.sparseCheckout", "true", cwd=clone)
    sparse = clone / ".git" / "info" / "sparse-checkout"
    wanted = set(sparse.read_text(encoding="utf-8").split()) if sparse.exists() else set()
    sparse.write_text("\n".join(sorted(wanted | {project["path"] + "/"})) + "\n", encoding="utf-8")
    git("fetch", "-q", "--depth=1", "--no-tags", "origin", project["commit"], cwd=clone)
    git("checkout", "-q", "--detach", "FETCH_HEAD", cwd=clone)
    if git("rev-parse", "HEAD", cwd=clone) != project["commit"]:
        raise TrialError(f"{project['name']}: the clone is not at the pinned commit")
    return clone


def lay_out(project: dict, source: Path, work: Path) -> Path:
    """A checkout for one project: its folder as `project/`, our routes, the bundled approved spec."""
    folder = source / project["path"]
    if not (folder / "project.godot").is_file():
        raise TrialError(f"{project['name']}: no project.godot at {project['path']} in the source")
    checkout = work / project["name"]
    if checkout.exists():
        shutil.rmtree(checkout)
    shutil.copytree(folder, checkout / "project", symlinks=True)
    shutil.copytree(REPO / project["routes"], checkout / "routes")
    (checkout / "specs").mkdir()
    shutil.copy(SPEC, checkout / "specs" / SPEC.name)
    return checkout


def verify(project: dict, checkout: Path, out: Path, command: list[str], timeout: int,
           execution_class: str = "diagnostic") -> dict:
    jobs = out / "jobs" / project["name"]
    started = time.monotonic()
    try:
        done = subprocess.run([*command, "--jobs-root", str(jobs), "verify", "--head", str(checkout), "--game", "project",
                               "--routes", "routes/*.json", "--specs", "specs", "--execution-class", execution_class,
                               "--json"],
                              capture_output=True, text=True, timeout=timeout)
        code, stdout, stderr = done.returncode, done.stdout, done.stderr
    except subprocess.TimeoutExpired as late:
        code, stdout, stderr = 6, late.stdout or "", f"no answer in {timeout} seconds"
    seconds = round(time.monotonic() - started, 1)
    row = {"name": project["name"], "repository": project["repository"], "commit": project["commit"],
           "path": project["path"], "licence": project["licence"], "kind": project["kind"],
           "exit": code, "verdict": VERDICTS.get(code), "seconds": seconds, "decision": None, "reasons": [],
           "checks": None, "routes": [], "failures": [], "isolation": None}
    try:
        status = json.loads(stdout)
        row["decision"] = status.get("decision")
        row["reasons"] = [str(r)[:300] for r in (status.get("reasons") or [])][:12]
        row["diagnostics"] = [str(d.get("message", d))[:300] if isinstance(d, dict) else str(d)[:300]
                              for d in (status.get("diagnostics") or [])][:8]
    except (ValueError, AttributeError):
        row["output"] = (stdout.strip() or stderr.strip())[-600:]
    for record in sorted(jobs.rglob("findings.json")):
        try:
            doc = json.loads(record.read_text(encoding="utf-8"))
            row["checks"] = doc.get("counts")
            row["routes"] = [{"name": r.get("name"), "status": r.get("status")} for r in doc.get("routes", [])]
            row["isolation"] = doc.get("isolation")
            row["failures"] = [f"{f.get('spec')} on {f.get('route')}: {str(f.get('reason'))[:300]}"
                               for f in doc.get("findings", [])][:8]
        except (OSError, ValueError):
            pass
    return row


def markdown(rows: list[dict]) -> str:
    lines = ["| Project | Kind | Exit | Verdict | Seconds | Checks | Reasons |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        checks = "none" if not r["checks"] else f"{r['checks'].get('passed')} of {r['checks'].get('checks')} pass"
        reasons = "; ".join((r["reasons"] or r.get("diagnostics") or [r.get("output", "")]) + r.get("failures", [])) or "none"
        lines.append(f"| {r['name']} (`{r['commit'][:7]}`, {r['licence']}) | {r['kind']} | {r['exit']} | "
                     f"{r['verdict'] or 'no verdict'} | {r['seconds']} | {checks} | {reasons.replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--fetch", action="store_true", help="fetch each project at its pinned commit")
    where.add_argument("--source", type=Path, help="a clone that already holds the projects' folders")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", help="one project's name")
    ap.add_argument("--timeout", type=int, default=900, help="seconds for one verification")
    ap.add_argument("--execution-class", default="diagnostic", choices=("diagnostic", "isolated"),
                    help="isolated: every replay in the replay sandbox, or no accept (CI uses this)")
    ap.add_argument("--command", default=f"{sys.executable} -m expectrail.cli",
                    help="the command to run, as a stranger would have it (default: this checkout's)")
    args = ap.parse_args(argv)
    try:
        projects = [p for p in load_list() if args.only in (None, p["name"])]
        if not projects:
            raise TrialError(f"no project named {args.only}")
        args.out.mkdir(parents=True, exist_ok=True)
        rows = []
        for project in projects:
            source = fetch(project, args.out / "sources") if args.fetch else args.source
            checkout = lay_out(project, source, args.out / "checkouts")
            rows.append(verify(project, checkout, args.out, args.command.split(), args.timeout, args.execution_class))
            print(f"{project['name']}: exit {rows[-1]['exit']} ({rows[-1]['verdict'] or 'no verdict'}) in {rows[-1]['seconds']} s", flush=True)
    except TrialError as err:
        print(f"outside trial: {err}", file=sys.stderr)
        return 5
    (args.out / "outside-trial.json").write_text(json.dumps({"format": "expectrail.outside-trial/v0", "projects": rows}, indent=2) + "\n", encoding="utf-8")
    table = markdown(rows)
    (args.out / "outside-trial.md").write_text(table, encoding="utf-8")
    print(table)
    return 0 if all(r["verdict"] for r in rows) else 3


if __name__ == "__main__":
    sys.exit(main())
