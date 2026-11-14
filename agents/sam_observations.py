"""SAM 3.1 observations through the Meta Model API: the ``sam`` observations provider.

For the frames of one replay, asks SAM 3.1 (model ``sam-3.1`` on ``POST /v1/responses``) to find
each object a test spec names, and writes expectrail.observations/v0 with boxes in pixels of the
captured frame. The evaluator then decides the spec over that document, exactly as it does for the
position-log stand-in.

Looking at fewer frames (docs/sam.md has the reasoning and the limits):
  - sample: every Nth frame of the spec's window, plus its last frame (EXPECTRAIL_SAM_EVERY,
    default 4, the rate in docs/evaluation.md);
  - refine: when the spec fails on a sampled frame, look at every frame between the last passing
    sample and the first failing one, so the first bad frame in the report is exact;
  - confirm: a sampled pass is never the last word. Before passing, look at every remaining
    frame of the window, so a pass (and an accept built on it) rests on every frame; a fail
    found on a sample stays cheap (EXPECTRAIL_SAM_CONFIRM=0 turns this off, for probing only);
  - cache: results are kept by frame SHA-256, prompt, model and request settings, so a frame that
    was already judged is never sent again (EXPECTRAIL_SAM_CACHE; "off" disables it).
A frame that was not looked at is absent from the document, as the contract says.

The key is read from MODEL_API_KEY in the environment (or the gitignored .env) and nowhere else.
It is not on the fixer's environment allowlist (agents.keys.MUSE_ENV_ALLOWLIST), so Muse Code
never sees it.

    python3 -m agents.sam_observations --run runs/seeded/clean --spec specs/player-stays-above-ground.json
    EXPECTRAIL_OBS_PROVIDER=sam ...   # the verifier then uses this module through agents.observations
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import math
import os
import re
import struct
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Callable

from expectrail.evaluator import evaluate, _assertion_verdict

API_BASE = os.environ.get("EXPECTRAIL_MODEL_API_BASE", "https://api.meta.ai/v1")
MODEL = os.environ.get("EXPECTRAIL_SAM_MODEL", "sam-3.1")
KEY_ENV = "MODEL_API_KEY"
# Image segmentation price on the Meta Model API: $2.50 per 1,000 images
# (https://dev.meta.ai/docs/pricing-rate-limits, read Oct 29, 2026). Used only to report cost.
USD_PER_IMAGE = 2.50 / 1000
# Video segmentation on the same page: $0.20 per 1,000 frames, at least 50 frames billed a request.
USD_PER_VIDEO_FRAME = 0.20 / 1000
MIN_VIDEO_FRAMES = 50

# Every sam-3.1 request this process sent, across all clients and threads, for cost reporting.
# "images" counts image requests that got a response (one frame and one prompt each);
# "videoFrames" the frames billed for video requests that got one; "requests" also counts the
# tries that failed and were retried.
_usage = {"requests": 0, "images": 0, "videoFrames": 0, "reservedUsd": 0.0}
_usage_lock = threading.Lock()

# The most this process may spend on sam-3.1, in US dollars at list price. Every try is counted
# against it before it is sent, a failed try included, so the count can only be over what was
# billed. A request that would pass it is not sent. Without it no request leaves this machine.
CAP_ENV = "EXPECTRAIL_SAM_USD_CAP"


def usd_cap() -> float | None:
    """This run's spend cap from the environment, or None when none is set. A value that is not a
    plain amount of at least 0 is an error, never "no cap"."""
    raw = os.environ.get(CAP_ENV, "").strip()
    if not raw:
        return None
    try:
        cap = float(raw)
    except ValueError:
        cap = float("nan")
    if not (0.0 <= cap < float("inf")):
        raise SamError(f"{CAP_ENV} must be an amount in US dollars, 0 or more; it is {raw!r}", kind="budget")
    return cap


def _reserve(usd: float) -> None:
    """Count one try against the cap before it is sent; refuse it when it would pass the cap.

    When ``EXPECTRAIL_VISION_MONTH_LEDGER`` is set, the first try also reserves this run's whole
    cap against the month's $200 limit. A month that would be passed is a budget stop, and the
    request is not sent.
    """
    cap = usd_cap()
    if cap is not None and os.environ.get("EXPECTRAIL_VISION_MONTH_LEDGER", "").strip():
        from expectrail.spend import BudgetStop, admit_vision_month, note_stop
        try:
            admit_vision_month(cap)
        except BudgetStop as exc:
            note_stop("vision", str(exc))
            raise SamError(str(exc), kind="budget") from exc
    with _usage_lock:
        if cap is not None and _usage["reservedUsd"] + usd > cap + 1e-9:
            raise SamError(f"this run's SAM spend cap is reached: ${_usage['reservedUsd']:.4f} counted of "
                           f"${cap:.2f} ({CAP_ENV}), and the next request costs ${usd:.4f}; it was not sent",
                           kind="budget")
        _usage["reservedUsd"] += usd


def sam_usage() -> dict:
    """A snapshot of this process's sam-3.1 usage: {"requests", "images", "videoFrames", "reservedUsd"}.
    ``reservedUsd`` counts every try that was sent, at list price, and is what the cap is held against."""
    with _usage_lock:
        return dict(_usage)


def sam_images_since(before: dict) -> int:
    """Images sent to sam-3.1 since the snapshot ``before`` (from ``sam_usage``)."""
    return sam_usage()["images"] - before["images"]


def sam_usd_since(before: dict) -> float:
    """What the sam-3.1 requests since ``before`` cost at list price, images and video frames."""
    now = sam_usage()
    return ((now["images"] - before["images"]) * USD_PER_IMAGE
            + (now["videoFrames"] - before.get("videoFrames", 0)) * USD_PER_VIDEO_FRAME)
EVERY_ENV = "EXPECTRAIL_SAM_EVERY"
CONFIRM_ENV = "EXPECTRAIL_SAM_CONFIRM"
CACHE_ENV = "EXPECTRAIL_SAM_CACHE"
WORKERS_ENV = "EXPECTRAIL_SAM_WORKERS"
# Which model looks at the frames: sam (SAM 3.1, Meta Model API) or glimmer (Muse Glimmer, open
# weights, agents.glimmer_client). Everything else in this module is the same for both.
BACKEND_ENV = "EXPECTRAIL_VISION_BACKEND"
BACKENDS = ("sam", "glimmer", "both", "glimmer-engine", "local-http", "byo-vlm", "byo-vlm-engine")
GLIMMER_ALONE_ENV = "EXPECTRAIL_GLIMMER_ALONE"
VISION_LABELS = {"sam": "SAM 3.1", "glimmer": "Muse Glimmer", "both": "SAM 3.1 with Muse Glimmer",
                 "glimmer-engine": "Muse Glimmer checked against the engine",
                 "local-http": "a local open-vocabulary detector",
                 "byo-vlm": "a BYO vision-language model",
                 "byo-vlm-engine": "a BYO vision-language model checked against the engine"}
BYO_VLM_ALONE_ENV = "EXPECTRAIL_BYO_VLM_ALONE"
# Event keyframes (agents.byo_vision.select_event_keyframes) as the first sample instead of a stride.
KEYFRAMES_ENV = "EXPECTRAIL_KEYFRAMES_ONLY"
DEFAULT_EVERY = 4
DEFAULT_WORKERS = 4
# Bump when the request or the parsing changes, so older cache entries are never reused.
REQUEST_VERSION = "1"
# Confidence is required: the evaluator thresholds on it, and a missing score is never guessed.
# Masks are not used yet, so ask for the smaller encoding.
METADATA = {"include_confidence": "true", "mask_encoding": "one_bit"}
DEFAULT_PROMPTS = {"player": "blue robot", "ground": "grass-topped ground"}
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
# Kinds whose verdict fails as soon as one judged frame fails, so sampling can only miss a
# failure, never invent one, and refinement can only move the first failing frame earlier.
SAMPLE_SAFE = frozenset({"never-crosses", "inside-region"})

Transport = Callable[[dict], "tuple[bytes, str]"]


class SamError(RuntimeError):
    """SAM could not produce observations. Callers must treat the check as needs-review.

    ``kind`` says what went wrong, so a caller can tell a passing outage from one that waiting will
    not fix (agents/judge_ladder.py): auth, credit, budget (this run's own spend cap, or none set),
    rate-limit, server, network, request or unknown.
    ``status`` is the HTTP status when there was one.
    """

    def __init__(self, message: str, *, kind: str = "unknown", status: int | None = None):
        super().__init__(message)
        self.kind, self.status = kind, status


# Meta's out-of-credit reply has never been observed, so a body that says so counts as well as a 402:
# the OpenAI-compatible convention is a 429 reading "insufficient_quota".
# A plain "quota" is left out: a per-minute quota is a rate limit, and waiting does fix that.
_CREDIT_WORDS = re.compile(r"credit|insufficient|billing|balance|payment", re.I)


def http_error_kind(status: int, detail: str = "") -> str:
    """What an HTTP error from the model API means. Anything not explicit stays a passing outage."""
    if status == 402 or (status in (403, 429) and _CREDIT_WORDS.search(detail)):
        return "credit"
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate-limit"
    return "server" if status >= 500 else "request"


# ---------------------------------------------------------------------------------------------
# The wire format
# ---------------------------------------------------------------------------------------------

# One line per image (one per frame for video). A line starts with a frame marker <Nf> and holds
# comma-separated records: <id><|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..[;c=..]|><|mask;...|>
# Mask payloads never contain '|' or '<', so a token ends at the first '|>'.
TOKEN_RE = re.compile(r"<(\d+)f>|(-?\d+)<\|box;([^|]*)\|>|<\|mask;[^|]*\|>")


def _fields(text: str) -> dict[str, str]:
    out = {}
    for part in text.split(";"):
        key, sep, value = part.partition("=")
        if sep:
            out[key.strip()] = value.strip()
    return out


def parse_output(text: str, frame_size: tuple[int, int] | None = None) -> list[dict]:
    """Parse SAM 3.1 special-token output into box records.

    Box corners on the wire are inclusive pixel indices; records come back half-open
    ``[x0, y0, x1, y1]`` (x1 = x2 + 1, so width = x2 - x1 + 1), scaled to ``frame_size`` when the
    service reports a different media size. ``score`` is the box confidence ``c`` or None.
    """
    records = []
    frame = None
    leftover = TOKEN_RE.sub("", text).replace(",", "")
    if leftover.strip():
        # Refusals, prose or a format change must not read as "nothing found".
        raise SamError(f"unrecognised sam-3.1 output: {leftover.strip()[:120]!r}")
    for m in TOKEN_RE.finditer(text):
        if m.group(1) is not None:
            frame = int(m.group(1))
            continue
        if m.group(3) is None:
            continue  # a mask token; boxes are all the evaluator needs today
        if frame is None:
            raise SamError(f"box record before any frame marker: {m.group(0)[:120]}")
        f = _fields(m.group(3))
        try:
            x1, y1, x2, y2 = (_finite(f[k]) for k in ("x1", "y1", "x2", "y2"))
            size = (_finite(f["w"]), _finite(f["h"])) if "w" in f and "h" in f else None
            score = _finite(f["c"]) if "c" in f else None
        except (KeyError, ValueError) as exc:
            raise SamError(f"unreadable box token: {m.group(0)[:120]}") from exc
        if score is not None and not 0.0 <= score <= 1.0:
            raise SamError(f"confidence outside 0..1: {m.group(0)[:120]}")
        box = [x1, y1, x2 + 1, y2 + 1]
        if frame_size and size and size[0] > 0 and size[1] > 0 and size != (float(frame_size[0]), float(frame_size[1])):
            sx, sy = frame_size[0] / size[0], frame_size[1] / size[1]
            box = [box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy]
        records.append({"frame": frame, "id": int(m.group(2)), "box": [round(v, 3) for v in box],
                        "score": score})
    return records


def _finite(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"not a finite number: {value!r}")
    return number


def _from_sse(text: str) -> str:
    parts, completed = [], False
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except json.JSONDecodeError as exc:
            raise SamError(f"unreadable stream event: {data[:120]}") from exc
        if not isinstance(event, dict):
            raise SamError(f"unreadable stream event: {data[:120]}")
        kind = event.get("type", "")
        if kind == "response.output_text.delta":
            parts.append(event.get("delta") or "")
        elif kind == "response.completed":
            completed = True
        elif kind in ("error", "response.failed", "response.incomplete"):
            raise SamError(f"sam-3.1 stream ended with {kind}: {json.dumps(event)[:300]}")
    if not completed:
        raise SamError("sam-3.1 stream ended without response.completed; the output may be partial")
    return "".join(parts)


def _from_response(doc) -> str:
    if not isinstance(doc, dict):
        raise SamError(f"sam-3.1 reply is not a JSON object: {json.dumps(doc)[:120]}")
    if "output_text" not in doc and "output" not in doc and not doc.get("error"):
        raise SamError(f"sam-3.1 reply has no output: {json.dumps(doc)[:200]}")
    if doc.get("error"):
        raise SamError(f"sam-3.1 error: {json.dumps(doc['error'])[:300]}")
    status = doc.get("status")
    if status not in (None, "completed"):
        raise SamError(f"sam-3.1 response status {status!r}; the output may be partial")
    if isinstance(doc.get("output_text"), str):
        return doc["output_text"]
    parts = []
    output = doc.get("output") or []
    if not isinstance(output, list):
        raise SamError("sam-3.1 reply has an unreadable output list")
    for item in output:
        content = item.get("content") if isinstance(item, dict) else None
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "output_text":
                parts.append(str(block.get("text") or ""))
    return "".join(parts)


def output_text(raw: bytes, content_type: str = "") -> str:
    """The model's output text from a Responses API reply, streamed (SSE) or not."""
    text = raw.decode("utf-8", errors="replace")
    if "text/event-stream" in content_type or text.lstrip().startswith(("event:", "data:")):
        return _from_sse(text)
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SamError(f"sam-3.1 reply is not JSON: {text[:120]!r}") from exc
    return _from_response(doc)


def request_body(prompt: str, image_url: str, model: str = MODEL) -> dict:
    """One concept prompt and one image, as the Responses API expects them."""
    return {
        "model": model,
        "stream": False,
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": image_url},
        ]}],
        "metadata": dict(METADATA),
    }


