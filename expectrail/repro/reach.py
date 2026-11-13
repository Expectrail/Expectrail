"""Reach: short routes for behaviour no library probe exercises (issue #285, step 3).

    python3 -m expectrail.repro reach --report bench/jit/public/no-shooting-in-air/report.txt
    python3 -m expectrail.repro visibility --reach --out runs/repro-reach     # replays the game; no model, no key

A check can only fail on a defect when some route makes the game do the thing that is broken. The
probe library (expectrail/discovery/probes.py, expectrail/jit/probes.py) is a fixed set a tester
would try on any platformer, and it never presses two different actions close together except moving
while firing. On the public bench that is why ``no-shooting-in-air`` changes nothing on any of the 25
library probes: none shoots while in the air.

What this does, with no model and nothing written for one bug:

1. **What the library already does.** Every library probe is compiled to its route, and two actions
   count as *used together* on a route when one is pressed while the other is held down, or within
   ``NEAR_TICKS`` after the other was pressed.
2. **What is missing.** Every pair of different actions in the game's own action catalog that no
   library route uses together.
3. **A route for each.** Two probes per missing pair: hold the first and tap the second three times
   meanwhile, and the other way round. Each is a bounded action program for the same route compiler
   (expectrail/discovery/route_compiler.py), ``HOLD_TICKS`` long, so it is refused by the same rules
   as any other probe.

The bug report only **orders** them: a pair whose two actions the report names comes first, then a
pair with one, then the rest. It is untrusted text, and it is used for nothing else: it cannot add
an action, a duration or a probe, and with ``MAX_PROBES`` or fewer to make, every report gets the same
set. When there are more than ``MAX_PROBES``, the ones the report does not name are the ones left out,
and ``reach`` says how many.

A reach probe is a route, not a judgement. Whatever watches the game along it (the engine's record,
frames for a visual observer) is the caller's choice; nothing here reads either.

Offered to generated checks only under ``--offer signals-reach`` (expectrail/jit/offer.py). Under the
default, ``baseline``, ``expectrail.jit.run`` draws on ``jit_library`` alone and never imports this
module, so a live run on the bench is unchanged by it (the issue asks for the baseline first).
"""
from __future__ import annotations

import re
from itertools import combinations

from expectrail.discovery.route_compiler import ProgramError, compile_route
from expectrail.repro import bench

RECORD = bench.REPO / "bench" / "jit" / "public" / "visibility-reach.json"   # what the reach probes see, measured
NEAR_TICKS = 20      # a press this soon after another action's press counts as made together
HOLD_TICKS = 60      # half a second: the first action is held this long
TAP_TICKS = 4
FIRST_TAP_AFTER = 8  # the second action's first tap, in ticks after the first is pressed
TAP_EVERY = 16       # then every 16 ticks: taps at 8, 24 and 40, all inside the hold
TAPS = 3
SETTLE_TICKS = 30
MAX_PROBES = 8       # bounded in count; each is HOLD_TICKS + SETTLE_TICKS plus the compiler's lead and tail
MAX_ACTIONS = 16     # a catalog larger than this is not paired at all
MAX_REPORT_CHARS = 8000
MAX_ID_CHARS = 60    # a probe name in a visibility record (contracts/repro-visibility.v1.schema.json)
FAMILY = "reach"
NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


class ReachError(ValueError):
    """The action catalog cannot be paired."""


def used_together(route: dict) -> set[frozenset[str]]:
    """The pairs of different actions a route uses together: one is pressed while the other is down, or
    within NEAR_TICKS after the other was pressed."""
    down: dict[str, int] = {}          # action -> tick it was pressed, while it is held
    last_press: dict[str, int] = {}
    pairs: set[frozenset[str]] = set()
    for ev in sorted(route["events"], key=lambda e: (e["tick"], e["pressed"])):   # releases before presses on a tick
        action, tick = ev["action"], ev["tick"]
        if not ev["pressed"]:
            down.pop(action, None)
            continue
        for other, at in last_press.items():
            if other != action and (other in down or tick - at <= NEAR_TICKS):
                pairs.add(frozenset((action, other)))
        down[action] = tick
        last_press[action] = tick
    return pairs


def _catalog(actions) -> list[str]:
    names = list(actions)
    if len(set(names)) != len(names) or not all(isinstance(a, str) and NAME.match(a) for a in names):
        raise ReachError("the action catalog has a name that is not a plain action name, or one twice")
    if len(names) > MAX_ACTIONS:
        raise ReachError(f"the action catalog has {len(names)} actions (max {MAX_ACTIONS} to pair)")
    return names


