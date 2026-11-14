"""Muse Glimmer (open weights) as Expectrail's frame-vision backend, behind SAM's client interface.

    export FIREWORKS_API_KEY=...                     # or EXPECTRAIL_GLIMMER_API_KEY; never commit it
    # verdicts: an object counts only where SAM and Glimmer both see it (needs MODEL_API_KEY too)
    EXPECTRAIL_VISION_BACKEND=both EXPECTRAIL_OBS_PROVIDER=sam python3 -m agents.gate1 ...
    # measuring Glimmer alone on known runs
    EXPECTRAIL_VISION_BACKEND=glimmer python3 -m agents.sam_probe --spec specs/player-always-visible.json \\
        --runs runs/seeded/*/

The verifier's vision checks (the visibility specs and the hybrid ground check) ask one question per
frame and object: where is "<noun phrase>" drawn? ``agents.sam_observations`` asks SAM 3.1 through
the Meta Model API. With ``EXPECTRAIL_VISION_BACKEND=glimmer`` the same question goes to Muse
Glimmer 30B (Apache 2.0) on any OpenAI-compatible endpoint: a Fireworks on-demand deployment by
default (``EXPECTRAIL_GLIMMER_MODEL=accounts/<account>/deployments/<id>``; Glimmer left Fireworks
serverless on Sep 25, 2026), or our own vLLM/SGLang server
(``EXPECTRAIL_GLIMMER_API_BASE=http://<host>:8000/v1``,
``EXPECTRAIL_GLIMMER_MODEL=meta-models/Muse-Glimmer-30B``). Everything around the call stays the
same: sampling, refining to the first bad frame, confirming every frame before a pass, the cache,
and needs-review on any failure.

Glimmer never decides an accept on its own. It reads images the way a language model reads text,
and the fixer controls the candidate's pixels: a fix could draw text into the game that talks a
vision-language model into "the robot is there". SAM 3.1 is a segmenter and cannot be talked to. So
the verifier uses ``EXPECTRAIL_VISION_BACKEND=both``: SAM's boxes count only on frames where Glimmer
also sees the object (``BothClient``), which can only make the gate stricter than SAM alone.
``glimmer`` alone is for measuring Glimmer (``agents.sam_probe``, or the verifier with
``EXPECTRAIL_GLIMMER_ALONE=1`` on known fixtures); without that flag the verifier refuses it and every
vision check is needs-review.

What differs from SAM, and the code is honest about:

- Glimmer is a vision-language model, not a segmenter. It answers in JSON with boxes it reads off
  the image; it has no mask and no calibrated score. ``confidence`` is Glimmer's own 0-1 rating,
  recorded as the detection score so the evaluator's threshold applies, and labelled
  self-reported in the observations document (``model.provider``).
- Coordinates: the prompt asks for pixels of the image it was sent. Some VLMs answer on a 0-1000
  grid instead; set ``EXPECTRAIL_GLIMMER_COORDS=norm1000`` (or ``norm1``) if the probe shows that.
  A box far outside the image is refused (needs-review), never clipped into a pass.
- Positions stay in code: Glimmer is only ever asked for the spec's noun phrase, never "is it
  below the ground"; the evaluator decides that from the boxes, as it does for SAM.
"""
from __future__ import annotations

import http.client
import json
import math
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from agents.sam_observations import MetaSamClient, SamError, data_url, png_size

