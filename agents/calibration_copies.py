"""Emit the four bundled-game #330 visual defects as patches; never edit the source game.

python -m agents.calibration_copies --game game/platformer --out /tmp/calibration-patches
Replay with harness.run.run(..., patches=[patch]): its normal copy/apply machinery is unchanged.
"""
from __future__ import annotations

import argparse
import difflib
from pathlib import Path


def write_patches(game, out):
    game, out = Path(game).resolve(), Path(out).resolve()
    if out == game or game in out.parents or out.exists():
        raise ValueError('patch output must be a new folder outside the game')
    sprite = 'player/player.tscn'
    scene = 'game_singleplayer.tscn'
    definitions = {
        'hidden': (sprite, 'position = Vector2(0, -14)\ntexture =', 'visible = false\nposition = Vector2(0, -14)\ntexture ='),
        'behind-scenery': (scene, 'z_index = 3\nposition = Vector2(90, 636.5)', 'z_index = -3\nposition = Vector2(90, 636.5)'),
        'texture-blanked': (sprite, 'texture = ExtResource("9")\nhframes', 'texture = null\nhframes'),
        'shifted-off-body': (sprite, 'position = Vector2(0, -14)\ntexture =', 'position = Vector2(70, -14)\ntexture ='),
    }
    patches = {}
    for name, (rel, before, after) in definitions.items():
        source = game / rel
        if source.is_symlink():
            raise ValueError('a calibration scene cannot be a link')
        original = source.read_text()
        if original.count(before) != 1:
            raise ValueError(f'{name}: bundled scene no longer has its unique mutation site')
        patches[name] = ''.join(difflib.unified_diff(original.splitlines(True), original.replace(before, after).splitlines(True),
                                                   fromfile=f'a/{rel}', tofile=f'b/{rel}'))
    out.mkdir(parents=True)
    paths = {}
    for name, text in patches.items():
        paths[name] = out / (name+'.patch');paths[name].write_text(text)
    return paths


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--game',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args(argv)
    for name,path in write_patches(a.game,a.out).items():print(f'{name}: {path}')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
