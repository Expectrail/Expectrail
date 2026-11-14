"""The verification request (expectrail.verify-request/v1) and the digests the orchestrator takes itself.

A request names what to verify: the project's adapter, its game folder, routes and specs, a checkout
of the head and (when there is one) of the base, the execution class and the limits. It carries no
digest. The orchestrator computes them from the files (`inputs`): a client's claim about what the
files are is never used.

``headTree`` and ``baseTree`` describe what a replay reads. They come from ``harness.tree``, the one
walk every digest of a game and every copy a replay runs is made from: links are followed, ``.godot``
and ``.git`` are not part of a game, and there is no other list of folders to skip. A link that leaves
the checkout, loops or leads nowhere, and anything that is not a file, a folder or a link, is a
problem with the input (``problems``): never hashed and never left out quietly.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from harness import tree

from expectrail import resources
from expectrail.contracts import digest
from expectrail.gate import record as rec

FORMAT = "expectrail.verify-request/v1"
SCHEMA_PATH = resources.ROOT / "contracts" / "verify-request.v1.schema.json"
EXECUTION_CLASSES = ("diagnostic", "isolated")
DEFAULT_TIMEOUT_SECONDS = 1800
MAX_REQUEST_BYTES = 64 * 1024


class RequestError(ValueError):
    """The request cannot be used. Nothing ran."""


def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def build(*, adapter: str, head: Path, game: str, routes: list[str], specs: str, base: Path | None = None,
          head_commit: str | None = None, base_commit: str | None = None, execution_class: str = "diagnostic",
          timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS, idempotency_key: str | None = None, intent: str | None = None) -> dict:
    doc = {
        "format": FORMAT,
        **({"intent": intent} if intent is not None else {}),
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


# The walk is the harness's (harness.tree): the one definition of what a game folder holds.
TreeProblem = tree.TreeProblem


def engine_folders(adapter: str | None = None) -> tuple[str, ...]:
    """The folders the engine writes for itself, which are no part of a game: the adapter's own list
    (``harness.adapters``, ``ignore``), so a job's trees are taken the way the gate and the replay
    take them. Without a name it is Godot's, as before requests named an adapter here. A name the
    registry does not hold leaves nothing out: that job is refused before anything runs, and until
    then its digest covers every file."""
    if adapter is None:
        return tree.GODOT_SKIP
    from harness import adapters

    try:
        return tuple(adapters.get(adapter).ignore)
    except KeyError:
        return ()


def tree_files(root: Path, checkout: Path, adapter: str | None = None) -> list[tuple[str, Path]]:
    """Every file a replay's copy of ``root`` holds, as (path inside the game, file to read), sorted:
    ``harness.tree.files`` with the checkout as the folder a link may lead into."""
    return tree.files(root, within=checkout, skip=engine_folders(adapter))


def tree_digest(root: Path, checkout: Path | None = None, adapter: str | None = None) -> str | None:
    """A digest of what a replay of the game at ``root`` reads; None when the folder is not there.
    Raises TreeProblem for a link that leaves ``checkout`` (default: ``root`` itself) or loops."""
    root = Path(root)
    if not root.is_dir():
        return None
    return tree.digest(root, within=checkout, skip=engine_folders(adapter))


def read_checks(doc: dict):
    """The checks that will judge the change, read once by the gate's own reader
    (``expectrail.gate.verify.read_checks``), from where they come from: the base when there is one."""
    from expectrail.gate import verify as gate

    checks_root = Path(doc["base"]["checkout"]) if doc["base"] is not None else Path(doc["head"]["checkout"])
    return gate.read_checks(checks_root.resolve(), doc["project"]["specs"], doc["project"]["routes"],
                            "base" if doc["base"] is not None else "head")


def policy_digest(checks_root: Path, project: dict) -> str | None:
    """A digest of the spec and route files that will judge the change, as the gate's reader reads
    them (``expectrail.gate.verify.read_checks``): no link is followed, and a file it refuses is in
    the digest as refused. None when there is no spec file and no route file; the verifier then
    says so itself."""
    from expectrail.gate import verify as gate

    return gate.read_checks(Path(checks_root).resolve(), project["specs"], project["routes"]).digest


def pattern_reaches(pattern: str, folder: str) -> bool:
    """Whether a route pattern could match a file somewhere below ``folder`` (both relative to the
    same checkout, with ``/``). Errs towards yes: it is used to keep the jobs folder out of where
    routes are looked for. The gate's matcher (``gate.verify.pattern_matches``) compares names as
    written, case included; here they are also compared without regard to case, kept from when
    ``Path.glob`` found the routes and ``RUNS/**`` did reach ``runs/jobs`` on a file system that
    ignores case. It can only add a yes."""
    from expectrail.gate import verify as gate

    def reach(parts: list[str], below: list[str]) -> bool:
        if not below:
            return bool(parts)
        if not parts:
            return False
        if parts[0] == "**":
            return reach(parts[1:], below) or reach(parts, below[1:])
        # The gate's own comparison of one name (the matcher that finds the routes uses the same
        # one), or that comparison without regard to case: the second is added to the first, never
        # in its place, because folding a pattern's case changes what a range such as [S-s] holds.
        return ((gate.segment_matches(below[0], parts[0])
                 or gate.segment_matches(below[0].casefold(), parts[0].casefold()))
                and reach(parts[1:], below[1:]))

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
            trees[key] = tree_digest(checkout / game, checkout, doc["project"]["adapter"])
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
    if "intent" in doc:
        meaning["intent"] = doc["intent"]
    return {"requestDigest": digest(meaning), **resolved}
