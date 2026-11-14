"""Pixel checks across three jobs, so the observer's key and the change's code never meet (#286).

Under the pixel setting, ``run`` replays each pixel check's probe with frames and asks the observer about
every replay in the same process (expectrail/jit/run.py, ``_pixel_stage``). That is right offline, and
wrong in CI: the replays run the change's code, and asking SAM needs its key. jit.yml keeps the model key
away from the change's code by splitting jobs (the propose job holds the key and runs no game; the replay
jobs run the game and hold no secret). This module gives pixel checks the same split:

1. **Capture** (``run --observer sam-3.1-anchor --pixel-capture DIR``; runs the game, no secret). Every
   pixel check's probe is replayed with frames on the clean game, the bug build and the candidate,
   ``reps`` times each, whether or not the check will be kept (the candidate's frames are needed by the
   time the answers say so). Each replay folder is copied into ``DIR/<build>/<probe>-<n>/`` with the
   route it replayed (``route.json``). Nothing is asked and nothing is judged: the pixel rows are
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
``StoredReplays`` accept only the layout above (the three build names, ``<probe>-<n>`` folders, regular
files, no symbolic link), and ``ask`` caps the replays it will look at (``MAX_REPLAYS``) and the images it
will send (the observer's ``MAX_FRAMES`` a replay, and the budget), so a forged folder can at most make it
ask about frames that the judging run then refuses.

What this is not, yet: jit.yml does not run these steps. The asking job needs SAM's key in the main-only
environment, and only Sean may give a job a secret (AGENTS.md).
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


def store_replay(run_dir: Path, store: Path, route: dict) -> Path:
    """Copy one replay folder (``.../<build>/<probe>-<n>``) into the capture folder, with its route."""
    run_dir = Path(run_dir)
    build, name = run_dir.parent.name, run_dir.name
    if build not in BUILDS or not REPLAY.fullmatch(name):
        raise StoreError(f"not a pixel replay folder: {build[:40]}/{name[:60]}")
    _checked_tree(run_dir)
    dest = Path(store) / build / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(run_dir, dest)
    (dest / ROUTE_FILE).write_text(json.dumps(route, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return dest


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
        planned[name] = (folder, route, frames)
    images = sum(len(f) for _, _, f in planned.values())
    if images * usd_per_image > budget_usd + 1e-9:
        raise AskRefused(f"the {len(found)} replays need up to {images} images, ${images * usd_per_image:.4f}, "
                         f"over the budget of ${budget_usd:.2f}; nothing was asked")
    setting = observer.setting()
    runs, sent, stopped = [], 0, None
    for name, (folder, route, _) in planned.items():
        try:
            got, run, n = pixel.observe(observer, folder, route)
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
