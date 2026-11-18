"""The Unity trace as engine observations: the Unity game's counterpart of ``harness/web/layout.py``.

``observations(trace, spec)`` turns the harness's record into ``expectrail.observations/v0`` for the
objects a test spec names, so the unchanged evaluator judges the Unity game on what the engine says,
as it judges the Godot game on its position log. Unlike ``agents/observations.py``, nothing here is a
size measured on the Godot game:

- **player, coin, enemy, projectile**: each object of that role in the row's ``objects``, by its
  renderer's bounds in frame pixels (``harness/unity/package/Runtime/Recorder.cs``), and only when
  the harness found it visible (active, its renderer on, its sprite drawn and not transparent, and
  inside the camera's view). An object it did not find visible is absent from that frame: a
  ``visible`` spec fails there, and a spec that needs it to compare (``never-crosses``) is
  needs-review there, never a pass.
- **ground**: the row's ``ground`` (world y of the tile surface under the player, from the level's
  geometry) in frame pixels, with the camera of the frame (``agents.observations._view_at``: a row
  holds the camera of the frame drawn before it), as a box from that line to the bottom of the frame.
  A row with no ground has no ground box.

Frame ``n`` is tick ``n``: the harness draws one frame a physics tick.

``engine_objects(trace, names)`` and ``agreeing(trace, names)`` are what the SAM adapter takes
(``agents.sam_observations.from_replay``), as ``agents/web_bench.py`` hands it the page's: the boxes
of objects SAM is not asked to find (the ground), and a filter that keeps a SAM box for an object only
where it overlaps the engine's box for that object in that frame. Agreement only removes detections.

``python3 -m agents.unity_observations calibrate TRACE`` prints what the Unity checks' constants have
to come from, measured on a trace: the player's box, where its bottom sits against the ground line
when the game says it is on the floor, and the coins'. The replay job runs it on the clean trace.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Callable

from agents.observations import _to_frame, _view_at

MODEL_NAME = "expectrail.unity-engine"
# The harness player's window (harness/unity/package/Editor/HarnessBuild.cs): 1600 x 960.
FRAME_SIZE = (1600, 960)
ROLES = frozenset({"player", "coin", "enemy", "projectile"})
GROUND = "ground"
AGREE_IOU = 0.5
# A row the game calls on the floor, but whose box bottom is more than this far above the ground line,
# stands on something that is not the ground tilemap: the ground check cannot see a sink there.
OFF_GROUND_PX = 5.0


def _in_frame(box: list[float], frame_size: tuple[int, int]) -> bool:
    width, height = frame_size
    return box[2] > 0 and box[3] > 0 and box[0] < width and box[1] < height and box[2] > box[0] and box[3] > box[1]


def role_boxes(row: dict, role: str, frame_size: tuple[int, int] = FRAME_SIZE) -> list[dict]:
    """The visible objects of one role in a row, as detections in frame pixels."""
    return [{"box": list(o["box"]), "score": 1.0, "source": "engine"}
            for o in row.get("objects") or []
            if o.get("role") == role and o.get("visible") and o.get("box") is not None
            and _in_frame(o["box"], frame_size)]


def ground_line(rows: list[dict], i: int) -> float | None:
    """The frame y of the ground under the player on row ``i``, or None."""
    row = rows[i]
    ground, player, view = row.get("ground"), row.get("player"), _view_at(rows, i)
    if ground is None or player is None or not view:
        return None
    return _to_frame(view, float(player[0]), float(ground))[1]


def ground_boxes(rows: list[dict], i: int, frame_size: tuple[int, int] = FRAME_SIZE) -> list[dict]:
    y = ground_line(rows, i)
    if y is None:
        return []
    width, height = frame_size
    return [{"box": [0.0, round(y, 3), float(width), float(max(height, y + 1))], "score": 1.0, "source": "engine"}]


# The harness's ground search (harness/unity/maps/unity-platformer.json, "ground"; Recorder.GroundUnder):
# from SINK_WINDOW px above the player's origin, in its column and BODY_HALF_WIDTH px either side, the
# first solid tile surface at or below that point, within SEARCH_CELLS cells; the highest of the three.
SINK_WINDOW = 64.0
BODY_HALF_WIDTH = 20.0
SEARCH_CELLS = 16
CELL_PX = 128.0


def load_ground_config(map_path: Path) -> dict:
    """The ground search's constants from a harness map, so the reference uses the harness's own."""
    doc = json.loads(Path(map_path).read_text(encoding="utf-8"))
    ground, ppu = doc["ground"], float(doc.get("pixelsPerUnit", CELL_PX))
    return {"window": float(ground["sinkWindowPx"]), "half": float(ground["bodyHalfWidthPx"]),
            "depth": float(ground["searchCells"]) * ppu}


def _crossings(points: list, x: float) -> list[float]:
    """The y of every non-vertical edge of a closed path at x."""
    ys = []
    n = len(points)
    for i in range(n):
        (ax, ay), (bx, by) = points[i], points[(i + 1) % n]
        if ax == bx or x < min(ax, bx) or x > max(ax, bx):
            continue
        ys.append(ay + (by - ay) * (x - ax) / (bx - ax))
    return ys


def _inside(points: list, x: float, y: float) -> bool:
    """Whether (x, y) is inside a closed path (even-odd, a ray towards +x)."""
    inside = False
    n = len(points)
    for i in range(n):
        (ax, ay), (bx, by) = points[i], points[(i + 1) % n]
        if (ay > y) != (by > y) and x < ax + (bx - ax) * (y - ay) / (by - ay):
            inside = not inside
    return inside


def _solid(surfaces: list, x: float, y: float) -> bool:
    return any(_inside(points, x, y) for points in surfaces)


def column_ground(surfaces: list, x: float, start: float, depth: float, eps: float = 0.01) -> float | None:
    """In one column, the ground the harness's tile walk finds from ``start`` (y down): the first top
    surface (solid just below it, not just above) at or below ``start`` and within ``depth``. When
    ``start`` is already inside solid ground, the top of that solid, so a buried body is not given a
    floor beneath it."""
    ys = sorted({round(y, 4) for points in surfaces for y in _crossings(points, x)})
    if _solid(surfaces, x, start):
        above = [y for y in ys if y <= start and _solid(surfaces, x, y + eps) and not _solid(surfaces, x, y - eps)]
        return above[-1] if above else None
    for y in ys:
        if y < start or y > start + depth:
            continue
        if _solid(surfaces, x, y + eps) and not _solid(surfaces, x, y - eps):
            return y
    return None


def reference_ground(surfaces: list, x: float, y: float, config: dict | None = None) -> float | None:
    """World y (down) of the ground under a player whose origin is at (x, y), from level surfaces: the
    highest of the three columns' grounds, as the harness finds it."""
    c = config or {"window": SINK_WINDOW, "half": BODY_HALF_WIDTH, "depth": SEARCH_CELLS * CELL_PX}
    found = [g for dx in (-c["half"], 0.0, c["half"])
             if (g := column_ground(surfaces, x + dx, y - c["window"], c["depth"])) is not None]
    return min(found) if found else None