def point_prompt(points: list[tuple[int, int]], size: tuple[int, int]) -> str:
    """The text of an object prompt for one image: one point per object, under the ids 1, 2, ...

    The Model API's grammar (https://dev.meta.ai/docs/sam/segmenting, read November 12, 2026):
    ``<0f>1<|point;x=..;y=..;w=..;h=..|>,2<|point;...|>``. A point asks for the object drawn at
    that pixel. ``w`` and ``h`` are the image's own size, and a point outside it is refused by the
    service with HTTP 400, so it is refused here first and nothing is sent or paid for.
    """
    width, height = size
    if not points:
        raise ValueError("an object prompt needs at least one point")
    parts = []
    for n, (x, y) in enumerate(points, start=1):
        if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, int) or not isinstance(y, int):
            raise ValueError(f"a point is two whole pixel numbers, not {(x, y)!r}")
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError(f"the point {(x, y)} is outside the {width}x{height} image")
        parts.append(f"{n}<|point;x={x};y={y};w={width};h={height}|>")
    return "<0f>" + ",".join(parts)


def box_prompt(boxes: list[tuple[int, int, int, int]], size: tuple[int, int]) -> str:
    """The text of an object prompt for one image: one box per object, under the ids 1, 2, ...

    The same grammar as point_prompt (https://dev.meta.ai/docs/sam/segmenting, read November 12,
    2026): ``<0f>1<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..|>``. A box asks for the object inside
    it. Boxes here are half-open ``(x0, y0, x1, y1)`` like every box in this code; on the wire the
    far corner is the last pixel inside, so x2 = x1 - 1. A box that is empty or reaches outside
    the image is refused here first, and nothing is sent or paid for.
    """
    width, height = size
    if not boxes:
        raise ValueError("an object prompt needs at least one box")
    parts = []
    for n, box in enumerate(boxes, start=1):
        if len(box) != 4 or any(isinstance(v, bool) or not isinstance(v, int) for v in box):
            raise ValueError(f"a box is four whole pixel numbers, not {box!r}")
        x0, y0, x1, y1 = box
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise ValueError(f"the box {tuple(box)} is empty or outside the {width}x{height} image")
        parts.append(f"{n}<|box;x1={x0};y1={y0};x2={x1 - 1};y2={y1 - 1};w={width};h={height}|>")
    return "<0f>" + ",".join(parts)


