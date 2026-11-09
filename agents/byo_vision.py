"""Pluggable Vision & Open-Vocabulary Detection backends for Expectrail (`expectrail.observations/v0`).

Allows Expectrail to run frame verification using:
1. `local-http`: Any local open-vocabulary object detector (Grounding DINO + SAM 2.1, Florence-2,
   or Ultralytics YOLO-World) at $0.00 API cost.
2. `byo-vlm`: Any BYO Vision-Language Model (`anthropic`, `openai`, `gemini`, `openrouter`, `ollama`)
   using Expectrail's strict coordinate grid normalization (`pixels`, `norm1000`, `norm1`) and
   out-of-frame rejection (`OUT_OF_FRAME = 0.02`).
3. Event-driven keyframe selection (`select_event_keyframes`) to reduce cloud vision calls by ~85%.
"""

from __future__ import annotations

import base64
import json
import math
import os
import struct
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from expectrail.providers import (
    ProviderConfig,
    chat_completion,
    extract_message_text,
    resolve_provider,
    strip_json_fences,
)

MAX_OBJECTS = 30
OUT_OF_FRAME = 0.02

BOX_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["objects"],
    "properties": {
        "objects": {
            "type": "array",
            "maxItems": MAX_OBJECTS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["box", "confidence"],
                "properties": {
                    "box": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
    },
}

SYSTEM_PROMPT = (
    "You are the eyes of an automated test for an interactive application or 2D game. "
    "You look at one captured frame and report where a named object is drawn in it. "
    "Report only what is visibly drawn in this image: something hidden behind scenery, "
    "off screen, or not drawn at all is not visible. Never guess."
)

GRIDS = {
    "pixels": "Box corners are pixels of this image",
    "norm1000": (
        "Box corners are on a 0 to 1000 grid over the whole image "
        "(x 0 is the left edge and 1000 the right edge, y 0 the top edge and 1000 the bottom edge)"
    ),
    "norm1": (
        "Box corners are fractions of the image from 0 to 1 "
        "(x 0 is the left edge and 1 the right edge, y 0 the top edge and 1 the bottom edge)"
    ),
}


def png_dimensions(path: Path) -> tuple[int, int]:
    """Read (width, height) from a PNG header without requiring Pillow."""
    data = path.read_bytes()[:24]
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Not a valid PNG file: {path}")
    w, h = struct.unpack(">II", data[16:24])
    return int(w), int(h)


def image_data_url(path: Path) -> str:
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def normalize_box_to_pixels(
    raw_box: list[float],
    size: tuple[int, int],
    coords: str = "norm1000",
) -> list[float]:
    """Convert a raw [x0, y0, x1, y1] box from `pixels`, `norm1000`, or `norm1` into image pixels.

    Raises ValueError if any corner is more than OUT_OF_FRAME (2%) outside the frame or inverted.
    """
    if len(raw_box) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in raw_box):
        raise ValueError(f"Invalid box coordinates: {raw_box}")
    w, h = size
    x0, y0, x1, y1 = [float(v) for v in raw_box]
    if coords == "norm1000":
        x0, x1 = x0 * w / 1000.0, x1 * w / 1000.0
        y0, y1 = y0 * h / 1000.0, y1 * h / 1000.0
    elif coords == "norm1":
        x0, x1 = x0 * w, x1 * w
        y0, y1 = y0 * h, y1 * h
    elif coords != "pixels":
        raise ValueError(f"Unsupported coordinate grid: {coords}")

    tol_x = w * OUT_OF_FRAME
    tol_y = h * OUT_OF_FRAME
    if x0 < -tol_x or y0 < -tol_y or x1 > w + tol_x or y1 > h + tol_y or x1 <= x0 or y1 <= y0:
        raise ValueError(f"Box {raw_box} ({coords}) out of bounds for frame {w}x{h}")

    return [
        round(max(0.0, min(float(w), x0)), 2),
        round(max(0.0, min(float(h), y0)), 2),
        round(max(0.0, min(float(w), x1)), 2),
        round(max(0.0, min(float(h), y1)), 2),
    ]


