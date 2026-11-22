"""Prepare the bundled first-user trial for the local app, from a checkout."""
import argparse
import json
from pathlib import Path
import tempfile

from expectrail import project_config
from expectrail.orchestrator import sample


def prepare(destination):
    resolved = destination.resolve()
    if any(resolved.is_relative_to(sample.ROOT / source) for source in (sample.GAME, sample.SPECS)):
        raise ValueError('Choose a new folder outside the bundled game and its checks.')
    try:
        destination.mkdir()
    except FileExistsError as exc:
        raise ValueError('Choose a new folder. The destination already exists.') from exc

    try:
        with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
            pair = Path(temp) / 'projects'
            pair.mkdir()
            for name, bug in [('Clean', False), ('Broken', True)]:
                checkout = sample.checkout(Path(temp) / name, bug=bug)
                game = checkout / sample.GAME
                route = Path('routes/smoke.json')
                check = Path('checks/player-stays-above-ground.json')
                for relative, source in [(route, checkout / sample.ROUTE),
                                         (check, checkout / sample.SPECS / check.name)]:
                    (game / relative.parent).mkdir()
                    source.rename(game / relative)
                config = project_config.load(game / project_config.FILENAME)
                config.update(routes=[route.as_posix()], approvedContracts=[check.as_posix()])
                (game / project_config.FILENAME).write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
                game.rename(pair / name)
            # Publish both together. A file someone added to the reserved folder prevents replacement.
            pair.replace(destination)
    except BaseException:
        try:
            destination.rmdir()
        except OSError:
            pass  # Keep any files the user added during preparation.
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path, help='New folder for the Clean and Broken projects.')
    args = parser.parse_args(argv)
    try:
        prepare(args.destination)
    except (OSError, ValueError, sample.SampleError) as exc:
        parser.exit(1, f'Could not prepare the trial folders: {exc}\n')
    for name in ('Clean', 'Broken'):
        print(args.destination.resolve() / name)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
