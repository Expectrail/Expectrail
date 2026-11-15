"""Pixel checks across three jobs, so the observer's key and the change's code never meet (#286).

Under the pixel setting, ``run`` replays each pixel check's probe with frames and asks the observer about
every replay in the same process (expectrail/jit/run.py, ``_pixel_stage``). That is right offline, and
wrong in CI: the replays run the change's code, and asking SAM needs its key. jit.yml keeps the model key
away from the change's code by splitting jobs (the propose job holds the key and runs no game; the replay
jobs run the game and hold no secret). This module gives pixel checks the same split:

1. **Capture** (``run --observer sam-3.1-anchor --pixel-capture DIR``; runs the game, no secret). Every
   pixel check's probe is replayed with frames on the clean game, the bug build and the candidate,
   ``reps`` times each, whether or not the check will be kept (the candidate's frames are needed by the
   time the answers say so). Each replay is kept in ``DIR/<build>/<probe>-<n>/`` with the route it
   replayed (``route.json``): its replay.json, its trace.json and only the frames the observer will ask
   about (``store_replay``), so the folder the later jobs download is a few megabytes a replay, not the
   whole movie. Nothing is asked and nothing is judged: the pixel rows are
   ``not-run`` with the reason ``CAPTURED``. The trace checks run as always.
2. **Ask** (``python -m expectrail.jit.cli pixel-ask --replays DIR --out answers.json``; holds the key,
   runs no game). ``ask`` plans every stored replay's frames from its route, reserves all of their images
   against the budget before the first request, and asks SAM through the same observer the judging run
   uses (expectrail/jit/sam_observer.py), so the frames are checked against the replay's digests and the
   questions are the ones the judge will ask. It writes an agents/sam_anchor.py answer file with one run
   per replay, named ``<build>/<probe>-<n>``. It reads PNGs and JSON and never runs anything from the
   change. The first replay that cannot be asked about stops it (``stopped``), and nothing more is sent.
3. **Judge** (``run --observer sam-3.1-anchor --sam-answers answers.json --pixel-replays DIR``; runs the
   game, no secret). The trace checks replay as always. A pixel replay is not run again: ``StoredReplays``
   puts the captured folder in its place, after checking it is a replay of the route this run compiled.
   The observer then asks exactly what step 2 asked, and ``RecordedSamClient`` answers only those
   questions, so a replay missing from the answers, or captured differently, drops its checks; it never
   passes them. The record charges the images the answers stand for at the list price.

**The capture folder is untrusted.** It was written by a job that ran the change's code. ``ask`` and
``StoredReplays`` accept only the layout above (the three build names, ``<probe>-<n>`` folders holding
only what ``store_replay`` keeps, regular files, no symbolic link), and ``ask`` caps the replays it will look at (``MAX_REPLAYS``) and the images it
will send (the observer's ``MAX_FRAMES`` a replay, and the budget), so a forged folder can at most make it
ask about frames that the judging run then refuses.

**What the asking job may spend** (``budget_left``; ``python -m expectrail.jit.cli pixel-budget``): the
change's cap less what the capture run's record says was spent (the model's calls and the replays so far).
The record is untrusted too: it is read only if it is a valid ``jit-run`` record of at most 8 MiB with a
plain spend, and otherwise nothing is left, so nothing is asked. A forged record can lower what is left,
never raise it above the cap.

In jit.yml (under the pixel setting): replay-final is the capture, pixel-ask the asking (the key, in the
main-only environment), pixel-judge the judging.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from expectrail.jit import pixel

BUILDS = ("pixel-reference", "pixel-base", "pixel-candidate")   # the replay folders of expectrail/jit/run.py
REPLAY = re.compile(r"[a-z0-9][a-z0-9-]{0,80}-[1-9][0-9]?")
ROUTE_FILE = "route.json"
OBJECTS_FILE = "objects.json"   # what the observer is asked about on this replay, when it is more or less than the player
KEPT = ("replay.json", "trace.json")   # besides the route and the frames asked about: what the later jobs read
FRAME = "f{:08d}.png"                  # Movie Maker's frame names (harness/run.py)
FRAME_NAME = re.compile(r"f[0-9]{8}\.png")
MAX_REPLAYS = 3 * 3 * pixel.MAX_PIXEL_CHECKS   # three builds, three runs each, a probe per pixel check at most
CAPTURED = ("captured for the observer, not judged here: the frames are in the capture folder, for pixel-ask "
            "and then run --pixel-replays")


class StoreError(pixel.PixelError):
    """The capture folder is not one this module wrote, or not the replay this run needs."""


def _checked_tree(root: Path) -> None:
    """Refuse a folder holding anything but regular files and folders: a link could point anywhere."""
    if root.is_symlink() or not root.is_dir():
        raise StoreError(f"{root.name[:60]} is not a folder")
    for p in root.rglob("*"):
        if p.is_symlink():
            raise StoreError(f"{p.relative_to(root).as_posix()[:80]} is a symbolic link")
        if not (p.is_file() or p.is_dir()):
            raise StoreError(f"{p.relative_to(root).as_posix()[:80]} is not a regular file")


def store_replay(run_dir: Path, store: Path, route: dict, frames, objects=(), player: bool = True) -> Path:
    """Keep one replay folder (``.../<build>/<probe>-<n>``) in the capture folder, with its route: only
    what the later jobs read (``KEPT``) and, of the frames, only ``frames``, the ones the observer will ask
    about (``observer.frames(route)``). A frame the replay did not capture is not kept, and the observer
    treats it as it would on the full replay. Everything else (the game's working copy, the log, the
    sound, every frame not asked about) stays behind: on a bench probe that is most of the folder
    (docs/new-work/2026-11-15-trim-pixel-capture.md has the measurement). ``objects`` and ``player`` say
    what the observer is asked about (``asked_of``), when that is not the player alone."""
    run_dir = Path(run_dir)
    build, name = run_dir.parent.name, run_dir.name
    if build not in BUILDS or not REPLAY.fullmatch(name):
        raise StoreError(f"not a pixel replay folder: {build[:40]}/{name[:60]}")
    _checked_tree(run_dir)
    wanted = sorted({int(n) for n in frames})
    if any(n < 0 for n in wanted):
        raise StoreError("a frame number is 0 or more")
    dest = Path(store) / build / name
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "frames").mkdir(parents=True)
    for file in KEPT:
        if (run_dir / file).is_file():
            shutil.copyfile(run_dir / file, dest / file)
    for n in wanted:
        src = run_dir / "frames" / FRAME.format(n)
        if src.is_file():
            shutil.copyfile(src, dest / "frames" / FRAME.format(n))
    (dest / ROUTE_FILE).write_text(json.dumps(route, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    objects = sorted(objects)
    if not isinstance(player, bool):
        raise StoreError(f"{build}/{name}: whether the player is asked about is true or false")
    if not player and not objects:
        raise StoreError(f"{build}/{name}: the observer would be asked about nothing")
    if objects:
        _checked_objects(objects, f"{build}/{name}")
    if objects or not player:
        doc = {"objects": objects} if player else {"objects": objects, "player": False}
        (dest / OBJECTS_FILE).write_text(json.dumps(doc) + "\n", encoding="utf-8")
    return dest


def _checked_objects(objects, where: str) -> list[str]:
    allowed = pixel.OBSERVERS["sam-3.1-anchor"].get("boxes", ())
    if not isinstance(objects, list) or len(set(map(str, objects))) != len(objects) \
            or not all(isinstance(r, str) and r in allowed for r in objects):
        raise StoreError(f"{where}: the named objects are not a list of {', '.join(allowed)}, each once")
    return sorted(objects)


def asked_of(folder: Path) -> tuple[bool, list[str]]:
    """(player, objects): whether the capture said the observer is asked about the player on this replay,
    and the named roles it is asked about. Without the file: the player alone. The file is untrusted:
    ``{"objects": [...]}`` (the player too) or ``{"objects": [...], "player": false}``, only roles the
    observer is pointed at, each once, and never nothing at all."""
    path = Path(folder) / OBJECTS_FILE
    where = f"{folder.parent.name}/{folder.name}"
    if not path.exists():
        return True, []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StoreError(f"{where}: no readable {OBJECTS_FILE} ({type(exc).__name__})") from exc
    if not isinstance(doc, dict) or set(doc) not in ({"objects"}, {"objects", "player"}) \
            or doc.get("player", False) is not False:
        raise StoreError(f"{where}: {OBJECTS_FILE} is not {{objects}} or {{objects, player: false}}")
    objects = _checked_objects(doc["objects"], where)
    player = "player" not in doc
    if not player and not objects:
        raise StoreError(f"{where}: {OBJECTS_FILE} asks about nothing")
    return player, objects


def objects_of(folder: Path) -> list[str]:
    """The named roles the capture said the observer is asked about on this replay (``asked_of``)."""
    return asked_of(folder)[1]


def _checked_replay(folder: Path) -> None:
    """Refuse a replay folder holding anything but what store_replay keeps."""
    for p in folder.iterdir():
        if p.name in (*KEPT, ROUTE_FILE, OBJECTS_FILE) and p.is_file():
            continue
        if p.name == "frames" and p.is_dir():
            for f in p.iterdir():
                if not (f.is_file() and FRAME_NAME.fullmatch(f.name)):
                    raise StoreError(f"{folder.parent.name}/{folder.name}/frames holds {f.name[:60]!r}, "
                                     "which is not a kept frame")
            continue
        raise StoreError(f"{folder.parent.name}/{folder.name} holds {p.name[:60]!r}, which a kept replay does not")


def _route_of(folder: Path) -> dict:
    try:
        route = json.loads((folder / ROUTE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StoreError(f"{folder.parent.name}/{folder.name}: no readable {ROUTE_FILE} ({type(exc).__name__})") from exc
    ticks = route.get("ticks") if isinstance(route, dict) else None
    if not isinstance(route, dict) or not isinstance(route.get("name"), str) \
            or not isinstance(ticks, int) or isinstance(ticks, bool) or not 0 < ticks <= 100_000:
        raise StoreError(f"{folder.parent.name}/{folder.name}: {ROUTE_FILE} is not a route with a name and ticks")
    return route


def replays(store: Path) -> list[tuple[str, Path]]:
    """The stored replays as (``<build>/<probe>-<n>``, folder), in a fixed order. Anything else in the
    capture folder, or more replays than a run can make, refuses the whole folder."""
    store = Path(store)
    _checked_tree(store)
    found: list[tuple[str, Path]] = []
    tops = sorted(store.iterdir())
    for top in tops:
        if top.name not in BUILDS or not top.is_dir():
            raise StoreError(f"the capture folder holds {top.name[:60]!r}, which is not a build's replays")
    for top in sorted(tops, key=lambda t: BUILDS.index(t.name)):
        for folder in sorted(top.iterdir()):
            if not folder.is_dir() or not REPLAY.fullmatch(folder.name):
                raise StoreError(f"{top.name}/{folder.name[:60]} is not a replay folder")
            _checked_replay(folder)
            found.append((f"{top.name}/{folder.name}", folder))
    if not found:
        raise StoreError("the capture folder holds no replay")
    if len(found) > MAX_REPLAYS:
        raise StoreError(f"the capture folder holds {len(found)} replays; a run makes at most {MAX_REPLAYS}")
    return found


class StoredReplays:
    """A frame runner for ``run.generate`` that puts a captured replay folder where the replay would be
    made, instead of running the game. The folder must be the one for the same build and run number, and
    a replay of the same route (the route this run compiled, compared as data)."""

    def __init__(self, store):
        self.store = Path(store)

    def __call__(self, route_path, run_dir, patches=()):
        run_dir = Path(run_dir)
        build, name = run_dir.parent.name, run_dir.name
        if build not in BUILDS or not REPLAY.fullmatch(name):
            raise StoreError(f"no captured replay is kept for {build[:40]}/{name[:60]}")
        src = self.store / build / name
        if not src.is_dir():
            raise StoreError(f"the capture folder has no replay {build}/{name}")
        _checked_tree(src)
        _checked_replay(src)
        own = json.loads(Path(route_path).read_text(encoding="utf-8"))
        if _route_of(src) != own:
            raise StoreError(f"the captured replay {build}/{name} is not of the route this run compiled")
        if run_dir.exists():
            shutil.rmtree(run_dir)
        shutil.copytree(src, run_dir)


class AskRefused(pixel.PixelError):
    """Nothing was asked: the capture folder or the budget does not allow it."""


def ask(store: Path, observer, budget_usd: float, usd_per_image: float) -> dict:
    """Ask ``observer`` about every replay in the capture folder; the answer file (see the module docstring).

    All images are reserved first: if the stored replays' planned frames cost more than ``budget_usd`` at
    ``usd_per_image``, nothing is sent (AskRefused). An observer that refuses a replay or stops part way
    ends the asking there, and what it already sent is counted."""
    if not (isinstance(budget_usd, (int, float)) and budget_usd >= 0):
        raise AskRefused("the budget is a number of dollars, 0 or more")
    found = replays(store)
    planned = {}
    for name, folder in found:
        route = _route_of(folder)
        frames = list(observer.frames(route))
        if len(frames) > observer.max_frames:
            raise AskRefused(f"{name}: the observer planned {len(frames)} frames, more than its {observer.max_frames}")
        player, objects = asked_of(folder)
        planned[name] = (folder, route, frames, objects, player)
    # One image a planned frame for the player when it is asked about, and up to MAX_BOXES a planned frame
    # for each named role.
    images = sum(len(f) * pixel.images_per_frame(p, o) for _, _, f, o, p in planned.values())
    if images * usd_per_image > budget_usd + 1e-9:
        raise AskRefused(f"the {len(found)} replays need up to {images} images, ${images * usd_per_image:.4f}, "
                         f"over the budget of ${budget_usd:.2f}; nothing was asked")
    setting = observer.setting()
    runs, sent, stopped = [], 0, None
    for name, (folder, route, _, objects, player) in planned.items():
        try:
            got, run, n = pixel.observe(observer, folder, route, objects, player)
        except pixel.PixelError as exc:
            extra = getattr(exc, "images", 0)
            sent += extra if isinstance(extra, int) and not isinstance(extra, bool) and extra > 0 else 0
            stopped = f"{name}: {' '.join(str(exc).split())[:240]}"
            break
        sent += n
        if got != setting:
            stopped = f"{name}: the observer answered under another setting"
            break
        runs.append({**run, "run": name})
    doc = {"model": setting.get("model"), "lift": observer.lift,
           "box": observer.box if isinstance(observer.box, str) else list(observer.box),
           "pad": observer.pad if isinstance(observer.box, str) else None,
           "source": "expectrail.jit.pixel_jobs ask",
           "stats": {"replays": len(found), "plannedImages": images, "calls": sent,
                     "usd": round(sent * usd_per_image, 4), "usdPerImage": usd_per_image},
           "stopped": stopped, "runs": runs}
    if pixel.setting_of(doc) != setting:
        raise AskRefused("the answer file would not read back under the observer's setting")
    return doc


MAX_RECORD_BYTES = 8 * 1024 * 1024


def budget_left(record_path, budget_usd: float) -> tuple[float, str | None]:
    """(dollars the asking job may spend, why it is 0 or None). The change's cap less the capture record's
    ``spend.usd``, never below 0 and never above the cap; an unreadable record leaves 0 (see the module
    docstring)."""
    import math

    from expectrail.contracts import load_strict

    if not (isinstance(budget_usd, (int, float)) and not isinstance(budget_usd, bool)
            and math.isfinite(budget_usd) and budget_usd >= 0):
        return 0.0, "the cap is not a number of dollars, 0 or more"
    path = Path(record_path)
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_RECORD_BYTES:
            return 0.0, "the capture record is missing, a link, or over 8 MiB"
        record = load_strict(path, "jit-run")
        spent = record["spend"]["usd"]
    except Exception as exc:  # noqa: BLE001 - any unreadable record leaves nothing to spend
        return 0.0, f"the capture record cannot be read ({type(exc).__name__})"
    if not (isinstance(spent, (int, float)) and not isinstance(spent, bool) and math.isfinite(spent) and spent >= 0):
        return 0.0, "the capture record's spend is not a plain amount"
    left = max(0.0, float(budget_usd) - float(spent))
    return math.floor(left * 10000) / 10000, None if left > 0 else "the capture run spent the whole cap"

