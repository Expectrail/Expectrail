"""The verification request (expectrail.verify-request/v1) and the digests the orchestrator takes itself.

A request names what to verify: the project's adapter, its game folder, routes and specs, a checkout
of the head and (when there is one) of the base, the execution class and the limits. It carries no
digest. The orchestrator computes them from the files (`inputs`): a client's claim about what the
files are is never used.

``headTree`` and ``baseTree`` describe what a replay reads. The harness copies the game folder into a
work folder, following links and leaving out only ``.godot`` (``harness.run.prepare``), so the digest
walks the same way and leaves out the same one name: there is no second list of folders to skip. For
a game with no links it is ``harness.run.tree_digest`` exactly: the same files in the same order. A link that leaves the checkout, or
that loops, is a problem with the input (``problems``): the copy would pull in a file from outside
what was asked to be verified.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
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
    """Raise RequestError unless ``doc`` is a valid request. Nothing the request names is opened:
    the paths are checked as text, by the rule the gate uses (``gate.verify.safe_relative``), so a
    game, a specs folder or a route pattern outside the checkout is refused before any file is read."""
    from expectrail.gate.verify import ConfigError, safe_relative

    found = rec.errors(doc, schema())
    if found:
        raise RequestError(f"the request does not match contracts/{SCHEMA_PATH.name}: {found[0]}"
                           + (f" (and {len(found) - 1} more)" if len(found) > 1 else ""))
    for side in ("head", "base"):
        ref = doc[side]
        if ref is not None and not Path(ref["checkout"]).is_absolute():
            raise RequestError(f"{side}.checkout must be an absolute path")
    project = doc["project"]
    try:
        safe_relative(project["game"], "project.game", root_ok=True)
        safe_relative(project["specs"], "project.specs")
        for pattern in project["routes"]:
            safe_relative(pattern, "a route pattern", glob=True)
    except ConfigError as exc:
        raise RequestError(str(exc)) from exc


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


class TreeProblem(ValueError):
    """The game folder cannot be described: a link in it leaves the checkout or loops."""


# The one name the harness's copy leaves out (harness.run.prepare, harness.run.tree_digest).
NOT_COPIED = ".godot"


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def tree_files(root: Path, checkout: Path) -> list[tuple[str, Path]]:
    """Every file a replay's copy of ``root`` would hold, as (path inside the game, file to read),
    sorted. Links are followed, as the copy follows them; one that leaves ``checkout`` or loops raises
    TreeProblem. Nothing outside ``checkout`` is opened."""
    limit = os.path.realpath(checkout)
    found: list[tuple[str, Path]] = []

    def walk(folder: str, inside: str, above: tuple[str, ...]) -> None:
        real = os.path.realpath(folder)
        if not _inside(real, limit):
            raise TreeProblem(f"{inside or '.'} is a link that leaves the checkout")
        if real in above:
            raise TreeProblem(f"{inside or '.'} is a link that loops back into its own folder")
        with os.scandir(folder) as entries:
            for entry in sorted(entries, key=lambda e: e.name):
                if entry.name == NOT_COPIED:
                    continue
                name = f"{inside}/{entry.name}" if inside else entry.name
                if entry.is_symlink() and not _inside(os.path.realpath(entry.path), limit):
                    raise TreeProblem(f"{name} is a link that leaves the checkout")
                if entry.is_dir():
                    walk(entry.path, name, above + (real,))
                elif entry.is_file():
                    found.append((name, Path(entry.path)))
                elif entry.is_symlink():
                    raise TreeProblem(f"{name} is a link to nothing")
                else:
                    # A pipe, a socket or a device: the copy would try to read it. Never left out quietly.
                    raise TreeProblem(f"{name} is not a file, a folder or a link")

    walk(str(root), "", ())
    # Part by part, as pathlib orders paths and so as the harness's digest does: "a/y" before "a-b/x".
    return sorted(found, key=lambda item: item[0].split("/"))


def tree_digest(root: Path, checkout: Path | None = None) -> str | None:
    """A digest of what a replay of the game at ``root`` reads; None when the folder is not there.
    Raises TreeProblem for a link that leaves ``checkout`` (default: ``root`` itself) or loops."""
    root = Path(root)
    if not root.is_dir():
        return None
    h = hashlib.sha256()
    for name, path in tree_files(root, root if checkout is None else checkout):
        h.update(name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).hexdigest().encode() + b"\n")
    return h.hexdigest()


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


def pattern_reaches(pattern: str, folder: str) -> bool:
    """Whether a route pattern could match a file somewhere below ``folder`` (both relative to the
    same checkout, with ``/``). Errs towards yes: it is used to keep the jobs folder out of where
    routes are looked for."""
    def reach(parts: list[str], below: list[str]) -> bool:
        if not below:
            return bool(parts)
        if not parts:
            return False
        if parts[0] == "**":
            return reach(parts[1:], below) or reach(parts, below[1:])
        return fnmatch.fnmatchcase(below[0], parts[0]) and reach(parts[1:], below[1:])

    return reach([p for p in pattern.split("/") if p not in ("", ".")], [p for p in folder.split("/") if p not in ("", ".")])


def _trees(doc: dict) -> tuple[dict, list[str]]:
    head = Path(doc["head"]["checkout"])
    base = Path(doc["base"]["checkout"]) if doc["base"] is not None else None
    game = doc["project"]["game"]
    trees: dict = {"headTree": None, "baseTree": None}
    found: list[str] = []
    for key, checkout in (("headTree", head), ("baseTree", base)):
        if checkout is None:
            continue
        try:
            trees[key] = tree_digest(checkout / game, checkout)
        except TreeProblem as exc:
            # Named, never hashed and never skipped: the tree stays null, the worker refuses the job
            # on the reason (`problems`), and the reason is part of what the request means.
            found.append(f"the {'head' if key == 'headTree' else 'base'} game cannot be verified as it stands: {exc}")
    return trees, found


def problems(doc: dict) -> list[str]:
    """What in the files the request names stops a verification before it starts. The worker turns
    each into INPUT_INVALID, so the job completes as needs-review with the reason and nothing runs."""
    return _trees(doc)[1]


def inputs(doc: dict) -> dict:
    """What the request resolves to right now, taken from the files. The idempotency check compares this."""
    check(doc)  # nothing below may open a path the request should not have named
    head = Path(doc["head"]["checkout"])
    base = Path(doc["base"]["checkout"]) if doc["base"] is not None else None
    trees, found = _trees(doc)
    resolved = {**trees, "policyDigest": policy_digest(base if base is not None else head, doc["project"])}
    # The key itself is not part of what a request means, and neither is where the checkouts happen to be.
    meaning = {"project": doc["project"], "executionClass": doc["executionClass"], "limits": doc["limits"],
               "headCommit": doc["head"]["commit"], "baseCommit": doc["base"]["commit"] if doc["base"] else None,
               "hasBase": doc["base"] is not None, **resolved, **({"problems": found} if found else {})}
    return {"requestDigest": digest(meaning), **resolved}
