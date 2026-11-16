"""Share identical real replays between the ground and body-box geometry assertions.

Every distinct scene, route, engine and harness still runs. These tests inspect
rows rather than independent replay stability; the determinism tests do not use
this helper. Store serialized data only, returning a fresh document to each test.
No cached game directory or mutable trace is handed to another test.
"""
import json
from pathlib import Path

from harness import run as hr

_traces = {}


def replay_trace(game: Path, route: Path, out: Path, godot: Path) -> dict:
    engine = godot.resolve()
    stat = engine.stat()
    scripts = tuple((hr.REPO / 'harness/godot' / name).read_bytes()
                    for name in ('expectrail_harness.gd', 'expectrail_recorder.gd', 'expectrail_roles.gd'))
    key = (hr.tree_digest(game), route.read_bytes(), str(engine), stat.st_size, stat.st_mtime_ns, scripts)
    if key not in _traces:
        hr.run(route, out, game=game, godot=godot, capture_frames=False)
        _traces[key] = (out / 'trace.json').read_text(encoding='utf-8')
    return json.loads(_traces[key])
