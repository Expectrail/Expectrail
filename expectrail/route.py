"""Make a first Godot route, keeping it only after three identical complete traces."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

FALLBACK_ACTIONS = ("ui_left", "ui_right", "ui_up", "ui_down", "ui_accept")
MOVEMENT_WORDS = {"move", "walk", "run", "strafe", "left", "right", "up", "down", "forward", "backward", "back"}


class RouteError(ValueError):
    """The project or the replay cannot supply a checked route."""


def _records(text: str):
    """Godot config records, retaining strings and nested Variant values across lines.

    This reads structure, not executable Variant constructors. In particular a bracket or
    semicolon inside an input event's quoted string must not end a record or start a comment.
    """
    record, stack = [], []
    quoted = escaped = comment = False
    for char in text + "\n":
        if comment:
            if char != "\n":
                continue
            comment = False
        if quoted:
            record.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == ";":
            comment = True
            continue
        if char == '"':
            quoted = True
        elif char in "[{(":
            stack.append(char)
        elif char in "]})":
            if not stack or stack.pop() != {"]": "[", "}": "{", ")": "("}[char]:
                raise RouteError("project.godot has unbalanced brackets")
        if char == "\n" and not stack:
            value = "".join(record).strip()
            if value:
                yield value
            record = []
        else:
            record.append(char)
    if quoted or stack:
        raise RouteError("project.godot has an unfinished string or value")


def input_map(project: Path) -> tuple[list[str], int, bool]:
    """Return custom actions, physics tick rate, and whether built-ins were needed."""
    section, actions, rate = "", set(), 60
    for record in _records((project / "project.godot").read_text(encoding="utf-8-sig")):
        if record.startswith("[") and record.endswith("]"):
            section = record[1:-1].strip()
            continue
        if section not in ("input", "physics"):
            continue
        match = re.fullmatch(r'("(?:\\.|[^"\\])*"|[^=\s]+)\s*=\s*(.*)', record, re.S)
        if not match:
            raise RouteError(f"cannot read an assignment in [{section}] in project.godot")
        key, value = match.groups()
        if key.startswith('"'):
            key = json.loads(key)
        if section == "input":
            if not key or not value.startswith("{") or not value.endswith("}"):
                raise RouteError("each input action must have a name and a dictionary in project.godot")
            if key in actions:
                raise RouteError(f"input action {key!r} is defined more than once")
            actions.add(key)
        elif key == "common/physics_ticks_per_second":
            if not re.fullmatch(r"[0-9]+", value) or not 1 <= int(value) <= 1000:
                raise RouteError("physics_ticks_per_second must be an integer from 1 to 1000")
            rate = int(value)
    # An explicitly configured ui_* action is part of this project's map too. Add the
    # fallback only when [input] defines nothing; never silently discard a project action.
    return sorted(actions) or list(FALLBACK_ACTIONS), rate, not bool(actions)


def is_movement(action: str) -> bool:
    separated = re.sub(r"([a-z])([A-Z])", r"\1_\2", action)
    return bool(set(re.findall(r"[a-z]+", separated.lower())) & MOVEMENT_WORDS)


def make_route(actions: list[str], rate: int) -> dict:
    """One second per movement action; three short presses of every other action, seed 1."""
    pause, tap = max(1, round(rate / 4)), max(1, round(rate / 10))
    tick, events = pause, []
    for action in sorted(set(actions), key=lambda a: (not is_movement(a), a)):
        for _ in range(1 if is_movement(action) else 3):
            duration = rate if is_movement(action) else tap
            events += [{"tick": tick, "action": action, "pressed": True},
                       {"tick": tick + duration, "action": action, "pressed": False}]
            tick += duration + pause
    return {"format": "expectrail.route/v0", "name": "auto-input-map", "seed": 1,
            "description": "First route from the project's input map: movement holds, short presses and pauses.",
            "ticks": tick + pause, "events": events}


def read_trace(path: Path, ticks: int, rate: int) -> dict:
    def nonfinite(value):
        raise RouteError(f"trace contains a non-finite number: {value}")

    trace = json.loads(path.read_text(encoding="utf-8"), parse_constant=nonfinite)
    if not isinstance(trace, dict) or trace.get("format") != "expectrail.trace/v0":
        raise RouteError("replay did not produce an expectrail.trace/v0")
    if trace.get("ticks") != ticks or trace.get("physicsTicksPerSecond") != rate:
        raise RouteError("trace length or physics tick rate does not match the generated route")
    rows = trace.get("rows")
    if not isinstance(rows, list) or len(rows) != ticks or any(
            not isinstance(row, dict) or type(row.get("tick")) is not int or row["tick"] != i
            for i, row in enumerate(rows)):
        raise RouteError("trace is incomplete: expected one row for every route tick, in order")
    for row in rows:
        if "player" in row:
            point = row["player"]
            if not isinstance(point, list) or len(point) != 2 or any(
                    type(x) not in (int, float) or not math.isfinite(x) for x in point):
                raise RouteError(f"invalid bound player position at tick {row['tick']}")
    return trace


def differences(traces: list[dict]) -> tuple[list[int], list[str]]:
    """Compare every recorded field, including camera, enemies, and trace metadata."""
    first = traces[0]
    ticks = sorted({i for trace in traces[1:] for i, (left, right) in enumerate(zip(first["rows"], trace["rows"]))
                    if left != right})
    headers = sorted({key for trace in traces[1:] for key in first.keys() | trace.keys()
                      if key != "rows" and (key not in first or key not in trace or first[key] != trace[key])})
    return ticks, headers


def tick_ranges(ticks: list[int]) -> str:
    runs = []
    for tick in ticks:
        if runs and tick == runs[-1][1] + 1:
            runs[-1][1] = tick
        else:
            runs.append([tick, tick])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


def describe(route: dict, rate: int, trace: dict) -> list[str]:
    lines = [f"Route: {route['ticks']} physics ticks ({route['ticks'] / rate:g} seconds at {rate} ticks/second), seed 1."]
    held, durations = {}, {}
    for event in route["events"]:
        if event["pressed"]:
            held[event["action"]] = event["tick"]
        else:
            durations.setdefault(event["action"], []).append(event["tick"] - held.pop(event["action"]))
    for action, stretches in durations.items():
        lines.append(f"  {action}: {len(stretches)} press(es), {stretches[0]} ticks "
                     f"({stretches[0] / rate:g} seconds) each.")
    pause = max(1, round(rate / 4))
    lines.append(f"Pauses: {pause} ticks ({pause / rate:g} seconds) before and between actions; "
                 f"{2 * pause} ticks after the last release.")
    positions = [row["player"] for row in trace["rows"] if "player" in row]
    moved = bool(positions) and any(p != positions[0] for p in positions[1:])
    if not route["events"]:
        lines.append("Empty route: no actions were pressed; this is not useful input coverage.")
    if moved:
        lines.append("The bound player (Player) moved during the replay. Movement alone does not prove the actions caused it.")
    elif not positions:
        lines.append("No bound player (Player) was recorded; movement is unknown. This is not demonstrated useful coverage.")
    else:
        lines.append("The bound player (Player) did not move at all. This is not demonstrated useful movement coverage.")
    if positions and len(positions) != len(trace["rows"]):
        lines.append("The bound player was absent on some ticks; movement is reported only where it was recorded.")
    return lines


def auto_route(project: Path, out: Path, *, replay=None) -> int:
    """The real harness and offline stand-ins use exactly the same three-run decision path."""
    if out.exists() or out.is_symlink():
        raise RouteError(f"output already exists: {out}; choose a new path (nothing was overwritten)")
    project = project.resolve()
    actions, rate, fallback = input_map(project)
    route = make_route(actions, rate)
    if fallback:
        print("No custom input actions: using built-in ui_left, ui_right, ui_up, ui_down and ui_accept.")
    if replay is None:
        from harness.run import run
        replay = run
    with tempfile.TemporaryDirectory(prefix="expectrail-auto-route-") as tmp:
        work = Path(tmp)
        candidate = work / "candidate.json"
        encoded = json.dumps(route, indent=2) + "\n"
        candidate.write_text(encoded, encoding="utf-8")
        traces, trees = [], []
        for n in range(1, 4):
            print(f"Replaying input map: run {n} of 3.", flush=True)
            result = replay(candidate, work / str(n), game=project, capture_frames=False)
            trees.append(result["game"]["tree"])
            traces.append(read_trace(work / str(n) / "trace.json", route["ticks"], rate))
        if len(set(trees)) != 1:
            raise RouteError("the project changed between replays; keep it unchanged and try again")
        ticks, headers = differences(traces)
        if ticks or headers:
            print("The project is not yet deterministic under the harness. No route was written.")
            if ticks:
                print(f"Differing ticks (zero-based; ranges inclusive): {tick_ranges(ticks)}.")
            if headers:
                print(f"Differing trace metadata: {', '.join(headers)}.")
            return 2
        print("Three complete traces are identical (headless replays; rendered images were not compared).")
        for line in describe(route, rate, traces[0]):
            print(line)
        out.parent.mkdir(parents=True, exist_ok=True)
        # Publish complete bytes without clobbering a route created during the replays.
        # A hard link within this directory is atomic and fails if the destination exists.
        pending = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=out.parent,
                                             prefix=".expectrail-route-", delete=False) as stream:
                pending = Path(stream.name)
                stream.write(encoded)
            os.link(pending, out)
        finally:
            if pending is not None:
                pending.unlink(missing_ok=True)
        print(f"Wrote {out}.")
    return 0


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise RouteError(message)


def main(argv: list[str] | None = None) -> int:
    parser = Parser(prog="expectrail route", description=__doc__)
    parser.add_argument("--project", type=Path, required=True, help="directory containing project.godot")
    parser.add_argument("--auto", action="store_true", required=True, help="generate and check a first route")
    parser.add_argument("--out", type=Path, required=True, help="new route file; existing files are never overwritten")
    try:
        args = parser.parse_args(argv)
        return auto_route(args.project, args.out)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"expectrail route: {exc}. No route was written.", file=sys.stderr)
        return 5
    except SystemExit as exc:
        # --help exits 0; harness failures carry a diagnostic string, not a CLI usage exit.
        if exc.code == 0:
            return 0
        print(f"expectrail route: replay could not finish: {exc}. No route was written.", file=sys.stderr)
        return 5


if __name__ == "__main__":
    sys.exit(main())
