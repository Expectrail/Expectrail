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
every answer it gave, so the recording holds exactly what the model was asked.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from agents.sam_observations import SamError, box_prompt, png_size, sha256_bytes
from expectrail import resources
from expectrail.gate import record as rec
from expectrail.observers import FramesObserver

FORMAT = "expectrail.vision-recording/v1"
SCHEMA_PATH = resources.ROOT / "contracts" / "vision-recording.v1.schema.json"
MAX_BYTES = 16 * 1024 * 1024
SEGMENT, SEGMENT_IN = "segment", "segment-in"
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
            raise SamError("this frame and question are not in the recording", kind="not-recorded")
        return [None if d is None else {"box": list(d["box"]), "score": d["score"]} for d in found]

    def segment(self, png: Path, prompt: str) -> list[dict]:
        return self._answer(SEGMENT, png, prompt)

    def segment_in(self, png: Path, boxes: list[tuple[int, int, int, int]]) -> list[dict | None]:
        found = self._answer(SEGMENT_IN, png, box_prompt(boxes, png_size(Path(png))))
        if len(found) != len(boxes):
            raise SamError("the recording answers for another number of boxes", kind="not-recorded")
        return found


class RecordingClient:
    """Wraps a live client for the one recording run of a sample and keeps every answer it gave."""

    def __init__(self, inner):
        self._inner = inner
        self.model = inner.model
        self.base = getattr(inner, "base", "")
        self.provider = getattr(inner, "provider", "meta-model-api")
        self._answers: dict[tuple[str, str, str], list] = {}
        self._lock = threading.Lock()

    @property
    def calls(self) -> int:
        return getattr(self._inner, "calls", 0)

    def _keep(self, kind: str, png: Path, prompt: str, detections: list) -> None:
        with self._lock:
            self._answers[(kind, sha256_bytes(Path(png)), prompt)] = _clean(detections)

    def segment(self, png: Path, prompt: str) -> list[dict]:
        found = self._inner.segment(png, prompt)
        self._keep(SEGMENT, png, prompt, found)
        return found

    def segment_in(self, png: Path, boxes: list[tuple[int, int, int, int]]) -> list[dict | None]:
        found = self._inner.segment_in(png, boxes)
        self._keep(SEGMENT_IN, png, box_prompt(boxes, png_size(Path(png))), found)
        return found

    def recording(self, *, sample: str, recorded_at: str, run: str) -> dict:
        doc = {"format": FORMAT, "sample": sample, "recordedAt": recorded_at, "run": run,
               "model": {"name": str(self.model), "provider": str(self.provider)},
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


