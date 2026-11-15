"""Audit Dodge's region using the pinned viewport and a real clean replay's player body.

    python -m tools.dodge_play_area PROJECT_GODOT --trace CLEAN_TRACE

Never calibrate from a changed game. The trace must include an in-play player and
native, unrotated view; missing body/visibility is refused rather than guessed.
The resulting spec still requires a person's review and approval.
"""
import argparse
import json
import math
from configparser import ConfigParser
from pathlib import Path

from expectrail.gate.verify import observations


def region(project: Path, trace: dict) -> list[float]:
    display = []
    section = ""
    for line in project.read_text(encoding="utf-8").splitlines():
        if line.startswith("["):
            section = line.strip()
        elif section == "[display]":
            display.append(line)
    config = ConfigParser(interpolation=None)
    config.read_string("[display]\n" + "\n".join(display))
    settings = config["display"]
    width, height = (settings.getint("window/size/viewport_" + axis) for axis in ("width", "height"))
    for axis, size in (("width", width), ("height", height)):
        if not size or size <= 0 or settings.getint(f"window/size/window_{axis}_override", size) != size:
            raise ValueError("Dodge's check needs a positive viewport displayed at its native size")

    offsets = set()
    for row in trace.get("rows", []):
        if row.get("playerVisible") is not True:
            continue
        player, body = row.get("player"), row.get("body")
        if not (isinstance(player, list) and len(player) == 2 and isinstance(body, list) and len(body) == 4):
            raise ValueError("an in-play clean frame lacks a measured player body")
        if row.get("view") != [1, 0, 0, 1, 0, 0]:
            raise ValueError("Dodge's clean replay needs the native identity view")
        if not all(type(n) in (int, float) and math.isfinite(n) for n in player + body):
            raise ValueError("player body and position must be finite numbers")
        if body[2] <= body[0] or body[3] <= body[1]:
            raise ValueError("the clean player body must have positive dimensions")
        x, y = player
        # Ask the same converter the gate uses, WITH the actual measured body.
        origin = dict(row, tick=0, player=[0, 0], body=[body[0]-x, body[1]-y, body[2]-x, body[3]-y])
        obs = observations({"physicsTicksPerSecond":60,"rows":[origin]},"0"*64)
        offsets.add(tuple(obs["frames"][0]["objects"]["player"][0]["box"]))
    if not offsets:
        raise ValueError("no in-play clean frame measured the player's body; cannot derive a region")
    if len(offsets) != 1:
        raise ValueError("the clean player's converted body changes size/offset; cannot use one fixed region")
    left, top, right, bottom = offsets.pop()
    return [left, top, width + right, height + bottom]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_godot", type=Path)
    parser.add_argument("--trace", required=True, type=Path, help="real clean replay's trace.json")
    args = parser.parse_args()
    print(json.dumps(region(args.project_godot, json.loads(args.trace.read_text(encoding="utf-8")))))
