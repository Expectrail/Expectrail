"""What the generator is offered: one named setting, the same in every step of one change.

    python -m expectrail.jit.cli measure|propose|revise|run ... --offer baseline|signals-reach|signals-reach-evidence

Issue #285 asks for the reproduction rate on the public bench "before changing anything", and then
after each step. Steps 3 and 4 were built before that baseline was run, so they are held back from
the generator (expectrail/jit/intent.py, ``NOT_YET_OFFERED``; expectrail/repro/reach.py). This module
names what each setting offers, so the "after" run is one input of the same workflow and the
baseline stays what it was:

- ``baseline`` (the default): the generator as it was before steps 3 and 4. The eleven signals of
  ``intent.SIGNAL_MEANINGS`` and the probe library of ``expectrail.jit.probes``. With this setting the
  system prompt, the user prompt and the probe list are byte for byte what they were before this
  module existed (tests/test_jit_offer.py holds the system prompt's digest).
- ``signals-reach``: also the three signals of #323 (``coins_collected``,
  ``player_screen_x_range_px``, ``player_screen_y_range_px``) and the reach probes of #336, the short
  routes that press two actions together where no library probe does.
- ``signals-reach-evidence``: everything ``signals-reach`` offers, and step 5's evidence
  (expectrail/repro/evidence.py): along each probe, what the bug build changes against the clean
  game in the engine's record (which fields, from which tick) and **on the screen** (how many frames
  differ, from which frame, where). The measure step makes it by replaying every probe with frames
  (the clean game twice, the bug build once); the propose and revise steps put the summary that
  ``evidence.for_proposer`` makes on at most six probes of the prompt (``differs``). Like the
  measurements, it comes from the clean game and the bug build only, never the candidate (#285, step 6).
  No visual observer is asked or read for it.

Nothing about what decides a check changes: a check is kept or dropped by replays only
(expectrail/jit/assess.py), under either setting.

**One setting per change.** The setting is written into the proposal (``offer``) and into the run
record (``settings.offer``). A saved proposal is replayed only under the setting it was made with, a
revision only under the setting of its first round, and the reproduction score counts only records
made with the setting it was asked to count, so a rate measured with more on offer can never be read
as the baseline, nor the baseline as a later step. A record or proposal written before this setting
existed says nothing, and is read as ``baseline``, which is what it was.

Where the reach probes can be used. They join the library with family ``reach``. The diff map
(expectrail/jit/diff_map.py) keeps every probe when the change touches no file a profile claim maps
to a family, which is the case on the reproduction bench (its stand-in candidate changes the game's
README); a candidate that maps to known families keeps only those families' probes, and ``reach`` is
none of them yet.
"""
from __future__ import annotations

BASELINE = "baseline"
SIGNALS_REACH = "signals-reach"
EVIDENCE = "signals-reach-evidence"
OFFERS = (BASELINE, SIGNALS_REACH, EVIDENCE)
DEFAULT = BASELINE


class OfferError(ValueError):
    """Not a setting this module knows, or two steps of one change disagree about it."""


def check(offer) -> str:
    if offer not in OFFERS:
        raise OfferError(f"unknown offer {str(offer)[:40]!r}: one of {', '.join(OFFERS)}")
    return offer


def of_record(value) -> str:
    """The setting a proposal or run record states; a record from before the setting existed is ``baseline``."""
    return DEFAULT if value is None else check(value)


def shows_evidence(offer) -> bool:
    """Whether the proposer is given step 5's evidence (what the bug build changes, record and screen)."""
    return check(offer) == EVIDENCE


def meanings(offer: str) -> dict[str, str]:
    """{signal: what it measures} for the signals the generator is told about under ``offer``."""
    from expectrail.jit.intent import NOT_YET_OFFERED, SIGNAL_MEANINGS

    check(offer)
    return dict(SIGNAL_MEANINGS) if offer == BASELINE else {**SIGNAL_MEANINGS, **NOT_YET_OFFERED}


def signals(offer: str) -> tuple[str, ...]:
    return tuple(sorted(meanings(offer)))


def library(actions, offer: str, report: str = "") -> list[dict]:
    """The probes the generator may use under ``offer``: the jit library, then (any setting but ``baseline``) the
    reach probes for the pairs of actions it never presses together, ordered by the report.

    The report only orders the reach probes and, when there are more than the reach limit, decides
    which are left out (expectrail/repro/reach.py); on the platformer there are eight, so every report
    gets the same set."""
    from expectrail.jit.probes import jit_library

    check(offer)
    probes = jit_library(actions)
    if offer == BASELINE:
        return probes
    from expectrail.repro.reach import reach

    return probes + reach(report if isinstance(report, str) else "", actions, probes)["probes"]


def attach_evidence(probes: list[dict], path, base: list, offer: str) -> list[str]:
    """Under ``signals-reach-evidence``, put step 5's evidence (expectrail/repro/evidence.py) on the probes
    it shows, as ``differs``. Returns diagnostics, like ``expectrail.jit.cli.attach_measurements``: empty when it was
    attached; otherwise why not, and the proposal goes ahead without it.

    The record is read as untrusted data: ``evidence.load`` checks it against its schema and itself and
    that it was made for these base patches, and ``evidence.for_proposer`` keeps only this library's
    probe ids, the trace's own fields and signals, and numbers. Under any other setting nothing is
    attached, and a file given anyway is said and not read."""
    if not shows_evidence(offer):
        return [] if path is None else [f"evidence: not used: the offer {offer} does not offer it"]
    if path is None:
        return ["evidence: none given"]
    from expectrail.repro.evidence import EvidenceError, for_proposer, load

    try:
        summary = for_proposer(load(path, base_patches=base), probes=[p["id"] for p in probes])
    except (EvidenceError, OSError) as exc:
        return [" ".join(f"evidence: not used: {exc}".split())[:200]]
    header = {"ticksPerSecond": summary["ticksPerSecond"], "framesPerSecond": summary["framesPerSecond"],
              "frame": summary["frame"]}
    shown = {e["probe"]: e for e in summary["probes"]}
    for p in probes:
        p.pop("differs", None)
        if p["id"] in shown:
            p["differs"] = {**header, "record": shown[p["id"]]["record"], "screen": shown[p["id"]]["screen"]}
    notes = []
    if summary["probesNotCompared"]:
        notes.append(f"evidence: {summary['probesNotCompared']} probes could not be compared")
    if summary["probesNotKnown"]:
        notes.append(f"evidence: {summary['probesNotKnown']} probes that differ are not in this library")
    return notes


def make_evidence(profile: dict, probes: list[dict], base: list, out, *, game=None,
                  jobs: int = 1, runner=None) -> dict:
    """The measure step's second record under ``signals-reach-evidence``: ``out/repro-evidence.json``.
    Replays every probe with frames, the clean game twice and the bug build once. No model, no key."""
    from expectrail.repro.evidence import evidence

    if runner is None:
        from functools import partial
        from pathlib import Path

        from harness.run import run as harness_run

        runner = partial(harness_run, capture_frames=True, **({"game": Path(game)} if game else {}))
    return evidence(profile, probes, base, out, runner=runner, jobs=jobs)
