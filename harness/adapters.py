"""Engine adapters: the one boundary between Expectrail and the engine that replays a route.

An adapter wraps the runner an engine already has (``harness/run.py`` for the Godot game,
``harness/web/run.py`` for the checkout page in Chromium) behind one signature, and carries the facts
about that engine that the fixer, the verifier and the tools would otherwise hard-code: where the
project lives, which folders are the engine's own caches, how frames are named, what the run's log is
called, which files a fix may edit by default, how a prompt names the project, which file suffixes
are text, and the capture and physics rates.

    from harness import adapters
    godot = adapters.get("godot")
    replay = godot.run(route, out, patches=[seed, candidate])

Every adapter's ``run`` has the same signature::

    run(route, out, patches=None, *, game=None, fps=None, capture_frames=True) -> replay document

``patches`` apply in order (seed first, then candidate) to a copy of ``game`` (default: the adapter's
``game_root``); ``fps=None`` means the adapter's own capture rate. A replay that fails raises
SystemExit, as ``harness.run.run`` always has and as the verifiers catch. The Godot runner can also
raise ``subprocess.CalledProcessError`` or ``OSError`` from its import and patch steps, and still
does: the wrapper passes them on unchanged, because callers retry on them. The web wrapper turns the
web harness's ``WebHarnessError`` into SystemExit, chained, so the original stays on ``__cause__``.

A new engine plugs in by building an ``Adapter`` in its own module and calling ``register``; the
shared verifier (``agents.domain_verifier``), the fixer and the harness tools then take it by name.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from harness import run as _godot

REPO = _godot.REPO

# Unity, for the adapter that comes next. Not registered: there is no Unity runner yet. These are the
# Unity project folders the editor rebuilds on its own (never part of a game's digest or a fixer's copy).
UNITY_IGNORE = ("Library", "Temp", "Logs", "obj", "UserSettings")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_digest(root: Path, ignore: tuple[str, ...] = ()) -> str:
    """A digest of every file under ``root``, skipping any file with a folder (or a name) in ``ignore``.

    Each file adds its path relative to ``root``, a NUL, its sha256 and a newline, in sorted path
    order: the same bytes ``harness.run.tree_digest`` hashes. The ignore list is matched against the
    path relative to ``root``. ``harness.run.tree_digest`` matches ``.godot`` against the whole path,
    so the two differ only for a root that itself sits inside a folder named ``.godot``, where that
    function hashes no file at all.
    """
    root = Path(root)
    skip = set(ignore)
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and not skip.intersection(p.relative_to(root).parts)):
        h.update(path.relative_to(root).as_posix().encode() + b"\0" + sha256_file(path).encode() + b"\n")
    return h.hexdigest()


@dataclass(frozen=True)
class Adapter:
    """One engine, as everything outside the harness sees it."""

    name: str
    """The registry key and the ``--adapter`` value: ``godot``, ``web``."""
    engine: str
    """What the engine's replay document records as ``engine.name`` (contracts/replay.schema.json)."""
    run: Callable[..., dict]
    """``run(route, out, patches=None, *, game=None, fps=None, capture_frames=True) -> replay``."""
    game_root: Path
    """The clean project a replay copies and a fix is made against."""
    ignore: tuple[str, ...]
    """Folders the engine writes for itself, left out of the tree digest and of the fixer's copies."""
    frame_pattern: str
    """Where a replay's frames are, relative to its output folder, printf style."""
    log_name: str | None
    """The engine's log in a replay's output folder, given to the fixer; None when it writes none."""
    editable: tuple[str, ...]
    """The files a fix may change by default, as globs relative to ``game_root``."""
    prompt_subject: str
    """How a prompt names the project: "You are fixing {prompt_subject} bug."."""
    text_suffixes: frozenset[str]
    """Suffixes of the project's text files: what export_scan reads to learn the clean lines."""
    capture_fps: int | None
    """Frames captured per second of game time; None when frames are taken per step, not per second."""
    ticks_per_second: int | None
    """Physics ticks per second, the unit routes count in; None when routes count steps."""
    trace_format: str
    """The ``format`` of the engine-side trace each replay writes to ``trace.json``."""
    default_route: Path
    """The route a tool replays when it is given none."""
    bugs: Path
    """The public seeded bugs, ``<bugs>/<family>/vN.patch``."""
    trace_state: Callable[[dict], object]
    """The part of one trace row two replays of a route must agree on (harness.replay_check)."""

    def tree_digest(self, root: Path | None = None) -> str:
        """The digest that names the project a replay ran: ``root`` (default ``game_root``)."""
        return tree_digest(self.game_root if root is None else root, self.ignore)

    def frames(self, out: Path) -> list[Path]:
        """A replay's frames in ``out``, in order."""
        return sorted(Path(out).glob(re.sub(r"%0?\d*d", "*", self.frame_pattern)))