def png_size(path: Path) -> tuple[int, int]:
    with open(path, "rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise SamError(f"{path} is not a PNG")
    width, height = struct.unpack(">II", head[16:24])
    return int(width), int(height)


def data_url(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")


def sha256_bytes(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------------------------

class MetaSamClient:
    """Calls sam-3.1 once per (frame, prompt). ``transport`` is injectable for tests."""

    def __init__(self, *, model: str = MODEL, base: str | None = None, transport: Transport | None = None,
                 retries: int = 3, timeout: float = 120.0, sleep: Callable[[float], None] = time.sleep):
        self.model = model
        self.base = (base or API_BASE).rstrip("/")
        self._transport = transport or self._http
        self.retries, self.timeout, self._sleep = retries, timeout, sleep
        self.calls = 0
        self.seconds = 0.0  # time spent waiting on the service, summed over calls
        self._lock = threading.Lock()

    def _http(self, body: dict) -> tuple[bytes, str]:
        key = os.environ.get(KEY_ENV, "").strip()
        if not key:
            raise SamError(f"set {KEY_ENV} to a Meta Model API key in your shell or the gitignored .env "
                           "(never commit it, never paste it into chat)", kind="auth")
        if key == os.environ.get("META_API_KEY", "").strip() and not _warned_shared_key.is_set():
            _warned_shared_key.set()
            print(f"warning: {KEY_ENV} is the same key as META_API_KEY, which Muse Code (the fixer) "
                  "receives; use a separate key for SAM so the fixer never holds the verifier's key",
                  file=sys.stderr)
        if usd_cap() is None:
            raise SamError(f"no spend cap for this run: set {CAP_ENV} to the most it may spend on SAM, in US "
                           "dollars. Nothing is sent without one", kind="budget")
        req = urllib.request.Request(
            f"{self.base}/responses", data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read(), resp.headers.get("Content-Type", "")

    def _call(self, body: dict, *, video_frames: int | None = None) -> tuple[bytes, str]:
        """One request with retries. ``video_frames`` set: a video of that many frames (billed per frame)."""
        delay = 2.0
        for attempt in range(self.retries + 1):
            with self._lock:
                self.calls += 1
            with _usage_lock:
                _usage["requests"] += 1
            _reserve(USD_PER_IMAGE if video_frames is None else max(video_frames, MIN_VIDEO_FRAMES) * USD_PER_VIDEO_FRAME)
            started = time.monotonic()
            try:
                reply = self._transport(body)
                with _usage_lock:
                    if video_frames is None:
                        _usage["images"] += 1
                    else:
                        _usage["videoFrames"] += max(video_frames, MIN_VIDEO_FRAMES)
                return reply
            except SamError:
                raise
            except urllib.error.HTTPError as err:
                try:
                    detail = err.read().decode(errors="replace")[:300]
                except (OSError, http.client.HTTPException):
                    detail = ""
                if err.code not in RETRY_STATUS or attempt == self.retries:
                    raise SamError(f"sam-3.1 HTTP {err.code}: {detail}", kind=http_error_kind(err.code, detail),
                                   status=err.code) from err
            except (OSError, http.client.HTTPException) as err:
                # URLError, timeouts, resets and truncated reads (IncompleteRead) all land here.
                if attempt == self.retries:
                    raise SamError(f"sam-3.1 unreachable after {attempt + 1} tries: "
                                   f"{type(err).__name__}: {err}", kind="network") from err
            finally:
                with self._lock:
                    self.seconds += time.monotonic() - started
            self._sleep(delay)
            delay *= 2
        raise SamError("unreachable")  # pragma: no cover

    def segment(self, png: Path, prompt: str) -> list[dict]:
        """Every match for ``prompt`` in one frame: ``[{"box", "score"}]``, best first."""
        size = png_size(png)
        raw, content_type = self._call(request_body(prompt, data_url(png), self.model))
        detections = []
        for record in parse_output(output_text(raw, content_type), frame_size=size):
            if record["score"] is None:
                raise SamError("sam-3.1 returned a box without a confidence although the request asks "
                               "for one (metadata.include_confidence); a missing score is never guessed")
            detections.append({"box": record["box"], "score": record["score"]})
        return sorted(detections, key=lambda d: (-d["score"], d["box"]))


    def segment_at(self, png: Path, points: list[tuple[int, int]]) -> list[dict | None]:
        """What is drawn at each of ``points`` in one frame: ``{"box", "score"}`` or None, in the points' order.

        One request, whatever the number of points. None means the reply held no record under that
        point's id. ``score`` is None when the reply gave a box without a confidence: with a point
        the question is "what is here", and whether the service scores that is not documented, so
        a missing score is reported as missing and never guessed. A reply about an object that was
        not asked for, or two records for one point, is an error and never a pick.
        """
        size = png_size(png)
        return self._objects(png, point_prompt(points, size), len(points), size)

    def segment_in(self, png: Path, boxes: list[tuple[int, int, int, int]]) -> list[dict | None]:
        """What is drawn inside each of ``boxes`` (half-open, frame pixels) in one frame, as segment_at
        gives it: ``{"box", "score"}`` or None, in the boxes' order. One request, counted like any image."""
        size = png_size(png)
        return self._objects(png, box_prompt(boxes, size), len(boxes), size)

    def _objects(self, png: Path, text: str, asked: int, size: tuple[int, int]) -> list[dict | None]:
        raw, content_type = self._call(request_body(text, data_url(png), self.model))
        found: dict[int, dict] = {}
        for record in parse_output(output_text(raw, content_type), frame_size=size):
            n = record["id"]
            if not 1 <= n <= asked:
                raise SamError(f"sam-3.1 answered for object {n}, and {asked} were asked for")
            if n in found:
                raise SamError(f"sam-3.1 gave two boxes for object {n}; one prompt is one object")
            found[n] = {"box": record["box"], "score": record["score"]}
        return [found.get(n) for n in range(1, asked + 1)]


_warned_shared_key = threading.Event()


def vision_backend() -> str:
    name = os.environ.get(BACKEND_ENV, "sam").strip().lower() or "sam"
    if name not in BACKENDS:
        raise SamError(f"unknown {BACKEND_ENV} {name!r} (want {'|'.join(BACKENDS)})")
    return name


def vision_label() -> str:
    try:
        return VISION_LABELS[vision_backend()]
    except SamError:
        return VISION_LABELS["sam"]


def default_client(verdict: bool = False):
    """The frame-vision client for this run: SAM 3.1, Muse Glimmer, both (an object counts only
    when both see it), or Glimmer checked against the engine (agents.engine_check).

    ``verdict=True`` is the verifier's path. Glimmer alone is refused there unless
    EXPECTRAIL_GLIMMER_ALONE=1: the fixer controls the candidate's pixels, and a vision-language
    model can be talked into a pass by text drawn into the game. Use ``both``, or
    ``glimmer-engine`` to run without SAM, for verdicts.
    """
    backend = vision_backend()
    if backend == "sam":
        return MetaSamClient()
    if backend in ("local-http", "byo-vlm", "byo-vlm-engine"):
        return _byo_client(backend, verdict)
    from agents.glimmer_client import BothClient, EngineCheckedGlimmer, GlimmerClient

    if backend == "both":
        return BothClient()
    if backend == "glimmer-engine":
        return EngineCheckedGlimmer()
    alone = os.environ.get(GLIMMER_ALONE_ENV, "").strip().lower() in ("1", "true", "yes")
    if verdict and not alone:
        raise SamError("Glimmer alone does not decide a verdict: the fixer controls the frames, and text drawn "
                       f"into the game could talk a vision-language model into a pass. Use {BACKEND_ENV}=both "
                       f"or glimmer-engine, "
                       f"or set {GLIMMER_ALONE_ENV}=1 to measure Glimmer on known fixtures")
    return GlimmerClient()


def _byo_client(backend: str, verdict: bool):
    """local-http (a detector), byo-vlm (any VLM), byo-vlm-engine (a VLM checked against the engine).

    A VLM alone follows Glimmer's rule: refused for a verdict unless EXPECTRAIL_BYO_VLM_ALONE=1.
    """
    from agents import byo_vision

    try:
        if backend == "local-http":
            return byo_vision.LocalHTTPDetectorClient()
        if backend == "byo-vlm-engine":
            return byo_vision.EngineCheckedBYOVLM()
        alone = os.environ.get(BYO_VLM_ALONE_ENV, "").strip().lower() in ("1", "true", "yes")
        if verdict and not alone:
            raise SamError("a vision-language model alone does not decide a verdict: the fixer controls the "
                           "frames, and text drawn into the game could talk it into a pass. Use "
                           f"{BACKEND_ENV}=byo-vlm-engine or local-http, or set {BYO_VLM_ALONE_ENV}=1 to measure "
                           "it on known fixtures")
        return byo_vision.BYOVLMObserverClient()
    except (RuntimeError, ValueError) as exc:
        if isinstance(exc, SamError):
            raise
        raise SamError(f"{BACKEND_ENV}={backend}: {exc}") from exc


def first_sample(indices: list[int], rate: int, trace: dict | None) -> list[int]:
    """The frames looked at first: every ``rate``-th frame, or with EXPECTRAIL_KEYFRAMES_ONLY=1 and a
    trace, the frames where the engine says something happened (plus a coarser stride and both ends).

    Only the first look changes: refinement and the every-frame confirmation of a pass still run, so
    choosing keyframes can never turn a failure into a pass.
    """
    keyframes = os.environ.get(KEYFRAMES_ENV, "").strip().lower() in ("1", "true", "yes")
    if not keyframes or rate <= 1 or not indices or not (trace or {}).get("rows"):
        return sample(indices, rate)
    from agents.byo_vision import select_event_keyframes, trace_keyframe_rows

    picked = set(select_event_keyframes(trace_keyframe_rows(trace), indices[-1] + 1, base_stride=rate * 2))
    chosen = sorted(picked.intersection(indices) | {indices[0], indices[-1]})
    return chosen


# ---------------------------------------------------------------------------------------------
# The cache
# ---------------------------------------------------------------------------------------------

def default_cache_dir() -> Path | None:
    """Verifier-side state, outside the repo so the fixer's worktree never contains it.

    Under bwrap the fixer gets a fresh tmpfs HOME, so it cannot reach this either. With no OS
    sandbox (kind ``none``) nothing stops a host process from writing here; see docs/sam.md.
    """
    raw = os.environ.get(CACHE_ENV)
    if raw is not None:
        return None if raw.strip().lower() in ("", "off", "0", "none") else Path(raw).expanduser()
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "expectrail" / "sam"


class Cache:
    def __init__(self, root: Path | None):
        self.root = Path(root) if root else None
        self.hits = 0
        self._warned = False
        self._lock = threading.Lock()

    @staticmethod
    def key(frame_sha: str, prompt: str, model: str, base: str = "") -> str:
        """Which frame, what was asked, of which model at which endpoint, with which settings."""
        parts = [REQUEST_VERSION, base, model, prompt, frame_sha, METADATA]
        return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> list[dict] | None:
        if self.root is None:
            return None
        try:
            doc = json.loads(self._path(key).read_text(encoding="utf-8"))
            detections = doc["detections"]
            if not isinstance(detections, list) or not all(_valid_detection(d) for d in detections):
                return None
        except (OSError, ValueError, KeyError, TypeError):
            return None
        with self._lock:
            self.hits += 1
        return detections

    def put(self, key: str, detections: list[dict], meta: dict) -> None:
        """Best effort: a cache that cannot be written only costs a repeat request later."""
        if self.root is None:
            return
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"detections": detections, **meta}, fh, allow_nan=False)
            os.replace(tmp, path)
        except (OSError, ValueError) as exc:
            with self._lock:
                first, self._warned = not self._warned, True
            if first:
                print(f"warning: sam cache not written, continuing without it ({type(exc).__name__}: {exc})",
                      file=sys.stderr)


def _valid_detection(d) -> bool:
    if not isinstance(d, dict) or not isinstance(d.get("box"), list) or len(d["box"]) != 4:
        return False
    values = [*d["box"], d.get("score")]
    return (all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)
            and 0.0 <= d["score"] <= 1.0)


# ---------------------------------------------------------------------------------------------
# Which frames to look at
# ---------------------------------------------------------------------------------------------

def frame_files(frames_dir: Path) -> dict[int, Path]:
    """Movie Maker frames: f00000000.png, f00000001.png, ... keyed by frame number."""
    frames = {}
    for path in Path(frames_dir).glob("f*.png"):
        digits = path.stem[1:]
        if digits.isdigit():
            frames[int(digits)] = path
    return dict(sorted(frames.items()))


def window(available: list[int], spec: dict | None) -> list[int]:
    w = (spec or {}).get("window", {})
    lo, hi = w.get("fromFrame", 0), w.get("toFrame")
    return [i for i in available if i >= lo and (hi is None or i <= hi)]


def sample(indices: list[int], every: int) -> list[int]:
    """Every ``every``-th frame from the start of the window, plus its last frame."""
    if every <= 1 or not indices:
        return list(indices)
    start = indices[0]
    picked = [i for i in indices if (i - start) % every == 0]
    if indices[-1] not in picked:
        picked.append(indices[-1])
    return picked


def sampling_plan(spec: dict | None, every: int) -> int:
    """The sample rate this spec can safely use.

    never-crosses and inside-region fail on any failing frame, so sampling can only miss a
    failure. ``reaches`` can sample (a sampled frame that reaches is a real pass; a fail is
    re-checked on every frame). ``visible`` counts frames against a fraction, so it looks at
    every frame unless the fraction is 1.0.
    """
    if not spec:
        return every
    # Explicit count/share obligations must not be defeated by an early sampled witness.
    if any(key in spec.get("coverage", {}) for key in ("minFrames", "minFraction")):
        return 1
    assertion = spec.get("assertion", {})
    kind = assertion.get("type")
    if kind in SAMPLE_SAFE or kind == "reaches":
        return every
    if kind == "visible" and float(assertion.get("minFraction", 1.0)) >= 1.0:
        return every
    return 1


def refine_targets(indices: list[int], looked: set[int], verdict: dict, passed: set[int],
                   kind: str | None = None) -> list[int]:
    """Frames to add after a sampled verdict.

    A fail with a first failing frame: every unseen frame between the last sample that passed on
    its own (``passed``) and that frame, so the first failing frame is exact over that stretch. A
    sample where the object was missing or the check did not apply is not a pass, so the stretch
    reaches back past it. ``reaches`` that has not passed, or a fail without a first frame: every
    unseen frame, since the moment may sit between two samples.
    """
    result = verdict.get("result")
    unseen = [i for i in indices if i not in looked]
    if kind == "reaches":
        return unseen if result != "pass" else []
    if result != "fail":
        return []
    first = verdict.get("firstFrame")
    if first is None:
        return unseen
    before = [i for i in passed if i < first]
    previous = max(before) if before else indices[0] - 1
    return [i for i in unseen if previous < i < first]


def passing_frames(spec: dict, doc: dict) -> set[int]:
    """Frames with no assertion violation, for sampling only; not covered final verdicts."""
    return {frame["frame"] for frame in doc["frames"]
            if _assertion_verdict(spec, dict(doc, frames=[frame]))["result"] == "pass"}


# ---------------------------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------------------------

def _prompts(spec: dict | None, prompts: dict | None, engine_names: frozenset = frozenset()) -> dict[str, str]:
    """What SAM is asked to find: the spec's objects minus those the engine supplies."""
    if spec and spec.get("objects"):
        return {name: obj["prompt"] for name, obj in spec["objects"].items() if name not in engine_names}
    return {k: v for k, v in (prompts or DEFAULT_PROMPTS).items() if k not in engine_names}


def observe(frames: dict[int, Path], indices: list[int], prompts: dict[str, str], client: MetaSamClient,
            cache: Cache, workers: int = DEFAULT_WORKERS) -> dict[int, dict]:
    """{frame: {object name: detections}} for the given frames, from the cache or SAM."""
    shas = {i: sha256_bytes(frames[i]) for i in indices}
    jobs = [(i, name) for i in indices for name in prompts]

    def run(job):
        i, name = job
        key = Cache.key(shas[i], prompts[name], client.model, client.base + getattr(client, "cache_tag", ""))
        detections = cache.get(key)
        if detections is None:
            detections = client.segment(frames[i], prompts[name])
            cache.put(key, detections, {"frameSha256": shas[i], "prompt": prompts[name], "model": client.model,
                                        "base": client.base})
        return i, name, detections

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(run, job) for job in jobs]
        done, pending = wait(futures, return_when=FIRST_EXCEPTION)
        failed = [f for f in futures if f in done and f.exception() is not None]
        if failed:
            for f in pending:
                f.cancel()  # stop spending requests once one has failed
            raise failed[0].exception()
        results = [f.result() for f in futures]
    observed: dict[int, dict] = {i: {} for i in indices}
    for i, name, detections in results:
        observed[i][name] = detections
    return observed


