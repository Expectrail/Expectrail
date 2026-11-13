"""The CI gate's findings record (contracts/findings.schema.json): finding ids, the decision rule, and
reading a record as data.

Standard library only, on purpose. The comment step runs this in a job that can write pull request
comments, on a file that came out of a job that ran the pull request's code. So a record is read the
way untrusted input should be: a size cap before parsing, a regular file only (no symlink), JSON with
duplicate keys and NaN or Infinity refused, the closed schema checked by the small validator below
(it refuses any schema keyword it does not implement, so it cannot pass something by ignoring it),
and then every derived value recomputed: each finding id from its spec, route and kind, each
comparison from its two results, the counts from the rows and the decision from the counts. Nothing
in a record is ever run, imported or passed to a shell.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

FORMAT = "expectrail.findings/v0"
# Where Expectrail's own files are: beside the package in a clone, inside it (`_bundle`) in an
# installed copy. The same rule as expectrail.resources, worked out here because this module is
# trusted code that imports the standard library and nothing else (the comment job runs it).
_PACKAGE = Path(__file__).resolve().parent.parent
SCHEMA_PATH = (_PACKAGE / "_bundle" if (_PACKAGE / "_bundle").is_dir() else _PACKAGE.parent) / "contracts" / "findings.schema.json"
RESULTS = ("pass", "fail", "needs-review", "replay-error")
KINDS = ("fail", "needs-review", "replay-error")
DECISIONS = ("accept", "reject", "needs-review")
MAX_RECORD_BYTES = 4 * 1024 * 1024
MAX_DEPTH = 32
FINDING_ID = re.compile(r"[0-9a-f]{12}")


# The review's comparison table (expectrail.change_evidence.compare, docs/review.md), repeated here so
# the trusted side imports nothing but this file; a test holds the two equal.
_COMPARE = {("fail", "pass"): "REPAIRED", ("pass", "pass"): "PRESERVED",
            ("pass", "fail"): "REGRESSION", ("fail", "fail"): "UNRESOLVED"}


def compare(before: str | None, after: str | None) -> str:
    """One check before and after the change. Anything but pass or fail on either side (not run,
    needs review, a replay that did not finish) is INCONCLUSIVE: never read as a pass or a failure."""
    return _COMPARE.get((before, after), "INCONCLUSIVE")


class RecordError(ValueError):
    """The record cannot be used: too big, not JSON, not the schema, or not consistent."""


def finding_id(spec: str, route: str, kind: str) -> str:
    """The first 12 hex digits of sha256(spec LF route LF kind).

    It depends on nothing that changes from push to push (no commit, frame, reason or time), so the
    same failure keeps its id. Reproduce one by hand with
    ``printf '%s\\n%s\\n%s' SPEC ROUTE KIND | sha256sum | cut -c1-12``.
    """
    for name, value in (("spec", spec), ("route", route), ("kind", kind)):
        if not isinstance(value, str) or not value or "\n" in value:
            raise ValueError(f"finding {name} must be a non-empty single-line string")
    return hashlib.sha256(f"{spec}\n{route}\n{kind}".encode("utf-8")).hexdigest()[:12]


# Which observers judged a record's checks (the record's ``observers.rule``).
# ``both``: Sean's rule of November 12, 2026 (#327). Every check is judged by the engine's record and
# by a visual observer over the captured frames, and ``combine`` below gives the check's result.
# ``engine-only``: the engine's record alone, which is how every record was judged before the rule.
# An engine-only record is written without an ``observers`` block, as records were before the block
# existed, so a reader older than the block still reads it; no block is read as ``engine-only``.
BOTH, ENGINE_ONLY = "both", "engine-only"
RULES = (BOTH, ENGINE_ONLY)
# What a visual observer said about one check: its verdict, or that it did not answer (no frames,
# the model failed), or that it was not asked (none was configured, or the engine's record had
# already failed the check).
VISUAL_VERDICTS = ("pass", "fail", "needs-review")
VISUAL_SAID = VISUAL_VERDICTS + ("no-answer", "not-asked")


def combine(engine: str, visual: str) -> str:
    """One check's result from what its two observers said (the rule ``both``):

        the engine's record    the visual observer         the check
        pass                   pass                        pass
        fail                   anything                    fail
        anything               fail                        fail
        pass                   unsure, no answer, not asked    needs-review
        needs-review           pass                        needs-review

    So a pass needs both, a failure on either is a failure, and nothing passes on the engine's record
    alone. A replay that did not finish has no observations at all and stays ``replay-error``.
    """
    if engine not in RESULTS:
        raise ValueError(f"unknown result {engine!r}")
    if visual not in VISUAL_SAID:
        raise ValueError(f"unknown visual answer {visual!r}")
    if engine == "replay-error":
        return "replay-error"
    if engine == "fail" or visual == "fail":
        return "fail"
    if engine == "pass" and visual == "pass":
        return "pass"
    return "needs-review"


def rule_of(doc: dict) -> str:
    """The rule a record was judged by; a record from before the block existed is ``engine-only``."""
    block = doc.get("observers")
    return ENGINE_ONLY if block is None else block["rule"]


def observers_words(doc: dict) -> str:
    """One line on which observers judged, for the page and the comment."""
    block = doc.get("observers")
    if rule_of(doc) == ENGINE_ONLY:
        return ("the engine's record only: no visual observer looked at the frames, so read an accept as "
                "the engine's record passing, not as the full verdict")
    visual = block["visual"]
    if visual is None:
        return ("the engine's record; a visual observer is required for an accept and none was asked, so "
                "nothing here is accepted")
    return (f"two observers on every check: the engine's record, and {visual['name']} "
            f"({visual['model']}, {visual['provider']}) over the captured frames; a check passes only when both pass")


def kind_of(after: str) -> str | None:
    """The finding kind for a check's result after the change; None when it passes."""
    if after not in RESULTS:
        raise ValueError(f"unknown result {after!r}")
    return None if after == "pass" else after