class _ClientBase:
    """The interface agents.sam_observations.observe calls: ``segment``, ``model``, ``base``, ``calls``.

    Every failure leaves as SamError, so the verifier records needs-review: an outage or a bad answer
    can never become a pass.
    """

    provider = "byo"
    cache_tag = "#byo-1"
    engine_checked = False

    def __init__(self) -> None:
        self.calls = 0
        self.seconds = 0.0
        self._lock = threading.Lock()

    def detect_prompt(self, frame_path: Path, noun_phrase: str) -> list[dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError

    def segment(self, png: Path, prompt: str) -> list[dict[str, Any]]:
        from agents.sam_observations import SamError

        with self._lock:
            self.calls += 1
        started = time.monotonic()
        try:
            found = self.detect_prompt(png, prompt)
        except SamError:
            raise
        except Exception as exc:  # noqa: BLE001 - any failure is needs-review
            raise SamError(f"{self.provider}: {type(exc).__name__}: {exc}") from exc
        finally:
            with self._lock:
                self.seconds += time.monotonic() - started
        return sorted(found, key=lambda d: (-d["score"], d["box"]))


class BYOVLMObserverClient(_ClientBase):
    """Any vision-language model (anthropic, openai, gemini, openrouter, ollama, vllm) behind ``segment``.

    Like Muse Glimmer, a VLM does not decide a verdict alone (agents.sam_observations.default_client):
    the fixer controls the frames, and text drawn into the game could talk it into a pass. Use
    byo-vlm-engine, which counts its boxes only where the engine agrees.
    """

    def __init__(
        self,
        config: ProviderConfig | None = None,
        coords: str | None = None,
    ) -> None:
        super().__init__()
        self.config = config or resolve_provider(role="VLM")
        default_grid = "norm1000" if self.config.provider in ("gemini", "fireworks", "ollama") else "pixels"
        self.coords = coords or os.environ.get("EXPECTRAIL_VLM_COORDS", default_grid)
        if self.coords not in GRIDS:
            raise ValueError(f"EXPECTRAIL_VLM_COORDS must be one of {', '.join(GRIDS)}, not {self.coords!r}")
        self.model = self.config.model
        self.base = self.config.api_base
        self.provider = f"byo vision-language model {self.config.provider}/{self.model}, self-reported confidence"
        self.cache_tag = f"#byo-vlm-1#{self.coords}"

    def detect_prompt(self, frame_path: Path, noun_phrase: str) -> list[dict[str, Any]]:
        size = png_dimensions(frame_path)
        w, h = size
        size_line = f"This image is {w} by {h} pixels. " if self.coords == "pixels" else ""
        user_text = (
            f'{size_line}Find every visible "{noun_phrase}". '
            'Answer with JSON only: {"objects": [{"box": [x0, y0, x1, y1], "confidence": c}]}, '
            f"one entry per separate {noun_phrase}, at most {MAX_OBJECTS} entries. "
            f"{GRIDS[self.coords]}: x0, y0 is the top-left corner and x1, y1 the bottom-right corner. "
            "confidence is your certainty from 0 to 1. "
            'If none is visible, return {"objects": []}.'
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_data_url(frame_path)}},
                    {"type": "text", "text": user_text},
                ],
            },
        ]
        raw = chat_completion(
            messages,
            role="VLM",
            config=self.config,
            max_tokens=4096,
            temperature=0.0,
            json_schema=BOX_SCHEMA,
            schema_name="expectrail_boxes",
        )
        text = strip_json_fences(extract_message_text(self.config, raw))
        parsed = json.loads(text)
        results: list[dict[str, Any]] = []
        for item in parsed.get("objects", []):
            if "confidence" not in item:
                raise ValueError("a box without a confidence; a missing score is never guessed")
            px_box = normalize_box_to_pixels(item["box"], size, coords=self.coords)
            results.append({"box": px_box, "score": round(float(item["confidence"]), 4)})
        return results


