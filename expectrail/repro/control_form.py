"""Why a check passes the do-nothing control, read from its form (issue #285, with #675).

    python3 -m expectrail.repro control-form --score <repro-score.json> --records <dir> \\
        --do-nothing-rows <rows.json> [--out page.md]

Nothing here calls a model or starts the engine. Advisory: it changes no rule and no record.

Under the do-nothing control the actor a check is about stands still. Whether a check can fail there is
mostly settled by the form of what it asserts, before any replay:

- ``holds-when-equal``: a relation between two probes whose comparator holds when the two probes measure
  the same value (``eq``, ``lte``, ``gte`` with a tolerance of zero or more). A still actor measures the
  same on both probes, so it cannot make the check fail.
- ``holds-when-still``: a bound on activity (``max_entity_drop``, ``max_episode_rise``, ``entity_present``,
  ``min_event_interval``). A still actor never drops, rises, vanishes or fires too often.
- ``fails-when-equal``: a relation whose comparator fails when the two probes measure the same value
  (``gt``, ``lt`` with a tolerance of zero or more). It asks the two probes to differ.
- ``needs-activity``: a demand a still actor cannot meet (``min_event_count``, ``min_motion_extent``,
  ``event_response``).
- ``other``: anything the form does not settle (``direction_agreement``, ``signal_compare``, an operation
  this does not know, a malformed relation). Never guessed.

A relation is judged with the evaluator's own comparator (``expectrail.trace.evaluator.COMPARATORS``) at two
equal arms, so a negative tolerance is read, not assumed. "Cannot fail when still" is not "passes the
control": the evaluator may find nothing to judge and the control then reports indeterminate.

The control's outcome per check is read from the rows of ``tools/do_nothing_public.py`` exactly as
expectrail/repro/control_rate.py reads them: a row counts only when it names this record (``sourceRun``)
and this exact check (``specSha256``), and each record must be the file the score names.
"""
from __future__ import annotations

from pathlib import Path

from expectrail.contracts import digest_v1, strict_loads
from expectrail.jit import counting
from expectrail.repro import bench, control_rate, score
from expectrail.trace.evaluator import COMPARATORS

HEADING = "## Why the dropped defects' checks state no obligation"
FORMS = ("holds-when-equal", "holds-when-still", "fails-when-equal", "needs-activity", "other")
STILL = ("holds-when-equal", "holds-when-still")      # a still actor cannot make these fail
DEMANDING = ("fails-when-equal", "needs-activity")   # a still actor cannot make these pass
OUTCOMES = ("fails", "indeterminate", "not-run", "passes", "unbound")
_HOLDS_WHEN_STILL = frozenset({"max_entity_drop", "max_episode_rise", "entity_present", "min_event_interval"})
_NEEDS_ACTIVITY = frozenset({"min_event_count", "min_motion_extent", "event_response"})


class ControlFormError(ValueError):
    """The score, its records or the rows cannot be read together."""


def form(spec: dict) -> str:
    """The form of one trace check (see the module text)."""
    op = spec.get("operation") if isinstance(spec, dict) else None
    kind = op.get("type") if isinstance(op, dict) else None
    if kind == "relation":
        compare, tol = COMPARATORS.get(op.get("comparator")), op.get("toleranceAbs")
        if compare is None or isinstance(tol, bool) or not isinstance(tol, (int, float)):
            return "other"
        return "holds-when-equal" if compare(0.0, 0.0, tol) else "fails-when-equal"
    if kind in _HOLDS_WHEN_STILL:
        return "holds-when-still"
    if kind in _NEEDS_ACTIVITY:
        return "needs-activity"
    return "other"


def _outcome(row: dict | None, source: str, spec: dict) -> str:
    if row is None or row.get("sourceRun") != source or row.get("specSha256") != digest_v1(spec):
        return "unbound"
    return row["outcome"]


