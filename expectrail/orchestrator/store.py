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
# A worker's environment names its job, and everything the worker starts inherits that (the harness
# passes this one name on to the game and to the sandbox tool). It is how a lost worker's children
# are found: by the job's own random id, never by a process or group number, which can be reused.
JOB_ENV = "EXPECTRAIL_JOB"
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
    found = rec.errors(doc, schema())
    if found:
        raise StoreError(f"status.json does not match contracts/{SCHEMA_PATH.name}: {found[0]}"
                         + (f" (and {len(found) - 1} more)" if len(found) > 1 else ""))
    final, decided = doc["phase"] in FINAL, doc["decision"] is not None
    if decided != (doc["phase"] == "completed"):
        raise StoreError("status.json: only a completed job has a decision, and every completed job has one")
    if final != (doc["finishedAt"] is not None):
        raise StoreError("status.json: a job has a finish time exactly when its phase is final")
    if doc["output"] is not None and doc["phase"] != "completed":
        raise StoreError("status.json: only a completed job has an output")
    if doc["decision"] in ("accept", "reject") and doc["output"] is None:
        raise StoreError("status.json: an accept or a reject has its evidence in output/")
    if doc["history"][-1]["phase"] != doc["phase"]:
        raise StoreError("status.json: the history does not end at the phase")
    if any(entry["phase"] in FINAL for entry in doc["history"][:-1]):
        raise StoreError("status.json: the history leaves a final phase")


