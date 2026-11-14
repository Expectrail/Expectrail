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
