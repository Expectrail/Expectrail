"""Hand-written stand-in proposals of counter checks for the two pause-menu counter defects (#285).

No model wrote these checks. Each proposal holds one check per menu probe of the `signals-reach-evidence-menu`
setting: "after this walk, the pause menu's one integer label equals the coins the engine says were picked
up" (``signal_compare`` of ``coins_collected`` and ``ui_integer_at_end``, equal, no tolerance). It is written
as a proposal so that `jit run --proposal` replays it under the keep rule itself: three runs on the clean
game, three on the bug build, three on the candidate. The keep rule, not this tool, decides which of the
three checks are kept; the tool does not pick the probes the bench's menu evidence shows the defect on.

The proposals are made with the candidate withheld, so each is bound to its defect's report and to no patch.
The answer goes through the parser a model's answer goes through (``intent.parse_answer``), so a check the
menu setting does not offer is refused here as it would be there.

    python3 -m tools.menu_counter_stand_in --defect coin-counts-twice --out DIR   # writes DIR/jit-proposal.json

The committed copies are bench/jit/stand-in/<defect>-menu-counter/jit-proposal.json, and
tests/test_menu_counter_stand_in.py holds that they are what this writes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from expectrail.jit import intent, offer as offer_mod

ROOT = Path(__file__).resolve().parents[1]
DEFECTS = ("coin-counts-twice", "coin-counter-stuck")
OFFER = offer_mod.MENU
MODEL = "hand-written-stand-in"
COUNTER = {"type": "signal_compare", "leftSignal": "coins_collected", "rightSignal": "ui_integer_at_end",
           "comparator": "eq", "toleranceAbs": 0}


def report_path(defect: str) -> Path:
    return ROOT / "bench" / "jit" / "public" / defect / "report.txt"


def committed(defect: str) -> Path:
    return ROOT / "bench" / "jit" / "stand-in" / f"{defect}-menu-counter" / intent.PROPOSAL_NAME


def _check(defect: str) -> str:
    if defect not in DEFECTS:
        raise ValueError(f"no counter stand-in for {defect!r}; there is one for {', '.join(DEFECTS)}")
    return defect


def answer(probes: list[dict]) -> dict:
    """The answer a model would give: one counter check on each menu probe of ``probes``, and nothing else."""
    menu = [p["id"] for p in probes if p.get("family") == offer_mod.MENU_FAMILY]
    if not menu:
        raise ValueError(f"the probe list has no menu probe; the offer {OFFER} should have three")
    return {"probes": [], "candidates": [{
        "id": f"menu-counter-{probe}",
        "statement": "After this walk the pause menu's coin counter shows the number of coins the player picked up.",
        "claimId": "player.jump",  # the bundled profile has no coin claim; the menu-setting tests use this one too
        "class": "player",
        "operation": dict(COUNTER),
        "appliesTo": [probe],
    } for probe in menu]}


def stand_in():
    """An intent callable that proposes ``answer()``'s checks through the model's parser, and calls no model."""
    def propose(report, patch_text, dmap, profile, probes):
        new, entries, notes = intent.parse_answer(json.dumps(answer(probes)), profile, {p["id"] for p in probes},
                                                  offer=OFFER)
        return {"probes": new, "candidates": entries, "usage": {"model": MODEL}, "promptSha256": None,
                "diagnostics": ["hand-written stand-in: no model was called (tools/menu_counter_stand_in.py)",
                                *notes]}
    propose.model, propose.system, propose.offer = MODEL, "", OFFER
    propose.candidate, propose.observer = intent.WITHHELD, intent.SAM
    return propose


def library(defect: str):
    """(profile, report, probes) for ``defect`` under the menu setting, as `jit run` makes them."""
    from expectrail.contracts import load_strict
    from expectrail.jit.cli import PROFILE

    profile = load_strict(PROFILE, "mechanics-profile")
    report = report_path(_check(defect)).read_text(encoding="utf-8", errors="replace")
    return profile, report, offer_mod.library(profile["actions"], OFFER, report, profile=profile)


def write(defect: str, out: Path) -> dict:
    """Write ``defect``'s stand-in proposal to ``out/jit-proposal.json`` the way `propose` writes one."""
    profile, report, probes = library(defect)
    return intent.propose_to_file(stand_in(), report, "", profile, probes, out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--defect", choices=DEFECTS, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    doc = write(args.defect, args.out)
    print(json.dumps({"candidates": [c["spec"]["id"] for c in doc["candidates"]], "error": doc["error"]}))
    return 0 if doc["error"] is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