def _document(observed, prompts, model, replay_sha256, captured, in_window, every, refined,
              confirmed: int = 0, engine_objects: dict | None = None, provider: str = "meta-model-api",
              engine_check: dict | None = None) -> dict:
    engine_objects = engine_objects or {}
    engine_names = sorted({name for objs in engine_objects.values() for name in objs})
    model_doc = {"name": model, "provider": provider, "prompts": dict(prompts)}
    if engine_check is not None:
        # The vision boxes below are only those that agreed with the engine (agents.engine_check).
        model_doc["engineCheck"] = engine_check
    if engine_names:
        # These objects come from the game engine, not from SAM: the evaluator compares SAM's view
        # of the prompted objects against them (e.g. the robot SAM sees against the level's ground).
        model_doc["engineObjects"] = engine_names
    return {
        "format": "expectrail.observations/v0",
        "replay": {"sha256": replay_sha256},
        "model": model_doc,
        "frames": [{"frame": i, "objects": {**{name: observed[i][name] for name in prompts},
                                            **{name: list(engine_objects.get(i, {}).get(name, []))
                                               for name in engine_names}}}
                   for i in sorted(observed)],
        # Deterministic given the same detections, so the document digest is stable run to run.
        "analysis": {"framesCaptured": captured, "framesInWindow": in_window,
                     "framesAnalyzed": len(observed), "every": every,
                     "refined": ({"frames": len(refined), "from": min(refined), "to": max(refined)}
                                 if refined else None),
                     "confirmed": confirmed},
    }


