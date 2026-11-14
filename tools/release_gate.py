"""Run the release gate suite (#258) and write its summary from the results.

    python3 -m tools.release_gate [--require] [--out docs/release-gate.md] [--json FILE]

The controls are ``tests/release_gate/controls.py``; the tests are the ``gate_*.py`` modules beside
it. Every test in those modules is run, whether a row names it or not (``tests/test_release_gate.py``
holds that every test belongs to one row or is a baseline).

A row is **held** only when every test it names ran and passed and it has no ``open`` reason. A row
with an ``open`` reason is **open**, whatever its probe did; a skipped test makes its row **not run**;
a failure, an error, or a probe that unexpectedly passes makes it **FAILED**. Nothing is held because
nothing failed.

Exit 0 when nothing failed (and, with ``--require``, nothing was skipped), 1 otherwise.
"""
from __future__ import annotations

import argparse
import datetime
import importlib
import json
import os
import pkgutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKAGE = "tests.release_gate"

HELD, OPEN, FAILED, NOT_RUN = "held", "open", "FAILED", "not run"
PASSED, FAILURE, ERROR, SKIPPED, EXPECTED, UNEXPECTED = (
    "passed", "failed", "error", "skipped", "expected failure", "unexpected success")


class Collector(unittest.TextTestResult):
    """Each test's outcome by its id (``module.Class.method``), with how long it took."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes: dict[str, dict] = {}
        self._started: dict[str, float] = {}

    def startTest(self, test):
        self._started[test.id()] = time.monotonic()
        super().startTest(test)

    def _note(self, test, outcome: str, detail: str = "") -> None:
        tid = test.id() if hasattr(test, "id") else str(test)
        took = time.monotonic() - self._started.get(tid, time.monotonic())
        self.outcomes[tid] = {"outcome": outcome, "seconds": round(took, 1), "detail": detail[-2000:]}

    def addSuccess(self, test):
        super().addSuccess(test)
        self._note(test, PASSED)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._note(test, FAILURE, self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        # An error in setUpClass arrives on a placeholder: every test of that class is then noted below.
        self._note(test, ERROR, self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._note(test, SKIPPED, reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._note(test, EXPECTED, self._exc_info_to_string(err, test))

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._note(test, UNEXPECTED)


def gate_modules() -> list[str]:
    folder = REPO / "tests" / "release_gate"
    return sorted(f"{PACKAGE}.{m.name}" for m in pkgutil.iter_modules([str(folder)]) if m.name.startswith("gate_"))


def gate_tests() -> list[str]:
    """Every test id in the gate modules."""
    ids: list[str] = []

    def walk(suite):
        for item in suite:
            if isinstance(item, unittest.TestSuite):
                walk(item)
            else:
                ids.append(item.id())

    loader = unittest.TestLoader()
    for name in gate_modules():
        walk(loader.loadTestsFromModule(importlib.import_module(name)))
    return sorted(ids)


def run(stream=None) -> dict[str, dict]:
    """Run every gate test and return the outcome of each, by id. A test that never reported (its
    class could not be set up) is an error, never a pass."""
    from tests.release_gate import controls

    loader = unittest.TestLoader()
    suite = unittest.TestSuite(loader.loadTestsFromModule(importlib.import_module(n)) for n in gate_modules())
    runner = unittest.TextTestRunner(stream=stream or sys.stderr, verbosity=2, resultclass=Collector)
    result = runner.run(suite)
    outcomes = dict(result.outcomes)
    class_errors = {k: v for k, v in outcomes.items() if not k.count(".") or "setUpClass" in k}
    for tid in set(gate_tests()) | set(controls.all_tests()):
        if tid not in outcomes:
            why = "; ".join(v["detail"].strip().splitlines()[-1] for v in class_errors.values() if v["detail"]) or \
                  "the test did not report"
            outcomes[tid] = {"outcome": ERROR, "seconds": 0.0, "detail": why}
    return {k: v for k, v in outcomes.items() if k not in class_errors}


def row_status(control: dict, outcomes: dict[str, dict]) -> tuple[str, str]:
    """A row's status and what to say beside it."""
    got = [outcomes.get(t, {"outcome": ERROR, "detail": "not reported"}) for t in control["tests"]]
    kinds = [g["outcome"] for g in got]
    if any(k in (FAILURE, ERROR) for k in kinds):
        return FAILED, "a test failed or could not run: clearance may be granted where it must not be"
    if UNEXPECTED in kinds:
        return FAILED, ("its probe now passes: the control may be defended; make the probe a plain test and "
                        "remove the row's open reason")
    if control["open"]:
        note = control["open"]
        if EXPECTED in kinds:
            note += " (probe run: it still fails, as expected)"
        return OPEN, note
    if not control["tests"]:
        return OPEN, "no test"
    if any(k != PASSED for k in kinds):
        return NOT_RUN, "a test was skipped: " + "; ".join(g.get("detail", "") for g in got if g["outcome"] == SKIPPED)
    return HELD, f"{len(kinds)} real-process test{'s' if len(kinds) != 1 else ''} passed"