def tally(score_path: Path, records_dir: Path, rows_path: Path) -> dict:
    """Every check of every record the score names, by form and control outcome, with the dropped and the
    shown defects from expectrail/repro/control_rate.py."""
    try:   # refuses a score, records or rows it cannot read together
        rated = control_rate.rate(score_path, records_dir, rows_path)
    except control_rate.ControlRateError as exc:
        raise ControlFormError(str(exc)) from exc
    record = score.load(Path(score_path))
    try:
        rows = counting.do_nothing_rows(rows_path)
    except (OSError, ValueError) as exc:
        raise ControlFormError(str(exc)[:300]) from exc
    forms = {f: dict.fromkeys(OUTCOMES, 0) for f in FORMS}
    reproducing = {f: dict.fromkeys(OUTCOMES, 0) for f in FORMS}
    per_defect, checks = {}, 0
    for r in record["rows"]:
        path = Path(records_dir) / f"{score.CASE_PREFIX}{r['id']}" / "jit-run.json"
        try:
            sha = bench.sha256(path)
            run = strict_loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ControlFormError(f"{r['id']}: the record cannot be read ({type(exc).__name__})") from exc
        if sha != r["recordSha256"]:
            raise ControlFormError(f"{r['id']}: the record on disk is not the one the score names")
        source, mine = digest_v1(run), set(r.get("reproducing") or [])
        seen = {"reproducing": {}, "failing": set(), "demanding": 0}
        for entry in run["proposed"]:
            spec = entry["spec"]
            f, outcome = form(spec), _outcome(rows.get((r["id"], spec["id"])), source, spec)
            checks += 1
            forms[f][outcome] += 1
            seen["demanding"] += f in DEMANDING
            if spec["id"] in mine:
                reproducing[f][outcome] += 1
                seen["reproducing"][f] = seen["reproducing"].get(f, 0) + 1
                if outcome == "fails":
                    seen["failing"].add(f)
        per_defect[r["id"]] = seen
    dropped = [{"id": d["id"], "visibility": d["visibility"], "reproducing": per_defect[d["id"]]["reproducing"],
                "demanding": per_defect[d["id"]]["demanding"]}
               for d in rated["defects"] if d["state"] == "dropped"]
    shown = [{"id": d["id"], "failingForms": sorted(per_defect[d["id"]]["failing"])}
             for d in rated["defects"] if d["state"] == "reproduced"]
    return {"score": str(score_path), "checks": checks, "forms": forms, "reproducing": reproducing,
            "dropped": dropped, "shown": shown}


def _table(counts: dict) -> list[str]:
    lines = ["| Form | Checks | Fail the control | Indeterminate | Not run | Pass (dropped) | No bound row |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for f in FORMS:
        c = counts[f]
        lines.append(f"| {f} | {sum(c.values())} | {c['fails']} | {c['indeterminate']} | {c['not-run']} | "
                     f"{c['passes']} | {c['unbound']} |")
    return lines


def render(result: dict) -> str:
    forms = result["forms"]
    still = {k: sum(forms[f][k] for f in STILL) for k in OUTCOMES}
    strict = forms["fails-when-equal"]
    lines = [
        HEADING, "",
        f"Of the {result['checks']} checks in the 24 baseline records, those a still actor satisfies by their form "
        f"(`holds-when-equal`, `holds-when-still`): {sum(still.values())}; **{still['fails']} fail the control**, "
        f"{still['passes']} pass it, {still['indeterminate']} are indeterminate. Strict relations "
        f"(`fails-when-equal`): {sum(strict.values())}; **{strict['passes']} pass the control**, "
        f"{strict['fails']} fail it.", "",
        "All checks, by form:", "",
        *_table(forms), "",
        "The reproducing checks of the reproduced defects, by form:", "",
        *_table(result["reproducing"]), "",
    ]
    for d in result["dropped"]:
        made = ", ".join(f"{n} `{f}`" for f, n in sorted(d["reproducing"].items()))
        lines.append(f"- Dropped, `{d['id']}`: reproduced only by {made}; checks of a demanding form in its "
                     f"record: {d['demanding']}.")
    for d in result["shown"]:
        lines.append(f"- Shown, `{d['id']}`: its reproducing checks that fail the control are "
                     + ", ".join(f"`{f}`" for f in d["failingForms"]) + ".")
    return "\n".join(lines).rstrip() + "\n"
