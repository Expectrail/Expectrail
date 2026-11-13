"""Pair the same checks before and after a change, and say what the pair shows. Pure: no replays,
no model calls, no files except load_record.

A review runs the request's public checks twice: on the failing base (the request's seed alone) and
on the candidate (seed plus the patch). pair() joins the two runs claim by claim; review_status()
says what may be claimed from the pairs and the verifier's own decision.

    compare("fail", "pass") == "REPAIRED"

Policy (docs/review.md):
- A claim is primary when the repair request names its spec as failing. Only primary claims can
  show a repair; an optional check changing never qualifies.
- REPAIR DEMONSTRATED needs the verifier to accept, every required check to pass afterwards, every
  primary claim to be comparable and pass afterwards, and at least one primary claim to go from
  FAIL to PASS by the gate's rule (expectrail.gate.record.row_counts, issue #284): failing on the
  base and passing on the candidate REPAIR_RUNS times of REPAIR_RUNS, so the review and the gate
  say the same thing about the same runs. A primary claim that passed before and after (PRESERVED)
  shows nothing was repaired; one that went from FAIL to PASS on a single run, or not on every run,
  shows nothing either (NO REPAIR DEMONSTRATED, first reason ``repair-not-demonstrated``).
- REJECTED when the verifier rejects, or any required check fails afterwards.
- INCONCLUSIVE when a primary claim cannot be compared: missing, needs-review, or judged differently
  in the two arms (a different spec, route, evaluator or observer).
- NO REPAIR DEMONSTRATED when the evidence is complete and passing but no primary claim went from
  FAIL to PASS.
No status authorizes a merge or a release.
"""
from __future__ import annotations

import json
from pathlib import Path

from expectrail.gate import record as _gate  # one definition of a demonstrated repair, the gate's

FORMAT = "expectrail.change-evidence/v0"
RESULTS = ("pass", "fail")
COMPARISONS = ("REPAIRED", "PRESERVED", "REGRESSION", "UNRESOLVED", "INCONCLUSIVE")
STATUSES = ("REPAIR DEMONSTRATED", "NO REPAIR DEMONSTRATED", "REJECTED", "INCONCLUSIVE")
_TABLE = {("fail", "pass"): "REPAIRED", ("pass", "pass"): "PRESERVED",
          ("pass", "fail"): "REGRESSION", ("fail", "fail"): "UNRESOLVED"}
_NO_DIGEST = "0" * 64
REPAIR_RUNS = _gate.REPAIR_RUNS
NOT_DEMONSTRATED = _gate.NOT_DEMONSTRATED


def compare(before: str | None, after: str | None) -> str:
    """One claim's outcome before and after. Anything but pass or fail on either side (missing,
    needs-review, an execution failure) is INCONCLUSIVE: never read as a pass or a failure."""
    return _TABLE.get((before, after), "INCONCLUSIVE")


def _key(check: dict) -> tuple[str, str]:
    return check["spec"], check["route"]


def _index(checks: list[dict], arm: str) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for check in checks:
        if _key(check) in out:
            raise ValueError(f"{arm} arm judges {check['spec']} on {check['route']} twice; a claim is judged once")
        out[_key(check)] = check
    return out


def _digest(check: dict | None) -> str | None:
    sha = (check or {}).get("verdictSha256")
    return sha if sha and sha != _NO_DIGEST else None  # a missing verdict has no digest, never a zero one


def mismatch(base_ids: dict, candidate_ids: dict) -> list[str]:
    """Which parts of how the two arms were judged differ (empty: the arms are comparable)."""
    keys = sorted(set(base_ids) | set(candidate_ids))
    return [k for k in keys if base_ids.get(k) != candidate_ids.get(k)]


