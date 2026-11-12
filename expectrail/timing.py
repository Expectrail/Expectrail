"""Where the wall time of one verification goes: import, replay, evaluate.

    python3 -m expectrail.timing show runs/verify/timing.json [--notice]

``agents.verifier.verify`` writes ``timing.json`` (``expectrail.verify-timing/v1``) beside
``verification.json``. The harness times its own steps, the verifier names the replay each belongs to
(the arm), and everything the verifier does outside a harness run is counted as ``evaluate``:

    import     Godot's ``--import`` on the patched copy, and warming the shared import cache when it is cold
    replay     the Godot process that plays the route and writes the frames and the trace
    evaluate   the rest of the verifier: building observations, judging the checks, writing the verdicts
    other      the harness outside Godot: copying the game, applying patches, hashing the frames

The four add up to the total, because ``evaluate`` is the total less the harness's own time. The clock
is ``time.perf_counter``: wall time on one machine, for one run. It says nothing about spread.

Timing never changes a verdict: with no recording open, ``arm`` and ``phase`` do nothing, and a phase
opened inside another phase is not counted, so the parts can never exceed the total.
"""
from __future__ import annotations

import argparse
import contextlib
import contextvars
import json
import math
import os
import sys
import time
from pathlib import Path

from expectrail import resources

FORMAT = "expectrail.verify-timing/v1"
SCHEMA = resources.ROOT / "contracts" / "verify-timing.v1.schema.json"
CLOCK = "time.perf_counter"
# The harness's own steps, in the order it takes them, and the summary phase each is counted under.
HARNESS_PHASES = {
    "import-cache": "import",
    "prepare": "other",
    "import": "import",
    "replay": "replay",
    "record": "other",
}
SUMMARY = ("import", "replay", "evaluate", "other")
UNLABELLED = "unlabelled"
# Parts are rounded to a millisecond each, so sums may differ from the total by a few of them.
TOLERANCE = 0.05

_recorder: contextvars.ContextVar["Recorder | None"] = contextvars.ContextVar("expectrail_timing", default=None)
_arm: contextvars.ContextVar[str] = contextvars.ContextVar("expectrail_timing_arm", default=UNLABELLED)


class TimingError(ValueError):
    pass


class Recorder:
    """The harness steps seen while one recording was open, and how long the recording lasted."""

    def __init__(self, clock=time.perf_counter) -> None:
        self.clock = clock
        self.events: list[tuple[str, str, float]] = []
        self.runs: dict[str, int] = {}
        self.total: float | None = None
        self._started = clock()
        self._depth = 0

    def stop(self) -> None:
        if self.total is None:
            self.total = self.clock() - self._started

    def document(self, what: str, **context) -> dict:
        """The ``expectrail.verify-timing/v1`` record. ``context`` is copied in as given."""
        self.stop()
        arms: dict[str, dict[str, float]] = {}
        for arm_name, name, seconds in self.events:
            row = arms.setdefault(arm_name, dict.fromkeys(HARNESS_PHASES, 0.0))
            row[name] += seconds
        summary = dict.fromkeys(SUMMARY, 0.0)
        for row in arms.values():
            for name, seconds in row.items():
                summary[HARNESS_PHASES[name]] += seconds
        harness = sum(summary.values())
        summary["evaluate"] = max(0.0, self.total - harness)
        doc = {
            "format": FORMAT,
            "what": what,
            "clock": CLOCK,
            "totalSeconds": round(self.total, 3),
            "phases": {name: round(summary[name], 3) for name in SUMMARY},
            "arms": [
                {"arm": arm_name, "harnessRuns": self.runs.get(arm_name, 0),
                 "seconds": {name: round(row[name], 3) for name in HARNESS_PHASES}}
                for arm_name, row in arms.items()
            ],
        }
        doc.update(context)
        return doc


@contextlib.contextmanager
def recording(clock=time.perf_counter):
    """Open a recording for the calling context. A recording opened inside another replaces it until it ends."""
    recorder = Recorder(clock)
    token = _recorder.set(recorder)
    try:
        yield recorder
    finally:
        recorder.stop()
        _recorder.reset(token)


@contextlib.contextmanager
def arm(label: str):
    """Name the replay the harness steps inside belong to: ``candidate``, ``clean``, ``held-out-1``."""
    token = _arm.set(label)
    try:
        yield
    finally:
        _arm.reset(token)


def count_run() -> None:
    """Called once by each harness run, so a retried replay shows as two runs of one arm."""
    recorder = _recorder.get()
    if recorder is not None:
        label = _arm.get()
        recorder.runs[label] = recorder.runs.get(label, 0) + 1


