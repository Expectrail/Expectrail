"""`expectrail inspect --at-tick N`: what the engine reported for each bound object at one tick.

The static `inspect` reads saved scenes and never starts the game. This replays the project's own
config headless along one route and reads the role records every configured replay writes
(``roleObjects``, #538): per bound object, its node path, its box in captured-frame pixels and in
world units, and the engine's visible flag. Writer: ``document``; reader: ``problems``; contract:
``contracts/inspection.v1.schema.json``.

It is setup information. A box is the bounds of the object's drawing (or, labelled, its collision
shape), not its opaque pixels; visible is the engine's flag, not a claim that anything was seen. A
bound role with no object at the tick is listed as absent, never given a box. Anything this cannot
read is refused with what to change, never shown as a measurement.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from expectrail import project_config, resources

FORMAT = "expectrail.inspection/v1"
SCHEMA = resources.ROOT / "contracts" / "inspection.v1.schema.json"
NOTE = ("These are the engine's geometry and visible flag at this tick, not what a camera image shows: "
        "a box is the drawing's bounds, not its opaque pixels.")
# The recorder writes a node's path with '#' doubled, then '#N' for the Nth node seen at that path.
IDENTITY = re.compile(r"((?:[^#]|##)+)(?:#([1-9][0-9]*))?")


class InspectionError(ValueError):
    """The inspection cannot be made as asked. The message names what to change."""


def split_identity(identity: str) -> tuple[str, int]:
    """The recorder's stable id as (node path, generation)."""
    match = IDENTITY.fullmatch(identity) if isinstance(identity, str) else None
    if match is None:
        raise InspectionError(f"the replay recorded an object id that cannot be read: {json.dumps(str(identity))[:200]}")
    return match[1].replace("##", "#"), int(match[2] or 1)


def on_screen(box, viewport) -> bool:
    left, top, right, bottom = box
    width, height = viewport
    return right > left and bottom > top and right > 0 and bottom > 0 and left < width and top < height


def selector(binding: dict) -> str:
    return f"node:{binding['node']}" if "node" in binding else f"group:{binding['group']}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _route(root: Path, config: dict, given: Path | None) -> tuple[Path, str]:
    if given is not None:
        path = Path(given)
        if not path.is_file():
            raise InspectionError(f"--route {given}: no such route file; give the path of a route JSON file")
        return path, "argument"
    routes = config.get("routes") or []
    if not routes:
        raise InspectionError("the project config lists no routes: give one with --route ROUTE, or make a first "
                              "route with `expectrail route --project GAME --auto --out routes/first.json` and "
                              "add it to the config's routes")
    path = (root / routes[0])
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or path.is_symlink():
        raise InspectionError(f"the config's first route {routes[0]} is a link or leads outside the project; "
                              "keep the route as an ordinary file inside the game folder")
    if not resolved.is_file():
        raise InspectionError(f"the config's first route {routes[0]} does not exist; restore it or give --route ROUTE")
    return resolved, "config"


def _route_ticks(path: Path) -> tuple[str, int | None]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InspectionError(f"the route {path.name} cannot be read as JSON ({type(exc).__name__}); fix the file") from exc
    if not isinstance(doc, dict):
        raise InspectionError(f"the route {path.name} is not a route object; fix the file")
    ticks = doc.get("ticks")
    name = doc.get("name") if isinstance(doc.get("name"), str) and doc.get("name") else path.stem
    return name[:200], ticks if isinstance(ticks, int) and not isinstance(ticks, bool) and ticks > 0 else None


def _scrub(exc: BaseException, out: Path) -> str:
    """The harness's reason without a pointer into the replay folder, which is removed on return."""
    text = str(exc).replace(f"; see {out / 'godot.log'}", "")
    return text.replace(str(out), "<removed replay folder>")