def pair(base_checks: list[dict], candidate_checks: list[dict], *, primary: set[str] | frozenset[str],
         base_ids: dict, candidate_ids: dict) -> list[dict]:
    """Join the two arms' checks on (spec, route); one row per claim judged in either arm, and one for
    every primary claim neither arm judged. When the arms were judged differently every row is
    INCONCLUSIVE and names the difference. Primary rows come first."""
    before, after = _index(base_checks, "the base"), _index(candidate_checks, "the candidate")
    differ = mismatch(base_ids, candidate_ids)
    keys = list(before) + [k for k in after if k not in before]
    routes = sorted({route for _spec, route in keys})
    for spec in sorted(primary):
        if not any(s == spec for s, _route in keys):
            keys.append((spec, routes[0] if len(routes) == 1 else "unknown"))
    rows = []
    for key in keys:
        b, a = before.get(key), after.get(key)
        row = {
            "spec": key[0],
            "kind": (b or a or {}).get("kind", "regression"),
            "route": key[1],
            "primary": key[0] in primary,
            "required": True,  # every public check the verifier makes must pass for it to accept
            "before": (b or {}).get("result"),
            "after": (a or {}).get("result"),
            "comparison": "INCONCLUSIVE" if differ else compare((b or {}).get("result"), (a or {}).get("result")),
            "evidence": {"before": _digest(b), "after": _digest(a)},
        }
        if differ:
            row["mismatch"] = differ
        rows.append(row)
    rows.sort(key=lambda r: (not r["primary"], r["kind"], r["spec"], r["route"]))
    return rows


def review_status(rows: list[dict], verification: dict, repair: dict | None = None) -> tuple[str, list[str]]:
    """The review's status and why, from the paired rows, the verifier's own decision and the ``repair``
    block (see repair_block). Without a repair block no repair is demonstrated: one run a side is not
    enough, whatever it shows."""
    decision = verification.get("decision")
    if decision == "reject":
        return "REJECTED", ["the verifier rejected the candidate: "
                            + "; ".join(verification.get("reasons") or ["no reason given"])]
    failed = [r for r in rows if r["required"] and r["after"] == "fail"]
    if failed:
        return "REJECTED", [f"{r['spec']} fails after the change ({r['comparison'].lower()})" for r in failed]
    primary = [r for r in rows if r["primary"]]
    if not primary:
        return "INCONCLUSIVE", ["no requested claim was judged in either arm"]
    unclear = [r for r in primary if r["comparison"] == "INCONCLUSIVE"]
    if unclear:
        return "INCONCLUSIVE", [_unclear(r) for r in unclear]
    if decision != "accept":
        return "INCONCLUSIVE", [f"the verifier's decision is {decision}, not accept"]
    pending = [r for r in rows if r["required"] and r["after"] != "pass"]
    if pending:
        return "INCONCLUSIVE", [f"{r['spec']} was not judged pass after the change" for r in pending]
    claims = repair_claims(rows)
    if not claims:
        return "NO REPAIR DEMONSTRATED", [f"{NOT_DEMONSTRATED}: no requested claim went from FAIL to PASS: "
                                          + ", ".join(f"{r['spec']} {r['comparison'].lower()}" for r in primary)]
    shown = demonstrations(rows, repair)
    if shown:
        return "REPAIR DEMONSTRATED", []
    if repair is None:
        return "NO REPAIR DEMONSTRATED", [
            f"{NOT_DEMONSTRATED}: {_claims_words(claims)} went from FAIL to PASS on one run, and was not replayed "
            f"{REPAIR_RUNS} times of {REPAIR_RUNS} on each side"]
    runs = {(r["spec"], r["route"]): r for r in repair["rows"]}
    detail = "; ".join(_runs_words(runs.get((c["spec"], c["route"])), c) for c in claims)
    return "NO REPAIR DEMONSTRATED", [
        f"{NOT_DEMONSTRATED}: {_claims_words(claims)} went from FAIL to PASS once, but not {REPAIR_RUNS} times of "
        f"{REPAIR_RUNS} on both sides ({detail})"]


def repair_claims(rows: list[dict]) -> list[dict]:
    """The rows that may demonstrate a repair: primary claims that went from FAIL to PASS on the first run.
    Only these are replayed again; an optional check changing never qualifies."""
    return [r for r in rows if r["primary"] and r["comparison"] == "REPAIRED"]


def repair_block(rows: list[dict], runs: dict[tuple[str, str], dict]) -> dict:
    """The record's ``repair`` block: one row per claim of repair_claims(rows), with every run on each side
    (``runs[(spec, route)]`` holds ``base`` and ``head`` lists whose first entries are the row's own
    before and after). Its shape and its counting are the gate's (expectrail.gate.record.repair_block)."""
    return _gate.repair_block([{"spec": r["spec"], "route": r["route"],
                                **runs.get((r["spec"], r["route"]), {"base": [r["before"]], "head": [r["after"]]})}
                               for r in repair_claims(rows)])