def with_reference_ground(trace: dict, surfaces: list, config: dict | None = None) -> dict:
    """The trace with every row's ground recomputed from trusted (the clean game's) level surfaces.

    A candidate may edit the level, so the ground its harness logs is the ground it shipped; judging
    it against the clean level means a fix cannot move the line it is measured by. SAM cannot check
    the ground either (docs/sam.md, docs/unity.md), so on Unity this is the only guard."""
    out = dict(trace)
    rows = []
    for row in trace.get("rows") or []:
        row = dict(row)
        player = row.get("player")
        ground = reference_ground(surfaces, float(player[0]), float(player[1]), config) if player is not None else None
        if ground is None:
            row.pop("ground", None)
        else:
            row["ground"] = round(ground, 3)
        rows.append(row)
    out["rows"] = rows
    out["groundReference"] = "clean level"
    return out


def reference_agreement(trace: dict, config: dict | None = None) -> dict:
    """How the reference ground, from the trace's own surfaces, agrees with the ground its harness
    logged: on a clean trace they must agree on every row, or the reference is not the harness's."""
    surfaces = trace.get("levelSurfaces") or []
    both = within = only_logged = only_reference = 0
    worst = 0.0
    for row in trace.get("rows") or []:
        player = row.get("player")
        if player is None:
            continue
        ref = reference_ground(surfaces, float(player[0]), float(player[1]), config)
        logged = row.get("ground")
        if ref is None and logged is None:
            continue
        if ref is None:
            only_logged += 1
        elif logged is None:
            only_reference += 1
        else:
            both += 1
            gap = abs(ref - float(logged))
            worst = max(worst, gap)
            within += gap <= 1.0
    return {"both": both, "within1px": within, "largestGap": round(worst, 3),
            "onlyLogged": only_logged, "onlyReference": only_reference}


