"""Run the installed console script with a replay stand-in, never a replacement judge.

Only sample.run's engine injection is used. The sample still copies its packaged game,
applies its packaged bug patch, and uses its installed gate, evaluator and schemas.
The sandbox record is synthetic too; this fixture is not evidence of real isolation.
"""
import functools
import importlib.util
import json
from pathlib import Path
import runpy
import struct
import sys
from unittest import mock
import zlib

from expectrail import resources
from expectrail.contracts import digest
from expectrail.orchestrator import engines, sample
from harness import sandbox, tree


def png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 128, 96, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\0' + bytes(128 * 3)) * 96)) + chunk(b'IEND', b''))


def replay(route, game, out, frames):
    ticks = json.loads(route.read_text())['ticks']
    broken = 'collision_mask = 14' in (game / 'player/player.tscn').read_text()
    view = [1, 0, 0, 1, 0, 0]
    rows = [{'tick': n, 'player': [70, 86.75 + (max(0, n // 2 - 33) * 5 if broken else 0)],
             'onFloor': not broken, 'ground': 100, 'view': view} for n in range(ticks)]
    trace = {'physicsTicksPerSecond': 120, 'rows': rows, 'unknownActions': [],
             'captureTimeline': {'fps': 60, 'frames': [
                 {'frame': n, 'tick': 2 * n + 1, 'tickInterval': [2 * n, 2 * n + 1],
                  'phase': 'post-physics-pre-draw', 'viewport': [128, 96], 'transform': view}
                 for n in range(ticks // 2)]}}
    folder = out / 'frames'
    folder.mkdir(parents=True, exist_ok=True)
    for n in range(ticks // 2):
        (folder / f'f{n:08d}.png').write_bytes(png())
    (out / 'trace.json').write_text(json.dumps(trace))
    return {'trace': trace, 'replaySha256': digest(trace), 'framesDir': folder, 'timelineRequired': True,
            'tree': tree.digest(game, skip=tree.GODOT_SKIP),
            'isolation': sandbox.describe(sandbox.Tool('stand-in', 'stand-in'), 'require', None)}


if __name__ == '__main__':
    assert resources.ROOT.name == '_bundle', 'must exercise the installed wheel'
    for optional in ('jsonschema', 'numpy', 'PIL'):
        assert importlib.util.find_spec(optional) is None, optional
    sys.argv = sys.argv[1:]
    injected = functools.partial(sample.run, engines={'godot': engines.GodotGate(replay=replay)})
    with mock.patch.object(sample, 'run', injected):
        runpy.run_path(sys.argv[0], run_name='__main__')
