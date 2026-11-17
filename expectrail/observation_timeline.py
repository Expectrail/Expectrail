"""Capture placement and observation completeness; no image library or interpolation.

The harness records the draw's physics interval and camera. Rates describe the
clock, but do not replace those records. v0 documents remain readable; fresh
harness replays require v1 provenance before the trusted evaluator runs.
"""
from __future__ import annotations

import copy
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import stat
import struct

from expectrail.contracts import digest
from expectrail import resources

FORMAT = "expectrail.observation-timeline/v1"
OBSERVATIONS = "expectrail.observations/v1"
PLACEMENT = ("frame", "tick", "tickInterval", "phase", "viewport", "transform")


class TimelineError(ValueError):
    pass


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _require(ok, reason):
    if not ok:
        raise TimelineError("observation-timeline: " + reason)


def frame_count(trace, fps=60, ticks=None):
    """Recorded draws for new captures; legacy integral scheduling for old traces."""
    if "captureTimeline" in trace:
        return len(trace["captureTimeline"]["frames"])
    total = len(trace.get("rows", [])) if ticks is None else ticks
    tps = trace.get("physicsTicksPerSecond") or 120
    _require(_integer(tps, 1) and _integer(fps, 1), "invalid capture clock")
    _require(tps % fps == 0, "legacy trace has no explicit mapping for this non-integer tick/frame ratio")
    return total * fps // tps


