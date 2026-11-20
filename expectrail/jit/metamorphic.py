"""Metamorphic checks (#675, piece 3): a generated check that states its own obligation.

A check proposed for a report often states nothing a working game must do (piece 1 found that 56 of
135 pass when the actor does nothing). A metamorphic check states a relation between two runs of the
same game instead, and the relation holds on any game whose rules do not depend on the direction, so
no person writes the expected answer per game and no healthy reference build is needed.

Transformation 1, **mirror the inputs** (``mirror_x``): the twin probe is the probe with each
left/right action swapped. The pairs come from the action catalog: ``move_left``/``move_right``, the
names the probe library already uses, or whatever pairs a caller passes. The relations, per signal
(expectrail/trace/evaluator.py, ``MIRROR_SIGNALS``):

- the player's sideways travel negates (``player_dx_px``);
- its height, airborne time and air jumps stay equal (``max_rise_px``, ``airborne_ticks``, ``air_jumps``).

A level is not symmetric, so the evaluator judges only the clear window: from the first mirrored input
until either twin touches something the mirror did not also move. What cannot be mirrored is "cannot
tell" (``NoMirror``), never guessed: a probe with no paired action (the mirror would change nothing),
a pointer input, or an action whose name says left or right but which is not in a pair.

The generator offers them when asked (``run.generate(..., metamorphic=True)``, ``jit run --metamorphic``;
slice 2): ``offer`` picks at most ``PAIR_LIMIT`` pairs, and each check is judged by the same rule as a
proposed check, the do-nothing control included. Its rows are the record's ``metamorphic``, never in
``proposed``, ``validity``, ``catches``, ``counts``, the gate summary or the counting audit.
``tools/metamorphic_public.py`` measures every pair on the public bench.

Advisory: nothing here changes what may count or what may clear a change.
"""
from __future__ import annotations

import copy
import re

TRANSFORM = "mirror_x"
PAIR_LIMIT = 4  # pairs one run offers: 16 checks, at most 8 routes more to replay on each build
DEFAULT_PAIRS = (("move_left", "move_right"),)
CLAIM = "metamorphic.mirror-x"
TOLERANCE = {"player_dx_px": 2.0, "max_rise_px": 2.0, "airborne_ticks": 2, "air_jumps": 0}
_SIDED = re.compile(r"(^|[_\-.])(left|right)($|[_\-.])")
_STATEMENT = {
    "player_dx_px": "mirrors the player's sideways travel",
    "max_rise_px": "leaves the player's highest rise unchanged",
    "airborne_ticks": "leaves the player's time in the air unchanged",
    "air_jumps": "leaves the number of jumps made in the air unchanged",
}


class NoMirror(ValueError):
    """This probe has no mirror the evaluator can check; the message says why."""


def pairs_for(actions, pairs=DEFAULT_PAIRS) -> list[list[str]]:
    """The pairs whose two actions are both in the catalog."""
    have = set(actions)
    return [[a, b] for a, b in pairs if a in have and b in have]


