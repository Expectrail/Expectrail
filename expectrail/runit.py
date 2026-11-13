""""Run it" on expectrail.tech, the same run offline (#265, slice 1).

    python3 -m expectrail.runit run --sample fall-through-bug --out DIR [--request-id ID] [--require-sandbox]
    python3 -m expectrail.runit check DIR --sample fall-through-bug --request-id ID
    python3 -m expectrail.runit record --sample fall-through-bug --out FILE --run ID     (live: spends money)

A visitor chooses one thing: a sample id from ``docs/run-it/samples.json``. ``run`` replays that
sample's game (the bundled platformer, as it is or with its seeded bug) on the smoke route, judges it
with the approved check under the two-observer rule (#327: the engine's record and the vision model,
both needed for a pass), and writes:

    DIR/status.json       expectrail.run-it-result/v1: the sample, the job's phase and decision, the
                          vision answers it used, the receipt (not signed yet, #255)
    DIR/findings.json     the gate's findings record, when the job completed with one
    DIR/viewer/           the evidence viewer's folder (#264), what the site opens

The vision answers are the sample's recording (``expectrail.recorded``): no model is called and no
key is needed. Without a recording, or for a frame the recording does not hold, the vision side has
no answer, so nothing is accepted: the decision is needs-review (a check the engine sees failing still
rejects). The site's workflow (``.github/workflows/run-it.yml``) runs exactly this in a job that holds
no secret, and ``check`` is what its publishing job runs on the folder before it commits anything.

``record`` is the one live run per sample that makes the recording. It needs a model key and a spend
cap (``EXPECTRAIL_SAM_USD_CAP``), costs about $0.33 a sample (docs/sam.md), and is dispatched by Sean.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from expectrail import resources
from expectrail.diagnostics import redact
from expectrail.gate import record as rec

ROOT = resources.ROOT
MANIFEST = "docs/run-it/samples.json"
SAMPLES_SCHEMA = "contracts/run-it-samples.v1.schema.json"
RESULT_SCHEMA = "contracts/run-it-result.v1.schema.json"
RESULT_FORMAT = "expectrail.run-it-result/v1"
ID = re.compile(r"[a-z0-9-]{1,40}")
TIMEOUT_SECONDS = 15 * 60
RECEIPT = {"signed": False, "why": "not signed yet (#255)"}
NO_RECORDING = "no vision answers are recorded for this sample yet, so nothing can be accepted"

# What the publishing job lets through (``check``): these names, and frames named as the viewer
# names them. Nothing else, no link, nothing larger than the caps.
FIXED_FILES = {"status.json", "findings.json", "viewer/index.html", "viewer/views.json", "viewer/evidence.html"}
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 40 * 1024 * 1024
MAX_FILES = 400
MAX_STATUS_BYTES = 256 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class RunItError(ValueError):
    """The request cannot be run. Nothing was replayed and nothing was written."""


def valid_id(value) -> bool:
    return isinstance(value, str) and ID.fullmatch(value) is not None


def _schema(root: Path, name: str) -> dict:
    return json.loads((Path(root) / name).read_text(encoding="utf-8"))


def read_manifest(root: Path = ROOT) -> dict:
    path = Path(root) / MANIFEST
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RunItError(f"{MANIFEST} could not be read ({type(exc).__name__})") from exc
    found = rec.errors(doc, _schema(root, SAMPLES_SCHEMA))
    if found:
        raise RunItError(f"{MANIFEST} does not match its schema: {found[0]}")
    ids = [s["id"] for s in doc["samples"]]
    if len(set(ids)) != len(ids):
        raise RunItError(f"{MANIFEST} lists a sample twice")
    for s in doc["samples"]:
        if s["vision"] != f"docs/run-it/vision/{s['id']}.json":
            raise RunItError(f"{MANIFEST}: sample {s['id']}'s recording is not at docs/run-it/vision/{s['id']}.json")
    return doc


def find_sample(manifest: dict, sample_id) -> dict:
    """The sample with this id. Anything that is not one of the manifest's ids is refused."""
    if not valid_id(sample_id):
        raise RunItError("a sample id is lower-case letters, digits and hyphens, at most 40")
    for s in manifest["samples"]:
        if s["id"] == sample_id:
            return s
    raise RunItError(f"no sample named {sample_id}; the samples are {', '.join(s['id'] for s in manifest['samples'])}")


