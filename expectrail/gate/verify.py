"""The CI gate's verify step: replay a pull request's game on its routes, judge every approved spec,
and write the evidence the comment step reads.

    python3 -m expectrail.gate.verify --repo . --game game --routes 'tests/routes/*.json' \\
        --specs tests/specs --out runs/gate [--work runs/gate-work] [--base .expectrail/base] \\
        [--heldout DIR] [--pr 12 --head-sha SHA --base-sha SHA] [--expectrail-commit SHA]

This runs in the job that runs the pull request's code, with read-only permissions. It writes, in
``--out`` (the artifact):

- ``findings.json`` (expectrail.findings/v0): the decision, every check, and one finding per check
  that does not pass after the change, each with an id that stays the same across pushes;
- ``verdicts/head/<route>/<spec>.json`` and ``verdicts/base/...``: the evaluator's verdicts;
- ``review/index.html``: the review page, with the first failing frame before and after.

With ``--base`` (a checkout of the pull request's base commit) the specs and routes are read from
the base, so a change cannot edit the checks that judge it, and the base game is replayed too, so
each check gets a comparison (REPAIRED, PRESERVED, REGRESSION, UNRESOLVED or INCONCLUSIVE). Without
it, the head's own checks are used and the record says so.

Only specs with a person's approval judge a change. The evaluator decides each spec on the engine's
position log (``agents.observations.from_trace_synthetic``): no model key is used, and a spec about
an object the log does not hold (anything but the player and the ground) needs review.

``--heldout`` points at a checkout of private routes (``manifest.json`` listing ``routes[].file``).
They are replayed on the head without frames, every spec is judged on each, and only counts leave:
no route name, file, frame or reason is written or printed. Their run folders are deleted.

Exit 0 accept, 1 reject, 2 needs review (as ``agents.review_change``); 3 if no record could be
written at all.
"""
from __future__ import annotations

import argparse
import fnmatch
import functools
import json
import os
import re
import shutil
import sys
import tempfile
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

from expectrail import resources
from expectrail import __version__
from expectrail.contracts import digest
from expectrail.gate import record as rec
from expectrail.gate.page import write_page

EXPECTRAIL_ROOT = resources.ROOT
CONTRACTS = EXPECTRAIL_ROOT / "contracts"
EXIT = {"accept": 0, "reject": 1, "needs-review": 2}
MAX_SPECS = 64
MAX_ROUTES = 64
MAX_REASONS = 20
MAX_UNLISTED = 5   # folders that cannot be listed, named one by one in the reasons
MAX_REASON = 300
SPEC_CAP = 256 * 1024
ROUTE_CAP = 1024 * 1024
# A path a workflow passes in: relative, forward slashes, no "..", no leading dash. Glob characters
# are allowed in route patterns only.
SAFE_PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._/-]*")
SAFE_GLOB = re.compile(r"[A-Za-z0-9_*?\[][A-Za-z0-9._/*?\[\]-]*")
SHA40 = re.compile(r"[0-9a-f]{40}")

# (route file, game folder, run folder, capture frames) -> {"trace", "replaySha256", "framesDir"}, and
# "isolation": the replay's own account of what the game could reach (replay.json's block), when it has one.
Replay = Callable[[Path, Path, Path, bool], dict]


class ConfigError(ValueError):
    """An input the workflow gave cannot be used."""


def harness_replay(route: Path, game: Path, out: Path, frames: bool, sandbox: str | None = None,
                   checkouts: tuple[Path, ...] = ()) -> dict:
    """One replay through the Godot harness (``harness.run``), which gives Godot only the display
    and rendering variables from the environment and runs it in the replay sandbox where the
    machine can (``sandbox``: auto, require or off; default $EXPECTRAIL_SANDBOX, else auto).
    ``checkouts`` are the folders a link in a game may lead into: the one that holds ``game``
    is used, and without one a link may not leave the game folder."""
    from harness.run import run, sha256_file

    replay = run(route, out, game=game, capture_frames=frames, sandbox=sandbox, within=_checkout_of(game, checkouts))
    trace = json.loads((out / "trace.json").read_text(encoding="utf-8"))
    return {"trace": trace, "replaySha256": sha256_file(out / "replay.json"),
            "framesDir": (out / "frames") if frames else None, "isolation": replay.get("isolation"),
            # The digest of the copy this replay ran (harness.tree.copy), for the gate to hold
            # against the tree its record names.
            "tree": replay["game"]["tree"]}


def observations(trace: dict, replay_sha256: str) -> dict:
    """The engine's position log as observations; never SAM, whatever the environment says."""
    from agents.observations import from_trace_synthetic

    return from_trace_synthetic(trace, replay_sha256=replay_sha256)