NOT_SAID = "the replay did not say whether it was sandboxed"
SANDBOX_TOOLS = ("bubblewrap",)   # the tools contracts/findings.schema.json lets a record name


def isolation_summary(seen: list, required: bool) -> dict:
    """The record's ``isolation`` block from each finished replay's own account (the ``isolation``
    block of its replay.json, or None when the replay gave none). A replay counts as sandboxed only
    when it names the tool and says the game had no network, a confined file system and its own
    processes; anything less is outside."""
    def named(one) -> tuple[str, str] | None:
        """The tool and version a replay names, when it names a known tool and all three properties."""
        if not isinstance(one, dict) or not isinstance(one.get("sandbox"), dict):
            return None
        tool, version = one["sandbox"].get("tool"), one["sandbox"].get("version")
        if tool not in SANDBOX_TOOLS or not isinstance(version, str) or not 0 < len(version) <= 40:
            return None
        if (one.get("network"), one.get("filesystem"), one.get("processes")) != ("none", "confined", "own"):
            return None
        return tool, version

    names = [named(one) for one in seen]
    first = next((name for name in names if name is not None), None)
    # One record names one tool: a replay that names another tool or version is not counted with it.
    inside = [name is not None and name == first for name in names]
    reasons = set()
    for one, name, ok in zip(seen, names, inside):
        if ok:
            continue
        if name is not None:
            reasons.add(f"a replay ran in {name[0]} {name[1]}, not the {first[0]} {first[1]} the others ran in")
        elif isinstance(one, dict) and isinstance(one.get("sandbox"), dict):
            reasons.add("a replay named a sandbox this record does not know, or not all of: no network, "
                        "confined files, own processes")
        else:
            said = one.get("reason") if isinstance(one, dict) else None
            reasons.add(str(said)[:300] if isinstance(said, str) and said.strip() else NOT_SAID)
    return {"replays": len(seen), "sandboxed": sum(inside), "required": bool(required),
            "sandbox": None if first is None or not any(inside) else {"tool": first[0], "version": first[1]},
            "reasons": sorted(reasons)[:5]}


