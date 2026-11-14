"""The visual observer for games Expectrail did not write: ask about the player's place, not a word (#330).

Why: the outside trial judged kinematic-character with the bundled game's spec, which asks the vision
model for a "blue robot". That game's player is a grey square in a level made of squares, so the
model found the player in 0 of 120 frames (run 43559500793). Words cannot name a player the team has
never seen. A place can: the engine's record says where the player's collision box is in every
tick (the trace's ``body``, #259), and the model is asked what is drawn inside that box, widened by
a few pixels. The point probe asked that of the same game on November 12 and found a 16 x 16 object
in 13 of 13 frames (run 43304967915, docs/sam.md).

What stays independent: the model is told where to look, never what it should find. Its answer is
the box of what is drawn there, and the spec's assertion is judged on that box (for
player-stays-above-ground, against the engine's ground line, as before). A player that is drawn
somewhere else, drawn wrongly or not drawn at all gives a box that disagrees, or no box, which is
needs-review: a frame missing the player is never read as agreement (expectrail.evaluator).

What it leans on, said plainly: the place comes from the engine, so if the engine's record and the
picture both lie in the same way, this cannot see it. That is why the observer is used for a game
only after it has been measured on that game's clean run, against rules fixed here in advance
(``RULES``, November 14, 2026), and the measurement is published with every verdict:

- found:  the model answered with a box holding the place it was asked about, in at least
          ``found`` of the asked frames;
- size:   of those, at least ``size`` have a box within ``sizeTolerance`` of the engine's own
          collision box (the drawn player is about the size the engine says it is);
- stable: asked again with a box ``wideFactor`` times as large, at least ``stable`` of the frames
          give a box of the same size (within ``sizeTolerance``). A model that only echoes the box
          it was given fails here: its answer grows with the question. A model that sees the player
          gives the player again.

A game that does not meet all three keeps no visual observer, and its verdicts stay needs-review,
as before. Nothing here can make a decision accept on its own: the gate's rule ``both`` still needs
the engine's checks and this observer's evidence on them.

Every asked frame is a paid image when the client is live. The calibration asks about every tenth
clean frame twice (26 images for a 120-frame route). Recorded once per game (Option A,
expectrail.recorded), the same answers replay for free in CI.
"""
from __future__ import annotations

import statistics
from pathlib import Path

from expectrail.gate.verify import NoAnswer

CALIBRATION_FORMAT = "expectrail.vision-calibration/v1"
NAME = "sam-anchored"
PAD = 4.0              # game pixels added on each side of the collision box (agents.sam_anchor.DEFAULT_PAD)
CALIBRATION_EVERY = 10
# Fixed November 14, 2026, before any live answer for an outside game was seen (#330). Changing any of
# these is a decision for Sean, recorded on #330; the calibration record carries them.
RULES = {"found": 0.9, "size": 0.9, "stable": 0.9, "sizeTolerance": 0.25, "wideFactor": 2.0, "minFrames": 8}
MAX_FRAMES = 64
MAX_WHY = 200