def evaluate(spec: dict, obs: dict) -> dict:
    from expectrail.evaluator import evaluate as _evaluate

    return _evaluate(spec, obs)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clip(text: str, limit: int = MAX_REASON) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def safe_relative(text: str, what: str, *, glob: bool = False, root_ok: bool = False) -> str:
    """A repository-relative path from the workflow: no absolute path, no '..', no backslash."""
    value = str(text).strip() if text is not None else ""
    if root_ok and value in (".", "./"):
        return "."
    if value.startswith("/"):
        raise ConfigError(f"{what} must be relative to the repository, not an absolute path")
    value = value.rstrip("/")
    pattern = SAFE_GLOB if glob else SAFE_PATH
    parts = PurePosixPath(value).parts if value else ()
    if not value or not pattern.fullmatch(value) or ".." in parts or len(value) > 200:
        raise ConfigError(f"{what} must be a path inside the repository (letters, digits, . _ - /"
                          + (", * ? [ ]" if glob else "") + "; no '..')")
    return value


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def segment_matches(name: str, part: str) -> bool:
    """Whether one name matches one part of a route pattern (`*`, `?`, `[...]`), as written: the
    case of the name counts on every file system."""
    return fnmatch.fnmatchcase(name, part)


def pattern_matches(root: Path, pattern: str, unlisted: set[Path] | None = None) -> set[Path]:
    """Every path below ``root`` that a route pattern names. The gate's own matcher, so the files
    that judge a change are the same on every Python: ``Path.glob`` gives a pattern that ends in
    ``**`` the files below on Python 3.13 and none of them on 3.12.

    The rules, part by part between the slashes:

    - ``**`` alone stands for no folder or any number of them, and as the last part for everything
      below as well. It never passes through a link to a folder.
    - Any other part matches one name with ``segment_matches``. Such a part may name a link to a
      folder and continue below it (the caller keeps a file only when it is inside the checkout).
    - A folder that cannot be listed is never passed over in silence. A part that is a plain name
      (no ``*``, ``?`` or ``[``) needs no listing: the one name is tried, so a route named in full
      is found in a folder that can be entered but not listed. Any other part, and ``**``, cannot
      know what is there: the folder is added to ``unlisted``, for the caller to report.
    """
    parts = [p for p in pattern.split("/") if p not in ("", ".")]
    found: set[Path] = set()
    if not parts:
        return found

    def listing(folder: str) -> list[os.DirEntry] | None:
        try:
            with os.scandir(folder) as entries:
                return sorted(entries, key=lambda e: e.name)
        except OSError:
            return None

    def listed(folder: str) -> list[os.DirEntry]:
        entries = listing(folder)
        if entries is None:
            if unlisted is not None:
                unlisted.add(Path(folder))
            return []
        return entries

    def is_folder(entry: os.DirEntry, through_links: bool) -> bool:
        try:
            return entry.is_dir(follow_symlinks=through_links)
        except OSError:
            return False

    # A list of work, not recursion: a checkout may nest folders deeper than Python nests calls.
    seen: set[tuple[str, int]] = set()
    work: list[tuple[str, int]] = [(str(root), 0)]
    last = len(parts) - 1
    while work:
        at = work.pop()
        if at in seen:
            continue
        seen.add(at)
        folder, i = at
        if i > last:  # only after a last "**": everything below, and no link to a folder is entered
            for entry in listed(folder):
                found.add(Path(entry.path))
                if is_folder(entry, False):
                    work.append((entry.path, i))
        elif parts[i] == "**":
            work.append((folder, i + 1))
            work.extend((entry.path, i) for entry in listed(folder) if is_folder(entry, False))
        else:
            entries = listing(folder)
            if entries is None:
                if any(c in parts[i] for c in "*?["):
                    listed(folder)  # recorded: what the part matches in there cannot be known
                    continue
                # A plain name in a folder that cannot be listed: go to the name. (Here the file
                # system compares the name, so one that ignores case ignores it for this part.)
                named = os.path.join(folder, parts[i])
                if i == last:
                    if os.path.lexists(named):
                        found.add(Path(named))
                elif os.path.isdir(named):
                    work.append((named, i + 1))
                continue
            for entry in entries:
                if not segment_matches(entry.name, parts[i]):
                    continue
                if i == last:
                    found.add(Path(entry.path))
                elif is_folder(entry, True):
                    work.append((entry.path, i + 1))
    return found


