"""Prepare the bundled outside example as an ordinary configured project.

This module prepares files only. Verification uses project_job, the normal CLI worker and Gate.
Existing approved check bytes are copied unchanged; this command never approves a check.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil

from harness import tree
from expectrail import project_config, resources

OUTSIDE = resources.ROOT / ('outside' if resources.INSTALLED else 'tests/outside')
ROUTE = OUTSIDE / 'kinematic-character/routes/walk.json'
SPEC = resources.ROOT / 'agents/specs/player-stays-above-ground.json'
RECORDING = OUTSIDE / 'recordings/kinematic-character'
CONFIG = resources.ROOT / 'contracts/examples/project-recorded.json'


def prepare(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(source):
        raise ValueError('Choose a new destination outside the source project.')
    if not (source / 'project.godot').is_file():
        raise ValueError('The source must contain project.godot.')
    project_config.load(CONFIG, source)  # The example's scene, player and image must exist.
    try:
        tree.copy(source, destination, within=source, skip=tree.GODOT_SKIP)
        for relative, original in [
            ('routes/walk.json', ROUTE), ('checks/' + SPEC.name, SPEC),
            ('vision/calibration.json', RECORDING / 'calibration.json'),
            ('vision/vision-recording.json', RECORDING / 'vision-recording.json'),
            (project_config.FILENAME, CONFIG),
        ]:
            target = destination / relative
            if target.exists():
                raise ValueError(f'The source already contains {relative}; no file is overwritten.')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
        project_config.read_game(destination)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description='Prepare a new configured copy of the bundled outside example; no verification or model call.')
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args(argv)
    try:
        print(prepare(args.source, args.destination))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
