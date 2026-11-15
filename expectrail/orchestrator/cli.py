"""Verification as a job, from the command line.

    python3 -m expectrail.orchestrator verify --head . --game game/platformer \\
        --routes 'harness/routes/*.json' --specs agents/specs [--base ../base] [--detach] [--json]
    python3 -m expectrail.orchestrator status JOB [--json]
    python3 -m expectrail.orchestrator cancel JOB
    python3 -m expectrail.orchestrator report JOB
    python3 -m expectrail.orchestrator sample [--json]     three real runs on the bundled game

Jobs are kept under ``--jobs-root`` (default: $EXPECTRAIL_JOBS, else runs/jobs here). `verify` waits for
the job unless ``--detach`` is given; then it prints the job's id and returns.

Exit code, the same for `verify`, `status`, `cancel` and `report`: 0 accept, 1 reject, 2 needs
review, 3 the job failed (no result), 4 cancelled, 5 the command could not be carried out (a command
line that cannot be read is one of these: a missing or unknown option exits 5, not argparse's 2, which
here means needs review), 6 the job is not finished (no result yet). 0 only ever means a job that completed as accept and 1 one that
completed as reject, with two stated exceptions for 0: `verify --detach` exits 0 when the job was
started, and `sample` exits 0 when all three runs decide as a working install does (3 otherwise: it
checks the install, it is not a verdict on a change).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from expectrail.orchestrator import request as req
from expectrail.orchestrator import runner
from expectrail.orchestrator import sample as smp
from expectrail.orchestrator import store as st
from expectrail import auto_fix, viewer

EXIT = {"accept": 0, "reject": 1, "needs-review": 2}
EXIT_FAILED, EXIT_CANCELLED, EXIT_USAGE, EXIT_UNFINISHED = 3, 4, 5, 6


def exit_code(status: dict) -> int:
    """The exit code for a job's status, the same for every command that reports one. 0 is a
    completed job with accept and nothing else; a job that is not finished has a code of its own."""
    if status["phase"] == "completed":
        return EXIT[status["decision"]]
    return {"failed": EXIT_FAILED, "cancelled": EXIT_CANCELLED}.get(status["phase"], EXIT_UNFINISHED)


def describe(status: dict, job_folder: Path | None = None) -> str:
    from expectrail.gate import record as rec

    lines = []
    if status["decision"] == "needs-review" and any(
            r.startswith(rec.NOT_DEMONSTRATED + ":") for r in status["reasons"]):
        lines.append(req.UNVERIFIED_FIX)
    lines.append(f"job {status['id']}: {status['phase']}" + (f", {status['decision']}" if status["decision"] else ""))
    if status.get("intent", "none") != "none":
        lines.append(f"  Declared intent: {status['intent']}")
    if "bug" in status:
        lines.append(f"  Bug report (user supplied; not a check): {status['bug']}")
    lines += [f"  {reason}" for reason in status["reasons"]]
    lines += [f"  {d['code']} ({d['stage']}): {d['detail']} Fix: {d['fix']}" for d in status["diagnostics"]]
    if "observers" in status:
        from expectrail.gate.record import observers_words

        lines.append(f"  Judged on: {observers_words(status)}")
    if status["evidenceGrade"]:
        lines.append(f"  evidence grade: {status['evidenceGrade']}")
    from expectrail.orchestrator.budget import words as budget_words

    lines.extend("  " + line for line in budget_words(status))
    if job_folder is not None and "budget" in status:
        lines.append(f"  Budget record: {(job_folder / 'job-budget.json').as_uri()}")
    if status["decision"] == "reject":
        lines.append("  " + viewer.auto_fix_words(status))
        repair = status.get("repair", {})
        if "record" in repair:
            path = repair["record"]
            lines.append(f"  Repair record: {(job_folder / path).as_uri() if job_folder else path}")
        if "review" in repair:
            lines.append("  " + repair["review"])
    return "\n".join(lines)


def _store(args) -> st.JobStore:
    root = args.jobs_root or os.environ.get("EXPECTRAIL_JOBS") or "runs/jobs"
    return st.JobStore(Path(root), lease_seconds=args.lease_seconds)


def _show(status: dict, as_json: bool, store: st.JobStore) -> None:
    print(json.dumps(status, indent=2) if as_json else describe(status, store.paths(status["id"]).root))


class UsageError(Exception):
    """The command line could not be read."""


class Parser(argparse.ArgumentParser):
    """argparse exits 2 on a command line it cannot read, and 2 is needs-review here. This parser
    raises instead, and ``main`` returns 5: the command could not be carried out. (Subcommands are
    made with this class too: ``add_subparsers`` uses the class of the parser it is called on.)"""

    full_usage: str | None = None   # what a command line that cannot be read shows, in place of argparse's usage

    def error(self, message):
        raise UsageError(f"{message}\n{self.full_usage or self.format_usage().strip()}")


JOBS_ROOT_HELP = "where jobs are kept (default: $EXPECTRAIL_JOBS, else runs/jobs)"


def _jobs_root_after(parser: argparse.ArgumentParser) -> None:
    """``--jobs-root`` after the command, as `expectrail app --jobs-root DIR` takes it (#383). SUPPRESS
    keeps a value given before the command when none is given after it."""
    parser.add_argument("--jobs-root", dest="jobs_root_after", default=argparse.SUPPRESS, help=JOBS_ROOT_HELP)


def main(argv: list[str] | None = None, *, prog: str = "python3 -m expectrail.orchestrator",
         usage: str | None = None) -> int:
    """``prog`` is the name shown in help and errors: the `expectrail` command passes its own, and
    ``usage``, its command list, which a command line that cannot be read then shows. ``--jobs-root``
    is taken before the command or after it (not both with different folders)."""
    p = Parser(prog=prog, description=__doc__.splitlines()[0])
    p.full_usage = usage
    p.add_argument("--jobs-root", help=JOBS_ROOT_HELP)
    p.add_argument("--lease-seconds", type=float, default=st.DEFAULT_LEASE_SECONDS, help=argparse.SUPPRESS)
    # COMMAND, not argparse's {verify,...,_work}: the worker's command is not for people.
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

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
    v.add_argument("--intent", choices=req.INTENTS, default="none",
                   help="fix requires a check to fail on the base and pass on the head three times each; "
                        "change and none keep the existing rule (default: none)")
    v.add_argument("--bug", metavar="TEXT|@FILE",
                   help="report with --intent fix; capture text or a UTF-8 file (8192 characters max). "
                        "Use @@ for a literal leading @. No URL is fetched; this does not create a check")
    v.add_argument("--detach", action="store_true", help="start the job, print its id and return")
    v.add_argument("--json", action="store_true")
    auto_fix.options(v)
    _jobs_root_after(v)

    for name, text in (("status", "show a job's status"), ("cancel", "cancel a job and stop what it started"),
                       ("report", "show a finished job's result and where its evidence is")):
        s = sub.add_parser(name, help=text)
        s.add_argument("job")
        s.add_argument("--json", action="store_true")
        _jobs_root_after(s)

    sm = sub.add_parser("sample", help="three real verifications of the bundled game: as it is, broken, repaired")
    sm.add_argument("--timeout", type=int, default=600, help="seconds allowed for each of the three runs")
    sm.add_argument("--json", action="store_true")
    _jobs_root_after(sm)

    w = sub.add_parser("_work")   # the worker process; started by `verify`, not by people
    w.add_argument("job")

    try:
        args = p.parse_args(argv)
        after = getattr(args, "jobs_root_after", None)
        if after is not None:
            if args.jobs_root is not None and Path(args.jobs_root) != Path(after):
                raise UsageError(f"--jobs-root was given twice, as {args.jobs_root} before the command and as "
                                 f"{after} after it; give it once")
            args.jobs_root = after
    except UsageError as exc:
        print(f"expectrail: {exc}\nNothing was run.", file=sys.stderr)
        return EXIT_USAGE
    store = _store(args)
    try:
        if args.command == "_work":
            runner.work(store, args.job, own_group=True)
            return 0
        if args.command == "sample":
            if not args.json:
                print("Expectrail sample: three real runs on the bundled game and a seeded bug. Acceptance needs vision.")
            results = smp.run(store, timeout_seconds=args.timeout,
                              on_case=None if args.json else (lambda r: print(smp.line(r), flush=True)))
            if args.json:
                print(json.dumps(results, indent=2))
            return 0 if all(r["asExpected"] for r in results) else EXIT_FAILED
        if args.command == "verify":
            if args.bug is not None and args.intent != "fix":
                raise req.RequestError("--bug requires --intent fix; nothing was run")
            try:
                settings, patch = auto_fix.configure(args.auto_fix, args.auto_fix_attempts, args.auto_fix_usd_cap,
                                                     fixture=args.auto_fix_fixture, recorded=args.auto_fix_recorded)
            except (OSError, ValueError) as exc:
                raise req.RequestError(str(exc)) from exc
            request = req.build(adapter=args.adapter, head=args.head, base=args.base, game=args.game,
                                routes=[r for r in re.split(r"[\s,]+", args.routes) if r], specs=args.specs,
                                head_commit=args.head_commit, base_commit=args.base_commit,
                                execution_class=args.execution_class, timeout_seconds=args.timeout,
                                idempotency_key=args.idempotency_key, intent=args.intent,
                                bug=req.bug_text(args.bug))
            if settings:
                if not args.json:
                    cost = f"${settings['usdCap']:g} Muse cap" if settings["source"] == "muse" else "offline patch, no fixer spend"
                    print(f"Auto-fix on reject: up to {settings['attempts']} attempts, {cost}.", file=sys.stderr)
                request["autoFix"] = settings
            status, created = store.create(request)
            proc = None
            if created:
                proc = auto_fix.launch(store, status["id"], patch) if settings else runner.spawn(store, status["id"])
            if args.detach:
                print(json.dumps({"id": status["id"], "created": created}) if args.json else status["id"])
                return 0
            progress = None if args.json else (lambda s: print(f"job {s['id']}: {s['phase']}", file=sys.stderr))
            status = runner.wait(store, status["id"], proc, on_phase=progress)
            while status.get("repair", {}).get("state") == "running":
                if proc is not None:
                    proc.wait()
                else:
                    time.sleep(0.2)
                status = store.status(status["id"])
            _show(status, args.json, store)
            return exit_code(status)
        if args.command == "cancel":
            status = store.cancel(args.job)
            _show(status, args.json, store)
            return exit_code(status)
        status = store.status(args.job)
        if args.command == "report":
            if status["phase"] not in st.FINAL:
                print(f"job {status['id']} is {status['phase']}; there is no result yet", file=sys.stderr)
                return EXIT_UNFINISHED
            # The evidence viewer (#264): one folder that opens from disk, written for every final job,
            # so a job with no result (cancelled, failed, could not be carried out) has its page too.
            try:
                page = viewer.write_job(store, status["id"])
            except Exception as exc:  # noqa: BLE001 - the viewer never changes the job's result or exit code
                page = None
                print(f"expectrail: the evidence viewer was not written ({type(exc).__name__})", file=sys.stderr)
            # --json prints the status as it is (expectrail.verify-job/v1); the viewer is always at
            # <job>/viewer/index.html, and the same page as one file at <job>/viewer/evidence.html.
            _show(status, args.json, store)
            if not args.json:
                if status["output"]:
                    print(f"  evidence: {store.paths(status['id']).output}")
                if page:
                    print(f"  viewer: {page}")
                    single = page.parent / viewer.EXPORT_NAME
                    if single.is_file():
                        print(f"  one file to keep or send: {single}")
            return exit_code(status)
        _show(status, args.json, store)
        return exit_code(status)
    except (req.RequestError, st.StoreError, smp.SampleError) as exc:
        print(f"expectrail: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except Exception as exc:  # noqa: BLE001 - a crash here must never look like a verdict (1 is reject)
        print(f"expectrail: the command failed and no job result was produced ({type(exc).__name__}: "
              f"{str(exc)[:200]})", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