def summarise(outcomes: dict[str, dict], *, commit: str, where: str, when: str) -> dict:
    from tests.release_gate import controls

    baselines = {t: outcomes.get(t, {}).get("outcome", ERROR) for t in controls.BASELINES}
    baseline_ok = all(v == PASSED for v in baselines.values())
    rows = []
    for c in controls.CONTROLS:
        status, note = row_status(c, outcomes)
        if status == HELD and not baseline_ok:
            # Without the positive control, "not cleared" could mean "nothing is ever cleared".
            status, note = NOT_RUN, "the positive control did not pass, so this row cannot be read as held"
        rows.append({**c, "status": status, "note": note,
                     "results": {t: outcomes.get(t, {}).get("outcome", ERROR) for t in c["tests"]}})
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in (HELD, OPEN, FAILED, NOT_RUN)}
    return {"format": "expectrail.release-gate/v0", "commit": commit, "where": where, "when": when,
            "counts": counts, "baselines": baselines, "rows": rows,
            "tests": {k: outcomes[k] for k in sorted(outcomes)}}


def render(summary: dict) -> str:
    from tests.release_gate import controls

    c = summary["counts"]
    baseline_ok = all(v == PASSED for v in summary["baselines"].values())
    lines = [
        "# Release gate",
        "",
        "One control per row (#258). Each row's tests start real processes (the `expectrail verify` command, its",
        "worker, Godot) and assert that clearance is **not** granted: today, that the command does not exit 0",
        "and the job is not an accept. A row is held only when its tests ran and passed. A row without a test,",
        "or with a probe that shows the control is not defended, is open, with the reason.",
        "",
        "This file is written by `python3 -m tools.release_gate` from the results of one run. Do not edit it by",
        "hand.",
        "",
        f"- Run: {summary['where']}",
        f"- Commit: `{summary['commit']}`",
        f"- When: {summary['when']}",
        f"- Rows: {sum(c.values())}. Held {c[HELD]}, open {c[OPEN]}, failed {c[FAILED]}, not run {c[NOT_RUN]}.",
        f"- Positive control (the same command clears the unchanged game and rejects the seeded bug): "
        f"{'passed' if baseline_ok else 'NOT passed, so no row below can be read as held'}.",
        "",
    ]
    for group in controls.GROUPS:
        lines += [f"## {group}", "", "| Control | Status | Why |", "| --- | --- | --- |"]
        for r in summary["rows"]:
            if r["group"] == group:
                lines.append(f"| {r['control']} | {r['status']} | {r['note'].replace('|', '/')} |")
        lines.append("")
    lines += ["## Tests", "", "| Test | Result | Seconds |", "| --- | --- | --- |"]
    for tid, t in summary["tests"].items():
        lines.append(f"| `{tid.removeprefix(PACKAGE + '.')}` | {t['outcome']} | {t['seconds']} |")
    lines.append("")
    return "\n".join(lines)


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _where() -> str:
    run_id = os.environ.get("GITHUB_RUN_ID")
    if run_id and os.environ.get("GITHUB_REPOSITORY"):
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        return f"[CI run {run_id}]({server}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{run_id})"
    return "a local run, not CI"


def failed(summary: dict, *, require: bool) -> bool:
    bad = {FAILURE, ERROR, UNEXPECTED} | ({SKIPPED} if require else set())
    return any(t["outcome"] in bad for t in summary["tests"].values())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--require", action="store_true", help="a skipped test fails the run (the CI job sets it)")
    p.add_argument("--out", type=Path, help="write the summary as Markdown here")
    p.add_argument("--json", type=Path, help="write the summary as JSON here")
    args = p.parse_args(argv)
    if args.require:
        os.environ["EXPECTRAIL_RELEASE_GATE"] = "required"
    outcomes = run()
    when = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    summary = summarise(outcomes, commit=_commit(), where=_where(), when=when)
    text = render(summary)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    c = summary["counts"]
    print(f"release gate: held {c[HELD]}, open {c[OPEN]}, failed {c[FAILED]}, not run {c[NOT_RUN]}")
    return 1 if failed(summary, require=args.require) else 0


if __name__ == "__main__":
    sys.exit(main())
