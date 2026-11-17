"""A hand-written stand-in proposal of `faces-motion` checks for `enemy-walks-backwards` (#286).

No model wrote these checks. They are the three windowed checks measured by hand on November 16
(docs/jit.md, "Which way the enemy faces"), written as a proposal so that `jit run --proposal` replays them
under the keep rule itself: three runs on the clean game, three on the bug build, three on the candidate.
That is the offline half of "a generated pixel check reproduces a screen-only defect end to end"; the other
half, a model proposing such a check, needs a live run.

The proposal is made with the candidate withheld, so it is bound to the bench's report and to no patch, and
under the pixel setting for the no-model sensor. Each window starts after the last frame the bench's
evidence lists the enemy as partly on screen on that probe (`edges`, #590), so no judged frame is a gap
for that reason.

    python3 -m tools.faces_motion_stand_in --out DIR     # writes DIR/jit-proposal.json

The committed copy is bench/jit/stand-in/enemy-walks-backwards-faces-motion/jit-proposal.json, and
tests/test_faces_motion_stand_in.py holds that it is what this writes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from expectrail.jit import intent, offer as offer_mod

ROOT = Path(__file__).resolve().parents[1]
DEFECT = "enemy-walks-backwards"
REPORT = ROOT / "bench" / "jit" / "public" / DEFECT / "report.txt"
EVIDENCE = ROOT / "bench" / "jit" / "public" / f"evidence-{DEFECT}.json"
COMMITTED = ROOT / "bench" / "jit" / "stand-in" / f"{DEFECT}-faces-motion" / intent.PROPOSAL_NAME
OFFER = "signals-reach-evidence-pixel"
OBSERVER = "visual-sensor"
MODEL = "hand-written-stand-in"

# (probe, first judged frame, what the statement says about the probe)
WINDOWS = (
    ("hold-right", 30, "holding right"),
    ("reverse", 130, "walking right and then back left"),
    ("move-fire-right", 30, "walking right and firing"),
)


def checks() -> list[dict]:
    return [{
        "id": f"jit-px-enemy-faces-motion-{probe}",
        "statement": f"While {said}, from frame {start} on, every enemy on screen is drawn facing the way the "
                     "engine moves it, in every frame where it walks one way.",
        "object": "enemy",
        "observer": OBSERVER,
        "probe": probe,
        "window": {"fromFrame": start},
        "predicate": {"type": "faces-motion"},
    } for probe, start, said in WINDOWS]


def last_enemy_edge(evidence: dict, probe: str) -> int | None:
    """The last frame the evidence lists the enemy partly on screen on ``probe``, or None if it lists none."""
    for row in evidence["rows"]:
        if row.get("probe") == probe:
            spans = (((row.get("edges") or {}).get("objects") or {}).get("enemy") or {}).get("spans")
            if spans is None:
                raise ValueError(f"the evidence cannot say where the enemy is partly on screen on {probe}")
            return spans[-1][1] if spans else None
    raise ValueError(f"the evidence has no row for {probe}")


def stand_in():
    """An intent callable that proposes ``checks()`` and nothing else, and calls no model."""
    def propose(report, patch_text, dmap, profile, probes):
        from expectrail.jit import pixel

        parsed = []
        for entry in checks():
            # Through the parser a model's answer goes through (intent.spark_intent), so the saved form is
            # what `run --proposal` re-checks. A refusal is written as the proposal's error, as `propose` writes one.
            check, why = pixel.parse_candidate(entry, pixel.bindings_for(), {p["id"] for p in probes},
                                               pixel.proposed(OBSERVER))
            if check is None:
                raise intent.IntentUnavailable(f"PROPOSAL_INVALID: {entry['id']}: {why}")
            parsed.append(check)
        return {"probes": [], "candidates": [], "pixelChecks": parsed, "usage": {"model": MODEL},
                "promptSha256": None,
                "diagnostics": ["hand-written stand-in: no model was called (tools/faces_motion_stand_in.py)"]}
    propose.model, propose.system, propose.offer = MODEL, "", OFFER
    propose.candidate, propose.observer = intent.WITHHELD, OBSERVER
    return propose


def write(out: Path) -> dict:
    """Write the stand-in proposal to ``out/jit-proposal.json`` the way `propose` writes one, and return it.
    Refuses a window that starts on or before a frame the bench's evidence lists the enemy partly on screen."""
    from expectrail.contracts import load_strict
    from expectrail.jit.cli import PROFILE

    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    for probe, start, _ in WINDOWS:
        last = last_enemy_edge(evidence, probe)
        if last is not None and start <= last:
            raise ValueError(f"the window on {probe} starts at {start}, on or before frame {last}, "
                             "where the enemy is partly on screen")
    profile = load_strict(PROFILE, "mechanics-profile")
    report = REPORT.read_text(encoding="utf-8", errors="replace")
    probes = offer_mod.library(profile["actions"], OFFER, report)
    return intent.propose_to_file(stand_in(), report, "", profile, probes, out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    doc = write(args.out)
    print(json.dumps({"pixelChecks": [c["id"] for c in doc["pixelChecks"]], "error": doc["error"]}))
    return 0 if doc["error"] is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
