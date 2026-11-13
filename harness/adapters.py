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

The verify path (``expectrail verify``, the CI gate, the orchestrator's engines) takes its engine
from here too. An adapter that can be verified gives ``verify_run``, the replay a verification makes,
which also takes the sandbox mode and the checkout a link in the game may lead into::

    verify_run(route, out, *, game, capture_frames, sandbox=None, within=None) -> replay document

and ``project_file``, ``title`` and ``missing``, which say how a project folder is recognised, how
a message names the engine, and what a run on this machine lacks. An adapter without ``verify_run``
has no verify path: asked to verify with it, the gate and the orchestrator refuse and run nothing.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from harness import run as _godot
from harness import tree as _tree

REPO = _godot.REPO

# Unity (the adapter is below, its runner harness/unity/run.py). These are the Unity project folders
# the editor rebuilds on its own (never part of a game's digest or a fixer's copy).
UNITY_IGNORE = ("Library", "Temp", "Logs", "obj", "UserSettings")
# Unity's text files, with the editor's asset serialization set to Force Text: scripts, scenes,
# prefabs, assets, their .meta files, assembly definitions, input actions and shaders.
UNITY_TEXT_SUFFIXES = frozenset({".cs", ".unity", ".prefab", ".asset", ".meta", ".asmdef", ".inputactions", ".shader"})


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_digest(root: Path, ignore: tuple[str, ...] = ()) -> str:
    """A digest of every file under ``root``, skipping any file with a folder (or a name) in ``ignore``.

    Each file adds its path relative to ``root``, a NUL, its sha256 and a newline, in sorted path
    order: the same bytes ``harness.run.tree_digest`` hashes, from the same walk (``harness.tree``).
    Links are followed and may not leave ``root``; see that module for the rules.
    """
    return _tree.digest(Path(root), skip=tuple(ignore))


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
    # What the verify path asks. Each has a default, so an adapter that says nothing has no verify path.
    verify_run: Callable[..., dict] | None = None
    """``verify_run(route, out, *, game, capture_frames, sandbox=None, within=None) -> replay``: the
    replay a verification makes. ``game`` is always given (no default project). It writes
    ``trace.json`` and ``replay.json`` in ``out`` and the frames under ``frame_pattern``; the document
    it returns says which tree it ran (``game.tree``) and how it was isolated (``isolation``). None
    when nothing verifies on this engine yet."""
    project_file: str | None = None
    """The file every project of this engine has at its root (``project.godot``): how the verify
    path tells a project folder from any other folder. None when no one file says so."""
    title: str = ""
    """The engine's name in a sentence a person reads: "no Godot project at ...". Empty: ``name``."""
    missing: Callable[[], list[str]] | None = None
    """``missing() -> [sentence]``: what a verification needs and this machine lacks, each with its
    fix, checked the way a run uses it. None when the adapter cannot tell, and then nothing is
    reported before the run."""

    def can_verify(self) -> bool:
        """Whether the verify path can run on this engine."""
        return self.verify_run is not None

    def is_project(self, root: Path) -> bool:
        """Whether ``root`` is a project of this engine: a folder that holds ``project_file``. An
        adapter with no ``project_file`` recognises no folder: it is never guessed."""
        root = Path(root)
        return self.project_file is not None and root.is_dir() and (root / self.project_file).is_file()

    def label(self) -> str:
        """How a sentence names the engine."""
        return self.title or self.name

    def tree_digest(self, root: Path | None = None, within: Path | None = None) -> str:
        """The digest that names the project a replay ran: ``root`` (default ``game_root``).
        ``within`` is the folder a link in the project may lead into (default: ``root`` itself);
        ``harness.tree.TreeProblem`` for a link that leaves it, loops or leads nowhere."""
        return _tree.digest(Path(self.game_root if root is None else root), within=within, skip=tuple(self.ignore))

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


def _godot_verify_run(route: Path, out: Path, *, game: Path, capture_frames: bool, sandbox: str | None = None,
                      within: Path | None = None) -> dict:
    # The same runner as _godot_run, looked up at call time, with what a verification adds: the
    # sandbox mode and the checkout a link may lead into. The game is the caller's, never a default.
    if game is None:
        raise ValueError("a verification names its game; there is no default project")
    return _godot.run(Path(route), Path(out), game=Path(game), capture_frames=capture_frames, sandbox=sandbox,
                      within=within)


def _godot_missing() -> list[str]:
    # The list `expectrail doctor` reports, checked by the same functions (expectrail.doctor.for_run),
    # so `doctor` and a run cannot disagree about a tool.
    from expectrail import doctor

    return [f"{c.found}. Fix: {c.fix}" for c in doctor.missing(doctor.for_run())]


def _godot_state(row: dict) -> object:
    return row.get("player")


GODOT = Adapter(
    name="godot",
    engine="godot",
    run=_godot_run,
    game_root=REPO / "game" / "platformer",
    ignore=_tree.GODOT_SKIP,
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
    verify_run=_godot_verify_run,
    project_file="project.godot",
    title="Godot",
    missing=_godot_missing,
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


# Unity: Platformio in a player built with the Expectrail harness ------------------------------------

UNITY_TICKS_PER_SECOND = 50  # Platformio's Fixed Timestep, 0.02 s; one captured frame per tick


def _unity_run(route: Path, out: Path, patches: list[Path] | None = None, *, game: Path | None = None,
               fps: int | None = None, capture_frames: bool = True) -> dict:
    # The player comes from $EXPECTRAIL_UNITY_PLAYER (a build folder, or a folder of them): a Unity
    # game is built before it runs, and run() refuses a player built from other files.
    from harness.unity import run as unity  # looked up at call time, so a test can replace it

    return unity.run(Path(route), Path(out), None if patches is None else list(patches), game=game, fps=fps,
                     capture_frames=capture_frames)


def _unity_state(row: dict) -> object:
    return row


UNITY = Adapter(
    name="unity",
    engine="unity",
    run=_unity_run,
    game_root=REPO / "game" / "unity-platformer",
    ignore=UNITY_IGNORE,
    frame_pattern="frames/f%08d.png",
    log_name="unity.log",
    # A default until a patch policy for Unity fixes is agreed: the game's own assets and scripts, and
    # the 2D physics settings one seeded-bug family edits.
    editable=("Assets/_Project/**", "ProjectSettings/Physics2DSettings.asset"),
    prompt_subject="a Unity 6 2D platformer",
    text_suffixes=UNITY_TEXT_SUFFIXES,
    capture_fps=UNITY_TICKS_PER_SECOND,
    ticks_per_second=UNITY_TICKS_PER_SECOND,
    trace_format="expectrail.trace/v0",
    default_route=REPO / "harness" / "routes" / "unity-smoke.json",
    bugs=REPO / "bugs" / "unity-platformer",
    trace_state=_unity_state,
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


def verifying() -> tuple[str, ...]:
    """The adapters the verify path can run on, by name."""
    return tuple(name for name in names() if _REGISTRY[name].can_verify())


def resolve(adapter: str | Adapter) -> Adapter:
    """An adapter given by name or as itself."""
    return adapter if isinstance(adapter, Adapter) else get(adapter)


register(GODOT)
register(WEB)
register(UNITY)
