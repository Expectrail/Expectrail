"""A blind set's manifest (``expectrail.blind-manifest/v1``): its reader, its writer, and a validator a
person runs on the set before sealing it (#742; the set is #281, the protocol #282).

    python3 -m expectrail.blind_set validate SET/manifest.json --project bundled=game/platformer \\
        --project kinematic-character=../godot-demo-projects/2d/kinematic_character ...
    python3 -m expectrail.blind_set validate SET/manifest.json --skip-apply     # no patch is applied

The validator is offline: no network, no model, and it never runs Expectrail on the set. It reports, in
plain words, every quota cell of #282 section 3 that is unmet and how many more it needs, every entry
missing its ground truth, every declared count that disagrees with the entries, and every patch that is
missing or does not apply (``git apply --check`` on a copy of the project, outside any repository; a
candidate is checked on top of its defect). When nothing is unmet it prints one PASS line naming the
counts the set would run with. It prints entry ids and counts, never a description or a patch.

The minimum counts below are copied from #282 section 3 and are not decided here. When
``blind-registration/v2`` exists, the registration carries them and the validator will read them from it.

This module is written and tested against synthetic sets only. No agent runs it on a real blind set.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from expectrail import contracts
from expectrail.contracts import ContractError

FORMAT = "expectrail.blind-manifest/v1"
KIND = "blind-manifest"
MAX_BYTES = 4 * 1024 * 1024

FAMILIES = ("collision-physics", "movement-input", "state-counters", "visibility-rendering",
            "layering-draw-order", "assets", "camera-viewport", "timing-cooldowns", "spawning-enemies",
            "hud-text")
WRONG_FIX_KINDS = ("does-nothing", "partial", "hides-symptom-on-route", "breaks-something-else",
                   "changes-what-is-measured")
NOT_A_FIX_KINDS = ("intentional-with-contract", "intentional-without-contract", "refactor",
                   "comment-or-formatting", "asset-rename", "performance")
HARMLESS_KINDS = ("refactor", "comment-or-formatting", "asset-rename", "performance")

# #282 section 3, copied, not decided here. Targets are reported; only minimums decide a pass.
QUOTAS = {
    "wrongFixes": {"target": 60, "minimum": 30},
    "correctFixes": {"target": 40, "minimum": 20},
    "notAFix": {"target": 20, "minimum": 10},
    "maxProjectShare": 0.5,          # no project above half the set
    "screenOnlyWrongShare": 0.25,    # at least a quarter of wrong fixes are screen-only
    "perFamily": 4,                  # at least four candidates in each of the ten families
    "perWrongFixKind": 6,            # at least six of each kind of wrong fix
    "correctPerDefect": 2,           # two differently written correct fixes: one minimal, one restructures
    "perNotAFixKind": 1,             # each kind of change that is not a fix is present
}


class ManifestError(ValueError):
    """The manifest cannot be read as expectrail.blind-manifest/v1."""


# --- reading and writing --------------------------------------------------------------------------
def is_not_a_fix(entry: dict) -> bool:
    return isinstance(entry, dict) and "notAFixKind" in entry


def manifest_sha256(doc: dict) -> str:
    """The digest a sealed manifest carries: canonical JSON of the manifest with ``sha256`` removed."""
    return contracts.digest_v1({k: v for k, v in doc.items() if k != "sha256"})


def _schema() -> dict:
    return contracts.schema_v1(KIND)


def _errors(doc, ref: str | None = None) -> list[str]:
    import jsonschema

    schema = _schema()
    if ref is None:
        # Entries are checked one by one, each against its own kind (structure_problems).
        schema = dict(schema, properties=dict(schema["properties"], entries={"type": "array"}))
    else:
        schema = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": f"#/$defs/{ref}"}
    found = sorted(jsonschema.Draft202012Validator(schema).iter_errors(doc), key=lambda e: [str(p) for p in e.path])
    out = []
    for e in found:
        where = "/".join(str(p) for p in e.path)
        out.append(f"{where + ': ' if where else ''}{_message(e)}"[:300])
    return out


def _message(error) -> str:
    """jsonschema's message, without the value when the value could be set content (a text, a
    patch path list, a whole entry): the validator prints ids and counts, never a description."""
    kind = error.validator
    if kind == "not" and isinstance(error.instance, dict) and "truth" in error.instance:
        return "a wrong fix carries no style or confirmedBy, and a correct fix carries no wrongFixKind"
    if kind in ("enum", "const"):
        allowed = error.validator_value if kind == "enum" else [error.validator_value]
        return "must be one of: " + ", ".join(str(a) for a in allowed)
    if kind in ("required", "additionalProperties", "type", "minItems", "maxItems",
                "minimum", "minProperties", "maxProperties") and not (
            isinstance(error.instance, str) and len(error.instance) > 60):
        if kind in ("minItems", "maxItems", "type") and isinstance(error.instance, (dict, list)):
            return f"fails {kind} ({error.validator_value})"
        return error.message
    return f"fails {kind} ({error.validator_value})" if not isinstance(error.validator_value, (dict, list)) \
        else f"fails {kind}"


def structure_problems(doc) -> list[str]:
    """Every schema problem, one line each. Each entry is checked against its own kind, so a problem
    names the field rather than saying an entry matched neither kind."""
    if not isinstance(doc, dict):
        return ["the manifest is not a JSON object"]
    if doc.get("format") != FORMAT:
        return [f"format must be {FORMAT!r}, found {doc.get('format')!r}"]
    entries = doc.get("entries")
    out = _errors(doc)
    if isinstance(entries, list):
        if not entries:
            out.append("entries: the manifest has no entries")
        if len(entries) > 500:
            out.append("entries: more than 500")
        for n, entry in enumerate(entries):
            label = entry.get("id") if isinstance(entry, dict) and isinstance(entry.get("id"), str) else f"#{n}"
            ref = "notAFixEntry" if is_not_a_fix(entry) else "defectEntry"
            out += [f"entry {label}: {p}" for p in _errors(entry, ref)]
    return out


def load(path: Path) -> dict:
    """The manifest as JSON: duplicate keys and NaN refused, size bounded. Not yet checked."""
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ManifestError(f"{path.name}: larger than {MAX_BYTES} bytes")
    try:
        return contracts.strict_loads(path.read_text(encoding="utf-8"))
    except (ContractError, ValueError) as exc:
        raise ManifestError(f"{path.name}: not readable JSON ({exc})") from None


def read(path: Path) -> dict:
    """The reader the runner uses: the manifest, refused unless its structure, ids, references and
    seal are sound. Quotas are the validator's business, not the reader's: a set under its minimum
    is refused by the runner with the validator's words."""
    doc = load(path)
    problems = structure_problems(doc) or consistency_problems(doc)
    if problems:
        raise ManifestError("; ".join(problems[:5]) + (f" (and {len(problems) - 5} more)" if len(problems) > 5 else ""))
    return doc