# Godot ----------------------------------------------------------------------------------------------

GODOT_CAPTURE_FPS = 60  # harness/run.py's --fps default: Movie Maker writes one frame each 1/60 s
GODOT_TICKS_PER_SECOND = 120  # the demo's physics rate (docs/contracts.md, Frames and ticks)


def _godot_run(route: Path, out: Path, patches: list[Path] | None = None, *, game: Path | None = None,
               fps: int | None = None, capture_frames: bool = True) -> dict:
    # harness.run.run is looked up at call time, so a test can replace it.
    return _godot.run(Path(route), Path(out), patches=None if patches is None else list(patches), game=game,
                      fps=GODOT_CAPTURE_FPS if fps is None else fps, capture_frames=capture_frames)


def _godot_state(row: dict) -> object:
    return row.get("player")


GODOT = Adapter(
    name="godot",
    engine="godot",
    run=_godot_run,
    game_root=REPO / "game" / "platformer",
    ignore=(".godot",),
    frame_pattern="frames/f%08d.png",
    log_name="godot.log",
    editable=("player/**", "level/**", "game_singleplayer.tscn"),
    prompt_subject="a Godot 4 2D platformer",
    text_suffixes=frozenset({".tscn", ".tres", ".gd", ".godot", ".cfg", ".import"}),
    capture_fps=GODOT_CAPTURE_FPS,
    ticks_per_second=GODOT_TICKS_PER_SECOND,
    trace_format="expectrail.trace/v0",
    default_route=REPO / "harness" / "routes" / "smoke.json",
    bugs=REPO / "bugs",
    trace_state=_godot_state,
)


# Web: the checkout page in Chromium -----------------------------------------------------------------

def _web_run(route: Path, out: Path, patches: list[Path] | None = None, *, game: Path | None = None,
             fps: int | None = None, capture_frames: bool = True) -> dict:
    if fps is not None:
        raise ValueError("the web harness saves one frame after each step; it takes no frame rate")
    if not capture_frames:
        raise ValueError("the web harness always saves its frames")
    from harness.web import run as web  # looked up at call time, so a test can replace it

    try:
        return web.run(Path(route), Path(out), patches=None if patches is None else list(patches), app=game)
    except web.WebHarnessError as exc:
        raise SystemExit(str(exc)) from exc


def _web_state(row: dict) -> object:
    return row


WEB = Adapter(
    name="web",
    engine="chromium",
    run=_web_run,
    game_root=REPO / "apps" / "checkout" / "site",
    ignore=(),
    frame_pattern="frames/f%08d.png",
    log_name=None,
    editable=("checkout/index.html", "checkout/checkout.css", "checkout/checkout.js"),
    prompt_subject="a web checkout page",
    text_suffixes=frozenset({".html", ".css", ".js"}),
    capture_fps=None,
    ticks_per_second=None,
    trace_format="expectrail.web-trace/v0",
    default_route=REPO / "harness" / "web" / "routes" / "checkout-desktop.json",
    bugs=REPO / "apps" / "checkout" / "bugs",
    trace_state=_web_state,
)


# Registry -------------------------------------------------------------------------------------------

_REGISTRY: dict[str, Adapter] = {}


def register(adapter: Adapter, *, replace: bool = False) -> Adapter:
    """Add an adapter under its name. A second adapter with a taken name is refused unless ``replace``."""
    if adapter.name in _REGISTRY and not replace and _REGISTRY[adapter.name] is not adapter:
        raise ValueError(f"an adapter named {adapter.name!r} is already registered")
    _REGISTRY[adapter.name] = adapter
    return adapter


def unregister(name: str) -> None:
    """Remove an adapter (for tests that register their own)."""
    _REGISTRY.pop(name, None)


def get(name: str) -> Adapter:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"no adapter named {name!r}; registered: {', '.join(names())}") from None


def names() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def resolve(adapter: str | Adapter) -> Adapter:
    """An adapter given by name or as itself."""
    return adapter if isinstance(adapter, Adapter) else get(adapter)


register(GODOT)
register(WEB)
