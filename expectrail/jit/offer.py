"""What the generator is offered: one named setting, the same in every step of one change.

    python -m expectrail.jit.cli measure|propose|revise|run ... --offer baseline|signals-reach

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
OFFERS = (BASELINE, SIGNALS_REACH)
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


def meanings(offer: str) -> dict[str, str]:
    """{signal: what it measures} for the signals the generator is told about under ``offer``."""
    from expectrail.jit.intent import NOT_YET_OFFERED, SIGNAL_MEANINGS

    check(offer)
    return dict(SIGNAL_MEANINGS) if offer == BASELINE else {**SIGNAL_MEANINGS, **NOT_YET_OFFERED}


def signals(offer: str) -> tuple[str, ...]:
    return tuple(sorted(meanings(offer)))


def library(actions, offer: str, report: str = "") -> list[dict]:
    """The probes the generator may use under ``offer``: the jit library, then (``signals-reach``) the
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
