"""The CI gate on the known-bugs bench, judged as a change of no stated intent and as a declared fix (#284).

The known-bugs bench (``bench/jit/known/cases.json``) has the four reported bugs, each with a wrong fix
(one comment claiming the fix, nothing else) and the correct fix (the exact undo). For each of the eight
cases this runs the gate as blind set 3's arm A did (``expectrail.jit.blind``): the bug build as the base,
the bug build plus the candidate as the head, the repository's own routes and approved specs, the
engine's record only. It runs the gate twice per case, once with intent ``none`` (today's rule) and once
with intent ``fix`` (a fix is accepted only when a check failed on the base and passes on the head three
times of three, ``expectrail.gate.record.decide``), and records both decisions side by side.

No model is asked anything and nothing is generated: this is the approved checks alone, the "before"
and "after" of the repair rule. Generated checks reach the rule only under #271.

The record (``expectrail.gate-known-bench/v1``, ``bench/jit/known/gate.json``) keeps per case and intent
the decision, the first reason, how many checks ran, how many failed before the change, and how many
repairs were demonstrated. The reader recomputes the totals from the rows and refuses a record whose
totals, or whose decisions, do not follow from them.

    python3 -m expectrail.gate.known_bench run --out bench/jit/known/gate.json --markdown bench/jit/known/gate.md
    python3 -m expectrail.gate.known_bench show
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from expectrail.contracts import ContractError, strict_loads

REPO = Path(__file__).resolve().parents[2]
CASES = REPO / "bench" / "jit" / "known" / "cases.json"
RECORD = REPO / "bench" / "jit" / "known" / "gate.json"
SCHEMA = REPO / "contracts" / "gate-known-bench.v1.schema.json"
FORMAT = "expectrail.gate-known-bench/v1"
GAME = "game/platformer"
ROUTES = ["harness/routes/smoke.json", "harness/routes/combat.json"]   # blind set 3's arm A
SPECS = "agents/specs"
INTENTS = ("none", "fix")
LABELS = ("wrong", "correct")
DECISIONS = ("accept", "reject", "needs-review")
NOT_DEMONSTRATED = "repair-not-demonstrated"
MAX_BYTES = 256 * 1024
MAX_REASON = 300


class BenchError(ValueError):
    """The bench cannot be run, or its record cannot be used."""


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sha_files(root: Path, rels: list[str]) -> str:
    h = hashlib.sha256()
    for rel in sorted(rels):
        h.update(rel.encode("utf-8") + b"\0" + _sha(root / rel).encode("ascii") + b"\n")
    return h.hexdigest()


def spec_files(root: Path = REPO) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in (root / SPECS).glob("*.json"))


def load_cases(path: Path = CASES) -> list[dict]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return doc["cases"]


# --- one case --------------------------------------------------------------------------------------------
def _patch(game: Path, patch: Path) -> None:
    subprocess.run(["patch", "-p1", "--forward", "--batch", "--silent", "-d", str(game), "-i", str(Path(patch).resolve())],
                   check=True, capture_output=True)


def build_tree(dest: Path, patches: list[Path], root: Path = REPO) -> Path:
    """A checkout holding the game with ``patches`` applied, the routes and the approved specs."""
    shutil.copytree(root / GAME, dest / GAME, ignore=shutil.ignore_patterns(".godot"))
    for p in patches:
        _patch(dest / GAME, p)
    for r in ROUTES:
        (dest / r).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / r, dest / r)
    shutil.copytree(root / SPECS, dest / SPECS)
    return dest


def summarize(findings: dict) -> dict:
    """What the bench keeps of one findings record."""
    checks = findings.get("checks") or []
    reasons = findings.get("reasons") or []
    return {"decision": findings["decision"],
            "firstReason": (reasons[0] if reasons else "")[:MAX_REASON],
            "checks": len(checks),
            "failedBefore": sum(1 for c in checks if c.get("before") == "fail"),
            "repairsDemonstrated": int((findings.get("repair") or {}).get("demonstrated") or 0)}


def run_case(case: dict, work: Path, *, root: Path = REPO, run_gate=None) -> dict:
    """One bench row: the gate on this case with each intent."""
    if run_gate is None:
        from expectrail.gate.verify import run_gate
    work = Path(work)
    base = build_tree(work / "base", [root / case["base"]], root)
    head = build_tree(work / "head", [root / case["base"], root / case["candidate"]], root)
    row = {"case": case["case"], "bug": case["bug"], "label": case["label"], "tunedOn": bool(case.get("tunedOn")),
           "baseSha256": _sha(root / case["base"]), "candidateSha256": _sha(root / case["candidate"])}
    for intent in INTENTS:
        findings = run_gate(repo=head, game=GAME, routes=ROUTES, specs=SPECS, out=work / f"gate-{intent}",
                            work=work / f"gate-work-{intent}", base=base, intent=intent)
        row[intent] = summarize(findings)
    return row


def _run_case_job(args) -> dict:
    case, work = args
    return run_case(case, Path(work))


# --- the record ------------------------------------------------------------------------------------------
def totals(rows: list[dict]) -> dict:
    out = {i: {lab: {d: 0 for d in DECISIONS} for lab in LABELS} for i in INTENTS}
    for r in rows:
        for i in INTENTS:
            out[i][r["label"]][r[i]["decision"]] += 1
    out["wrongAcceptToNeedsReview"] = sum(1 for r in rows if r["label"] == "wrong"
                                          and r["none"]["decision"] == "accept" and r["fix"]["decision"] == "needs-review")
    out["correctAcceptToNeedsReview"] = sum(1 for r in rows if r["label"] == "correct"
                                            and r["none"]["decision"] == "accept" and r["fix"]["decision"] == "needs-review")
    return out


def make_record(rows: list[dict], *, engine: str, root: Path = REPO, cases_path: Path = CASES) -> dict:
    return {"format": FORMAT, "casesSha256": _sha(cases_path), "engine": engine, "rule": "engine-only",
            "routes": list(ROUTES), "specs": spec_files(root), "specsSha256": _sha_files(root, spec_files(root)),
            "rows": rows, "totals": totals(rows)}


def problems(record) -> list[str]:
    """What is wrong with a record: the schema first, then what must agree inside it."""
    import jsonschema

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(record), key=lambda e: list(e.path))
    if errors:
        return [f"gate-known-bench: {'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}"[:300]
                for e in errors[:10]]
    out = []
    names = [r["case"] for r in record["rows"]]
    if len(set(names)) != len(names):
        out.append("gate-known-bench: a case is listed twice")
    for r in record["rows"]:
        for i in INTENTS:
            s = r[i]
            if s["failedBefore"] > s["checks"] or s["repairsDemonstrated"] > s["checks"]:
                out.append(f"gate-known-bench: {r['case']} ({i}): the check counts do not agree")
        fix, none = r["fix"], r["none"]
        # A declared fix is never easier to accept than no declaration (decide), and with no repair
        # demonstrated it is never accepted, and its first reason names why.
        if fix["decision"] == "accept" and (fix["repairsDemonstrated"] == 0 or none["decision"] != "accept"):
            out.append(f"gate-known-bench: {r['case']}: a fix is accepted without a demonstrated repair or "
                       "where no intent was not")
        if fix["repairsDemonstrated"] == 0 and fix["decision"] != "reject" and not fix["firstReason"].startswith(NOT_DEMONSTRATED):
            out.append(f"gate-known-bench: {r['case']}: a fix with no repair demonstrated does not lead with "
                       f"{NOT_DEMONSTRATED}")
        if none["repairsDemonstrated"] != 0:
            out.append(f"gate-known-bench: {r['case']}: intent none records a repair")
    if record["totals"] != totals(record["rows"]):
        out.append("gate-known-bench: the totals do not match the rows")
    return out


def load(path: Path = RECORD) -> dict:
    raw = Path(path).read_bytes()
    if len(raw) > MAX_BYTES:
        raise BenchError(f"gate-known-bench: over {MAX_BYTES} bytes")
    try:
        record = strict_loads(raw.decode("utf-8"))
    except (ValueError, ContractError) as exc:
        raise BenchError(f"gate-known-bench: unreadable: {exc}"[:300]) from exc
    found = problems(record)
    if found:
        raise BenchError("; ".join(found))
    return record


def stale(record: dict, root: Path = REPO, cases_path: Path = CASES) -> list[str]:
    """Why the record no longer describes the bench: [] when the cases, patches, routes and specs are those it ran."""
    out = []
    if record["casesSha256"] != _sha(cases_path):
        out.append("the cases file changed")
    by_name = {c["case"]: c for c in load_cases(cases_path)}
    if set(by_name) != {r["case"] for r in record["rows"]}:
        out.append("the cases are not the ones measured")
    for r in record["rows"]:
        c = by_name.get(r["case"])
        if c and (_sha(root / c["base"]) != r["baseSha256"] or _sha(root / c["candidate"]) != r["candidateSha256"]):
            out.append(f"{r['case']}: a patch changed")
    if record["routes"] != ROUTES:
        out.append("the routes are not the gate's")
    if record["specs"] != spec_files(root) or record["specsSha256"] != _sha_files(root, spec_files(root)):
        out.append("the approved specs changed")
    return out


def render(record: dict) -> str:
    t = record["totals"]

    def cell(intent: str, label: str) -> str:
        return ", ".join(f"{t[intent][label][d]} {d}" for d in DECISIONS if t[intent][label][d]) or "none"

    n = {lab: sum(1 for r in record["rows"] if r["label"] == lab) for lab in LABELS}
    lines = [
        "# The gate on the known-bugs bench: before and after the repair rule (#284)",
        "",
        f"Written by `python3 -m expectrail.gate.known_bench run` ({record['engine']}, engine's record only, no model). "
        "Each case is the bug build as the base and the bug build plus the candidate as the head, on the gate's own "
        f"routes ({', '.join('`' + r + '`' for r in record['routes'])}) and approved specs "
        f"({', '.join('`' + s + '`' for s in record['specs'])}), judged once with no stated intent (today's rule) "
        "and once declared as a fix (accepted only when a check fails on the base and passes on the head, "
        "three times of three).",
        "",
        "| Candidates | No stated intent | Declared a fix |",
        "| --- | --- | --- |",
        f"| {n['wrong']} wrong fixes | {cell('none', 'wrong')} | {cell('fix', 'wrong')} |",
        f"| {n['correct']} correct fixes | {cell('none', 'correct')} | {cell('fix', 'correct')} |",
        "",
        f"Wrong fixes that went from accept to needs-review: {t['wrongAcceptToNeedsReview']} of {n['wrong']}. "
        f"Correct fixes that went from accept to needs-review: {t['correctAcceptToNeedsReview']} of {n['correct']}.",
        "",
    ]
    if not any(r["none"]["failedBefore"] or r["fix"]["failedBefore"] for r in record["rows"]):
        lines += ["No approved check failed on any bug build, so nothing here can demonstrate a repair: a declared fix, "
                  "correct or wrong, is needs-review. A correct fix is accepted as a fix only once a check that "
                  "reproduces its bug exists: a person's approved check, or a generated check allowed to count (#285, #271).",
                  ""]
    lines += [
        "| Case | Label | Checks | Failed before | No stated intent | Declared a fix |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in record["rows"]:
        lines.append(f"| `{r['case']}`{' (tuned on)' if r['tunedOn'] else ''} | {r['label']} | {r['fix']['checks']} | "
                     f"{r['fix']['failedBefore']} | {r['none']['decision']} | {r['fix']['decision']} |")
    lines += ["", "The first reason the gate gave each declared fix:", ""]
    by_reason: dict[str, list[str]] = {}
    for r in record["rows"]:
        by_reason.setdefault(r["fix"]["firstReason"] or "(none)", []).append(r["case"])
    for reason, names in by_reason.items():
        lines.append(f"- {len(names)} of {len(record['rows'])} ({', '.join('`' + n + '`' for n in names)}): {reason}")
    lines.append("")
    return "\n".join(lines)


# --- command ---------------------------------------------------------------------------------------------
def _engine() -> str:
    from harness.run import GODOT_VERSION
    return f"Godot {GODOT_VERSION}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m expectrail.gate.known_bench", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the gate on every case, with each intent, and write the record")
    r.add_argument("--out", type=Path, default=RECORD)
    r.add_argument("--markdown", type=Path, default=None)
    r.add_argument("--work", type=Path, default=None, help="where the trees and replays go (default: a temporary folder)")
    r.add_argument("--jobs", type=int, default=1)
    s = sub.add_parser("show", help="check a record and print it as Markdown")
    s.add_argument("record", type=Path, nargs="?", default=RECORD)
    args = ap.parse_args(argv)
    if args.cmd == "show":
        try:
            record = load(args.record)
        except BenchError as exc:
            print(exc, file=sys.stderr)
            return 1
        sys.stdout.write(render(record))
        for line in stale(record):
            print(f"stale: {line}", file=sys.stderr)
        return 0
    cases = load_cases()
    work = args.work or Path(tempfile.mkdtemp(prefix="expectrail-known-gate-"))
    jobs = [(c, str(work / c["case"])) for c in cases]
    if args.jobs > 1:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            rows = list(pool.map(_run_case_job, jobs))
    else:
        rows = [_run_case_job(j) for j in jobs]
    record = make_record(rows, engine=_engine())
    found = problems(record)
    if found:
        print("; ".join(found), file=sys.stderr)
        return 1
    args.out.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.write_text(render(record), encoding="utf-8")
    sys.stdout.write(render(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