def isolation_words(isolation: dict | None) -> str:
    """One line on whether the game ran in the replay sandbox, for the page and the comment."""
    if isolation is None:
        return "not recorded (a record from before the sandbox existed): read it as not sandboxed"
    total, inside = isolation["replays"], isolation["sandboxed"]
    if not total:
        return "no replay ran" + (" (the sandbox was required)" if isolation["required"] else "")
    tool = isolation["sandbox"]
    if inside == total:
        return (f"all {total}, in {tool['tool']} {tool['version']}: no network, the game's own files only"
                + (" (required)" if isolation["required"] else ""))
    why = "; ".join(isolation["reasons"])
    return f"{inside} of {total}. Outside it the game ran as the job's user, with the network: {why}"


# What a change says it is for (issue #284). ``fix``: it claims to fix a reported bug, and is accepted
# only when the repair is demonstrated. ``change``: an intended change of behaviour. ``none``: nothing
# declared, which is also how a record from before the field existed is read. ``change`` and ``none``
# are judged by the same rule as before; ``fix`` is the stricter path and can only take accepts away.
INTENTS = ("fix", "change", "none")
REPAIR_RUNS = 3   # a demonstration is the base failing and the head passing this many times of this many
NOT_DEMONSTRATED = "repair-not-demonstrated"


def intent_of(doc: dict) -> str:
    """What the change was declared as; a record from before the field existed declared nothing."""
    return doc.get("intent", "none")


def row_counts(row: dict) -> bool:
    """Whether one repair row is a demonstration: the check failed on the base on every run and passed
    after the change on every run, REPAIR_RUNS times each. A base that fails once and then passes is
    flaky, and a flaky failure demonstrates nothing."""
    return (len(row["base"]) == REPAIR_RUNS and len(row["head"]) == REPAIR_RUNS
            and all(r == "fail" for r in row["base"]) and all(r == "pass" for r in row["head"]))


def repair_block(rows: list[dict]) -> dict:
    """The record's ``repair`` block from its rows; ``counts`` and ``demonstrated`` are worked out here."""
    rows = [dict(spec=r["spec"], route=r["route"], base=list(r["base"]), head=list(r["head"])) for r in rows]
    for row in rows:
        row["counts"] = row_counts(row)
    return {"runs": REPAIR_RUNS, "demonstrated": sum(r["counts"] for r in rows), "rows": rows}


def unverified_fix(doc: dict) -> bool:
    """A change declared as a fix for which no check demonstrated the repair."""
    return intent_of(doc) == "fix" and not (doc.get("repair") or {}).get("demonstrated")


def _not_demonstrated(counts: dict, repair: dict | None, base_judged: bool) -> str:
    """The reason line for a fix whose repair no check demonstrated. It starts with the reason's name."""
    head = f"{NOT_DEMONSTRATED}: this change is declared as a fix, and "
    rows = (repair or {}).get("rows") or []
    if rows:
        return (head + f"{len(rows)} check{'s' if len(rows) != 1 else ''} failed before the change and passed after it "
                f"once, but not {REPAIR_RUNS} times of {REPAIR_RUNS} on both sides, so the repair is not demonstrated")
    if not counts["checks"]:
        return head + "no check ran, so nothing shows the bug or its repair"
    if not base_judged:
        return head + "the build before the change was not judged, so no check could show the bug"
    return (head + f"none of the {counts['checks']} checks that ran failed before the change, so no check reproduced "
            "the reported bug and nothing shows it is fixed")