def write(doc: dict, path: Path) -> Path:
    """Write a manifest. Its sha256 is filled in only when ``sealedAt`` is set (sealing is a person's
    act: this function never sets ``sealedAt``); otherwise it must be null."""
    doc = dict(doc)
    doc["sha256"] = None
    if doc.get("sealedAt"):
        doc["sha256"] = manifest_sha256(doc)
    problems = structure_problems(doc) or consistency_problems(doc)
    if problems:
        raise ManifestError("; ".join(problems[:5]))
    path = Path(path)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return path


def consistency_problems(doc: dict) -> list[str]:
    """Ids, references and the seal: what the schema cannot say. Assumes the structure is sound."""
    out: list[str] = []
    projects = doc.get("projects") or {}
    seen: set[str] = set()
    for entry in doc.get("entries") or []:
        eid = entry.get("id")
        if eid in seen:
            out.append(f"entry {eid}: the id is used twice")
        seen.add(eid)
        if entry.get("project") not in projects:
            out.append(f"entry {eid}: project {entry.get('project')!r} is not listed under projects")
        cids = [c.get("id") for c in entry.get("candidates") or []]
        for cid in sorted({c for c in cids if cids.count(c) > 1}):
            out.append(f"entry {eid}: candidate id {cid!r} is used twice")
    excluded: set[str] = set()
    for item in doc.get("exclusions") or []:
        if item.get("id") not in seen:
            out.append(f"exclusion {item.get('id')}: no entry has this id")
        if item.get("id") in excluded:
            out.append(f"exclusion {item.get('id')}: listed twice")
        excluded.add(item.get("id"))
    sealed, sha = doc.get("sealedAt"), doc.get("sha256")
    if sealed:
        try:
            when = datetime.fromisoformat(str(sealed).replace("Z", "+00:00"))
            if when.tzinfo is None:
                out.append("sealedAt: give a time zone, for example 2026-12-04T18:00:00Z")
        except ValueError:
            out.append(f"sealedAt: {sealed!r} is not a date and time, for example 2026-12-04T18:00:00Z")
    if bool(sealed) != bool(sha):
        out.append("sealedAt and sha256 must be set together: both null before sealing, both set after")
    elif sha and sha != manifest_sha256(doc):
        out.append("sha256 does not match the manifest: it was edited after sealing, or the digest is wrong")
    return out


