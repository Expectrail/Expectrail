"""Run `expectrail verify` on Godot projects the team did not write, and write down what happened.

    python -m tools.outside_trial --fetch --out runs/outside        # in CI: fetch at the pinned commits
    python -m tools.outside_trial --source <clone> --out runs/outside   # a clone that is already there

The list is `tests/outside/projects.json`: a repository, a full commit, a folder in it, a licence and
our own routes for it. A project is fetched at its commit and never copied into this repository. For
each one a checkout is laid out (the project as `project/`, our routes, the project's spec or the bundled
spec copied unchanged) and the installed command is run on it as a
stranger would run it. Nothing is approved here and no model is called.

A project may list `changes`: small patches of ours against its folder (`tests/outside/<name>/changes/`),
each with the verdict it should get. For each, the project unchanged is the base and the patched copy
is the head, and `expectrail verify --base` judges the change, as it would judge a pull request. The
row says the expected verdict beside the one given; a declared mismatch fails the trial.

Needs-review and reject are valid results. Declared expectations are regression checks. The trial fails
when a project cannot be fetched at its commit, or when a verification produces no verdict. A
draft-only trial may instead require a specific setup refusal before any job starts, together with
its separate draft diagnostics. Other failures still fail the trial. What it writes
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
DRAFT_REFUSAL = "unapproved-drafts"
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]{0,200}$")


class TrialError(Exception):
    """The list is not usable, or a project could not be fetched as pinned."""


def load_list(path: Path = LIST) -> list[dict]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("format") != FORMAT or not isinstance(doc.get("projects"), list) or not doc["projects"]:
        raise TrialError(f"{path.name}: not a {FORMAT} list with projects")
    from expectrail.contracts import validate, ContractError
    try:
        validate(doc, "outside-projects")
    except ContractError as exc:
        raise TrialError(str(exc)) from exc
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
            if not _plain_path(p[key], root=key == "path"):
                raise TrialError(f"{p['name']}: {key} must be a plain path inside its repository")
        if not p["routes"].startswith("tests/outside/"):
            raise TrialError(f"{p['name']}: routes are ours and live under tests/outside/")
        if "spec" in p:
            project_spec(p)
        if 'config' in p:
            if not p['config'].startswith('tests/outside/'):
                raise TrialError('config must name our file under tests/outside/')
            contained(REPO, p['config'])
        drafts = draft_specs(p)
        expectations = [p] + p.get('changes', [])
        if not drafts and any(item.get('expect') == DRAFT_REFUSAL for item in expectations):
            raise TrialError('an unapproved-drafts expectation requires configured draftSpecs')
        if drafts:
            if 'config' not in p or 'spec' in p:
                raise TrialError('draftSpecs requires a config and cannot also select an approved spec')
            ids = {strict_json(path)['id'] for path in drafts}
            if len(ids) != len(drafts):
                raise TrialError('draft ids must be distinct')
            for expected in expectations:
                if set(expected.get('engineExpect', {})) != ids or 'expect' not in expected:
                    raise TrialError('every draft copy needs a verification outcome and an engine expectation for every draft')
        elif 'engineExpect' in p or any('engineExpect' in c for c in p.get('changes', [])):
            raise TrialError('engineExpect requires draftSpecs')
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
            if c["expect"] != DRAFT_REFUSAL and c["expect"] not in VERDICTS.values():
                raise TrialError(f"{p['name']}/{c['name']}: expect must be one of {', '.join(VERDICTS.values())}")
            folder = f"tests/outside/{p['name']}/changes/"
            if (not _PATH.match(c["patch"]) or ".." in c["patch"].split("/") or not c["patch"].startswith(folder)
                    or not c["patch"].endswith(".patch")):
                raise TrialError(f"{p['name']}/{c['name']}: the patch is ours and lives under {folder}")
    return doc["projects"]


def strict_json(path: Path) -> dict:
    from expectrail.contracts import strict_loads
    return strict_loads(path.read_text(encoding="utf-8"))


def _plain_path(value: str, *, root=False) -> bool:
    return isinstance(value, str) and ((root and value == '.') or bool(
        _PATH.fullmatch(value) and '..' not in value.split('/')))


def contained(root: Path, relative: str, *, directory=False) -> Path:
    """Resolve only a plain path beneath the selected root, never a symlink.

    Refusing even internal symlinks keeps copy/patch/replay interpretation identical.
    Root checkout metadata and import caches are excluded from the copy separately.
    """
    if not _plain_path(relative, root=directory):
        raise TrialError('path must stay inside its checkout')
    root = root.resolve()
    path = root / relative
    if not path.resolve().is_relative_to(root):
        raise TrialError('path points outside its checkout')
    cursor = root
    for part in Path(relative).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise TrialError('symbolic links are not allowed in trial inputs')
    if directory:
        if not path.is_dir():
            raise TrialError('no project.godot: project folder is missing')
        for current, dirs, files in os.walk(path, followlinks=False):
            dirs[:] = [d for d in dirs if d not in ('.git', '.godot')]
            for name in dirs + files:
                if (Path(current) / name).is_symlink():
                    raise TrialError('symbolic links are not allowed in a trial project')
    elif not path.is_file():
        raise TrialError('trial input file is missing: ' + relative)
    return path


def draft_specs(project: dict) -> list[Path]:
    paths = []
    for value in project.get('draftSpecs', []):
        if not isinstance(value, str) or not value.startswith('tests/outside/') or not value.endswith('.json'):
            raise TrialError('draftSpecs must name our JSON checks under tests/outside/')
        path = contained(REPO, value)
        from expectrail.contracts import validate
        doc = strict_json(path)
        validate(doc, 'test-spec')
        if 'approval' in doc:
            raise TrialError('draftSpecs contains an approval; review the registry before changing this trial')
        paths.append(path)
    if len({p.name for p in paths}) != len(paths):
        raise TrialError('draft check filenames must be distinct')
    return paths


def reports_draft_refusal(root: Path, stderr: str, count: int) -> bool:
    # Preflight failures are on stderr even with --json. Check the trusted selection
    # independently of that text, then match the CLI's full explanation for this Before.
    from expectrail import project_job
    try:
        info = project_job.inspect(root)
        if not info['routes'] or info['checks'] or info['drafts'] != count or info['problems']:
            return False
        steps = project_job.unready(root)
    except (ValueError, OSError):
        return False
    return bool(steps) and stderr.strip() == 'expectrail: Nothing here can be verified yet. ' + ' '.join(steps)


def observed_outcome(row: dict) -> str | None:
    if (row.get('setupRefusal') == DRAFT_REFUSAL and row.get('exit') == 5
            and row.get('verifyJobs') == 0 and row.get('expectedEngine')
            and row.get('verdict') is None and 'decision' in row and row['decision'] is None
            and row.get('checks') is None):
        return DRAFT_REFUSAL
    return row.get('verdict')


def expectation_errors(row: dict) -> list[str]:
    errors = []
    outcome = observed_outcome(row)
    if row.get('expect') and outcome != row['expect']:
        errors.append(f"expected {row['expect']}, got {outcome or 'no verdict'}")
    elif not row.get('verdict') and row.get('expect') != DRAFT_REFUSAL:
        errors.append('verification produced no verdict')
    if row.get('expect') and 'decision' in row and row['decision'] != row.get('verdict'):
        errors.append('CLI exit verdict and saved decision disagree or the decision is missing')
    if row.get('draftDiagnosticError'):
        errors.append('draft engine replay failed: ' + row['draftDiagnosticError'])
    for name, expected in row.get('expectedEngine', {}).items():
        found = [f for f in row.get('draftFindings', []) if f['spec'] == name]
        if not found or any(f['result'] != expected for f in found):
            errors.append(f"draft {name}: expected {expected}, got {', '.join(f['result'] for f in found) or 'no finding'}")
    return errors


def draft_diagnostics(project: dict, checkout: Path, into: Path, timeout: int,
                      execution_class: str) -> tuple[list[dict], list[str]]:
    """Separate unapproved engine diagnostics. Never call a gate or vision provider.

    In CI the exact same isolated replay requirement applies. A missing diagnostic
    fails its declared expectation; it is never filled in from an expected value.
    """
    from expectrail.contracts import validate
    from expectrail.evaluator import evaluate
    from expectrail.gate.verify import observations, window_frames
    from expectrail.route import describe
    findings, summaries = [], []
    specs = [strict_json(path) for path in draft_specs(project)]
    sandbox = 'require' if execution_class == 'isolated' else 'auto'
    for route_file in sorted((checkout / 'routes').glob('*.json')):
        route = strict_json(route_file); validate(route, 'route')
        dest = into / route_file.stem
        cmd = [sys.executable, '-m', 'harness.run', '--game', str(checkout / 'project'),
               '--route', str(route_file), '--out', str(dest), '--sandbox', sandbox]
        try:
            proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise TrialError(f'draft replay timed out after {timeout} seconds') from exc
        if proc.returncode:
            raise TrialError(f'draft replay exited {proc.returncode}; inspect its retained godot.log')
        trace = strict_json(dest / 'trace.json'); validate(trace, 'trace')
        if len(trace.get('rows', [])) != route['ticks'] or [r.get('tick') for r in trace['rows']] != list(range(route['ticks'])):
            raise TrialError('draft replay has missing or duplicate ticks')
        sha = hashlib.sha256((dest / 'trace.json').read_bytes()).hexdigest()
        obs = observations(trace, hashlib.sha256((dest / 'replay.json').read_bytes()).hexdigest())
        summaries += [route['name'] + ': ' + s for s in describe(route, trace['physicsTicksPerSecond'], trace)]
        for spec in specs:
            verdict = evaluate(spec, obs, route=route['name'], trace=trace,
                               expected_frames=window_frames(spec, route['ticks'], trace, 60), capture_fps=60)
            frame = verdict['firstFrame']
            around_rows = [] if frame is None else [r for r in trace['rows'] if abs(r.get('frame', -100) - frame) <= 1]
            findings.append({'spec': spec['id'], 'route': route['name'],
                             **{k: verdict[k] for k in ('result', 'reason', 'firstFrame', 'framesJudged', 'coverage')},
                             'traceSha256': sha, 'around': around_rows})
        # Captures are diagnostics, not a source archive. Keep trace/replay/log.
        for folder in ('work', 'frames', 'sandbox'):
            shutil.rmtree(dest / folder, ignore_errors=True)
    return findings, summaries


def project_spec(project: dict) -> Path:
    if "spec" not in project:
        return SPEC
    value = project["spec"]
    if not isinstance(value, str) or not re.fullmatch(r"tests/outside/specs/[a-z0-9][a-z0-9-]*\.json", value):
        raise TrialError(f"{project['name']}: spec must name a file under tests/outside/specs/")
    path = REPO / value
    if path.resolve() != path or not path.is_file():
        raise TrialError(f"{project['name']}: spec must be an existing file without symbolic links")
    return path


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
    sparse.write_text("\n".join(sorted(wanted | {"/*" if project["path"] == "." else project["path"] + "/"})) + "\n", encoding="utf-8")
    git("fetch", "-q", "--depth=1", "--no-tags", "origin", project["commit"], cwd=clone)
    git("checkout", "-q", "--detach", "FETCH_HEAD", cwd=clone)
    if git("rev-parse", "HEAD", cwd=clone) != project["commit"]:
        raise TrialError(f"{project['name']}: the clone is not at the pinned commit")
    return clone


def lay_out(project: dict, source: Path, work: Path, change: dict | None = None) -> Path:
    """A checkout for one project: its folder as `project/`, our routes and its selected spec.
    With ``change``, the checkout is named after it and its patch is applied to `project/`."""
    folder = contained(source, project["path"], directory=True)
    if not (folder / "project.godot").is_file():
        raise TrialError(f"{project['name']}: no project.godot at {project['path']} in the source")
    checkout = work / (project["name"] if change is None else f"{project['name']}+{change['name']}")
    if checkout.exists():
        shutil.rmtree(checkout)
    shutil.copytree(folder, checkout / "project", ignore=shutil.ignore_patterns(".git", ".godot"))
    shutil.copytree(contained(REPO, project["routes"], directory=True), checkout / "routes")
    (checkout / "specs").mkdir()
    drafts = draft_specs(project)
    if drafts:
        for spec in drafts:
            shutil.copy(spec, checkout / 'specs')
    else:
        shutil.copy(project_spec(project), checkout / "specs")
    if 'config' in project:
        if any((checkout / 'project' / name).exists() or (checkout / 'project' / name).is_symlink()
               for name in ('routes', 'checks', 'expectrail.project.json')):
            raise TrialError('config overlay would overwrite a source config, routes or checks; use a distinct layout')
        from expectrail import project_config
        config = strict_json(contained(REPO, project['config']))
        if config.get('draft') is not True:
            raise TrialError('trial config overlay must remain a draft')
        if config.get('routes') != ['routes/' + path.name for path in sorted((checkout / 'routes').glob('*.json'))]:
            raise TrialError('config routes must equal the trial routes')
        if sorted(config.get('approvedContracts', [])) != sorted('checks/' + p.name for p in drafts):
            raise TrialError('config check paths must equal draftSpecs (none are approved here)')
        shutil.copytree(checkout / 'routes', checkout / 'project/routes')
        shutil.copytree(checkout / 'specs', checkout / 'project/checks')
        (checkout / 'project/expectrail.project.json').write_text(json.dumps(config, indent=2) + '\n')
        project_config.validate(config, checkout / 'project')
        if config['captureFps'] != 60:
            raise TrialError('draft engine diagnostics currently require captureFps 60')
    if change is not None:
        # git apply refuses a patch that reaches outside the folder it runs in. It must not find a
        # repository above that folder: inside one (CI lays checkouts out inside this repository)
        # it reads paths from the repository's top and silently skips every file outside the folder
        # it runs in, exits 0 and changes nothing. That happened on the first run (PR #385).
        patch = str(contained(REPO, change["patch"]))
        env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(checkout.resolve())}
        for args, why in ((["apply", "--whitespace=nowarn", patch], "the patch does not apply"),
                          # Proof that it took: the change can be taken back out of the copy.
                          (["apply", "--check", "--reverse", patch], "the patch did not change the copy")):
            done = subprocess.run(["git", *args], cwd=checkout / "project", capture_output=True, text=True,
                                  timeout=60, env=env)
            if done.returncode:
                raise TrialError(f"{project['name']}/{change['name']}: {why}: {done.stderr.strip()[-300:]}")
    contained(checkout, "project", directory=True)  # patched copies obey the same no-link boundary
    return checkout


def verify(project: dict, checkout: Path, out: Path, command: list[str], timeout: int,
           execution_class: str = "diagnostic", base: Path | None = None, change: dict | None = None) -> dict:
    jobs = out / "jobs" / (project["name"] if change is None else f"{project['name']}+{change['name']}")
    started = time.monotonic()
    try:
        selection = (["--project", str(checkout / "project")] if 'config' in project else
                     ["--head", str(checkout), "--game", "project", "--routes", "routes/*.json", "--specs", "specs"])
        base_path = base / 'project' if base is not None and 'config' in project else base
        done = subprocess.run([*command, "--jobs-root", str(jobs), "verify", *selection,
                               "--execution-class", execution_class,
                               "--json", *(["--base", str(base_path)] if base_path is not None else [])],
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
           "expect": project.get("expect") if change is None else change["expect"]}
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
    # A check that could not be decided names the first frame where an object was not found; the
    # engine's log around it is what a person (or a check written for the game) has to judge.
    # The finding's own reason carries it ("<spec> on <route>: ..."), not the decision's reasons: the
    # first version read only the decision's and printed nothing on the run it was written for (#393).
    for reason in row["reasons"] + row["failures"]:
        unseen = UNSEEN.search(reason)
        if unseen and len(row["around"]) < 3:
            row["around"].append(around(jobs, {"spec": unseen["spec"], "route": unseen["route"],
                                                "frame": int(unseen["frame"])}, after=6))
    expected = project if change is None else change
    if project.get('draftSpecs'):
        row['expectedEngine'] = expected['engineExpect']
        # JobStore creates jobs/<id> before writing status. Count even a partial job, and
        # fail closed if a reused output directory contains evidence from an earlier run.
        job_entries = jobs / 'jobs'
        row['verifyJobs'] = sum(1 for _ in job_entries.iterdir()) if job_entries.exists() else 0
        if code == 5 and not stdout.strip() and reports_draft_refusal((base or checkout) / 'project', stderr, len(project['draftSpecs'])):
            row['setupRefusal'] = DRAFT_REFUSAL
        try:
            row['draftFindings'], row['routeSummaries'] = draft_diagnostics(
                project, checkout, jobs / 'draft-diagnostics', timeout, execution_class)
        except (TrialError, OSError, ValueError) as exc:
            row['draftFindings'] = []
            row['draftDiagnosticError'] = str(exc)
    row['expectationErrors'] = expectation_errors(row)
    row['verifySeconds'] = seconds
    row['seconds'] = round(time.monotonic() - started, 1)
    return row


# "player-stays-above-ground on walk: no violation in 115 frames judged, but an object was not found
# in 5 frames (first 38); ..." (expectrail.evaluator)
UNSEEN = re.compile(r"(?P<spec>[A-Za-z0-9._-]+) on (?P<route>[A-Za-z0-9._-]+): .*?not found in \d+ frames? \(first (?P<frame>\d+)\)")


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
                        "groundFrom": r.get("groundFrom"), "body": r.get("body"),
                        "onFloor": r.get("onFloor"), "view": r.get("view")}
                       for r in rows[max(0, tick - before * step):tick + after * step + 1:step]]
        out["first"] = {k: rows[0].get(k) for k in ("player", "ground", "onFloor")} if rows else None
        break
    return out


def markdown(rows: list[dict]) -> str:
    from expectrail.contracts import validate
    validate({"format": "expectrail.outside-trial/v0", "projects": rows}, "outside-trial")
    lines = ["| Project | Change | Exit | Verdict | Expected | Seconds | Checks | Reasons |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        checks = "none" if not r["checks"] else f"{r['checks'].get('passed')} of {r['checks'].get('checks')} pass"
        reasons = "; ".join((r["reasons"] or r.get("diagnostics") or [r.get("output", "")]) + r.get("failures", [])) or "none"
        if 'verifyJobs' in r:
            reasons += f" ({r['verifyJobs']} verification jobs)"
        change = "none (the project as pinned)" if not r.get("change") else f"{r['change']}: {r['what']}"
        expected = "-" if not r.get("expect") else (r["expect"] + (" (as expected)" if observed_outcome(r) == r["expect"] else " (DIFFERS)"))
        lines.append(f"| {r['name']} (`{r['commit'][:7]}`, {r['licence']}) | {change.replace('|', '/')} | {r['exit']} | "
                     f"{r['verdict'] or 'no verdict'} | {expected} | {r['seconds']} | {checks} | {reasons.replace('|', '/')} |")
    for r in rows:
        if r.get('draftFindings'):
            lines += ['', f"Draft engine diagnostics for {r['name']} / {r.get('change') or 'pinned'} (unapproved; do not change the gate verdict):", '']
            for f in r['draftFindings']:
                lines.append(f"- {f['spec']} on {f['route']}: {f['result']}; {f['reason']}; first checked failure {f['firstFrame']}.")
        lines += ['- ' + s for s in r.get('routeSummaries', [])]
        lines += ['- EXPECTATION FAILED: ' + s for s in r.get('expectationErrors', [])]
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
    from expectrail.contracts import validate
    validate({"format": "expectrail.outside-trial/v0", "projects": rows}, "outside-trial")
    (args.out / "outside-trial.json").write_text(json.dumps({"format": "expectrail.outside-trial/v0", "projects": rows}, indent=2) + "\n", encoding="utf-8")
    table = markdown(rows)
    (args.out / "outside-trial.md").write_text(table, encoding="utf-8")
    print(table)
    return 0 if all(not expectation_errors(r) for r in rows) else 3


if __name__ == "__main__":
    sys.exit(main())
