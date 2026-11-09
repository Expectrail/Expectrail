"""A stand-in for a Unity player built with the Expectrail harness, for tests/test_unity_harness.py.

It takes the arguments harness/unity/run.py passes a real player and writes what the C# harness
writes (frames/f%08d.png, trace.json, run.json), so the runner's checks can be tested without
Unity. It prints the environment variables a patched game could read, for the allowlist tests.
A mode file (``--mode``, JSON) makes it misbehave in the ways the runner must catch.
Standard library only: the runner gives it the game's environment, not the test's.
"""
from __future__ import annotations

import json
import os
import struct
import sys
import time
import zlib
from pathlib import Path


def png(path: Path, width: int, height: int, shade: int) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    row = b"\x00" + bytes((shade % 256, 40, 90)) * width
    raw = zlib.compress(row * height, 1)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def args(argv: list[str]) -> dict:
    out, i = {"frames": True}, 0
    while i < len(argv):
        a = argv[i]
        if a in ("-expectrail-route", "-expectrail-map", "-expectrail-out", "-expectrail-seed", "--mode"):
            out[a.lstrip("-")] = argv[i + 1]
            i += 2
            continue
        if a == "-expectrail-no-frames":
            out["frames"] = False
        i += 1
    return out


def main(argv: list[str]) -> int:
    a = args(argv)
    mode = json.loads(Path(a["mode"]).read_text()) if a.get("mode") and Path(a["mode"]).is_file() else {}
    print("CANARY_ENV=" + os.environ.get("EXPECTRAIL_CANARY", ""))
    print("CANARY_HELDOUT=" + os.environ.get("EXPECTRAIL_HELDOUT_DIR", ""))
    print("HOME=" + os.environ.get("HOME", ""))
    print("ENV_KEYS=" + ",".join(sorted(os.environ)))
    print("ARGS=" + json.dumps(argv))
    sys.stdout.flush()
    if mode.get("sleep"):
        time.sleep(mode["sleep"])
    if "exit" in mode:
        print("fake player exiting early", file=sys.stderr)
        return int(mode["exit"])
    out = Path(a["expectrail-out"])
    route = json.loads(Path(a["expectrail-route"]).read_text())
    game_map = json.loads(Path(a["expectrail-map"]).read_text())
    ticks = int(route["ticks"])
    if mode.get("error"):
        (out / "run.json").write_text(json.dumps({"format": "expectrail.unity-run/v0", "status": "error",
                                                  "error": mode["error"]}))
        return 3
    width, height = mode.get("frameSize", [game_map["frameWidth"], game_map["frameHeight"]])
    frames = out / "frames"
    frames.mkdir(exist_ok=True)
    # "vary" makes every run draw different frames: a counter kept beside the mode file.
    shade = 0
    if mode.get("vary"):
        counter = Path(a["mode"]).with_name("runs.txt")
        shade = int(counter.read_text()) if counter.is_file() else 0
        counter.write_text(str(shade + 1))
    rows = []
    for t in range(ticks):
        x = 100.0 + 4.0 * t
        rows.append({"tick": t, "frame": t, "player": [x, -300.0], "onFloor": True, "facing": 1, "ground": -172.0,
                     "coins": [[600.0, -250.0]], "enemies": [[0, 900.0 - t, -172.0]], "projectiles": [],
                     "view": [0.625, 0.0, 0.0, 0.625, 800.0 - 2.5 * t, 700.0],
                     "objects": [{"id": "Player", "role": "player", "box": [700.0, 500.0, 780.0, 660.0],
                                  "active": True, "visible": True},
                                 {"id": "LevelRoot/Level1(Clone)/Coins/GoldCoin", "role": "coin",
                                  "box": [1100.0, 520.0, 1140.0, 560.0], "active": True, "visible": True},
                                 {"id": "LevelRoot/Level1(Clone)/Enemies/Enemy", "role": "enemy", "box": None,
                                  "active": True, "visible": False}]})
        if a["frames"] and t != mode.get("dropFrame"):
            png(frames / f"f{t:08d}.png", width, height, shade + t)
    if mode.get("badObject"):
        rows[0]["objects"][0]["box"] = [1.0, 2.0]
    if "rows" in mode:
        rows = rows[: mode["rows"]]
    if mode.get("tickGap"):
        rows[1]["tick"] = 5
    steps = [1] * ticks
    for t, n in (mode.get("steps") or {}).items():
        steps[int(t)] = n
    trace = {"format": "expectrail.trace/v0", "ticks": ticks,
             "physicsTicksPerSecond": mode.get("tps", game_map["physicsTicksPerSecond"]),
             "capabilities": {"enemies": "complete", "projectiles": "complete", "facing": True, "onFloor": True},
             "levelSurfaces": [[[0.0, -172.0], [2000.0, -172.0], [2000.0, 0.0], [0.0, 0.0]]],
             "levelArt": {"x0": 0, "y0": -172, "width": 2, "height": 172, "columns": [[[-172, 0]], [[-172, 0]]]},
             "rows": rows}
    if not mode.get("noTrace"):
        (out / "trace.json").write_text(json.dumps(trace, separators=(",", ":")))
    run = {"format": "expectrail.unity-run/v0", "status": "ok", "error": None, "unityVersion": "6000.3.21f1",
           "graphics": {"type": "OpenGLCore", "name": "llvmpipe (fake)", "version": "OpenGL 4.5 (fake)"},
           "screen": [width, height], "seed": int(a.get("expectrail-seed", 1)), "ticks": ticks, "steps": steps,
           "frameCount": [80, 80 + ticks - 1], "fixedTime": [1.52, 1.52 + 0.02 * (ticks - 1)],
           "settle": {"ticks": 76, "frozenFrames": 3}, "groundTilemaps": ["LevelRoot/Level1(Clone)/TilemapGrid/PlatformsTilemap"],
           "hazards": [{"kind": "real-time-fade", "detail": "fake", "tick": None}],
           "integrity": {"exceptions": 0, "errors": 1, "messages": [{"type": "Error", "message": "fake error"}]}}
    (out / "run.json").write_text(json.dumps(run))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