# --- counting -------------------------------------------------------------------------------------
def included(doc: dict) -> list[dict]:
    excluded = {x.get("id") for x in doc.get("exclusions") or []}
    return [e for e in doc.get("entries") or [] if isinstance(e, dict) and e.get("id") not in excluded]


def _bump(counts: dict, key, allowed=None) -> None:
    # A value the schema refuses is counted as "(not valid)", so its text never becomes a key.
    if allowed is not None and key not in allowed:
        key = "(not valid)"
    counts[key] = counts.get(key, 0) + 1


def counts(doc: dict) -> dict:
    """The counts the set would run with, after exclusions, in declaredCounts' shape."""
    out = {"wrongFixes": 0, "correctFixes": 0, "notAFix": 0, "byProject": {}, "wrongFixesByWhereItShows": {},
           "byFamily": {}, "byWrongFixKind": {}, "byNotAFixKind": {}}
    projects = set(doc.get("projects") or {}) if isinstance(doc.get("projects"), dict) else set()
    for entry in included(doc):
        if is_not_a_fix(entry):
            out["notAFix"] += 1
            _bump(out["byProject"], entry.get("project"), projects)
            _bump(out["byNotAFixKind"], entry.get("notAFixKind"), NOT_A_FIX_KINDS)
            continue
        for cand in entry.get("candidates") or []:
            truth = cand.get("truth")
            if truth not in ("wrong", "correct"):
                continue
            _bump(out["byProject"], entry.get("project"), projects)
            _bump(out["byFamily"], entry.get("family"), FAMILIES)
            if truth == "wrong":
                out["wrongFixes"] += 1
                _bump(out["wrongFixesByWhereItShows"], entry.get("whereItShows"), ("trace-only", "screen-only", "both"))
                _bump(out["byWrongFixKind"], cand.get("wrongFixKind"), WRONG_FIX_KINDS)
            else:
                out["correctFixes"] += 1
    return out


def _more(n: int, what: str) -> str:
    return f"{n} more {what}"


def quota_problems(doc: dict, have: dict | None = None) -> list[str]:
    """Every unmet cell of #282 section 3, with how many more it needs."""
    have = have or counts(doc)
    out: list[str] = []
    for key, words in (("wrongFixes", "wrong fixes"), ("correctFixes", "correct fixes"),
                       ("notAFix", "changes that are not fixes")):
        need = QUOTAS[key]["minimum"] - have[key]
        if need > 0:
            out.append(f"size: {have[key]} {words}, the minimum is {QUOTAS[key]['minimum']}: {_more(need, words)}")
    total = have["wrongFixes"] + have["correctFixes"] + have["notAFix"]
    for project in sorted(doc.get("projects") or {}):
        n = have["byProject"].get(project, 0)
        if n == 0:
            out.append(f"project {project}: listed but has no candidate")
        elif total and n > QUOTAS["maxProjectShare"] * total:
            # The smallest set of other candidates that brings this project to half: n <= (total + k) / 2.
            k = 2 * n - total
            out.append(f"project {project}: {n} of {total} candidates is above half the set: "
                       f"{_more(k, 'candidates on the other projects')}, or {k} fewer here")
    wrong = have["wrongFixes"]
    screen = have["wrongFixesByWhereItShows"].get("screen-only", 0)
    need_screen = math.ceil(QUOTAS["screenOnlyWrongShare"] * wrong)
    if screen < need_screen:
        out.append(f"screen-only: {screen} of {wrong} wrong fixes show only on screen, a quarter needs "
                   f"{need_screen}: {_more(need_screen - screen, 'screen-only wrong fixes')}")
    for family in FAMILIES:
        n = have["byFamily"].get(family, 0)
        if n < QUOTAS["perFamily"]:
            out.append(f"family {family}: {n} candidates, at least {QUOTAS['perFamily']}: "
                       f"{_more(QUOTAS['perFamily'] - n, 'candidates')}")
    for kind in WRONG_FIX_KINDS:
        n = have["byWrongFixKind"].get(kind, 0)
        if n < QUOTAS["perWrongFixKind"]:
            out.append(f"wrong-fix kind {kind}: {n}, at least {QUOTAS['perWrongFixKind']}: "
                       f"{_more(QUOTAS['perWrongFixKind'] - n, 'wrong fixes of this kind')}")
    for kind in NOT_A_FIX_KINDS:
        n = have["byNotAFixKind"].get(kind, 0)
        if n < QUOTAS["perNotAFixKind"]:
            out.append(f"not-a-fix kind {kind}: none in the set: {_more(QUOTAS['perNotAFixKind'] - n, 'change of this kind')}")
    for entry in included(doc):
        if is_not_a_fix(entry):
            continue
        correct = [c for c in entry.get("candidates") or [] if c.get("truth") == "correct"]
        if not correct:
            continue
        styles = {c.get("style") for c in correct}
        if len(correct) < QUOTAS["correctPerDefect"]:
            out.append(f"entry {entry.get('id')}: {len(correct)} correct fix, needs {QUOTAS['correctPerDefect']} "
                       f"written differently: {_more(QUOTAS['correctPerDefect'] - len(correct), 'correct fix')}")
        elif not {"minimal", "restructures"} <= styles:
            missing = sorted({"minimal", "restructures"} - styles)
            out.append(f"entry {entry.get('id')}: its correct fixes are all {'/'.join(sorted(s for s in styles if s))}: "
                       f"1 more correct fix in the style {missing[0]}")
    return out


