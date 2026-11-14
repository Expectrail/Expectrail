"""Run one route through the game and capture what a player would see.

    python3 -m harness.run --route harness/routes/smoke.json --out runs/smoke [--patch bugs/x/v1.patch]

The game under test is copied into <out>/work, a seeded-bug patch is applied there if given, and the
harness autoload is added to the copy only. Godot renders every frame through Movie Maker mode
(fixed frame rate, non-real time, so a slow machine gives the same frames, more slowly). Output:
<out>/frames/f00000000.png ..., <out>/trace.json (ground truth, for checking the evaluator, never
shown to the fixer) and <out>/replay.json (expectrail.replay/v0).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from expectrail import timing
from harness import sandbox as box
from harness import tree

REPO = Path(__file__).resolve().parent.parent
GODOT_VERSION = "4.7.2-stable"
AUTOLOAD = 'ExpectrailHarness="*res://expectrail_harness.gd"'


def tools_dir() -> Path:
    """Where the engine download and the import cache are kept: $EXPECTRAIL_TOOLS if set; ``tools/``
    in a clone; and for an installed copy (the harness is then inside the package, under
    ``_bundle``) the user's cache folder, since the place a package is installed is not one to
    write into and is often read-only."""
    named = os.environ.get("EXPECTRAIL_TOOLS")
    if named:
        return Path(named)
    if REPO.name == "_bundle":
        return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "expectrail"
    return REPO / "tools"


DEFAULT_CACHE_DIR = tools_dir() / "godot_cache" / ".godot"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_godot() -> Path:
    env = os.environ.get("EXPECTRAIL_GODOT")
    if env:
        return Path(env)
    if sys.platform == "darwin":
        mac_binary = REPO / "tools" / "godot_mac" / "Godot.app" / "Contents" / "MacOS" / "Godot"
        if mac_binary.is_file():
            return mac_binary
        out = subprocess.run([str(REPO / "harness" / "macos" / "get_godot_mac.sh")], check=True, capture_output=True, text=True)
        return Path(out.stdout.strip().splitlines()[-1])
    # Run with bash by name: an installed copy's script may have lost its executable bit. It is told
    # where to keep the engine, so a clone and an installed copy use the one rule (tools_dir).
    out = subprocess.run(["bash", str(REPO / "harness" / "get_godot.sh")], check=True, capture_output=True, text=True,
                         env={**os.environ, "EXPECTRAIL_TOOLS": str(tools_dir())})
    return Path(out.stdout.strip().splitlines()[-1])


def get_cache_dir() -> Path:
    env = os.environ.get("EXPECTRAIL_GODOT_CACHE")
    if env:
        p = Path(env)
        return p if p.name == ".godot" else p / ".godot"
    return tools_dir() / "godot_cache" / ".godot"


def cache_key(game: Path, godot: Path, within: Path | None = None, game_tree: str | None = None) -> str:
    """Identify what an import cache was built from: the Godot binary and the exact game files.

    A cache built by another Godot build (another version, or the macOS editor) or from a game
    tree that has since changed is stale and must not be reused for a run.
    """
    st = godot.resolve().stat()
    h = hashlib.sha256()
    h.update(f"{GODOT_VERSION}\0{godot.resolve()}\0{st.st_size}\0{st.st_mtime_ns}\0".encode())
    h.update((game_tree or tree_digest(game, within)).encode())
    return h.hexdigest()


def _key_file(cache_dir: Path) -> Path:
    # Kept beside the cache, not inside it, so the key never lands in a run's .godot/.
    return cache_dir.with_name(cache_dir.name + ".key")


def godot_import(godot: Path, project: Path, env: dict, tool: box.Tool | None = None,
                 timeout: float = 600) -> subprocess.CompletedProcess:
    """Godot's import step on a game copy, inside the sandbox when there is one: importing runs the
    project's own import code, so it is the candidate's code as much as the replay is."""
    if tool is None:
        return subprocess.run([str(godot), "--headless", "--path", str(project), "--import"], check=True,
                              capture_output=True, text=True, env=env, timeout=timeout)
    with tempfile.TemporaryDirectory(prefix="expectrail-import-") as nowhere:
        done = box.run(tool, [box.ENGINE_BINARY, "--headless", "--path", box.GAME, "--import"],
                       timeout=timeout, game=project, out=Path(nowhere), engine=godot, env=env)
    if done.returncode != 0:
        raise subprocess.CalledProcessError(done.returncode, done.args, done.stdout, done.stderr)
    return done


def ensure_import_cache(game: Path, godot: Path, env: dict, tool: box.Tool | None = None,
                        within: Path | None = None, game_tree: str | None = None) -> Path | None:
    """Return an import cache built from exactly this game and Godot binary, warming it if needed.

    Only the external cache directory is used, and only when its key matches. An import folder
    inside the clean game itself (left by the editor or a local play session) is never trusted.
    Warming happens in a private staging folder and is swapped in at the end, so parallel runs
    cannot see a half-built cache; any failure falls back to a normal full import (slower, same
    frames).

    ``game_tree`` is the game's digest when the caller has already taken it (a replay has): the key
    is made from it, and a cache is stored only when the copy it was imported from is that tree. If
    the folder changed between the digest and the copy, the cache would hold another game's imports
    under this game's key and a later replay would reuse it; it is thrown away instead.
    """
    cache_dir = get_cache_dir()
    game_tree = game_tree or tree_digest(game, within)
    key = cache_key(game, godot, within, game_tree)
    key_file = _key_file(cache_dir)
    if (cache_dir / "imported").is_dir() and key_file.is_file() \
            and key_file.read_text(encoding="utf-8").strip() == key:
        return cache_dir

    staging = None
    try:
        cache_dir.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="staging-", dir=cache_dir.parent))
        copy = staging / "game"
        if tree.copy(game, copy, within=within, skip=tree.GODOT_SKIP) != game_tree:
            print("harness: warning: the game folder changed while its import cache was being made; "
                  "no cache is stored and this run imports directly", file=sys.stderr)
            return None
        godot_import(godot, copy, env, tool)
        if not (copy / ".godot" / "imported").is_dir():
            return None
        if cache_dir.exists():
            retired = staging / "retired"
            cache_dir.rename(retired)
        (copy / ".godot").rename(cache_dir)
        key_file.write_text(key + "\n", encoding="utf-8")
        return cache_dir
    except Exception as exc:
        print(f"harness: warning: cache warming failed ({exc}); falling back to direct import",
              file=sys.stderr)
        return None
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def tree_digest(root: Path, within: Path | None = None) -> str:
    """A digest of the game at ``root``, so a replay names the exact game it ran: the files the
    replay's copy holds (``harness.tree``), no more and no fewer. Raises ``tree.TreeProblem`` for a
    link that leaves ``within`` (default: the game folder), loops or leads nowhere."""
    return tree.digest(root, within=within, skip=tree.GODOT_SKIP)


def apply_patches(work: Path, patches: list[Path]) -> None:
    """Apply unified diffs in order to a game copy (seed first, then candidate, …)."""
    for patch in patches:
        subprocess.run(
            ["patch", "-p1", "--forward", "--batch", "-d", str(work), "-i", str(patch.resolve())],
            check=True, capture_output=True, text=True,
        )


def prepare(game: Path, work: Path, patch: Path | None = None, patches: list[Path] | None = None,
            cache: Path | None = None, within: Path | None = None) -> str:
    """Make the copy of the game a replay runs: exactly the files its digest is taken over
    (``harness.tree``), then the import cache, the patches and the harness's own two scripts.
    Returns the digest of the game files as they were copied, before anything was added."""
    if work.exists():
        shutil.rmtree(work)
    copied = tree.copy(game, work, within=within, skip=tree.GODOT_SKIP)
    if cache and (cache / "imported").is_dir():
        shutil.copytree(cache, work / ".godot")
    ordered = list(patches) if patches is not None else ([patch] if patch is not None else [])
    apply_patches(work, ordered)
    for name in ("expectrail_harness.gd", "expectrail_recorder.gd"):
        shutil.copy(REPO / "harness" / "godot" / name, work / name)
    project = (work / "project.godot").read_text(encoding="utf-8")
    if "[autoload]" in project:
        project = project.replace("[autoload]\n", "[autoload]\n\n" + AUTOLOAD + "\n", 1)
    else:
        project += "\n[autoload]\n\n" + AUTOLOAD + "\n"
    (work / "project.godot").write_text(project, encoding="utf-8")
    return copied


# The patched game is the candidate's code: a fix can change any script under the editable globs,
# and GDScript can read its environment (OS.get_environment) and open network connections. It runs
# on the verifier's machine, whose environment holds the SAM key, the Muse key in a live loop and
# the path to the private held-out set. So Godot gets only what it and the virtual display need.
GAME_ENV_KEEP = frozenset({"PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LANGUAGE", "TZ", "TMPDIR",
                           "DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "LIBGL_ALWAYS_SOFTWARE", "GALLIUM_DRIVER",
                           # llvmpipe's instruction set, held the same on every runner (harness/unity/run.py).
                           "GALLIUM_OVERRIDE_CPU_CAPS",
                           # The id of the verification job this replay belongs to (a random number, no
                           # secret): the orchestrator finds a lost worker's processes by it.
                           "EXPECTRAIL_JOB"})
GAME_ENV_PREFIXES = ("LC_", "XDG_", "MESA_", "LP_", "__GLX_", "__EGL_")


def game_env(source: dict | None = None) -> dict:
    """The environment for a Godot process: the display and rendering variables, nothing secret."""
    source = os.environ if source is None else source
    env = {k: v for k, v in source.items() if k in GAME_ENV_KEEP or k.startswith(GAME_ENV_PREFIXES)}
    env.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
    return env


def godot_cmd(godot: Path, display: bool) -> list[str]:
    cmd = [str(godot)]
    if not display and sys.platform != "darwin":
        cmd = ["xvfb-run", "-a", "-s", "-screen 0 1920x1080x24"] + cmd
    return cmd


def run(route: Path, out: Path, patch: Path | None = None, game: Path | None = None, fps: int | None = 60,
        godot: Path | None = None, patches: list[Path] | None = None,
        force_import: bool = False, capture_frames: bool = True, sandbox: str | None = None,
        within: Path | None = None) -> dict:
    """Replay one route and write trace.json and replay.json (and the frames, unless capture_frames is
    False: discovery reads only the trace, so it runs headless and skips writing a PNG per frame).

    ``sandbox`` is ``auto``, ``require`` or ``off`` (default: $EXPECTRAIL_SANDBOX, else ``auto``); see
    ``harness.sandbox``. What was in force is written to replay.json as ``isolation``.

    ``within`` is the folder a link in the game may lead into (default: the game folder itself; a
    caller that verifies a checkout passes the checkout). A link that leaves it, loops or leads
    nowhere stops the replay before anything is copied or run."""
    game = game or REPO / "game" / "platformer"
    # A config that exists is the game's settings. fps is None when the verify path wants that
    # rate instead of the number in this file. The bindings go to the harness as values: inside
    # the sandbox the game is a copy, and a path from this machine would not be there.
    from expectrail.project_config import ProjectConfigError, harness_arguments, read_game

    try:
        config = read_game(game)
    except ProjectConfigError as exc:
        raise SystemExit(str(exc)) from exc
    if fps is None:
        fps = int(config["captureFps"]) if config is not None else 60
    godot = godot or find_godot()
    out.mkdir(parents=True, exist_ok=True)
    work, frames = out / "work", out / "frames"
    ordered = list(patches) if patches is not None else ([patch] if patch is not None else [])
    try:
        tool, isolation = box.choose(sandbox, display=capture_frames)
    except box.SandboxError as exc:
        raise SystemExit(str(exc)) from exc
    try:
        game_tree = tree_digest(game, within)
    except tree.TreeProblem as exc:
        raise SystemExit(f"the game cannot be replayed as it stands: {exc}") from exc
    env = game_env()
    # Wall time per step, for the verifier's timing.json (expectrail.timing); nothing here reads it back.
    timing.count_run()
    with timing.phase("import-cache"):
        cache = ensure_import_cache(game, godot, env, tool, within, game_tree)
    staging = out / "sandbox"  # the one folder the sandboxed game can write to, besides its own copy
    with timing.phase("prepare"):
        try:
            copied = prepare(game, work, patches=ordered, cache=cache, within=within)
        except tree.TreeProblem as exc:
            raise SystemExit(f"the game cannot be replayed as it stands: {exc}") from exc
        if copied != game_tree:
            # The folder was read once for the digest (and the import cache's key) and once for the
            # copy. A replay names exactly the game it ran, or it does not run.
            shutil.rmtree(work, ignore_errors=True)
            raise SystemExit("the game folder changed while the replay was being set up: the copy made for "
                             f"this replay ({copied[:12]}) is not the game read at the start ({game_tree[:12]}). "
                             "Nothing was run.")
        if frames.exists():
            shutil.rmtree(frames)
        frames.mkdir()
        (out / "trace.json").unlink(missing_ok=True)  # a trace left by an earlier run is not this run's
        if staging.exists():
            shutil.rmtree(staging)
        if tool is not None:
            (staging / "frames").mkdir(parents=True)
    route_doc = json.loads(route.read_text(encoding="utf-8"))

    # If the clean cache is populated and no patches modified assets, skip --import (~7s savings).
    # Patched runs run an incremental --import, which finishes in ~0.2s since all base assets are cached.
    needs_import = force_import or (not cache) or bool(ordered) or not (work / ".godot" / "imported").is_dir()
    if needs_import:
        try:
            with timing.phase("import"):
                godot_import(godot, work, env, tool)
        except subprocess.TimeoutExpired as exc:
            (out / "godot.log").write_text((exc.stdout or "") + (exc.stderr or "") + "\nimport timed out\n",
                                           encoding="utf-8")
            raise SystemExit(f"godot import timed out; see {out / 'godot.log'}") from exc
    if tool is not None:
        # Inside, the game sees these paths and never the host's; the display is started inside too.
        engine, project, movie = box.ENGINE_BINARY, box.GAME, f"{box.OUT}/frames/f.png"
        route_arg, trace_arg = f"{box.INPUTS}/route.json", f"{box.OUT}/trace.json"
        shown = godot_cmd(Path(engine), False)
    else:
        engine, project, movie = str(godot), str(work), str((frames / "f.png").resolve())
        route_arg, trace_arg = str(route.resolve()), str((out / "trace.json").resolve())
        shown = godot_cmd(godot, bool(os.environ.get("DISPLAY")))
    if capture_frames:
        cmd = shown + ["--path", project, "--audio-driver", "Dummy", "--rendering-driver", "opengl3",
                       "--write-movie", movie, "--fixed-fps", str(fps)]
    else:
        cmd = [engine, "--headless", "--path", project, "--audio-driver", "Dummy", "--fixed-fps", str(fps)]
    cmd += ["--disable-vsync", "--", f"--route={route_arg}", f"--trace={trace_arg}",
            f"--seed={route_doc.get('seed', 1)}"]
    if config is not None:
        cmd += harness_arguments(config)
    try:
        with timing.phase("replay"):
            if tool is not None:
                proc = box.run(tool, cmd, timeout=1800, game=work, out=staging, engine=godot, env=env,
                               inputs={"route.json": route})
            else:
                proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=1800)
    except subprocess.TimeoutExpired as exc:
        (out / "godot.log").write_text((exc.stdout or "") + (exc.stderr or "") + "\ncapture timed out\n",
                                       encoding="utf-8")
        raise SystemExit(f"godot capture timed out; see {out / 'godot.log'}") from exc
    (out / "godot.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if tool is not None:
        try:
            box.collect(staging, out, frames=capture_frames)
        except box.SandboxError as exc:
            raise SystemExit(f"the replay's output was refused: {exc}") from exc
    if proc.returncode != 0 or not (out / "trace.json").exists():
        raise SystemExit(f"godot failed ({proc.returncode}); see {out / 'godot.log'}")
    with timing.phase("record"):
        replay = _replay_record(route, out, game_tree, fps, ordered, route_doc, proc.stdout + proc.stderr, frames,
                                isolation)
    return replay


def _replay_record(route: Path, out: Path, game_tree: str, fps: int, ordered: list[Path], route_doc: dict, log: str,
                   frames: Path, isolation: dict) -> dict:
    """Hash the frames and the trace and write replay.json."""
    device = re.search(r"Using Device: (.+)", log)
    version = re.search(r"Godot Engine v(\S+)", log)
    pngs = sorted(frames.glob("f*.png"))
    trace = json.loads((out / "trace.json").read_text(encoding="utf-8"))
    primary = ordered[0] if ordered else None
    replay = {
        "format": "expectrail.replay/v0",
        "route": {"name": route_doc.get("name", route.stem), "sha256": sha256_file(route)},
        # The digest of the bytes this replay's copy was made from (harness.tree.copy).
        "game": {"tree": game_tree,
                 "patch": ",".join(str(p) for p in ordered) if ordered else None,
                 "patchSha256": sha256_file(primary) if primary and len(ordered) == 1 else (
                     None if not ordered else hashlib.sha256(
                         b"".join(sha256_file(p).encode() for p in ordered)).hexdigest())},
        "engine": {"name": "godot", "version": version.group(1) if version else GODOT_VERSION,
                   "renderer": "opengl3", "device": device.group(1).strip() if device else None},
        "capture": {"fps": fps, "physicsTicksPerSecond": trace.get("physicsTicksPerSecond"),
                    "frames": len(pngs), "pattern": "frames/f%08d.png"},
        "frameSha256": [sha256_file(p) for p in pngs],
        "trace": {"path": "trace.json", "sha256": sha256_file(out / "trace.json")},
        "isolation": isolation,
    }
    (out / "replay.json").write_text(json.dumps(replay, indent=2) + "\n", encoding="utf-8")
    return replay


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--route", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--patch", type=Path, action="append", default=[],
                   help="patch to apply (repeatable; order is seed then candidate)")
    p.add_argument("--game", type=Path, help="game directory (default: game/platformer)")
    p.add_argument("--fps", type=int, default=None,
                   help="capture frames per second (default: the project config's captureFps, else 60)")
    p.add_argument("--warm-cache", action="store_true",
                   help="warm the .godot/ import cache and exit")
    p.add_argument("--sandbox", choices=box.MODES,
                   help="auto: isolate the game when this machine can, and record why not otherwise "
                        "(default, or $EXPECTRAIL_SANDBOX); require: refuse to run without it; off")
    p.add_argument("--force-import", action="store_true",
                   help="force full godot --import even if cache is present")
    args = p.parse_args(argv)
    if args.warm_cache:
        game = args.game or REPO / "game" / "platformer"
        godot = find_godot()
        env = game_env()
        try:
            tool, _isolation = box.choose(args.sandbox, display=False)
        except box.SandboxError as exc:
            raise SystemExit(str(exc)) from exc
        cache = ensure_import_cache(game, godot, env, tool)
        print(f"harness cache ready at {cache}")
        return 0
    if not args.route or not args.out:
        p.error("--route and --out are required unless --warm-cache is specified")
    patches = args.patch or None
    replay = run(args.route, args.out, patch=None, game=args.game, fps=args.fps, patches=patches,
                 force_import=args.force_import, sandbox=args.sandbox)
    how = replay["isolation"]
    print(f"{replay['capture']['frames']} frames, device {replay['engine']['device']}, "
          + ("sandboxed" if how["sandbox"] else f"not sandboxed ({how['reason']})") + f": {args.out / 'replay.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
