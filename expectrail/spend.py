"""Spend caps for the model roles, the job's budget record, and the vision month.

Vision (SAM) is already counted in ``agents.sam_observations`` against
``EXPECTRAIL_SAM_USD_CAP``. This module does the same for the other roles that
send a request: Glimmer, Muse and triage. Each hold is taken before the request
is sent. A missing cap, a cap that is not an amount, or a hold that would pass
the cap stops the request and says why. Nothing is sent in those cases.

A hold is not a vendor bill. Vision images use Meta's list price in
``agents.sam_observations``. The other roles hold a fixed amount, named in the
provider capability record, because the bill is not known until the provider
answers.

    python3 -m expectrail.spend job-budget JOB_ID --out runs/job-budget.json
    python3 -m expectrail.spend month-check --cap 0.50

The month's vision total is Sean's limit of $200. It lives in the file
``EXPECTRAIL_VISION_MONTH_LEDGER`` points at, which is outside this repository
so a pull request cannot write it. With that variable unset the month is not
counted and SAM behaves as it did. With it set, a run whose cap would take the
month past $200 is refused before a request is sent, and the run's whole cap
is reserved (the worst case), not the images that happened to be sent.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from expectrail import resources
from expectrail.contracts import ContractError, canonical_v1, strict_loads

FORMAT_BUDGET = "expectrail.job-budget/v1"
FORMAT_MONTH = "expectrail.vision-month/v1"
FORMAT_CAPABILITY = "expectrail.provider-capability/v1"

# Sean's limit for vision, November 12: $200 in a calendar month and never more.
VISION_MONTH_LIMIT_USD = 200.0
LEDGER_ENV = "EXPECTRAIL_VISION_MONTH_LEDGER"
JOB_ENV = "EXPECTRAIL_JOB_ID"

ROLES = ("vision", "glimmer", "muse", "triage")
PHASE_OF = {"vision": "observing", "glimmer": "observing", "muse": "fixing", "triage": "triaging"}
CAP_ENV = {
    "vision": "EXPECTRAIL_SAM_USD_CAP",
    "glimmer": "EXPECTRAIL_GLIMMER_USD_CAP",
    "muse": "EXPECTRAIL_MUSE_USD_CAP",
    "triage": "EXPECTRAIL_TRIAGE_USD_CAP",
}
# Holds taken before a request whose bill is not known yet. Vision's per-image
# price stays in agents.sam_observations; this figure is what the capability
# record publishes for that role.
RESERVE_USD = {
    "vision": 2.50 / 1000,
    "glimmer": 0.05,
    "muse": 1.0,
    "triage": 0.05,
}

SCHEMAS = resources.ROOT / "contracts"
_SCHEMA_FILE = {
    "job-budget": "job-budget.v1.schema.json",
    "vision-month": "vision-month.v1.schema.json",
    "provider-capability": "provider-capability.v1.schema.json",
}


class BudgetStop(Exception):
    """The request was not sent. ``role`` is the model role; the message is the reason.

    Not a ``RuntimeError``: callers that turn a model failure into an offline
    fallback must not swallow a stop. A stop is the outcome, not a fallback.
    """

    def __init__(self, message: str, *, role: str):
        super().__init__(message)
        self.role = role
        self.kind = "budget"


def _finite_amount(raw: str, name: str, role: str) -> float:
    try:
        cap = float(raw)
    except ValueError:
        cap = float("nan")
    if not (0.0 <= cap < float("inf")):
        raise BudgetStop(f"{name} must be an amount in US dollars, 0 or more; it is {raw!r}", role=role)
    return cap


def parse_cap(role: str) -> float | None:
    """The role's cap from the environment, or None when it is unset.

    A value that is not an amount of 0 or more is a stop, never "no cap".
    """
    name = CAP_ENV[role]
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    return _finite_amount(raw, name, role)


class _Role:
    def __init__(self) -> None:
        self.reserved = 0.0
        self.requests = 0
        self.stopped: str | None = None


class Meter:
    """What this process has held for each role."""

    def __init__(self) -> None:
        self.roles = {role: _Role() for role in ROLES}
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self.roles = {role: _Role() for role in ROLES}

    def reserve(self, role: str, usd: float, *, live: bool) -> None:
        """Hold ``usd`` before a request. A live call with no cap is not sent.

        A stand-in (a test's transport, a recorded answer) is not held to a cap
        that was never set: that is how the SAM counter already works. A cap
        that is set applies to both.
        """
        if role not in self.roles:
            raise BudgetStop(f"unknown model role {role!r}", role=role)
        if not (0.0 < usd < float("inf")):
            raise BudgetStop(f"a hold must be a finite amount above 0, not {usd!r}", role=role)
        cap = parse_cap(role)
        with self._lock:
            row = self.roles[role]
            if cap is None:
                if not live:
                    return
                message = (f"no spend cap for {role}: set {CAP_ENV[role]} to the most this run may spend, "
                           "in US dollars. Nothing is sent without one")
                row.stopped = message
                raise BudgetStop(message, role=role)
            if row.reserved + usd > cap + 1e-9:
                message = (f"this run's {role} spend cap is reached: ${row.reserved:.4f} counted of "
                           f"${cap:.2f} ({CAP_ENV[role]}), and the next request holds ${usd:.4f}; "
                           "it was not sent")
                row.stopped = message
                raise BudgetStop(message, role=role)
            row.reserved += usd
            row.requests += 1

    def snapshot_roles(self) -> dict[str, dict]:
        with self._lock:
            return {role: {"reserved": row.reserved, "requests": row.requests, "stopped": row.stopped}
                    for role, row in self.roles.items()}


METER = Meter()
_month_lock = threading.Lock()
_month_status: dict = {
    "limitUsd": VISION_MONTH_LIMIT_USD,
    "spentUsd": 0.0,
    "runWorstCaseUsd": None,
    "admitted": False,
}
# This process has already reserved its vision cap against a ledger. A second image must not
# reserve the cap again.
_vision_run_reserved = False


def reset_for_tests() -> None:
    """Drop this process's holds and the remembered month check. Tests only."""
    global _month_status, _vision_run_reserved
    METER.reset()
    with _month_lock:
        _vision_run_reserved = False
        _month_status = {
            "limitUsd": VISION_MONTH_LIMIT_USD,
            "spentUsd": 0.0,
            "runWorstCaseUsd": None,
            "admitted": False,
        }


def note_stop(role: str, message: str) -> None:
    """Remember why ``role`` stopped, so the job budget can say it. Does not hold."""
    if role not in METER.roles:
        return
    with METER._lock:
        row = METER.roles[role]
        if row.stopped is None:
            row.stopped = message


def hold(role: str, *, live: bool, usd: float | None = None) -> None:
    """Hold one request of ``role`` before it is sent."""
    METER.reserve(role, RESERVE_USD[role] if usd is None else usd, live=live)


def require_cap(role: str) -> float:
    """The cap, or a stop when it is missing or not an amount. Does not hold."""
    cap = parse_cap(role)
    if cap is None:
        raise BudgetStop(
            f"no spend cap for {role}: set {CAP_ENV[role]} to the most this run may spend, "
            "in US dollars. Nothing is sent without one",
            role=role,
        )
    return cap


def _validate(doc: dict, kind: str) -> None:
    import jsonschema

    canonical_v1(doc)
    schema = json.loads((SCHEMAS / _SCHEMA_FILE[kind]).read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.path) or "(root)"
        raise ContractError(f"{kind}: {where}: {first.message}")


def _check_budget(doc: dict) -> None:
    _validate(doc, "job-budget")
    total = 0.0
    for phase in doc["phases"]:
        if PHASE_OF[phase["role"]] != phase["phase"]:
            raise ContractError(
                f"job-budget: role {phase['role']} belongs to phase {PHASE_OF[phase['role']]}, "
                f"not {phase['phase']}"
            )
        total += phase["reservedUsd"]
    if abs(total - doc["totalReservedUsd"]) > 1e-6:
        raise ContractError(
            f"job-budget: totalReservedUsd is {doc['totalReservedUsd']}, phases sum to {total}"
        )
    if doc["visionMonth"]["limitUsd"] != VISION_MONTH_LIMIT_USD:
        raise ContractError(f"job-budget: vision month limit is ${VISION_MONTH_LIMIT_USD:.0f}")


def write_job_budget(doc: dict, path: Path | None = None) -> dict:
    """Validate and optionally write a job budget. Returns the document."""
    _check_budget(doc)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def read_job_budget(path: Path) -> dict:
    doc = strict_loads(Path(path).read_text(encoding="utf-8"))
    _check_budget(doc)
    return doc


def _vision_reserved() -> tuple[float, int]:
    """What SAM has already held in this process, if that counter is loaded."""
    try:
        from agents.sam_observations import sam_usage
    except Exception:  # noqa: BLE001 — a tree without the adapter has held nothing
        return 0.0, 0
    usage = sam_usage()
    return float(usage.get("reservedUsd") or 0.0), int(usage.get("requests") or 0)


def build_job_budget(job_id: str, *, month: dict | None = None) -> dict:
    """The budget record for this process: caps, and what each phase has held."""
    roles = METER.snapshot_roles()
    vision_usd, vision_requests = _vision_reserved()
    roles["vision"] = {
        "reserved": vision_usd,
        "requests": vision_requests,
        "stopped": roles["vision"]["stopped"],
    }
    phases = []
    stopped = None
    for role in ROLES:
        row = roles[role]
        if row["stopped"] and stopped is None:
            stopped = row["stopped"]
        if row["requests"] == 0 and row["reserved"] == 0 and row["stopped"] is None:
            continue
        phases.append({
            "phase": PHASE_OF[role],
            "role": role,
            "reservedUsd": round(row["reserved"], 6),
            "requests": row["requests"],
            "stopped": row["stopped"],
        })
    with _month_lock:
        remembered = dict(_month_status)
    month = month or remembered
    doc = {
        "format": FORMAT_BUDGET,
        "jobId": job_id,
        "capsUsd": {role: parse_cap(role) for role in ROLES},
        "phases": phases,
        "totalReservedUsd": round(sum(p["reservedUsd"] for p in phases), 6),
        "stopped": stopped,
        "visionMonth": {
            "limitUsd": VISION_MONTH_LIMIT_USD,
            "spentUsd": round(float(month.get("spentUsd") or 0.0), 6),
            "runWorstCaseUsd": month.get("runWorstCaseUsd"),
            "admitted": bool(month.get("admitted")),
        },
    }
    return write_job_budget(doc)


def _check_capability(doc: dict) -> None:
    _validate(doc, "provider-capability")
    seen = set()
    for role in doc["roles"]:
        if role["role"] in seen:
            raise ContractError(f"provider-capability: {doc['provider']} lists {role['role']} twice")
        seen.add(role["role"])
        if role["capEnv"] != CAP_ENV[role["role"]]:
            raise ContractError(
                f"provider-capability: {role['role']} is capped by {CAP_ENV[role['role']]}, "
                f"not {role['capEnv']}"
            )
        if abs(role["reserveUsd"] - RESERVE_USD[role["role"]]) > 1e-9:
            raise ContractError(
                f"provider-capability: {role['role']} holds ${RESERVE_USD[role['role']]}, "
                f"not {role['reserveUsd']}"
            )


def write_provider_capability(doc: dict, path: Path | None = None) -> dict:
    _check_capability(doc)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def read_provider_capability(path: Path) -> dict:
    doc = strict_loads(Path(path).read_text(encoding="utf-8"))
    _check_capability(doc)
    return doc


def _blank_month(month: str) -> dict:
    return {
        "format": FORMAT_MONTH,
        "month": month,
        "limitUsd": VISION_MONTH_LIMIT_USD,
        "spentUsd": 0.0,
        "entries": [],
    }


def _check_month_doc(doc: dict) -> None:
    _validate(doc, "vision-month")
    if doc["limitUsd"] != VISION_MONTH_LIMIT_USD:
        raise ContractError(f"vision-month: the limit is ${VISION_MONTH_LIMIT_USD:.0f}")
    total = sum(entry["reservedUsd"] for entry in doc["entries"])
    if abs(total - doc["spentUsd"]) > 1e-6:
        raise ContractError(f"vision-month: spentUsd is {doc['spentUsd']}, entries sum to {total}")


def month_of(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


def _load_month(text: str, month: str) -> dict:
    if not text.strip():
        return _blank_month(month)
    doc = strict_loads(text)
    _check_month_doc(doc)
    if doc["month"] != month:
        return _blank_month(month)
    return doc


def admit_vision_month(cap_usd: float, *, path: Path | None = None, job_id: str | None = None,
                       now: datetime | None = None) -> dict:
    """Reserve this run's whole vision cap against the month, or refuse.

    ``path`` defaults to ``EXPECTRAIL_VISION_MONTH_LEDGER``. When that is unset
    and ``path`` is None, the month is not counted and the call reports
    ``admitted`` false: SAM's own cap still applies. A cap that would take the
    month past $200 is not reserved and raises ``BudgetStop``.
    """
    global _month_status
    if not (0.0 <= cap_usd < float("inf")):
        raise BudgetStop(f"a vision run's worst case must be an amount of 0 or more, not {cap_usd!r}",
                         role="vision")
    raw = str(path) if path is not None else os.environ.get(LEDGER_ENV, "").strip()
    if not raw:
        with _month_lock:
            _month_status = {
                "limitUsd": VISION_MONTH_LIMIT_USD,
                "spentUsd": 0.0,
                "runWorstCaseUsd": cap_usd,
                "admitted": False,
            }
            return dict(_month_status)
    ledger = Path(raw)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    job_id = job_id or os.environ.get(JOB_ENV, "").strip() or "run"
    now = now or datetime.now(timezone.utc)
    month = month_of(now)
    with _month_lock:
        global _vision_run_reserved
        if _vision_run_reserved:
            return dict(_month_status)
        with ledger.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.seek(0)
            doc = _load_month(handle.read(), month)
            spent = doc["spentUsd"]
            if spent + cap_usd > VISION_MONTH_LIMIT_USD + 1e-9:
                raise BudgetStop(
                    f"this month's vision spend would pass ${VISION_MONTH_LIMIT_USD:.0f}: "
                    f"${spent:.4f} already reserved in {month}, and this run's cap is ${cap_usd:.4f}. "
                    "The run was not started",
                    role="vision",
                )
            doc["entries"].append({
                "jobId": job_id,
                "reservedUsd": round(float(cap_usd), 6),
                "at": now.astimezone(timezone.utc).isoformat(),
            })
            doc["spentUsd"] = round(spent + float(cap_usd), 6)
            _check_month_doc(doc)
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(doc, indent=2) + "\n")
            handle.flush()
        status = {
            "limitUsd": VISION_MONTH_LIMIT_USD,
            "spentUsd": doc["spentUsd"],
            "runWorstCaseUsd": round(float(cap_usd), 6),
            "admitted": True,
        }
        _month_status = dict(status)
        _vision_run_reserved = True
        return status


def read_vision_month(path: Path) -> dict:
    doc = strict_loads(Path(path).read_text(encoding="utf-8"))
    _check_month_doc(doc)
    return doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m expectrail.spend")
    sub = parser.add_subparsers(dest="cmd", required=True)
    job = sub.add_parser("job-budget", help="write this process's job budget record")
    job.add_argument("job_id")
    job.add_argument("--out", type=Path, required=True)
    month = sub.add_parser("month-check", help="reserve a vision cap against the month, or say why not")
    month.add_argument("--cap", type=float, required=True)
    month.add_argument("--ledger", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "job-budget":
            doc = build_job_budget(args.job_id)
            write_job_budget(doc, args.out)
            print(f"wrote {args.out} ({doc['totalReservedUsd']:.4f} USD reserved)")
            return 0
        status = admit_vision_month(args.cap, path=args.ledger)
    except (BudgetStop, ContractError, OSError) as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return 1
    if status["admitted"]:
        print(f"admitted: ${status['runWorstCaseUsd']:.4f} against ${status['spentUsd']:.4f} "
              f"of ${status['limitUsd']:.0f} this month")
    else:
        print(f"not counted: {LEDGER_ENV} is unset, so the ${VISION_MONTH_LIMIT_USD:.0f} month was not checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
