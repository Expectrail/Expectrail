"""The verification request (expectrail.verify-request/v1) and the digests the orchestrator takes itself.

A request names what to verify: the project's adapter, its game folder, routes and specs, a checkout
of the head and (when there is one) of the base, the execution class and the limits. It carries no
digest. The orchestrator computes them from the files (`inputs`): a client's claim about what the
files are is never used.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from expectrail.contracts import digest
from expectrail.gate import record as rec

FORMAT = "expectrail.verify-request/v1"
SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "contracts" / "verify-request.v1.schema.json"
EXECUTION_CLASSES = ("diagnostic", "isolated")
DEFAULT_TIMEOUT_SECONDS = 1800
MAX_REQUEST_BYTES = 64 * 1024


class RequestError(ValueError):
    """The request cannot be used. Nothing ran."""


def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def build(*, adapter: str, head: Path, game: str, routes: list[str], specs: str, base: Path | None = None,
          head_commit: str | None = None, base_commit: str | None = None, execution_class: str = "diagnostic",
          timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS, idempotency_key: str | None = None) -> dict:
    doc = {
        "format": FORMAT,
        "project": {"adapter": adapter, "game": game, "routes": [r for r in routes if str(r).strip()], "specs": specs},
        "head": {"checkout": str(Path(head).resolve()), "commit": head_commit},
        "base": None if base is None else {"checkout": str(Path(base).resolve()), "commit": base_commit},
        "executionClass": execution_class,
        "limits": {"timeoutSeconds": timeout_seconds},
        "idempotencyKey": idempotency_key,
    }
    check(doc)
    return doc


def check(doc) -> None:
    """Raise RequestError unless ``doc`` is a valid request."""
    try:
        rec.validate(doc, schema())
    except rec.RecordError as exc:
        raise RequestError(str(exc)) from exc
    for side in ("head", "base"):
        ref = doc[side]
        if ref is not None and not Path(ref["checkout"]).is_absolute():
            raise RequestError(f"{side}.checkout must be an absolute path")


def load(path: Path) -> dict:
    try:
        doc = rec.read_json(path, cap=MAX_REQUEST_BYTES, label="request.json")
    except rec.RecordError as exc:
        raise RequestError(str(exc)) from exc
    check(doc)
    return doc


def _files_digest(files: list[Path], root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(files, key=lambda p: p.relative_to(root).as_posix()):
        h.update(path.relative_to(root).as_posix().encode() + b"\0" + hashlib.sha256(path.read_bytes()).hexdigest().encode() + b"\n")
    return h.hexdigest()


def tree_digest(root: Path) -> str | None:
    """A digest of every file under ``root`` (version control and caches left out); None when the folder is not there."""
    if not root.is_dir():
        return None
    skip = {".godot", ".git", ".expectrail", "__pycache__"}
    return _files_digest([p for p in root.rglob("*") if p.is_file() and not skip & set(p.relative_to(root).parts)], root)


def policy_digest(checks_root: Path, project: dict) -> str | None:
    """A digest of the spec and route files that will judge the change, read from where the checks come
    from (the base when there is one). None when none can be read; the verifier then says so itself."""
    files: list[Path] = []
    specs = checks_root / project["specs"]
    if specs.is_dir():
        files += [p for p in specs.glob("*.json") if p.is_file()]
    for pattern in project["routes"]:
        files += [p for p in checks_root.glob(pattern) if p.is_file()]
    inside = [p for p in set(files) if checks_root.resolve() in p.resolve().parents]
    return _files_digest(inside, checks_root) if inside else None


def inputs(doc: dict) -> dict:
    """What the request resolves to right now, taken from the files. The idempotency check compares this."""
    head = Path(doc["head"]["checkout"])
    base = Path(doc["base"]["checkout"]) if doc["base"] is not None else None
    game = doc["project"]["game"]
    resolved = {
        "headTree": tree_digest(head / game),
        "baseTree": tree_digest(base / game) if base is not None else None,
        "policyDigest": policy_digest(base if base is not None else head, doc["project"]),
    }
    # The key itself is not part of what a request means, and neither is where the checkouts happen to be.
    meaning = {"project": doc["project"], "executionClass": doc["executionClass"], "limits": doc["limits"],
               "headCommit": doc["head"]["commit"], "baseCommit": doc["base"]["commit"] if doc["base"] else None,
               "hasBase": doc["base"] is not None, **resolved}
    return {"requestDigest": digest(meaning), **resolved}
