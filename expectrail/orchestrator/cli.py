"""Verification as a job, from the command line.

    python3 -m expectrail.orchestrator verify --head . --game game/platformer \\
        --routes 'harness/routes/*.json' --specs agents/specs [--base ../base] [--detach] [--json]
    python3 -m expectrail.orchestrator status JOB [--json]
    python3 -m expectrail.orchestrator cancel JOB
    python3 -m expectrail.orchestrator report JOB
    python3 -m expectrail.orchestrator sample [--json]     three real runs on the bundled game

Jobs are kept under ``--jobs-root`` (default: $EXPECTRAIL_JOBS, else runs/jobs here). `verify` waits for
the job unless ``--detach`` is given; then it prints the job's id and returns.

Exit code: 0 accept, 1 reject, 2 needs review, 3 the job failed (no result), 4 cancelled, 5 the
command could not be carried out. 1 only ever means a job that completed as reject. `sample` exits 0
when all three runs decide as a working install does, and 3 otherwise: it is a check of the install,
not a verdict on a change.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from expectrail.orchestrator import request as req
from expectrail.orchestrator import runner
from expectrail.orchestrator import sample as smp
from expectrail.orchestrator import store as st

EXIT = {"accept": 0, "reject": 1, "needs-review": 2}
EXIT_FAILED, EXIT_CANCELLED, EXIT_USAGE = 3, 4, 5


def exit_code(status: dict) -> int:
    if status["phase"] == "completed":
        return EXIT[status["decision"]]
    return {"failed": EXIT_FAILED, "cancelled": EXIT_CANCELLED}.get(status["phase"], EXIT_USAGE)


def describe(status: dict) -> str:
    lines = [f"job {status['id']}: {status['phase']}" + (f", {status['decision']}" if status["decision"] else "")]
    lines += [f"  {reason}" for reason in status["reasons"]]
    lines += [f"  {d['code']} ({d['stage']}): {d['detail']} Fix: {d['fix']}" for d in status["diagnostics"]]
    if status["evidenceGrade"]:
        lines.append(f"  evidence grade: {status['evidenceGrade']}")
    return "\n".join(lines)


def _store(args) -> st.JobStore:
    root = args.jobs_root or os.environ.get("EXPECTRAIL_JOBS") or "runs/jobs"
    return st.JobStore(Path(root), lease_seconds=args.lease_seconds)


def _show(status: dict, as_json: bool) -> None:
    print(json.dumps(status, indent=2) if as_json else describe(status))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python3 -m expectrail.orchestrator", description=__doc__.splitlines()[0])
    p.add_argument("--jobs-root", help="where jobs are kept (default: $EXPECTRAIL_JOBS, else runs/jobs)")
    p.add_argument("--lease-seconds", type=float, default=st.DEFAULT_LEASE_SECONDS, help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="command", required=True)

    v = sub.add_parser("verify", help="verify a change and say accept, reject or needs review")
    v.add_argument("--head", type=Path, required=True, help="a checkout of the change")
    v.add_argument("--base", type=Path, help="a checkout of what it is compared with; the checks are read from it")
    v.add_argument("--adapter", default="godot")
    v.add_argument("--game", required=True, help="the project folder, relative to the checkout")
    v.add_argument("--routes", required=True, help="route files or globs, relative to the checkout, separated by spaces or commas")
    v.add_argument("--specs", required=True, help="the folder of approved test specs, relative to the checkout")
    v.add_argument("--head-commit")
    v.add_argument("--base-commit")
    v.add_argument("--execution-class", choices=req.EXECUTION_CLASSES, default="diagnostic")
    v.add_argument("--timeout", type=int, default=req.DEFAULT_TIMEOUT_SECONDS, help="seconds before the job stops as needs review")
    v.add_argument("--idempotency-key")
    v.add_argument("--detach", action="store_true", help="start the job, print its id and return")
    v.add_argument("--json", action="store_true")

    for name, text in (("status", "show a job's status"), ("cancel", "cancel a job and stop what it started"),
                       ("report", "show a finished job's result and where its evidence is")):
        s = sub.add_parser(name, help=text)
        s.add_argument("job")
        s.add_argument("--json", action="store_true")

    sm = sub.add_parser("sample", help="three real verifications of the bundled game: as it is, broken, repaired")
    sm.add_argument("--timeout", type=int, default=600, help="seconds allowed for each of the three runs")
    sm.add_argument("--json", action="store_true")

    w = sub.add_parser("_work")   # the worker process; started by `verify`, not by people
    w.add_argument("job")

    args = p.parse_args(argv)
    store = _store(args)
    try:
        if args.command == "_work":
            runner.work(store, args.job, own_group=True)
            return 0
        if args.command == "sample":
            if not args.json:
                print("Expectrail sample: three real runs on the bundled game and a seeded bug. No model key is used.")
            results = smp.run(store, timeout_seconds=args.timeout,
                              on_case=None if args.json else (lambda r: print(smp.line(r), flush=True)))
            if args.json:
                print(json.dumps(results, indent=2))
            return 0 if all(r["asExpected"] for r in results) else EXIT_FAILED
        if args.command == "verify":
            request = req.build(adapter=args.adapter, head=args.head, base=args.base, game=args.game,
                                routes=[r for r in re.split(r"[\s,]+", args.routes) if r], specs=args.specs,
                                head_commit=args.head_commit, base_commit=args.base_commit,
                                execution_class=args.execution_class, timeout_seconds=args.timeout,
                                idempotency_key=args.idempotency_key)
            status, created = store.create(request)
            proc = runner.spawn(store, status["id"]) if created else None
            if args.detach:
                print(json.dumps({"id": status["id"], "created": created}) if args.json else status["id"])
                return 0
            progress = None if args.json else (lambda s: print(f"job {s['id']}: {s['phase']}", file=sys.stderr))
            status = runner.wait(store, status["id"], proc, on_phase=progress)
            _show(status, args.json)
            return exit_code(status)
        if args.command == "cancel":
            status = store.cancel(args.job)
            _show(status, args.json)
            return exit_code(status)
        status = store.status(args.job)
        if args.command == "report":
            if status["phase"] not in st.FINAL:
                print(f"job {status['id']} is {status['phase']}; there is no result yet", file=sys.stderr)
                return EXIT_USAGE
            _show(status, args.json)
            if not args.json and status["output"]:
                print(f"  evidence: {store.paths(status['id']).output}")
            return exit_code(status)
        _show(status, args.json)
        return 0 if status["phase"] not in st.FINAL else exit_code(status)
    except (req.RequestError, st.StoreError, smp.SampleError) as exc:
        print(f"expectrail: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except Exception as exc:  # noqa: BLE001 - a crash here must never look like a verdict (1 is reject)
        print(f"expectrail: the command failed and no job result was produced ({type(exc).__name__}: "
              f"{str(exc)[:200]})", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