def _boxes(rows: list[dict], i: int, name: str, frame_size: tuple[int, int]) -> list[dict]:
    if name == GROUND:
        return ground_boxes(rows, i, frame_size)
    if name in ROLES:
        return role_boxes(rows[i], name, frame_size)
    raise ValueError(f"the Unity trace has no object called {name!r}: it names roles {sorted(ROLES)} and {GROUND!r}")


def observations(trace: dict, spec: dict, replay_sha256: str = "0" * 64,
                 frame_size: tuple[int, int] = FRAME_SIZE) -> dict:
    rows = list(trace.get("rows") or [])
    names = list(spec.get("objects") or {})
    frames = [{"frame": row.get("frame", i), "objects": {name: _boxes(rows, i, name, frame_size) for name in names}}
              for i, row in enumerate(rows)]
    return {"format": "expectrail.observations/v0", "replay": {"sha256": replay_sha256},
            "model": {"name": MODEL_NAME, "prompts": {n: o.get("prompt", n) for n, o in spec["objects"].items()},
                      "units": "frame pixels",
                      "boxes": "renderer bounds of the objects the harness found visible; the ground line from the level's tiles"},
            "frames": frames}


def engine_objects(trace: dict, names: list[str], frame_size: tuple[int, int] = FRAME_SIZE) -> dict[int, dict]:
    """{frame: {name: [detection, ...]}} for objects SAM is not asked to find."""
    rows = list(trace.get("rows") or [])
    return {row.get("frame", i): {name: _boxes(rows, i, name, frame_size) for name in names}
            for i, row in enumerate(rows)}


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def agreeing(trace: dict, names: list[str], iou: float = AGREE_IOU,
             frame_size: tuple[int, int] = FRAME_SIZE) -> Callable[[dict[int, dict]], dict[int, dict]]:
    """{frame: {name: detections}} -> the same, keeping for each named role only the detections that
    overlap one of the engine's boxes for it in that frame by at least ``iou``."""
    rows = list(trace.get("rows") or [])
    by_frame = {row.get("frame", i): i for i, row in enumerate(rows)}

    def keep(observed: dict[int, dict]) -> dict[int, dict]:
        out: dict[int, dict] = {}
        for frame, objects in observed.items():
            out[frame] = dict(objects)
            i = by_frame.get(frame)
            for name in names:
                if name not in objects:
                    continue
                engine = [d["box"] for d in _boxes(rows, i, name, frame_size)] if i is not None else []
                out[frame][name] = [d for d in objects[name] if any(_iou(d["box"], e) >= iou for e in engine)]
        return out

    return keep


def _stats(values: list[float]) -> dict | None:
    if not values:
        return None
    return {"n": len(values), "min": round(min(values), 2), "median": round(statistics.median(values), 2),
            "max": round(max(values), 2)}


def _spans(ticks: list[int]) -> list[list[int]]:
    """Consecutive ticks as [first, last] spans."""
    spans: list[list[int]] = []
    for t in ticks:
        if spans and t == spans[-1][1] + 1:
            spans[-1][1] = t
        else:
            spans.append([t, t])
    return spans