API_BASE = os.environ.get("EXPECTRAIL_GLIMMER_API_BASE", "https://api.fireworks.ai/inference/v1")
# Fireworks retired Glimmer from serverless on Sep 25, 2026: it runs on an on-demand deployment,
# addressed as accounts/<account>/deployments/<id>. Set EXPECTRAIL_GLIMMER_MODEL to that. The base
# model id below is what the deployment is created from, and what a self-hosted server may serve.
BASE_MODEL = "accounts/fireworks/models/muse-glimmer-30b"
MODEL = os.environ.get("EXPECTRAIL_GLIMMER_MODEL", BASE_MODEL)
KEY_ENVS = ("EXPECTRAIL_GLIMMER_API_KEY", "FIREWORKS_API_KEY")
COORDS_ENV = "EXPECTRAIL_GLIMMER_COORDS"
COORDS = ("pixels", "norm1000", "norm1")
# Glimmer answers on a 0-1000 grid over the image, whatever the prompt asks: measured against the
# engine's robot position on Oct 29 (run 40936605897), its x came out 1.58-1.60 times smaller than
# the frame's pixels and its y 0.95-0.99 times, i.e. 1600/1000 and 960/1000 on a 1600x960 frame.
DEFAULT_COORDS = "norm1000"
# Bump when the prompt or the parsing changes, so cached answers to an older question are not reused.
REQUEST_VERSION = "glimmer-4"
# Glimmer reasons before it answers, and its reasoning counts against max_tokens: at 2048 a frame with a
# dozen coins was cut off mid-JSON (Oct 29). Room for the reasoning plus up to MAX_OBJECTS boxes.
MAX_TOKENS = int(os.environ.get("EXPECTRAIL_GLIMMER_MAX_TOKENS", "8192"))
MAX_OBJECTS = 30
# Optional: e.g. "low", sent as reasoning_effort, for servers that accept it. Unset sends nothing.
REASONING_ENV = "EXPECTRAIL_GLIMMER_REASONING"
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
# A corner more than 2% of the frame outside the image is a format error (another grid, or not a box).
OUT_OF_FRAME = 0.02
SCHEMA_REFUSAL = ("response_format", "json_schema", "schema", "structured")

SYSTEM_PROMPT = (
    "You are the eyes of an automated test for a 2D platformer game. You look at one captured frame "
    "and report where a named thing is drawn in it. Report only what is visibly drawn in this image: "
    "something hidden behind scenery, off screen, or not drawn at all is not visible. Never guess."
)

BOX_SCHEMA = {
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
                    "box": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        }
    },
}

Transport = Callable[[dict], "tuple[bytes, str]"]


GRIDS = {
    "pixels": "Box corners are pixels of this image",
    "norm1000": "Box corners are on a 0 to 1000 grid over the whole image (x 0 is the left edge and 1000 the "
                "right edge, y 0 the top edge and 1000 the bottom edge, whatever the image's size)",
    "norm1": "Box corners are fractions of the image from 0 to 1 (x 0 is the left edge and 1 the right edge, "
             "y 0 the top edge and 1 the bottom edge)",
}


def user_prompt(prompt: str, size: tuple[int, int], coords: str = "pixels") -> str:
    w, h = size
    # The image's pixel size only when asking for pixels: told "1600 by 960 pixels" and asked for the
    # 0-1000 grid, Glimmer sometimes rescaled its own grid answer once more (x / 1.6; run 40937863760).
    size_line = f"This image is {w} by {h} pixels. " if coords == "pixels" else ""
    return (
        f'{size_line}Find every visible "{prompt}". '
        'Answer with JSON only: {"objects": [{"box": [x0, y0, x1, y1], "confidence": c}]}, one entry per '
        f"separate {prompt}, at most {MAX_OBJECTS} entries. {GRIDS[coords]}: x0, y0 is the top-left corner and x1, "
        "y1 the bottom-right, with the origin at the top-left and y growing downward. confidence is how "
        'sure you are, from 0 to 1. If none is visible, answer {"objects": []}.'
    )


def request_body(prompt: str, image_url: str, size: tuple[int, int], model: str = MODEL,
                 structured: bool = True, coords: str = "pixels") -> dict:
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": user_prompt(prompt, size, coords)},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]},
        ],
    }
    reasoning = os.environ.get(REASONING_ENV, "").strip()
    if reasoning:
        body["reasoning_effort"] = reasoning
    if structured:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "expectrail_boxes", "schema": BOX_SCHEMA}}
    else:
        body["response_format"] = {"type": "json_object"}
    return body