class EngineCheckedBYOVLM(BYOVLMObserverClient):
    """A BYO VLM whose boxes count only where they agree with the game engine (agents.engine_check)."""

    engine_checked = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.provider += ", each box checked against the engine's position for that object"


class LocalHTTPDetectorClient(_ClientBase):
    """Zero-API-cost client for local Grounding DINO + SAM 2.1 / Florence-2 / YOLO-World servers.

    POSTs {image_base64, prompt, width, height}; expects {"objects": [{"box": [x0,y0,x1,y1],
    "score": s, "coords": "pixels"|"norm1000"|"norm1"}]}. A box without a score is refused.
    """

    def __init__(self, endpoint_url: str | None = None) -> None:
        super().__init__()
        self.endpoint_url = (
            endpoint_url
            or os.environ.get("EXPECTRAIL_LOCAL_VISION_URL", "http://localhost:8090/detect")
        )
        self.model = "local-http-detector"
        self.base = self.endpoint_url
        self.provider = f"local open-vocabulary detector at {self.endpoint_url}"
        self.cache_tag = "#local-http-1"

    def detect_prompt(self, frame_path: Path, noun_phrase: str) -> list[dict[str, Any]]:
        size = png_dimensions(frame_path)
        payload = json.dumps(
            {
                "image_base64": base64.b64encode(frame_path.read_bytes()).decode("ascii"),
                "prompt": noun_phrase,
                "width": size[0],
                "height": size[1],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results: list[dict[str, Any]] = []
        for item in data.get("objects", []):
            score = item.get("score", item.get("confidence"))
            if score is None:
                raise ValueError("a box without a score; a missing score is never guessed")
            px_box = normalize_box_to_pixels(item["box"], size, coords=item.get("coords", "pixels"))
            results.append({"box": px_box, "score": round(float(score), 4)})
        return results


def trace_keyframe_rows(trace: dict | None) -> list[dict[str, Any]]:
    """The harness trace's rows in the shape select_event_keyframes reads (frame, on_floor, y)."""
    rows = []
    for row in (trace or {}).get("rows", []):
        player = row.get("player") or [None, None]
        rows.append({"frame": row.get("frame", row.get("tick")), "on_floor": row.get("onFloor"),
                     "y": player[1] if len(player) > 1 else None})
    return rows


def select_event_keyframes(
    trace_rows: list[dict[str, Any]],
    total_frames: int,
    *,
    base_stride: int = 6,
) -> list[int]:
    """Select critical keyframes from engine telemetry (`trace.jsonl`) to cut vision API calls by ~85%.

    Always includes:
    - Frame 0 and the final frame (`total_frames - 1`)
    - Every `base_stride`th frame
    - Any frame where `on_floor` flips, vertical velocity sign flips, or `y` changes by >12px
      (plus the immediate neighbor frames `f-1`, `f`, `f+1`).
    """
    if total_frames <= 0:
        return []
    selected: set[int] = {0, max(0, total_frames - 1)}
    for f in range(0, total_frames, max(1, base_stride)):
        selected.add(f)

    prev_floor = None
    prev_vy = None
    prev_y = None
    for idx, row in enumerate(trace_rows):
        f = int(row.get("frame", idx))
        if f < 0 or f >= total_frames:
            continue
        on_floor = row.get("on_floor")
        vy = row.get("vy", row.get("velocity_y"))
        y = row.get("y", row.get("player_y"))
        interesting = False
        if prev_floor is not None and on_floor != prev_floor:
            interesting = True
        if prev_vy is not None and vy is not None and ((prev_vy <= 0 < vy) or (prev_vy >= 0 > vy)):
            interesting = True
        if prev_y is not None and y is not None and abs(float(y) - float(prev_y)) > 12.0:
            interesting = True
        if interesting:
            for neighbor in (f - 1, f, f + 1):
                if 0 <= neighbor < total_frames:
                    selected.add(neighbor)
        prev_floor = on_floor
        prev_vy = vy
        prev_y = y

    return sorted(selected)
