"""Replay one route through a Unity player built with the Expectrail harness, and capture what a player would see.

    python3 -m harness.unity.run --route harness/routes/unity-smoke.json --out runs/unity-smoke \\
        --player runs/unity/harness [--patch bugs/x/v1.patch]
    python3 -m harness.unity.run --prepare-build --out runs/unity/harness [--patch ...]   # then build it with Unity
    python3 -m harness.unity.run --build --unity /path/to/Unity --out runs/unity/harness [--patch ...]
    python3 -m harness.unity.run --out runs/unity-smoke --compare runs/unity-smoke-2   # frames and trace hash
    EXPECTRAIL_UNITY_PLAYER=runs/unity/harness python3 -m harness.replay_check --adapter unity \\
        --route harness/routes/unity-smoke.json --runs 10

Unlike Godot, a Unity game has to be built into a player before it can run, and building needs a
licensed Editor (.github/workflows/unity.yml does it in CI; locally, an Editor a person has already
activated). So a run needs a player built from exactly this game, these patches and this harness
package: ``build_key`` names that set, the build writes it into ``build.json`` beside the player,
and ``run`` refuses a player whose key differs.

``run`` copies the game to <out>/work and applies the patches there in order (seed, then
candidate), which also proves they apply; starts the player under a virtual display on Mesa's
llvmpipe with only the allowlisted environment (harness/run.py's game_env) and an empty HOME; and
checks what it wrote: exactly one PNG per tick, 1600 x 960, contiguous from f00000000.png; a trace
row per tick with rows[i].tick == i; exactly one physics step in every captured frame. Any failure
raises SystemExit, which the verifier turns into needs-review. Output, as from harness/run.py:
<out>/frames/f%08d.png, <out>/trace.json, <out>/replay.json, and <out>/unity.log (the player's
stdout and stderr).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

from harness.adapters import UNITY_IGNORE, sha256_file, tree_digest as _tree_digest
from harness.run import REPO, apply_patches, game_env

GAME = REPO / "game" / "unity-platformer"
HERE = Path(__file__).resolve().parent
PACKAGE = HERE / "package"
PACKAGE_NAME = "com.expectrail.harness"
MAPS = HERE / "maps"
BUILD_METHOD = "Expectrail.Harness.Editor.HarnessBuild.Build"
PLAYER = "player/game.x86_64"
BUILD_FORMAT = "expectrail.unity-build/v0"
ROUTE_FORMAT = "expectrail.route/v0"
# llvmpipe's settings, when the caller sets none: the same as CI's replay job.
RENDER_DEFAULTS = {"LIBGL_ALWAYS_SOFTWARE": "1", "GALLIUM_DRIVER": "llvmpipe",
                   "LP_NATIVE_VECTOR_WIDTH": "128", "LP_NUM_THREADS": "4"}
TIMEOUT = 1800
LINK_XML = """<linker>
  <!-- Written by harness/unity/run.py into the build copy: Unity reads link.xml only under Assets/. -->
  <assembly fullname="Expectrail.Harness" preserve="all"/>
  <assembly fullname="Unity.InputSystem">
    <type fullname="UnityEngine.InputSystem.Keyboard" preserve="all"/>
    <type fullname="UnityEngine.InputSystem.Mouse" preserve="all"/>
  </assembly>