def match_routes(root: Path, patterns: list[str],
                 unlisted: set[Path] | None = None) -> tuple[list[Path], list[Path], list[Path]]:
    """What the patterns name, in three lists: the route files (regular files inside the checkout),
    the links to a file, and the files that are outside the checkout (reached through a link that
    leaves it). The last two are never read as routes; they are given back so the caller can say
    so, because a file the job named as a route and the gate left out is a check that did not run.
    A folder, a link to a folder or to nothing, and anything that is not a file are no route file.
    Folders that could not be listed while looking are added to ``unlisted``."""
    files: set[Path] = set()
    links: set[Path] = set()
    outside: set[Path] = set()
    for pattern in patterns:
        for match in pattern_matches(root, pattern, unlisted):
            if not match.is_file():
                continue
            if match.is_symlink():
                links.add(match)
            elif not _inside(root, match):
                outside.add(match)
            else:
                files.add(match)
    return sorted(files), sorted(links), sorted(outside)


def find_routes(root: Path, patterns: list[str], unlisted: set[Path] | None = None) -> list[Path]:
    """The route files the patterns name: regular files inside the checkout, never a link."""
    return match_routes(root, patterns, unlisted)[0]


def spec_files(folder: Path) -> list[Path]:
    """The spec files of a specs folder that is a real folder: every *.json that is a file, or a
    link to one. (A link is listed and then refused by the reader, with the reason; it is never
    followed to be read.)"""
    if not folder.is_dir() or folder.is_symlink():
        return []
    return sorted(p for p in folder.glob("*.json") if p.is_file())