def verdict_problems(doc: dict) -> list[str]:
    out = []
    for entry in included(doc):
        if not is_not_a_fix(entry):
            continue
        kind, expected = entry.get("notAFixKind"), entry.get("expectedVerdict")
        if kind in HARMLESS_KINDS and expected != "accept":
            out.append(f"entry {entry.get('id')}: a {kind} change is expected to be accepted (#282 section 3), "
                       f"the manifest says {expected}")
        if kind == "intentional-without-contract" and expected == "accept":
            out.append(f"entry {entry.get('id')}: an intentional change without its contract update must not be "
                       "expected to pass silently (#282 section 3)")
    return out


def declared_problems(doc: dict, have: dict | None = None) -> list[str]:
    have = have or counts(doc)
    out = []
    for key, value in (doc.get("declaredCounts") or {}).items():
        actual = have.get(key)
        if isinstance(value, dict):
            for cell in sorted(set(value) | set(actual or {})):
                if value.get(cell, 0) != (actual or {}).get(cell, 0):
                    out.append(f"declaredCounts.{key}.{cell}: declared {value.get(cell, 0)}, "
                               f"the entries give {(actual or {}).get(cell, 0)}")
        elif value != actual:
            out.append(f"declaredCounts.{key}: declared {value}, the entries give {actual}")
    return out


# --- files ----------------------------------------------------------------------------------------
def _inside(root: Path, rel: str) -> Path | None:
    """root/rel when it is a regular file reached with no link on the way; otherwise None."""
    base = root.resolve()
    path = root / rel
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if resolved != base / rel or not resolved.is_file():
        return None
    return path


def ground_truth_problems(doc: dict, root: Path) -> tuple[list[str], list[str]]:
    """Missing ground truth (unmet) and what #282 asks beyond the manifest's required fields (notes)."""
    unmet, notes, unshown = [], [], []
    for entry in included(doc):
        eid = entry.get("id")
        if is_not_a_fix(entry):
            if entry.get("notAFixKind") in HARMLESS_KINDS and not entry.get("whyHarmless"):
                notes.append(f"entry {eid}: no whyHarmless; #281 asks for a sentence on why behaviour cannot differ")
            continue
        rep = entry.get("reproduction") or {}
        if not rep.get("steps"):
            unmet.append(f"entry {eid}: no reproduction steps")
        if not rep.get("recording"):
            unmet.append(f"entry {eid}: no recording path")
        elif _inside(root, rep["recording"]) is None:
            unmet.append(f"entry {eid}: the recording {rep['recording']} is not a file in the set")
        for cand in entry.get("candidates") or []:
            cid = f"{eid}/{cand.get('id')}"
            if cand.get("truth") == "correct" and not cand.get("confirmedBy"):
                unmet.append(f"candidate {cid}: a correct fix with no confirmedBy")
            if cand.get("truth") == "wrong":
                crep = cand.get("reproduction")
                if not crep:
                    unshown.append(cid)
                elif _inside(root, crep.get("recording", "")) is None:
                    unmet.append(f"candidate {cid}: the recording {crep.get('recording')} is not a file in the set")
    if unshown:
        listed = ", ".join(unshown[:5]) + (f" and {len(unshown) - 5} more" if len(unshown) > 5 else "")
        notes.append(f"{len(unshown)} wrong fix(es) have no reproduction of their own ({listed}); #282 section 4 "
                     "asks for each wrong fix to be shown wrong by a person playing the build")
    return unmet, notes