@contextlib.contextmanager
def phase(name: str):
    """Time one harness step. The time is recorded even when the step raises."""
    if name not in HARNESS_PHASES:
        raise TimingError(f"not a harness phase: {name!r}")
    recorder = _recorder.get()
    if recorder is None:
        yield
        return
    outermost = recorder._depth == 0
    recorder._depth += 1
    started = recorder.clock()
    try:
        yield
    finally:
        recorder._depth -= 1
        if outermost:
            recorder.events.append((_arm.get(), name, recorder.clock() - started))


def not_finite(value, where: str = "") -> str | None:
    """Where the first NaN or infinity sits in a parsed JSON value, or None when every number is finite.

    ``json`` reads and writes ``NaN`` and ``Infinity`` unless told not to, a JSON Schema ``number`` accepts
    them, and every comparison with NaN is false, so a sum check passes on one.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return where or "(root)"
    if isinstance(value, dict):
        children = ((f"{where}/{key}" if where else str(key), child) for key, child in value.items())
    elif isinstance(value, (list, tuple)):
        children = ((f"{where}/{index}" if where else str(index), child) for index, child in enumerate(value))
    else:
        return None
    for path, child in children:
        found = not_finite(child, path)
        if found:
            return found
    return None


def problems(doc: dict) -> list[str]:
    """What is wrong with a timing record, one line each: numbers that are not numbers, the schema, the sums."""
    import jsonschema

    bad = not_finite(doc)
    if bad:
        return [f"verify-timing: {bad}: not a finite number"]
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.path) or "(root)"
        return [f"verify-timing: {where}: {first.message}"]
    out = []
    parts = sum(doc["phases"].values())
    if abs(parts - doc["totalSeconds"]) > TOLERANCE:
        out.append(f"verify-timing: the phases add up to {parts:.3f} s and the total is {doc['totalSeconds']:.3f} s")
    by_summary = dict.fromkeys(SUMMARY, 0.0)
    labels = [row["arm"] for row in doc["arms"]]
    if len(set(labels)) != len(labels):
        out.append("verify-timing: an arm is listed twice")
    for row in doc["arms"]:
        for name, seconds in row["seconds"].items():
            by_summary[HARNESS_PHASES[name]] += seconds
    for name in ("import", "replay", "other"):
        if abs(by_summary[name] - doc["phases"][name]) > TOLERANCE:
            out.append(f"verify-timing: the arms' {name} time is {by_summary[name]:.3f} s and phases.{name} is "
                       f"{doc['phases'][name]:.3f} s")
    return out


def load(path: Path) -> dict:
    """A timing record that passes ``problems``. Raises TimingError with the first problem."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TimingError(f"verify-timing: cannot read {path}: {exc}") from exc
    found = problems(doc)
    if found:
        raise TimingError(found[0])
    return doc


def write(recorder: Recorder, path: Path, what: str, **context) -> dict:
    doc = recorder.document(what, **context)
    found = problems(doc)
    if found:
        raise TimingError(found[0])
    Path(path).write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return doc


def line(doc: dict) -> str:
    """One line a person can read in a CI log."""
    phases = doc["phases"]
    arms = ", ".join(f"{row['arm']} {sum(row['seconds'].values()):.1f}" for row in doc["arms"]) or "no harness run"
    return (f"total {doc['totalSeconds']:.1f} s: import {phases['import']:.1f}, replay {phases['replay']:.1f}, "
            f"evaluate {phases['evaluate']:.1f}, other {phases['other']:.1f} (by replay: {arms})")


def table(doc: dict) -> str:
    """The same as a Markdown table, for a job summary."""
    rows = ["| Phase | Seconds |", "| --- | --- |"]
    rows += [f"| {name} | {doc['phases'][name]:.3f} |" for name in SUMMARY]
    rows += [f"| **total** | {doc['totalSeconds']:.3f} |", "", "| Replay | Harness runs | "
             + " | ".join(HARNESS_PHASES) + " |", "| --- | --- | " + " | ".join("---" for _ in HARNESS_PHASES) + " |"]
    rows += [f"| {row['arm']} | {row['harnessRuns']} | "
             + " | ".join(f"{row['seconds'][name]:.3f}" for name in HARNESS_PHASES) + " |" for row in doc["arms"]]
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("show",))
    parser.add_argument("path", type=Path)
    parser.add_argument("--notice", action="store_true",
                        help="print the line as a GitHub notice and add the table to the job summary")
    args = parser.parse_args(argv)
    try:
        doc = load(args.path)
    except TimingError as err:
        print(err, file=sys.stderr)
        return 1
    print(("::notice title=Verification wall time::" if args.notice else "") + line(doc))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if args.notice and summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"### Verification wall time\n\n{doc['what']}\n\n{table(doc)}\n")
    elif not args.notice:
        print(table(doc), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