def demonstrations(rows: list[dict], repair: dict | None) -> list[dict]:
    """The repair rows that count, recomputed from their runs and only for claims the rows themselves
    show going from FAIL to PASS: a ``counts`` written in a record is never trusted."""
    if not repair:
        return []
    keys = {(r["spec"], r["route"]) for r in repair_claims(rows)}
    return [r for r in repair.get("rows") or [] if (r["spec"], r["route"]) in keys and _gate.row_counts(r)]


def _claims_words(claims: list[dict]) -> str:
    if len(claims) == 1:
        return claims[0]["spec"]
    return f"{len(claims)} requested claims"


def _runs_words(row: dict | None, claim: dict) -> str:
    if row is None:
        return f"{claim['spec']}: no runs recorded"
    return (f"{claim['spec']} before {', '.join(str(x) for x in row['base'])}; "
            f"after {', '.join(str(x) for x in row['head'])}")


def _unclear(row: dict) -> str:
    if row.get("mismatch"):
        return f"{row['spec']} cannot be compared: the arms differ in {', '.join(row['mismatch'])}"
    return f"{row['spec']} cannot be compared: before {row['before'] or 'missing'}, after {row['after'] or 'missing'}"


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r}")
        out[key] = value
    return out


def load_record(path: Path) -> dict:
    """Read a change-evidence record strictly: duplicate JSON keys, an unknown format or version,
    a schema violation or a claim listed twice is refused."""
    from expectrail.contracts import ContractError, validate

    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_keys)
    except ValueError as exc:
        raise ContractError(f"{path}: {exc}") from exc
    if validate(doc) != "change-evidence":
        raise ContractError(f"{path}: not a change-evidence record")
    keys = [(r["spec"], r["route"]) for r in doc["rows"]]
    if len(keys) != len(set(keys)):
        raise ContractError(f"{path}: a claim is listed twice")
    problem = repair_problem(doc)
    if problem:
        raise ContractError(f"{path}: {problem}")
    return doc


def repair_problem(doc: dict) -> str | None:
    """Why a record's ``repair`` block does not follow from its rows, or None when it does.

    The block has one row for every primary claim that went from FAIL to PASS (and no other), in the
    rows' order; each row's first run on each side is that claim's own before and after; whether a
    row counts, and how many do, is recomputed; and a record that says REPAIR DEMONSTRATED has at
    least one row that counts. A record written before the block existed (no ``repair`` key) is read
    as it was written: ``pre_repair_rule`` says so, and the page says the claim was judged once a side.
    """
    repair = doc.get("repair")
    if repair is None:
        return None
    if repair["runs"] != REPAIR_RUNS:
        return f"a repair is judged on {REPAIR_RUNS} runs a side"
    want = [(r["spec"], r["route"]) for r in repair_claims(doc["rows"])]
    if [(r["spec"], r["route"]) for r in repair["rows"]] != want:
        return "the repair rows are not exactly the requested claims that went from FAIL to PASS, in their order"
    before = {(r["spec"], r["route"]): (r["before"], r["after"]) for r in doc["rows"]}
    for n, row in enumerate(repair["rows"]):
        if (row["base"][0], row["head"][0]) != before[(row["spec"], row["route"])]:
            return f"repair/rows/{n}: the first run on each side is the claim's own before and after"
        if row["counts"] != _gate.row_counts(row):
            return f"repair/rows/{n}: whether it counts does not follow from its runs"
    if repair["demonstrated"] != sum(r["counts"] for r in repair["rows"]):
        return "the count of demonstrations does not match the repair rows"
    if doc["status"] == "REPAIR DEMONSTRATED" and not repair["demonstrated"]:
        return f"the status is REPAIR DEMONSTRATED but no claim failed before and passed after {REPAIR_RUNS} times of {REPAIR_RUNS}"
    return None


def pre_repair_rule(doc: dict) -> bool:
    """A record written before reviews replayed a claimed repair (it has no ``repair`` block)."""
    return "repair" not in doc
