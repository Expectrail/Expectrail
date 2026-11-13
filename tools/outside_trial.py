"""Run `expectrail verify` on Godot projects the team did not write, and write down what happened.

    python -m tools.outside_trial --fetch --out runs/outside        # in CI: fetch at the pinned commits
    python -m tools.outside_trial --source <clone> --out runs/outside   # a clone that is already there

The list is `tests/outside/projects.json`: a repository, a full commit, a folder in it, a licence and
our own routes for it. A project is fetched at its commit and never copied into this repository. For
each one a checkout is laid out (the project as `project/`, our routes, the bundled approved spec
copied unchanged, as the tests of a second project do) and the installed command is run on it as a
stranger would run it. Nothing is approved here and no model is called.

A project may list `changes`: small patches of ours against its folder (`tests/outside/<name>/changes/`),
each with the verdict it should get. For each, the project unchanged is the base and the patched copy
is the head, and `expectrail verify --base` judges the change, as it would judge a pull request. The
row says the expected verdict beside the one given; a mismatch is a finding, not a failure of the trial.

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
        changes = p.get("changes", [])
        if not isinstance(changes, list):
            raise TrialError(f"{p['name']}: changes must be a list")
        names = set()
        for c in changes:
            if not isinstance(c, dict) or not all(isinstance(c.get(k), str) for k in ("name", "patch", "expect", "what")):
                raise TrialError(f"{p['name']}: a change needs a name, a patch, an expected verdict and what it does")
            if not _NAME.match(c["name"]) or c["name"] in names:
                raise TrialError(f"{p['name']}: change name {c['name']!r} is not a plain name used once")
            names.add(c["name"])
            if c["expect"] not in VERDICTS.values():
                raise TrialError(f"{p['name']}/{c['name']}: expect must be one of {', '.join(VERDICTS.values())}")
            folder = f"tests/outside/{p['name']}/changes/"
            if (not _PATH.match(c["patch"]) or ".." in c["patch"].split("/") or not c["patch"].startswith(folder)
                    or not c["patch"].endswith(".patch")):
                raise TrialError(f"{p['name']}/{c['name']}: the patch is ours and lives under {folder}")
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


def lay_out(project: dict, source: Path, work: Path, change: dict | None = None) -> Path:
    """A checkout for one project: its folder as `project/`, our routes, the bundled approved spec.
    With ``change``, the checkout is named after it and its patch is applied to `project/`."""
    folder = source / project["path"]
    if not (folder / "project.godot").is_file():
        raise TrialError(f"{project['name']}: no project.godot at {project['path']} in the source")
    checkout = work / (project["name"] if change is None else f"{project['name']}+{change['name']}")
    if checkout.exists():
        shutil.rmtree(checkout)
    shutil.copytree(folder, checkout / "project", symlinks=True)
    shutil.copytree(REPO / project["routes"], checkout / "routes")
    (checkout / "specs").mkdir()
    shutil.copy(SPEC, checkout / "specs" / SPEC.name)
    if change is not None:
        # git apply refuses a patch that reaches outside the folder it runs in.
        done = subprocess.run(["git", "apply", "--whitespace=nowarn", str(REPO / change["patch"])],
                              cwd=checkout / "project", capture_output=True, text=True, timeout=60)
        if done.returncode:
            raise TrialError(f"{project['name']}/{change['name']}: the patch does not apply: {done.stderr.strip()[-300:]}")
    return checkout


def verify(project: dict, checkout: Path, out: Path, command: list[str], timeout: int,
           execution_class: str = "diagnostic", base: Path | None = None, change: dict | None = None) -> dict:
    jobs = out / "jobs" / (project["name"] if change is None else f"{project['name']}+{change['name']}")
    started = time.monotonic()
    try:
        done = subprocess.run([*command, "--jobs-root", str(jobs), "verify", "--head", str(checkout), "--game", "project",
                               "--routes", "routes/*.json", "--specs", "specs", "--execution-class", execution_class,
                               "--json", *(["--base", str(base)] if base is not None else [])],
                              capture_output=True, text=True, timeout=timeout)
        code, stdout, stderr = done.returncode, done.stdout, done.stderr
    except subprocess.TimeoutExpired as late:
        code, stdout, stderr = 6, late.stdout or "", f"no answer in {timeout} seconds"
    seconds = round(time.monotonic() - started, 1)
    row = {"name": project["name"], "repository": project["repository"], "commit": project["commit"],
           "path": project["path"], "licence": project["licence"], "kind": project["kind"],
           "exit": code, "verdict": VERDICTS.get(code), "seconds": seconds, "decision": None, "reasons": [],
           "checks": None, "routes": [], "failures": [], "isolation": None, "around": [],
           "change": None if change is None else change["name"], "what": None if change is None else change["what"],
           "expect": None if change is None else change["expect"]}
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
            row["around"] = [around(jobs, f) for f in doc.get("findings", [])[:3] if isinstance(f.get("frame"), int)]
        except (OSError, ValueError):
            pass
    return row


def capture(project: dict, checkout: Path, out: Path, timeout: int, sandbox: str = "require") -> list[dict]:
    """Replay each of our routes on the project with the harness alone, the sandbox required, and
    keep the frames and the trace: `out/<project>/<route>/frames/`, `trace.json`, `replay.json`.
    Nothing is judged. The frames are pictures, to be looked at by a job that never starts the
    project's code. The command line always requires the sandbox; ``sandbox`` is an argument only so
    that the tests can run this on a project of our own where bubblewrap is not installed."""
    rows = []
    for route in sorted((checkout / "routes").glob("*.json")):
        into = out / project["name"] / route.stem
        try:
            done = subprocess.run([sys.executable, "-m", "harness.run", "--route", str(route), "--game",
                                   str(checkout / "project"), "--out", str(into), "--sandbox", sandbox],
                                  capture_output=True, text=True, timeout=timeout, cwd=REPO)
            code, said = done.returncode, (done.stderr.strip() or done.stdout.strip())[-300:]
        except subprocess.TimeoutExpired:
            code, said = 6, f"no answer in {timeout} seconds"
        frames = len(list((into / "frames").glob("*.png"))) if (into / "frames").is_dir() else 0
        for extra in ("work", "godot.log"):   # the copy of the project and its log stay out of the artifact
            target = into / extra
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink()
        rows.append({"project": project["name"], "route": route.stem, "exit": code, "frames": frames,
                     "said": "" if code == 0 else said})
    return rows


def around(jobs: Path, finding: dict, before: int = 3, after: int = 3) -> dict:
    """What the engine logged around a failing check's first frame: the player's position, the
    ground line and whether the player was on a floor, from the head's trace. Printed with the
    result because the trace itself stays in the job's folder."""
    out = {"spec": finding.get("spec"), "route": finding.get("route"), "frame": finding["frame"], "rows": []}
    for trace_file in sorted(jobs.rglob(f"head/{finding.get('route')}/trace.json")):
        try:
            trace = json.loads(trace_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = trace.get("rows") or []
        step = max(int(trace.get("physicsTicksPerSecond") or 120) // 60, 1)
        tick = finding["frame"] * step
        out["ticksPerFrame"] = step
        out["rows"] = [{"tick": r.get("tick"), "player": r.get("player"), "ground": r.get("ground"),
                        "onFloor": r.get("onFloor"), "view": r.get("view")}
                       for r in rows[max(0, tick - before * step):tick + after * step + 1:step]]
        out["first"] = {k: rows[0].get(k) for k in ("player", "ground", "onFloor")} if rows else None
        break
    return out


def markdown(rows: list[dict]) -> str:
    lines = ["| Project | Change | Exit | Verdict | Expected | Seconds | Checks | Reasons |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        checks = "none" if not r["checks"] else f"{r['checks'].get('passed')} of {r['checks'].get('checks')} pass"
        reasons = "; ".join((r["reasons"] or r.get("diagnostics") or [r.get("output", "")]) + r.get("failures", [])) or "none"
        change = "none (the project as pinned)" if not r.get("change") else f"{r['change']}: {r['what']}"
        expected = "-" if not r.get("expect") else (r["expect"] + (" (as expected)" if r["verdict"] == r["expect"] else " (DIFFERS)"))
        lines.append(f"| {r['name']} (`{r['commit'][:7]}`, {r['licence']}) | {change.replace('|', '/')} | {r['exit']} | "
                     f"{r['verdict'] or 'no verdict'} | {expected} | {r['seconds']} | {checks} | {reasons.replace('|', '/')} |")
    for r in rows:
        for a in r.get("around", []):
            lines += ["", f"What the engine logged for {r['name']} around frame {a['frame']} of `{a['route']}` "
                          f"({a.get('ticksPerFrame', '?')} ticks a frame; at tick 0: {json.dumps(a.get('first'))}):", "", "```"]
            lines += [json.dumps(row) for row in a["rows"]] or ["no trace was found"]
            lines += ["```"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--fetch", action="store_true", help="fetch each project at its pinned commit")
    where.add_argument("--source", type=Path, help="a clone that already holds the projects' folders")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--capture", action="store_true",
                    help="only replay our routes and keep the frames and traces; judge nothing")
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
        if args.capture:
            work = args.out.parent / (args.out.name + "-work")   # sources and checkouts stay out of --out
            captured = []
            for project in projects:
                source = fetch(project, work / "sources") if args.fetch else args.source
                captured += capture(project, lay_out(project, source, work / "checkouts"), args.out, args.timeout)
            (args.out / "captured.json").write_text(json.dumps({"format": "expectrail.outside-capture/v0",
                                                                "runs": captured}, indent=2) + "\n", encoding="utf-8")
            for row in captured:
                print(f"{row['project']}/{row['route']}: exit {row['exit']}, {row['frames']} frames {row['said']}".rstrip(), flush=True)
            return 0 if captured and all(r["exit"] == 0 and r["frames"] for r in captured) else 3
        for project in projects:
            source = fetch(project, args.out / "sources") if args.fetch else args.source
            checkout = lay_out(project, source, args.out / "checkouts")
            rows.append(verify(project, checkout, args.out, args.command.split(), args.timeout, args.execution_class))
            print(f"{project['name']}: exit {rows[-1]['exit']} ({rows[-1]['verdict'] or 'no verdict'}) in {rows[-1]['seconds']} s", flush=True)
            for change in project.get("changes", []):
                head = lay_out(project, source, args.out / "checkouts", change)
                rows.append(verify(project, head, args.out, args.command.split(), args.timeout, args.execution_class,
                                   base=checkout, change=change))
                print(f"{project['name']}+{change['name']}: exit {rows[-1]['exit']} ({rows[-1]['verdict'] or 'no verdict'}; "
                      f"expected {change['expect']}) in {rows[-1]['seconds']} s", flush=True)
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