def from_replay(
    trace: dict | None = None,
    replay_sha256: str = "0" * 64,
    fps: int = 60,
    physics_tps: int | None = None,
    frames_dir: str | Path | None = None,
    *,
    spec: dict | None = None,
    prompts: dict[str, str] | None = None,
    every: int | None = None,
    refine: bool = True,
    confirm: bool | None = None,
    engine_objects: dict[int, dict] | None = None,
    client: MetaSamClient | None = None,
    cache: Cache | None = None,
    workers: int | None = None,
    stats: dict | None = None,
    keep: Callable[[dict[int, dict]], dict[int, dict]] | None = None,
) -> dict:
    """expectrail.observations/v0 for one replay, from SAM 3.1. Matches the seam's signature.

    ``trace``, ``fps`` and ``physics_tps`` are accepted for the seam and unused: SAM looks at
    pixels only. ``spec`` supplies the prompts, the frame window and the assertion that decides
    whether sampling is safe and where to refine. ``engine_objects`` ({frame: {name: boxes}})
    supplies objects SAM cannot see, such as the level's ground line in frame pixels; SAM is not
    asked for those. ``keep`` ({frame: {name: detections}} -> the same) filters SAM's answer before
    anything is decided from it, sampling and refinement included: the web adapter keeps only the
    boxes that agree with where the page drew the element.

    Every failure comes out as SamError, so the verifier can turn it into needs-review instead of
    crashing; nothing here can fail into a pass.
    """
    try:
        if confirm is None:
            confirm = os.environ.get(CONFIRM_ENV, "1").strip().lower() not in ("0", "off", "false", "no")
        return _from_replay(frames_dir, replay_sha256, spec=spec, prompts=prompts, every=every, refine=refine,
                            confirm=confirm, engine_objects=engine_objects, client=client, cache=cache,
                            workers=workers, stats=stats, trace=trace, fps=fps, keep=keep)
    except SamError:
        raise
    except Exception as exc:  # noqa: BLE001 - any surprise is needs-review, never a crash or a pass
        raise SamError(f"unexpected {type(exc).__name__}: {exc}") from exc