</linker>
"""


def tree_digest(root: Path, ignore: tuple[str, ...] = UNITY_IGNORE) -> str:
    """The Unity adapter's digest (harness.adapters.tree_digest), without the Editor's own folders."""
    return _tree_digest(root, ignore)


def load_map(game: Path) -> dict:
    """The per-game map (harness/unity/maps/<game folder>.json): input actions, roles, ground, settle."""
    path = MAPS / f"{Path(game).name}.json"
    if not path.is_file():
        raise SystemExit(f"no Unity harness map for {game}: expected {path}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("format") != "expectrail.unity-map/v0":
        raise SystemExit(f"{path} is not an expectrail.unity-map/v0 document")
    return doc


def map_path(game: Path) -> Path:
    return MAPS / f"{Path(game).name}.json"


def unity_version(game: Path) -> str:
    for line in (Path(game) / "ProjectSettings" / "ProjectVersion.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("m_EditorVersion:"):
            return line.split(":", 1)[1].strip()
    raise SystemExit(f"{game} has no m_EditorVersion in ProjectSettings/ProjectVersion.txt")


def build_key(game: Path, patches: list[Path], *, harness: bool = True) -> dict:
    """What a player is built from. Two players with the same key are built from the same files."""
    doc = {
        "format": BUILD_FORMAT,
        "game": {"tree": tree_digest(game)},
        "patches": [sha256_file(p) for p in patches],
        "package": {"name": PACKAGE_NAME, "tree": tree_digest(PACKAGE, ())} if harness else None,
        "startScene": load_map(game)["scene"] if harness else None,
        "unityVersion": unity_version(game),
    }
    doc["key"] = hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return doc


def _copy_game(game: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(game, dest, ignore=shutil.ignore_patterns(*UNITY_IGNORE))


def _apply(work: Path, patches: list[Path]) -> None:
    try:
        apply_patches(work, patches)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"a patch does not apply to the game: {exc.stdout or ''}{exc.stderr or ''}".strip()) from exc


def prepare_build(out: Path, patches: list[Path] | None = None, *, game: Path | None = None) -> dict:
    """Lay out a project for the Editor to build: <out>/project (the game, patched, with the harness
    package as a file: dependency), <out>/com.expectrail.harness (the package), <out>/build.json.

    The Editor then runs BUILD_METHOD on <out>/project and writes the player to <out>/player.
    """
    game = Path(game or GAME)
    ordered = [Path(p) for p in patches or []]
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    project, package = out / "project", out / PACKAGE_NAME
    _copy_game(game, project)
    _apply(project, ordered)
    if package.exists():
        shutil.rmtree(package)
    shutil.copytree(PACKAGE, package)
    manifest_path = project / "Packages" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Relative to the project's Packages folder, so it resolves inside the builder's container too.
    manifest["dependencies"][PACKAGE_NAME] = f"file:../../{PACKAGE_NAME}"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    link = project / "Assets" / "ExpectrailHarness" / "link.xml"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.write_text(LINK_XML, encoding="utf-8")
    m = load_map(game)
    (project / "expectrail-build.json").write_text(json.dumps(
        {"startScene": m["scene"], "player": f"../{PLAYER}", "width": m["frameWidth"], "height": m["frameHeight"]},
        indent=2) + "\n", encoding="utf-8")
    key = build_key(game, ordered)
    key["patchPaths"] = [str(p) for p in ordered]
    key["player"] = PLAYER
    (out / "build.json").write_text(json.dumps(key, indent=2) + "\n", encoding="utf-8")
    return key


def build(out: Path, unity: Path, patches: list[Path] | None = None, *, game: Path | None = None) -> dict:
    """Prepare and build with an Editor a person has already activated (this never activates Unity)."""
    key = prepare_build(out, patches, game=game)
    log = Path(out) / "build.log"
    cmd = [str(unity), "-batchmode", "-nographics", "-quit", "-projectPath", str((Path(out) / "project").resolve()),
           "-buildTarget", "StandaloneLinux64", "-executeMethod", BUILD_METHOD, "-logFile", str(log.resolve())]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    if proc.returncode != 0 or not (Path(out) / PLAYER).is_file():
        raise SystemExit(f"the Unity build failed ({proc.returncode}); see {log}")
    return key


def resolve_player(player: Path | None, key: dict) -> tuple[Path, dict]:
    """The player built from ``key``: ``player`` (or $EXPECTRAIL_UNITY_PLAYER) is a build folder with
    build.json, or a folder of such folders."""
    where = player or os.environ.get("EXPECTRAIL_UNITY_PLAYER")
    if not where:
        raise SystemExit("no Unity player given: build one (python3 -m harness.unity.run --prepare-build, then the "
                         "Unity workflow or --build) and pass --player or set EXPECTRAIL_UNITY_PLAYER")
    where = Path(where)
    candidates = [where] if (where / "build.json").is_file() else sorted(p.parent for p in where.glob("*/build.json"))
    if not candidates:
        raise SystemExit(f"no build.json in {where} or in any folder inside it")
    for folder in candidates:
        built = json.loads((folder / "build.json").read_text(encoding="utf-8"))
        if built.get("key") == key["key"]:
            exe = folder / built.get("player", PLAYER)
            if not exe.is_file():
                raise SystemExit(f"{folder}/build.json names a player that is not there: {exe}")
            return exe, built
    raise SystemExit(f"no player in {where} was built from this game, these patches and this harness "
                     f"(key {key['key'][:12]}); the players there have "
                     + ", ".join(json.loads((f / 'build.json').read_text())['key'][:12] for f in candidates))


def png_size(path: Path) -> tuple[int, int]:
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise SystemExit(f"{path} is not a PNG")
    return struct.unpack(">II", head[16:24])


def cpu_model() -> str | None:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


def player_env(home: Path) -> dict:
    """harness/run.py's allowlisted environment, llvmpipe's defaults, and an empty home of the run's own,
    so PlayerPrefs (Unity keeps them under ~/.config/unity3d) start empty every time."""
    env = game_env()
    for k, v in RENDER_DEFAULTS.items():
        env.setdefault(k, v)
    if home.exists():
        shutil.rmtree(home)
    (home / ".config").mkdir(parents=True)
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), XDG_DATA_HOME=str(home / ".local" / "share"),
               XDG_CACHE_HOME=str(home / ".cache"))
    return env


def player_cmd(exe: Path, route: Path, game_map: Path, out: Path, seed: int, m: dict, frames: bool) -> list[str]:
    cmd = [str(exe.resolve()), "-force-glcore", "-screen-width", str(m["frameWidth"]),
           "-screen-height", str(m["frameHeight"]), "-screen-fullscreen", "0", "-logFile", "-",
           "-expectrail-route", str(route.resolve()), "-expectrail-map", str(game_map.resolve()),
           "-expectrail-out", str(out.resolve()), "-expectrail-seed", str(seed)]
    if not frames:
        cmd.append("-expectrail-no-frames")
    if not os.environ.get("DISPLAY") and sys.platform != "darwin":
        cmd = ["xvfb-run", "-a", "-s", "-screen 0 1920x1080x24"] + cmd
    return cmd


def check_route(route_doc: dict, m: dict) -> None:
    from expectrail.contracts import ContractError, validate

    if route_doc.get("format") != ROUTE_FORMAT:
        raise SystemExit(f"not an {ROUTE_FORMAT} route: {route_doc.get('format')!r}")
    try:
        validate(route_doc, "route")
    except ContractError as exc:
        raise SystemExit(f"invalid route: {exc}") from exc
    known = {a["name"] for a in m["actions"]}
    for e in route_doc["events"]:
        if e["action"] not in known:
            raise SystemExit(f"the route presses {e['action']!r}, which the map does not define ({', '.join(sorted(known))})")
        if not 0 <= e["tick"] < route_doc["ticks"]:
            raise SystemExit(f"event at tick {e['tick']} is outside the route's {route_doc['ticks']} ticks")


def check_outputs(route_doc: dict, m: dict, trace: dict, run_doc: dict, frames: Path, capture_frames: bool) -> list[Path]:
    """What the player wrote, against the route; returns the frames in order. Raises SystemExit."""
    from expectrail.contracts import ContractError, validate

    ticks = route_doc["ticks"]
    try:
        validate(trace, "trace")
    except ContractError as exc:
        raise SystemExit(f"the trace does not match contracts/trace.schema.json: {exc}") from exc
    if trace["ticks"] != ticks or len(trace["rows"]) != ticks:
        raise SystemExit(f"the trace has {len(trace['rows'])} rows for {trace['ticks']} ticks; the route has {ticks}")
    for i, row in enumerate(trace["rows"]):
        if row["tick"] != i or row.get("frame", i) != i:
            raise SystemExit(f"trace row {i} is tick {row['tick']}, frame {row.get('frame')}")
        ids = [o["id"] for o in row.get("objects") or []]
        if len(ids) != len(set(ids)):
            raise SystemExit(f"trace row {i} names an object twice")
    if trace["physicsTicksPerSecond"] != m["physicsTicksPerSecond"]:
        raise SystemExit(f"the player ran {trace['physicsTicksPerSecond']} physics ticks a second; the map says "
                         f"{m['physicsTicksPerSecond']}")
    steps = run_doc.get("steps") or []
    if len(steps) != ticks:
        raise SystemExit(f"the player counted physics steps for {len(steps)} frames; the route has {ticks} ticks")
    for i, n in enumerate(steps):
        if n != 1:
            raise SystemExit(f"frame {i} held {n} physics steps, not 1: one frame must be one tick")
    pngs = sorted(frames.glob("f*.png"))
    if not capture_frames:
        if pngs:
            raise SystemExit(f"{len(pngs)} frames written by a run asked for none")
        return []
    names = [p.name for p in pngs]
    expected = [f"f{i:08d}.png" for i in range(ticks)]
    if names != expected:
        missing = sorted(set(expected) - set(names))
        extra = sorted(set(names) - set(expected))
        raise SystemExit(f"{len(names)} frames for {ticks} ticks (missing {missing[:3]}, unexpected {extra[:3]})")
    size = (m["frameWidth"], m["frameHeight"])
    for p in pngs:
        if png_size(p) != size:
            raise SystemExit(f"{p.name} is {png_size(p)[0]} x {png_size(p)[1]}, not {size[0]} x {size[1]}")
    return pngs


def run(route: Path, out: Path, patches: list[Path] | None = None, *, game: Path | None = None,
        fps: int | None = None, capture_frames: bool = True, player: Path | None = None) -> dict:
    """Replay one route and write replay.json (expectrail.replay/v0); return it. Raises SystemExit on any failure."""
    game = Path(game or GAME)
    route, out = Path(route), Path(out)
    ordered = [Path(p) for p in patches or []]
    m = load_map(game)
    if fps is not None and fps != m["physicsTicksPerSecond"]:
        raise SystemExit(f"a Unity replay captures one frame per tick, {m['physicsTicksPerSecond']} a second; "
                         f"it cannot capture at {fps}")
    route_doc = json.loads(route.read_text(encoding="utf-8"))
    check_route(route_doc, m)
    key = build_key(game, ordered)
    exe, built = resolve_player(player, key)

    out.mkdir(parents=True, exist_ok=True)
    work, frames = out / "work", out / "frames"
    _copy_game(game, work)
    _apply(work, ordered)
    for stale in (frames, out / "trace.json", out / "run.json", out / "replay.json"):
        if stale.is_dir():
            shutil.rmtree(stale)
        elif stale.exists():
            stale.unlink()
    frames.mkdir()
    env = player_env(out / "home")
    seed = int(route_doc.get("seed", 1))
    cmd = player_cmd(exe, route, map_path(game), out, seed, m, capture_frames)
    log = out / "unity.log"
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=TIMEOUT, cwd=out)
    except subprocess.TimeoutExpired as exc:
        log.write_text(_text(exc.stdout) + _text(exc.stderr) + f"\nthe player did not finish in {TIMEOUT} s\n",
                       encoding="utf-8")
        raise SystemExit(f"the Unity player timed out; see {log}") from exc
    log.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    run_path, trace_path = out / "run.json", out / "trace.json"
    run_doc = json.loads(run_path.read_text(encoding="utf-8")) if run_path.is_file() else None
    if run_doc and run_doc.get("status") != "ok":
        raise SystemExit(f"the harness failed in the player: {run_doc.get('error')}; see {log}")
    if proc.returncode != 0 or run_doc is None or not trace_path.is_file():
        raise SystemExit(f"the Unity player failed ({proc.returncode}) without a trace; see {log}")
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    pngs = check_outputs(route_doc, m, trace, run_doc, frames, capture_frames)

    primary = ordered[0] if ordered else None
    graphics = run_doc.get("graphics") or {}
    replay = {
        "format": "expectrail.replay/v0",
        "route": {"name": route_doc.get("name", route.stem), "sha256": sha256_file(route)},
        "game": {"tree": key["game"]["tree"],
                 "patch": ",".join(str(p) for p in ordered) if ordered else None,
                 "patchSha256": sha256_file(primary) if primary and len(ordered) == 1 else (
                     None if not ordered else hashlib.sha256(
                         b"".join(sha256_file(p).encode() for p in ordered)).hexdigest())},
        "engine": {"name": "unity", "version": run_doc.get("unityVersion") or built.get("unityVersion"),
                   "renderer": " ".join(str(graphics.get(k)) for k in ("type", "version") if graphics.get(k)) or None,
                   "device": cpu_model()},
        "capture": {"fps": m["physicsTicksPerSecond"], "physicsTicksPerSecond": trace["physicsTicksPerSecond"],
                    "frames": len(pngs), "pattern": "frames/f%08d.png"},
        "frameSha256": [sha256_file(p) for p in pngs],
        "trace": {"path": "trace.json", "sha256": sha256_file(trace_path)},
        "seed": seed,
        "build": {"key": built["key"], "unityVersion": built.get("unityVersion")},
        "settle": run_doc.get("settle") or {"ticks": 0, "frozenFrames": 0},
        "hazards": run_doc.get("hazards") or [],
        "integrity": run_doc.get("integrity") or {"exceptions": 0, "errors": 0, "messages": []},
    }
    from expectrail.contracts import ContractError, validate

    try:
        validate(replay, "replay")
    except ContractError as exc:
        raise SystemExit(f"the replay document does not match contracts/replay.schema.json: {exc}") from exc
    (out / "replay.json").write_text(json.dumps(replay, indent=2) + "\n", encoding="utf-8")
    return replay


def compare(first: dict, other: dict) -> dict:
    """How two replays of one route differ: frames by index (frameSha256), and the trace by its sha256."""
    a, b = first["frameSha256"], other["frameSha256"]
    frames = [i for i in range(max(len(a), len(b))) if i >= len(a) or i >= len(b) or a[i] != b[i]]
    trace = first["trace"]["sha256"] != other["trace"]["sha256"]
    return {"framesDiffer": frames, "traceDiffers": trace, "identical": not frames and not trace}


def visible_boxes(trace: dict, role: str) -> dict[int, list[list[float]]]:
    """The reader of the trace's objects field: {frame: [box, ...]} for the visible objects of one role,
    in frame pixels, the shape agents.observations.engine_refs_by_frame returns."""
    out: dict[int, list[list[float]]] = {}
    for row in trace.get("rows") or []:
        if "objects" not in row:
            continue
        out[row.get("frame", row["tick"])] = [o["box"] for o in row["objects"]
                                              if o["role"] == role and o["visible"] and o["box"] is not None]
    return out


def _text(data) -> str:
    if data is None:
        return ""
    return data.decode("utf-8", "replace") if isinstance(data, bytes) else data


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--route", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--patch", type=Path, action="append", default=[],
                   help="patch to apply (repeatable; order is seed then candidate)")
    p.add_argument("--game", type=Path, help="Unity project (default: game/unity-platformer)")
    p.add_argument("--player", type=Path, help="a build folder with build.json, or a folder of them "
                                               "(default: $EXPECTRAIL_UNITY_PLAYER)")
    p.add_argument("--no-frames", action="store_true", help="record the trace only")
    p.add_argument("--prepare-build", action="store_true", help="lay out a project for the Editor and exit")
    p.add_argument("--build", action="store_true", help="prepare and build with --unity (an activated Editor)")
    p.add_argument("--unity", type=Path, help="the Unity Editor executable, for --build")
    p.add_argument("--compare", type=Path, nargs="+", metavar="RUN",
                   help="compare these replay folders with --out's (frames and trace hash); exit 1 if any differs")
    args = p.parse_args(argv)
    if args.compare:
        first = json.loads((args.out / "replay.json").read_text(encoding="utf-8"))
        code = 0
        for other_dir in args.compare:
            result = compare(first, json.loads((other_dir / "replay.json").read_text(encoding="utf-8")))
            print(json.dumps({"run": str(other_dir), **result}))
            code |= 0 if result["identical"] else 1
        return code
    if args.prepare_build or args.build:
        if args.build and not args.unity:
            p.error("--build needs --unity")
        key = (build(args.out, args.unity, args.patch, game=args.game) if args.build
               else prepare_build(args.out, args.patch, game=args.game))
        print(f"build {key['key'][:12]}: project {args.out / 'project'}, player {args.out / PLAYER}, "
              f"method {BUILD_METHOD}")
        return 0
    if not args.route:
        p.error("--route is required unless --prepare-build or --build is given")
    replay = run(args.route, args.out, args.patch, game=args.game, capture_frames=not args.no_frames,
                 player=args.player)
    print(f"{replay['capture']['frames']} frames, {replay['engine']['renderer']} on {replay['engine']['device']}: "
          f"{args.out / 'replay.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
