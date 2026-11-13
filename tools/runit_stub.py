"""A local stand-in for the Run it edge function (#265, slice 2), on 127.0.0.1 only.

It speaks the same HTTP contract as the edge function will (``expectrail.run-it-api/v1``) and serves
the site from ``docs/``, so the Run it page can be opened and used without GitHub or an account:

    python3 -m tools.runit_stub                 real runs: needs Godot, as `expectrail.runit run` does
    python3 -m tools.runit_stub --stand-in      stand-in replays, no Godot; the page says so on every run
    python3 -m tools.runit_stub --stand-in --stand-in-recorded
                                                the stand-ins with vision answers recorded from the
                                                scripted stand-in model, so a sample can be accepted

then open http://127.0.0.1:8765/run-it/#local (the fragment tells the page to use this stub).

    GET  /api/health                 {"kind": "health", "open": ..., "standIn": ...}
    POST /api/run   {"sample": id}   202 accepted, with a request id the stub mints; or refused
    GET  /api/status/<request id>    the run's state; or refused (404, unknown-request)
    GET  /results/<request id>/...   the published folders and latest.json, as the results branch holds them
    GET  /...                        docs/

What the workflow does, the stub does in the same order: the run writes its folder, main's
``expectrail.runit check`` checks it, and only a folder that passes is published under
``results/<request id>/`` and listed in ``latest.json``. A folder that fails the check is not
published: the run is failed, with no verdict.

The limits are the ones the edge function will hold (slice 3 writes them for its runtime): one run at
a time ("busy"), a number of runs per visitor per day (keyed on a salted hash of the address, never
stored raw), a global daily cap, and a circuit breaker that stops starting runs after a number of
failed runs in a row. Every refusal says which limit and when it resets.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import http.server
import json
import mimetypes
import re
import secrets
import shutil
import sys
import tempfile
import threading
import traceback
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

from expectrail import runit, runit_site

ROOT = Path(__file__).resolve().parent.parent
FORMAT = runit_site.API_FORMAT
MAX_BODY_BYTES = 1024
SAFE_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}")
ACTIVE = ("queued", "running", "publishing")
FAILED = "failed"


def iso(moment: dt.datetime) -> str:
    return moment.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def refusal(reason: str, detail: str, *, resets_at: str | None = None, retry_after: int | None = None) -> dict:
    return {"format": FORMAT, "kind": "refused", "reason": reason, "detail": detail[:300],
            "resetsAt": resets_at, "retryAfterSeconds": retry_after}


class Limits:
    """The edge function's limits, in one place, with an injectable clock (tests)."""

    def __init__(self, *, per_visitor: int = 3, daily_cap: int = 40, breaker: int = 3, clock=utc_now):
        self.per_visitor, self.daily_cap, self.breaker, self.clock = per_visitor, daily_cap, breaker, clock
        self._salt = secrets.token_bytes(16)   # per process: the hashes mean nothing outside it
        self._day = None
        self._visitors: dict[str, int] = {}
        self._today = 0
        self.failed_in_a_row = 0

    def visitor(self, address: str) -> str:
        return hashlib.sha256(self._salt + address.encode("utf-8", "replace")).hexdigest()

    def _roll(self) -> dt.datetime:
        now = self.clock()
        if self._day != now.date():
            self._day, self._visitors, self._today = now.date(), {}, 0
        return now

    def _midnight(self, now: dt.datetime) -> str:
        return iso(dt.datetime.combine(now.date() + dt.timedelta(days=1), dt.time(0), dt.UTC))

    def refuse(self, visitor: str) -> dict | None:
        """The refusal for a new run from ``visitor`` now, or None when it may start."""
        now = self._roll()
        if self.failed_in_a_row >= self.breaker:
            return refusal("circuit-open", f"Run it stopped starting runs after {self.failed_in_a_row} failed runs in a "
                           "row. A person has to look before it starts again; the latest finished runs are still here.")
        if self._today >= self.daily_cap:
            return refusal("daily-cap", f"Run it has started {self._today} runs today, its most for one day. "
                           "It starts again at midnight UTC.", resets_at=self._midnight(now))
        if self._visitors.get(visitor, 0) >= self.per_visitor:
            return refusal("visitor-quota", f"You have started {self.per_visitor} runs today, the most for one "
                           "visitor. Your quota resets at midnight UTC.", resets_at=self._midnight(now))
        return None

    def started(self, visitor: str) -> None:
        self._roll()
        self._visitors[visitor] = self._visitors.get(visitor, 0) + 1
        self._today += 1

    def finished(self, failed: bool) -> None:
        self.failed_in_a_row = self.failed_in_a_row + 1 if failed else 0

    @property
    def broken(self) -> bool:
        return self.failed_in_a_row >= self.breaker


def real_runner(require_sandbox: bool = False):
    """The run the workflow's verify job makes: ``expectrail.runit run`` (needs Godot)."""
    def run(sample: str, out: Path, request_id: str) -> None:
        runit.run(sample, out, request_id=request_id, require_sandbox=require_sandbox)
    return run, ROOT