def _from_replay(frames_dir, replay_sha256, *, spec, prompts, every, refine, confirm, engine_objects, client,
                 cache, workers, stats, trace=None, fps=60, keep=None) -> dict:
    if frames_dir is None or not Path(frames_dir).is_dir():
        raise SamError("the sam provider needs the replay's captured frames (frames_dir)")
    frames = frame_files(Path(frames_dir))
    if not frames:
        raise SamError(f"no frames in {frames_dir}")
    client = client or default_client(verdict=True)
    cache = cache if cache is not None else Cache(default_cache_dir())
    workers = workers or int(os.environ.get(WORKERS_ENV, DEFAULT_WORKERS))
    rate = every or int(os.environ.get(EVERY_ENV, DEFAULT_EVERY))
    rate = sampling_plan(spec, max(1, rate))
    engine_objects = engine_objects or {}
    names = _prompts(spec, prompts, frozenset(n for objs in engine_objects.values() for n in objs))
    if not names:
        raise SamError("nothing for SAM to look for: every object of the spec comes from the engine")

    indices = window(list(frames), spec)
    if not indices:
        raise SamError("no captured frame falls inside the spec's window")
    check = None
    if getattr(client, "engine_checked", False):
        from agents.engine_check import check_for_trace

        check = check_for_trace(trace, list(frames), fps=fps or 60)

    def look(chosen):
        got = observe(frames, chosen, names, client, cache, workers)
        got = check(got) if check is not None else got
        return keep(got) if keep is not None else got

    observed = look(first_sample(indices, rate, trace))

    def doc_of(refined_frames, confirmed_count=0):
        return _document(observed, names, client.model, replay_sha256, len(frames), len(indices), rate,
                         refined_frames, confirmed_count, engine_objects,
                         getattr(client, "provider", "meta-model-api"),
                         check.summary() if check is not None else None)

    refined: list[int] = []
    if refine and spec and rate > 1:
        doc = doc_of([])
        kind = spec.get("assertion", {}).get("type")
        refined = refine_targets(indices, set(observed), _assertion_verdict(spec, doc), passing_frames(spec, doc), kind)
        if refined:
            observed.update(look(refined))
    confirmed: list[int] = []
    # "reaches" passes on the frame that reaches the goal, so more frames cannot change its pass.
    if confirm and spec and rate > 1 and spec.get("assertion", {}).get("type") != "reaches":
        doc = doc_of(refined)
        if _assertion_verdict(spec, doc)["result"] == "pass":
            # Sampling finds failures cheaply; a pass has to hold on every frame.
            confirmed = [i for i in indices if i not in observed]
            if confirmed:
                observed.update(look(confirmed))
    if stats is not None:
        stats.update(calls=client.calls, cacheHits=cache.hits, framesAnalyzed=len(observed),
                     framesCaptured=len(frames), every=rate, refined=len(refined), confirmed=len(confirmed))
    return doc_of(refined, len(confirmed))


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    from agents.keys import load_dotenv
    from expectrail.contracts import digest, load, validate

    p = argparse.ArgumentParser(description="SAM 3.1 observations for one replay, then the verdict.")
    p.add_argument("--run", type=Path, required=True, help="a harness run dir with frames/ and replay.json")
    p.add_argument("--spec", type=Path, required=True)
    p.add_argument("--every", type=int, help=f"look at every Nth frame (default {DEFAULT_EVERY})")
    p.add_argument("--no-refine", action="store_true")
    p.add_argument("--no-confirm", action="store_true", help="let a pass rest on the sample (probing only)")
    p.add_argument("--out", type=Path, help="default: <run>/observations-sam.json")
    args = p.parse_args(argv)
    load_dotenv()

    spec = load(args.spec, "test-spec")
    replay = args.run / "replay.json"
    stats: dict = {}
    try:
        doc = from_replay(
            replay_sha256=sha256_bytes(replay) if replay.is_file() else "0" * 64,
            frames_dir=args.run / "frames", spec=spec, every=args.every, refine=not args.no_refine,
            confirm=False if args.no_confirm else None,
            stats=stats)
    except SamError as exc:
        print(f"needs-review: {exc}", file=sys.stderr)
        return 2
    validate(doc, "observations")
    out = args.out or args.run / "observations-sam.json"
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    verdict = evaluate(spec, doc)
    print(f"observations: {out} ({digest(doc)[:12]})")
    print(f"frames analyzed: {stats['framesAnalyzed']} of {stats['framesCaptured']} (every {stats['every']}, "
          f"{stats['refined']} refined, {stats['confirmed']} confirmed); API calls {stats['calls']}, "
          f"cache hits {stats['cacheHits']}")
    print(f"{verdict['result']}: {verdict['reason']}")
    return {"pass": 0, "fail": 1, "needs-review": 2}[verdict["result"]]


if __name__ == "__main__":
    sys.exit(main())