def placement(trace, frame, fps=60):
    """One draw's placement. The legacy reader keeps its documented camera phase."""
    if "captureTimeline" in trace:
        frames = trace["captureTimeline"]["frames"]
        _require(0 <= frame < len(frames) and frames[frame]["frame"] == frame,
                 f"missing or unordered capture frame {frame}")
        return frames[frame]
    tps = trace.get("physicsTicksPerSecond") or 120
    _require(_integer(tps, 1) and _integer(fps, 1) and tps % fps == 0,
             "legacy trace has no explicit mapping for this non-integer tick/frame ratio")
    tick = (frame + 1) * tps // fps - 1
    rows = trace.get("rows") or []
    view = (rows[min(tick + 1, len(rows) - 1)].get("view") or rows[tick].get("view")) \
        if 0 <= tick < len(rows) else None
    return {"frame": frame, "tick": tick, "tickInterval": [frame * tps // fps, tick],
            "phase": "legacy-after-physics", "viewport": trace.get("viewport"), "transform": view}


def tick_for(trace, frame, fps=60):
    return placement(trace, frame, fps)["tick"]


def view_for(trace, frame, fps=60):
    return placement(trace, frame, fps)["transform"]


def frame_files(folder):
    """Do not collapse two names for one frame into a dict's last value."""
    found = {}
    for path in Path(folder).glob("f*.png"):
        match = re.fullmatch(r"f([0-9]+)\.png", path.name)
        _require(match is not None, "unrecognised capture filename")
        n = int(match[1])
        _require(n not in found, f"duplicate image for frame {n}")
        _require(not path.is_symlink() and stat.S_ISREG(path.stat().st_mode), f"frame {n} is not a regular image")
        found[n] = path
    return dict(sorted(found.items()))


def _image(path):
    _require(path.stat().st_size <= 128 * 1024 * 1024, "image exceeds 128 MiB")
    with path.open("rb") as stream:
        header = stream.read(24)
        _require(len(header) == 24 and header[:8] == b"\x89PNG\r\n\x1a\n" and header[12:16] == b"IHDR",
                 "capture is not a PNG with an IHDR")
        width, height = struct.unpack(">II", header[16:24])
        hasher = hashlib.sha256(header)
        for chunk in iter(lambda: stream.read(65536), b""):
            hasher.update(chunk)
    return [width, height], hasher.hexdigest()


def build(trace, frames_dir=None, *, ticks=None):
    """Join the harness's ordered draws to exact image bytes. Never infer missing draws."""
    capture = trace.get("captureTimeline")
    _require(isinstance(capture, dict), "the harness did not record a capture timeline")
    rows = trace.get("rows") or []
    total = len(rows) if ticks is None else ticks
    _require(_integer(total, 1) and [r.get("tick") for r in rows] == list(range(total)),
             "the engine record is missing, duplicated or out of order")
    _require(_integer(trace.get("physicsTicksPerSecond"), 1) and _integer(capture.get("fps"), 1),
             "invalid capture clock")
    frames = capture.get("frames")
    _require(isinstance(frames, list) and bool(frames), "no frames recorded by the harness")
    files = frame_files(frames_dir) if frames_dir is not None else None
    if files is not None:
        _require(list(files) == list(range(len(frames))),
                 f"captured images do not cover the timeline: {len(files)} files for {len(frames)} frames; "
                 f"missing {sorted(set(range(len(frames))) - files.keys())[:8]}")
    out, previous = [], -1
    for n, row in enumerate(frames):
        _require(isinstance(row, dict) and row.get("frame") == n and type(row.get("frame")) is int,
                 f"capture frame {n} is missing, duplicated or out of order")
        tick, interval, viewport, transform = (row.get(k) for k in ("tick", "tickInterval", "viewport", "transform"))
        _require(_integer(tick) and previous <= tick < total, f"frame {n} has an invalid or reversed tick")
        _require(interval == [min(previous + 1, tick), tick], f"frame {n} has a gap or overlap in its tick interval")
        _require(row.get("phase") in ("post-physics-pre-draw", "post-draw"), f"frame {n} has an unknown capture phase")
        _require(isinstance(viewport, list) and len(viewport) == 2 and all(_integer(v, 1) for v in viewport),
                 f"frame {n} has no measured viewport")
        _require(isinstance(transform, list) and len(transform) == 6 and all(
            type(v) in (int, float) and math.isfinite(v) for v in transform), f"frame {n} has no measured transform")
        _require(transform[0] * transform[3] - transform[1] * transform[2] != 0,
                 f"frame {n} has a singular transform")
        source = None
        if files is not None:
            size, source = _image(files[n])
            _require(size == viewport, f"frame {n} resolution is {size}; harness recorded {viewport}")
        out.append({**{k: copy.deepcopy(row[k]) for k in PLACEMENT}, "sourceSha256": source})
        previous = tick
    _require(previous == total - 1, f"capture stopped at tick {previous}; route ends at tick {total - 1}")
    return {"format": FORMAT, "traceSha256": digest(trace), "physicsTicksPerSecond": trace["physicsTicksPerSecond"],
            "captureFps": capture["fps"], "frames": out}


def emit(document, trace, frames_dir=None, *, version="1"):
    """Producer-side provenance. Old traces/documents remain v0, never fabricated v1."""
    if "captureTimeline" not in (trace or {}):
        return document
    timeline = build(trace, frames_dir)
    doc = copy.deepcopy(document)
    doc.update(format=OBSERVATIONS, timeline=timeline)
    sensor = {"name": str(doc["model"]["name"]), "version": version}
    for frame in doc["frames"]:
        n = frame["frame"]
        _require(_integer(n) and n < len(timeline["frames"]), "observation is outside the capture timeline")
        at = timeline["frames"][n]
        source = {"kind": "image" if frames_dir is not None else "trace",
                  "sha256": at["sourceSha256"] if frames_dir is not None else timeline["traceSha256"]}
        provenance = {"frame": n, "tick": at["tick"], "source": source, "coordinateSpace": "screen-pixels"}
        frame.update(**provenance, observer=sensor)
        for name, detections in frame["objects"].items():
            for detection in detections:
                engine_source = detection.get("source") == "engine" or frames_dir is None
                row = trace["rows"][at["tick"]]
                entities = [o for o in row.get("roleObjects", row.get("objects", [])) if o.get("role") == name]
                identity = detection.get("entityId")
                if identity is None and len(entities) == 1:
                    identity = str(entities[0]["id"])
                if identity is None and engine_source:
                    matches = [o for o in entities if o.get("box") == detection["box"]]
                    if len(matches) == 1:
                        identity = str(matches[0]["id"])
                detection.update(copy.deepcopy(provenance), sensor=sensor,
                                 entityId=(identity if identity is not None else
                                           f"{name}:{detection['track']}" if "track" in detection else
                                           f"{name}:unique" if len(detections) == 1 else None))
                if engine_source:
                    detection["source"] = {"kind": "trace", "sha256": timeline["traceSha256"]}
                    detection["sensor"] = {"name": "engine-record", "version": "1"}
    return doc


@lru_cache(maxsize=1)
def _validator():
    from jsonschema import Draft202012Validator
    path = resources.ROOT / "contracts/observations.schema.json"
    return Draft202012Validator(json.loads(path.read_text()))


def singular_names(spec):
    assertion = spec["assertion"]
    # `visible` asks whether any member of the class is visible; it does not select an entity.
    if assertion["type"] == "visible":
        return set()
    names = {assertion["object"]}
    if assertion["type"] == "reaches":
        names.add(assertion["goal"])
    if assertion["type"] == "inside-region" and "relativeTo" in assertion["region"]:
        names.add(assertion["region"]["relativeTo"])
    return names


def ambiguity(spec, document):
    window = spec.get("window") or {}
    lo, hi = window.get("fromFrame", 0), window.get("toFrame", math.inf)
    for frame in document.get("frames", []):
        if not lo <= frame["frame"] <= hi:
            continue
        for name in spec["objects"]:
            if any(d.get("engineAgreement") is False and d.get("score", 0) >= spec["objects"][name].get("minScore", .5)
                   for d in frame.get("objects", {}).get(name, [])):
                return f"ambiguous identity: {name} pixel box disagrees with engine placement at frame {frame['frame']}"
        for name in singular_names(spec):
            score = spec["objects"][name].get("minScore", .5)
            found = [d for d in frame.get("objects", {}).get(name, []) if d.get("score", 0) >= score]
            if len(found) > 1:
                return f"ambiguous identity: {name} has {len(found)} candidates at frame {frame['frame']}"
            if found and document.get("format") == OBSERVATIONS and found[0].get("entityId") is None:
                return f"ambiguous identity: {name} has no entity id at frame {frame['frame']}"
    return None


def validate(spec, document, *, trusted=None, expected_frames=None, source_kind=None):
    """Completeness/provenance before geometry. Returns a named gap, never repairs evidence."""
    issue = ambiguity(spec, document)
    if issue:
        return issue
    if document.get("format") != OBSERVATIONS:
        return "observation-timeline: legacy observations have no capture provenance" if trusted else None
    error = next(_validator().iter_errors(document), None)
    if error is not None:
        return "observation-timeline: invalid observations at " + "/".join(map(str, error.path))
    timeline = document["timeline"]
    reference = trusted or timeline
    if any(timeline[k] != reference[k] for k in ("format", "traceSha256", "physicsTicksPerSecond", "captureFps")):
        return "observation-timeline: observations name another engine record or clock"
    if [f["frame"] for f in reference["frames"]] != list(range(len(reference["frames"]))):
        return "observation-timeline: capture frames are missing, duplicated or out of order"
    if len(timeline["frames"]) != len(reference["frames"]):
        return "observation-timeline: capture frame count differs from the harness"
    previous = -1
    for n, at in enumerate(reference["frames"]):
        if at["tick"] < previous or at["tickInterval"] != [min(previous + 1, at["tick"]), at["tick"]]:
            return f"observation-timeline: invalid tick interval at frame {n}"
        transform = at["transform"]
        if not all(math.isfinite(v) for v in transform) or transform[0] * transform[3] == transform[1] * transform[2]:
            return f"observation-timeline: invalid transform at frame {n}"
        previous = at["tick"]
    frames = document["frames"]
    ids = [f["frame"] for f in frames]
    if ids != sorted(set(ids)):
        return "observation-timeline: observation frames are duplicated or out of order"
    wanted = expected_frames
    if wanted is None:
        window = spec.get("window") or {}
        wanted = [f["frame"] for f in reference["frames"] if f["frame"] >= window.get("fromFrame", 0)
                  and f["frame"] <= window.get("toFrame", math.inf)]
    missing = sorted(set(wanted) - set(ids))
    if missing:
        return f"observation-timeline: observer gap at frames {missing[:8]}; no interpolation"
    if not wanted:
        return "observation-timeline: required window has no frames"
    for frame in frames:
        n = frame["frame"]
        if n >= len(reference["frames"]) or n >= len(timeline["frames"]):
            return f"observation-timeline: frame {n} is outside the capture"
        at = reference["frames"][n]
        if any(timeline["frames"][n].get(k) != at.get(k) for k in PLACEMENT):
            return f"observation-timeline: placement differs from the harness at frame {n}"
        if source_kind == "image":
            for detection in frame["objects"].get(spec["assertion"]["object"], []):
                if detection["source"]["kind"] != "image":
                    return f"observation-timeline: visual target is not pixel evidence at frame {n}"
        for item in [frame] + [d for ds in frame["objects"].values() for d in ds]:
            if item["frame"] != n or item["tick"] != at["tick"] or item["coordinateSpace"] != "screen-pixels":
                return f"observation-timeline: shifted frame/tick or coordinate space at frame {n}"
            source = item["source"]
            kind = source["kind"]
            if source_kind is not None and item is frame and kind != source_kind:
                return f"observation-timeline: wrong sensor source at frame {n}"
            expected = at["sourceSha256"] if kind == "image" else reference["traceSha256"]
            if expected is None or source["sha256"] != expected:
                return f"observation-timeline: source digest differs at frame {n}"
    return None