def stand_in_runner(recorded: bool = False):
    """Stand-in replays and, with ``recorded``, recordings made from the scripted stand-in model.

    For looking at the page without Godot. These are not runs of the game: the API says
    ``standIn: true`` on every one, and the page says so beside the verdict."""
    from agents.sam_observations import MetaSamClient
    from tests.test_runit import make_root
    from tests.test_two_observers import Game

    root = make_root(Path(tempfile.mkdtemp(prefix="expectrail-stub-root-")))
    game = Game()
    game.look_of = lambda folder: "BUG" if (folder / "BUG").exists() else "clean"
    lock = threading.Lock()
    if recorded:
        client = MetaSamClient(transport=game.transport, retries=0, sleep=lambda s: None)
        for sample in runit.read_manifest(root)["samples"]:
            runit.record(sample["id"], root / sample["vision"], run_id="stand-in", client=client, root=root,
                         replay=game.replay, recorded_at=utc_now().date().isoformat())

    def run(sample: str, out: Path, request_id: str) -> None:
        with lock:
            runit.run(sample, out, request_id=request_id, root=root, replay=game.replay)
    return run, root


class Service:
    """The runs, their states and the limits. One worker thread runs one run at a time."""

    def __init__(self, results: Path, runner, root: Path = ROOT, *, limits: Limits | None = None,
                 open_: bool = True, stand_in: bool = False, clock=utc_now):
        self.results = Path(results)
        self.results.mkdir(parents=True, exist_ok=True)
        self.runner, self.root, self.open, self.stand_in, self.clock = runner, Path(root), open_, stand_in, clock
        self.limits = limits or Limits(clock=clock)
        self.manifest = runit.read_manifest(self.root)
        self.runs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.log = lambda message: print(message, file=sys.stderr)

    # The API's bodies -------------------------------------------------------------------------
    def health(self) -> dict:
        with self.lock:
            return {"format": FORMAT, "kind": "health", "open": self.open and not self.limits.broken,
                    "standIn": self.stand_in}

    def status(self, request_id: str) -> tuple[int, dict]:
        with self.lock:
            run = self.runs.get(request_id) if runit.valid_id(request_id) else None
            if run is None:
                return 404, refusal("unknown-request", "No run with this request id is known here.")
            return 200, self._status(request_id, run)

    def _status(self, request_id: str, run: dict) -> dict:
        return {"format": FORMAT, "kind": "status", "requestId": request_id, "sample": run["sample"],
                "state": run["state"], "updatedAt": run["updatedAt"], "standIn": self.stand_in}

    def start(self, body: bytes, address: str) -> tuple[int, dict]:
        try:
            doc = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return 400, refusal("bad-request", 'Send {"sample": "<sample id>"} as JSON.')
        if not isinstance(doc, dict) or set(doc) != {"sample"} or not isinstance(doc["sample"], str):
            return 400, refusal("bad-request", 'Send {"sample": "<sample id>"} as JSON, and nothing else.')
        sample = doc["sample"]
        if not runit.valid_id(sample) or sample not in {s["id"] for s in self.manifest["samples"]}:
            return 400, refusal("unknown-sample", "That is not one of the samples Run it offers.")
        with self.lock:
            if not self.open:
                return 503, refusal("disabled", "Run it is switched off. The latest finished runs are still here.")
            if any(r["state"] in ACTIVE for r in self.runs.values()):
                return 409, refusal("busy", "Another visitor's run is going. Try again in a minute.", retry_after=60)
            visitor = self.limits.visitor(address)
            refused = self.limits.refuse(visitor)
            if refused is not None:
                return (503 if refused["reason"] == "circuit-open" else 429), refused
            self.limits.started(visitor)
            request_id = str(uuid.uuid4())
            self.runs[request_id] = {"sample": sample, "state": "queued", "updatedAt": iso(self.clock())}
        threading.Thread(target=self._work, args=(request_id,), daemon=True, name=f"run-{request_id}").start()
        return 202, {"format": FORMAT, "kind": "accepted", "requestId": request_id, "sample": sample}

    # The run ----------------------------------------------------------------------------------
    def _set(self, request_id: str, state: str) -> None:
        with self.lock:
            self.runs[request_id].update(state=state, updatedAt=iso(self.clock()))

    def _work(self, request_id: str) -> None:
        sample = self.runs[request_id]["sample"]
        published = False
        with tempfile.TemporaryDirectory(prefix="expectrail-stub-run-") as tmp:
            out = Path(tmp) / request_id
            try:
                self._set(request_id, "running")
                self.runner(sample, out, request_id)
                self._set(request_id, "publishing")
                problems = runit.check(out, sample_id=sample, request_id=request_id, root=self.root)
                if problems:
                    self.log(f"run {request_id}: not published, the check refused it: {problems[0]}")
                elif (self.results / request_id).exists():
                    self.log(f"run {request_id}: not published, a run with this id is published")
                else:
                    shutil.copytree(out, self.results / request_id)
                    try:
                        runit_site.update_latest(self.results, request_id, self.root)
                    except BaseException:
                        shutil.rmtree(self.results / request_id, ignore_errors=True)   # all or nothing
                        raise
                    published = True
            except Exception:   # noqa: BLE001 - whatever happens, the run ends failed with no verdict
                self.log(f"run {request_id}: failed\n{traceback.format_exc()}")
        failed = not published
        if published:
            status = json.loads((self.results / request_id / "status.json").read_text(encoding="utf-8"))
            failed = status["phase"] != "completed"
        with self.lock:
            self.limits.finished(failed)
        self._set(request_id, "published" if published else FAILED)


