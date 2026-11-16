"""Play a short random route from the start and describe trace anomalies, without a model."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import re

from expectrail.route import input_map, is_movement, read_trace

VERSION = "1.0.0"
FALL = "My character falls below the bottom of the level."
STUCK = "My character stops moving even though I keep holding a movement button."
FACING = "My character keeps turning back and forth while I keep moving in one direction."
OFFSCREEN = "My character goes off screen and stays there while I keep playing."


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def make_route(actions: list[str], seed: int, ticks: int = 1200) -> dict:
    """Bounded random holds and taps. Sort the map so its declaration order is irrelevant.

    Prefer the bundled game's single-player actions. UI and player-two aliases would pause,
    switch modes or release another action's shared key; they are deliberately outside this probe.
    Other projects use their movement actions and exact jump/shoot actions, if present.
    """
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError("seed must be an integer from 0 to 4294967295")
    if type(ticks) is not int or not 1 <= ticks <= 1800:
        raise ValueError("ticks must be an integer from 1 to 1800")
    actions = sorted(set(actions))
    movement = [a for a in ("move_left", "move_right") if a in actions]
    if not movement:
        movement = [a for a in actions if is_movement(a)]
    if not movement:
        raise ValueError("input map has no recognised movement action")
    rng, events = random.Random(seed), []

    def hold(action, start, duration):
        end = min(ticks - 1, start + duration)
        if start < end:
            events.extend([{"tick": start, "action": action, "pressed": True},
                           {"tick": end, "action": action, "pressed": False}])

    tick = 15
    while tick < ticks - 1:
        duration = rng.randint(45, 210)
        action = rng.choice(movement + [None])
        if action is not None:
            hold(action, tick, duration)
        # Independent taps may overlap movement, but never another tap of the same action.
        for name in ("jump", "shoot"):
            if name in actions:
                at = tick + rng.randint(0, 15)
                while at < min(tick + duration, ticks - 1):
                    if rng.randrange(3) != 0:
                        hold(name, at, rng.randint(1, 8))
                    at += rng.randint(12, 45)
        tick += duration + rng.randint(0, 20)
    events.sort(key=lambda e: (e["tick"], e["action"], e["pressed"]))
    return {"format": "expectrail.route/v0", "name": f"playtest-seed-{seed}",
            "seed": seed, "ticks": ticks, "events": events}


def point(row: dict):
    value = row.get("player")
    if isinstance(value, list) and len(value) == 2 and all(
            type(n) in (int, float) and math.isfinite(n) for n in value):
        return value
    return None


def anomalies(route: dict, trace: dict) -> list[dict]:
    """First observation of each symptom; no check names or inferred causes in the result.

    Below level: origin > largest tile polygon y + 64 px.
    Stopped: all positions stay within 0.5 px for 120 ticks under one continuous move hold.
    Turning: facing alternates for 8 consecutive steps moving >= 0.25 px along the same x sign.
    Missing observations break a window. These are suspicions, including legitimate wall stops.
    """
    rows = trace["rows"]
    ground = [p[1] for polygon in trace.get("levelSurfaces", []) for p in polygon
              if isinstance(p, list) and len(p) == 2 and type(p[1]) in (int, float)
              and math.isfinite(p[1])]
    bottom = max(ground) if ground else None
    events = {}
    for event in route["events"]:
        events.setdefault(event["tick"], []).append(event)
    held, found, stopped = set(), {}, []
    turning, last_direction, last_held = 0, None, None
    for tick, row in enumerate(rows):
        for event in events.get(tick, []):
            if event["pressed"]:
                held.add(event["action"])
            else:
                held.discard(event["action"])
        moving = tuple(sorted(a for a in held if is_movement(a)))
        here = point(row)
        before = point(rows[tick - 1]) if tick else None

        def record(bug):
            if tick > 0 and before is not None and bug not in found:
                found[bug] = {"bug": bug, "fault": {
                    "preFaultTick": tick - 1, "faultTick": tick,
                    "anchor": {"object": "Player", "x": before[0], "y": before[1], "tolerancePx": 2}}}

        if here is not None and bottom is not None and here[1] > bottom + 64:
            record(FALL)
        if here is not None and len(moving) == 1:
            if moving != last_held:
                stopped = []
            stopped.append(here)
            stopped = stopped[-120:]
            if len(stopped) == 120 and all(math.dist(stopped[0], p) <= 0.5 for p in stopped):
                record(STUCK)
        else:
            stopped = []
        last_held = moving
        dx = here[0] - before[0] if here is not None and before is not None else 0
        direction = 1 if dx >= 0.25 else -1 if dx <= -0.25 else None
        if (tick and direction is not None and direction == last_direction
                and row.get("facing") in (-1, 1) and rows[tick - 1].get("facing") in (-1, 1)
                and row["facing"] != rows[tick - 1]["facing"]):
            turning += 1
        else:
            turning = 0
        if turning >= 8:
            record(FACING)
        last_direction = direction
    return sorted(found.values(), key=lambda f: (f["fault"]["faultTick"], f["bug"]))


def reports(route: dict, trace: dict, commit: str, *, viewport=None) -> list[dict]:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("target commit must be a full lowercase Git SHA-1")
    result = []
    observed = anomalies(route, trace)
    if viewport is not None:
        from .offscreen import findings
        observed += findings(trace, viewport)
    for finding in sorted(observed, key=lambda f: (f["fault"]["faultTick"], f["bug"])):
        report = {"format": "expectrail.playtest-report/v1",
                  "producer": {"name": "Expectrail", "version": "1.1.0" if viewport is not None else VERSION},
                  "target": {"commit": commit}, "route": route, **finding}
        digest = hashlib.sha256(json.dumps(report, sort_keys=True, allow_nan=False,
                                          separators=(",", ":")).encode()).hexdigest()
        result.append({"id": f"playtest-{digest[:32]}", **report})
    return result


def play(project: Path, commit: str, seed: int, out: Path, *, ticks=1200, godot=None, viewport=None) -> list[dict]:
    from harness.run import run

    if out.exists():
        raise ValueError(f"output already exists: {out}")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("target commit must be a full lowercase Git SHA-1")
    if viewport is not None:
        from .offscreen import viewport_size
        viewport = viewport_size(viewport)
    actions, rate, _ = input_map(project)
    route = make_route(actions, seed, ticks)
    out.mkdir(parents=True)
    write_json(out / "route.json", route)
    run(out / "route.json", out / "replay", game=project, godot=godot, capture_frames=False)
    trace = read_trace(out / "replay/trace.json", ticks, rate)
    if trace.get("unknownActions"):
        raise ValueError("engine did not recognise every route action")
    documents = reports(route, trace, commit, viewport=viewport)
    for report in documents:
        write_json(out / "reports" / f"{report['id']}.json", report)
    write_json(out / "summary.json", {"seed": seed, "ticks": ticks, "inputActions": actions,
                                      "reports": [r["id"] for r in documents]})
    return documents


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--commit", required=True, help="full commit of the exact project played")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--ticks", type=int, default=1200)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--godot", type=Path, help="explicit engine binary; otherwise harness default")
    parser.add_argument("--viewport", type=int, nargs=2, metavar=("WIDTH", "HEIGHT"),
                        help="enable persistent offscreen observation; supply measured trace-view dimensions")
    args = parser.parse_args(argv)
    try:
        docs = play(args.project.resolve(), args.commit, args.seed, args.out.resolve(),
                    ticks=args.ticks, godot=args.godot, viewport=args.viewport)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Expectrail playtester: {exc}\n")
    print(f"seed {args.seed}: {len(docs)} report(s); {args.out}")
    return 0