def _body_size(trace: dict, frame: int) -> tuple[float, float] | None:
    from agents.observations import _frame_tick

    rows = list(trace.get("rows") or [])
    step = max(int(trace.get("physicsTicksPerSecond") or 120) // 60, 1)
    tick = _frame_tick(frame, step)
    body = rows[tick].get("body") if tick < len(rows) else None
    if not body:
        return None
    return float(body[2]) - float(body[0]), float(body[3]) - float(body[1])


def _places(trace: dict, frames: dict[int, Path], chosen: list[int], pad: float) -> dict[int, dict]:
    from agents.sam_anchor import BODY, anchors
    from agents.sam_observations import png_size

    return anchors(trace, png_size(frames[chosen[0]]), chosen, box=BODY, pad=pad) if chosen else {}


def _close(a: float, b: float, tolerance: float) -> bool:
    return b > 0 and abs(a - b) <= tolerance * b


def _answer_size(answer: dict, scale: list) -> tuple[float, float]:
    x0, y0, x1, y1 = answer["box"]
    sx, sy = (s or 1.0 for s in scale)
    return (x1 - x0) / sx, (y1 - y0) / sy


def _holds(answer: dict, point: list) -> bool:
    x0, y0, x1, y1 = answer["box"]
    return x0 <= point[0] < x1 and y0 <= point[1] < y1


def calibrate(game: dict, run: dict, client, *, every: int = CALIBRATION_EVERY, rules: dict | None = None) -> dict:
    """expectrail.vision-calibration/v1 for one game, measured on one clean replay.

    ``game`` is {"name", "commit"}; ``run`` a finished replay (``trace``, ``framesDir``,
    ``replaySha256``); ``client`` answers ``segment_in``. A model error that the next frame would meet
    too (no key, the cap, the network) is raised as NoAnswer: a calibration that stopped is not one."""
    from agents.sam_anchor import STOP_KINDS
    from agents.sam_observations import SamError, frame_files, sample

    rules = dict(rules or RULES)
    folder = run.get("framesDir")
    frames = frame_files(Path(folder)) if folder and Path(folder).is_dir() else {}
    trace = run.get("trace") or {}
    chosen = sample(sorted(frames), every)[:MAX_FRAMES]
    normal = _places(trace, frames, chosen, PAD)
    rows = []
    for n in chosen:
        place = normal[n]
        body = _body_size(trace, n)
        if "why" in place or "promptBox" not in place or body is None:
            rows.append({"frame": n, "asked": False, "why": str(place.get("why", "no collision box"))[:MAX_WHY]})
            continue
        wide_pad = PAD + (rules["wideFactor"] - 1) * (max(body) + 2 * PAD) / 2
        wide = _places(trace, frames, [n], wide_pad)[n]
        try:
            got = client.segment_in(frames[n], [tuple(place["promptBox"])])[0]
            again = client.segment_in(frames[n], [tuple(wide["promptBox"])])[0] if "promptBox" in wide else None
        except SamError as exc:
            if exc.kind in STOP_KINDS or exc.status is not None or exc.kind == "not-recorded":
                raise NoAnswer(f"the calibration stopped ({str(exc.kind)[:60]})") from exc
            got = again = None
        row = {"frame": n, "asked": True, "body": [round(body[0], 1), round(body[1], 1)],
               "found": False, "sizeAgrees": False, "stable": False}
        if got is not None and _holds(got, place["point"]):
            size = _answer_size(got, place["scale"])
            row.update(found=True, size=[round(size[0], 1), round(size[1], 1)],
                       sizeAgrees=all(_close(s, b, rules["sizeTolerance"]) for s, b in zip(size, body)))
            if again is not None:
                wsize = _answer_size(again, wide["scale"])
                row["wideSize"] = [round(wsize[0], 1), round(wsize[1], 1)]
                row["stable"] = all(_close(w, s, rules["sizeTolerance"]) for w, s in zip(wsize, size))
        rows.append(row)
    return judge_calibration(game, run.get("replaySha256", "0" * 64), rows, rules,
                             model=str(getattr(client, "model", "unknown"))[:80],
                             provider=str(getattr(client, "provider", "unknown"))[:200])


def judge_calibration(game: dict, replay_sha256: str, rows: list[dict], rules: dict, *, model: str,
                      provider: str) -> dict:
    """The calibration record from measured rows, by ``rules``: enabled only when every rule holds."""
    asked = [r for r in rows if r["asked"]]
    found = [r for r in asked if r["found"]]
    rates = {
        "found": round(len(found) / len(asked), 3) if asked else 0.0,
        "size": round(sum(r["sizeAgrees"] for r in found) / len(found), 3) if found else 0.0,
        "stable": round(sum(r["stable"] for r in found) / len(found), 3) if found else 0.0,
    }
    why = []
    if len(asked) < rules["minFrames"]:
        why.append(f"only {len(asked)} frames could be asked about (at least {rules['minFrames']} are needed)")
    for key, label in (("found", "frames where the player was found at its place"),
                       ("size", "found frames where the drawn size matches the engine's collision box"),
                       ("stable", "found frames where a box twice as large gives the same answer")):
        if rates[key] < rules[key]:
            why.append(f"{label}: {rates[key]:.0%}, below {rules[key]:.0%}")
    sizes = [r["size"] for r in found]
    return {
        "format": CALIBRATION_FORMAT,
        "game": {"name": str(game["name"])[:80], "commit": str(game["commit"])[:64]},
        "replay": {"sha256": replay_sha256},
        "observer": {"name": NAME, "model": model, "provider": provider, "box": "body", "pad": PAD},
        "rules": dict(rules),
        "frames": {"listed": len(rows), "asked": len(asked), "found": len(found)},
        "rates": rates,
        "drawnSize": ({"width": round(statistics.median(s[0] for s in sizes), 1),
                       "height": round(statistics.median(s[1] for s in sizes), 1)} if sizes else None),
        "enabled": not why,
        "why": [w[:MAX_WHY] for w in why][:8],
        "rows": rows[:MAX_FRAMES],
        "machineWritten": True,
    }


class CalibrationError(ValueError):
    """The calibration cannot be used. The observer is then not used either."""


def calibration_schema() -> dict:
    import json

    from expectrail import resources

    return json.loads((resources.ROOT / "contracts" / "vision-calibration.v1.schema.json").read_text(encoding="utf-8"))


def check_calibration(doc) -> dict:
    """``doc`` if it is a usable calibration: it matches the schema, its rules are the ones fixed in
    ``RULES``, and ``enabled`` follows from its own rates. Raises CalibrationError for anything else,
    so a hand-edited ``enabled: true`` is never believed."""
    from expectrail.gate import record as rec

    found = rec.errors(doc, calibration_schema())
    if found:
        raise CalibrationError(f"does not match the vision calibration schema: {found[0]}")
    if doc["rules"] != RULES:
        raise CalibrationError("measured against other rules than the ones fixed for #330")
    again = judge_calibration(doc["game"], doc["replay"]["sha256"], doc["rows"], doc["rules"],
                              model=doc["observer"]["model"], provider=doc["observer"]["provider"])
    if (again["enabled"], again["rates"], again["frames"]) != (doc["enabled"], doc["rates"], doc["frames"]):
        raise CalibrationError("its rates or its verdict do not follow from its own frames")
    return doc


class AnchoredObserver:
    """The visual observer, asked at the player's place. Used for a game only when ``calibration``
    says so; with a calibration that does not, every ``look`` is NoAnswer and the verdict says why.

    ``client`` answers ``segment_in`` (a live client, a RecordingClient around one, or a
    RecordedClient). ``player`` names the spec object that is the engine's player (default: the
    assertion's object)."""

    def __init__(self, client, calibration: dict, *, pad: float = PAD):
        self._client, self.calibration, self._pad = client, calibration, pad

    def _usable(self):
        if not self.calibration.get("enabled"):
            why = "; ".join(self.calibration.get("why") or ["not measured"])
            raise NoAnswer(f"vision is not calibrated for this game ({why})"[:300])
        return self._client

    def describe(self) -> dict:
        self._usable()
        return {"name": NAME, "provider": str(getattr(self._client, "provider", "meta-model-api"))[:80],
                "model": str(getattr(self._client, "model", "unknown"))[:80]}

    def segmenter(self):
        return self._usable()

    def look(self, spec: dict, run: dict, *, keep: bool = True) -> dict:
        from agents.observations import engine_ground_by_frame, has_engine_ground
        from agents.sam_anchor import STOP_KINDS
        from agents.sam_observations import SamError, frame_files, png_size, window

        client = self._usable()
        folder = run.get("framesDir")
        if folder is None or not Path(folder).is_dir():
            raise NoAnswer("the replay captured no frames")
        trace = run.get("trace") or {}
        objects = spec.get("objects") or {}
        player = (spec.get("assertion") or {}).get("object")
        engine = {"ground"} if "ground" in objects and has_engine_ground(trace) else set()
        others = sorted(set(objects) - {player} - engine)
        if player not in objects or others:
            raise NoAnswer("the anchored observer sees only the player and the engine's ground; this spec names "
                           + (", ".join(others)[:120] or "no player"))
        frames = frame_files(Path(folder))
        indices = window(sorted(frames), spec)
        if not indices:
            raise NoAnswer("no captured frame falls inside the spec's window")
        size = png_size(frames[indices[0]])
        places = _places(trace, frames, indices, self._pad)
        ground = engine_ground_by_frame(trace, size, indices) if engine else {}
        out = []
        for n in indices:
            place, found = places[n], []
            if "promptBox" in place and "why" not in place:
                try:
                    got = client.segment_in(frames[n], [tuple(place["promptBox"])])[0]
                except SamError as exc:
                    if exc.kind in STOP_KINDS or exc.status is not None or exc.kind == "not-recorded":
                        raise NoAnswer(f"the model did not answer ({str(exc.kind)[:60]})") from exc
                    got = None
                # An answer without a confidence is not used: the evaluator's threshold needs one.
                if got is not None and got.get("score") is not None and _holds(got, place["point"]):
                    found = [{"box": [float(v) for v in got["box"]], "score": float(got["score"])}]
            objs = {player: found}
            if engine:
                objs["ground"] = list(ground.get(n, {}).get("ground", []))
            out.append({"frame": n, "objects": objs})
        model = {"name": str(getattr(client, "model", "unknown")),
                 "provider": str(getattr(client, "provider", "meta-model-api")),
                 "prompts": {player: f"what is drawn inside the engine's collision box, widened {self._pad:g} px"}}
        if engine:
            model["engineObjects"] = ["ground"]
        return {"format": "expectrail.observations/v0", "replay": {"sha256": run["replaySha256"]}, "model": model,
                "frames": out,
                "analysis": {"framesCaptured": len(frames), "framesInWindow": len(indices),
                             "framesAnalyzed": len(indices), "every": 1, "refined": None, "confirmed": 0}}
