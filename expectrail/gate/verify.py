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

That is the rule ``engine-only``, which this command line still runs: the job that runs a pull
request's code holds no model key (#254). ``run_gate`` also takes the rule ``both`` (#327): every
check is then judged by the engine's record and by a visual observer over the captured frames
(``expectrail.observers``), a check passes only when both pass, and with no visual observer nothing
is accepted. A record judged that way says so in its ``observers`` block; a record without the
block was judged ``engine-only``.

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
from expectrail import viewer

EXPECTRAIL_ROOT = resources.ROOT
CONTRACTS = EXPECTRAIL_ROOT / "contracts"
EXIT = {"accept": 0, "reject": 1, "needs-review": 2}
ANCHOR_EVERY = 10   # the player's place is asked about in every this-many captured frames (expectrail.gate.anchor)
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


DEFAULT_ADAPTER = "godot"   # what a caller that names no adapter gets: the gate's first engine


def adapter_for(name: str):
    """The engine adapter a verification runs on, from the registry (``harness.adapters``).
    ConfigError for a name the registry does not hold and for an adapter with no verify path:
    nothing is replayed on an engine that was not asked for."""
    from harness import adapters

    if not isinstance(name, (str, adapters.Adapter)):
        raise ConfigError(f"an adapter is named by a string, not {type(name).__name__}; registered: "
                          f"{', '.join(adapters.names())}")
    try:
        engine = adapters.resolve(name)
    except KeyError:
        raise ConfigError(f"no adapter named {str(name)[:40]!r}; registered: {', '.join(adapters.names())}") from None
    if not engine.can_verify():
        raise ConfigError(f"the adapter {engine.name!r} has no verify path yet; those that have one: "
                          f"{', '.join(adapters.verifying()) or 'none'}")
    return engine


def harness_replay(route: Path, game: Path, out: Path, frames: bool, sandbox: str | None = None,
                   checkouts: tuple[Path, ...] = (), adapter: str = DEFAULT_ADAPTER) -> dict:
    """One replay through the adapter's harness (``harness.adapters``, ``verify_run``; for Godot that
    is ``harness.run``, which gives Godot only the display and rendering variables from the
    environment and runs it in the replay sandbox where the machine can). ``sandbox`` is auto,
    require or off (default $EXPECTRAIL_SANDBOX, else auto).
    ``checkouts`` are the folders a link in a game may lead into: the one that holds ``game``
    is used, and without one a link may not leave the game folder."""
    from harness.adapters import sha256_file

    engine = adapter_for(adapter)
    replay = engine.verify_run(route, out, game=game, capture_frames=frames, sandbox=sandbox,
                               within=_checkout_of(game, checkouts))
    trace = json.loads((out / "trace.json").read_text(encoding="utf-8"))
    return {"trace": trace, "replaySha256": sha256_file(out / "replay.json"),
            "framesDir": (out / engine.frame_pattern).parent if frames else None, "isolation": replay.get("isolation"),
            # The digest of the copy this replay ran (harness.tree.copy), for the gate to hold
            # against the tree its record names.
            "tree": replay["game"]["tree"]}


def observations(trace: dict, replay_sha256: str) -> dict:
    """The engine's position log as observations; never SAM, whatever the environment says."""
    from agents.observations import from_trace_synthetic

    return from_trace_synthetic(trace, replay_sha256=replay_sha256)


def evaluate(spec: dict, obs: dict, **context) -> dict:
    from expectrail.evaluator import evaluate as _evaluate

    return _evaluate(spec, obs, **context)


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


class NoAnswer(Exception):
    """A visual observer gave no observations for a check: no frames, or the model failed. Never a
    pass and never a failure: the check needs review.

    A visual observer is any object with ``describe() -> {"name", "provider", "model"}`` and
    ``look(spec, run, keep=True) -> observations`` (expectrail.observations/v0), each raising this
    when it cannot answer. ``expectrail.observers.FramesObserver`` is the one that asks a vision
    model; the gate itself imports no model code."""


def _why(text) -> str:
    return _clip(str(text), 160)


CAPTURE_FPS = 60   # what the Godot harness captures at (harness.run), and what a spec's window counts in;
#                    a caller that verifies on another engine gives its adapter's rate (run_gate does)
FRAME_FILE = re.compile(r"f(\d+)\.png")   # a captured frame: f00000000.png, f00000001.png, ...
PASSES_ON_ONE_FRAME = ("reaches",)   # a pass that rests on the frame that shows it, not on every frame


def route_ticks(path: Path) -> int | None:
    """How many physics ticks the route file says a replay of it runs; None when it cannot be told."""
    try:
        ticks = json.loads(Path(path).read_bytes())["ticks"]
    except Exception:  # noqa: BLE001 - a route that cannot be read gives no count, and no pass rests on none
        return None
    return ticks if isinstance(ticks, int) and not isinstance(ticks, bool) and ticks >= 0 else None


