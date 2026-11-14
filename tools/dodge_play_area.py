"""Print Dodge's inside-region box from its pinned project.godot and the gate's player box."""
import argparse
import json
from configparser import ConfigParser
from pathlib import Path

from expectrail.gate.verify import observations


def region(project: Path) -> list[float]:
    # Other sections of project.godot contain multiline Godot resources, not INI values.
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

    # The pinned scene has no camera. At native size the view is the identity.
    row = {"tick": 0, "player": [0, 0], "view": [1, 0, 0, 1, 0, 0]}
    obs = observations({"physicsTicksPerSecond": 60, "rows": [row]}, "0" * 64)
    left, top, right, bottom = obs["frames"][0]["objects"]["player"][0]["box"]
    return [left, top, width + right, height + bottom]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_godot", type=Path)
    print(json.dumps(region(parser.parse_args().project_godot)))