class Handler(http.server.BaseHTTPRequestHandler):
    service: Service
    docs: Path = ROOT / "docs"
    server_version = "expectrail-runit-stub"

    def log_message(self, fmt, *args):   # quiet; errors still reach stderr through the service
        pass

    def _send(self, code: int, body: bytes, kind: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, doc: dict) -> None:
        extra = {}
        if doc.get("retryAfterSeconds"):
            extra["Retry-After"] = str(doc["retryAfterSeconds"])
        self._send(code, (json.dumps(doc) + "\n").encode("utf-8"), "application/json", extra)

    def _file(self, base: Path, parts: list[str]) -> None:
        if not all(SAFE_SEGMENT.fullmatch(p) for p in parts):
            return self._send(404, b"not found\n", "text/plain; charset=utf-8")
        path = base.joinpath(*parts) if parts else base
        if path.is_dir():
            path = path / "index.html"
        try:
            inside = path.resolve().is_relative_to(base.resolve())
        except OSError:
            inside = False
        if not inside or path.is_symlink() or not path.is_file():
            return self._send(404, b"not found\n", "text/plain; charset=utf-8")
        kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind in ("application/json", "application/javascript"):
            kind += "; charset=utf-8"
        self._send(200, path.read_bytes(), kind)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/health":
            return self._json(200, self.service.health())
        if path.startswith("/api/status/"):
            return self._json(*self.service.status(path[len("/api/status/"):]))
        if path.startswith("/api/"):
            return self._json(404, refusal("bad-request", "No such endpoint."))
        if path == "/":
            return self._send(302, b"", "text/plain", {"Location": "/run-it/#local"})
        parts = [unquote(p) for p in path.split("/") if p]
        if parts and parts[0] == "results":
            return self._file(self.service.results, parts[1:])
        if (not path.endswith("/") and all(SAFE_SEGMENT.fullmatch(p) for p in parts)
                and self.docs.joinpath(*parts).is_dir()):
            return self._send(301, b"", "text/plain", {"Location": path + "/"})
        return self._file(self.docs, parts)

    do_HEAD = do_GET

    def do_POST(self):
        if urlsplit(self.path).path != "/api/run":
            return self._json(404, refusal("bad-request", "No such endpoint."))
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY_BYTES:
            return self._json(400, refusal("bad-request", f"Send a body of at most {MAX_BODY_BYTES} bytes."))
        self._json(*self.service.start(self.rfile.read(length), self.client_address[0]))


def serve(service: Service, port: int = 8765, docs: Path | None = None) -> http.server.ThreadingHTTPServer:
    """A server bound to 127.0.0.1 (port 0: any free port). The caller runs ``serve_forever``."""
    handler = type("BoundHandler", (Handler,), {"service": service, "docs": Path(docs or ROOT / "docs")})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m tools.runit_stub", description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--results", type=Path, default=None, help="where published folders go (default: a new temporary folder)")
    parser.add_argument("--stand-in", action="store_true", help="stand-in replays, no Godot (not runs of the game)")
    parser.add_argument("--stand-in-recorded", action="store_true",
                        help="with --stand-in: vision answers recorded from the scripted stand-in model")
    parser.add_argument("--require-sandbox", action="store_true", help="real runs: every replay in the sandbox")
    parser.add_argument("--closed", action="store_true", help="switched off: every run is refused, as with the worker disabled")
    parser.add_argument("--per-visitor", type=int, default=3)
    parser.add_argument("--daily-cap", type=int, default=40)
    parser.add_argument("--breaker", type=int, default=3)
    args = parser.parse_args(argv)
    if args.stand_in_recorded and not args.stand_in:
        parser.error("--stand-in-recorded needs --stand-in")
    runner, root = stand_in_runner(args.stand_in_recorded) if args.stand_in else real_runner(args.require_sandbox)
    results = args.results or Path(tempfile.mkdtemp(prefix="expectrail-stub-results-"))
    service = Service(results, runner, root, open_=not args.closed, stand_in=args.stand_in,
                      limits=Limits(per_visitor=args.per_visitor, daily_cap=args.daily_cap, breaker=args.breaker))
    server = serve(service, args.port)
    print(f"Run it, local stub: http://127.0.0.1:{server.server_address[1]}/run-it/#local  (results in {results})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