def _walk(node, swap: dict, used: set, sided: set):
    if isinstance(node, list):
        return [_walk(n, swap, used, sided) for n in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for key, value in node.items():
        if key == "action" and isinstance(value, str):
            if value in swap:
                used.add(value)
                value = swap[value]
            elif _SIDED.search(value):
                sided.add(value)
        elif key in ("pointer", "position") or (key == "op" and str(value).startswith("pointer")):
            raise NoMirror("a pointer input has no mirror the trace can check")
        out[key] = _walk(value, swap, used, sided) if key != "action" else value
    return out


def mirror_program(program: dict, pairs) -> dict:
    """The program with each paired action swapped; ``NoMirror`` when that would mean nothing."""
    if not pairs:
        raise NoMirror("the action catalog has no left/right pair")
    swap = {}
    for a, b in pairs:
        swap[a], swap[b] = b, a
    used: set = set()
    sided: set = set()
    mirrored = _walk(copy.deepcopy(program), swap, used, sided)
    if sided:
        raise NoMirror(f"{', '.join(sorted(sided))} names a side but is in no pair")
    if not used:
        raise NoMirror("the probe uses no paired action, so the mirror changes nothing")
    return mirrored


def mirror_probe(probe: dict, pairs) -> dict:
    return {"id": f"{probe['id']}-mirror", "family": f"{probe.get('family', 'probe')}-mirror",
            "description": f"{probe.get('description', probe['id'])} Mirrored: left and right swapped.",
            "program": mirror_program(probe["program"], pairs), "tags": sorted({*probe.get("tags", ()), "mirror"}),
            "mirrorOf": probe["id"]}


def spec(left: str, right: str, signal: str, pairs) -> dict:
    from expectrail.trace.evaluator import MIRROR_SIGNALS

    relation = MIRROR_SIGNALS[signal]
    return {"format": "expectrail.trace-spec/v1", "id": f"mm-mirror-{left}-{signal.replace('_', '-')}",
            "origin": "AUTO_RELATION",
            "statement": f"Mirroring the inputs of {left} {_STATEMENT[signal]}, while the player touches nothing "
                         f"the mirror does not also move."[:300],
            "expectationRef": {"claimId": CLAIM, "authority": "inferred_behavior"},
            "scope": {"class": "player"}, "window": {"kind": "episode"},
            "operation": {"type": "metamorphic", "transform": TRANSFORM, "pairs": [list(p) for p in pairs],
                          "signal": signal, "relation": relation, "toleranceAbs": TOLERANCE[signal],
                          "left": left, "right": right},
            "evidenceRequirement": {"minimumTriggers": 1, "minimumEvaluations": 1, "completeWindow": True},
            "guards": []}


def derive(probe: dict, actions, pairs=DEFAULT_PAIRS) -> dict:
    """{probe, mirror, entries} for one probe, or {probe, reason} when it has no mirror.

    Each entry has the generator's shape (``spec``, ``applies`` a pair, ``approved`` false) so a later
    slice can offer it without a new record type."""
    from expectrail.trace.evaluator import MIRROR_SIGNALS

    usable = pairs_for(actions, pairs)
    try:
        twin = mirror_probe(probe, usable)
    except NoMirror as exc:
        return {"probe": probe["id"], "mirror": None, "entries": [], "reason": f"cannot tell: {exc}"}
    entries = [{"templateId": f"metamorphic.{TRANSFORM}", "spec": spec(probe["id"], twin["id"], signal, usable),
                "approved": False, "applies": {"kind": "pair", "left": probe["id"], "right": twin["id"]},
                "source": "metamorphic"}
               for signal in MIRROR_SIGNALS]
    return {"probe": probe["id"], "mirror": twin, "entries": entries, "reason": None}


def offer(probes: list[dict], actions, first=(), limit: int = PAIR_LIMIT, pairs=DEFAULT_PAIRS) -> tuple[list[dict], list[dict]]:
    """(derivations, skipped) for one generator run: at most ``limit`` pairs, each a ``derive`` result.

    Only probes with a ``program`` the generator made are mirrored (a replayed report or a model's probe is
    not). The ids in ``first`` (the probes the proposed checks use) come first, then library order. A probe
    whose pair is the same two programs as one already offered (``hold-left`` is ``hold-right`` mirrored) is
    skipped, as is one with no mirror; ``skipped`` says why for each."""
    import hashlib
    import json

    def key(program):
        return hashlib.sha256(json.dumps(program, sort_keys=True).encode()).hexdigest()

    by_id = {p["id"]: p for p in probes if isinstance(p.get("program"), dict)}
    order = [i for i in dict.fromkeys(first) if i in by_id] + [p["id"] for p in probes if p["id"] in by_id]
    out, skipped, seen = [], [], set()
    for pid in dict.fromkeys(order):
        d = derive(by_id[pid], actions, pairs)
        if d["mirror"] is None:
            skipped.append({"probe": pid, "reason": d["reason"]})
            continue
        twin = frozenset((key(by_id[pid]["program"]), key(d["mirror"]["program"])))
        if twin in seen:
            skipped.append({"probe": pid, "reason": "the same two programs as a pair already offered"})
            continue
        if len(out) >= limit:
            skipped.append({"probe": pid, "reason": f"over the limit of {limit} pairs"})
            continue
        seen.add(twin)
        out.append(d)
    return out, skipped
