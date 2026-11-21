"""The public reproduction rate under the do-nothing validity rule (issue #285, with #675).

    python3 -m expectrail.repro control-rate --score <repro-score.json> --records <dir> \\
        --do-nothing-rows <rows.json> [--out page.md]

Nothing here calls a model or starts the engine.

A live score (expectrail/repro/score.py) counts a defect as reproduced when a kept check passes the clean
game 3 of 3 and fails the bug build 3 of 3. Since #675 the generator also drops a check that passes all 3
runs of the do-nothing control, the clean game with the check's actor doing nothing
(``assess.validity``): such a check states no obligation. Records made before that rule were never put to
the control. This reads the control's per-check rows (the ``rows.json`` of ``tools/do_nothing_public.py``,
read with the counting audit's reader) beside a score and its records, and says which reproduced defects
the rule keeps.

**Binding.** A row counts for a check only when it names this record (``sourceRun``, the record's
``digest_v1``) and this exact check (``specSha256``). Each record must be the file the score names
(``recordSha256``). A check with no bound row is ``unbound``.

**One defect.** Of its reproducing checks:

- ``reproduced``: at least one fails the control (shown to state an obligation);
- ``reproduced-indeterminate``: none fails it and at least one is indeterminate. The generator keeps an
  indeterminate check, so the rate counts the defect; the control did not show the check states anything;
- ``cannot-tell``: none fails or is indeterminate, and at least one was not run on the control or is
  unbound. The control has not judged the check that reproduces it, so it is in neither count;
- ``dropped``: every one passed the control. The rule would not have kept any, so it is not reproduced.

A defect the score did not reproduce stays ``not-reproduced``: the control only removes checks.

The pixel checks of a pixel score and a candidate-withheld score are refused here, not misread: the rows
are made for the baseline's trace checks.
"""
from __future__ import annotations

from pathlib import Path

from expectrail.contracts import digest_v1, strict_loads
from expectrail.jit import counting
from expectrail.jit.offer import BASELINE
from expectrail.repro import bench, score

HEADING = "## Reproduction rate under the do-nothing rule"
STATES = ("reproduced", "reproduced-indeterminate", "cannot-tell", "dropped", "not-reproduced")
CHECK_STATES = ("fails", "indeterminate", "not-run", "unbound", "passes")


class ControlRateError(ValueError):
    """The score, its records or the rows cannot be read together."""


def _check_state(row: dict | None, source: str, spec: dict) -> str:
    if row is None or row.get("sourceRun") != source or row.get("specSha256") != digest_v1(spec):
        return "unbound"
    return row["outcome"]


def _defect_state(checks: dict[str, list[str]]) -> str:
    if checks["fails"]:
        return "reproduced"
    if checks["indeterminate"]:
        return "reproduced-indeterminate"
    if checks["not-run"] or checks["unbound"]:
        return "cannot-tell"
    return "dropped"


def rate(score_path: Path, records_dir: Path, rows_path: Path) -> dict:
    """{source, defects: [...], totals} for the score at ``score_path``, its records under ``records_dir``
    (``repro-<id>/jit-run.json``) and the control's rows at ``rows_path``."""
    try:
        record = score.load(Path(score_path))
    except (OSError, ValueError) as exc:
        raise ControlRateError(f"the score cannot be read: {exc}"[:300]) from exc
    if record.get("candidate", score.SHOWN) != score.SHOWN or record["offer"] != BASELINE:
        raise ControlRateError("only a baseline score with the candidate shown is read here: the rows are made for "
                               "its trace checks")
    try:
        rows = counting.do_nothing_rows(rows_path)
    except (OSError, ValueError) as exc:
        raise ControlRateError(str(exc)[:300]) from exc
    defects = []
    for r in record["rows"]:
        out = {"id": r["id"], "visibility": r["visibility"], "tunedOn": r["tunedOn"],
               "legacy": r["outcome"], "state": "not-reproduced" if r["outcome"] != "reproduced" else None,
               "checks": {k: [] for k in CHECK_STATES}}
        defects.append(out)
        if r["outcome"] != "reproduced":
            continue
        path = Path(records_dir) / f"{score.CASE_PREFIX}{r['id']}" / "jit-run.json"
        try:
            sha = bench.sha256(path)
            run = strict_loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ControlRateError(f"{r['id']}: the record cannot be read ({type(exc).__name__})") from exc
        if sha != r["recordSha256"]:
            raise ControlRateError(f"{r['id']}: the record on disk is not the one the score names")
        source = digest_v1(run)
        specs = {e["spec"]["id"]: e["spec"] for e in run["proposed"]}
        for cid in r["reproducing"]:
            if cid not in specs:
                raise ControlRateError(f"{r['id']}: the score's reproducing check {cid} is not in the record")
            out["checks"][_check_state(rows.get((r["id"], cid)), source, specs[cid])].append(cid)
        out["checks"] = {k: sorted(v) for k, v in out["checks"].items()}
        out["state"] = _defect_state(out["checks"])
    return {"score": str(score_path), "source": record.get("source"), "defects": defects, "totals": totals(defects)}


