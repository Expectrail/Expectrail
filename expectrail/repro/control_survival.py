"""Survival under the do-nothing control, and the form histogram, read from a live run's own records
(issue #285, with #675).

    python3 -m expectrail.repro control-survival --run <repro-score.json> <records-dir> \\
        [--run <repro-score.json> <records-dir> ...] [--out page.md]

Nothing here calls a model or starts the engine. Advisory: it changes no rule and no record.

``docs/repro-audit.md`` states, before the control run, the three numbers the control setting is read on
against the menu setting. This reads two of them from each run's records, where the generator wrote its
own do-nothing rows (``validity[].doNothing``, expectrail/jit/run.py ``_do_nothing_stage``):

1. **Survival.** Each proposed check falls in exactly one of these, from its validity row:

   - ``no-row``: the record has no validity row for it (it never reached the reference runs).
   - ``absent``: its validity row has no do-nothing row: the record was made before the control.
   - ``off-reference``: it did not pass the clean game 3 of 3, so the control was not run for it.
   - ``not-run``: it passed the clean game, and the control was not run (no control was given or made).
   - ``passes``, ``fails``, ``indeterminate``: the control's outcome (``assess.do_nothing``).

   *Survival, as stated* is the audit's own definition: of the checks proposed, the share not ``passes``.
   It also counts checks the control never judged, so a prompt that made checks fail the clean game would
   raise it. *Survival, of those judged* is ``fails`` and ``indeterminate`` over ``passes``, ``fails`` and
   ``indeterminate``. Both are given; neither is a number when any record is ``absent`` (cannot tell), and
   the second is not one when the control judged nothing.
2. **Valid catches** are the score's: its reproducing checks and reproduced defects. Under today's
   generator a reproducing check has already survived the control; this refuses a record where one did not.
3. **The form histogram:** the proposed checks by operation (a relation by its comparator) and by the forms
   of expectrail/repro/control_form.py, each form split by control outcome.

**Fails closed.** A record that disagrees with itself gives no number: a do-nothing outcome its own runs
do not give, a check kept valid after it passed the control, a control run for a check that failed the
clean game, an outcome this does not know, a validity row for a check not proposed or given twice, a
reproducing check with no validity row, a record that is not the file the score names, a record made with
another setting than the score's, or some records with do-nothing rows and some without.

Only the trace checks (``proposed``) are read; a pixel setting's screen checks are not.
"""
from __future__ import annotations

from pathlib import Path

from expectrail.contracts import strict_loads
from expectrail.jit import assess
from expectrail.repro import bench, control_form, score

HEADING = "## Survival under the do-nothing control, from a run's own records"
OUTCOMES = ("passes", "fails", "indeterminate", "not-run", "off-reference", "no-row", "absent")
JUDGED = ("passes", "fails", "indeterminate")
_CONTROL = ("passes", "fails", "indeterminate", "not-run")


class ControlSurvivalError(ValueError):
    """The score and its records cannot be read together, or a record disagrees with itself."""


def operation(spec: dict) -> str:
    op = spec.get("operation") if isinstance(spec, dict) else None
    kind = op.get("type") if isinstance(op, dict) else None
    if not isinstance(kind, str):
        return "(none)"
    if kind == "relation":
        return f"relation {op.get('comparator')}"
    return kind


def _on_reference(reference: list, reps: int) -> bool:
    return assess.all_of(reference, "pass", reps)


def _outcome(did: str, sid: str, v: dict | None, reps: int) -> str:
    if v is None:
        return "no-row"
    if "doNothing" not in v:
        return "absent"
    row = v["doNothing"]
    if not isinstance(row, dict) or row.get("outcome") not in _CONTROL or not isinstance(row.get("runs"), list):
        raise ControlSurvivalError(f"{did}: {sid}: a do-nothing row this cannot read")
    if not _on_reference(v.get("reference") or [], reps):
        if row["runs"] or row["outcome"] != "not-run":
            raise ControlSurvivalError(f"{did}: {sid}: the control ran for a check that failed the clean game")
        return "off-reference"
    if assess.do_nothing(row["runs"], reps) != row["outcome"]:
        raise ControlSurvivalError(f"{did}: {sid}: its do-nothing outcome disagrees with its own runs")
    if row["outcome"] == "passes" and v.get("valid"):
        raise ControlSurvivalError(f"{did}: {sid}: kept valid after it passed the do-nothing control")
    return row["outcome"]