def window_frames(spec: dict, ticks: int | None, trace: dict | None,
                  capture_fps: int | None = CAPTURE_FPS) -> list[int] | None:
    """The frames of the spec's window that a finished replay of a route of ``ticks`` ticks has.

    Counted from the route (the gate's own input) and the tick rate the trace states, never from
    what an observer returned: an observer that saw five frames cannot say the window is five frames
    long. ``capture_fps`` is the frames the engine's harness captures per second of game time (the
    adapter's ``capture_fps``). None when it cannot be told (no tick count, no tick rate, no capture
    rate, a window that is not numbers)."""
    tps = (trace or {}).get("physicsTicksPerSecond")
    whole = lambda v: isinstance(v, int) and not isinstance(v, bool)   # noqa: E731
    if not whole(ticks) or ticks < 0 or not whole(tps) or tps < 1 or not whole(capture_fps) or capture_fps < 1:
        return None
    window = spec.get("window") or {}
    lo, hi = window.get("fromFrame", 0), window.get("toFrame")
    if not whole(lo) or (hi is not None and not whole(hi)):
        return None
    total = ticks // max(tps // capture_fps, 1)
    return list(range(max(lo, 0), total if hi is None else min(hi + 1, total)))


def frames_in(obs) -> set[int]:
    """The frame numbers an observations document holds."""
    frames = obs.get("frames") if isinstance(obs, dict) else None
    return {f["frame"] for f in frames if isinstance(f, dict) and isinstance(f.get("frame"), int)} \
        if isinstance(frames, list) else set()


def captured_frames(frames_dir) -> set[int]:
    """The frame numbers of the frame files in a replay's frames folder (none when there is none)."""
    try:
        names = [p.name for p in Path(frames_dir).iterdir()] if frames_dir is not None else []
    except OSError:
        return set()
    return {int(m.group(1)) for m in map(FRAME_FILE.fullmatch, names) if m}


