"""The local app's offline kinematic-character preset. Only the observer uses saved answers."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile

from harness import tree
from expectrail import anchored, recorded, resources
from expectrail.gate import verify
from expectrail.orchestrator import engines, request, runner
from expectrail.orchestrator.store import JobStore

# The pinned walk's replay.json, game.tree (outside vision run 43652198623).
BASE_TREE = 'ba5fb112d7603f608f0054c767e45f23469efcfe2861a0d85d2f7f7e3e2e9747'
OUTSIDE = resources.ROOT / ('outside' if resources.INSTALLED else 'tests/outside')
ROUTE = OUTSIDE / 'kinematic-character/routes/walk.json'
SPEC = resources.ROOT / 'agents/specs/player-stays-above-ground.json'
RECORDING = OUTSIDE / 'recordings/kinematic-character'
WRONG_BASE = 'Choose the unchanged pinned kinematic-character game as Before.'


def checks():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        copy_policy(root)
        return verify.read_checks(root, 'specs', ['routes/walk.json'], 'base')


def copy_policy(root):
    for name, source in [('specs', SPEC), ('routes', ROUTE)]:
        folder = root / name
        folder.mkdir(parents=True)
        shutil.copyfile(source, folder / source.name)


def create_job(store, before, after):
    for game in (before, after):
        if store.root.is_relative_to(game):
            raise ValueError('The job store must be outside both game folders.')
    store.root.mkdir(parents=True, exist_ok=True)
    pair = Path(tempfile.mkdtemp(prefix='kinematic-', dir=store.root))
    try:
        for side, source in [('before', before), ('after', after)]:
            digest = tree.copy(source, pair / side / 'project', within=source, skip=tree.GODOT_SKIP)
            if side == 'before' and digest != BASE_TREE:
                raise ValueError(WRONG_BASE)
            copy_policy(pair / side)
        doc = request.build(adapter='godot', base=pair / 'before', head=pair / 'after', game='project',
                            routes=['routes/walk.json'], specs='specs')
        return store.create(doc)
    except Exception:
        shutil.rmtree(pair)
        raise


def start(store, job_id):
    return runner.spawn(store, job_id, command=[sys.executable, '-m', 'expectrail.app_kinematic',
                        str(store.root), str(store.lease_seconds), job_id])


def worker(store, job_id):
    client = recorded.RecordedClient(recorded.read_recording(RECORDING / 'vision-recording.json'))
    calibration = anchored.check_calibration(json.loads((RECORDING / 'calibration.json').read_bytes()))
    engine = engines.GodotGate(rule='both', visual=anchored.AnchoredObserver(client, calibration))
    runner.work(store, job_id, engines={'godot': engine}, own_group=True)
    print(f'Saved vision answers used for {client.answered} of {client.calls} questions.')


if __name__ == '__main__':
    worker(JobStore(Path(sys.argv[1]), lease_seconds=float(sys.argv[2])), sys.argv[3])
