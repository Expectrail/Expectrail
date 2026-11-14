"""A stand-in for the vision provider, on this machine, for the release gate's provider rows (#258).

The real ``expectrail verify`` (the registered engine, its live visual observer and its SAM client,
unchanged) is pointed at this server with ``EXPECTRAIL_MODEL_API_BASE``. It speaks the part of the
Responses API the client uses (``POST /v1/responses``, one prompt and one image) and has three modes:

- ``answer``: it answers from the recorded vision answers of the "Run it" samples
  (``tests.release_gate.worker.recording``), looked up by the SHA256 of the image it was sent and the
  exact prompt. A frame or prompt that is not recorded gets HTTP 400 and no answer. So with this mode
  the live client path can clear the unchanged game, which makes "not cleared" in the other modes
  mean something.
- ``down``: every request gets HTTP 503, as a provider in an outage.
- ``no-credit``: every request gets HTTP 402, as a provider whose account has run out of credit.

Nothing here leaves the machine and nothing is spent: the key the client sends is a stand-in, never a
real one, and the server only listens on 127.0.0.1. It counts what it was asked, by mode.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANSWER, DOWN, NO_CREDIT = "answer", "down", "no-credit"
STAND_IN_KEY = "release-gate-stand-in-not-a-key"


def _png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("not a PNG")
    return struct.unpack(">II", data[16:24])


def wire(detections: list[dict], size: tuple[int, int]) -> str:
    """Recorded detections (half-open boxes) as SAM 3.1's output text (inclusive corners)."""
    width, height = size
    parts = []
    for n, d in enumerate(detections, start=1):
        x0, y0, x1, y1 = d["box"]
        parts.append(f"{n}<|box;x1={x0!r};y1={y0!r};x2={x1 - 1!r};y2={y1 - 1!r};w={width};h={height};"
                     f"c={d['score']!r}|>")
    return "<0f>" + ",".join(parts)


class Provider:
    """``with Provider(recording) as p:`` serves on ``p.base``; ``p.mode`` may be changed at any time;
    ``p.asked`` counts requests by mode, and ``p.unrecorded`` those that were not in the recording."""

    def __init__(self, recording: dict, mode: str = ANSWER):
        self.mode = mode
        self.asked = {ANSWER: 0, DOWN: 0, NO_CREDIT: 0}
        self.unrecorded = 0
        self._answers = {(a["frameSha256"], a["prompt"]): a["detections"]
                         for a in recording["answers"] if a["kind"] == "segment"}
        self._lock = threading.Lock()
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):   # quiet: the tests read the counts
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                with provider._lock:
                    mode = provider.mode
                    provider.asked[mode] += 1
                if self.path.rstrip("/") != "/v1/responses":
                    return self._send(404, {"error": {"message": "no such endpoint"}})
                if mode == DOWN:
                    return self._send(503, {"error": {"message": "service unavailable (stand-in outage)"}})
                if mode == NO_CREDIT:
                    return self._send(402, {"error": {"message": "insufficient credit (stand-in)"}})
                found = provider._answer(body)
                if found is None:
                    with provider._lock:
                        provider.unrecorded += 1
                    return self._send(400, {"error": {"message": "this frame and prompt are not recorded"}})
                return self._send(200, {"status": "completed", "output_text": found})

            def _send(self, code: int, doc: dict):
                data = json.dumps(doc).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def _answer(self, body: bytes) -> str | None:
        """The output text for one request, or None when its image and prompt are not recorded."""
        try:
            doc = json.loads(body)
            content = doc["input"][0]["content"]
            prompt = next(c["text"] for c in content if c.get("type") == "input_text")
            url = next(c["image_url"] for c in content if c.get("type") == "input_image")
            png = base64.b64decode(url.split(",", 1)[1], validate=True)
            size = _png_size(png)
        except (ValueError, KeyError, IndexError, TypeError, StopIteration, binascii.Error):
            return None
        detections = self._answers.get((hashlib.sha256(png).hexdigest(), prompt))
        return None if detections is None else wire(detections, size)

    @property
    def base(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
