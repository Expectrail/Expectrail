"""Blind set 3: approved checks alone (arm A) against approved plus generated checks (arm B), on fixes
nobody on the team has seen. The rules are bench/jit/blind-3/preregistration.json, signed off first.

    python -m expectrail.jit.blind verify --set heldout-set           # pins, digest; prints the entry ids
    python -m expectrail.jit.blind entry --set heldout-set --id h01 --out runs/blind/h01
    python -m expectrail.jit.blind score --rows runs/rows --out runs/blind-score

Candidates, per entry of fresh-3:

- **primary**: a defect's own wrong fix (label wrong) and correct fix (label correct), each on top of
  the defect; an intentional change on the clean game, with no base (label correct).
- **supplementary**: per defect, made here, mechanically, by code written before anyone read the set:
  one comment line claiming the fix (label wrong) and the exact undo of the defect (label correct).

Arm A is the CI gate (expectrail.gate.verify.run_gate) with the defect build as base and the defect
plus the candidate as head, on the repository's own routes and approved specs: a reject is a catch.
Arm B is arm A, or a strong catch from the generated checks (measure, propose, replay, one revision,
replay; the same steps as jit.yml). The model reads the entry's description and howItShows and the
candidate's patch, nothing else. Godot runs with the harness's whitelisted environment, so the set's
patched game never sees the model key.

Nothing about a check, a probe, a patch or a description is printed or written to a public file:
the entry command writes one public row per candidate (opaque id, source, label, each arm's outcome,
spend) and keeps everything else under ``--out``, which the workflow never uploads or prints.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PREREG = REPO / "bench" / "jit" / "blind-3" / "preregistration.json"
SET_DIR = "fresh-3"
GAME = REPO / "game" / "platformer"
ROUTES = ["harness/routes/smoke.json", "harness/routes/combat.json"]
SPECS = "agents/specs"
PINNED = ["expectrail/**/*.py", "agents/observations.py", "agents/specs/*.json", "harness/*.py", "harness/*.sh",
          "harness/routes/*.json", "contracts/*.json", "discovery/platformer.profile.json",
          ".github/workflows/jit-blind.yml"]
ENTRY_ID = re.compile(r"h[0-9]{2}")
COMMENT_MARK = {".gd": "#", ".tscn": ";", ".tres": ";", ".godot": ";", ".cfg": ";", ".gdshader": "//",
                ".shader": "//"}


def pins(root: Path = REPO) -> dict[str, str]:
    from expectrail.jit import bench

    out: dict[str, str] = {}
    for pattern in PINNED:
        for p in sorted(root.glob(pattern)):
            if p.is_file() and "__pycache__" not in p.parts:
                out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    out["game/platformer/**"] = bench.pins(root)["game/platformer/**"]
    return out


def check_registration(prereg: dict, root: Path = REPO) -> list[str]:
    problems = []
    if prereg.get("status") != "registered" or not prereg.get("signedOffBy"):
        problems.append("the registration is not signed off")
    pinned, now = prereg.get("pins") or {}, pins(root)
    if not pinned:
        problems.append("the registration pins no files")
    problems += [f"pin moved: {p}" for p in sorted(set(pinned) | set(now)) if pinned.get(p) != now.get(p)]
    return problems


def set_digest(set_root: Path) -> str:
    from expectrail.discovery.fresh import digest

    return digest(Path(set_root) / SET_DIR)


def entries(set_root: Path) -> list[dict]:
    """The manifest's entries, checked for the shape this run relies on; never printed."""
    doc = json.loads((Path(set_root) / SET_DIR / "manifest.json").read_text(encoding="utf-8"))
    out = []
    for e in doc["entries"]:
        if not ENTRY_ID.fullmatch(str(e.get("id"))) or e.get("kind") not in ("defect", "intentional"):
            raise ValueError("an entry has an unexpected id or kind")
        root = Path(set_root) / SET_DIR
        need = [f"{e['id']}.patch"] + ([f"{e['id']}.wrong-fix.patch", f"{e['id']}.correct-fix.patch"]
                                       if e["kind"] == "defect" else [])
        if not all((root / n).is_file() for n in need):
            raise ValueError("an entry is missing a patch")
        out.append(e)
    kinds = [e["kind"] for e in out]
    if kinds.count("defect") != 8 or kinds.count("intentional") != 2:
        raise ValueError("the set does not have 8 defects and 2 intentional changes")
    return out


def report_text(entry: dict) -> str:
    return f"{str(entry.get('description', '')).strip()}\n\n{str(entry.get('howItShows', '')).strip()}\n"


