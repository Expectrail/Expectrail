"""Stored answers of the vision model, for the site's "Run it" samples (#265, Sean's decision of
November 13, 2026: Option A).

The game run and the checks are live on every visit. The vision answers come from one recording per
sample, made once by a person-dispatched live run, and kept in the repository:

    docs/run-it/vision/<sample>.json        expectrail.vision-recording/v1

Every answer is keyed by the SHA256 of the frame's PNG bytes and the exact text asked, so an answer
is only ever given about the picture it was recorded for:

    observer = RecordedObserver(read_recording(path))   # describe, look, segmenter: as FramesObserver
    observer.look(spec, run)                            # observations, or NoAnswer

A frame or a question that is not in the recording gets no answer (``SamError`` with kind
``not-recorded``), which the observer turns into ``NoAnswer``; the gate then decides needs-review.
There is no nearest match and no fallback to a live model: this module never sends anything anywhere.

``RecordingClient`` is the other half: it wraps a live client during the one recording run and keeps
every answer it gave, so the recording holds exactly what the model was asked. Rendering provenance
comes from the captures, never the judge machine. Missing images under a different recorded
environment remain not-recorded, with a local explanation; provenance never relaxes matching.
"""
from __future__ import annotations

import json
import re
import threading
from functools import lru_cache
from pathlib import Path

from agents.sam_observations import SamError, box_prompt, point_prompt, png_size, sha256_bytes
from expectrail import resources
from expectrail.gate import record as rec
from expectrail.observers import FramesObserver

FORMAT = "expectrail.vision-recording/v1"
SCHEMA_PATH = resources.ROOT / "contracts" / "vision-recording.v1.schema.json"
MAX_BYTES = 16 * 1024 * 1024
SEGMENT, SEGMENT_IN, SEGMENT_AT = "segment", "segment-in", "segment-at"
NAME = "sam-recorded"


class RecordingError(ValueError):
    """The recording cannot be used. No answer is given from it."""


def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def check(doc) -> None:
    """Raise RecordingError unless ``doc`` is a usable recording: it matches the schema, every
    answer to a prompt carries a score, and no frame and question is answered twice."""
    found = rec.errors(doc, schema())
    if found:
        raise RecordingError(f"does not match the vision recording schema: {found[0]}")
    seen: set[tuple[str, str, str]] = set()
    for n, answer in enumerate(doc["answers"]):
        key = (answer["kind"], answer["frameSha256"], answer["prompt"])
        if key in seen:
            raise RecordingError(f"answers/{n}: the same frame and question are answered twice")
        seen.add(key)
        if answer["kind"] == SEGMENT and any(d is None or d["score"] is None for d in answer["detections"]):
            # The live client refuses a box without a confidence for a prompt; so does its recording.
            raise RecordingError(f"answers/{n}: an answer to a prompt without a box or a score")