def _schema(kind: str) -> dict:
    return json.loads((CONTRACTS / f"{kind}.schema.json").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Checks:
    """The checks that judge a change, read once.

    Everything the gate knows about its specs and routes comes from this one reading: the approved
    specs, the routes as the bytes that were read (replays run copies made from those bytes, not
    the checkout's files again), what could not be used and why, and a digest of all of it. A
    caller that must know the checks did not change (a verification job) reads them with
    ``read_checks``, compares the digest, and hands the same object to ``run_gate``: one reader and
    one source, so there is no second reading to hold against the first."""
    specs: list
    drafts: int
    problems: list
    routes: list            # [(name, the file's bytes, sha256)], sorted by name
    found_routes: bool      # whether any route file matched at all
    spec_entries: dict      # path inside the checkout -> what the digest holds for it, for every spec
                            # file listed: the sha256 of the bytes read, or `refused: <the reason>`
    route_entries: dict     # the same for every route file listed
    digest: str | None      # None when there is no spec file and no route file


def _parse(data: bytes, label: str):
    """``rec.read_json``'s parsing, for bytes already read."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise rec.RecordError(f"{label} is not UTF-8") from None
    return rec.strict_loads(text)


def read_checks(root: Path, specs: str, patterns: list[str], checks_from: str = "head") -> Checks:
    """Read the spec and route files of the checkout ``root``, each once, with the gate's reader
    (``rec.read_bytes_capped``: no link followed, a size cap).

    The digest covers every file listed, in path order: its path, a NUL, then the sha256 of the
    bytes that were read, or ``refused:`` and the reader's reason for a file it would not read (a
    link, a file over the cap). So a spec that is a link is in the digest by its name and the fact
    that it was refused, never by what it leads to, which is not opened."""
    import hashlib

    problems: list[str] = []
    spec_entries: dict[str, str] = {}
    route_entries: dict[str, str] = {}

    def read(path: Path, cap: int, label: str, entries: dict) -> bytes:
        name = path.relative_to(root).as_posix()
        try:
            data = rec.read_bytes_capped(path, cap, label)
        except rec.RecordError as exc:
            entries[name] = f"refused: {exc}"
            raise
        entries[name] = hashlib.sha256(data).hexdigest()
        return data

    # Specs: (approved specs, drafts, problems) from every *.json in the folder.
    folder = root / specs
    spec_problems: list[str] = []
    approved: list[dict] = []
    drafts = 0
    if not folder.is_dir() or folder.is_symlink():
        spec_problems.append(f"no specs folder at {specs} ({checks_from})")
    else:
        schema = _schema("test-spec")
        for path in spec_files(folder):
            try:
                doc = _parse(read(path, SPEC_CAP, path.name, spec_entries), path.name)
            except rec.RecordError as exc:
                spec_problems.append(f"spec {path.name}: {exc}")
                continue
            found = rec.errors(doc, schema)
            if found:
                spec_problems.append(f"spec {path.name} is not a valid test spec: {found[0]}")
            elif not doc.get("approval"):
                drafts += 1  # a draft never judges a change: a person approves every spec first
            else:
                approved.append(doc)
        ids = [s["id"] for s in approved]
        twice = sorted({i for i in ids if ids.count(i) > 1})
        if twice:
            spec_problems.append(f"spec id(s) {', '.join(twice)} appear in more than one file")
            approved = [s for s in approved if s["id"] not in twice]
        if len(approved) > MAX_SPECS:
            spec_problems.append(f"{len(approved)} approved specs, over the gate's limit of {MAX_SPECS}")
            approved = []

    # Routes: [(name, bytes, sha256)] and problems, from every file the patterns name.
    unlisted: set[Path] = set()
    route_files, route_links, route_outside = match_routes(root, patterns, unlisted)
    if not (route_files or route_links or route_outside):
        problems.append(f"no route files match {', '.join(patterns)} ({checks_from})")
    # Never silence: a route in a folder the gate could not list would judge nothing and nobody
    # would know. Named in the problems, which keep the result from an accept (#340).
    for folder in sorted(unlisted)[:MAX_UNLISTED]:
        shown = folder.relative_to(root).as_posix() if folder != root else "(the checkout itself)"
        problems.append(f"cannot list the folder {shown} while looking for routes ({checks_from})")
    if len(unlisted) > MAX_UNLISTED:
        problems.append(f"and {len(unlisted) - MAX_UNLISTED} more folders that cannot be listed ({checks_from})")
    route_problems: list[str] = []
    routes: list[tuple[str, bytes, str]] = []
    schema = _schema("route")
    # A file the patterns name that is outside the checkout is never opened. It is listed by its
    # name and the refusal, as a spec that is a link is: a check the job named did not run.
    for path in route_outside:
        shown = path.relative_to(root).as_posix()
        route_entries[shown] = "refused: outside the checkout"
        route_problems.append(f"route {shown}: it is outside the checkout (reached through a link) and is not read")
    # A link to a file goes to the reader with the route files, and the reader refuses it.
    for path in sorted(route_files + route_links):
        shown = path.relative_to(root).as_posix()
        try:
            data = read(path, ROUTE_CAP, shown, route_entries)
            doc = _parse(data, shown)
        except rec.RecordError as exc:
            route_problems.append(f"route {shown}: {exc}")
            continue
        found = rec.errors(doc, schema)
        if found:
            route_problems.append(f"route {shown} is not a valid route: {found[0]}")
            continue
        routes.append((doc["name"], data, hashlib.sha256(data).hexdigest()))
    names = [r[0] for r in routes]
    twice = sorted({n for n in names if names.count(n) > 1})
    if twice:
        route_problems.append(f"route name(s) {', '.join(twice)} appear in more than one file")
        routes = [r for r in routes if r[0] not in twice]
    if len(routes) > MAX_ROUTES:
        route_problems.append(f"{len(routes)} routes, over the gate's limit of {MAX_ROUTES}")
        routes = []

    listed = {**route_entries, **spec_entries}
    h = hashlib.sha256()
    for name in sorted(listed):
        h.update(name.encode() + b"\0" + listed[name].encode() + b"\n")
    return Checks(specs=sorted(approved, key=lambda s: s["id"]), drafts=drafts,
                  problems=problems + spec_problems + route_problems, routes=sorted(routes),
                  found_routes=bool(route_files or route_links or route_outside), spec_entries=spec_entries,
                  route_entries=route_entries,
                  digest=h.hexdigest() if listed else None)


def changed_count(head: dict, base: dict) -> int:
    """How many names differ between two listings of check files (``Checks.spec_entries`` or
    ``route_entries``): added, removed, or with another entry."""
    return sum(1 for name in set(head) | set(base) if head.get(name) != base.get(name))


def judge_arm(game: Path, routes: list[tuple[str, Path, str]], specs: list[dict], out: Path,
              replay: Replay, *, label: str) -> dict[tuple[str, str], dict]:
    """{(spec id, route name): result} for one game tree."""
    results: dict[tuple[str, str], dict] = {}
    for name, path, _sha in routes:
        try:
            run = replay(path, game, out / name, True)
            obs = observations(run["trace"], run["replaySha256"])
        except (Exception, SystemExit) as exc:  # noqa: BLE001 - the harness exits on a failed replay
            # The gate's own sentence when it is the gate that refused the replay; otherwise only the
            # kind of error, since a message could carry text from the game.
            why = f"the {label} game changed while it was being verified" if isinstance(exc, GameChanged) \
                else f"the {label} replay did not finish ({type(exc).__name__})"
            print(f"::warning title=Expectrail gate::route {name}: {why}")
            for spec in specs:
                results[(spec["id"], name)] = {"result": "replay-error", "verdict": None, "frame": None,
                                               "framesDir": None, "reason": why}
            continue
        for spec in specs:
            try:
                verdict = evaluate(spec, obs)
            except Exception as exc:  # noqa: BLE001 - a crash is recorded, never read as a pass
                results[(spec["id"], name)] = {"result": "needs-review", "verdict": None, "frame": None,
                                               "framesDir": None,
                                               "reason": f"the evaluator stopped ({type(exc).__name__})"}
                continue
            results[(spec["id"], name)] = {"result": verdict["result"], "verdict": verdict,
                                           "reason": verdict["reason"], "frame": verdict.get("firstFrame"),
                                           "framesDir": run.get("framesDir")}
    return results


class GameChanged(RuntimeError):
    """A replay ran a game other than the one the record names: the folder changed after the gate
    read it. The replay's result is not used."""