def read(score_path: Path, records_dir: Path) -> dict:
    """Every proposed check of every record the score names, by control outcome and form."""
    try:
        record = score.load(Path(score_path))
    except score.ScoreError as exc:
        raise ControlSurvivalError(str(exc)) from exc
    reps = record["reps"]
    outcomes = dict.fromkeys(OUTCOMES, 0)
    forms = {f: dict.fromkeys(OUTCOMES, 0) for f in control_form.FORMS}
    operations: dict[str, int] = {}
    with_rows, without_rows = [], []
    proposed = catches = reproduced = 0
    for r in record["rows"]:
        if not r.get("recordSha256"):
            continue  # no result: the score has no record for this defect
        did = r["id"]
        path = Path(records_dir) / f"{score.CASE_PREFIX}{did}" / "jit-run.json"
        try:
            sha = bench.sha256(path)
            run = strict_loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ControlSurvivalError(f"{did}: the record cannot be read ({type(exc).__name__})") from exc
        if sha != r["recordSha256"]:
            raise ControlSurvivalError(f"{did}: the record on disk is not the one the score names")
        if (run.get("settings") or {}).get("offer", "baseline") != record["offer"]:
            raise ControlSurvivalError(f"{did}: the record was made with another setting than the score's")
        specs = {e["spec"]["id"]: e["spec"] for e in run["proposed"]}
        rows: dict[str, dict] = {}
        for v in run["validity"]:
            sid = v.get("specId")
            if sid not in specs:
                raise ControlSurvivalError(f"{did}: a validity row for {sid}, which was not proposed")
            if sid in rows:
                raise ControlSurvivalError(f"{did}: {sid} has a validity row twice")
            rows[sid] = v
        has = {"doNothing" in v for v in run["validity"]}
        if has == {True, False}:
            raise ControlSurvivalError(f"{did}: some validity rows have a do-nothing row and some do not")
        if has:
            (with_rows if True in has else without_rows).append(did)
        mine = set(r.get("reproducing") or [])
        for sid, spec in specs.items():
            got = _outcome(did, sid, rows.get(sid), reps)
            if sid in mine and got in ("passes", "no-row"):
                raise ControlSurvivalError(f"{did}: {sid} reproduces, and its record says {got}")
            proposed += 1
            outcomes[got] += 1
            forms[control_form.form(spec)][got] += 1
            key = operation(spec)
            operations[key] = operations.get(key, 0) + 1
        catches += len(mine)
        reproduced += r["outcome"] == "reproduced"
    if with_rows and without_rows:
        raise ControlSurvivalError("some records have do-nothing rows and some do not: "
                                   + ", ".join(without_rows[:5]) + " have none")
    judged = sum(outcomes[k] for k in JUDGED)
    cannot_tell = outcomes["absent"] > 0
    survival = {
        "stated": None if cannot_tell or not proposed else (proposed - outcomes["passes"], proposed),
        "judged": None if cannot_tell or not judged else (judged - outcomes["passes"], judged),
    }
    label = record["offer"] + (f", {record['source']}" if record.get("source") else "")
    return {"score": str(score_path), "label": label, "offer": record["offer"], "proposed": proposed,
            "outcomes": outcomes, "survival": survival, "forms": forms,
            "operations": dict(sorted(operations.items())),
            "catches": {"checks": catches, "defects": reproduced, "of": len(record["rows"])}}


def _share(pair) -> str:
    if pair is None:
        return "cannot tell"
    n, of = pair
    return f"{n}/{of} ({100 * n / of:.1f}%)"


def render(results: list[dict]) -> str:
    head = "| | " + " | ".join(score._code(r["label"]) for r in results) + " |"
    rule = "| --- |" + " ---: |" * len(results)

    def row(name, cell):
        return f"| {name} | " + " | ".join(cell(r) for r in results) + " |"

    lines = [
        HEADING, "",
        "Read with `python3 -m expectrail.repro control-survival` from each run's records and score; no model, "
        "no engine. *As stated* counts every proposed check; *of those judged* counts only the checks the "
        "control ran for. \"cannot tell\" means a record predates the control, or the control judged nothing.", "",
        head, rule,
        row("Proposed checks", lambda r: str(r["proposed"])),
        row("Survival, as stated", lambda r: _share(r["survival"]["stated"])),
        row("Survival, of those judged", lambda r: _share(r["survival"]["judged"])),
        *[row(f"Control: `{k}`", lambda r, k=k: str(r["outcomes"][k])) for k in OUTCOMES],
        row("Valid catches: reproducing checks", lambda r: str(r["catches"]["checks"])),
        row("Valid catches: defects reproduced", lambda r: f"{r['catches']['defects']}/{r['catches']['of']}"),
        "", "Proposed checks by operation:", "", head, rule,
    ]
    for key in sorted({k for r in results for k in r["operations"]}):
        lines.append(row(f"`{key}`", lambda r, k=key: str(r["operations"].get(k, 0))))
    lines += ["", "Proposed checks by form, with how many passed the control:", "", head, rule]
    for f in control_form.FORMS:
        lines.append(row(f"`{f}`", lambda r, f=f: (
            f"{sum(r['forms'][f].values())} ({r['forms'][f]['passes']} pass)"
            if not r["outcomes"]["absent"] else f"{sum(r['forms'][f].values())} (cannot tell)")))
    return "\n".join(lines).rstrip() + "\n"
