"""Job-local snapshots of spend's counters; holds are not a provider bill.

Normal workers run one job per process. Subtracting the entry snapshot also keeps
sequential in-process stand-ins from inheriting another job's usage or stop. This
does not reset or relax any sending cap. Concurrent model jobs need separate
worker processes, as runner.spawn provides.
"""
from __future__ import annotations

import json
import os
import threading

from expectrail import diagnostics, resources, spend
from expectrail.contracts import canonical_v1
from expectrail.gate import record


def schema() -> dict:
    return json.loads((resources.ROOT / "contracts/job-budget.v1.schema.json").read_text(encoding="utf-8"))


def check(doc: dict, job_id: str) -> None:
    """The same contract in the installed, standard-library-only reader."""
    canonical_v1(doc)
    record.validate(doc, schema())
    if doc["jobId"] != job_id:
        raise ValueError("the budget belongs to another job")
    seen = set()
    for row in doc["phases"]:
        if row["role"] in seen or row["phase"] != spend.PHASE_OF[row["role"]]:
            raise ValueError("the budget repeats a role or names its wrong phase")
        seen.add(row["role"])
        if row["stopped"] and not doc["stopped"]:
            raise ValueError("a stopped phase needs the budget's stop reason")
    if abs(sum(row["reservedUsd"] for row in doc["phases"]) - doc["totalReservedUsd"]) > 1e-6:
        raise ValueError("the budget total differs from its phases")


class JobCosts:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.start = spend.build_job_budget(job_id)
        self._stop: tuple[str, str] | None = None
        self._seen_stops: dict[str, str] = {}
        self._lock = threading.RLock()

    def stop(self, exc: spend.BudgetStop) -> None:
        with self._lock:
            # Invalid cap values are never copied into records, even when the
            # sender's exception contains one. build_job_budget supplies that reason.
            if exc.role not in spend.CAP_ENV:
                reason = "the spend budget stopped an unknown model role"
            else:
                try:
                    spend.parse_cap(exc.role)
                except spend.BudgetStop:
                    reason = f"{spend.CAP_ENV[exc.role]} is not an amount"
                else:
                    reason = diagnostics.redact(str(exc)) or "the spend budget stopped the job"
            self._stop = (exc.role, reason)
            spend.note_stop(exc.role, reason)

    def snapshot(self) -> dict:
        with self._lock:
            doc = spend.build_job_budget(self.job_id)
            before = {r["role"]: r for r in self.start["phases"]}
            rows = {r["role"]: dict(r) for r in doc["phases"]}
            for role, reason in self._seen_stops.items():
                row = rows.setdefault(role, {"role": role, "phase": spend.PHASE_OF[role],
                                              "reservedUsd": 0, "requests": 0})
                row["stopped"] = reason
            if self._stop and self._stop[0] in spend.ROLES:
                role, reason = self._stop
                row = rows.setdefault(role, {"role": role, "phase": spend.PHASE_OF[role],
                                              "reservedUsd": 0, "requests": 0})
                row["stopped"] = reason
            phases = []
            for role, row in rows.items():
                old = before.get(role, {})
                row["reservedUsd"] = round(row["reservedUsd"] - old.get("reservedUsd", 0), 6)
                row["requests"] -= old.get("requests", 0)
                if row["reservedUsd"] < 0 or row["requests"] < 0:
                    raise ValueError("spend counters went backwards during the job")
                invalid = doc["capsUsd"][role] is None and bool(os.environ.get(spend.CAP_ENV[role], "").strip())
                explicit = role in self._seen_stops or (self._stop is not None and self._stop[0] == role)
                if not invalid and not explicit and row["stopped"] == old.get("stopped"):
                    row["stopped"] = None
                if row["requests"] or row["reservedUsd"] or row["stopped"]:
                    phases.append(row)
                if row["stopped"]:
                    self._seen_stops.setdefault(role, row["stopped"])
            doc["phases"] = phases
            doc["totalReservedUsd"] = round(sum(row["reservedUsd"] for row in phases), 6)
            stops = list(dict.fromkeys(row["stopped"] for row in phases if row["stopped"]))
            if self._stop and self._stop[1] not in stops:
                stops.append(self._stop[1])
            doc["stopped"] = "; ".join(stops) or None
            check(doc, self.job_id)
            return doc


def words(status: dict) -> list[str]:
    doc = status.get("budget")
    if doc is None:
        return ["Budget: not recorded (older job)."]
    lines = [f"Budget: ${doc['totalReservedUsd']:.6f} recorded holds; not a provider bill."]
    for role, cap in doc["capsUsd"].items():
        lines.append(f"  {role} cap: " + ("unset or invalid (see stop)" if cap is None and doc["stopped"]
                                         else "unset" if cap is None else f"${cap:g}"))
    by_phase: dict[str, float] = {}
    for row in doc["phases"]:
        by_phase[row["phase"]] = by_phase.get(row["phase"], 0) + row["reservedUsd"]
    for phase, cost in by_phase.items():
        rows = [r for r in doc["phases"] if r["phase"] == phase]
        lines.append(f"  {phase}: ${cost:.6f} held (" + ", ".join(
            f"{r['role']}: {r['requests']} requests" for r in rows) + ")")
    if not by_phase:
        lines.append("  No model holds recorded.")
    if doc["stopped"]:
        lines.append(f"  Budget stop: {doc['stopped']}")
    if status["phase"] != "completed" or any(d["code"] == "EXECUTION_TIMEOUT" for d in status["diagnostics"]):
        lines.append("  Last recorded snapshot; interrupted work may have unrecorded holds.")
    return lines