HELD_ZERO = {"routes": 0, "checks": 0, "passed": 0, "failed": 0, "needsReview": 0}


def judge_heldout(root: Path | None, game: Path, specs: list[dict], replay: Replay) -> dict:
    """Counts only. Nothing from the held-out set is printed, returned or left on disk."""
    if root is None:
        return {"status": "not-used", **HELD_ZERO}
    try:
        manifest = rec.read_json(root / "manifest.json", ROUTE_CAP, "the held-out manifest")
        entries = manifest["routes"]
        if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ROUTES:
            raise ValueError("bad route list")
        schema, paths = _schema("route"), []
        for entry in entries:
            path = root / str(entry["file"])
            if not path.is_file() or path.is_symlink() or not _inside(root, path):
                raise ValueError("missing route")
            if rec.errors(rec.read_json(path, ROUTE_CAP, "a held-out route"), schema):
                raise ValueError("invalid route")
            paths.append(path)
    except Exception:  # noqa: BLE001 - why it failed could name a route, so it is not said
        print("::warning title=Expectrail gate::the held-out routes could not be read (counts only, no detail)")
        return {"status": "unavailable", **HELD_ZERO}
    counts = dict(HELD_ZERO, routes=len(paths))
    scratch = Path(tempfile.mkdtemp(prefix="expectrail-heldout-runs-"))
    try:
        for n, path in enumerate(paths):
            try:
                run = replay(path, game, scratch / f"r{n:02d}", False)
                obs = observations(run["trace"], run["replaySha256"])
                results = []
                for spec in specs:
                    try:
                        results.append(evaluate(spec, obs)["result"])
                    except Exception:  # noqa: BLE001
                        results.append("needs-review")
            except (Exception, SystemExit):  # noqa: BLE001
                results = ["needs-review"] * len(specs)
            counts["checks"] += len(results)
            counts["passed"] += results.count("pass")
            counts["failed"] += results.count("fail")
            counts["needsReview"] += len(results) - results.count("pass") - results.count("fail")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return {"status": "judged", **counts}


def _checkout_of(game: Path, checkouts: tuple[Path, ...]) -> Path | None:
    game = Path(game).resolve()
    return next((c for c in (Path(c).resolve() for c in checkouts) if c == game or c in game.parents), None)


def game_tree(root: Path, within: Path | None = None) -> str:
    """The digest of the game the record names: ``harness.run.tree_digest``, which is taken over the
    files a replay's copy holds (``harness.tree``). The same function writes replay.json's
    ``game.tree``, so the record and its replays name a tree the same way. Raises
    ``harness.tree.TreeProblem`` for a link that leaves ``within``, loops or leads nowhere."""
    from harness.run import tree_digest

    return tree_digest(root, within)


def _game_ok(game: Path) -> bool:
    return game.is_dir() and (game / "project.godot").is_file()


