"""A third domain, written the way a new engine would be: one module, nothing edited outside it.

The "engine" here is a lamp described by ``lamp.json``. Replaying a route copies the project, applies
the patches in order and records the lamp on every frame: its box while it is lit, nothing while it
is dark. A frame file holds the lamp's state instead of pixels, so two frames differ exactly when the
lamp does. ``make(root)`` writes the project, a route, a seeded bug and two candidate fixes under
``root`` and returns the adapter; registering it (``harness.adapters.register``) is the only step that
makes the shared verifier, the fixer and the harness tools take it by name.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from harness.adapters import Adapter, sha256_file

NAME = "toy-lamp"
TRACE_FORMAT = "toy.lamp-trace/v0"
CACHE = ".lampcache"
SPEC = {"format": "expectrail.test-spec/v0", "id": "lamp-visible", "instruction": "The lamp is always visible.",
        "objects": {"lamp": {"prompt": "lit lamp"}}, "assertion": {"type": "visible", "object": "lamp"}}
BEHAVIOUR_SPEC = "lamp-is-switched-on"
LAMP = '{\n  "box": [10, 10, 30, 40],\n  "lit": true\n}\n'
DARK = ('--- a/lamp.json\n+++ b/lamp.json\n@@ -1,4 +1,4 @@\n {\n   "box": [10, 10, 30, 40],\n'
        '-  "lit": true\n+  "lit": false\n }\n')
FIX = ('--- a/lamp.json\n+++ b/lamp.json\n@@ -1,4 +1,4 @@\n {\n   "box": [10, 10, 30, 40],\n'
       '-  "lit": false\n+  "lit": true\n }\n')
# Switches the lamp on but takes its box away: the behaviour check passes, the visible spec cannot.
SWITCH_ONLY = ('--- a/lamp.json\n+++ b/lamp.json\n@@ -1,4 +1,4 @@\n {\n-  "box": [10, 10, 30, 40],\n'
               '-  "lit": false\n+  "box": null,\n+  "lit": true\n }\n')


def observe(trace: dict, spec: dict, replay_sha256: str) -> dict:
    """The engine observations: the lamp's recorded box on each frame, as the evaluator reads them."""
    return {"format": "expectrail.observations/v0", "replay": {"sha256": replay_sha256},
            "model": {"name": "toy.lamp-record", "prompts": {n: o.get("prompt", n) for n, o in spec["objects"].items()}},
            "frames": [{"frame": row["frame"],
                        "objects": {"lamp": [{"box": row["lamp"], "score": 1.0}] if row["lamp"] else []}}
                       for row in trace["rows"]]}


def behaviour(trace: dict) -> dict:
    if trace["outcome"]["switchedOn"]:
        return {"result": "pass", "reason": "the lamp is switched on"}
    return {"result": "fail", "reason": "the lamp is switched off"}


def make(root: Path) -> Adapter:
    """Write the toy project, its route, its seeded bug and two fixes under ``root``; return its adapter."""
    project = root / "project"
    (project / CACHE).mkdir(parents=True)
    (project / "lamp.json").write_text(LAMP)
    (project / CACHE / "state").write_text("written by the engine, never part of the project\n")
    (root / "routes").mkdir()
    (root / "routes" / "evening.json").write_text(json.dumps({"name": "evening", "frames": 4}) + "\n")
    (root / "bugs" / "dark").mkdir(parents=True)
    (root / "bugs" / "dark" / "v1.patch").write_text(DARK)
    (root / "fix.patch").write_text(FIX)
    (root / "switch-only.patch").write_text(SWITCH_ONLY)

    def run(route: Path, out: Path, patches: list[Path] | None = None, *, game: Path | None = None,
            fps: int | None = None, capture_frames: bool = True) -> dict:
        route_doc = json.loads(Path(route).read_text())
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        work = out / "work"
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(game or project, work, ignore=shutil.ignore_patterns(CACHE))
        for patch in patches or []:
            proc = subprocess.run(["patch", "-p1", "--forward", "--batch", "-d", str(work), "-i", str(Path(patch).resolve())],
                                  capture_output=True, text=True)
            if proc.returncode != 0:
                raise SystemExit(f"{Path(patch).name} does not apply to the lamp")
        lamp = json.loads((work / "lamp.json").read_text())
        frames = out / "frames"
        if frames.exists():
            shutil.rmtree(frames)
        frames.mkdir()
        rows = []
        for n in range(route_doc["frames"]):
            box = lamp["box"] if lamp["lit"] else None
            rows.append({"frame": n, "lamp": box})
            if capture_frames:
                (frames / f"f{n:08d}.png").write_text(json.dumps(box))
        (out / "trace.json").write_text(json.dumps({"format": TRACE_FORMAT, "rows": rows,
                                                    "outcome": {"switchedOn": lamp["lit"]}}) + "\n")
        replay = {"format": "toy.lamp-replay/v0", "route": {"name": route_doc["name"], "sha256": sha256_file(route)},
                  "engine": {"name": NAME}, "frames": len(rows), "trace": {"sha256": sha256_file(out / "trace.json")}}
        (out / "replay.json").write_text(json.dumps(replay, indent=2) + "\n")
        return replay

    return Adapter(name=NAME, engine=NAME, run=run, game_root=project, ignore=(CACHE,),
                   frame_pattern="frames/f%08d.png", log_name=None, editable=("lamp.json",),
                   prompt_subject="a lamp", text_suffixes=frozenset({".json"}), capture_fps=None,
                   ticks_per_second=None, trace_format=TRACE_FORMAT, default_route=root / "routes" / "evening.json",
                   bugs=root / "bugs", trace_state=lambda row: row["lamp"])