def totals(defects: list[dict]) -> dict:
    def count(rows, *states):
        return sum(d["state"] in states for d in rows)

    visible = [d for d in defects if d["visibility"] in score.TRACE_VISIBLE]
    untuned = [d for d in defects if not d["tunedOn"]]
    kept = ("reproduced", "reproduced-indeterminate")
    return {
        "defects": len(defects),
        "legacyReproduced": sum(d["legacy"] == "reproduced" for d in defects),
        "reproduced": count(defects, *kept),
        "reproducedShown": count(defects, "reproduced"),
        "reproducedOnlyIndeterminate": count(defects, "reproduced-indeterminate"),
        "cannotTell": count(defects, "cannot-tell"),
        "dropped": count(defects, "dropped"),
        "traceVisible": len(visible),
        "legacyReproducedTraceVisible": sum(d["legacy"] == "reproduced" for d in visible),
        "reproducedTraceVisible": count(visible, *kept),
        "reproducedShownTraceVisible": count(visible, "reproduced"),
        "cannotTellTraceVisible": count(visible, "cannot-tell"),
        "untuned": len(untuned),
        "reproducedUntuned": count(untuned, *kept),
    }


def _share(n: int, of: int) -> str:
    return f"**{n}/{of}** ({100 * n / of:.2f}%)" if of else f"**{n}/0**"


def render(result: dict) -> str:
    t = result["totals"]
    lines = [
        HEADING, "",
        f"Reproduced under the do-nothing rule: {_share(t['reproduced'], t['defects'])} of all public defects; "
        f"trace-visible {_share(t['reproducedTraceVisible'], t['traceVisible'])}; "
        f"authored/untuned {_share(t['reproducedUntuned'], t['untuned'])}.",
        f"The score reproduced {t['legacyReproduced']}/{t['defects']} "
        f"({t['legacyReproducedTraceVisible']}/{t['traceVisible']} trace-visible). "
        f"Dropped: {t['dropped']}. Cannot tell: {t['cannotTell']} "
        f"({t['cannotTellTraceVisible']} trace-visible), counted in neither. "
        f"Kept only by indeterminate checks: {t['reproducedOnlyIndeterminate']}. Reproduced by a check that fails "
        f"the control, so shown to state an obligation: {_share(t['reproducedShown'], t['defects'])}; trace-visible "
        f"{_share(t['reproducedShownTraceVisible'], t['traceVisible'])}.", "",
        "| Public defect | Visibility | Under the rule | Reproducing checks: fail the control | indeterminate | "
        "not run | unbound | pass (dropped) |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for d in result["defects"]:
        if d["legacy"] != "reproduced":
            continue
        c = d["checks"]
        lines.append(f"| {d['id']} | {d['visibility']} | {d['state']} | {len(c['fails'])} | {len(c['indeterminate'])} | "
                     f"{len(c['not-run'])} | {len(c['unbound'])} | {len(c['passes'])} |")
    lines.append("")
    dropped = [d["id"] for d in result["defects"] if d["state"] == "dropped"]
    if dropped:
        lines.append("- Dropped (every reproducing check passed the control): "
                     + ", ".join(f"`{i}`" for i in dropped) + ".")
    for d in result["defects"]:
        if d["state"] == "cannot-tell":
            why = [f"`{c}` {'not run on the control' if k == 'not-run' else 'has no bound row'}"
                   for k in ("not-run", "unbound") for c in d["checks"][k]]
            lines.append(f"- Cannot tell, `{d['id']}`: " + "; ".join(why) + ".")
    return "\n".join(lines).rstrip() + "\n"