def read_recording(path: Path) -> dict:
    """The recording at ``path``, checked. Raises RecordingError for anything else."""
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file():
            raise RecordingError("the recording is not a file")
        raw = path.read_bytes()
    except OSError as exc:
        raise RecordingError(f"the recording could not be read ({type(exc).__name__})") from exc
    if len(raw) > MAX_BYTES:
        raise RecordingError("the recording is larger than the cap")
    try:
        doc = json.loads(raw.decode("utf-8"), parse_constant=_no_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        raise RecordingError("the recording is not JSON") from exc
    check(doc)
    return doc


def _no_constant(name: str):
    raise ValueError(f"{name} is not JSON")


def write_recording(path: Path, doc: dict) -> Path:
    check(doc)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return path


def _clean(detections: list) -> list:
    return [None if d is None else {"box": [float(v) for v in d["box"]],
                                    "score": None if d.get("score") is None else float(d["score"])}
            for d in detections]


# This is provenance, not permission to reuse an answer for a different image.
_ENV_KEYS = ("name", "version", "renderer", "device")


def capture_environment(png: Path) -> dict | None:
    """Read only the capture's adjacent replay.json; never inspect this judge's own GPU.

    A missing/invalid/linked/oversized record is unknown. In particular it cannot establish
    a renderer mismatch. Cache by file identity so thousands of questions do not parse it again.
    """
    path = Path(png).parent.parent / "replay.json"
    try:
        if path.is_symlink() or not path.is_file():
            return None
        stat = path.stat()
        if stat.st_size > MAX_BYTES:
            return None
        encoded = _capture_environment(str(path.resolve()), stat.st_mtime_ns, stat.st_ctime_ns,
                                       stat.st_size, stat.st_ino)
        return json.loads(encoded) if encoded is not None else None
    except (OSError, ValueError, TypeError):
        return None


@lru_cache(maxsize=256)
def _capture_environment(path, *_identity):
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return None
        doc = json.loads(raw, parse_constant=_no_constant)
        if not isinstance(doc, dict) or doc.get("format") != "expectrail.replay/v0":
            return None
        engine = doc.get("engine")
        if not isinstance(engine, dict):
            return None
        def field(key):
            value = engine.get(key)
            return value if isinstance(value, str) and re.fullmatch(r"[ -~]{1,160}", value) else None
        env = {key: field(key) for key in _ENV_KEYS}
        return json.dumps(env, sort_keys=True) if any(env.values()) else None
    except (OSError, ValueError):
        return None


def _environment_difference(environments, current):
    if not current or not environments or any(env is None for env in environments):
        return None
    differences = [[key for key in ("device", "renderer", "version", "name")
                    if env.get(key) and current.get(key) and env[key] != current[key]]
                   for env in environments]
    if not all(differences):
        return None  # One known environment is compatible: do not blame another in the bank.
    if len(environments) != 1:
        return (f"the replay's rendering environment differs from all {len(environments)} recorded "
                "environments; no exact image answer (not-recorded)")
    key = differences[0][0]
    llvm = [re.search(r"llvmpipe \(LLVM ([0-9.]+)", env.get("device") or "")
            for env in (environments[0], current)]
    different_llvm = all(llvm) and llvm[0].group(1) != llvm[1].group(1)

    def label(env):
        value = env[key]
        if key == "device" and different_llvm:
            return f"llvmpipe LLVM {re.search(r'LLVM ([0-9.]+)', value)[1]}"
        prefix = "engine version " if key == "version" else key + " "
        if len(value) > 40:
            old, new = environments[0][key], current[key]
            start = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
            start = max(0, start - 10)
            value = ("..." if start else "") + value[start:start + 36]
        return prefix + value
    return (f"recorded under {label(environments[0])}; this replay used {label(current)}; "
            "no exact image answer (not-recorded)")


class MissingRecordedAnswer(SamError):
    """A locally constructed explanation, never a model/provider error body."""

    def __init__(self, reason):
        super().__init__(reason, kind="not-recorded")
        self.public_reason = reason


def missing_reason(exc: BaseException) -> str | None:
    """Recover only our bounded local diagnosis through observer exception chaining."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, MissingRecordedAnswer):
            return exc.public_reason
        exc = exc.__cause__
    return None


class _DiagnosticObserver:
    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def look(self, *args, **kwargs):
        from expectrail.gate.verify import NoAnswer
        try:
            return self._inner.look(*args, **kwargs)
        except NoAnswer as exc:
            reason = missing_reason(exc)
            if reason:
                raise NoAnswer(reason) from exc
            raise


def with_recorded_diagnostics(observer):
    """Preserve recorded-image diagnoses without changing the anchored observer's rules."""
    return _DiagnosticObserver(observer)


class RecordedClient:
    """Answers as the live client does (``segment``, ``segment_in``), from a recording only."""

    def __init__(self, recording: dict):
        check(recording)
        self.recording = recording
        self.model = recording["model"]["name"]
        self.base = "recorded"
        self.provider = (f"{recording['model']['provider']} (recorded {recording['recordedAt']}, "
                         f"run {recording['run']})")
        self._answers = {(a["kind"], a["frameSha256"], a["prompt"]): a["detections"] for a in recording["answers"]}
        self._environments = list(recording.get("renderingEnvironments") or [None])
        self._frame_hashes = {a["frameSha256"] for a in recording["answers"]}
        self.last_missing_reason = None
        self.calls = 0          # questions asked of the recording
        self.answered = 0       # of them, answered
        self.not_recorded = 0   # of them, not in the recording
        self._lock = threading.Lock()

    def _answer(self, kind: str, png: Path, prompt: str) -> list:
        sha = sha256_bytes(Path(png))
        with self._lock:
            self.calls += 1
            found = self._answers.get((kind, sha, prompt))
            if found is None:
                self.not_recorded += 1
            else:
                self.answered += 1
        if found is None:
            # Never the answer about another picture or another question.
            reason = None
            if sha not in self._frame_hashes:
                reason = _environment_difference(self._environments, capture_environment(png))
            reason = reason or "the recording does not hold this frame and question (not-recorded)"
            with self._lock:
                self.last_missing_reason = reason
            raise MissingRecordedAnswer(reason)
        return [None if d is None else {"box": list(d["box"]), "score": d["score"]} for d in found]

    def segment(self, png: Path, prompt: str) -> list[dict]:
        return self._answer(SEGMENT, png, prompt)

    def segment_in(self, png: Path, boxes: list[tuple[int, int, int, int]]) -> list[dict | None]:
        found = self._answer(SEGMENT_IN, png, box_prompt(boxes, png_size(Path(png))))
        if len(found) != len(boxes):
            raise SamError("the recording answers for another number of boxes", kind="not-recorded")
        return found

    def segment_at(self, png: Path, points: list[tuple[int, int]]) -> list[dict | None]:
        found = self._answer(SEGMENT_AT, png, point_prompt(points, png_size(Path(png))))
        if len(found) != len(points):
            raise SamError("the recording answers for another number of points", kind="not-recorded")
        return found


class RecordingClient:
    """Wraps a live client for the one recording run of a sample and keeps every answer it gave."""

    def __init__(self, inner):
        self._inner = inner
        self.model = inner.model
        self.base = getattr(inner, "base", "")
        self.provider = getattr(inner, "provider", "meta-model-api")
        self._answers: dict[tuple[str, str, str], list] = {}
        self._environments: set[str] = set()
        self._lock = threading.Lock()

    @property
    def calls(self) -> int:
        return getattr(self._inner, "calls", 0)

    def _keep(self, kind: str, png: Path, prompt: str, detections: list) -> None:
        with self._lock:
            self._answers[(kind, sha256_bytes(Path(png)), prompt)] = _clean(detections)
            self._environments.add(json.dumps(capture_environment(png), sort_keys=True))

    def segment(self, png: Path, prompt: str) -> list[dict]:
        found = self._inner.segment(png, prompt)
        self._keep(SEGMENT, png, prompt, found)
        return found

    def segment_in(self, png: Path, boxes: list[tuple[int, int, int, int]]) -> list[dict | None]:
        found = self._inner.segment_in(png, boxes)
        self._keep(SEGMENT_IN, png, box_prompt(boxes, png_size(Path(png))), found)
        return found

    def segment_at(self, png: Path, points: list[tuple[int, int]]) -> list[dict | None]:
        found = self._inner.segment_at(png, points)
        self._keep(SEGMENT_AT, png, point_prompt(points, png_size(Path(png))), found)
        return found

    def recording(self, *, sample: str, recorded_at: str, run: str) -> dict:
        doc = {"format": FORMAT, "sample": sample, "recordedAt": recorded_at, "run": run,
               "model": {"name": str(self.model), "provider": str(self.provider)},
               "renderingEnvironments": [json.loads(e) for e in sorted(self._environments)],
               "answers": [{"kind": k, "frameSha256": sha, "prompt": p, "detections": d}
                           for (k, sha, p), d in sorted(self._answers.items())]}
        check(doc)
        return doc


class RecordedObserver(FramesObserver):
    """The visual observer of a "Run it" sample: ``FramesObserver`` over a ``RecordedClient``, with no
    answer cache. The record names it honestly, with the date and the run of the recording."""

    def __init__(self, recording: dict, **kw):
        self.client = RecordedClient(recording)
        super().__init__(client=self.client, cache=_NoCache(), name=NAME, **kw)

    def look(self, *args, **kwargs):
        from expectrail.gate.verify import NoAnswer
        try:
            return super().look(*args, **kwargs)
        except NoAnswer as exc:
            reason = missing_reason(exc)
            if reason:
                raise NoAnswer(reason) from exc
            raise

    def summary(self) -> dict:
        r = self.client.recording
        return {"recorded": True, "recordedAt": r["recordedAt"], "run": r["run"], "model": r["model"]["name"],
                "asked": self.client.calls, "answered": self.client.answered,
                "notRecorded": self.client.not_recorded}


class _NoCache:
    """No answer is read from or written to any cache: the recording is the only source."""

    hits = 0

    def get(self, key):
        return None

    def put(self, key, detections, meta):
        return None




class RecordedBankObserver(RecordedObserver):
    """Exact answers from an ordered set of trusted recordings, never a live fallback.

    Earlier files win for a duplicate frame/question. In CI clean.json remains first, so adding
    combat cannot replace any existing smoke answer. Dates/runs remain in ``recordings``.
    """

    def __init__(self, recordings: list[dict], **kw):
        if not recordings:
            raise RecordingError("the recording bank is empty")
        self.recordings = recordings
        self.client = RecordedClient(recordings[0])
        for doc in recordings[1:]:
            other = RecordedClient(doc)
            if doc["model"] != recordings[0]["model"]:
                raise RecordingError("recordings in a bank must use the same model and provider")
            self.client._frame_hashes.update(other._frame_hashes)
            for environment in other._environments:
                if environment not in self.client._environments:
                    self.client._environments.append(environment)
            for key, answer in other._answers.items():
                self.client._answers.setdefault(key, answer)
        self.client.provider = "recorded: " + ", ".join(d["sample"] for d in recordings)
        FramesObserver.__init__(self, client=self.client, cache=_NoCache(), name=NAME, **kw)