def answer_text(raw: bytes) -> str:
    try:
        doc = json.loads(raw)
        choice = doc["choices"][0]
        content = choice["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError, RecursionError) as exc:
        raise SamError(f"glimmer reply is not a chat completion: {raw[:160]!r}") from exc
    if isinstance(choice, dict) and choice.get("finish_reason") == "length":
        raise SamError("glimmer's answer was cut off at max_tokens (finish_reason length); raise "
                       "EXPECTRAIL_GLIMMER_MAX_TOKENS or set EXPECTRAIL_GLIMMER_REASONING=low")
    if isinstance(content, list):  # content parts
        texts = [p.get("text", "") for p in content if isinstance(p, dict)]
        if not all(isinstance(t, str) for t in texts):
            raise SamError("glimmer reply has a content part whose text is not a string")
        content = "".join(texts)
    if not isinstance(content, str):
        raise SamError("glimmer reply has no text content")
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text.lower().startswith("json") else text
    return text.strip()


def _num(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SamError(f"glimmer box value is not a number: {str(value)[:40]!r}")
    try:
        out = float(value)
    except OverflowError as exc:
        raise SamError("glimmer box value is too large to be a pixel") from exc
    if not math.isfinite(out):
        raise SamError(f"glimmer box value is not finite: {out!r}")
    return out


def parse_boxes(text: str, size: tuple[int, int], coords: str = "pixels") -> list[dict]:
    """Glimmer's JSON answer -> [{"box": [x0, y0, x1, y1], "score": c}] in pixels of ``size``.

    Prose, a missing confidence, corners in the wrong order, a box outside the frame or any other
    surprise raises SamError, which the verifier turns into needs-review. Nothing is repaired into a
    box: an [x, y, w, h] answer or one on another grid is refused, not reinterpreted.
    """
    if coords not in COORDS:
        raise SamError(f"{COORDS_ENV} must be one of {', '.join(COORDS)}")
    try:
        return _parse_boxes(text, size, coords)
    except SamError:
        raise
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise SamError(f"unreadable glimmer answer: {type(exc).__name__}") from exc


def _parse_boxes(text: str, size: tuple[int, int], coords: str) -> list[dict]:
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise SamError(f"glimmer did not answer in JSON: {text[:120]!r}") from exc
    objects = doc.get("objects") if isinstance(doc, dict) else None
    if not isinstance(objects, list):
        raise SamError(f"glimmer answer has no objects list: {text[:120]!r}")
    w, h = float(size[0]), float(size[1])
    scale = {"pixels": (1.0, 1.0), "norm1000": (w / 1000.0, h / 1000.0), "norm1": (w, h)}[coords]
    out = []
    for obj in objects:
        if not isinstance(obj, dict) or not isinstance(obj.get("box"), list) or len(obj["box"]) != 4:
            raise SamError(f"unreadable glimmer box: {str(obj)[:120]}")
        if "confidence" not in obj:
            raise SamError("glimmer returned a box without a confidence; a missing score is never guessed")
        score = _num(obj["confidence"])
        if not 0.0 <= score <= 1.0:
            raise SamError(f"glimmer confidence outside 0..1: {score}")
        x0, y0, x1, y1 = (_num(v) for v in obj["box"])
        x0, x1 = x0 * scale[0], x1 * scale[0]
        y0, y1 = y0 * scale[1], y1 * scale[1]
        if x1 <= x0 or y1 <= y0:
            raise SamError(f"glimmer box {str(obj['box'])[:80]} is not [x0, y0, x1, y1] with x0 < x1 and y0 < y1")
        if x0 < -OUT_OF_FRAME * w or x1 > (1 + OUT_OF_FRAME) * w or \
                y0 < -OUT_OF_FRAME * h or y1 > (1 + OUT_OF_FRAME) * h:
            raise SamError(f"glimmer box {str(obj['box'])[:80]} is outside the {int(w)}x{int(h)} frame; "
                           f"check {COORDS_ENV} (now {coords})")
        x0, x1 = max(0.0, x0), min(w, x1)
        y0, y1 = max(0.0, y0), min(h, y1)
        if x1 - x0 < 1 or y1 - y0 < 1:
            raise SamError(f"glimmer box {str(obj['box'])[:80]} has no area inside the frame")
        # The score is kept as given: rounding could lift 0.49996 over the evaluator's 0.5.
        out.append({"box": [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)], "score": score})
    return sorted(out, key=lambda d: (-d["score"], d["box"]))


# What kind of failure an observations error was, in fixed words only. The held-out verify run
# reports these instead of the error text, which can quote Glimmer's answer about a held-out frame.
_ERROR_KINDS: tuple[tuple[str, str], ...] = (
    ("cut off at max_tokens", "answer cut off at max_tokens"),
    ("outside the", "box outside the frame (strict parse)"),
    ("has no area inside", "box with no area in the frame (strict parse)"),
    ("is not [x0, y0, x1, y1]", "inverted or malformed box (strict parse)"),
    ("box value", "box value not a usable number (strict parse)"),
    ("unreadable glimmer box", "inverted or malformed box (strict parse)"),
    ("without a confidence", "box without a confidence (strict parse)"),
    ("glimmer confidence outside", "confidence outside 0..1 (strict parse)"),
    ("did not answer in JSON", "answer not JSON"),
    ("no objects list", "answer not JSON"),
    ("unreadable glimmer answer", "answer not JSON"),
    ("not a chat completion", "reply not a chat completion"),
    ("no text content", "reply not a chat completion"),
    ("content part", "reply not a chat completion"),
    ("glimmer unreachable", "glimmer unreachable after retries (timeouts or resets)"),
    ("did not wake", "glimmer deployment did not wake"),
    ("no captured frames", "no captured frames"),
)


def error_kind(text: str) -> str:
    """Classify an observations error (Glimmer's or SAM's) without repeating any of its content."""
    flat = " ".join(text.split())
    if "glimmer HTTP " in flat:
        code = flat.split("glimmer HTTP ", 1)[1][:3]
        return f"glimmer HTTP {code}" if code.isdigit() else "glimmer HTTP error"
    for needle, kind in _ERROR_KINDS:
        if needle in flat:
            return kind
    if "sam-3.1" in flat:
        return "SAM error"
    return "other error"


def warm(*, base: str | None = None, model: str | None = None, key: str | None = None,
         timeout_s: float = 900.0, every_s: float = 15.0, opener=urllib.request.urlopen,
         sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> float:
    """Wake a scaled-to-zero deployment before the frames go out; returns seconds waited.

    An on-demand deployment at zero replicas answers 503 (or 429) while it starts, and after a long
    idle it has also answered 404 "not deployed" until its replica came up (Oct 29, run 40986446779,
    while Fireworks' API reported it READY with replicas 0-1). Keep asking with a tiny text-only
    request until it answers 200. For an accounts/<account>/deployments/<id> model a 404 is retried
    too (the workflows read the deployment through the control plane first, so a wrong id has
    already failed there); for any other model, and for a 401 or 403, it stops at once.
    """
    base = (base or API_BASE).rstrip("/")
    model = model or MODEL
    key = key or api_key()
    if not key:
        raise SamError(f"set one of {', '.join(KEY_ENVS)} for {base}")
    live = opener is urllib.request.urlopen
    body = json.dumps({"model": model, "max_tokens": 4, "temperature": 0,
                       "messages": [{"role": "user", "content": "Reply with OK."}]}).encode()
    started = clock()
    last = ""
    while True:
        from expectrail.spend import BudgetStop, hold
        try:
            hold("glimmer", live=live)
        except BudgetStop as exc:
            raise SamError(str(exc), kind="budget") from exc
        req = urllib.request.Request(f"{base}/chat/completions", data=body, method="POST",
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with opener(req, timeout=120) as resp:
                resp.read()
                return round(clock() - started, 1)
        except urllib.error.HTTPError as err:
            try:
                detail = err.read().decode(errors="replace")[:300]
            except (OSError, http.client.HTTPException):
                detail = ""
            starting = err.code == 404 and "/deployments/" in model
            if err.code not in RETRY_STATUS and not starting:
                hint = {
                    404: (" (the deployment is not serving: after a suspension Fireworks sets its replicas to "
                          "0-0, which python -m agents.fireworks_deployment --restore puts back; or the model id "
                          f"is not an on-demand deployment of {BASE_MODEL} this key can reach)"),
                    412: " (the Fireworks account is suspended, usually out of credits: add credits, then run again)",
                }.get(err.code, "")
                raise SamError(f"glimmer HTTP {err.code}: {detail}{hint}") from err
            last = f"HTTP {err.code}"
        except (OSError, http.client.HTTPException) as err:
            last = f"{type(err).__name__}: {err}"
        if clock() - started > timeout_s:
            raise SamError(f"glimmer deployment did not wake within {int(timeout_s)} s (last: {last})")
        sleep(every_s)


def api_key() -> str | None:
    for name in KEY_ENVS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


class GlimmerClient(MetaSamClient):
    """Muse Glimmer behind ``segment(png, prompt)``, so agents.sam_observations runs unchanged."""

    def __init__(self, *, model: str | None = None, base: str | None = None, key: str | None = None,
                 transport: Transport | None = None, coords: str | None = None, retries: int = 3,
                 timeout: float = 180.0, sleep: Callable[[float], None] = time.sleep):
        super().__init__(model=model or MODEL, base=base or API_BASE, transport=transport, retries=retries,
                         timeout=timeout, sleep=sleep)
        self._key = key
        self.coords = (coords or os.environ.get(COORDS_ENV, DEFAULT_COORDS)).strip().lower()
        if self.coords not in COORDS:
            raise SamError(f"{COORDS_ENV} must be one of {', '.join(COORDS)}, not {self.coords!r}")
        host = urllib.parse.urlparse(self.base).hostname or self.base
        # What the observations document records as the provider (see _document).
        self.provider = f"open-weights glimmer at {host}, self-reported confidence"
        # Part of the cache key: a changed prompt or coordinate reading never reuses old answers.
        self.cache_tag = f"#{REQUEST_VERSION}#{self.coords}"
        self._structured = True
        self._flag = threading.Lock()

    def _http(self, body: dict) -> tuple[bytes, str]:
        key = self._key or api_key()
        if not key:
            raise SamError(f"set one of {', '.join(KEY_ENVS)} for {self.base} (never commit it)")
        if key == os.environ.get("META_API_KEY", "").strip():
            raise SamError("the Glimmer key is the same as META_API_KEY, which Muse Code (the fixer) "
                           "receives; the verifier's vision key must be its own")
        from expectrail.spend import BudgetStop, require_cap
        try:
            require_cap("glimmer")
        except BudgetStop as exc:
            raise SamError(str(exc), kind="budget") from exc
        req = urllib.request.Request(
            f"{self.base}/chat/completions", data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read(), resp.headers.get("Content-Type", "")

    def _call(self, body: dict) -> tuple[bytes, str]:
        delay = 2.0
        live = self._transport is self._http
        for attempt in range(self.retries + 1):
            from expectrail.spend import BudgetStop, hold
            try:
                hold("glimmer", live=live)
            except BudgetStop as exc:
                raise SamError(str(exc), kind="budget") from exc
            with self._lock:
                self.calls += 1
            started = time.monotonic()
            try:
                return self._transport(body)
            except SamError:
                raise
            except urllib.error.HTTPError as err:
                try:
                    detail = err.read().decode(errors="replace")[:300]
                except (OSError, http.client.HTTPException):
                    detail = ""
                if err.code not in RETRY_STATUS or attempt == self.retries:
                    raise SamError(f"glimmer HTTP {err.code}: {detail}") from err
            except (OSError, http.client.HTTPException) as err:
                if attempt == self.retries:
                    raise SamError(f"glimmer unreachable after {attempt + 1} tries: "
                                   f"{type(err).__name__}: {err}") from err
            finally:
                with self._lock:
                    self.seconds += time.monotonic() - started
            self._sleep(delay)
            delay *= 2
        raise SamError("unreachable")  # pragma: no cover

    def segment(self, png: Path, prompt: str) -> list[dict]:
        size = png_size(png)
        url = data_url(png)
        structured = self._structured
        try:
            raw, _ = self._call(request_body(prompt, url, size, self.model, structured, self.coords))
        except SamError as exc:
            # A server that rejects json_schema gets plain JSON mode, once, remembered. Any other
            # 400 (image too large, context length) is a real failure: needs-review.
            text = str(exc).lower()
            if not (structured and text.startswith("glimmer http 400") and any(w in text for w in SCHEMA_REFUSAL)):
                raise
            with self._flag:
                self._structured = False
            raw, _ = self._call(request_body(prompt, url, size, self.model, False, self.coords))
        return parse_boxes(answer_text(raw), size, self.coords)


class EngineCheckedGlimmer(GlimmerClient):
    """Muse Glimmer whose boxes count only where they agree with the game engine (agents.engine_check).

    The check itself runs in agents.sam_observations._from_replay, after the frame cache, because it
    needs the replay's trace; this class only asks for it. Without a trace that can place objects,
    that path raises SamError (needs-review): its boxes never reach a verdict unchecked.
    """

    engine_checked = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.provider += ", each box checked against the engine's position for that object"


class BothClient:
    """SAM 3.1's boxes, counted only on frames where Muse Glimmer also sees the object.

    The verdict backend: an object is found when both models find it, so adding Glimmer can only
    make a check stricter than SAM alone. Boxes (and their scores) are SAM's, since the evaluator's
    geometry needs a segmenter's precision; Glimmer answers "is it visibly drawn here at all".
    """

    def __init__(self, sam_client: MetaSamClient | None = None, glimmer: GlimmerClient | None = None,
                 min_score: float | None = None):
        from expectrail.evaluator import DEFAULT_MIN_SCORE

        self.sam = sam_client or MetaSamClient()
        self.glimmer = glimmer or GlimmerClient()
        self.min_score = DEFAULT_MIN_SCORE if min_score is None else min_score
        self.model = f"{self.sam.model}+{self.glimmer.model}"
        self.base = f"{self.sam.base}|{self.glimmer.base}"
        self.cache_tag = self.glimmer.cache_tag + "#both-1"
        host = urllib.parse.urlparse(self.glimmer.base).hostname or self.glimmer.base
        self.provider = f"SAM 3.1 boxes, counted only where open-weights glimmer at {host} also sees the object"

    @property
    def calls(self) -> int:
        return self.sam.calls + self.glimmer.calls

    @property
    def seconds(self) -> float:
        return self.sam.seconds + self.glimmer.seconds

    def segment(self, png: Path, prompt: str) -> list[dict]:
        seen = [d for d in self.glimmer.segment(png, prompt) if d["score"] >= self.min_score]
        if not seen:
            return []  # Glimmer does not see it: not found, whatever SAM says
        return self.sam.segment(png, prompt)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from agents.keys import load_dotenv

    p = argparse.ArgumentParser(description="Wake Muse Glimmer's deployment before a probe or a verify run.")
    p.add_argument("--warm", action="store_true", required=True, help="send tiny requests until it answers")
    p.add_argument("--timeout", type=float, default=900.0, help="seconds to wait (default 900)")
    args = p.parse_args(argv)
    load_dotenv()
    try:
        waited = warm(timeout_s=args.timeout)
    except SamError as exc:
        print(f"::error title=Glimmer not reachable::{' '.join(str(exc).split()).replace('::', ': :')[:400]}")
        return 1
    print(f"::notice title=Glimmer awake::{MODEL} at {API_BASE} answered after {waited} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