def missing_pairs(actions, probes: list[dict]) -> list[tuple[str, str]]:
    """Every pair of different catalog actions no probe uses together, in catalog order.

    A probe the compiler refuses reaches nothing, so it covers nothing."""
    names = _catalog(actions)
    covered: set[frozenset[str]] = set()
    for p in probes:
        try:
            route = compile_route(p["program"], name=p["id"], description=p["description"], actions=names)
        except ProgramError:
            continue
        covered |= used_together(route)
    return [(a, b) for a, b in combinations(names, 2) if frozenset((a, b)) not in covered]


def named(report, actions) -> list[str]:
    """The catalog actions a report names: one of the action's own words starts a word of the report.

    ``move_left`` is named by "left" and by "moving"; ``jump`` by "jumping". Words of one or two
    letters name nothing. This only orders probes, so a wrong match costs an order, never a probe."""
    text = str(report)[:MAX_REPORT_CHARS].lower() if isinstance(report, str) else ""
    words = set(re.findall(r"[a-z]{3,}", text))
    out = []
    for action in _catalog(actions):
        stems = [w[:-1] if w.endswith("e") else w for w in action.split("_") if len(w) >= 3]
        if any(word.startswith(stem) for stem in stems for word in words):
            out.append(action)
    return out


def _probe(held: str, tapped: str) -> dict:
    taps: list[dict] = [{"op": "wait", "durationTicks": FIRST_TAP_AFTER}]
    for i in range(TAPS):
        taps.append({"op": "tap", "action": tapped, "durationTicks": TAP_TICKS})
        if i < TAPS - 1:
            taps.append({"op": "wait", "durationTicks": TAP_EVERY - TAP_TICKS})
    program = {"op": "sequence", "steps": [
        {"op": "parallel", "branches": [{"op": "hold", "action": held, "durationTicks": HOLD_TICKS},
                                        {"op": "sequence", "steps": taps}]},
        {"op": "wait", "durationTicks": SETTLE_TICKS}]}
    tags = {FAMILY} | ({"no-shoot"} if "shoot" not in (held, tapped) else set())
    return {"id": f"reach-{held.replace('_', '-')}-with-{tapped.replace('_', '-')}", "family": FAMILY,
            "description": f"Hold {held} for {HOLD_TICKS} ticks and tap {tapped} {TAPS} times meanwhile, "
                           f"every {TAP_EVERY} ticks.",
            "program": program, "tags": sorted(tags)}


def reach(report, actions, probes: list[dict], limit: int = MAX_PROBES) -> dict:
    """{"probes": [...], "missingPairs": [[a, b], ...], "named": [...], "leftOut": n}.

    The probes for the pairs of actions ``probes`` never use together, at most ``limit`` of them,
    the pairs the report names first. ``leftOut`` counts the probes the limit dropped."""
    names = _catalog(actions)
    pairs = missing_pairs(names, probes)
    said = set(named(report, names))
    order = sorted(range(len(pairs)), key=lambda i: (-len(said & set(pairs[i])), i))
    made: list[dict] = []
    taken = {p["id"] for p in probes}
    for i in order:
        a, b = pairs[i]
        for held, tapped in ((a, b), (b, a)):
            probe = _probe(held, tapped)
            if probe["id"] in taken:
                raise ReachError(f"a probe is already called {probe['id']}")
            if len(probe["id"]) > MAX_ID_CHARS:
                raise ReachError(f"the probe name for {held} with {tapped} is over {MAX_ID_CHARS} characters")
            compile_route(probe["program"], name=probe["id"], description=probe["description"], actions=names)
            taken.add(probe["id"])
            made.append(probe)
    limit = max(0, min(int(limit), MAX_PROBES))
    return {"probes": made[:limit], "missingPairs": [list(p) for p in pairs],
            "named": [a for a in names if a in said], "leftOut": max(0, len(made) - limit)}


def reach_probes(actions, probes: list[dict]) -> list[dict]:
    """The one set of reach probes for a catalog, when it does not depend on the report.

    Refused when there are more than MAX_PROBES to make: then the report decides which are left out,
    and no single set stands for every report."""
    found = reach("", actions, probes)
    if found["leftOut"]:
        raise ReachError(f"{found['leftOut']} reach probes are over the limit of {MAX_PROBES}, so the set "
                         f"depends on the report")
    return found["probes"]
