"""The miss breakdown of a live run on the public bench: the scorer's reasons, and the hand findings
for the misses no record can classify (issue #285, step 2).

    python3 -m expectrail.repro breakdown --score <dir>/repro-score.json [--hand bench/jit/public/hand-reasons.json]

Nothing here calls a model or starts the engine.

**Two sources, kept apart.** The scorer (expectrail/repro/score.py) gives a miss a reason only where a
run's records can show one, and ``undetermined`` where they cannot: the defect leaves the engine's
record unchanged on every library probe, so no record says whether no route reaches it or it shows
only on screen. Those were looked at by hand on November 12, 2026, before any live run, and are
written down in ``hand-reasons.json`` (``expectrail.repro-hand-reasons/v1``) with what was seen.

**The rule, fixed before the baseline's score was read.** A hand finding replaces a scorer's reason
only where that reason is ``undetermined``. A scorer's reason read from the records stands, and a
hand finding for that defect is shown beside it and changes no count. A reproduced defect keeps
its outcome whatever the hand file says. So the hand file can sort the misses the records cannot
sort, and can never move the rate or overrule a run.

A hand finding may give only the two reasons no record can separate: ``route-never-reaches`` and
``probe-language``. Every other reason in the vocabulary is the scorer's to give.
"""
from __future__ import annotations

import json
from pathlib import Path

from expectrail.contracts import ContractError, strict_loads
from expectrail.repro import bench, score

REPO = bench.REPO
SCHEMA = REPO / "contracts" / "repro-hand-reasons.v1.schema.json"
HAND = REPO / "bench" / "jit" / "public" / "hand-reasons.json"
FORMAT = "expectrail.repro-hand-reasons/v1"
HAND_REASONS = ("route-never-reaches", "probe-language")
MAX_BYTES = 64 * 1024
REASON_TEXT = {
    "route-never-reaches": "no route reaches the behaviour",
    "no-signal": "the record has it and no signal reads it",
    "probe-language": "the check language cannot express it (it shows only on screen)",
    "wrong-predicate": "a signal moves and no proposed check failed on the bug build",
    "flaky": "a check gave different outcomes on the same build",
    "budget": "the run ran out of budget",
    "undetermined": "the records cannot say, and there is no hand finding",
}


class BreakdownError(ValueError):
    """A hand-reasons record cannot be used, or does not fit the score it is read with."""


def problems(record) -> list[str]:
    """What is wrong with a hand-reasons record: the schema first, then what must agree inside it."""
    import jsonschema

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(record), key=lambda e: list(e.path))
    if errors:
        return [f"repro-hand-reasons: {'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}"[:300]
                for e in errors[:10]]
    out = []
    ids = [r["id"] for r in record["rows"]]
    if len(set(ids)) != len(ids):
        out.append("repro-hand-reasons: a defect is listed twice")
    for r in record["rows"]:
        if r["basis"] != score.one_line(r["basis"]):
            out.append(f"repro-hand-reasons: {r['id']}: basis is not one line of plain text")
    return out


def load(path: Path = HAND) -> dict:
    raw = Path(path).read_bytes()
    if len(raw) > MAX_BYTES:
        raise BreakdownError(f"repro-hand-reasons: over {MAX_BYTES} bytes")
    try:
        record = strict_loads(raw.decode("utf-8"))
    except (ValueError, ContractError) as exc:
        raise BreakdownError(f"repro-hand-reasons: unreadable: {exc}"[:300]) from exc
    found = problems(record)
    if found:
        raise BreakdownError("; ".join(found))
    return record


def unknown(hand: dict, doc: dict) -> list[str]:
    """Hand findings for a defect the bench does not have: [] when every one names a bench defect."""
    known = {d["id"] for d in doc["defects"]}
    return [f"{r['id']}: a hand finding for a defect the bench does not have" for r in hand["rows"]
            if r["id"] not in known]


def breakdown(scored: dict, hand: dict) -> list[dict]:
    """One row per defect of the score: its outcome, the reason the breakdown counts, and where it came from.

    ``source`` is ``scorer``, ``hand`` (a hand finding replaced ``undetermined``) or None (reproduced,
    or no result). ``hand`` carries the hand finding whenever there is one, used or not."""
    found = {r["id"]: r for r in hand["rows"]}
    rows = []
    for r in scored["rows"]:
        h = found.get(r["id"])
        row = {"id": r["id"], "outcome": r["outcome"], "reason": None, "source": None,
               "scorerReason": r["missReason"], "hand": h}
        if r["outcome"] == "not-reproduced":
            if r["missReason"] == "undetermined" and h is not None:
                row.update(reason=h["reason"], source="hand")
            else:
                row.update(reason=r["missReason"], source="scorer")
        rows.append(row)
    return rows


def counts(rows: list[dict]) -> dict:
    """Misses by reason, in the vocabulary's order, and how many of them rest on a hand finding."""
    out = {}
    for k in score.MISS_REASONS:
        n = sum(r["reason"] == k for r in rows)
        if n:
            out[k] = {"misses": n, "byHand": sum(r["reason"] == k and r["source"] == "hand" for r in rows)}
    return out


def render(scored: dict, hand: dict) -> str:
    """The breakdown as a page section: the counts, then one row per miss and per no result."""
    rows = breakdown(scored, hand)
    t = scored["totals"]
    c = counts(rows)
    lines = [f"## Why the misses were missed ({t['notReproduced']} not reproduced, {t['noResult']} no result)", "",
             "A reason comes from the run's records (the scorer) wherever they can show one. Where they cannot "
             "(`undetermined`), a hand finding written on November 12, 2026, before any live run, takes its place "
             "([`hand-reasons.json`](hand-reasons.json)). A hand finding never replaces a reason read from the "
             "records and never changes whether a defect was reproduced.", ""]
    if c:
        lines += ["| Reason | Misses | Of them by hand | Meaning |", "| --- | --- | --- | --- |"]
        for k, v in c.items():
            lines.append(f"| `{k}` | {v['misses']} | {v['byHand']} | {REASON_TEXT[k]} |")
    else:
        lines.append("No defect was missed.")
    lines.append("")
    misses = [r for r in rows if r["outcome"] != "reproduced"]
    if misses:
        lines += ["| Defect | Outcome | Counted as | From | Hand finding (November 12) |", "| --- | --- | --- | --- | --- |"]
        for r in misses:
            h = r["hand"]
            note = f"`{h['reason']}`: {score._code(h['basis'])}" if h else "-"
            if h and r["source"] == "scorer":
                note += " (shown only: the records give a reason)"
            lines.append(f"| `{r['id']}` | {r['outcome']} | {('`' + r['reason'] + '`') if r['reason'] else '-'} | "
                         f"{r['source'] or '-'} | {note} |")
    return "\n".join(lines) + "\n"