def expected_now(sample: dict, recorded: bool) -> str:
    """The decision a working install gives today. Without recorded vision answers nothing is
    accepted, so a sample that would accept needs review; one that rejects still rejects, because a
    check the engine's record sees failing is a failure under the two-observer rule."""
    if recorded or sample["expected"] != "accept":
        return sample["expected"]
    return "needs-review"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _commit(root: Path) -> str | None:
    sha = os.environ.get("GITHUB_SHA", "").strip()
    if re.fullmatch(r"[0-9a-f]{40}", sha):
        return sha
    try:
        done = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = done.stdout.strip()
    return out if done.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", out) else None


def _vision(sample: dict, root: Path):
    """(the observer, its summary for status.json). The observer is None when the sample has no
    usable recording; the summary then says why."""
    from expectrail import recorded

    empty = {"recorded": False, "recordedAt": None, "run": None, "model": None, "asked": 0, "answered": 0,
             "notRecorded": 0}
    path = Path(root) / sample["vision"]
    if not path.exists() and not path.is_symlink():
        return None, {**empty, "why": NO_RECORDING}
    try:
        recording = recorded.read_recording(path)
    except recorded.RecordingError as exc:
        return None, {**empty, "why": f"the recording could not be used: {exc}"[:300]}
    if recording["sample"] != sample["id"]:
        return None, {**empty, "why": "the recording is for another sample"}
    return recorded.RecordedObserver(recording), None


