"""Author one fixed-rail setup model from a pinned Godot reference and its replay."""

import argparse
import json
import math
import re
import subprocess
from pathlib import Path

from expectrail.contracts import canonical_v1, digest_v1, strict_loads, validate
from expectrail.evaluator import evaluate
from expectrail.gate.verify import observations
from expectrail.onboarding import ATTR, HEADER, property_value, resource
from expectrail.project_config import read_game
from expectrail.project_model import ModelError, draft_pair, read_model, write_model
from expectrail.resources import ROOT
from harness.run import GODOT_VERSION, run, sha256_file, tree_digest

IDENTITY = [1, 0, 0, 1, 0, 0]
ROLES = ("player", "goal", "home")
COLLIDER = re.compile(r'SubResource\("([^"\n]+)"\)')


def _one(sections, tag, **fields):
    matches = [body for kind, attrs, body in sections
               if kind == tag and all(attrs.get(key) == value for key, value in fields.items())]
    if len(matches) != 1:
        raise ModelError(f"needs-review: expected exactly one authored {tag} for {fields}")
    return matches[0]


def _y(value):
    match = re.fullmatch(r"Vector2\(\s*([^,]+),\s*([^)]+)\)", value or "")
    if match is None:
        raise ModelError("needs-review: the source needs a literal Vector2")
    try:
        parts = [float(part) for part in match.groups()]
    except ValueError as exc:
        raise ModelError("needs-review: the source needs a literal Vector2") from exc
    if not all(math.isfinite(part) for part in parts):
        raise ModelError("needs-review: source coordinates must be finite")
    return parts[1]


def _source_property(body, key):
    values = re.findall(r"^" + re.escape(key) + r"\s*=\s*(.*)$", body, re.M)
    if len(values) > 1:
        raise ModelError(f"needs-review: the source declares {key} more than once")
    return values[0].strip() if values else None


def authored_rail(project: Path, config: dict) -> tuple[dict, list]:
    """Read a direct child's authored position and local rectangular collider."""
    if config is None or config["adapter"] != "godot":
        raise ModelError("needs-review: this path requires a Godot project profile")
    settings = (project / "project.godot").read_text(encoding="utf-8-sig")
    if _source_property(settings, "run/main_scene") != json.dumps(config["entryScene"]):
        raise ModelError("needs-review: the configured entry scene must match the game's saved start scene")
    bindings = config["bindings"]
    nodes = [bindings.get(role, {}).get("node") for role in ROLES]
    if any(not isinstance(node, str) or "/" in node or not node for node in nodes) or len(set(nodes)) != len(ROLES):
        raise ModelError("needs-review: bind player, goal and home to distinct scene-root children")
    actor_name = nodes[0]
    scene = resource(project, config["entryScene"])
    if scene.suffix != ".tscn":
        raise ModelError("needs-review: use a saved text scene for this authoring path")
    text = scene.read_text(encoding="utf-8-sig")
    headers = list(HEADER.finditer(text))
    sections = [(header[1], {key: json.loads(value) for key, value in ATTR.findall(header[2])},
                 text[header.end():headers[i + 1].start() if i + 1 < len(headers) else len(text)])
                for i, header in enumerate(headers)]
    root = _one(sections, "node", type="Node2D", parent=None)
    actor = _one(sections, "node", name=actor_name, parent=".", type="CharacterBody2D")
    collider = _one(sections, "node", parent=actor_name, type="CollisionShape2D")
    if property_value(root, "position") or any(property_value(body, key)
            for body in (root, actor, collider) for key in ("transform", "scale", "skew", "rotation", "top_level")):
        raise ModelError("needs-review: authored rail needs an untransformed root, actor and collider")
    locator = COLLIDER.fullmatch(_source_property(collider, "shape") or "")
    if not locator:
        raise ModelError("needs-review: bind a local rectangle resource for the collider")
    shape = _one(sections, "sub_resource", id=locator[1], type="RectangleShape2D")
    offset = _source_property(collider, "position")
    center = _y(_source_property(actor, "position")) + (_y(offset) if offset is not None else 0)
    height = _y(_source_property(shape, "size"))
    if height <= 0:
        raise ModelError("needs-review: the authored collider height must be positive")
    band = {"kind": "fixed-axis-band", "subject": "player", "axis": "y", "coordinateSpace": "world",
            "units": "pixels", "minimum": center - height / 2, "maximum": center + height / 2}
    source = {"path": scene.relative_to(project).as_posix(), "sha256": sha256_file(scene)}
    origin = [dict(source, location=f"node:{actor_name}", property="position"),
              dict(source, location=f"collider:{actor_name}", property="shape"),
              dict(source, location=f"resource:{locator[1]}", property="size")]
    if offset is not None:
        origin.append(dict(source, location=f"collider:{actor_name}", property="position"))
    return band, origin


def _box(row, role, locator):
    matches = [obj for obj in row.get("roleObjects", []) if obj.get("role") == role]
    if len(matches) == 1:
        obj = matches[0]
        box = obj.get("worldBox")
        if (obj.get("id") == locator and obj.get("boundsSource") == "drawing" and obj.get("visible") is True
                and isinstance(box, list) and len(box) == 4 and all(type(value) in (int, float) and math.isfinite(value) for value in box)
                and box[0] < box[2] and box[1] < box[3]):
            return box
    raise ModelError(f"needs-review: incomplete or ambiguous {role} drawing at tick {row['tick']}")


def _touches(actor, mark):
    return actor[0] <= mark[2] and mark[0] <= actor[2] and actor[1] <= mark[3] and mark[1] <= actor[3]


