"""Observations providers: trace stand-in by default; SAM 3.1 when asked.

Default provider ``trace`` builds expectrail.observations/v0 from harness
trace.json world positions (y-down boxes). Set ``EXPECTRAIL_OBS_PROVIDER=sam``
(or pass provider=\"sam\") to use SAM 3.1 through the Meta Model API
(``agents.sam_observations``, docs/sam.md). Verifier and loop call ``from_trace``
through this module only.

Gameplay motion is still judged by agents.gameplay from the harness/fixture
trace; SAM replaces the position-log stand-in for the observations document.
"""
from __future__ import annotations

import importlib
import math
import os
from typing import Callable

from expectrail.contracts import digest

PLAYER_HALF_W = 20.0
PLAYER_H = 60.0
GROUND_DEPTH = 400.0
# never-crosses tolerance is in the same units as these boxes (world px).
FLOOR_TOLERANCE_PAD = 12.0
# Where the player's feet are relative to its origin, measured on the clean game (its collision
# rectangle's bottom edge). A constant on purpose: a bug that moves or shrinks the player's own
# collision shape must not move the yardstick it is judged by.
FEET_OFFSET = 13.25

PROVIDER_ENV = "EXPECTRAIL_OBS_PROVIDER"
DEFAULT_PROVIDER = "trace"


def _floor_y(rows: list[dict]) -> float:
    """Lowest walkable surface in y-down space (max on-floor y).

    Median of all on-floor samples skews upward when the smoke route lands on
    platforms, which makes standing on the real ground look like fall-through.
    """
    samples = [
        float(r["player"][1])
        for r in rows
        if r.get("player") is not None and r.get("onFloor") is True
    ]
    if samples:
        return float(max(samples))
    # Fall-through-only traces: use the earliest player y as a standing guess.
    for r in rows:
        if r.get("player") is not None:
            return float(r["player"][1])
    return 452.0


def _start_x(rows: list[dict]) -> float:
    for r in rows:
        if r.get("player") is not None and r.get("onFloor") is True:
            return float(r["player"][0])
    for r in rows:
        if r.get("player") is not None:
            return float(r["player"][0])
    return 210.0


def _player_box(x: float, y: float) -> list[float]:
    return [x - PLAYER_HALF_W, y - PLAYER_H, x + PLAYER_HALF_W, y]


def _frame_tick(n: int, step: int) -> int:
    """The physics tick whose state a captured frame shows: the last one before it was drawn."""
    return n * step + step - 1


def _view_at(rows: list[dict], tick: int) -> list | None:
    """The camera a frame was drawn with, for the frame that shows tick ``tick``.

    The harness reads the camera inside the physics tick, so a row holds the camera of the frame
    drawn before it: the frame showing tick t was drawn with the camera logged on tick t + 1
    (measured against the image scroll). The last frame has no later row and keeps its own.
    """
    later = rows[min(tick + 1, len(rows) - 1)].get("view")
    return later or rows[tick].get("view")


def _to_frame(view: list, x: float, y: float) -> tuple[float, float]:
    return view[0] * x + view[2] * y + view[4], view[1] * x + view[3] * y + view[5]


def _frame_box(view: list, box: list[float]) -> list[float]:
    (ax, ay), (bx, by) = _to_frame(view, box[0], box[1]), _to_frame(view, box[2], box[3])
    return [round(min(ax, bx), 3), round(min(ay, by), 3), round(max(ax, bx), 3), round(max(ay, by), 3)]