def _git_env(tmp: str) -> dict:
    # Its own small environment: git finds no repository above the copy and reads nobody's settings.
    return {"PATH": os.environ.get("PATH", os.defpath), "HOME": tmp,
            "GIT_CEILING_DIRECTORIES": str(Path(tmp).resolve()), "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull}


def _git_apply(git: str, work: Path, patch: Path, env: dict, check: bool) -> str | None:
    cmd = [git, "apply", "-p1"] + (["--check"] if check else []) + [str(patch.resolve())]
    done = subprocess.run(cmd, cwd=work, capture_output=True, text=True, env=env)
    if done.returncode != 0:
        return " ".join((done.stdout + done.stderr).split())[:200] or f"git apply exited {done.returncode}"
    return None


def project_commit_problem(project_dir: Path, commit: str) -> str | None:
    """None when the folder's committed and working content equals its content at ``commit``.

    Only the folder is compared, so the bundled game inside this repository passes at any later commit
    that leaves it unchanged. Files git does not track are not compared."""
    git = shutil.which("git")
    if git is None:
        return "git is not installed, so the pinned commit was not checked"
    inside = subprocess.run([git, "-C", str(project_dir), "rev-parse", "--is-inside-work-tree"],
                            capture_output=True, text=True)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return "not a git checkout, so the pinned commit cannot be checked"
    known = subprocess.run([git, "-C", str(project_dir), "cat-file", "-e", f"{commit}^{{commit}}"],
                           capture_output=True, text=True)
    if known.returncode != 0:
        return f"commit {commit} is not in this checkout, so the pinned commit cannot be checked"
    diff = subprocess.run([git, "-C", str(project_dir), "diff", "--quiet", commit, "--", "."],
                          capture_output=True, text=True)
    if diff.returncode != 0:
        return f"the folder differs from commit {commit}"
    return None


def patch_problems(doc: dict, root: Path, project_dirs: dict[str, Path]) -> list[str]:
    """Missing patches, and patches that do not apply. A candidate is checked on top of its defect."""
    out: list[str] = []
    git = shutil.which("git")
    by_project: dict[str, list[dict]] = {}
    for entry in included(doc):
        by_project.setdefault(entry.get("project"), []).append(entry)
    for project in sorted(by_project, key=str):
        entries = by_project[project]
        paths: list[tuple[dict, list[tuple[str, Path | None, str]]]] = []
        for entry in entries:
            eid = entry.get("id")
            named = [(f"entry {eid}", entry.get("patch") if is_not_a_fix(entry) else entry.get("defectPatch"))]
            named += [(f"candidate {eid}/{c.get('id')}", c.get("patch")) for c in entry.get("candidates") or []]
            found = []
            for who, rel in named:
                path = _inside(root, rel) if isinstance(rel, str) else None
                if path is None:
                    out.append(f"{who}: the patch {rel} is not a file in the set")
                found.append((who, path, rel))
            paths.append((entry, found))
        source = project_dirs.get(project)
        if source is None:
            out.append(f"project {project}: patches not applied, because no folder was given "
                       f"(--project {project}=FOLDER, at its pinned commit)")
            continue
        if not Path(source).is_dir():
            out.append(f"project {project}: {source} is not a folder")
            continue
        if git is None:
            out.append(f"project {project}: git is not installed, so no patch was applied")
            continue
        commit = ((doc.get("projects") or {}).get(project) or {}).get("commit")
        if commit:
            problem = project_commit_problem(Path(source), commit)
            if problem:
                out.append(f"project {project}: {problem}")
        for entry, found in paths:
            if any(p is None for _, p, _ in found):
                continue  # already reported missing
            with tempfile.TemporaryDirectory(prefix="expectrail-blindset-") as tmp:
                work = Path(tmp) / "project"
                shutil.copytree(source, work, ignore=shutil.ignore_patterns(".git", ".godot"), symlinks=True)
                env = _git_env(tmp)
                (who, base, rel), rest = found[0], found[1:]
                if is_not_a_fix(entry):
                    problem = _git_apply(git, work, base, env, check=True)
                    if problem:
                        out.append(f"{who}: {rel} does not apply to project {project}: {problem}")
                    continue
                problem = _git_apply(git, work, base, env, check=False)
                if problem:
                    out.append(f"{who}: the defect {rel} does not apply to project {project}: {problem}")
                    continue
                for who, path, rel in rest:
                    problem = _git_apply(git, work, path, env, check=True)
                    if problem:
                        out.append(f"{who}: {rel} does not apply on top of its defect: {problem}")
    return out


# --- the validator --------------------------------------------------------------------------------
def validate(manifest: Path, project_dirs: dict[str, Path] | None = None, *, apply: bool = True) -> dict:
    """The validator's findings: ``unmet`` (each blocks the set), ``notes`` (do not), the counts, and
    whether the set would be accepted. Never raises on a bad set: what is wrong is the answer."""
    manifest = Path(manifest)
    root = manifest.parent
    report = {"unmet": [], "notes": [], "counts": None, "passed": False, "patchesChecked": apply}
    try:
        doc = load(manifest)
    except (OSError, ManifestError) as exc:
        report["unmet"].append(str(exc))
        return report
    structure = structure_problems(doc)
    report["unmet"] += structure
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        return report
    try:
        report["unmet"] += consistency_problems(doc)
        have = counts(doc)
        report["counts"] = have
        report["unmet"] += quota_problems(doc, have)
        report["unmet"] += verdict_problems(doc)
        report["unmet"] += declared_problems(doc, have)
        unmet, notes = ground_truth_problems(doc, root)
        report["unmet"] += unmet
        report["notes"] += notes
        if apply:
            report["unmet"] += patch_problems(doc, root, project_dirs or {})
        else:
            report["notes"].append("patches were not applied (--skip-apply): the set cannot pass until they are")
    except (AttributeError, TypeError, KeyError) as exc:
        # Only reachable when the structure is already reported as wrong.
        report["unmet"].append(f"cannot finish the checks until the structure is fixed ({type(exc).__name__})")
    if not doc.get("sealedAt"):
        report["notes"].append("not sealed yet: sealedAt and sha256 are null")
    report["passed"] = not report["unmet"] and apply
    return report


def render(report: dict) -> str:
    lines = []
    if report["unmet"]:
        lines.append(f"NOT READY: {len(report['unmet'])} thing(s) to fix")
        lines += [f"  - {p}" for p in report["unmet"]]
    if report["notes"]:
        lines.append("Notes (these do not block the set):")
        lines += [f"  - {n}" for n in report["notes"]]
    have = report.get("counts")
    if have:
        projects = ", ".join(f"{k} {v}" for k, v in sorted(have["byProject"].items(), key=lambda kv: str(kv[0])))
        summary = (f"{have['wrongFixes']} wrong fixes, {have['correctFixes']} correct fixes, {have['notAFix']} changes "
                   f"that are not fixes ({projects}); {have['wrongFixesByWhereItShows'].get('screen-only', 0)} "
                   "wrong fixes are screen-only")
        if report["passed"]:
            lines.append(f"PASS: the set would be accepted and would run with {summary}.")
        else:
            lines.append(f"Counts now: {summary}.")
    return "\n".join(lines) + "\n"


def _project_arg(text: str) -> tuple[str, Path]:
    name, sep, folder = text.partition("=")
    if not sep or not name or not folder:
        raise argparse.ArgumentTypeError("use --project NAME=FOLDER")
    return name, Path(folder)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m expectrail.blind_set",
                                     description="Read and check a blind set's manifest (expectrail.blind-manifest/v1).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="report every unmet quota, missing ground truth and patch that does not apply")
    v.add_argument("manifest", type=Path)
    v.add_argument("--project", action="append", type=_project_arg, default=[],
                   help="NAME=FOLDER: a checkout of the project at its pinned commit (repeat per project)")
    v.add_argument("--skip-apply", action="store_true", help="check everything but the patches (never passes)")
    v.add_argument("--json", action="store_true", help="print the findings as JSON")
    args = parser.parse_args(argv)
    report = validate(args.manifest, dict(args.project), apply=not args.skip_apply)
    if args.json:
        sys.stdout.write(json.dumps(report, indent=1, sort_keys=True) + "\n")
    else:
        sys.stdout.write(render(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