def run_gate(*, repo: Path, game: str, routes: list[str], specs: str, out: Path, work: Path,
             base: Path | None = None, heldout: Path | None = None, pr: dict | None = None,
             expectrail_commit: str | None = None, replay: Replay = harness_replay,
             generated_checks: Path | None = None, require_sandbox: bool = False,
             checks: Checks | None = None) -> dict:
    """Run the gate and write the artifact in ``out``; returns the findings record.

    ``checks`` is the checks as a caller has already read them (``read_checks``). The gate then
    judges with exactly those and reads no spec or route file itself. Without it the gate reads them
    here, once. Either way each replay is given a copy of its route made from the bytes that were
    read, so the route a replay plays is the route the record names.

    ``require_sandbox`` refuses to replay the game outside the replay sandbox: where the machine
    cannot provide it nothing is replayed (ConfigError), and a replay that ran outside it anyway
    keeps the decision from being accept. Without it the game is sandboxed where possible, and the
    record's ``isolation`` block says how many replays were.

    ``generated_checks`` is the advisory block a check-generation step wrote (docs/jit.md). It is read
    as untrusted data after the decision is made, and nothing in it can change the decision."""
    repo = repo.resolve()
    problems: list[str] = []
    if require_sandbox and replay is harness_replay:
        from harness import sandbox as box

        tool, why = box.probe(True)
        if tool is None:
            raise ConfigError(f"the replay sandbox is required and this machine cannot provide it: {why}")
        replay = functools.partial(harness_replay, sandbox="require")
    if getattr(replay, "func", replay) is harness_replay:
        # A link in a game may lead anywhere inside its own checkout, and nowhere else.
        replay = functools.partial(replay, checkouts=tuple(c for c in (repo, base) if c is not None))
    accounts: list = []   # each finished replay's own account of its isolation
    named: dict[Path, str] = {}   # game folder -> the tree the record names for it (filled below)
    one_replay = replay

    def replay(route: Path, game: Path, out: Path, frames: bool) -> dict:  # noqa: F811 - the same call, recorded
        run = one_replay(route, game, out, frames)
        accounts.append(run.get("isolation"))
        # The harness says which tree its copy was made from. The record names one tree per side,
        # read once before any replay: a replay of anything else is not a replay of that game.
        ran, want = run.get("tree"), named.get(Path(game))
        if ran is not None and want is not None and ran != want:
            raise GameChanged(f"the replay ran tree {ran[:12]}, the record names {want[:12]}")
        return run

    game_rel = safe_relative(game, "game-path", root_ok=True)
    specs_rel = safe_relative(specs, "specs")
    patterns = [safe_relative(p, "routes", glob=True) for p in routes if str(p).strip()]
    if not patterns:
        raise ConfigError("routes must name at least one route file or glob")
    checks_root = base.resolve() if base is not None else repo
    checks_from = "base" if base is not None else "head"

    if checks is None:
        checks = read_checks(checks_root, specs_rel, patterns, checks_from)
    spec_docs, drafts = checks.specs, checks.drafts
    problems += checks.problems
    # The replays play copies of the routes made from the bytes that were read (written below, once
    # the work folder is known not to be inside a game): the checkout's route files are not opened again.
    routes_dir = Path(work) / "checks" / "routes"
    route_list = [(name, routes_dir / f"{name}.json", sha) for name, _data, sha in checks.routes]
    changed = {"specs": 0, "routes": 0}
    if base is not None:
        # What the change does to the check files, counted from one kind of reading on both sides:
        # the head's checks are listed by the same reader as the base's. A file the reader refuses
        # compares by its name and its refusal, so one that is the same on both sides is not counted
        # and one that the change removes is. (The head's checks judge nothing here.)
        mine = read_checks(repo, specs_rel, patterns, "head")
        changed["specs"] = changed_count(mine.spec_entries, checks.spec_entries)
        changed["routes"] = changed_count(mine.route_entries, checks.route_entries)

    head_game = repo / game_rel
    base_game = (checks_root / game_rel) if base is not None else None
    if not _game_ok(head_game):
        problems.append(f"no Godot project (project.godot) at {game_rel}")
        route_list_for_head: list = []
    else:
        route_list_for_head = route_list
    if base_game is not None and not _game_ok(base_game):
        problems.append(f"the base commit has no Godot project at {game_rel}, so nothing is compared")
        base_game = None
    # The trees are taken now, before anything is copied or replayed, by the walk the replay's copy
    # uses. A game that cannot be described (a link that leaves its checkout, loops or leads nowhere)
    # is not replayed, and neither is one that holds the gate's own output: its copy would hold itself.
    from harness.tree import TreeProblem

    trees: dict = {"head": None, "base": None}
    for side, folder, checkout in (("head", head_game if _game_ok(head_game) else None, repo), ("base", base_game, base)):
        if folder is None:
            continue
        for label, place in (("output", out), ("work", work)):
            place = Path(place).resolve()
            if place == folder.resolve() or folder.resolve() in place.parents:
                raise ConfigError(f"the {label} folder is inside the {side} game folder ({game_rel}); keep it outside the game")
        try:
            trees[side] = game_tree(folder, checkout)
        except TreeProblem as exc:
            raise ConfigError(f"the {side} game cannot be verified as it stands: {exc}") from exc
        named[Path(folder)] = trees[side]
    shutil.rmtree(routes_dir, ignore_errors=True)
    routes_dir.mkdir(parents=True)
    for name, data, _sha in checks.routes:
        (routes_dir / f"{name}.json").write_bytes(data)

    head = judge_arm(head_game, route_list_for_head, spec_docs, work / "head", replay, label="head") \
        if route_list_for_head and spec_docs else {}
    before = judge_arm(base_game, route_list, spec_docs, work / "base", replay, label="base") \
        if base_game is not None and route_list_for_head and spec_docs else {}
    if heldout is None or not spec_docs:
        held = {"status": "not-used", **HELD_ZERO}
    elif not _game_ok(head_game):
        held = {"status": "unavailable", **HELD_ZERO}
    else:
        held = judge_heldout(heldout.resolve(), head_game, spec_docs, replay)

    checks, findings, frames = [], [], {}
    for name, _path, _sha in route_list if head else []:
        for spec in spec_docs:
            key = (spec["id"], name)
            after = head[key]
            prior = before.get(key)
            b = prior["result"] if prior else None
            kind = rec.kind_of(after["result"])
            fid = rec.finding_id(spec["id"], name, kind) if kind else None
            row = {"spec": spec["id"], "route": name, "before": b, "after": after["result"],
                   "comparison": rec.compare(b, after["result"]), "findingId": fid}
            checks.append(row)
            if fid:
                frame = after["frame"] if isinstance(after["frame"], int) and after["frame"] >= 0 else None
                findings.append({"id": fid, "spec": spec["id"], "route": name, "kind": kind, "before": b,
                                 "after": after["result"], "comparison": row["comparison"],
                                 "reason": _clip(after["reason"]), "frame": frame})
                frames[fid] = {"after": (after["framesDir"], frame),
                               "before": ((prior or {}).get("framesDir"), frame)}
    afters = [c["after"] for c in checks]
    counts = {"checks": len(afters), "passed": afters.count("pass"), "failed": afters.count("fail"),
              "needsReview": len(afters) - afters.count("pass") - afters.count("fail")}
    isolation = rec.isolation_summary(accounts, require_sandbox)
    decision, reasons = rec.decide(counts, held, isolation)
    if checks_from == "base" and (changed["specs"] or changed["routes"]):
        reasons.append(f"this change edits {changed['specs']} spec and {changed['routes']} route files; "
                       "they judge changes once it merges")
    reasons = [_clip(r) for r in (reasons + problems)][:MAX_REASONS]

    document = {
        "format": rec.FORMAT,
        "decision": decision,
        "reasons": reasons,
        "adapter": "godot",
        "pullRequest": pr,
        "game": {"path": game_rel, "headTree": trees["head"], "baseTree": trees["base"]},
        "checksFrom": checks_from,
        "checksChanged": changed,
        "specs": [{"id": s["id"], "sha256": digest(s), "instruction": _clip(s["instruction"])} for s in spec_docs],
        "drafts": drafts,
        # The record lists the routes that were judged, so its checks are every spec on every route.
        "routes": [{"name": n, "sha256": sha} for n, _p, sha in route_list] if head else [],
        "counts": counts,
        "checks": checks,
        "findings": findings,
        "heldOut": held,
        "isolation": isolation,
        "reviewPage": "review/index.html",
        **({"generatedChecks": read_generated(generated_checks)} if generated_checks is not None else {}),
        "expectrail": {"version": __version__,
                       "commit": expectrail_commit if expectrail_commit and SHA40.fullmatch(expectrail_commit) else None},
        "createdAt": _now(),
    }
    rec.check_record(document)  # the writer checks what the reader will check

    out.mkdir(parents=True, exist_ok=True)
    for arm, results in (("head", head), ("base", before)):
        for (spec_id, route), result in results.items():
            if result.get("verdict") is not None:
                target = out / "verdicts" / arm / route / f"{spec_id}.json"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(result["verdict"], indent=2) + "\n", encoding="utf-8")
    write_page(out, document, frames)
    (out / "findings.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return document


MAX_GENERATED_BYTES = 64 * 1024


def read_generated(path: Path) -> dict:
    """The generated-checks block, or "nothing-generated" with a reason when it cannot be used.
    Advisory only: whatever this returns, the decision is computed without it."""
    try:
        gen = rec.read_json(Path(path), MAX_GENERATED_BYTES, "generated-checks.json")
        rec.validate(gen, rec.schema()["properties"]["generatedChecks"])
        rec.check_generated(gen)
        return gen
    except (rec.RecordError, rec.SchemaError, OSError, ValueError) as exc:
        return {"status": "nothing-generated", "reason": _clip(f"the generated checks could not be read: {exc}"),
                "proposed": 0, "valid": 0, "strong": 0, "weak": 0, "catches": [], "runSha256": None}


def stopped_record(reason: str, *, pr: dict | None, game: str | None, checks_from: str,
                   expectrail_commit: str | None, require_sandbox: bool = False) -> dict:
    """A valid record for a run that could not finish: needs review, and why."""
    held = {"status": "not-used", **HELD_ZERO}
    counts = {"checks": 0, "passed": 0, "failed": 0, "needsReview": 0}
    decision, reasons = rec.decide(counts, held)
    try:
        game_path = safe_relative(game, "game-path", root_ok=True)
    except ConfigError:
        game_path = "unknown"
    document = {
        "format": rec.FORMAT, "decision": decision, "reasons": [_clip(reason)] + reasons, "adapter": "godot",
        "pullRequest": pr, "game": {"path": game_path, "headTree": None, "baseTree": None},
        "checksFrom": checks_from, "checksChanged": {"specs": 0, "routes": 0}, "specs": [], "drafts": 0,
        "routes": [], "counts": counts, "checks": [], "findings": [], "heldOut": held,
        "isolation": rec.isolation_summary([], require_sandbox), "reviewPage": None,
        "expectrail": {"version": __version__,
                       "commit": expectrail_commit if expectrail_commit and SHA40.fullmatch(expectrail_commit) else None},
        "createdAt": _now(),
    }
    rec.check_record(document)
    return document


def _pull_request(number: str | None, head_sha: str | None, base_sha: str | None) -> dict | None:
    if not number:
        return None
    if not str(number).isdigit() or not head_sha or not SHA40.fullmatch(head_sha):
        raise ConfigError("--pr needs a number and --head-sha a 40-digit commit")
    if base_sha and not SHA40.fullmatch(base_sha):
        raise ConfigError("--base-sha must be a 40-digit commit")
    return {"number": int(number), "headSha": head_sha, "baseSha": base_sha or None}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repo", type=Path, required=True, help="the checkout of the pull request")
    p.add_argument("--game", required=True, help="the Godot project folder, relative to --repo")
    p.add_argument("--routes", required=True, help="route files or globs, relative to --repo, one per line")
    p.add_argument("--specs", required=True, help="the folder of test specs, relative to --repo")
    p.add_argument("--out", type=Path, required=True, help="the artifact folder (must not exist yet)")
    p.add_argument("--work", type=Path, help="where replays are kept (default: next to --out)")
    p.add_argument("--base", type=Path, help="a checkout of the pull request's base commit")
    p.add_argument("--heldout", type=Path, help="a checkout of the held-out routes (counts only leave)")
    p.add_argument("--pr", help="the pull request number")
    p.add_argument("--head-sha", help="the pull request's head commit")
    p.add_argument("--base-sha", help="the pull request's base commit")
    p.add_argument("--expectrail-commit", help="the Expectrail commit this action was pinned to")
    p.add_argument("--generated-checks", type=Path,
                   help="the advisory generated-checks block (docs/jit.md); it never changes the decision")
    p.add_argument("--require-sandbox", action="store_true",
                   help="refuse to replay the game outside the replay sandbox (docs/replay-sandbox.md): "
                        "where bubblewrap cannot run, nothing is replayed and the decision is needs-review")
    args = p.parse_args(argv)
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        print("::error title=Expectrail gate::the output folder already holds files")
        return 3
    work = (args.work or out.with_name(out.name + "-work")).resolve()
    checks_from = "base" if args.base else "head"
    commit = args.expectrail_commit
    try:
        pr = _pull_request(args.pr, args.head_sha, args.base_sha)
    except ConfigError as exc:
        print(f"::error title=Expectrail gate::{exc}")
        return 3
    try:
        document = run_gate(repo=args.repo, game=args.game, routes=re.split(r"[\s,]+", args.routes),
                            specs=args.specs, out=out, work=work, base=args.base, heldout=args.heldout, pr=pr,
                            expectrail_commit=commit, generated_checks=args.generated_checks,
                            require_sandbox=args.require_sandbox)
    except ConfigError as exc:
        document = stopped_record(f"the gate's inputs cannot be used: {exc}", pr=pr, game=args.game,
                                  checks_from=checks_from, expectrail_commit=commit,
                                  require_sandbox=args.require_sandbox)
    except Exception as exc:  # noqa: BLE001 - a crash still leaves a record, so the comment says so
        traceback.print_exc()
        document = stopped_record(f"the gate stopped ({type(exc).__name__}); see the verify job's log", pr=pr,
                                  game=args.game, checks_from=checks_from, expectrail_commit=commit,
                                  require_sandbox=args.require_sandbox)
    if not (out / "findings.json").is_file():
        out.mkdir(parents=True, exist_ok=True)
        (out / "findings.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    counts, held = document["counts"], document["heldOut"]
    print(f"::notice title=Expectrail gate {document['decision']}::{counts['checks']} public checks: "
          f"{counts['passed']} pass, {counts['failed']} fail, {counts['needsReview']} need review; held-out "
          f"{held['status']} ({held['checks']} checks, {held['failed']} fail); {len(document['findings'])} findings; "
          f"replays in the sandbox: {rec.isolation_words(document.get('isolation'))}")
    return EXIT[document["decision"]]


if __name__ == "__main__":
    sys.exit(main())