def exercised_route(trace: dict, route: dict, config: dict) -> tuple[int, int]:
    """Find the two commanded legs in the complete, bound clean trace."""
    ticks, events, rows = route["ticks"], route["events"], trace.get("rows", [])
    if (trace.get("unknownActions") != [] or trace.get("bindings") != config["bindings"]
            or trace.get("viewport") != config["viewport"] or trace.get("ticks") != ticks
            or trace.get("physicsTicksPerSecond") != config["captureFps"]
            or [r.get("tick") for r in rows] != list(range(ticks))
            or any(r.get("view") != IDENTITY for r in rows)):
        raise ModelError("needs-review: the route must have a complete bound identity-transform recording")
    first, release, left = events if len(events) == 3 else ({}, {}, {})
    turn = left.get("tick", 0)
    if (first != {"tick": 0, "action": "right", "pressed": True}
            or not 0 < turn < ticks or release != {"tick": turn, "action": "right", "pressed": False}
            or left != {"tick": turn, "action": "left", "pressed": True}):
        raise ModelError("needs-review: the route must command right and then left")
    binding = config["bindings"]
    boxes = [tuple(_box(row, role, binding[role]["node"]) for role in ROLES) for row in rows]
    initial = boxes[0][0][0]
    goal = next((i for i, (actor, mark, _) in enumerate(boxes[:turn])
                 if actor[0] > initial and _touches(actor, mark)), None)
    right_edge = boxes[turn - 1][0][0]
    home = next((i for i, (actor, _, mark) in enumerate(boxes[turn:], turn)
                 if actor[0] < right_edge and _touches(actor, mark)), None)
    if goal is None or home is None:
        raise ModelError("needs-review: the reference did not exercise both commanded legs")
    return goal, home


def reference_identity(project: Path, route_path: Path, route: dict, config: dict, engine: dict) -> dict:
    harness_files = [ROOT / "harness/run.py", *sorted((ROOT / "harness/godot").glob("*.gd"))]
    return {
        "treeSha256": tree_digest(project), "profileSha256": digest_v1(config),
        "bindingsSha256": digest_v1(config["bindings"]),
        "harnessSha256": digest_v1({path.name: sha256_file(path) for path in harness_files}),
        "engine": engine,
        "route": {"name": route["name"], "sha256": sha256_file(route_path), "ticks": route["ticks"]},
        "capture": {"viewport": config["viewport"], "ticksPerSecond": config["physicsTicksPerSecond"],
                    "framesPerSecond": config["captureFps"]},
    }


def author(project: Path, route_path: Path, godot: Path, out: Path) -> dict:
    project, out = project.resolve(), out.resolve()
    if out.is_relative_to(project):
        raise ModelError("use a new output directory outside the reference tree")
    config = read_game(project)
    constraint, sources = authored_rail(project, config)
    route = strict_loads(route_path.read_text(encoding="utf-8"))
    validate(route, "route")
    version = subprocess.check_output([str(godot.resolve(strict=True)), "--version"], text=True, timeout=10).strip()
    if not version.startswith(GODOT_VERSION.replace("-", ".") + "."):
        raise ModelError(f"needs-review: use pinned Godot {GODOT_VERSION}")
    engine = {"name": "godot", "version": version, "sha256": sha256_file(godot)}
    reference = reference_identity(project, route_path, route, config, engine)
    out.mkdir(parents=True, exist_ok=False)
    replay_dir = out / "reference-replay"
    replay = run(route_path, replay_dir, game=project, godot=godot, project=config,
                 fps=None, capture_frames=False)
    trace_path = replay_dir / "trace.json"
    recorded = sha256_file(trace_path)
    if (replay["game"]["tree"] != reference["treeSha256"] or replay["game"]["patch"] is not None
            or replay["route"]["sha256"] != reference["route"]["sha256"] or replay["trace"]["sha256"] != recorded
            or replay["engine"]["version"] != version
            or reference != reference_identity(project, route_path, route, read_game(project),
                                                {**engine, "sha256": sha256_file(godot)})):
        raise ModelError("needs-review: the replay or its reference inputs changed")
    trace = strict_loads(trace_path.read_text(encoding="utf-8"))
    validate(trace, "trace")
    goal, home = exercised_route(trace, route, config)
    model = {
        "format": "expectrail.project-model/v1", "reference": reference, "constraint": constraint, "sources": sources,
        "evidence": {"traceSha256": recorded, "transform": "identity", "firstTick": 0,
                     "lastTick": route["ticks"] - 1, "goalTick": goal, "returnTick": home},
    }
    observed = observations(trace, sha256_file(replay_dir / "replay.json"))
    for spec in draft_pair(model).values():
        verdict = evaluate(spec, observed, route=route["name"], trace=trace, source_kind="trace",
                           expected_frames=list(range(route["ticks"])), capture_fps=config["captureFps"])
        if verdict["result"] != "pass":
            raise ModelError(f"needs-review: the clean paired draft needs work ({spec['id']}: {verdict['reason']})")
    path = out / "project-model.json"
    write_model(path, model)
    checks = out / "checks"
    checks.mkdir()
    for spec in draft_pair(read_model(path, reference)).values():
        (checks / f"{spec['id']}.json").write_bytes(canonical_v1(spec))
    return model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("reference", "route", "godot", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    try:
        author(args.reference, args.route, args.godot, args.out)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"{exc}\n")
    print(args.out / "project-model.json")


if __name__ == "__main__":
    main()
