"""Where jobs live on disk, and the only code that changes a job's status.

    <root>/jobs/<id>/request.json   the request, as accepted
                     status.json    expectrail.verify-job/v1, replaced whole on every change
                     lock           held while the status changes
                     work/          the job's own scratch space
                     staging/       evidence while it is being written
                     output/        the finished evidence (staging/, renamed once)
                     worker.log     the worker process's output
    <root>/keys/<sha256 of the idempotency key>.json

Rules this file holds:
- two jobs never share a folder;
- status.json is written to a temporary file, synced and renamed into place, so a reader sees the
  old status or the new one, never half of one;
- phases only go forward, and a final phase (completed, failed, cancelled) is never left, so a
  cancelled job cannot become accept;
- output/ appears by one rename, after the work is done, and only for a job that completes.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import secrets
import shutil
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from expectrail import __version__
from expectrail import diagnostics as diag
from expectrail.gate import record as rec
from expectrail.orchestrator import request as req

FORMAT = "expectrail.verify-job/v1"
SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "contracts" / "verify-job.v1.schema.json"
IN_PROGRESS = ("queued", "preparing", "executing", "observing", "evaluating")
FINAL = ("completed", "failed", "cancelled")
DECISIONS = ("accept", "reject", "needs-review")
DEFAULT_LEASE_SECONDS = 30
MAX_STATUS_BYTES = 256 * 1024
JOB_ID_LENGTH = 32
# Codes a job can carry beyond expectrail.diagnostics.CODES: the worker itself, not the change.
OWN_CODES = {
    "WORKER_LOST": ("the worker process stopped without finishing the job; there is no result",
                    "run the verification again"),
    "INTERNAL_ERROR": ("the orchestrator failed; this says nothing about the change",
                       "see the job's worker.log and run again"),
}


class StoreError(Exception):
    """The job store cannot do what was asked."""


class UnknownJob(StoreError):
    pass


class IdempotencyConflict(StoreError):
    """The key was used before for different inputs."""


def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(moment: datetime | None = None) -> str:
    return (moment or now()).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_stamp(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ" if "." in text else "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def diagnostic(code: str, *, stage: str, detail: str = "") -> dict:
    if code in OWN_CODES:
        meaning, fix = OWN_CODES[code]
        return {"code": code, "stage": stage, "detail": diag.redact(detail or meaning), "fix": fix}
    return diag.make(code, stage=stage, detail=detail)


def check_status(doc) -> None:
    """Raise StoreError unless ``doc`` is a status this code could have written."""
    try:
        rec.validate(doc, schema())
    except rec.RecordError as exc:
        raise StoreError(f"status.json: {exc}") from exc
    final, decided = doc["phase"] in FINAL, doc["decision"] is not None
    if decided != (doc["phase"] == "completed"):
        raise StoreError("status.json: only a completed job has a decision, and every completed job has one")
    if final != (doc["finishedAt"] is not None):
        raise StoreError("status.json: a job has a finish time exactly when its phase is final")
    if doc["output"] is not None and doc["phase"] != "completed":
        raise StoreError("status.json: only a completed job has an output")
    if doc["history"][-1]["phase"] != doc["phase"]:
        raise StoreError("status.json: the history does not end at the phase")
    if any(entry["phase"] in FINAL for entry in doc["history"][:-1]):
        raise StoreError("status.json: the history leaves a final phase")


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A worker that exited but has not been reaped still answers signal 0; its state file says so.
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


@dataclass(frozen=True)
class JobPaths:
    root: Path

    @property
    def request(self) -> Path: return self.root / "request.json"
    @property
    def status(self) -> Path: return self.root / "status.json"
    @property
    def lock(self) -> Path: return self.root / "lock"
    @property
    def work(self) -> Path: return self.root / "work"
    @property
    def staging(self) -> Path: return self.root / "staging"
    @property
    def output(self) -> Path: return self.root / "output"
    @property
    def log(self) -> Path: return self.root / "worker.log"


class JobStore:
    def __init__(self, root: Path, *, lease_seconds: float = DEFAULT_LEASE_SECONDS):
        self.root = Path(root).resolve()
        self.lease_seconds = lease_seconds

    # --- where things are --------------------------------------------------------------------------
    def paths(self, job_id: str) -> JobPaths:
        if not (isinstance(job_id, str) and len(job_id) == JOB_ID_LENGTH and all(c in "0123456789abcdef" for c in job_id)):
            raise UnknownJob("not a job id")
        return JobPaths(self.root / "jobs" / job_id)

    def _existing(self, job_id: str) -> JobPaths:
        paths = self.paths(job_id)
        if not paths.status.is_file():
            raise UnknownJob(f"no job {job_id}")
        return paths

    @contextlib.contextmanager
    def _locked(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    # --- creating ----------------------------------------------------------------------------------
    def create(self, request: dict) -> tuple[dict, bool]:
        """The job for this request, and whether it was created now. With an idempotency key, the job
        made earlier for the same key and inputs is returned instead; different inputs are an error."""
        req.check(request)
        inputs = req.inputs(request)
        key = request["idempotencyKey"]
        if key is None:
            return self._new(request, inputs), True
        key_file = self.root / "keys" / (hashlib.sha256(key.encode()).hexdigest() + ".json")
        with self._locked(self.root / "keys" / "lock"):
            if key_file.is_file():
                seen = json.loads(key_file.read_text(encoding="utf-8"))
                if seen["requestDigest"] != inputs["requestDigest"]:
                    raise IdempotencyConflict("this idempotency key was used for a request with different inputs")
                return self.status(seen["id"]), False
            status = self._new(request, inputs)
            _write_atomic(key_file, json.dumps({"id": status["id"], "requestDigest": inputs["requestDigest"]}) + "\n")
            return status, True

    def _new(self, request: dict, inputs: dict) -> dict:
        while True:
            job_id = secrets.token_hex(JOB_ID_LENGTH // 2)
            paths = self.paths(job_id)
            try:
                paths.root.mkdir(parents=True)   # fails if the folder exists: a folder has one job, ever
                break
            except FileExistsError:
                continue
        paths.work.mkdir()
        created = stamp()
        status = {
            "format": FORMAT, "id": job_id, "phase": "queued", "decision": None, "reasons": [], "diagnostics": [],
            "inputs": inputs, "executionClass": request["executionClass"], "evidenceGrade": None,
            "worker": None, "lease": None, "output": None, "history": [{"phase": "queued", "at": created}],
            "createdAt": created, "updatedAt": created, "finishedAt": None, "expectrail": {"version": __version__},
        }
        check_status(status)
        _write_atomic(paths.request, json.dumps(request, indent=2) + "\n")
        _write_atomic(paths.status, json.dumps(status, indent=2) + "\n")
        return status

    # --- reading -----------------------------------------------------------------------------------
    def request(self, job_id: str) -> dict:
        return req.load(self._existing(job_id).request)

    def _read(self, paths: JobPaths) -> dict:
        try:
            doc = rec.read_json(paths.status, cap=MAX_STATUS_BYTES, label="status.json")
        except rec.RecordError as exc:
            raise StoreError(str(exc)) from exc
        check_status(doc)
        return doc

    def status(self, job_id: str) -> dict:
        """The job's status. An unfinished job whose lease ran out and whose worker is gone is failed
        here, so nobody waits on a job that will never finish."""
        paths = self._existing(job_id)
        doc = self._read(paths)
        if doc["phase"] in FINAL or doc["lease"] is None:
            return doc
        if parse_stamp(doc["lease"]["expiresAt"]) > now() or (doc["worker"] and alive(doc["worker"]["pid"])):
            return doc
        return self.finish(job_id, "failed", diagnostics=[diagnostic("WORKER_LOST", stage=doc["phase"])],
                           reasons=["the worker stopped before the job finished"])

    # --- changing ----------------------------------------------------------------------------------
    def _write(self, paths: JobPaths, doc: dict) -> dict:
        doc["updatedAt"] = stamp()
        check_status(doc)
        _write_atomic(paths.status, json.dumps(doc, indent=2) + "\n")
        return doc

    def _lease(self) -> dict:
        beat = now()
        return {"heartbeatAt": stamp(beat), "expiresAt": stamp(beat + timedelta(seconds=self.lease_seconds))}

    def start(self, job_id: str, pid: int, pgid: int) -> dict:
        """A worker takes the job. Only a queued job can be taken, and only once."""
        paths = self._existing(job_id)
        with self._locked(paths.lock):
            doc = self._read(paths)
            if doc["phase"] != "queued" or doc["worker"] is not None:
                raise StoreError(f"job {job_id} is {doc['phase']} and cannot be started")
            doc.update(worker={"pid": pid, "pgid": pgid}, lease=self._lease())
            return self._write(paths, doc)

    def heartbeat(self, job_id: str) -> dict:
        paths = self._existing(job_id)
        with self._locked(paths.lock):
            doc = self._read(paths)
            if doc["phase"] in FINAL:
                return doc
            doc["lease"] = self._lease()
            return self._write(paths, doc)

    def advance(self, job_id: str, phase: str) -> dict:
        """Move an unfinished job forward to a later in-progress phase. Phases only go forward
        (queued, preparing, executing, observing, evaluating): asking for the same or an earlier one
        changes nothing, and a finished job stays as it is."""
        if phase not in IN_PROGRESS:
            raise StoreError(f"{phase!r} is not an in-progress phase")
        paths = self._existing(job_id)
        with self._locked(paths.lock):
            doc = self._read(paths)
            if doc["phase"] in FINAL or IN_PROGRESS.index(phase) <= IN_PROGRESS.index(doc["phase"]):
                return doc
            doc["phase"] = phase
            doc["history"].append({"phase": phase, "at": stamp()})
            doc["lease"] = self._lease() if doc["lease"] is not None else None
            return self._write(paths, doc)

    def finish(self, job_id: str, phase: str, *, decision: str | None = None, reasons: list[str] | None = None,
               diagnostics: list[dict] | None = None, evidence_grade: str | None = None,
               publish: bool = False) -> dict:
        """Take the job to a final phase, once. If it is already final, nothing changes and the status
        as it stands is returned: the first finish wins, so a cancel cannot be undone by a late result.

        ``publish`` renames staging/ to output/ for a completed job. Anything else in staging/ is removed."""
        if phase not in FINAL:
            raise StoreError(f"{phase!r} is not a final phase")
        if (phase == "completed") != (decision in DECISIONS) or (decision is not None and decision not in DECISIONS):
            raise StoreError("a completed job needs a decision, and no other job may have one")
        paths = self._existing(job_id)
        with self._locked(paths.lock):
            doc = self._read(paths)
            if doc["phase"] in FINAL:
                return doc
            output = None
            if phase == "completed" and publish and paths.staging.is_dir():
                os.replace(paths.staging, paths.output)
                output = "output"
            shutil.rmtree(paths.staging, ignore_errors=True)
            finished = stamp()
            doc.update(phase=phase, decision=decision, reasons=[str(r)[:300] for r in (reasons or [])][:20],
                       diagnostics=(doc["diagnostics"] + (diagnostics or []))[:32], output=output,
                       evidenceGrade=evidence_grade if phase == "completed" else None, finishedAt=finished)
            doc["history"].append({"phase": phase, "at": finished})
            return self._write(paths, doc)

    def cancel(self, job_id: str, *, grace_seconds: float = 3.0) -> dict:
        """Cancel an unfinished job and stop everything its worker started. The status is made final
        first, so whatever the worker does next cannot become a result."""
        before = self.status(job_id)
        status = self.finish(job_id, "cancelled", reasons=["cancelled on request"])
        worker = before["worker"]
        if before["phase"] in FINAL or status["phase"] != "cancelled" or worker is None:
            return status
        stop_group(worker["pgid"], grace_seconds=grace_seconds)
        return status


def stop_group(pgid: int, *, grace_seconds: float = 3.0) -> None:
    """Ask a process group to stop, then make it."""
    if pgid == os.getpgid(0):
        raise StoreError("refusing to stop this process's own group")
    for sig, wait in ((signal.SIGTERM, grace_seconds), (signal.SIGKILL, 1.0)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