def decide(counts: dict, held: dict, isolation: dict | None = None, check_problems: int = 0, *,
           intent: str = "none", repair: dict | None = None, base_judged: bool = True) -> tuple[str, list[str]]:
    """accept, reject or needs-review, and why.

    Accept only when at least one check ran and every public and held-out check passed. Any failure
    rejects. Anything unclear (a check that needs review, a replay that did not finish, held-out
    routes that could not be read) needs review: it is never read as a pass. When the sandbox was
    required, a replay outside it is unclear too: an accept never rests on one. A spec or route file
    the gate could not use (``check_problems``) is unclear in the same way: the checks that ran are
    then not all of the project's checks, so their passing is not an accept.

    ``intent`` is what the change says it is for. For ``fix`` an accept also needs the repair
    demonstrated: at least one row of ``repair`` (see ``repair_block``) where a check failed on the
    base and passed after the change, on the same route, REPAIR_RUNS times of REPAIR_RUNS. Without one
    the decision is needs-review with the reason ``repair-not-demonstrated``: "no check failed" is not
    "the fix is good" when no check touched the bug. It never turns a reject into anything else, and
    for ``change`` and ``none`` the rule is the one above, unchanged. ``base_judged`` only words the
    reason: whether any check has a result on the base. For an unverified fix the
    ``repair-not-demonstrated`` reason is always the first, whatever else is wrong.
    """
    if intent not in INTENTS:
        raise ValueError(f"unknown intent {intent!r}")
    unverified = intent == "fix" and not (repair or {}).get("demonstrated")
    reasons = []
    if counts["failed"]:
        reasons.append(f"{counts['failed']} of {counts['checks']} public checks fail after the change")
    if held["failed"]:
        reasons.append(f"{held['failed']} held-out checks fail after the change")
    if reasons:
        return "reject", reasons
    if not counts["checks"]:
        return "needs-review", ([_not_demonstrated(counts, repair, base_judged)] if unverified else []) + ["no checks ran"]
    if check_problems:
        reasons.append(f"{check_problems} problem{'s' if check_problems != 1 else ''} with the spec and route files, "
                       "so the checks that ran are not all of the project's checks")
    if counts["needsReview"]:
        reasons.append(f"{counts['needsReview']} of {counts['checks']} public checks could not be decided")
    if held["status"] == "unavailable":
        reasons.append("the held-out routes could not be judged")
    elif held["needsReview"]:
        reasons.append(f"{held['needsReview']} held-out checks could not be decided")
    if isolation is not None and isolation["required"] and isolation["sandboxed"] != isolation["replays"]:
        outside = isolation["replays"] - isolation["sandboxed"]
        reasons.append(f"{outside} of {isolation['replays']} replays ran outside the sandbox, which was required")
    if unverified:
        reasons.insert(0, _not_demonstrated(counts, repair, base_judged))
    if reasons:
        return "needs-review", reasons
    total = counts["checks"] + held["checks"]
    if intent == "fix":
        shown = repair["demonstrated"]
        return "accept", [f"all {total} checks pass, and {shown} of them failed before the change "
                          f"{REPAIR_RUNS} times of {REPAIR_RUNS}: the repair is demonstrated"]
    return "accept", [f"all {total} checks pass"]


# --- reading a record as data ---------------------------------------------------------------------

def _no_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise RecordError(f"duplicate key {key[:40]!r}")
        out[key] = value
    return out


def _no_constants(name):
    raise RecordError(f"non-finite number {name} is not allowed")


def strict_loads(text: str):
    """JSON with duplicate keys, NaN and Infinity refused, and nesting capped."""
    try:
        doc = json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_no_constants)
    except RecordError:
        raise
    except (ValueError, RecursionError) as exc:
        raise RecordError(f"not valid JSON: {type(exc).__name__}") from None
    if _depth(doc) > MAX_DEPTH:
        raise RecordError(f"nested deeper than {MAX_DEPTH} levels")
    return doc


def _depth(value, level: int = 1) -> int:
    if level > MAX_DEPTH:
        return level
    if isinstance(value, dict):
        return max([_depth(v, level + 1) for v in value.values()] or [level])
    if isinstance(value, list):
        return max([_depth(v, level + 1) for v in value] or [level])
    return level