def _patch(game: Path, patch: Path) -> None:
    # Absolute: patch -d changes folder before it opens -i, so a relative patch path is not found
    # (blind run 42940175240: the workflow passes the set as the relative path heldout-set).
    subprocess.run(["patch", "-p1", "--forward", "--batch", "--silent", "-d", str(game), "-i", str(Path(patch).resolve())],
                   check=True, capture_output=True)


def _copy_game(dest: Path, patches: list[Path]) -> Path:
    shutil.copytree(GAME, dest, ignore=shutil.ignore_patterns(".godot"))
    for p in patches:
        _patch(dest, p)
    return dest


def supplementary(defect: Path, work: Path) -> dict[str, Path | None]:
    """{'comment-only': patch or None, 'undo': patch}: made from the defect patch alone, the same way for
    every defect. The comment goes above the first hunk of the first file the defect changes, in that
    file's comment syntax; a file type without one gets no comment-only candidate."""
    from expectrail.jit.cli import diff_games

    work.mkdir(parents=True, exist_ok=True)
    clean = _copy_game(work / "clean", [])
    bug = _copy_game(work / "bug", [defect])
    out: dict[str, Path | None] = {}
    undo = work / "undo.patch"
    undo.write_text(diff_games(bug, clean), encoding="utf-8")
    out["undo"] = undo
    text = defect.read_text(encoding="utf-8", errors="replace").splitlines()
    first = next((l for l in text if l.startswith("+++ ")), None)
    hunk = next((l for l in text if l.startswith("@@")), None)
    out["comment-only"] = None
    if first and hunk:
        rel = first[4:].split("\t")[0].split("/", 1)[-1]
        mark = COMMENT_MARK.get(Path(rel).suffix)
        m = re.search(r"\+(\d+)", hunk)
        target = bug / rel
        if mark and m and target.is_file() and not target.is_symlink():
            cm = work / "comment"
            shutil.copytree(bug, cm)
            lines = (cm / rel).read_text(encoding="utf-8").split("\n")
            at = max(0, min(len(lines), int(m.group(1)) - 1))
            lines.insert(at, f"{mark} Fixed: the reported problem no longer happens.")
            (cm / rel).write_text("\n".join(lines), encoding="utf-8")
            patch = work / "comment-only.patch"
            patch.write_text(diff_games(bug, cm), encoding="utf-8")
            out["comment-only"] = patch
    return out


def candidates(set_root: Path, entry: dict, work: Path) -> list[dict]:
    root = Path(set_root) / SET_DIR
    eid, report = entry["id"], report_text(entry)
    if entry["kind"] == "intentional":
        return [{"cid": f"{eid}-change", "source": "primary", "label": "correct", "kind": "intentional",
                 "base": [], "candidate": root / f"{eid}.patch", "report": report}]
    defect = root / f"{eid}.patch"
    rows = [{"cid": f"{eid}-wrong", "source": "primary", "label": "wrong", "candidate": root / f"{eid}.wrong-fix.patch"},
            {"cid": f"{eid}-correct", "source": "primary", "label": "correct", "candidate": root / f"{eid}.correct-fix.patch"}]
    made = supplementary(defect, work / "supplementary")
    if made["comment-only"] is not None:
        rows.append({"cid": f"{eid}-comment", "source": "supplementary", "label": "wrong", "candidate": made["comment-only"]})
    rows.append({"cid": f"{eid}-undo", "source": "supplementary", "label": "correct", "candidate": made["undo"]})
    for r in rows:
        r.update(kind="defect", base=[defect], report=report)
    return rows


def arm_a(base: list[Path], candidate: Path, work: Path, run_gate=None) -> str:
    """accept | reject | needs-review, from the CI gate with the base build as base."""
    if run_gate is None:
        from expectrail.gate.verify import run_gate
    roots = {}
    for side, patches in (("base", base), ("head", [*base, candidate])):
        root = work / side
        _copy_game(root / "game" / "platformer", patches)
        for r in ROUTES:
            (root / r).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / r, root / r)
        shutil.copytree(REPO / SPECS, root / SPECS)
        roots[side] = root
    record = run_gate(repo=roots["head"], game="game/platformer", routes=ROUTES, specs=SPECS, out=work / "gate",
                      work=work / "gate-work", base=roots["base"])
    return record["decision"]


