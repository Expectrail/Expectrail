"""The probes generated checks may use: the discovery library (expectrail/discovery/probes.py) plus
the jump taps run once more, after walking the other way.

A rise can only be measured where nothing is overhead, and a level's start often sits under a
platform. On the platformer every spot the library's right-hand walk sweep reaches has a platform
within reach of a double jump, so two presses and eight give the same height on any build, and a
height check there can never tell the infinite-jump bug from its fix (live run 42908014398 proposed
exactly those two checks, and neither was valid). Walking left for 40 ticks reaches open sky.

The discovery library itself is left alone: it is part of discovery's freeze (expectrail/discovery/
freeze.py), and these probes are only used here.
"""
from __future__ import annotations

from expectrail.discovery.probes import JUMP_COUNTS, JUMP_EVERY, _taps, _walk, library

WALK_LEFT = (40,)


def jit_library(actions) -> list[dict]:
    probes = library(actions)
    actions = set(actions)
    if {"jump", "move_left"} <= actions:
        for walk in WALK_LEFT:
            for n in JUMP_COUNTS:
                program = {"op": "sequence", "steps": [*_walk("left", walk), {"op": "wait", "durationTicks": 10},
                                                       _taps("jump", n, JUMP_EVERY)]}
                probes.append({"id": f"jump-l{walk}-x{n}", "family": "jump-taps",
                               "description": f"Walk left for {walk} ticks, stop, then press jump {n} times, "
                                              f"every {JUMP_EVERY} ticks.",
                               "program": program, "tags": sorted({"no-shoot", f"jump-l{walk}", f"jump-x{n}"})})
    return probes
