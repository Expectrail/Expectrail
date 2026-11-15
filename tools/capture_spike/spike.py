"""The capture spike's supervisor (#246). See the package docstring for what each mode does."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import signal
import statistics
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:  # the grabs and the comparison need both; reading the screen file's layout needs neither
    import numpy as np
    from PIL import Image
except ModuleNotFoundError as exc:
    if exc.name not in ("numpy", "PIL"):
        raise
    np = Image = None

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SCREEN = (1920, 1080)
GAME_UID = 65534
SPIKE_AUTOLOAD = {"step": 'SpikeStep="*res://spike_step.gd"', "forge": 'SpikeForge="*res://spike_forge.gd"'}


# --- the supervisor's screen file -------------------------------------------------------------------

def xwd_layout(header: bytes) -> dict:
    """Where the pixels are in an XWD screen file (Xvfb -fbdir), from its header.

    The header is 25 big-endian 32-bit fields (X11's XWDFileHeader), then the window name, then
    ``ncolors`` colour entries of 12 bytes, then the pixels."""
    if len(header) < 100:
        raise ValueError("an XWD header is at least 100 bytes")
    f = struct.unpack(">25I", header[:100])
    layout = {"width": f[4], "height": f[5], "littleEndian": f[7] == 0, "bitsPerPixel": f[11],
              "bytesPerLine": f[12], "masks": (f[14], f[15], f[16]), "offset": f[0] + f[19] * 12}
    if layout["bitsPerPixel"] != 32:
        raise ValueError(f"the screen file has {layout['bitsPerPixel']} bits a pixel; only 32 is read")
    return layout


def read_xwd(path: Path, width: int, height: int) -> np.ndarray:
    """The top-left width x height pixels of an XWD screen file as an RGB array."""
    data = path.read_bytes()
    lay = xwd_layout(data[:100])
    if width > lay["width"] or height > lay["height"]:
        raise ValueError(f"the screen is {lay['width']}x{lay['height']}; cannot crop {width}x{height}")
    rows = np.frombuffer(data, dtype=np.uint8, count=lay["bytesPerLine"] * lay["height"], offset=lay["offset"])
    rows = rows.reshape(lay["height"], lay["bytesPerLine"])[:height, : width * 4]
    words = rows.copy().view("<u4" if lay["littleEndian"] else ">u4").reshape(height, width)
    out = np.empty((height, width, 3), dtype=np.uint8)
    for i, mask in enumerate(lay["masks"]):
        shift = (mask & -mask).bit_length() - 1
        out[..., i] = (words & mask) >> shift
    return out


def rgb_of_png(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"))


def digest(rgb: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(rgb).tobytes()).hexdigest()


# --- the display and the game's user -------------------------------------------------------------

def free_display() -> int:
    for n in range(140, 200):
        if not Path(f"/tmp/.X11-unix/X{n}").exists() and not Path(f"/tmp/.X{n}-lock").exists():
            return n
    raise RuntimeError("no free X display number between 140 and 199")


def start_xvfb(fbdir: Path) -> tuple[subprocess.Popen, int]:
    display = free_display()
    proc = subprocess.Popen(["Xvfb", f":{display}", "-screen", "0", f"{SCREEN[0]}x{SCREEN[1]}x24",
                             "-fbdir", str(fbdir), "-nolisten", "tcp", "-nocursor"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    screen = fbdir / "Xvfb_screen0"
    for _ in range(200):
        if screen.exists() and Path(f"/tmp/.X11-unix/X{display}").exists():
            return proc, display
        if proc.poll() is not None:
            raise RuntimeError(f"Xvfb exited: {proc.stderr.read().decode(errors='replace')[-500:]}")
        time.sleep(0.05)
    proc.kill()
    raise RuntimeError("Xvfb did not start in 10 s")


def as_game_user(cmd: list[str], uid: int) -> list[str]:
    if uid == os.getuid():
        return cmd
    return ["setpriv", f"--reuid={uid}", f"--regid={uid}", "--clear-groups", "--no-new-privs", "--"] + cmd


def chown_tree(root: Path, uid: int) -> None:
    for dirpath, _dirs, files in os.walk(root):
        os.chown(dirpath, uid, uid)
        for name in files:
            os.chown(os.path.join(dirpath, name), uid, uid, follow_symlinks=False)


# --- the replay ------------------------------------------------------------------------------------

def make_copy(work: Path, route: Path, extra: list[str]) -> list[str]:
    """The game copy harness.run makes (import cache, harness autoloads), plus the spike's autoloads.
    Returns the harness's own arguments for the Godot command."""
    sys.path.insert(0, str(REPO))
    from harness import run as hrun

    game = REPO / "game" / "platformer"
    godot = hrun.find_godot()
    env = hrun.game_env()
    tree_hash = hrun.tree_digest(game, None)
    cache = hrun.ensure_import_cache(game, godot, env, None, None, tree_hash)
    hrun.prepare(game, work, cache=cache)
    if not (work / ".godot" / "imported").is_dir():
        hrun.godot_import(godot, work, env, None)
    project = (work / "project.godot").read_text(encoding="utf-8")
    for name in extra:
        shutil.copy(HERE / f"{name}.gd", work / f"spike_{name}.gd")
        project = project.replace("[autoload]\n", "[autoload]\n\n" + SPIKE_AUTOLOAD[name] + "\n", 1)
    (work / "project.godot").write_text(project, encoding="utf-8")
    route_doc = json.loads(route.read_text(encoding="utf-8"))
    return [f"--seed={route_doc.get('seed', 1)}"]


def run(mode: str, out: Path, route: Path, *, forge: bool = False, reach: bool = False, uid: int = GAME_UID,
        settle_ms: float = 30.0, sample_ms: tuple[float, float] = (5.0, 40.0), fps: int = 60,
        seed: int = 1) -> dict:
    sys.path.insert(0, str(REPO))
    from harness import run as hrun

    out.mkdir(parents=True, exist_ok=True)
    area = Path(tempfile.mkdtemp(prefix="expectrail-spike-"))
    os.chmod(area, 0o711)
    supervisor = area / "supervisor"       # the screen file and the grabs: the supervisor's user only
    supervisor.mkdir(mode=0o700)
    game_side = area / "game"              # the game's copy, its home and Movie Maker's output
    game_side.mkdir()
    work, home, movie_dir, sync = game_side / "work", game_side / "home", game_side / "movie", game_side / "sync"
    for d in (home, movie_dir, sync):
        d.mkdir()
    extra = (["step"] if mode == "step" else []) + (["forge"] if forge or reach else [])
    harness_args = make_copy(work, route, extra)
    (sync / "ack").write_text("-1", encoding="ascii")
    chown_tree(game_side, uid)

    xvfb, display = start_xvfb(supervisor)
    screen = supervisor / "Xvfb_screen0"
    godot = hrun.find_godot()
    user_args = [f"--route={route.resolve()}", f"--trace={game_side / 'trace.json'}"] + harness_args
    if mode == "step":
        user_args.append(f"--spike-sync={sync}")
    if forge:
        user_args += ["--spike-forge=50:59:10", f"--spike-movie={movie_dir / 'f.png'}"]
    if reach:
        user_args.append(f"--spike-reach={screen}")
    cmd = [str(godot), "--path", str(work), "--audio-driver", "Dummy", "--rendering-driver", "opengl3",
           "--position", "0,0", "--write-movie", str(movie_dir / "f.png"), "--fixed-fps", str(fps),
           "--disable-vsync", "--"] + user_args
    env = hrun.game_env()
    env.update({"DISPLAY": f":{display}", "HOME": str(home), "XDG_CACHE_HOME": str(home / ".cache"),
                "XDG_DATA_HOME": str(home / ".local/share"), "XDG_CONFIG_HOME": str(home / ".config")})
    for key in [k for k in env if k.startswith("XDG_RUNTIME")]:
        del env[key]

    grabs: list[dict] = []
    started = time.monotonic()
    try:
        log_file = out / "godot.log"
        with open(log_file, "w", encoding="utf-8") as sink:
            proc = subprocess.Popen(as_game_user(cmd, uid), env=env, stdout=sink, stderr=subprocess.STDOUT)
        if mode == "step":
            grabs = _stepped(proc, sync, screen, supervisor, settle_ms)
        elif mode == "sample":
            grabs = _sampled(proc, screen, supervisor, sample_ms, seed)
        proc.wait(timeout=1800)
        elapsed = time.monotonic() - started
        probes = _probe_as_game(screen, supervisor, xvfb.pid, uid, env)
    finally:
        if xvfb.poll() is None:
            xvfb.send_signal(signal.SIGTERM)
            try:
                xvfb.wait(timeout=10)
            except subprocess.TimeoutExpired:
                xvfb.kill()
    log = (out / "godot.log").read_text(encoding="utf-8", errors="replace")
    result = _compare(mode, out, movie_dir, supervisor, grabs, settle_ms)
    result.update({
        "mode": mode, "forge": forge, "reach": reach, "gameUid": uid, "fps": fps, "route": str(route),
        "godotExit": proc.returncode, "wallSeconds": round(elapsed, 2),
        "traceWritten": (game_side / "trace.json").exists(),
        "inGameReach": [line.split(" ", 2)[2] for line in log.splitlines() if line.startswith("SPIKE reach ")],
        "inGameForge": [line for line in log.splitlines() if line.startswith("SPIKE forged")],
        "probesAsGameUser": probes,
    })
    if (game_side / "trace.json").exists():
        shutil.copy(game_side / "trace.json", out / "trace.json")
    (out / "spike.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(area, ignore_errors=True)
    return result


def _grab(screen: Path, size: tuple[int, int]) -> np.ndarray:
    return read_xwd(screen, *size)


def _stepped(proc: subprocess.Popen, sync: Path, screen: Path, supervisor: Path, settle_ms: float) -> list[dict]:
    """Approach 1: for every frame the game says it drew, grab the screen at once and after settle_ms,
    then let the game go on. The handshake is two ordinary files (step.gd says why)."""
    grabs = []
    last = None
    drawn, ack = sync / "drawn", sync / "ack"
    while proc.poll() is None:
        try:
            said = drawn.read_text(encoding="ascii").strip()
        except OSError:
            said = ""
        if not said or said == last:
            time.sleep(0.0002)
            continue
        last = said
        t0 = time.monotonic()
        first = _grab(screen, SCREEN)
        time.sleep(settle_ms / 1000)
        settled = _grab(screen, SCREEN)
        held = time.monotonic() - t0
        idx = len(grabs)
        np.save(supervisor / f"g{idx:05d}a.npy", first)
        np.save(supervisor / f"g{idx:05d}b.npy", settled)
        grabs.append({"said": int(said) if said.isdigit() else said, "heldMs": round(held * 1000, 1)})
        tmp = sync / "ack.tmp"
        tmp.write_text(said, encoding="ascii")
        os.replace(tmp, ack)
    return grabs


def _sampled(proc: subprocess.Popen, screen: Path, supervisor: Path, sample_ms: tuple[float, float],
             seed: int) -> list[dict]:
    """Approach 2: grab the screen at random moments while the game runs on its own."""
    rng = random.Random(seed)
    grabs = []
    start = time.monotonic()
    while proc.poll() is None:
        time.sleep(rng.uniform(*sample_ms) / 1000)
        try:
            image = _grab(screen, SCREEN)
        except (OSError, ValueError):
            continue
        np.save(supervisor / f"s{len(grabs):05d}.npy", image)
        grabs.append({"atMs": round((time.monotonic() - start) * 1000, 1)})
    return grabs


def _probe_as_game(screen: Path, supervisor: Path, xvfb_pid: int, uid: int, env: dict) -> dict:
    """What the game's user can do to the supervisor's capture, tried from a process of that user."""
    code = (
        "import json, os, sys\n"
        "screen, folder, pid = sys.argv[1], sys.argv[2], int(sys.argv[3])\n"
        "def attempt(f):\n"
        "    try:\n"
        "        f(); return 'allowed'\n"
        "    except OSError as e:\n"
        "        return f'refused ({e.strerror})'\n"
        "r = {\n"
        "  'read the screen file': attempt(lambda: open(screen, 'rb').read(16)),\n"
        "  'write the screen file': attempt(lambda: open(screen, 'r+b').write(b'x')),\n"
        "  'list the capture folder': attempt(lambda: os.listdir(folder)),\n"
        "  'plant a file in the capture folder': attempt(lambda: open(os.path.join(folder, 'p'), 'wb').close()),\n"
        "  'signal the display server': attempt(lambda: os.kill(pid, 0)),\n"
        "  'read the display server memory': attempt(lambda: open(f'/proc/{pid}/mem', 'rb').read(1)),\n"
        "}\n"
        "print(json.dumps(r))\n"
    )
    done = subprocess.run(as_game_user([sys.executable, "-I", "-c", code, str(screen), str(supervisor),
                                        str(xvfb_pid)], uid), capture_output=True, text=True, env=env, timeout=60)
    try:
        return json.loads(done.stdout)
    except json.JSONDecodeError:
        return {"error": (done.stdout + done.stderr)[-500:]}


# --- comparing the supervisor's grabs with Movie Maker's frames -----------------------------------

def _compare(mode: str, out: Path, movie_dir: Path, supervisor: Path, grabs: list[dict], settle_ms: float) -> dict:
    pngs = sorted(movie_dir.glob("f*.png"))
    if not pngs:
        return {"movieFrames": 0, "error": "Movie Maker wrote no frames"}
    movie = [rgb_of_png(p) for p in pngs]
    h, w = movie[0].shape[:2]
    movie_hash = [digest(m) for m in movie]
    where = {}
    for i, d in enumerate(movie_hash):
        where.setdefault(d, []).append(i)
    result: dict = {"movieFrames": len(pngs), "frameSize": [w, h], "grabs": len(grabs)}
    grabs_dir = out / "grabs"
    grabs_dir.mkdir(exist_ok=True)
    if mode == "step":
        rows = []
        for i, g in enumerate(grabs):
            first = np.load(supervisor / f"g{i:05d}a.npy")[:h, :w]
            settled = np.load(supervisor / f"g{i:05d}b.npy")[:h, :w]
            Image.fromarray(settled).save(grabs_dir / f"g{i:05d}.png")
            rows.append({**g, "first": where.get(digest(first), []), "settled": where.get(digest(settled), []),
                         "firstEqualsSettled": bool(np.array_equal(first, settled)),
                         "sameIndexDiffPixels": int(np.any(settled != movie[i], axis=2).sum()) if i < len(movie) else None})
        result["rows"] = rows
        result["summary"] = _step_summary(rows, len(movie), settle_ms)
    elif mode == "sample":
        images = []
        for i, g in enumerate(grabs):
            image = np.load(supervisor / f"s{i:05d}.npy")[:h, :w]
            if digest(image) not in where:
                Image.fromarray(image).save(grabs_dir / f"s{i:05d}.png")
            images.append(image)
        rows = classify_samples(images, movie)
        result["rows"] = [{**g, **r} for g, r in zip(grabs, rows)]
        result["summary"] = sample_summary(rows)
    return result


def torn_between(image: np.ndarray, before: np.ndarray, after: np.ndarray) -> bool:
    """True when every pixel of a grab is that pixel of one of two neighbouring frames, and both
    frames are present: the screen was grabbed while the next frame was being put on it.

    The tear is not a clean line. Measured for #246 with Godot on Mesa's software renderer under Xvfb,
    a torn grab is the new frame on one side of a ragged edge (some grabs top-down, some bottom-up,
    with 7 to 14 pixel steps within a row), so no order is assumed. This is weaker than an order rule:
    a forged picture made of two neighbouring frames would pass as a tear."""
    differ = np.any(before != after, axis=2)
    if not differ.any():
        return False
    is_before = np.all(image == before, axis=2)[differ]
    is_after = np.all(image == after, axis=2)[differ]
    return bool(np.all(is_before | is_after)) and bool(is_before.any()) and bool(is_after.any())


def classify_samples(images: list[np.ndarray], movie: list[np.ndarray]) -> list[dict]:
    """Each randomly timed grab, looked for among Movie Maker's frames by content.

    kinds: ``frame`` (equal to one or more movie frames), ``before`` (before the first matched grab:
    the window before Movie Maker's first frame), ``after`` (after the last), ``torn`` (rows of the two
    neighbouring frames), ``unexplained`` (between two matched grabs and equal to nothing written):
    either a frame the game drew was not what Movie Maker kept, or something drew between frames."""
    where: dict[str, list[int]] = {}
    for i, m in enumerate(movie):
        where.setdefault(digest(m), []).append(i)
    matches = [where.get(digest(im), []) for im in images]
    hit = [i for i, m in enumerate(matches) if m]
    rows = []
    for i, image in enumerate(images):
        if matches[i]:
            rows.append({"kind": "frame", "matches": matches[i]})
            continue
        if not hit or i < hit[0]:
            rows.append({"kind": "before", "matches": []})
            continue
        if i > hit[-1]:
            rows.append({"kind": "after", "matches": []})
            continue
        prev = max(matches[max(j for j in hit if j < i)])
        nxt = min(matches[min(j for j in hit if j > i)])
        kind = "torn" if nxt == prev + 1 and torn_between(image, movie[prev], movie[nxt]) else "unexplained"
        rows.append({"kind": kind, "matches": [], "between": [prev, nxt]})
    return rows


def sample_summary(rows: list[dict]) -> dict:
    kinds = {k: sum(1 for r in rows if r["kind"] == k) for k in ("frame", "before", "after", "torn", "unexplained")}
    unexplained = sorted({tuple(r["between"]) for r in rows if r["kind"] == "unexplained"})
    seen = {m for r in rows for m in r["matches"]}
    return {"grabs": len(rows), **kinds, "unexplainedBetween": [list(b) for b in unexplained],
            "movieFramesSeen": len(seen)}


def _step_summary(rows: list[dict], movie_frames: int, settle_ms: float) -> dict:
    """How the stepped grabs line up with Movie Maker's frames, by content alone."""
    def offsets(key: str) -> dict:
        found = {}
        for i, r in enumerate(rows):
            for m in r[key]:
                found[m - i] = found.get(m - i, 0) + 1
        return dict(sorted(found.items()))
    exact_same_index = [i for i, r in enumerate(rows) if i in r["settled"]]
    mismatched = [i for i, r in enumerate(rows) if i < movie_frames and i not in r["settled"]]
    return {
        "grabs": len(rows), "movieFrames": movie_frames, "settleMs": settle_ms,
        "settledEqualsMovieFrameSameIndex": len(exact_same_index),
        "settledDiffersFromMovieFrameSameIndex": mismatched,
        "firstGrabEqualsSettled": sum(1 for r in rows if r["firstEqualsSettled"]),
        "offsetsFirst": offsets("first"), "offsetsSettled": offsets("settled"),
        "medianHeldMs": statistics.median([r["heldMs"] for r in rows]) if rows else None,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("plain", "step", "sample"), required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--route", type=Path, default=REPO / "harness" / "routes" / "smoke.json")
    p.add_argument("--forge", action="store_true", help="the game rewrites movie frames 50..59 with frame 10")
    p.add_argument("--reach", action="store_true", help="the game tries to read and write the screen file")
    p.add_argument("--uid", type=int, default=GAME_UID, help="the game's user (default 65534)")
    p.add_argument("--settle", type=float, default=30.0, help="ms between the two grabs of a held frame")
    p.add_argument("--seed", type=int, default=1, help="seed for the sampling times")
    args = p.parse_args(argv)
    if np is None or Image is None:
        print("capture spike: needs numpy and Pillow (pip install numpy pillow)", file=sys.stderr)
        return 2
    if os.geteuid() != 0 and args.uid != os.getuid():
        print("capture spike: starting the game as another user needs root (or pass --uid with your own uid, "
              "which tests nothing about separation)", file=sys.stderr)
        return 2
    result = run(args.mode, args.out, args.route, forge=args.forge, reach=args.reach, uid=args.uid,
                 settle_ms=args.settle, seed=args.seed)
    print(json.dumps({k: result.get(k) for k in ("mode", "forge", "godotExit", "wallSeconds", "movieFrames", "grabs",
                                                 "summary", "inGameReach", "inGameForge", "probesAsGameUser")},
                     indent=2))
    return 0