def run(sample_id: str, out: Path, *, request_id: str | None = None, root: Path = ROOT, replay=None,
        require_sandbox: bool = False, timeout_seconds: int = TIMEOUT_SECONDS, record_with=None,
        on_phase=None) -> dict:
    """Run one sample and write its folder at ``out``; returns status.json's document.

    ``replay`` is a stand-in for the harness (tests). ``record_with`` is a live vision client: the
    run then asks it, and the answers it gave are returned under ``"recording"`` (``record``).
    Raises RunItError before anything runs for an unknown sample, a bad request id, or an ``out``
    that is not empty."""
    from expectrail import recorded, viewer
    from expectrail.observers import FramesObserver
    from expectrail.orchestrator import engines, runner
    from expectrail.orchestrator import request as req
    from expectrail.orchestrator import sample as smp
    from expectrail.orchestrator import store as st
    from agents.sam_observations import Cache

    root = Path(root)
    manifest = read_manifest(root)
    sample = find_sample(manifest, sample_id)
    request_id = request_id or "local"
    if not valid_id(request_id):
        raise RunItError("a request id is lower-case letters, digits and hyphens, at most 40")
    out = Path(out)
    if out.is_symlink() or (out.exists() and (not out.is_dir() or any(out.iterdir()))):
        raise RunItError(f"{out} is not an empty folder")
    started = _now()
    if record_with is not None:
        recorder = recorded.RecordingClient(record_with)
        observer, vision = FramesObserver(client=recorder, cache=Cache(None), name="sam"), None
    else:
        recorder = None
        observer, vision = _vision(sample, root)
    with tempfile.TemporaryDirectory(prefix="expectrail-runit-") as tmp:
        tmp = Path(tmp)
        try:
            trees = {"clean": smp.checkout(tmp / "clean", bug=False, root=root)}
            if "bug" in (sample["head"], sample["base"]):
                trees["bug"] = smp.checkout(tmp / "bug", bug=True, root=root)
        except smp.SampleError as exc:
            raise RunItError(str(exc)) from exc
        store = st.JobStore(tmp / "jobs")
        request = req.build(adapter="godot", head=trees[sample["head"]],
                            base=trees[sample["base"]] if sample["base"] else None,
                            game=manifest["game"], routes=[manifest["route"]], specs=manifest["specs"],
                            execution_class="isolated" if require_sandbox else "diagnostic",
                            timeout_seconds=timeout_seconds, idempotency_key=f"run-it-{request_id}"[:64])
        status, _ = store.create(request)
        engine = engines.GodotGate(replay=replay, rule=rec.BOTH, visual=observer)
        status = runner.work(store, status["id"], engines={"godot": engine})
        viewer.write_job(store, status["id"])
        folder = store.paths(status["id"]).root / "viewer"
        out.mkdir(parents=True, exist_ok=True)
        shutil.copytree(folder, out / "viewer")
        findings = store.paths(status["id"]).output / "findings.json" if status.get("output") else None
        has_findings = findings is not None and findings.is_file()
        if has_findings:
            shutil.copyfile(findings, out / "findings.json")
    if vision is None:
        if recorder is not None:
            vision = {"recorded": False, "recordedAt": None, "run": None, "model": str(recorder.model)[:80],
                      "asked": 0, "answered": 0, "notRecorded": 0, "why": "this run made the recording, live"}
        else:
            vision = {**observer.summary(), "why": None}
            if vision["notRecorded"]:
                vision["why"] = ("the replay drew a frame, or asked a question, that the recording does not hold; "
                                 "no answer was reused from another picture")
    decision = status["decision"] if status["phase"] == "completed" else None
    doc = {
        "format": RESULT_FORMAT,
        "requestId": request_id,
        "sample": {"id": sample["id"], "title": sample["title"], "expected": sample["expected"]},
        "phase": status["phase"] if status["phase"] in ("completed", "failed", "cancelled") else "failed",
        "decision": decision,
        "asExpected": decision is not None and decision == expected_now(sample, vision["recorded"]),
        "diagnostics": [{"code": d["code"], "detail": redact(d.get("detail", ""))[:600]}
                        for d in status.get("diagnostics", [])][:20],
        "vision": vision,
        "receipt": dict(RECEIPT),
        "startedAt": started,
        "finishedAt": _now(),
        "expectrailCommit": _commit(root),
        "viewer": "viewer/index.html",
        "findings": "findings.json" if has_findings else None,
    }
    found = rec.errors(doc, _schema(root, RESULT_SCHEMA))
    if found:   # a bug here, never a visitor's input: stop rather than publish a malformed result
        raise AssertionError(f"status.json does not match its schema: {found[0]}")
    (out / "status.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if recorder is not None:
        doc = {**doc, "recording": recorder}
    return doc


def record(sample_id: str, target: Path, *, run_id: str, client=None, root: Path = ROOT, replay=None,
           require_sandbox: bool = False, recorded_at: str | None = None) -> Path:
    """The one live run of a sample that records the vision model's answers into ``target``.
    ``client`` defaults to the live model client, which needs a key and a spend cap."""
    from expectrail import recorded

    if client is None:
        from agents.sam_observations import default_client

        client = default_client(verdict=True)
    with tempfile.TemporaryDirectory(prefix="expectrail-runit-record-") as tmp:
        doc = run(sample_id, Path(tmp) / "out", request_id="recording", root=root, replay=replay,
                  require_sandbox=require_sandbox, record_with=client)
    recording = doc["recording"].recording(sample=sample_id, run=run_id,
                                           recorded_at=recorded_at or dt.date.today().isoformat())
    return recorded.write_recording(target, recording)


# --- what the recording workflow lets through ------------------------------------------------------

def check_recording(path: Path, *, sample_id: str, root: Path = ROOT) -> list[str]:
    """Every reason not to propose the recording at ``path`` for ``sample_id``; empty when it may be.
    It must be a usable recording (expectrail.recorded.read_recording), for this sample, from a
    sample in the manifest, and hold at least one answer: an empty recording answers nothing."""
    from expectrail import recorded

    if not valid_id(sample_id):
        return ["the sample is not a sample id"]
    try:
        find_sample(read_manifest(root), sample_id)
    except RunItError as exc:
        return [str(exc)]
    try:
        doc = recorded.read_recording(Path(path))
    except recorded.RecordingError as exc:
        return [f"the recording cannot be used: {exc}"]
    problems = []
    if doc["sample"] != sample_id:
        problems.append(f"the recording is for {doc['sample']!r}, not {sample_id!r}")
    if not doc["answers"]:
        problems.append("the recording holds no answers")
    return problems


# --- what the publishing job lets through ----------------------------------------------------------

def check(folder: Path, *, sample_id: str, request_id: str, root: Path = ROOT) -> list[str]:
    """Every reason not to publish ``folder``; empty when it may be published. Reads the files as
    data only: nothing in them is run."""
    from expectrail import viewer

    problems: list[str] = []
    folder = Path(folder)
    if not valid_id(sample_id) or not valid_id(request_id):
        return ["the sample id or the request id is not a plain id"]
    if folder.is_symlink() or not folder.is_dir():
        return ["the output is not a folder"]
    files: dict[str, Path] = {}
    for here, dirs, names in os.walk(folder, followlinks=False):
        for name in list(dirs):
            p = Path(here) / name
            if p.is_symlink():
                problems.append(f"{p.relative_to(folder).as_posix()}: a link")
                dirs.remove(name)
        for name in names:
            p = Path(here) / name
            rel = p.relative_to(folder).as_posix()
            if p.is_symlink() or not p.is_file():
                problems.append(f"{rel}: not a plain file")
                continue
            allowed = rel in FIXED_FILES or (rel.startswith("viewer/") and viewer.FRAME_NAME.fullmatch(rel[len("viewer/"):]))
            if not allowed:
                problems.append(f"{rel}: not a file the site publishes")
                continue
            files[rel] = p
    if len(files) > MAX_FILES:
        problems.append(f"more than {MAX_FILES} files")
    total = 0
    for rel, p in files.items():
        size = p.stat().st_size
        total += size
        if size > MAX_FILE_BYTES:
            problems.append(f"{rel}: larger than {MAX_FILE_BYTES} bytes")
    if total > MAX_TOTAL_BYTES:
        problems.append(f"larger than {MAX_TOTAL_BYTES} bytes in all")
    if problems:
        return problems
    for need in ("status.json", "viewer/index.html"):
        if need not in files:
            problems.append(f"{need} is missing")
    for rel, p in files.items():
        data = p.read_bytes()
        if rel.endswith(".png"):
            if not data.startswith(PNG_SIGNATURE):
                problems.append(f"{rel}: not a PNG")
        elif rel.endswith(".json"):
            try:
                json.loads(data.decode("utf-8"), parse_constant=_no_constant)
            except (UnicodeDecodeError, ValueError):
                problems.append(f"{rel}: not JSON")
        elif rel.endswith(".html"):
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                problems.append(f"{rel}: not UTF-8")
                continue
            csp = f'<meta http-equiv="Content-Security-Policy" content="{viewer.CSP}">'
            if not text.lower().startswith("<!doctype html>") or csp not in text[:4096]:
                problems.append(f"{rel}: not the viewer's page (its Content-Security-Policy is not at the top)")
    if problems:
        return problems
    status = json.loads(files["status.json"].read_text(encoding="utf-8"))
    if files["status.json"].stat().st_size > MAX_STATUS_BYTES:
        problems.append("status.json is larger than its cap")
    found = rec.errors(status, _schema(root, RESULT_SCHEMA))
    if found:
        return problems + [f"status.json does not match its schema: {found[0]}"]
    if status["requestId"] != request_id:
        problems.append("status.json is for another request")
    if status["sample"]["id"] != sample_id:
        problems.append("status.json is for another sample")
    if (status["findings"] is not None) != ("findings.json" in files):
        problems.append("status.json and the folder disagree about findings.json")
    if status["decision"] is not None and status["phase"] != "completed":
        problems.append("status.json gives a decision for a job that did not complete")
    if "findings.json" in files:
        try:
            record = rec.read_record(files["findings.json"])
        except rec.RecordError as exc:
            problems.append(f"findings.json: {exc}")
        else:
            if status["decision"] is not None and record["decision"] != status["decision"]:
                # The job's decision is the one shown, and the viewer shows nothing as accepted
                # when the two disagree; the site publishes neither.
                problems.append("status.json and findings.json disagree about the decision")
    elif status["decision"] == "accept":
        problems.append("an accept with no findings record")
    return problems


def _no_constant(name: str):
    raise ValueError(f"{name} is not JSON")


# --- command line ----------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m expectrail.runit", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run", help="run one sample offline and write its folder")
    p_run.add_argument("--sample", required=True)
    p_run.add_argument("--out", required=True, type=Path)
    p_run.add_argument("--request-id", default=None)
    p_run.add_argument("--require-sandbox", action="store_true",
                       help="replay only inside the replay sandbox, or run nothing")
    p_run.add_argument("--expect", action="store_true",
                       help="exit 1 unless the decision is the one a working install gives today")
    p_check = sub.add_parser("check", help="check a folder before it is published")
    p_check.add_argument("folder", type=Path)
    p_check.add_argument("--sample", required=True)
    p_check.add_argument("--request-id", required=True)
    p_rec = sub.add_parser("record", help="the one live run per sample that records the vision answers (spends money)")
    p_rec.add_argument("--sample", required=True)
    p_rec.add_argument("--out", required=True, type=Path)
    p_rec.add_argument("--run", required=True, help="the recording run's id, written into the recording")
    p_rec.add_argument("--require-sandbox", action="store_true")
    p_chk = sub.add_parser("check-recording",
                           help="check a recording before it is proposed: its schema, its rules and its sample")
    p_chk.add_argument("file", type=Path)
    p_chk.add_argument("--sample", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            doc = run(args.sample, args.out, request_id=args.request_id, require_sandbox=args.require_sandbox)
            v = doc["vision"]
            print(f"{doc['sample']['title']}: {doc['decision'] or doc['phase']}"
                  + (f" (vision answers recorded on {v['recordedAt']})" if v["recorded"] else f" ({v['why']})"))
            for d in doc["diagnostics"]:
                print(f"    {d['code']}: {d['detail']}")
            print(f"receipt: {doc['receipt']['why']}")
            print(f"evidence: {args.out / doc['viewer']}")
            if args.expect and not doc["asExpected"]:
                print("NOT the decision a working install gives today", file=sys.stderr)
                return 1
            return 0
        if args.command == "check":
            problems = check(args.folder, sample_id=args.sample, request_id=args.request_id)
            for p in problems:
                print(f"refused: {p}", file=sys.stderr)
            if not problems:
                print("the folder may be published")
            return 1 if problems else 0
        if args.command == "check-recording":
            problems = check_recording(args.file, sample_id=args.sample)
            for p in problems:
                print(f"refused: {p}", file=sys.stderr)
            if not problems:
                doc = json.loads(args.file.read_text(encoding="utf-8"))
                print(f"the recording may be proposed: {len(doc['answers'])} answers for {doc['sample']}, "
                      f"recorded on {doc['recordedAt']}, run {doc['run']}")
            return 1 if problems else 0
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", args.run):
            raise RunItError("--run is letters, digits, dots, hyphens and underscores, at most 64")
        from agents.sam_observations import sam_usage

        before = sam_usage()
        try:
            path = record(args.sample, args.out, run_id=args.run, require_sandbox=args.require_sandbox)
        finally:
            # What was sent is printed whether or not the recording was written: money spent on a
            # failed recording is still spent.
            used = sam_usage()
            print(f"spend: ${used['reservedUsd'] - before['reservedUsd']:.4f} at list price, "
                  f"{used['requests'] - before['requests']} requests, "
                  f"{used['images'] - before['images']} images answered")
        print(f"recorded: {path}")
        return 0
    except RunItError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