def calibrate(trace: dict, frame_size: tuple[int, int] = FRAME_SIZE) -> dict:
    """What the Unity checks' constants come from, measured on one trace."""
    rows = list(trace.get("rows") or [])
    player = [role_boxes(r, "player", frame_size) for r in rows]
    coins = [role_boxes(r, "coin", frame_size) for r in rows]
    standing, airborne, off_ground = [], [], []
    for i, row in enumerate(rows):
        y = ground_line(rows, i)
        if y is None or not player[i]:
            continue
        gap = player[i][0]["box"][3] - y  # positive: the box's bottom is below the ground line
        (standing if row.get("onFloor") else airborne).append(gap)
        if row.get("onFloor") and gap < -OFF_GROUND_PX:
            off_ground.append(row.get("tick", i))
    boxes = [p[0]["box"] for p in player if p]
    coin_boxes = [c["box"] for frame in coins for c in frame]
    return {
        "rows": len(rows),
        "playerVisible": sum(1 for p in player if p),
        "playerSeveral": sum(1 for p in player if len(p) > 1),
        "playerWidth": _stats([b[2] - b[0] for b in boxes]),
        "playerHeight": _stats([b[3] - b[1] for b in boxes]),
        "groundRows": sum(1 for i in range(len(rows)) if ground_line(rows, i) is not None),
        "onFloorBottomMinusGround": _stats(standing),
        "onFloorOffGround": {"rows": len(off_ground), "spans": _spans(off_ground),
                             "onGround": _stats([g for g in standing if g >= -OFF_GROUND_PX])},
        "airborneBottomMinusGround": _stats(airborne),
        "coinsVisiblePerFrame": _stats([float(len(c)) for c in coins]),
        "coinWidth": _stats([b[2] - b[0] for b in coin_boxes]),
        "coinHeight": _stats([b[3] - b[1] for b in coin_boxes]),
    }


def calibration_line(c: dict) -> str:
    def s(v):
        return "none" if v is None else f"{v['min']}/{v['median']}/{v['max']} (n {v['n']})"

    return (f"player visible on {c['playerVisible']} of {c['rows']} rows (several at once on {c['playerSeveral']}); "
            f"player box w {s(c['playerWidth'])}, h {s(c['playerHeight'])}; ground line on {c['groundRows']} rows; "
            f"box bottom minus ground (px, + is below) on the floor {s(c['onFloorBottomMinusGround'])}, "
            f"of which on the ground tilemap {s(c['onFloorOffGround']['onGround'])} and above it by more than "
            f"{OFF_GROUND_PX:g} px on {c['onFloorOffGround']['rows']} rows (ticks "
            f"{', '.join(f'{a}-{b}' if a != b else str(a) for a, b in c['onFloorOffGround']['spans'][:8]) or 'none'}), "
            f"in the air {s(c['airborneBottomMinusGround'])}; coins visible a frame {s(c['coinsVisiblePerFrame'])}, "
            f"coin box w {s(c['coinWidth'])}, h {s(c['coinHeight'])} (min/median/max)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    cal = sub.add_parser("calibrate", help="measure the player, ground and coin boxes on a trace")
    cal.add_argument("trace", type=Path)
    cal.add_argument("--json", action="store_true", help="print the measurements as JSON")
    ref = sub.add_parser("reference", help="does the clean-level ground agree with the harness's on a clean trace")
    ref.add_argument("trace", type=Path)
    ref.add_argument("--map", type=Path, help="the harness map whose ground constants to use")
    args = ap.parse_args(argv)
    trace = json.loads(args.trace.read_text(encoding="utf-8"))
    if args.command == "reference":
        a = reference_agreement(trace, load_ground_config(args.map) if args.map else None)
        print(f"reference ground vs the harness's: both on {a['both']} rows, within 1 px on {a['within1px']}, "
              f"largest gap {a['largestGap']} px; only the harness's on {a['onlyLogged']}, "
              f"only the reference on {a['onlyReference']}")
        return 0 if a["within1px"] == a["both"] and not a["onlyLogged"] and not a["onlyReference"] else 1
    c = calibrate(trace)
    print(json.dumps(c, indent=1) if args.json else calibration_line(c))
    return 0


if __name__ == "__main__":
    sys.exit(main())