def document(root: Path, tick: int, route: Path | None = None, *, replay=None, godot: Path | None = None) -> dict:
    """Replay ``root`` with its own config along ``route`` (default: the config's first route) and
    return the ``expectrail.inspection/v1`` record for ``tick``. Raises InspectionError."""
    if not isinstance(tick, int) or isinstance(tick, bool) or tick < 0:
        raise InspectionError("--at-tick takes a whole number of physics ticks from 0")
    root = Path(root).resolve()
    if not (root / "project.godot").is_file():
        raise InspectionError(f"{root} has no project.godot; give the folder that holds the Godot project")
    path = project_config.find(root)
    if path is None:
        raise InspectionError(f"--at-tick replays the objects the project config binds, and this game has no "
                              f"{project_config.FILENAME}. Write one with `expectrail init --project GAME`, review "
                              "its bindings, then inspect again")
    config = project_config.load(path, root)
    bindings = config.get("bindings") or {}
    if not bindings:
        raise InspectionError(f"{project_config.FILENAME}: bindings is empty; bind at least the player, then inspect again")
    route_path, source = _route(root, config, route)
    route_name, route_ticks = _route_ticks(route_path)
    if route_ticks is not None and tick >= route_ticks:
        raise InspectionError(f"the route {route_name} is {route_ticks} ticks long; choose --at-tick from 0 to "
                              f"{route_ticks - 1}. Nothing was replayed")
    config_sha = _sha256(path)
    if replay is None:
        from harness.run import run as replay
    with tempfile.TemporaryDirectory(prefix="expectrail-inspect-") as tmp:
        out = Path(tmp) / "replay"
        options = {"godot": godot} if godot is not None else {}
        try:
            record = replay(route_path, out, game=root, capture_frames=False, fps=None, project=config, **options)
        except SystemExit as exc:
            raise InspectionError(f"the replay could not finish: {_scrub(exc, out)}") from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise InspectionError(f"the replay could not finish ({type(exc).__name__}): {_scrub(exc, out)}") from exc
        if _sha256(path) != config_sha:
            raise InspectionError(f"{project_config.FILENAME} changed during the replay; keep it unchanged and inspect again")
        try:
            trace = json.loads((out / "trace.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise InspectionError(f"the replay left no readable trace ({type(exc).__name__}); cannot tell") from exc
    return from_trace(trace, tick, config=config, config_sha256=config_sha, game_tree=record["game"]["tree"],
                      route={"name": route_name, "sha256": _sha256(route_path), "from": source})


def from_trace(trace: dict, tick: int, *, config: dict, config_sha256: str, game_tree: str, route: dict) -> dict:
    """The record for ``tick`` from a configured replay's trace. Raises InspectionError."""
    if not isinstance(trace, dict) or trace.get("capabilities", {}).get("roleBoxes") is not True:
        raise InspectionError("the replay recorded no role boxes, so the bound objects cannot be measured: "
                              "cannot tell. Replay with this version's harness")
    rows = trace.get("rows")
    viewport = trace.get("viewport")
    rate = trace.get("physicsTicksPerSecond")
    if not isinstance(rows, list) or not rows or not isinstance(viewport, list) or len(viewport) != 2:
        raise InspectionError("the replay's trace has no rows or no viewport: cannot tell")
    if tick >= len(rows):
        raise InspectionError(f"the replay recorded ticks 0 to {len(rows) - 1}; choose --at-tick in that range")
    row = rows[tick]
    if not isinstance(row, dict) or row.get("tick") != tick or not isinstance(row.get("roleObjects"), list):
        raise InspectionError(f"the trace's row {tick} is not tick {tick}'s role record: cannot tell")
    bindings = config["bindings"]
    objects = []
    for obj in row["roleObjects"]:
        if not isinstance(obj, dict) or obj.get("role") not in bindings:
            raise InspectionError(f"the replay recorded an object for a role the config does not bind: cannot tell")
        node, generation = split_identity(obj.get("id"))
        objects.append({"role": obj["role"], "node": node, "generation": generation, "box": obj.get("box"),
                        "worldBox": obj.get("worldBox"), "visible": obj.get("visible"),
                        "onScreen": on_screen(obj.get("box"), viewport) if _is_box(obj.get("box")) else False,
                        "boundsSource": obj.get("boundsSource")})
    seen = {o["role"] for o in objects}
    doc = {"format": FORMAT,
           "project": {"entryScene": config.get("entryScene"), "configSha256": config_sha256, "gameTree": game_tree},
           "route": route, "tick": tick, "lastTick": len(rows) - 1, "physicsTicksPerSecond": rate,
           "viewport": viewport, "objects": objects,
           "absent": [{"role": role, "selector": selector(bindings[role])} for role in sorted(bindings) if role not in seen]}
    found = problems(doc)
    if found:
        raise InspectionError("the replay's role record cannot be reported: " + "; ".join(found[:3]) + ". Cannot tell")
    return doc


def _is_box(box) -> bool:
    return (isinstance(box, list) and len(box) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in box))


def problems(doc) -> list[str]:
    """Why ``doc`` is not a valid inspection record ([] when it is). onScreen and the lists are
    recomputed, not taken on the record's word."""
    from expectrail.gate import record as rec

    try:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"inspection: the schema could not be read ({type(exc).__name__})"]
    found = [f"inspection: {e}" for e in rec.errors(doc, schema)]
    if found:
        return found
    if doc["tick"] > doc["lastTick"]:
        found.append("inspection: tick is past the last tick the replay recorded")
    for n, obj in enumerate(doc["objects"]):
        for name in ("box", "worldBox"):
            a, b, c, d = obj[name]
            if c < a or d < b:
                found.append(f"inspection: objects/{n}/{name} has its right or bottom before its left or top")
        if obj["onScreen"] != on_screen(obj["box"], doc["viewport"]):
            found.append(f"inspection: objects/{n}/onScreen does not follow from its box and the viewport")
    present = {o["role"] for o in doc["objects"]}
    absent = [a["role"] for a in doc["absent"]]
    if len(set(absent)) != len(absent):
        found.append("inspection: a role is listed as absent twice")
    if present & set(absent):
        found.append("inspection: a role is both measured and absent")
    return found


def _num(value) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


def describe(doc: dict) -> list[str]:
    width, height = doc["viewport"]
    origin = "the config's first route" if doc["route"]["from"] == "config" else "the given route"
    lines = [f"Tick {doc['tick']} of 0 to {doc['lastTick']} on route {doc['route']['name']} ({origin}), "
             f"{doc['physicsTicksPerSecond']} physics ticks per second; frame {width} x {height} pixels."]
    for obj in doc["objects"]:
        a, b, c, d = (_num(v) for v in obj["box"])
        node = obj["node"] + (f" (node {obj['generation']} at this path)" if obj["generation"] > 1 else "")
        lines.append(f"  {obj['role']}: {node}, box {a},{b} to {c},{d} px, "
                     f"{'visible' if obj['visible'] else 'hidden'}, {'on screen' if obj['onScreen'] else 'off screen'}, "
                     f"{obj['boundsSource']} bounds")
    for item in doc["absent"]:
        lines.append(f"  {item['role']}: no object at this tick ({item['selector']})")
    lines.append(NOTE)
    return lines