def _holds_a_file(folder: Path) -> bool:
    """Whether ``folder`` is a real folder with at least one plain file that has something in it."""
    if folder.is_symlink() or not folder.is_dir():
        return False
    return any(entry.is_file() and not entry.is_symlink() and entry.stat().st_size > 0 for entry in folder.rglob("*"))


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
        for side in ("head", "base"):
            if request[side] is not None:
                game = (Path(request[side]["checkout"]) / request["project"]["game"]).resolve()
                if self.root == game or game in self.root.parents:
                    # Every job would change the game's own digest, and the game's copy would hold the jobs.
                    raise StoreError(f"the jobs folder {self.root} is inside the {side} game folder; keep it outside")
                # The same for the checks: a job's own request.json and status.json would be read as
                # specs or routes, and the worker's second read of the inputs would never match the first.
                checkout = Path(request[side]["checkout"]).resolve()
                if checkout != self.root and checkout not in self.root.parents:
                    continue
                inside = self.root.relative_to(checkout).as_posix()
                specs = (checkout / request["project"]["specs"]).resolve()
                if self.root == specs or specs in self.root.parents:
                    raise StoreError(f"the jobs folder {self.root} is inside the {side} specs folder; keep it outside")
                for pattern in request["project"]["routes"]:
                    if req.pattern_reaches(pattern, inside):
                        raise StoreError(f"the jobs folder {self.root} is where the route pattern {pattern!r} looks "
                                         f"in the {side} checkout; keep it elsewhere or name the routes' own folder")
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
            # A job nobody takes is failed when this first lease runs out (`status`), so a starter that
            # died between creating the job and starting its worker leaves nothing to wait on for ever.
            "worker": None, "lease": self._lease(), "output": None, "history": [{"phase": "queued", "at": created}],
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
        """The job's status. An unfinished job whose lease ran out and whose worker is gone, or that
        no worker ever took, is failed here, so nobody waits on a job that will never finish."""
        paths = self._existing(job_id)
        doc = self._read(paths)
        if doc["phase"] in FINAL or doc["lease"] is None:   # no lease: written before jobs had one from the start
            return doc
        if parse_stamp(doc["lease"]["expiresAt"]) > now() or (doc["worker"] and alive(doc["worker"]["pid"])):
            return doc
        why = "the worker stopped before the job finished" if doc["worker"] else "no worker took the job in time"
        return self.lose(job_id, why, stage=doc["phase"])

    def lose(self, job_id: str, why: str, *, stage: str, detail: str = "", grace_seconds: float = 1.0) -> dict:
        """Fail a job whose worker is gone, then stop what that worker had started: a worker that
        was killed cannot do it itself, and the game and its display would run on to their own time
        limits. The status is made final first, so nothing they do can become a result."""
        status, lost_now = self._finish(job_id, "failed", reasons=[why],
                                        diagnostics=[diagnostic("WORKER_LOST", stage=stage, detail=detail)])
        if lost_now:
            stopped = stop_job(job_id, grace_seconds=grace_seconds)
            note = ("what it had started could not be looked for on this system (no /proc)" if stopped is None
                    else f"stopped {stopped} process(es) it had started" if stopped else None)
            if note:
                status = self._note(job_id, note)
        return status

    def _note(self, job_id: str, text: str) -> dict:
        """Add a reason to a job that is already final. Nothing else about it changes."""
        paths = self._existing(job_id)
        with self._locked(paths.lock):
            doc = self._read(paths)
            if text not in doc["reasons"] and len(doc["reasons"]) < 20:
                doc["reasons"].append(text[:300])
                return self._write(paths, doc)
            return doc

    # --- changing ----------------------------------------------------------------------------------
    def _write(self, paths: JobPaths, doc: dict) -> dict:
        doc["updatedAt"] = stamp()
        check_status(doc)
        _write_atomic(paths.status, json.dumps(doc, indent=2) + "\n")
        return doc

    def _lease(self) -> dict:
        beat = now()
        return {"heartbeatAt": stamp(beat), "expiresAt": stamp(beat + timedelta(seconds=self.lease_seconds))}

    def claim(self, job_id: str, pid: int, pgid: int) -> dict:
        """Record the job's worker. The process that starts a worker and the worker itself both call
        this, in either order: the first call records the worker and the second, naming the same
        process, changes nothing. A different process is refused, so a job has one worker, ever.
        A job that is already final is returned as it stands."""
        paths = self._existing(job_id)
        with self._locked(paths.lock):
            doc = self._read(paths)
            if doc["phase"] in FINAL:
                return doc
            if doc["worker"] is None:
                doc.update(worker={"pid": pid, "pgid": pgid}, lease=self._lease())
                return self._write(paths, doc)
            if doc["worker"] != {"pid": pid, "pgid": pgid}:
                raise StoreError(f"job {job_id} belongs to another worker")
            return doc

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

        A completed job's evidence is staging/, renamed to output/. An accept or a reject always
        publishes it and needs it to hold at least one file: with nothing to show, the job is failed
        instead, so neither decision ever stands without evidence, whatever the caller passed.
        ``publish`` only matters for needs-review, which may have none."""
        return self._finish(job_id, phase, decision=decision, reasons=reasons, diagnostics=diagnostics,
                            evidence_grade=evidence_grade, publish=publish)[0]

    def _finish(self, job_id: str, phase: str, *, decision: str | None = None, reasons: list[str] | None = None,
                diagnostics: list[dict] | None = None, evidence_grade: str | None = None,
                publish: bool = False) -> tuple[dict, bool]:
        """``finish``, also saying whether this call is the one that made the job final."""
        if phase not in FINAL:
            raise StoreError(f"{phase!r} is not a final phase")
        if (phase == "completed") != (decision in DECISIONS) or (decision is not None and decision not in DECISIONS):
            raise StoreError("a completed job needs a decision, and no other job may have one")
        paths = self._existing(job_id)
        with self._locked(paths.lock):
            doc = self._read(paths)
            if doc["phase"] in FINAL:
                return doc, False
            output = None
            decided = phase == "completed" and decision in ("accept", "reject")
            if decided and not _holds_a_file(paths.staging):
                phase, decision, evidence_grade = "failed", None, None
                reasons = ["the orchestrator failed; this says nothing about the change"]
                diagnostics = (diagnostics or []) + [diagnostic(
                    "INTERNAL_ERROR", stage=doc["phase"], detail="the engine returned a decision and wrote no evidence")]
                decided = False
            if phase == "completed" and (publish or decided) and paths.staging.is_dir():
                os.replace(paths.staging, paths.output)
                output = "output"
            shutil.rmtree(paths.staging, ignore_errors=True)
            finished = stamp()
            doc.update(phase=phase, decision=decision, reasons=[str(r)[:300] for r in (reasons or [])][:20],
                       diagnostics=(doc["diagnostics"] + (diagnostics or []))[:32], output=output,
                       evidenceGrade=evidence_grade if phase == "completed" else None, finishedAt=finished)
            doc["history"].append({"phase": phase, "at": finished})
            return self._write(paths, doc), True

    def cancel(self, job_id: str, *, grace_seconds: float = 3.0) -> dict:
        """Cancel an unfinished job and stop everything its worker started. The status is made final
        first, so whatever the worker does next cannot become a result."""
        self.status(job_id)   # a job whose worker is already lost is failed, not cancelled
        # The worker to stop is the one in the status this call made final, read under the lock: a
        # worker that recorded itself a moment before is in it, and one that comes later finds the
        # job final and does nothing (`claim`).
        status, cancelled_now = self._finish(job_id, "cancelled", reasons=["cancelled on request"])
        if cancelled_now and status["worker"] is not None:
            stop_group(status["worker"]["pgid"], grace_seconds=grace_seconds)
        if cancelled_now:
            stop_job(job_id, grace_seconds=1.0)   # and anything of the job's that had left the group
        return status


def processes_of(job_id: str) -> list[int] | None:
    """The processes whose starting environment names this job, other than this one. None where the
    system has no /proc to ask."""
    if not Path("/proc/self/environ").exists():
        return None
    marker = f"{JOB_ENV}={job_id}".encode()
    found = []
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            with open(f"/proc/{entry.name}/environ", "rb") as handle:
                names = handle.read().split(b"\0")
        except OSError:
            continue   # gone already, or another user's
        if marker in names:
            found.append(int(entry.name))
    return sorted(found)


def stop_job(job_id: str, *, grace_seconds: float = 1.0) -> int | None:
    """Stop every process that carries this job's id: ask, then make. Returns how many there were,
    or None where they cannot be looked for."""
    first = processes_of(job_id)
    if first is None:
        return None
    for sig, wait in ((signal.SIGTERM, grace_seconds), (signal.SIGKILL, 1.0)):
        left = processes_of(job_id) or []
        if not left:
            break
        for pid in left:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, sig)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline and processes_of(job_id):
            time.sleep(0.05)
    return len(first)


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