def read_bytes_capped(path: Path, cap: int = MAX_RECORD_BYTES, label: str = "findings.json") -> bytes:
    """A regular file's bytes, refusing a symlink, a non-file or anything over ``cap``."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        raise RecordError(f"no {label}") from None
    except OSError as exc:
        raise RecordError(f"{label} cannot be opened ({type(exc).__name__}; a symlink is refused)") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise RecordError(f"{label} is not a regular file")
        if info.st_size > cap:
            raise RecordError(f"{label} is {info.st_size} bytes, over the {cap} byte cap")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(cap + 1)
    finally:
        os.close(fd)
    if len(data) > cap:
        raise RecordError(f"{label} is over the {cap} byte cap")
    return data


def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def read_json(path: Path, cap: int = MAX_RECORD_BYTES, label: str = "findings.json"):
    """A capped, regular, UTF-8, strict JSON file, parsed (not validated)."""
    data = read_bytes_capped(Path(path), cap, label)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise RecordError(f"{label} is not UTF-8") from None
    return strict_loads(text)


def read_record(path: Path) -> dict:
    """Load, validate and check a findings record. Raises RecordError with a short reason."""
    doc = read_json(path)
    check_record(doc)
    return doc


def check_record(doc) -> None:
    validate(doc, schema())
    check_consistency(doc)


# --- a small JSON Schema validator ----------------------------------------------------------------
# The subset of draft 2020-12 that the contracts use. Annotation keywords are ignored; any other
# keyword is refused, so a schema change this validator does not understand fails closed.

ANNOTATIONS = frozenset({"$schema", "$id", "title", "description", "$comment", "default", "examples"})
IMPLEMENTED = frozenset({
    "type", "enum", "const", "required", "properties", "additionalProperties", "items", "minItems",
    "maxItems", "minLength", "maxLength", "pattern", "minimum", "maximum", "minProperties",
    "maxProperties", "propertyNames", "oneOf", "anyOf",
})


_PATTERNS: dict[str, re.Pattern] = {}


def schema_pattern(pattern: str) -> re.Pattern:
    r"""A schema's ``pattern``, compiled to match as JSON Schema means it (ECMA-262, no flags).

    The difference that matters: Python's ``$`` also matches before a final newline, so ``^[a-z]+$``
    would pass ``"godot\n"``; in a schema ``$`` is the end of the string. Every ``$`` outside a
    character class and not escaped becomes ``\Z``. And ``\d`` and ``\w`` are ASCII in a schema, so
    the pattern is compiled with ``re.ASCII`` (Python's would take any Unicode digit for ``\d``)."""
    got = _PATTERNS.get(pattern)
    if got is not None:
        return got
    out, i, in_class = [], 0, False
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\":
            out.append(pattern[i:i + 2])
            i += 2
            continue
        if in_class:
            in_class = ch != "]"
        elif ch == "[":
            in_class = True
            # a "]" first in a class is a member, not its end
            if pattern[i + 1:i + 2] == "^":
                out.append("[^")
                i += 2
                if pattern[i:i + 1] == "]":
                    out.append("]")
                    i += 1
                continue
            if pattern[i + 1:i + 2] == "]":
                out.append("[]")
                i += 2
                continue
        elif ch == "$":
            out.append("\\Z")
            i += 1
            continue
        out.append(ch)
        i += 1
    got = _PATTERNS[pattern] = re.compile("".join(out), re.ASCII)
    return got


class SchemaError(Exception):
    """The schema uses a keyword this validator does not implement."""


def _is_type(value, name: str) -> bool:
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "integer":
        return (isinstance(value, int) and not isinstance(value, bool)) or (
            isinstance(value, float) and value.is_integer())
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise SchemaError(f"unknown type {name!r}")


def _equal(a, b) -> bool:
    """JSON equality: true is not 1, and 1 equals 1.0."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_equal(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def errors(value, rule: dict, where: str = "") -> list[str]:
    """Every way ``value`` breaks ``rule``, as 'path: problem' strings (empty when it conforms)."""
    unknown = set(rule) - IMPLEMENTED - ANNOTATIONS
    if unknown:
        raise SchemaError(f"unsupported schema keyword(s) {sorted(unknown)} at {where or '(root)'}")
    here = where or "(root)"
    out: list[str] = []
    if "type" in rule:
        names = rule["type"] if isinstance(rule["type"], list) else [rule["type"]]
        if not any(_is_type(value, n) for n in names):
            return [f"{here}: expected {' or '.join(names)}"]
    if "const" in rule and not _equal(value, rule["const"]):
        out.append(f"{here}: not the required constant")
    if "enum" in rule and not any(_equal(value, option) for option in rule["enum"]):
        out.append(f"{here}: not one of the allowed values")
    if isinstance(value, str):
        if "minLength" in rule and len(value) < rule["minLength"]:
            out.append(f"{here}: shorter than {rule['minLength']}")
        if "maxLength" in rule and len(value) > rule["maxLength"]:
            out.append(f"{here}: longer than {rule['maxLength']}")
        if "pattern" in rule and schema_pattern(rule["pattern"]).search(value) is None:
            out.append(f"{here}: does not match its pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in rule and value < rule["minimum"]:
            out.append(f"{here}: below {rule['minimum']}")
        if "maximum" in rule and value > rule["maximum"]:
            out.append(f"{here}: above {rule['maximum']}")
    if isinstance(value, list):
        if "minItems" in rule and len(value) < rule["minItems"]:
            out.append(f"{here}: fewer than {rule['minItems']} items")
        if "maxItems" in rule and len(value) > rule["maxItems"]:
            out.append(f"{here}: more than {rule['maxItems']} items")
        if "items" in rule:
            for n, item in enumerate(value):
                out.extend(errors(item, rule["items"], f"{where}/{n}"))
    if isinstance(value, dict):
        if "minProperties" in rule and len(value) < rule["minProperties"]:
            out.append(f"{here}: fewer than {rule['minProperties']} properties")
        if "maxProperties" in rule and len(value) > rule["maxProperties"]:
            out.append(f"{here}: more than {rule['maxProperties']} properties")
        for key in rule.get("required", []):
            if key not in value:
                out.append(f"{here}: missing {key}")
        props = rule.get("properties", {})
        extra = rule.get("additionalProperties", True)
        for key, item in value.items():
            if "propertyNames" in rule and errors(key, rule["propertyNames"], f"{where}/(name)"):
                out.append(f"{here}: a property name does not match its pattern")
            if key in props:
                out.extend(errors(item, props[key], f"{where}/{key}"))
            elif extra is False:
                out.append(f"{here}: a property is not allowed here")
            elif isinstance(extra, dict):
                out.extend(errors(item, extra, f"{where}/(additional)"))
    if "oneOf" in rule:
        matched = sum(1 for option in rule["oneOf"] if not errors(value, option, where))
        if matched != 1:
            out.append(f"{here}: matches {matched} of the oneOf options, not exactly one")
    if "anyOf" in rule and not any(not errors(value, option, where) for option in rule["anyOf"]):
        out.append(f"{here}: matches none of the anyOf options")
    return out


def validate(doc, rule: dict) -> None:
    found = errors(doc, rule)
    if found:
        # Paths name schema properties and array indexes only; an unexpected key's own text is not
        # repeated, since it came from the record.
        raise RecordError(f"does not match the findings schema: {found[0]}"
                          + (f" (and {len(found) - 1} more)" if len(found) > 1 else ""))


# --- consistency ----------------------------------------------------------------------------------

def check_consistency(doc: dict) -> None:
    """Everything in a record that can be derived from the rest must agree with it."""
    spec_ids = [s["id"] for s in doc["specs"]]
    route_names = [r["name"] for r in doc["routes"]]
    if len(set(spec_ids)) != len(spec_ids):
        raise RecordError("a spec id is listed twice")
    if len(set(route_names)) != len(route_names):
        raise RecordError("a route name is listed twice")
    seen = set()
    expected: dict[str, dict] = {}
    for n, check in enumerate(doc["checks"]):
        key = (check["spec"], check["route"])
        if key in seen:
            raise RecordError(f"checks/{n}: the same spec and route are judged twice")
        seen.add(key)
        if check["spec"] not in spec_ids or check["route"] not in route_names:
            raise RecordError(f"checks/{n}: names a spec or route the record does not list")
        if check["comparison"] != compare(check["before"], check["after"]):
            raise RecordError(f"checks/{n}: the comparison does not follow from before and after")
        kind = kind_of(check["after"])
        want = None if kind is None else finding_id(check["spec"], check["route"], kind)
        if check["findingId"] != want:
            raise RecordError(f"checks/{n}: the finding id is not sha256(spec, route, kind)")
        if want is not None:
            expected[want] = check
    if len(seen) != len(spec_ids) * len(route_names):
        raise RecordError("the checks are not every listed spec on every listed route")
    ids = [f["id"] for f in doc["findings"]]
    if len(set(ids)) != len(ids):
        raise RecordError("a finding id is listed twice")
    if set(ids) != set(expected):
        raise RecordError("the findings are not exactly the checks that do not pass")
    for n, finding in enumerate(doc["findings"]):
        check = expected[finding["id"]]
        same = all(finding[k] == check[k] for k in ("spec", "route", "before", "after", "comparison"))
        if not same or finding["kind"] != kind_of(finding["after"]):
            raise RecordError(f"findings/{n}: does not match its check")
    counts = doc["counts"]
    afters = [c["after"] for c in doc["checks"]]
    recount = {"checks": len(afters), "passed": afters.count("pass"), "failed": afters.count("fail"),
               "needsReview": afters.count("needs-review") + afters.count("replay-error")}
    if counts != recount:
        raise RecordError("the counts do not match the checks")
    held = doc["heldOut"]
    if held["passed"] + held["failed"] + held["needsReview"] != held["checks"]:
        raise RecordError("the held-out counts do not add up")
    if held["status"] == "not-used" and any(held[k] for k in ("routes", "checks", "passed", "failed", "needsReview")):
        raise RecordError("held-out counts are given but the held-out routes were not used")
    isolation = doc.get("isolation")
    if isolation is not None:
        if isolation["sandboxed"] > isolation["replays"]:
            raise RecordError("more replays are called sandboxed than ran")
        if (isolation["sandbox"] is None) != (isolation["sandboxed"] == 0):
            raise RecordError("the sandbox tool is named exactly when a replay ran in it")
        if bool(isolation["reasons"]) != (isolation["sandboxed"] < isolation["replays"]):
            raise RecordError("a reason is given exactly when a replay ran outside the sandbox")
        # Every judged route was replayed at least once on each side that has a result, so a record
        # cannot count fewer replays than its own checks rest on (and so cannot hide one that ran
        # outside the sandbox by not counting it).
        ran = lambda result: result is not None and result != "replay-error"   # noqa: E731
        needed = (len({c["route"] for c in doc["checks"] if ran(c["after"])})
                  + len({c["route"] for c in doc["checks"] if ran(c["before"])})
                  # A held-out replay that finished gave every spec a result; one that did not finish
                  # is in needsReview and was not counted as a replay.
                  + -(-(held["passed"] + held["failed"]) // max(1, len(spec_ids))))
        if isolation["replays"] < needed:
            raise RecordError(f"the checks rest on at least {needed} replays and the record counts {isolation['replays']}")
    check_observers(doc)
    check_repair(doc)
    decision, _reasons = decide(counts, held, isolation, doc.get("checkProblems", 0),
                                intent=intent_of(doc), repair=doc.get("repair"))
    if doc["decision"] != decision:
        raise RecordError(f"the decision should be {decision} from these counts")
    pr = doc["pullRequest"]
    if pr is not None and doc["checksFrom"] == "base" and pr["baseSha"] is None:
        raise RecordError("checks from the base need the base commit")
    generated = doc.get("generatedChecks")
    if generated is not None:
        check_generated(generated)


def check_observers(doc: dict) -> None:
    """What the record says each observer said agrees with each check's result, by ``combine``.

    Under ``both`` every row says what the two observers said on each side that was judged, and its
    ``before`` and ``after`` are recomputed from that: a row cannot pass without the visual observer's
    pass, and a visual verdict needs a named observer and the digest of its answer. Under
    ``engine-only`` (and in a record from before the block) no row carries what observers said."""
    block = doc.get("observers")
    rule = rule_of(doc)
    if rule == ENGINE_ONLY:
        if block is not None and block["visual"] is not None:
            raise RecordError("a visual observer is named but the rule is engine-only")
        if any("observed" in c for c in doc["checks"]):
            raise RecordError("a check says what observers said but the rule is engine-only")
        return
    for n, check in enumerate(doc["checks"]):
        seen = check.get("observed")
        if seen is None:
            raise RecordError(f"checks/{n}: the rule is both observers and the check does not say what each said")
        for side in ("before", "after"):
            said, result = seen[side], check[side]
            if (said is None) != (result is None):
                raise RecordError(f"checks/{n}: what the observers said {side} is given exactly when that side was judged")
            if said is None:
                continue
            if combine(said["engine"], said["visual"]) != result:
                raise RecordError(f"checks/{n}: the result {side} does not follow from what the two observers said")
            answered = said["visual"] in VISUAL_VERDICTS
            if answered and block["visual"] is None:
                raise RecordError(f"checks/{n}: a visual verdict is given and the record names no visual observer")
            if answered != (said["visualAnswerSha256"] is not None):
                raise RecordError(f"checks/{n}: the digest of the visual observer's answer is given exactly when it gave a verdict")
            if said["engine"] == "replay-error" and said["visual"] != "not-asked":
                raise RecordError(f"checks/{n}: a replay that did not finish has nothing for a visual observer to look at")


def check_repair(doc: dict) -> None:
    """The ``repair`` block agrees with the checks: it is there exactly when the change was declared a
    fix, it has one row for every check that failed before and passes after (and no other), each
    row's first run on each side is the check's own result, and whether a row counts, and how many
    do, is recomputed. So a record cannot call a repair demonstrated that its own runs do not show."""
    repair = doc.get("repair")
    if (repair is not None) != (intent_of(doc) == "fix"):
        raise RecordError("the repair block is given exactly when the change is declared a fix")
    if repair is None:
        return
    if repair["runs"] != REPAIR_RUNS:
        raise RecordError(f"a repair is judged on {REPAIR_RUNS} runs a side")
    want = [(c["spec"], c["route"]) for c in doc["checks"] if c["comparison"] == "REPAIRED"]
    if [(r["spec"], r["route"]) for r in repair["rows"]] != want:
        raise RecordError("the repair rows are not exactly the checks that failed before and pass after, in their order")
    for n, row in enumerate(repair["rows"]):
        if not row["base"] or not row["head"] or row["base"][0] != "fail" or row["head"][0] != "pass":
            raise RecordError(f"repair/rows/{n}: the first run on each side is the check's own result")
        if row["counts"] != row_counts(row):
            raise RecordError(f"repair/rows/{n}: whether it counts does not follow from its runs")
    if repair["demonstrated"] != sum(r["counts"] for r in repair["rows"]):
        raise RecordError("the count of demonstrations does not match the repair rows")


def repair_words(doc: dict) -> str:
    """One line on what the change was declared as and whether its repair was shown, for the page and the comment."""
    intent = intent_of(doc)
    if intent == "none":
        return "nothing declared: judged as a change that should break no check"
    if intent == "change":
        return "an intended change of behaviour: judged as a change that should break no check"
    repair = doc["repair"]
    if repair["demonstrated"]:
        row = next(r for r in repair["rows"] if r["counts"])
        more = repair["demonstrated"] - 1
        return (f"a fix, and the repair is demonstrated: {row['spec']} on {row['route']} failed before the change "
                f"{REPAIR_RUNS} times of {REPAIR_RUNS} and passes after it {REPAIR_RUNS} times of {REPAIR_RUNS}"
                + (f" (and {more} more)" if more else ""))
    return "a fix, and no check demonstrated the repair"


def check_generated(gen: dict) -> None:
    """The advisory generated-checks block (docs/jit.md) agrees with itself. It never enters ``decide``."""
    catches = gen["catches"]
    total = gen["strong"] + gen["weak"]
    if gen["status"] != "ran":
        if total or catches or gen["valid"]:
            raise RecordError("generated checks that did not run cannot report checks or catches")
        if gen["status"] == "not-run" and (gen["proposed"] or gen["reason"] is not None or gen["runSha256"] is not None):
            raise RecordError("generated checks that were not run have nothing to report")
        if gen["status"] == "nothing-generated" and not gen["reason"]:
            raise RecordError("nothing generated needs its reason")
    else:
        if gen["runSha256"] is None:
            raise RecordError("generated checks that ran name their record")
    if not gen["valid"] <= gen["proposed"] or not total <= gen["valid"]:
        raise RecordError("generated checks: catches <= valid <= proposed does not hold")
    if len(catches) != min(total, 10):
        raise RecordError("generated checks: the rows do not match the counts")
    for strength in ("strong", "weak"):
        if total <= 10 and sum(1 for c in catches if c["strength"] == strength) != gen[strength]:
            raise RecordError(f"generated checks: the {strength} rows do not match the count")
    ids = [c["specId"] for c in catches]
    if len(set(ids)) != len(ids):
        raise RecordError("generated checks: a check is listed twice")
