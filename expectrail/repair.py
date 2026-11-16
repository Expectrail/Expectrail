"""Propose fixes for a completed reject. Only a fresh verify job can accept a patch."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import glob
import shutil
import subprocess
import sys
import tempfile

from harness import adapters, tree
from expectrail import contracts
from expectrail.diagnostics import redact
from expectrail.gate import record, verify
from expectrail.orchestrator import request, runner, store
from expectrail.orchestrator.cli import JOBS_ROOT_HELP, Parser, UsageError

CHANGED = "the checkout changed since the job; verify again"


def _public_failures(findings, specs):
    sentences = {s["id"]: s["instruction"] for s in specs}
    return [{"spec": {"id": f["spec"], "instruction": sentences[f["spec"]]},
             "verdict": {"result": "fail", "reason": redact(f["reason"]), "firstFrame": f["frame"]},
             "route": {"name": f["route"]}}
            for f in findings["findings"] if f["after"] == "fail" and f["spec"] in sentences]


def _editable(game, excluded):
    """Game-relative globs. Split a folder only where it also contains verifier inputs."""
    def walk(folder):
        for path in sorted(folder.iterdir()):
            name = path.relative_to(game)
            if name in excluded:
                continue
            if path.is_dir() and any(name in item.parents for item in excluded):
                yield from walk(path)
            else:
                yield glob.escape(name.as_posix()) + ("/**" if path.is_dir() else "")

    return list(walk(game))


def _live_budget():
    if not os.environ.get("EXPECTRAIL_MUSE_USD_CAP", "").strip():
        raise ValueError("set EXPECTRAIL_MUSE_USD_CAP before running the live fixer")
    try:
        from expectrail import spend
    except ImportError:
        raise ValueError("live repair requires the Muse spend meter from #436") from None
    try:
        return spend.require_cap("muse"), spend.BudgetStop
    except spend.BudgetStop as exc:
        raise ValueError(str(exc)) from exc


def _child(jobs, original, checkout, inputs, *, require_isolation, spawn_worker):
    req = request.build(**{k: v for k, v in original["project"].items() if k != "visual"},
                        head=checkout, base=Path(original["head"]["checkout"]),
                        base_commit=original["head"]["commit"],
                        execution_class="isolated" if require_isolation else original["executionClass"],
                        timeout_seconds=original["limits"]["timeoutSeconds"], intent="fix")
    if "visual" in original["project"]:
        req["project"]["visual"] = original["project"]["visual"]
    child, _ = jobs.create(req)
    if child["inputs"]["baseTree"] != inputs["headTree"] or child["inputs"]["policyDigest"] != inputs["policyDigest"]:
        jobs.cancel(child["id"])
        raise ValueError(CHANGED)
    return runner.wait(jobs, child["id"], spawn_worker(jobs, child["id"]))


def repair(jobs, job, *, attempts=3, fixture=None, recorded=False, spawn_worker=None):
    from agents import fixer

    if recorded and fixture is None:
        raise ValueError("a recorded repair needs its saved patch")
    if type(attempts) is not int or not 1 <= attempts <= 10:
        raise ValueError("attempts must be between 1 and 10")
    parent = jobs.status(job)
    if (parent["phase"], parent["decision"]) != ("completed", "reject"):
        raise ValueError("repair needs a completed verify job whose decision is reject")
    original = jobs.request(job)
    project, inputs = original["project"], parent["inputs"]
    head = Path(original["head"]["checkout"])
    game = head / project["game"]
    adapter = adapters.get(project["adapter"])
    try:
        current = request.tree_digest(game, head, adapter.name)
    except (OSError, tree.TreeProblem):
        current = None
    if current is None or current != inputs["headTree"]:
        raise ValueError(CHANGED)
    checks = verify.read_checks(head, project["specs"], project["routes"])
    if checks.digest != inputs["policyDigest"] or checks.problems:
        raise ValueError("the head's checks or routes differ from the verified policy; verify again")
    paths = jobs.paths(job)
    findings = record.read_record(paths.output / "findings.json")
    if findings["decision"] != "reject" or findings["game"]["headTree"] != inputs["headTree"]:
        raise ValueError("the findings do not match the rejected job")
    if findings["heldOut"]["status"] != "not-used":
        raise ValueError("this job used held-out routes that a public verify request cannot reproduce")
    failing = _public_failures(findings, checks.specs)
    if not 1 <= len(failing) <= 64:
        raise ValueError("repair needs between 1 and 64 public failing checks")
    if fixture is not None:
        fixture = Path(fixture)
    cap, budget_stop = _live_budget() if fixture is None else (None, ())
    if fixture is not None and not Path(fixture).is_file():
        raise ValueError("the fixture patch is missing")
    rr = {"format": "expectrail.repair-request/v0", "id": job, "base": {"tree": inputs["headTree"]},
          "failing": failing, "budget": {"attempts": attempts}}
    folder = Path(tempfile.mkdtemp(prefix="repair-", dir=paths.root))
    source = ("recorded" if recorded else "fixture") if fixture is not None else "muse"
    doc = {"format": "expectrail.repair-run/v1",
           "parent": {"job": job, "decision": "reject", "headTree": inputs["headTree"],
                      "failing": [{"spec": f["spec"]["id"], "route": f["route"]["name"]} for f in failing]},
           "fixer": {"source": source, "sandboxed": fixture is None},
           "budget": {"attempts": attempts, "usdCap": cap}, "startedAt": store.stamp(), "attempts": [],
           "machineWritten": True, "review": contracts.schema_v1("repair-run")["properties"]["review"]["enum"][0],
           "result": {"decision": "needs-review", "job": None, "patch": None}}
    stop, detail = "attempts-exhausted", "every candidate was rejected"
    prior = None
    with tempfile.TemporaryDirectory(prefix="repair-work-", dir=folder) as tmp:
        snapshot = Path(tmp) / "game"
        # The fixer receives only the game's own files. An external target of a game link is refused.
        if not game.resolve().is_relative_to(head.resolve()):
            raise ValueError(CHANGED)
        if tree.copy(game, snapshot, within=game, skip=tuple(adapter.ignore)) != inputs["headTree"]:
            raise ValueError(CHANGED)
        # Projects may keep their approved specs and routes inside the game itself.
        # The verifier gets the original files. The fixer sees only the failing sentences.
        workspace = Path(tmp) / "fixer-input"
        shutil.copytree(snapshot, workspace)
        excluded = set()
        for name in checks.spec_entries.keys() | checks.route_entries.keys():
            policy_path = head / name
            if policy_path.is_relative_to(game):
                excluded.add(policy_path.relative_to(game))
        for name in excluded:
            (workspace / name).unlink()
        # Recordings and other verifier documents can also be stored outside the configured
        # policy folder. Keep those files out of every fixer workspace, including offline fixtures.
        for file in workspace.rglob("*"):
            if not file.is_file():
                continue
            if file.name in (".env", ".expectrail-signing-key") or file.name.startswith(".env."):
                excluded.add(file.relative_to(workspace))
                file.unlink()
            elif file.suffix.lower() == ".json":
                try:
                    item = record.read_json(file, cap=16 * 1024 * 1024, label="game JSON")
                except record.RecordError:
                    # Opaque data cannot be identified as safe input for the fixer. The verifier
                    # still receives the untouched file as part of the original game snapshot.
                    item = None
                if item is None or (isinstance(item, dict) and str(item.get("format", "")).startswith("expectrail.")):
                    excluded.add(file.relative_to(workspace))
                    file.unlink()
        rr.update(base={"tree": adapter.tree_digest(workspace)}, editable=_editable(snapshot, excluded))
        contracts.validate(rr, "repair-request")
        for n in range(1, attempts + 1):
            attempt = folder / f"attempt-{n}"
            attempt.mkdir()
            row = {"n": n, "patch": None, "patchSha256": None, "job": None, "decision": None, "reasons": []}
            doc["attempts"].append(row)
            try:
                output = Path(tmp) / str(n)
                meta = fixer.run_fixer(rr, output, game=workspace, attempt=n, allow_empty=True,
                                       require_sandbox=True, candidate_patch=fixture, prior_reject=prior,
                                       adapter=adapter, agent="muse-code", provider_only=True)
                if not meta["ok"]:
                    stop, detail = "fixer-failed", "the fixer produced no patch"
                    break
                patch = attempt / "candidate.patch"
                data = record.read_bytes_capped(output / patch.name, label="candidate patch")
                sha = hashlib.sha256(data).hexdigest()
                if not data.strip() or sha != meta["patchSha256"]:
                    raise ValueError("the candidate patch is empty or its digest changed")
                patch.write_bytes(data)
                row.update(patch=str(patch.relative_to(folder)), patchSha256=sha)
                checkout = attempt / "checkout"
                fixed = checkout / project["game"]
                shutil.copytree(snapshot, fixed)
                from agents.patchutil import apply_patch
                apply_patch(fixed, patch)
                # Keep policy files in the candidate checkout for reproduction, outside the fixer workspace.
                for name in checks.spec_entries.keys() | checks.route_entries.keys():
                    target = checkout / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists():
                        shutil.copyfile(head / name, target)
                if any((fixed / name).read_bytes() != (snapshot / name).read_bytes() for name in excluded):
                    raise ValueError("the patch changes a verifier input")
                child = _child(jobs, original, checkout, inputs, require_isolation=fixture is None,
                               spawn_worker=spawn_worker or runner.spawn)
                row.update(job=child["id"], decision=child["decision"], reasons=[redact(s) for s in child["reasons"][:32]])
                row['gateDecision'] = child['decision']
                # Only verifier-owned output is read, never a path or flag supplied by the report.
                flags = candidate_flags(jobs.paths(child['id']).output, child['inputs']['headTree'])
                if flags:
                    row.update(decision='needs-review', advisoryDiscovery=flags,
                               reasons=[('advisory-discovery: ' + flag)[:600] for flag in flags][:32])
                    stop, detail = 'needs-review', 'advisory-discovery: ' + ', '.join(flags)
                    detail = detail[:600]
                    break
                if child["phase"] != "completed" or child["decision"] == "needs-review":
                    stop = "cancelled" if child["phase"] == "cancelled" else "needs-review"
                    detail = f"fresh verify job {child['id']}: {child['decision'] or child['phase']}"
                    break
                child_record = record.read_record(jobs.paths(child["id"]).output / "findings.json")
                if child_record["decision"] != child["decision"] or child_record.get("intent") != "fix":
                    raise ValueError("the child job and its repair evidence disagree")
                if child["decision"] == "accept":
                    if record.rule_of(child_record) != "both" or not child_record["repair"]["demonstrated"]:
                        stop, detail = "needs-review", "the child verification did not demonstrate a two-observer repair"
                        break
                    doc["result"] = {"decision": "accept", "patch": row["patch"], "job": row["job"]}
                    stop, detail = "accepted", f"a fresh verify job accepted attempt {n}"
                    break
                prior = {"attempt": n, "decision": "reject",
                         "failing": _public_failures(child_record, checks.specs)}
            except budget_stop as exc:
                stop, detail = "spend-cap", redact(str(exc))
                row['reasons'] = [detail]
                row['budgetStop'] = getattr(exc, 'code', 'spend-cap')
                source = getattr(exc, 'invocation_record', None)
                if source is not None:
                    from expectrail.fixer_budget import read
                    try:
                        read(source)  # A corrupt counter is no budget proof.
                        target = attempt / 'fixer-invocation.json'
                        shutil.copyfile(source, target)
                        row['fixerInvocation'] = target.relative_to(folder).as_posix()
                    except (OSError, ValueError):
                        row['budgetStop'] = 'fixer-meter-unavailable'
                        row['reasons'] = ['fixer-meter-unavailable: invocation counter could not be preserved']
                break
            except (SystemExit, OSError, ValueError, RuntimeError, subprocess.SubprocessError, store.StoreError) as exc:
                stop, detail = "fixer-failed" if row["patch"] is None else "needs-review", redact(str(exc))
                row["reasons"] = [detail]
                if row["decision"] is not None and stop == "needs-review":
                    row["decision"] = "needs-review"
                break
    doc.update(stop={"reason": stop, "detail": detail}, finishedAt=store.stamp())
    if doc["result"]["decision"] != "accept":
        doc["review"] = contracts.schema_v1("repair-run")["properties"]["review"]["enum"][1]
    return write_run(folder, doc)


def candidate_flags(output, head_tree):
    """Read an existing discovery-run from the trusted candidate verification output.

    Discovery runs are optional. A finding on the candidate vetoes automatic repair success;
    its contents are never copied to a repair request or a retry. No discovery is started here.
    """
    output = Path(output)
    flags = set()
    findings = output / 'findings.json'
    if findings.exists():
        judged = record.read_record(findings)
        if judged['game']['headTree'] != head_tree:
            raise ValueError('candidate findings do not name the verified candidate tree')
        flags.update(c['specId'] for c in judged.get('generatedChecks', {}).get('catches', []))
    path = output / 'discovery-run.json'
    if not path.exists():
        return sorted(flags)
    doc = record.read_json(path, label='candidate discovery')
    contracts.validate_v1(doc, 'discovery-run')
    candidates = {s['name'] for s in doc['snapshots'] if s['treeSha256'] == head_tree}
    if not candidates:
        raise ValueError('candidate discovery does not name the verified candidate tree')
    flags.update(f['id'] for f in doc['findings'] if f['snapshot'] in candidates)
    return sorted(flags)


def write_run(folder, doc):
    """Shared writer, also used for an opted-in ingest that cannot start a repair."""
    contracts.validate_v1(doc, 'repair-run')
    target = Path(folder) / 'repair-run.json'
    staging = target.with_suffix('.tmp')
    staging.write_bytes(contracts.canonical_v1(doc) + b'\n')
    staging.replace(target)
    return target, doc



def main(argv):
    p = Parser(prog="expectrail repair", description=__doc__)
    p.add_argument("job", metavar="JOB")
    p.add_argument("--jobs-root", help=JOBS_ROOT_HELP)
    p.add_argument("--attempts", type=int, default=3, help="maximum candidates, 1 to 10 (default 3)")
    p.add_argument("--fixture", type=Path, metavar="PATCH", help="use a fixed patch without starting Muse")
    try:
        args = p.parse_args(argv)
        jobs = store.JobStore(Path(args.jobs_root or os.environ.get("EXPECTRAIL_JOBS") or "runs/jobs"))
        path, doc = repair(jobs, args.job, attempts=args.attempts, fixture=args.fixture)
    except (UsageError, OSError, ValueError, store.StoreError) as exc:
        print(f"repair: {exc}", file=sys.stderr)
        return 5
    except ModuleNotFoundError as exc:
        if exc.name != "jsonschema":
            raise
        print("repair needs the contracts extra: install 'expectrail[contracts]'", file=sys.stderr)
        return 5
    print(f'{doc["result"]["decision"]}: {doc["stop"]["detail"]}\nRepair record: {path}')
    if doc["result"]["patch"]:
        print(f'Patch: {path.parent / doc["result"]["patch"]}\n{doc["review"]}')
    return 0 if doc["result"]["decision"] == "accept" else 2