def engine_gap(spec: dict, run: dict, ticks: int | None, capture_fps: int | None = CAPTURE_FPS) -> str | None:
    """Why the engine's record cannot carry a pass under either rule, or None when it can: the
    log must hold every tick of the route, and its observations every frame of the check's window.
    A log that stops early says nothing about the ticks it does not have."""
    trace = run.get("trace") or {}
    want = window_frames(spec, ticks, trace, capture_fps)
    if want is None:
        return "the gate cannot tell how many frames this route should have"
    rows = trace.get("rows")
    tick_ids = [r.get("tick") for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    logged = len({t for t in tick_ids if type(t) is int and 0 <= t < ticks})
    if logged < ticks:
        return f"the engine's record has {logged} of {ticks} ticks of the route"
    if tick_ids != list(range(ticks)):
        return f"the engine's record has {logged} of {ticks} ticks but not one ordered row per tick"
    if not want:
        return "not-exercised: the check's window has no frames on this route"
    have = frames_in(run.get("engineObservations"))
    got = sum(1 for i in want if i in have)
    if got < len(want):
        return f"the engine's record covers {got} of {len(want)} frames of the check's window"
    return None


def visual_gap(spec: dict, seen: dict, run: dict, ticks: int | None,
               capture_fps: int | None = CAPTURE_FPS) -> str | None:
    """Why the visual observer's passing answer cannot carry a pass, or None when it can.

    A pass counts only when the replay captured every frame of the check's window and the observer's
    answer holds every one of them. The one exception is an assertion that passes on the frame that
    shows it (``reaches``): there the answer need not hold every frame, but the replay must still
    have captured the whole window. (That the answer is about this replay at all is checked before
    any verdict is read from it: ``judge_run``.)"""
    want = window_frames(spec, ticks, run.get("trace"), capture_fps)
    if want is None:
        return "the gate cannot tell how many frames this route should have"
    on_disk = captured_frames(run.get("framesDir"))
    got = sum(1 for i in want if i in on_disk)
    if got < len(want):
        return f"the replay captured {got} of {len(want)} frames of the check's window"
    if (spec.get("assertion") or {}).get("type") in PASSES_ON_ONE_FRAME:
        return None
    have = frames_in(seen)
    got = sum(1 for i in want if i in have)
    if got < len(want):
        return f"the visual observer saw {got} of {len(want)} frames of the check's window"
    return None


def judge_run(spec: dict, run: dict, *, rule: str = rec.ENGINE_ONLY, visual=None, keep: bool = True,
              ticks: int | None = None, capture_fps: int | None = CAPTURE_FPS,
              route: str | None = None) -> dict:
    """One approved spec on one finished replay, by the rule.

    ``engine-only``: the evaluator on the engine's record, as the gate always judged. ``both``: that,
    and the evaluator on what the visual observer (``expectrail.observers``) saw in the captured
    frames, joined by ``rec.combine``. The visual observer is not asked when the engine's record
    already fails the check (a failure on either observer is a failure, so its answer could not
    change the result), and anything it cannot answer is needs-review, never a pass. The result
    then carries ``observed`` (what each said), and the visual observer's observations and verdict.

    Under either rule a pass is a pass only when it covers the check: ``ticks`` is how many physics
    ticks the route runs (``route_ticks``), and from it the gate counts the frames of the spec's
    window the replay should have. An engine's record that stops short of the route, a replay that
    captured only part of the window, or a visual answer that holds only part of it is needs-review
    with the count in the reason (``engine_gap``, ``visual_gap``); a visual answer that names
    another replay is no answer. Without ``ticks`` the gate cannot tell, and nothing passes; the same
    holds without ``capture_fps``, the frames the engine's harness captures per second of game time."""
    try:
        verdict = evaluate(spec, run["engineObservations"], route=route, trace=run.get("trace"),
                           expected_frames=window_frames(spec, ticks, run.get("trace"), capture_fps))
    except Exception as exc:  # noqa: BLE001 - a crash is recorded, never read as a pass
        verdict = None
        engine, engine_reason = "needs-review", f"the evaluator stopped ({type(exc).__name__})"
    else:
        engine, engine_reason = verdict["result"], verdict["reason"]
        if engine not in ("pass", "fail", "needs-review", "not-applicable"):
            engine, engine_reason = "needs-review", "the evaluator gave a result this gate does not know"
    if engine not in ("fail", "not-applicable"):
        gap = engine_gap(spec, run, ticks, capture_fps)
        if gap:
            engine, engine_reason = "needs-review", f"not-exercised: {gap}; {engine_reason}"
            if verdict is not None:
                verdict = dict(verdict, result=engine, reason=engine_reason, firstFrame=None)
                if "coverage" in verdict:
                    verdict["coverage"] = dict(verdict["coverage"], completeWindow=False,
                                               semanticResult="insufficient_observation")
    result = {"result": engine, "verdict": verdict, "reason": engine_reason,
              "frame": verdict.get("firstFrame") if verdict else None,
              "framesDir": run.get("framesDir") if verdict else None}
    if rule == rec.ENGINE_ONLY:
        return result
    if engine == "not-applicable":
        return dict(result, observed={"engine": engine, "visual": "not-asked", "visualAnswerSha256": None})
    said, why, seen, seen_verdict, answer, part = "not-asked", None, None, None, None, None
    if engine != "fail" and visual is not None:
        try:
            seen = visual.look(spec, run, keep=keep)
            answer = digest(seen)
            about = (seen.get("replay") or {}).get("sha256")
            if not isinstance(about, str) or about != run.get("replaySha256"):
                # Whatever it says, it is not about what this replay showed: not a pass, and not a
                # failure of this change either.
                raise NoAnswer("its answer is about another replay")
            seen_verdict = evaluate(spec, seen, route=route, trace=run.get("trace"),
                                    expected_frames=window_frames(spec, ticks, run.get("trace"), capture_fps))
            said = seen_verdict["result"] if seen_verdict["result"] in rec.VISUAL_VERDICTS else "needs-review"
            if said != "fail":
                part = visual_gap(spec, seen, run, ticks, capture_fps)
                if part:
                    said = "needs-review"
                    seen_verdict = dict(seen_verdict, result=said, reason="not-exercised: " + part)
        except NoAnswer as exc:
            said, why, seen, seen_verdict = "no-answer", _why(exc), None, None
        except Exception as exc:  # noqa: BLE001 - a visual observer that stops, or whose answer cannot be
            # digested or evaluated, gave no answer; never a pass
            said, why, seen, seen_verdict = "no-answer", f"the visual observer stopped ({type(exc).__name__})", None, None
    combined = rec.combine(engine, said)
    if engine == "fail":
        reason = engine_reason
    elif said == "fail":
        reason = f"the visual observer sees a failure in the frames: {seen_verdict['reason']}"
        result["frame"] = seen_verdict.get("firstFrame")
    elif engine == "pass" and said == "pass":
        reason = engine_reason
    elif engine == "pass":
        reason = "the engine's record passes; " + {
            "not-asked": "no visual observer was asked, so this is not a pass",
            "no-answer": f"the visual observer gave no answer ({why}), so this is not a pass",
            "needs-review": f"the visual observer could not decide ({_why(part or (seen_verdict or {}).get('reason'))}), "
                            "so this is not a pass"}[said]
    else:
        reason = f"the engine's record could not decide: {engine_reason}"
    result.update(result=combined, reason=reason, visualWhy=why if said == "no-answer" else None,
                  observed={"engine": engine, "visual": said,
                            "visualAnswerSha256": answer if said in rec.VISUAL_VERDICTS else None},
                  visualObservations=seen if said in rec.VISUAL_VERDICTS else None,
                  visualVerdict=seen_verdict if said in rec.VISUAL_VERDICTS else None)
    return result


def judge_arm(game: Path, routes: list[tuple[str, Path, str]], specs: list[dict], out: Path,
              replay: Replay, *, label: str, rule: str = rec.ENGINE_ONLY, visual=None,
              on_phase: Callable[[str], object] | None = None,
              capture_fps: int | None = CAPTURE_FPS, runs: dict | None = None) -> dict[tuple[str, str], dict]:
    """{(spec id, route name): result} for one game tree. ``runs``, when given, is filled with each
    finished replay by route name (the player's place is compared between the two sides from them)."""
    results: dict[tuple[str, str], dict] = {}
    not_run = {"observed": {"engine": "replay-error", "visual": "not-asked", "visualAnswerSha256": None}} \
        if rule == rec.BOTH else {}
    for name, path, _sha in routes:
        applicable_specs = []
        for spec in specs:
            scope = spec.get("coverage", {}).get("routes")
            if scope is None or name in scope:
                applicable_specs.append(spec)
                continue
            results[(spec["id"], name)] = {
                "result": "not-applicable", "verdict": None, "frame": None, "framesDir": None,
                "reason": "not-applicable: this spec does not apply to this route",
                **({"observed": {"engine": "not-applicable", "visual": "not-asked", "visualAnswerSha256": None}}
                   if rule == rec.BOTH else {})}
        if not applicable_specs:
            continue
        try:
            if on_phase:
                on_phase("observing")
            run = replay(path, game, out / name, True)
            run = dict(run, engineObservations=observations(run["trace"], run["replaySha256"]))
            if runs is not None:
                runs[name] = run
        except (Exception, SystemExit) as exc:  # noqa: BLE001 - the harness exits on a failed replay
            # The gate's own sentence when it is the gate that refused the replay; otherwise only the
            # kind of error, since a message could carry text from the game.
            why = f"the {label} game changed while it was being verified" if isinstance(exc, GameChanged) \
                else f"the {label} replay did not finish ({type(exc).__name__})"
            print(f"::warning title=Expectrail gate::route {name}: {why}")
            for spec in applicable_specs:
                results[(spec["id"], name)] = {"result": "replay-error", "verdict": None, "frame": None,
                                               "framesDir": None, "reason": why, **not_run}
            continue
        if on_phase:
            on_phase("evaluating")
        ticks = route_ticks(path)
        for spec in applicable_specs:
            result = judge_run(spec, run, rule=rule, visual=visual, ticks=ticks, capture_fps=capture_fps, route=name)
            # The evidence viewer's timeline (expectrail.viewer): measured from the engine's record the
            # evaluator judged, kept only when it agrees with that verdict. It decides nothing.
            result["timeline"] = viewer.check_series(spec, run, result.get("verdict"))
            results[(spec["id"], name)] = result
    return results


class GameChanged(RuntimeError):
    """A replay ran a game other than the one the record names: the folder changed after the gate
    read it. The replay's result is not used."""


HELD_ZERO = {"routes": 0, "checks": 0, "passed": 0, "failed": 0, "needsReview": 0}


def unscoped(spec: dict) -> dict:
    """The spec without its route scope (``coverage.routes``), for judging held-out routes."""
    coverage = spec.get("coverage")
    if not isinstance(coverage, dict) or "routes" not in coverage:
        return spec
    rest = {k: v for k, v in coverage.items() if k != "routes"}
    return {k: v for k, v in spec.items() if k != "coverage"} | ({"coverage": rest} if rest else {})


def judge_heldout(root: Path | None, game: Path, specs: list[dict], replay: Replay, *,
                  rule: str = rec.ENGINE_ONLY, visual=None, frames_to_visual: bool = False,
                  capture_fps: int | None = CAPTURE_FPS) -> dict:
    """Counts only. Nothing from the held-out set is printed, returned or left on disk.

    Under the rule ``both`` each held-out check needs both observers, as a public check does: a
    held-out check cannot pass on the engine's record alone either. A visual observer over the
    frames sends those frames to a model's provider, and whether a held-out route's frames may leave
    for a third party is a person's decision. So it is off unless the caller says
    ``frames_to_visual=True``: without it the held-out routes are replayed without frames, the
    visual observer is not asked, a failure on the engine's record still counts, and no held-out
    check passes. With it they are replayed with frames (in the scratch folder that is deleted) and
    the visual observer is asked to keep no answer cache."""
    if not (rule == rec.BOTH and frames_to_visual):
        visual = None
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
                run = replay(path, game, scratch / f"r{n:02d}", visual is not None)
                run = dict(run, engineObservations=observations(run["trace"], run["replaySha256"]))
                ticks = route_ticks(path)
                # A spec's coverage.routes names the public routes its author can see. A held-out route
                # is never among them, so applying the scope here would drop every scoped spec and leave
                # a judged held-out set with no checks (merge guard on #416). Every approved spec is
                # judged on every held-out route, as before coverage existed.
                results = [judge_run(unscoped(spec), run, rule=rule, visual=visual, keep=False, ticks=ticks,
                                     capture_fps=capture_fps, route=rec.read_json(path, ROUTE_CAP, "route")["name"])["result"]
                           for spec in specs]
            except (Exception, SystemExit):  # noqa: BLE001
                results = ["needs-review"] * len(specs)
            results = [r for r in results if r != "not-applicable"]
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


def game_tree(root: Path, within: Path | None = None, adapter: str = DEFAULT_ADAPTER) -> str:
    """The digest of the game the record names, taken over the files a replay's copy holds
    (``harness.tree``), leaving out the folders the adapter says are the engine's own. For Godot it
    is ``harness.run.tree_digest``, the function that writes replay.json's ``game.tree``, so the
    record and its replays name a tree the same way. Raises ``harness.tree.TreeProblem`` for a link
    that leaves ``within``, loops or leads nowhere."""
    return adapter_for(adapter).tree_digest(root, within)


def _game_ok(game: Path, adapter: str = DEFAULT_ADAPTER) -> bool:
    return adapter_for(adapter).is_project(game)


@dataclass(frozen=True)
class SavedReplays:
    """Prechecked runs keyed by logical game folder and SHA-256 of the trusted route bytes."""
    trees: dict[Path, str]
    runs: dict[tuple[Path, str], dict]

    def __call__(self, route: Path, game: Path, out: Path, frames: bool) -> dict:
        import hashlib

        return self.runs[game, hashlib.sha256(route.read_bytes()).hexdigest()]


def run_gate(*, repo: Path, game: str, routes: list[str], specs: str, out: Path, work: Path,
             base: Path | None = None, heldout: Path | None = None, pr: dict | None = None,
             expectrail_commit: str | None = None, replay: Replay = harness_replay,
             generated_checks: Path | None = None, require_sandbox: bool = False,
             checks: Checks | None = None, rule: str = rec.ENGINE_ONLY, visual=None,
             on_phase: Callable[[str], object] | None = None, heldout_frames_to_visual: bool = False,
             intent: str = "none", adapter: str = DEFAULT_ADAPTER,
             anchor_every: int = ANCHOR_EVERY, changed_checks: dict | None = None) -> dict:
    """Run the gate and write the artifact in ``out``; returns the findings record.

    ``adapter`` names the engine, and everything about the engine comes from its entry in the
    registry (``harness.adapters``): the replay (``verify_run``), how a project folder is recognised,
    which folders are left out of the game's digest, and the capture rate a spec's window is counted
    in. A name the registry does not hold, or an adapter with no verify path, is a ConfigError and
    nothing runs. A ``replay`` given by the caller is used in place of the adapter's.

    ``rule`` is which observers judge (``rec.RULES``). ``engine-only`` is the engine's record alone,
    as the pull-request gate runs until its two-job form exists (#254). ``both`` (#327) judges every
    check with the engine's record and with ``visual`` (an ``expectrail.observers.FramesObserver``)
    over the captured frames: a check passes only when both pass, a failure on either rejects, and
    with ``visual`` None, or an observer that cannot be set up or does not answer, nothing is
    accepted. The record's ``observers`` block (written under ``both`` only; without it a record
    reads as ``engine-only``) names the rule and the observer, each row says what
    each observer said, and the visual observer's observations are written under ``observations/``
    with their digest in the row, so its verdict can be read again without asking the model.

    Under ``both`` a pass must cover the check: the engine's record every tick of the route, the
    captured frames and the visual observer's answer every frame of the spec's window, counted from
    the route's ticks (``judge_run``). ``heldout_frames_to_visual`` lets the visual observer see the
    held-out routes' frames, which sends them to the model's provider; it is off by default, and
    then no held-out check passes under ``both`` (``judge_heldout``).

    ``on_phase`` is told ``observing`` when a replay starts and ``evaluating`` when its checks are
    judged (the verification job's phases).

    ``intent`` is what the change says it is for (``fix``, ``change`` or ``none``; issue #284). For
    ``fix`` an accept also needs a check that failed on the base and passes on the head. Each such
    check is replayed twice more on each side, and only one that fails on the base and passes on the
    head all three times demonstrates the repair; with none the decision is needs-review. For
    ``change`` and ``none`` nothing more is replayed and the rule is as it was.

    ``checks`` is the checks as a caller has already read them (``read_checks``). The gate then
    judges with exactly those and reads no spec or route file itself. Without it the gate reads them
    here, once. Either way each replay is given a copy of its route made from the bytes that were
    read, so the route a replay plays is the route the record names.

    ``require_sandbox`` refuses to replay the game outside the replay sandbox: where the machine
    cannot provide it nothing is replayed (ConfigError), and a replay that ran outside it anyway
    keeps the decision from being accept. Without it the game is sandboxed where possible, and the
    record's ``isolation`` block says how many replays were.

    Under ``both`` with a base, the player's place is asked of the visual observer's model on both
    sides as well (``expectrail.gate.anchor``; #327, decision B): every ``anchor_every``-th captured
    frame of each route and its last, inside the player's own collision box. A route where the head
    shows something different from the base, or a frame with no answer, keeps the decision from
    accept, and the record's ``anchor`` block says why, with the frames kept under ``anchor/``. It
    never rejects and never accepts. Each frame asked about is a paid image.

    ``generated_checks`` is the advisory block a check-generation step wrote (docs/jit.md). It is read
    as untrusted data after the decision is made, and nothing in it can change the decision."""
    repo = repo.resolve()
    engine = adapter_for(adapter)
    saved = replay if isinstance(replay, SavedReplays) else None
    # A saved run names the tree captured on the other machine. No game is installed here.
    game_ok = engine.is_project if saved is None else saved.trees.__contains__
    if intent not in rec.INTENTS:
        raise ConfigError("the intent must be one of: " + ", ".join(rec.INTENTS))
    problems: list[str] = []
    if rule not in rec.RULES:
        raise ConfigError(f"the rule must be one of {', '.join(rec.RULES)}")
    if rule == rec.ENGINE_ONLY and visual is not None:
        raise ConfigError("a visual observer was given and the rule is engine-only; ask for the rule both")
    observer = None   # how the record names the visual observer; None when none judged
    if visual is not None:
        try:
            observer = visual.describe()
            rec.validate(observer, rec.schema()["properties"]["observers"]["properties"]["visual"])
        except NoAnswer as exc:
            problems.append(f"the visual observer could not be used: {_why(exc)}")
            observer = visual = None
        except Exception as exc:  # noqa: BLE001 - an observer that cannot say what it is does not judge
            problems.append(f"the visual observer could not be used ({type(exc).__name__})")
            observer = visual = None
    if replay is harness_replay:
        mine = {"adapter": engine.name}
        if require_sandbox:
            from harness import sandbox as box

            tool, why = box.probe(True)
            if tool is None:
                raise ConfigError(f"the replay sandbox is required and this machine cannot provide it: {why}")
            mine["sandbox"] = "require"
        replay = functools.partial(harness_replay, **mine)
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
    # Every problem the one reading of the spec and route files found: a file refused or not valid,
    # an id or a name used twice, a limit passed, nothing found where the job said to look. With
    # any of them the checks that run are not all of the project's checks, and `decide` is told.
    check_problems = len(checks.problems)
    # The replays play copies of the routes made from the bytes that were read (written below, once
    # the work folder is known not to be inside a game): the checkout's route files are not opened again.
    routes_dir = Path(work) / "checks" / "routes"
    route_list = [(name, routes_dir / f"{name}.json", sha) for name, _data, sha in checks.routes]
    changed = {"specs": 0, "routes": 0}
    if changed_checks is not None:
        if saved is None:
            raise ConfigError("changed check counts require saved replays")
        changed = changed_checks
    elif base is not None:
        # What the change does to the check files, counted from one kind of reading on both sides:
        # the head's checks are listed by the same reader as the base's. A file the reader refuses
        # compares by its name and its refusal, so one that is the same on both sides is not counted
        # and one that the change removes is. (The head's checks judge nothing here.)
        mine = read_checks(repo, specs_rel, patterns, "head")
        changed["specs"] = changed_count(mine.spec_entries, checks.spec_entries)
        changed["routes"] = changed_count(mine.route_entries, checks.route_entries)

    head_game = repo / game_rel
    base_game = (checks_root / game_rel) if base is not None else None
    if not game_ok(head_game):
        problems.append(f"no {engine.label()} project ({engine.project_file}) at {game_rel}")
        route_list_for_head: list = []
    else:
        route_list_for_head = route_list
    if base_game is not None and not game_ok(base_game):
        problems.append(f"the base commit has no {engine.label()} project at {game_rel}, so nothing is compared")
        base_game = None
    # The trees are taken now, before anything is copied or replayed, by the walk the replay's copy
    # uses. A game that cannot be described (a link that leaves its checkout, loops or leads nowhere)
    # is not replayed, and neither is one that holds the gate's own output: its copy would hold itself.
    from harness.tree import TreeProblem

    trees: dict = {"head": None, "base": None}
    for side, folder, checkout in (("head", head_game if game_ok(head_game) else None, repo), ("base", base_game, base)):
        if folder is None:
            continue
        for label, place in (("output", out), ("work", work)):
            place = Path(place).resolve()
            if place == folder.resolve() or folder.resolve() in place.parents:
                raise ConfigError(f"the {label} folder is inside the {side} game folder ({game_rel}); keep it outside the game")
        try:
            trees[side] = game_tree(folder, checkout, engine.name) if saved is None else saved.trees[folder]
        except TreeProblem as exc:
            raise ConfigError(f"the {side} game cannot be verified as it stands: {exc}") from exc
        named[Path(folder)] = trees[side]
    shutil.rmtree(routes_dir, ignore_errors=True)
    routes_dir.mkdir(parents=True)
    for name, data, _sha in checks.routes:
        (routes_dir / f"{name}.json").write_bytes(data)

    how = {"rule": rule, "visual": visual, "on_phase": on_phase, "capture_fps": engine.capture_fps}
    held_back = False   # under `both`: the held-out frames were kept from the visual observer
    head_runs: dict = {}
    base_runs: dict = {}
    head = judge_arm(head_game, route_list_for_head, spec_docs, work / "head", replay, label="head",
                     runs=head_runs, **how) if route_list_for_head and spec_docs else {}
    before = judge_arm(base_game, route_list, spec_docs, work / "base", replay, label="base",
                       runs=base_runs, **how) if base_game is not None and route_list_for_head and spec_docs else {}
    if heldout is None or not spec_docs:
        held = {"status": "not-used", **HELD_ZERO}
    elif not game_ok(head_game):
        held = {"status": "unavailable", **HELD_ZERO}
    else:
        held = judge_heldout(heldout.resolve(), head_game, spec_docs, replay, rule=rule, visual=visual,
                             frames_to_visual=heldout_frames_to_visual, capture_fps=engine.capture_fps)
        if rule == rec.BOTH and visual is not None and not heldout_frames_to_visual:
            held_back = True

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
            if rule == rec.BOTH:
                row["observed"] = {"before": prior["observed"] if prior else None, "after": after["observed"]}
            checks.append(row)
            if fid:
                frame = after["frame"] if isinstance(after["frame"], int) and after["frame"] >= 0 else None
                findings.append({"id": fid, "spec": spec["id"], "route": name, "kind": kind, "before": b,
                                 "after": after["result"], "comparison": row["comparison"],
                                 "reason": _clip(after["reason"]), "frame": frame})
                frames[fid] = {"after": (after["framesDir"], frame),
                               "before": ((prior or {}).get("framesDir"), frame)}
    afters = [c["after"] for c in checks if c["after"] != "not-applicable"]
    counts = {"checks": len(afters), "passed": afters.count("pass"), "failed": afters.count("fail"),
              "needsReview": len(afters) - afters.count("pass") - afters.count("fail")}
    repair = None
    if intent == "fix":
        # A check that failed on the base and passes on the head may demonstrate the repair. One
        # failure on the base could be a flaky check, so its route is replayed again on both sides
        # until each side has REPAIR_RUNS results; only a row that fails every time on the base and
        # passes every time on the head counts (rec.row_counts). Nothing else is replayed again.
        claimed = [c for c in checks if c["comparison"] == "REPAIRED"]
        again = [r for r in route_list if r[0] in {c["route"] for c in claimed}]
        runs = {(c["spec"], c["route"]): {"base": [c["before"]], "head": [c["after"]]} for c in claimed}
        for n in range(2, rec.REPAIR_RUNS + 1):
            for side, folder in (("base", base_game), ("head", head_game)):
                # By the same rule as the first run: under `both` a run passes only with both observers.
                more = judge_arm(folder, again, spec_docs, work / f"{side}-run{n}", replay, label=side,
                                 rule=rule, visual=visual, capture_fps=engine.capture_fps) if again else {}
                for key, kept in runs.items():
                    kept[side].append(more[key]["result"])
        repair = rec.repair_block([{"spec": c["spec"], "route": c["route"], **runs[(c["spec"], c["route"])]}
                                   for c in claimed])
    isolation = rec.isolation_summary(accounts, require_sandbox)
    anchor_doc = None
    if rule == rec.BOTH and before:
        # The player's place, asked of the vision model on both sides (#327, decision B): a route that
        # differs keeps the decision from accept and its frames are kept side by side. With no visual
        # observer, or one whose model cannot be asked about a box, the block says it was not asked.
        pairs = [(n, base_runs[n], head_runs[n]) for n, _p, _s in route_list if n in base_runs and n in head_runs]
        try:
            from expectrail.gate import anchor as anchor_check
        except ImportError:   # a copy without the vision adapter; with no visual observer nothing is accepted anyway
            anchor_check = None
        if anchor_check is not None:
            segmenter = getattr(visual, "segmenter", None) if visual is not None else None
            try:
                client = segmenter() if callable(segmenter) else None
            except Exception:  # noqa: BLE001 - a model that cannot be set up is not asked
                client = None
            found = anchor_check.block(pairs, client, observer if client is not None else None, every=anchor_every)
            out.mkdir(parents=True, exist_ok=True)
            anchor_doc = anchor_check.keep_pictures(found, out)
    spec_records = [{"id": s["id"], "sha256": digest(s), "instruction": _clip(s["instruction"]),
                     **({"routes": s["coverage"]["routes"]} if "routes" in s.get("coverage", {}) else {})}
                    for s in spec_docs]
    route_records = [{"name": n, "sha256": sha} for n, _p, sha in route_list] if head else []
    decision, reasons = rec.decide(counts, held, isolation, check_problems, intent=intent, repair=repair,
                                   required_routes_missing=rec.missing_required_routes(spec_records, route_records),
                                   observers={"rule": rule, "visual": observer} if rule == rec.BOTH else None,
                                   base_judged=any(c["before"] is not None for c in checks), anchor=anchor_doc)
    if rule == rec.BOTH:
        # Why a check the engine's record passes is not a pass, in the record's own words.
        held_up = [c for c in checks if c["after"] == "needs-review" and c["observed"]["after"]["engine"] == "pass"]
        said = [c["observed"]["after"] for c in held_up]
        # Why the visual observer gave no answer (a provider outage, a spent cap, no credit...), in the
        # job's own reasons, so whoever reads the status can tell one from another (#258).
        whys = sorted({head[(c["spec"], c["route"])].get("visualWhy") or "no reason was given"
                       for c in held_up if c["observed"]["after"]["visual"] == "no-answer"})
        for answer, words in (("not-asked", "no visual observer was asked about"),
                              ("no-answer", "the visual observer gave no answer on"),
                              ("needs-review", "the visual observer could not decide")):
            n = sum(1 for one in said if one["visual"] == answer)
            if n:
                because = f" ({'; '.join(whys[:3])})" if answer == "no-answer" and whys else ""
                reasons.append(f"the engine's record passes {n} check{'s' if n != 1 else ''} that {words}{because}, "
                               "so this is not an accept: an accept needs the visual observer's evidence")
        if held_back and held["status"] == "judged" and decision != "reject":
            reasons.append("the held-out routes' frames were not sent to the visual observer (that needs a "
                           "person's decision), so no held-out check passes under this rule")
    if checks_from == "base" and (changed["specs"] or changed["routes"]):
        reasons.append(f"this change edits {changed['specs']} spec and {changed['routes']} route files; "
                       "they judge changes once it merges")
    reasons = [_clip(r) for r in (reasons + problems)][:MAX_REASONS]

    document = {
        "format": rec.FORMAT,
        "decision": decision,
        "reasons": reasons,
        "adapter": engine.name,
        "pullRequest": pr,
        "game": {"path": game_rel, "headTree": trees["head"], "baseTree": trees["base"]},
        "checksFrom": checks_from,
        "checksChanged": changed,
        "specs": spec_records,
        "drafts": drafts,
        "checkProblems": check_problems,
        # Written under the rule both only. An engine-only record stays as it was before the block
        # existed, so a reader from before it (the comment job runs main's) can still read it; a
        # reader takes a record without the block as engine-only.
        **({"observers": {"rule": rule, "visual": observer}} if rule == rec.BOTH else {}),
        **({"anchor": anchor_doc} if anchor_doc is not None else {}),
        # Written only when something was declared, so a record of an undeclared change is the record
        # it was before the field existed and a reader older than the field still reads it.
        **({"intent": intent} if intent != "none" else {}),
        **({"repair": repair} if repair is not None else {}),
        # The record lists the routes that were judged, so its checks are every spec on every route.
        "routes": route_records,
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
            if result.get("visualObservations") is not None:
                # The visual observer's answer, under the digest its row names, and its verdict.
                for folder, doc in (("observations", result["visualObservations"]), ("verdicts", result["visualVerdict"])):
                    target = out / folder / arm / route / f"{spec_id}.visual.json"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    write_page(out, document, frames)
    timelines = {key: {"after": result.get("timeline"), "before": (before.get(key) or {}).get("timeline")}
                 for key, result in head.items()}
    try:
        viewer.write_gate(out, document, frames, timelines)
    except Exception as exc:  # noqa: BLE001 - the viewer shows the decision; it never changes or blocks it
        print(f"::warning title=Expectrail gate::the evidence viewer was not written ({type(exc).__name__}); "
              "the review page and findings.json are")
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


def _adapter_name(adapter) -> str:
    """The name a stopped record gives its adapter: the registry's name for a registered adapter
    (with or without a verify path), else ``unknown``. Never an exception: a stopped record is
    written because something already went wrong."""
    try:
        from harness import adapters
        if isinstance(adapter, adapters.Adapter):
            return adapter.name
        if isinstance(adapter, str) and adapter in adapters.names():
            return adapters.resolve(adapter).name
    except Exception:  # noqa: BLE001 - a registry that cannot be read leaves the name unknown
        pass
    return "unknown"


def stopped_record(reason: str, *, pr: dict | None, game: str | None, checks_from: str,
                   expectrail_commit: str | None, require_sandbox: bool = False,
                   rule: str = rec.ENGINE_ONLY, intent: str = "none", adapter: str = DEFAULT_ADAPTER) -> dict:
    """A valid record for a run that could not finish: needs review, and why. An intent that is not
    one of the three is recorded as ``fix``, the stricter reading; the reason given says what was wrong.
    The record names the adapter the run asked for when the registry holds it, and ``unknown``
    otherwise: a run on an engine that is not Godot is never recorded as a Godot run."""
    held = {"status": "not-used", **HELD_ZERO}
    counts = {"checks": 0, "passed": 0, "failed": 0, "needsReview": 0}
    intent = intent if intent in rec.INTENTS else "fix"
    repair = rec.repair_block([]) if intent == "fix" else None
    decision, reasons = rec.decide(counts, held, intent=intent, repair=repair, base_judged=False)
    try:
        game_path = safe_relative(game, "game-path", root_ok=True)
    except ConfigError:
        game_path = "unknown"
    document = {
        # For a fix the repair-not-demonstrated reason stays first, as on every other record.
        "format": rec.FORMAT, "decision": decision, "adapter": _adapter_name(adapter),
        "reasons": reasons[:1] + [_clip(reason)] + reasons[1:] if intent == "fix" else [_clip(reason)] + reasons,
        "pullRequest": pr, "game": {"path": game_path, "headTree": None, "baseTree": None},
        "checksFrom": checks_from, "checksChanged": {"specs": 0, "routes": 0}, "specs": [], "drafts": 0, "checkProblems": 0,
        **({"observers": {"rule": rec.BOTH, "visual": None}} if rule == rec.BOTH else {}),
        **({"intent": intent} if intent != "none" else {}), **({"repair": repair} if repair is not None else {}),
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
    p.add_argument("--game", required=True, help="the project folder, relative to --repo")
    p.add_argument("--adapter", default=DEFAULT_ADAPTER,
                   help=f"the engine adapter (harness/adapters.py) to verify on (default: {DEFAULT_ADAPTER}); "
                        "one with no verify path stops before anything is replayed, and the record says why")
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
    p.add_argument("--intent", default="none",
                   help="what the change says it is for: fix, change or none (default). A fix is accepted only "
                        "when a check failed before the change and passes after it, three times of three "
                        "(docs/ci-gate.md); anything else typed here is read as fix, the stricter path")
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
                            require_sandbox=args.require_sandbox, intent=args.intent, adapter=args.adapter)
    except ConfigError as exc:
        document = stopped_record(f"the gate's inputs cannot be used: {exc}", pr=pr, game=args.game,
                                  checks_from=checks_from, expectrail_commit=commit,
                                  require_sandbox=args.require_sandbox, intent=args.intent, adapter=args.adapter)
    except Exception as exc:  # noqa: BLE001 - a crash still leaves a record, so the comment says so
        traceback.print_exc()
        document = stopped_record(f"the gate stopped ({type(exc).__name__}); see the verify job's log", pr=pr,
                                  game=args.game, checks_from=checks_from, expectrail_commit=commit,
                                  require_sandbox=args.require_sandbox, intent=args.intent, adapter=args.adapter)
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