def arm_b(base: list[Path], candidate: Path, report: str, work: Path, *, budget_usd: float, runner=None,
          intent_factory=None) -> dict:
    """The final jit-run record for this candidate: the same steps as jit.yml, in one process."""
    from expectrail.contracts import load_strict
    from expectrail.jit.cli import PROFILE, attach_measurements
    from expectrail.jit.intent import from_proposal, propose_to_file, revise_to_file, spark_intent
    from expectrail.jit.measure import NAME, measure
    from expectrail.jit.probes import jit_library
    from expectrail.jit.run import generate

    intent_factory = intent_factory or spark_intent
    profile = load_strict(PROFILE, "mechanics-profile")
    probes = jit_library(profile["actions"])
    measure(profile, base, work / "measure", probes=probes, runner=runner)
    notes = attach_measurements(probes, work / "measure" / NAME, base)
    text = candidate.read_bytes().decode("utf-8", errors="replace")
    propose_to_file(intent_factory(), report, text, profile, probes, work / "p1", budget_usd=budget_usd, notes=notes)
    first = generate(PROFILE, report, candidate, base, work / "r1", runner=runner,
                     intent=from_proposal(work / "p1" / "jit-proposal.json"), budget_usd=budget_usd)
    try:
        doc = revise_to_file(intent_factory(), report, text, profile, probes, work / "p1" / "jit-proposal.json",
                             work / "r1" / "jit-run.json", work / "p2", budget_usd=budget_usd, notes=notes)
        revised = doc["revision"]["revised"]
    except Exception:  # noqa: BLE001 - the first round stands; never a pass or a catch
        (work / "revise-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        revised = False
    if not revised:
        return first
    return generate(PROFILE, report, candidate, base, work / "r2", runner=runner,
                    intent=from_proposal(work / "p2" / "jit-proposal.json"), budget_usd=budget_usd)


def run_entry(set_root: Path, entry_id: str, out: Path, *, budget_usd: float, arm_a_fn=None, arm_b_fn=None) -> list[dict]:
    """Every candidate of one entry through both arms. Returns the public rows; writes them and keeps
    the rest under ``out``. Paths are made absolute first, as the workflow passes relative ones."""
    arm_a_fn, arm_b_fn = arm_a_fn or arm_a, arm_b_fn or arm_b
    set_root, out = Path(set_root).resolve(), Path(out).resolve()
    entry = next(e for e in entries(set_root) if e["id"] == entry_id)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for c in candidates(set_root, entry, out / "work"):
        row = {"cid": c["cid"], "source": c["source"], "label": c["label"], "kind": c["kind"],
               "traceVisible": entry.get("traceVisible") if entry.get("traceVisible") in ("yes", "no", "unsure") else "unsure",
               "armA": None, "jitStatus": None, "jitStrong": 0, "jitWeak": 0, "spendUsd": 0.0, "error": None}
        work = out / "work" / c["cid"]
        try:
            row["armA"] = arm_a_fn(c["base"], c["candidate"], work / "arm-a")
        except Exception:  # noqa: BLE001
            row["error"] = "arm A did not finish"
            (work / "arm-a-error.txt").parent.mkdir(parents=True, exist_ok=True)
            (work / "arm-a-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        try:
            record = arm_b_fn(c["base"], c["candidate"], c["report"], work / "arm-b", budget_usd=budget_usd)
            row.update(jitStatus=record["status"], jitStrong=record["counts"]["strong"],
                       jitWeak=record["counts"]["weak"], spendUsd=round(float(record["spend"]["usd"]), 4))
        except Exception:  # noqa: BLE001
            row["error"] = (row["error"] + "; " if row["error"] else "") + "arm B did not finish"
            (work / "arm-b-error.txt").parent.mkdir(parents=True, exist_ok=True)
            (work / "arm-b-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        rows.append(row)
    (out / "public-rows.json").write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    return rows


def outcome(row: dict) -> dict:
    """Each arm's catch for one row: True, False, or None (no result). An undecided gate
    (needs-review) is not a catch; a generated-checks run that did not complete is no result."""
    a = None if row["armA"] is None else row["armA"] == "reject"
    b_jit = None if row["jitStatus"] != "complete" else row["jitStrong"] > 0
    b = None if a is None or b_jit is None else (a or b_jit)
    return {"A": a, "B": b}


def score(rows: list[dict]) -> dict:
    def tally(subset: list[dict]) -> dict:
        t = {"cases": len(subset)}
        for arm in ("A", "B"):
            outs = [outcome(r)[arm] for r in subset]
            t[f"{arm}caught"] = sum(o is True for o in outs)
            t[f"{arm}noResult"] = sum(o is None for o in outs)
        t["weakOnly"] = sum(1 for r in subset if r["jitWeak"] and not r["jitStrong"])
        return t

    out: dict = {"format": "expectrail.jit-blind/v0", "groups": {}}
    for source in ("primary", "supplementary"):
        for group, pick in (("wrong", lambda r: r["label"] == "wrong"),
                            ("correct", lambda r: r["label"] == "correct" and r["kind"] == "defect"),
                            ("intentional", lambda r: r["kind"] == "intentional")):
            subset = [r for r in rows if r["source"] == source and pick(r)]
            if subset:
                out["groups"][f"{source}/{group}"] = tally(subset)
                for tv in ("yes", "no", "unsure"):
                    sub = [r for r in subset if r["traceVisible"] == tv]
                    if sub:
                        out["groups"][f"{source}/{group}/traceVisible={tv}"] = tally(sub)
    g = out["groups"]
    wrong, correct, intent = g.get("primary/wrong", {}), g.get("primary/correct", {}), g.get("primary/intentional", {})
    false_a = correct.get("Acaught", 0) + intent.get("Acaught", 0)
    false_b = correct.get("Bcaught", 0) + intent.get("Bcaught", 0)
    no_result = sum(t.get("AnoResult", 0) + t.get("BnoResult", 0) for t in (wrong, correct, intent))
    expected = {"wrong": 8, "correct": 8, "intentional": 2}
    missing = sum(max(0, n - g.get(f"primary/{k}", {}).get("cases", 0)) for k, n in expected.items())
    out["missingPrimary"] = missing
    if no_result or missing:
        verdict = "incomplete"
    elif wrong.get("Bcaught", 0) > wrong.get("Acaught", 0) and false_b == false_a:
        verdict = "adds-value"
    elif wrong.get("Bcaught", 0) > wrong.get("Acaught", 0):
        verdict = "more-catches-with-more-false-catches"
    else:
        verdict = "no-added-value"
    out.update(verdict=verdict, falseCatches={"A": false_a, "B": false_b}, spendUsd=round(sum(r["spendUsd"] for r in rows), 4),
               perCandidate=[{"cid": r["cid"], "source": r["source"], "label": r["label"],
                              "A": outcome(r)["A"], "B": outcome(r)["B"]} for r in rows])
    return out


def render(doc: dict) -> str:
    lines = [f"# Blind set 3: {doc['verdict']}", ""]
    if doc.get("missingPrimary"):
        lines += [f"{doc['missingPrimary']} of the 18 primary candidates have no row: the run is incomplete.", ""]
    lines += [
             f"False catches on primary correct fixes and intentional changes: A {doc['falseCatches']['A']}, "
             f"B {doc['falseCatches']['B']}. Generated-checks spend: ${doc['spendUsd']:.4f}.", "",
             "| Group | Cases | A caught | B caught | A no result | B no result | weak only |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for k, t in doc["groups"].items():
        lines.append(f"| {k} | {t['cases']} | {t['Acaught']} | {t['Bcaught']} | {t['AnoResult']} | {t['BnoResult']} | {t['weakOnly']} |")
    lines += ["", "| Candidate | Source | Label | A | B |", "| --- | --- | --- | --- | --- |"]
    fmt = {True: "caught", False: "not caught", None: "no result"}
    for r in doc["perCandidate"]:
        lines.append(f"| {r['cid']} | {r['source']} | {r['label']} | {fmt[r['A']]} | {fmt[r['B']]} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="expectrail.jit.blind")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--set", type=Path, required=True)
    e = sub.add_parser("entry")
    e.add_argument("--set", type=Path, required=True)
    e.add_argument("--id", required=True)
    e.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("score")
    s.add_argument("--rows", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if args.cmd == "verify":
        problems = check_registration(prereg)
        got = set_digest(args.set)
        if got != prereg["set"]["sha256"]:
            problems.append("the set's digest does not match the registration")
        for p in problems:
            print(f"::error::{p}")
        if problems:
            return 1
        print(json.dumps([x["id"] for x in entries(args.set)]))
        return 0
    if args.cmd == "entry":
        if not ENTRY_ID.fullmatch(args.id):
            ap.error("unexpected id")
        rows = run_entry(args.set, args.id, args.out, budget_usd=float(prereg.get("budgetUsdPerCandidate", 2.0)))
        print(json.dumps({"candidates": len(rows), "errors": sum(1 for r in rows if r["error"])}))
        return 0
    rows = []
    for p in sorted(args.rows.rglob("public-rows.json")):
        rows += json.loads(p.read_text(encoding="utf-8"))
    doc = score(rows)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "blind-3.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    (args.out / "blind-3.md").write_text(render(doc), encoding="utf-8")
    print(json.dumps({"verdict": doc["verdict"], "falseCatches": doc["falseCatches"], "spendUsd": doc["spendUsd"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