def from_trace_synthetic(
    trace: dict,
    replay_sha256: str = "0" * 64,
    fps: int = 60,
    physics_tps: int | None = None,
) -> dict:
    """Build expectrail.observations/v0 from a harness trace (position-log stand-in).

    Physics is 120 Hz and capture is 60 fps, so a frame shows the state after every other tick.

    Traces from the current harness carry the level's ground line (``ground``) and the camera
    (``view``): the ground box then sits on that line, the player's box ends at its feet
    (origin + FEET_OFFSET), and both are in captured-frame pixels like SAM's boxes, so a spec's
    tolerancePx means the same thing for either provider. A row with no ground line (no tile
    collision under the player, or a level with none at all) has no ground observation, so a check
    against the ground cannot be decided there and is needs-review: an unmeasured ground is never
    stood in for by a guess.

    Traces from before the harness logged the camera fall back to world pixels and a floor taken
    from the player's own on-floor positions, which cannot see a player that rests too low. That
    fallback is for those old traces only. Until November 12, 2026 it also took every trace that had
    no ground line at all, and a game with no tile ground (Godot's Dodge the Creeps, #263) was
    rejected against a floor guessed at 0.
    """
    rows = list(trace.get("rows") or [])
    tps = physics_tps or int(trace.get("physicsTicksPerSecond") or 120)
    step = max(tps // fps, 1)
    floor = _floor_y(rows)
    start_x = _start_x(rows)
    in_frame = any(r.get("view") for r in rows)   # today's harness logs the camera in every row
    measured = any(r.get("ground") is not None for r in rows)

    frames = []
    if in_frame:
        for n in range(len(rows) // step):
            tick = _frame_tick(n, step)
            row, view = rows[tick], _view_at(rows, tick)
            player, g = row.get("player"), row.get("ground")
            objects: dict = {"ground": [], "player": []}
            if player is not None and view:
                x, y = float(player[0]), float(player[1])
                if g is not None:
                    gx, gy = _to_frame(view, x, float(g))
                    objects["ground"] = [{"box": [round(gx - 4000.0, 3), round(gy, 3), round(gx + 4000.0, 3),
                                                  round(gy + 2 * GROUND_DEPTH, 3)], "score": 0.95, "track": 2}]
                if y <= floor + 800:  # far below the level: off screen, so not seen
                    objects["player"] = [{"box": _frame_box(view, _player_box(x, y + FEET_OFFSET)),
                                          "score": 0.94, "track": 1}]
            frames.append({"frame": n, "objects": objects})
    else:
        ground = [start_x - 200.0, floor, start_x + 2000.0, floor + GROUND_DEPTH]
        for row in rows:
            tick = int(row["tick"])
            if tick % step != 0:
                continue
            player = row.get("player")
            objects = {"ground": [{"box": list(ground), "score": 0.95, "track": 2}]}
            if player is None or float(player[1]) > floor + 800:
                objects["player"] = []
            else:
                objects["player"] = [{"box": _player_box(float(player[0]), float(player[1])), "score": 0.94,
                                      "track": 1}]
            frames.append({"frame": tick // step, "objects": objects})

    return {
        "format": "expectrail.observations/v0",
        "replay": {"sha256": replay_sha256},
        "model": {
            "name": "expectrail.trace-synthetic",
            "prompts": {
                "player": "blue robot",
                "ground": "grass-topped ground",
            },
            "ground": ("level tile geometry (harness)" if measured else "not measured: no tile collision under the player")
            if in_frame else "player's own on-floor positions",
            "units": "captured-frame pixels" if in_frame else "world pixels",
        },
        "frames": frames,
    }


def _load_sam_provider() -> Callable[..., dict]:
    """Import the SAM 3.1 adapter (``agents.sam_observations``, Meta Model API).

    ``from_replay(...)`` takes ``from_trace_synthetic``'s kwargs plus ``frames_dir`` and
    ``spec`` (prompts, window, sampling); the trace itself is unused there.
    """
    try:
        mod = importlib.import_module("agents.sam_observations")
    except ImportError as exc:
        raise SystemExit(
            f"{PROVIDER_ENV}=sam but agents.sam_observations is not installed "
            f"(pair with Zayyad). Import error: {exc}"
        ) from exc
    fn = getattr(mod, "from_replay", None) or getattr(mod, "from_trace", None)
    if not callable(fn):
        raise SystemExit(
            "agents.sam_observations must export from_replay(trace, ...) or from_trace(...)"
        )
    return fn


def resolve_provider(name: str | None = None) -> str:
    raw = (name or os.environ.get(PROVIDER_ENV) or DEFAULT_PROVIDER).strip().lower()
    if raw not in ("trace", "sam"):
        raise SystemExit(f"unknown observations provider {raw!r} (want trace|sam)")
    return raw


DRILL_ENV = "EXPECTRAIL_JUDGE_DRILL"
DRILL_ALL = "sam-unavailable"  # SAM is down from the start: the pre-run check stops the run
DRILL_MID_RUN = "sam-outage-mid-run"  # the pre-run check passes for real, then SAM goes down: the judge ladder runs
DRILLS = (DRILL_ALL, DRILL_MID_RUN)


def judge_drill(stage: str = "judge") -> str | None:
    """A judge-outage drill (docs/fallbacks.md), so a fallback can be run end to end on purpose. Every
    SAM request made at ``stage`` fails as an outage would, before any cache. ``sam-unavailable`` takes
    SAM down at every stage, so the pre-run check stops the run; ``sam-outage-mid-run`` leaves the
    pre-run check (``stage="preflight"``) alone, so the run reaches the judge ladder. It touches SAM
    only (backends ``sam`` and ``both``); Glimmer checked against the engine answers, or fails to, for
    real. Returns the outage message, or None when no drill applies."""
    raw = os.environ.get(DRILL_ENV, "").strip().lower()
    if not raw:
        return None
    if raw not in DRILLS:
        raise SystemExit(f"{DRILL_ENV}={raw!r}: the drills are {', '.join(DRILLS)}")
    if raw == DRILL_MID_RUN and stage == "preflight":
        return None
    from agents.sam_observations import SamError, vision_backend

    try:
        backend = vision_backend()
    except SamError:
        backend = "sam"
    if backend not in ("sam", "both"):
        return None
    return f"drill ({DRILL_ENV}={raw}): SAM made unavailable on purpose"


def from_trace(
    trace: dict,
    replay_sha256: str = "0" * 64,
    fps: int = 60,
    physics_tps: int | None = None,
    *,
    provider: str | None = None,
    frames_dir: str | None = None,
    spec: dict | None = None,
    engine_objects: dict | None = None,
) -> dict:
    """Dispatch to the configured observations provider.

    ``provider=trace`` (default): synthetic boxes from the position log; ``spec`` is ignored.
    ``provider=sam``: ``agents.sam_observations`` (SAM 3.1 over the captured frames). A SAM
    failure surfaces as SystemExit, which the verifier turns into needs-review for the candidate,
    clean and held-out checks; it is never a pass.
    """
    kind = resolve_provider(provider)
    if kind == "trace":
        return from_trace_synthetic(
            trace, replay_sha256=replay_sha256, fps=fps, physics_tps=physics_tps,
        )
    drill = judge_drill()
    if drill:
        raise SystemExit(f"sam observations unavailable: {drill}")
    sam = _load_sam_provider()
    sam_error = getattr(importlib.import_module("agents.sam_observations"), "SamError", None)
    catch = sam_error if isinstance(sam_error, type) and issubclass(sam_error, Exception) else ()

    kwargs = {
        "replay_sha256": replay_sha256,
        "fps": fps,
        "physics_tps": physics_tps,
        "frames_dir": frames_dir,
        "spec": spec,
    }
    if engine_objects is not None:
        kwargs["engine_objects"] = engine_objects
    while True:
        try:
            return sam(trace, **kwargs)
        except catch as exc:
            raise SystemExit(f"sam observations unavailable (kind={getattr(exc, 'kind', 'unknown')}): {exc}") from exc
        except TypeError as exc:
            # An older adapter may not take every kwarg; drop only the one it rejects.
            dropped = next((k for k in ("engine_objects", "spec", "frames_dir")
                            if k in kwargs and f"'{k}'" in str(exc)), None)
            if dropped is None:
                raise
            kwargs.pop(dropped)


def observations_digest(doc: dict) -> str:
    return digest(doc)


def engine_ground_by_frame(trace: dict, frame_size: tuple[int, int], frames: list[int],
                           fps: int = 60) -> dict[int, dict]:
    """The level's ground line for each captured frame, in that frame's pixels.

    From the harness's ``ground`` (world y of the tile surface under the player) and ``view`` on
    the last physics tick before the frame was drawn (see _frame_tick and _view_at). Returns
    {frame: {"ground": [box]}}, with an empty list when the engine logged no ground then.
    """
    rows = list(trace.get("rows") or [])
    step = max(int(trace.get("physicsTicksPerSecond") or 120) // fps, 1)
    width, height = frame_size
    out: dict[int, dict] = {}
    for n in frames:
        tick = _frame_tick(n, step)
        if tick >= len(rows):
            continue
        row, view = rows[tick], _view_at(rows, tick)
        g, player = row.get("ground"), row.get("player")
        if g is None or not view or player is None:
            out[n] = {"ground": []}
            continue
        _, y = _to_frame(view, float(player[0]), float(g))
        out[n] = {"ground": [{"box": [0.0, round(y, 3), float(width), float(max(height, y + 1))],
                              "score": 1.0, "source": "engine"}]}
    return out


# Half the size of a coin as the game draws it, in world pixels: one 32x32 cell of coin.webp at the
# coin sprite's 0.65 scale, measured on the clean game. A constant, like FEET_OFFSET, so a candidate
# that resizes its coins does not move the yardstick its coins are checked against.
COIN_HALF = 10.4


def engine_refs_by_frame(trace: dict, frame_size: tuple[int, int], frames: list[int],
                         fps: int = 60) -> dict[int, dict[str, list[list[float]]]]:
    """Where the engine put each checkable object on each captured frame, as boxes in frame pixels.

    ``player``: the robot's body (origin to feet, as from_trace_synthetic draws it), from the
    position log. ``coin``: every coin still in the level, from the harness's ``coins`` rows. Both
    use the camera of that frame (``view``). A frame the trace cannot place (no row, no camera) is
    left out, so a caller can tell "the engine has nothing here" from "no coins here". The frame
    size is accepted for symmetry with engine_ground_by_frame; boxes may lie off the frame.
    """
    del frame_size
    rows = list(trace.get("rows") or [])
    step = max(int(trace.get("physicsTicksPerSecond") or 120) // fps, 1)
    out: dict[int, dict[str, list[list[float]]]] = {}
    for n in frames:
        tick = _frame_tick(n, step)
        if tick >= len(rows):
            continue
        row, view = rows[tick], _view_at(rows, tick)
        if not view:
            continue
        player = row.get("player")
        refs: dict[str, list[list[float]]] = {"player": [], "coin": []}
        if player is not None:
            x, y = float(player[0]), float(player[1])
            refs["player"] = [_frame_box(view, _player_box(x, y + FEET_OFFSET))]
        for cx, cy in row.get("coins") or []:
            refs["coin"].append(_frame_box(view, [float(cx) - COIN_HALF, float(cy) - COIN_HALF,
                                                  float(cx) + COIN_HALF, float(cy) + COIN_HALF]))
        out[n] = refs
    return out


def has_engine_refs(trace: dict) -> bool:
    """Whether the trace can place objects in frame pixels (it logs the camera)."""
    return any(r.get("view") for r in trace.get("rows") or [])


def has_engine_ground(trace: dict) -> bool:
    return any(r.get("ground") is not None and r.get("view") for r in trace.get("rows") or [])


# The ground search, the same as the harness's (_ground_under in expectrail_harness.gd), but over
# the level surfaces of a game the verifier trusts: the clean game, not the candidate.
SINK_WINDOW = 64.0
BODY_HALF_WIDTH = 20.0


def _polygon_top(points: list, x: float) -> float | None:
    top = None
    n = len(points)
    for i in range(n):
        (ax, ay), (bx, by) = points[i], points[(i + 1) % n]
        if x < min(ax, bx) or x > max(ax, bx):
            continue
        y = min(ay, by) if ax == bx else ay + (by - ay) * (x - ax) / (bx - ax)
        if top is None or y < top:
            top = y
    return top


def surface_under(surfaces: list, x: float, y: float) -> float | None:
    """World y of the highest solid surface under a body at (x, y), at most SINK_WINDOW above it."""
    best = None
    floor_limit = y - SINK_WINDOW
    for dx in (-BODY_HALF_WIDTH, 0.0, BODY_HALF_WIDTH):
        for points in surfaces:
            top = _polygon_top(points, x + dx)
            if top is not None and top >= floor_limit and (best is None or top < best):
                best = top
    return best


# How far the top of the floor's drawn art sits above its collision, measured on the clean game: the
# grass tufts on top of the tiles. Over all 3,648 exposed surface columns of the clean level the art
# starts 1 to 10 px above the collision, 8 px at the mode. A constant, like FEET_OFFSET, so a
# candidate cannot move it.
DRAWN_GROUND_OFFSET = 8.0


def drawn_surface_under(art: dict, x: float, y: float) -> float | None:
    """World y of the floor as it is drawn under a body at (x, y), or None.

    ``art`` is the trace's levelArt (where the harness found the tile layers opaque when rendered
    alone). Per body column, the first drawn run that starts at or below y - SINK_WINDOW and reaches
    down past the feet; its top, lowered by DRAWN_GROUND_OFFSET, is where the floor's top would be
    if its art matched the clean game's. The highest line over the columns wins, as for
    surface_under.
    """
    columns = art.get("columns") or []
    x0, width = int(art.get("x0", 0)), int(art.get("width", len(columns)))
    floor_limit, feet = y - SINK_WINDOW, y + FEET_OFFSET
    best = None
    for dx in (-BODY_HALF_WIDTH, 0.0, BODY_HALF_WIDTH):
        i = math.floor(x + dx) - x0
        if not 0 <= i < min(width, len(columns)):
            continue
        for top, bottom in columns[i]:
            # Art that starts above the window is a platform overhead or a wall beside the body, not a
            # floor under it; the collision search skips those surfaces the same way. Art that ends
            # above the feet is the overhanging end of a platform the robot is jumping up beside (seen
            # on the public combat route), not a floor: a floor reaches down past the feet.
            if top < floor_limit or bottom <= feet:
                continue
            if best is None or top < best:
                best = float(top)
            break
    return None if best is None else best + DRAWN_GROUND_OFFSET


def with_reference_ground(trace: dict, surfaces: list) -> dict:
    """The trace with every row's ground line recomputed from trusted level surfaces.

    A candidate may edit the level, so the ground it logs is the ground it shipped. Judging it
    against the clean game's surfaces means a fix cannot move the yardstick it is measured by.

    When the trace carries levelArt (the floor as the candidate's game draws it), the line is the
    higher of the clean level's collision and the drawn floor: a robot whose body rests on the
    collision but is drawn inside a floor whose art was moved up looks sunk, and fails. Art moved
    down (a robot that looks like it floats) leaves the collision line in charge.
    """
    out = dict(trace)
    art = trace.get("levelArt") if isinstance(trace.get("levelArt"), dict) else None
    rows = []
    for row in trace.get("rows") or []:
        row = dict(row)
        player = row.get("player")
        ground = surface_under(surfaces, float(player[0]), float(player[1])) if player is not None else None
        if art is not None and player is not None:
            drawn = drawn_surface_under(art, float(player[0]), float(player[1]))
            if drawn is not None and (ground is None or drawn < ground):
                ground = drawn
        if ground is None:
            row.pop("ground", None)
        else:
            row["ground"] = round(ground, 3)
        rows.append(row)
    out["rows"] = rows
    out["groundReference"] = "clean level, and the floor as drawn" if art is not None else "clean level"
    return out
