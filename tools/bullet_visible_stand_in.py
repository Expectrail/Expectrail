"""A hand-written stand-in proposal of `visible` bullet checks for `bullet-behind-scenery`, judged by SAM (#286).

No model wrote these checks. `bullet-behind-scenery` draws the player's bullets behind the platforms and
rocks (`z_index` 5 becomes -5), so nothing in the engine's record changes; only what is drawn does. The
no-model sensor cannot be asked about the bullet (its bank holds no bullet template: the bullet's additive
glow leaves no crop with enough opaque detail, docs/new-work/2026-11-16-sensor-enemy.md), so the observer
these checks name is `sam-3.1-anchor`, asked at each bullet's logged box.

The proposal is written so that `jit run --proposal --pixel-capture` replays the checks' probes with frames
(no secret, no SAM call) and `pixel-ask` can say exactly what asking SAM about them would reserve. It is made
with the candidate withheld, so it is bound to the bench's report and to no patch, under the pixel setting.
The probes are three of the six on which the bench's screen record shows the defect. Each window is chosen
so that every frame SAM would be asked about in it (``sam_observer.plan_frames``, the default plan):

- has no more bullets on screen than SAM is asked about in one frame (``pixel.MAX_BOXES``) on any captured
  replay: SAM's observer does not ask about such a frame, so it is a gap, and a check with a gap is never
  kept (``PLAN``, measured with ``--measure`` from a capture of the whole probes);
- is clear of the frames the bench's evidence lists a bullet partly on screen (`edges`). SAM is asked about a
  box cut to the picture, so this is the sensor's rule, kept so the windows read the same to a proposer
  given that evidence;

and so that the clean game has a bullet on screen in at least one of them on every captured replay.

The capture, the asking job, the in-process replay and the judging job ask SAM only about the planned
frames inside the windows of the checks on a probe (#605; expectrail/jit/pixel.py ``planned``), so the three
checks reserve 675 images, $1.69 at list price (``reserved_images``), under jit.yml's per-change cap of $2
(``CAP_USD``) less the capture's own spend. Before #605 every ``DEFAULT_EVERY``-th frame of each probe's
route was asked about, whatever the windows: 1,296 images, $3.24, and the asking job refused.

    python3 -m tools.bullet_visible_stand_in --out DIR          # writes DIR/jit-proposal.json
    python3 -m tools.bullet_visible_stand_in --measure CAPTURE  # writes PLAN from a --pixel-capture folder

The committed copy is bench/jit/stand-in/bullet-behind-scenery-visible/jit-proposal.json, and
tests/test_bullet_visible_stand_in.py holds that it is what this writes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from expectrail.jit import intent, offer as offer_mod

ROOT = Path(__file__).resolve().parents[1]
DEFECT = "bullet-behind-scenery"
REPORT = ROOT / "bench" / "jit" / "public" / DEFECT / "report.txt"
EVIDENCE = ROOT / "bench" / "jit" / "public" / f"evidence-{DEFECT}.json"
COMMITTED = ROOT / "bench" / "jit" / "stand-in" / f"{DEFECT}-visible" / intent.PROPOSAL_NAME
OFFER = "signals-reach-evidence-pixel"
OBSERVER = "sam-3.1-anchor"
MODEL = "hand-written-stand-in"
# Frames are captured at 60 a second and the engine ticks 120 a second: two ticks a frame.
TICKS_A_FRAME = 2

PLAN = COMMITTED.parent / "capture-plan.json"
# jit.yml's default spend cap for one change (budget_usd), which pixel-ask gets less the capture's own spend.
CAP_USD = 2.0

# (probe, window, what the statement says about the probe)
PROBES = (
    ("shoot-left-every12", {"fromFrame": 50}, "standing and firing left every 12 ticks"),
    ("move-fire-left", {"fromFrame": 90}, "walking left and firing"),
    ("move-fire-right", {"fromFrame": 10, "toFrame": 80}, "walking right and firing"),
)


# The no-model sensor's windows (November 19). The sensor does not judge a bullet in its fade, the last 0.3 s of
# its 1.3 s life, nor one whose searched path another logged box touches (agents/template_radial.py ``crowded``;
# a gap either way: on the real engine, a clean bullet overlapping another one was not found). Both are read from
# the trace alone. So each window here starts where the SAM window starts and ends at the last planned frame before
# the first planned frame with such a bullet on screen on the clean game's replay: frame 60 of shoot-left-every12
# (two bullets crowded) and frame 40 of move-fire-right (one crowded). move-fire-left has one at frame 90, where its
# SAM window starts, and is left out.
SENSOR_PROBES = (
    ("shoot-left-every12", {"fromFrame": 50, "toFrame": 50}, "standing and firing left every 12 ticks"),
    ("move-fire-right", {"fromFrame": 10, "toFrame": 30}, "walking right and firing"),
)


def probes_for(observer: str = OBSERVER):
    return SENSOR_PROBES if observer == "visual-sensor" else PROBES


def checks(observer: str = OBSERVER) -> list[dict]:
    return [{
        "id": f"jit-px-bullet-visible-{probe}",
        "statement": f"While {said}, {_span(window)}, every bullet on screen is drawn where the engine puts it, in every "
                     "frame, in front of the scenery.",
        "object": "bullet",
        "observer": observer,
        "probe": probe,
        "window": dict(window),
        "predicate": {"type": "visible", "minFraction": 1.0},
    } for probe, window, said in probes_for(observer)]


def _span(window: dict) -> str:
    if "toFrame" in window:
        return f"from frame {window['fromFrame']} to frame {window['toFrame']}"
    return f"from frame {window['fromFrame']} on"


def in_window(frames, window: dict) -> list[int]:
    return [n for n in frames if n >= window["fromFrame"] and ("toFrame" not in window or n <= window["toFrame"])]


def bullet_edges(evidence: dict, probe: str) -> set[int]:
    """The frames the evidence lists a bullet partly on screen on ``probe``."""
    for row in evidence["rows"]:
        if row.get("probe") == probe:
            spans = (((row.get("edges") or {}).get("objects") or {}).get("bullet") or {}).get("spans")
            if spans is None:
                raise ValueError(f"the evidence cannot say where a bullet is partly on screen on {probe}")
            return {n for lo, hi in spans for n in range(lo, hi + 1)}
    raise ValueError(f"the evidence has no row for {probe}")


def planned(probes: list[dict], profile: dict) -> dict[str, list[int]]:
    """{probe: the frames SAM's default plan asks about on it}, from each probe's compiled route alone."""
    from expectrail.discovery.route_compiler import compile_route
    from expectrail.jit import sam_observer

    out = {}
    for p in probes:
        route = compile_route(p["program"], name=p["id"], description=p["description"], actions=profile["actions"])
        out[p["id"]] = sam_observer.plan_frames(route, TICKS_A_FRAME, sam_observer.DEFAULT_EVERY, None,
                                                sam_observer.MAX_FRAMES)
    return out


def measure(capture: Path) -> dict:
    """How many bullets the engine logged on screen on each planned frame of each replay a ``--pixel-capture``
    folder kept: {"probes": {probe: {"planned": [...], "bullets": {build: {"<n>": [count, ...]}}}}}, one count
    a planned frame. Read with ``pixel_jobs.replays`` and ``sam_observer.checked_replay``, so only a folder
    that a capture job could have written, and replays whose frames are their own, are measured."""
    from agents import sam_anchor
    from expectrail.jit import pixel, pixel_jobs, sam_observer

    probes: dict = {}
    for name, folder in pixel_jobs.replays(Path(capture)):
        build, run = name.split("/")
        probe, rep = run.rsplit("-", 1)
        route = json.loads((folder / "route.json").read_text(encoding="utf-8"))
        frames = sam_observer.plan_frames(route, TICKS_A_FRAME, sam_observer.DEFAULT_EVERY, None,
                                          sam_observer.MAX_FRAMES)
        # A capture keeps only the planned frames inside the checks' windows (#605); the bullets are counted
        # from the engine's record on every planned frame, so the plan reads the same either way.
        kept = pixel.in_windows(frames, pixel_jobs.windows_of(folder))
        _, _, files = sam_observer.checked_replay(folder, route, kept, sam_observer.DEFAULT_FPS,
                                                  sam_observer.DEFAULT_TICKS_PER_SECOND)
        size = _frame_size(files[kept[0]])
        trace = json.loads((folder / "trace.json").read_text(encoding="utf-8"))
        boxes = sam_anchor.object_boxes(trace, size, frames, "bullet")
        counts = [len(boxes[n]["boxes"]) if "boxes" in boxes[n] else None for n in frames]
        entry = probes.setdefault(probe, {"planned": frames, "bullets": {}})
        if entry["planned"] != frames:
            raise ValueError(f"{name}: planned frames differ from another replay of {probe}")
        entry["bullets"].setdefault(build, {}).setdefault(rep, counts)
    return {"source": "tools/bullet_visible_stand_in.py measure", "every": sam_observer.DEFAULT_EVERY,
            "maxBoxes": pixel.MAX_BOXES,
            "probes": {p: probes[p] for p in sorted(probes)}}


def _frame_size(path) -> tuple[int, int]:
    """(width, height) of one captured frame. Pillow is needed only to measure a real capture."""
    from PIL import Image

    with Image.open(path) as image:
        return image.size


def window_problems(plan: dict, probe: str, window: dict) -> list[str]:
    """Why ``window`` on ``probe`` would leave a check that cannot be kept, by the measured ``plan``: a frame
    with more bullets than SAM is asked about (a gap on that replay), a frame the engine could not place
    them in, or no frame in the window where the clean game has a bullet on screen on every replay."""
    entry = (plan.get("probes") or {}).get(probe)
    if entry is None:
        return [f"the capture plan has no replay of {probe}"]
    at = {n: i for i, n in enumerate(entry["planned"])}
    frames = in_window(entry["planned"], window)
    out = []
    for build, reps in sorted(entry["bullets"].items()):
        for rep, counts in sorted(reps.items()):
            for n in frames:
                c = counts[at[n]]
                if c is None:
                    out.append(f"{probe}: frame {n} of {build} {rep} has no bullet boxes")
                elif c > plan["maxBoxes"]:
                    out.append(f"{probe}: frame {n} of {build} {rep} has {c} bullets on screen, more than "
                               f"{plan['maxBoxes']}")
    clean = entry["bullets"].get("pixel-reference") or {}
    if not clean or any(not any(counts[at[n]] for n in frames) for counts in clean.values()):
        out.append(f"{probe}: no frame in the window has a bullet on screen on every clean replay")
    return out


def reserved_images(plan: dict) -> int:
    """Images pixel-ask reserves for the checks' probes (expectrail/jit/pixel_jobs.py ``ask``): the planned
    frames of each probe's route inside the windows of its checks (#605), MAX_BOXES a frame, on nine replays
    (three builds, three each)."""
    from expectrail.jit import pixel

    windows: dict = {}
    for probe, window, _ in PROBES:
        windows.setdefault(probe, []).append(window)
    return sum(len(pixel.in_windows(plan["probes"][probe]["planned"], windows[probe])) * plan["maxBoxes"] * 9
               for probe in sorted(windows))


def stand_in(observer: str = OBSERVER):
    """An intent callable that proposes ``checks(observer)`` and nothing else, and calls no model."""
    def propose(report, patch_text, dmap, profile, probes):
        from expectrail.jit import pixel

        parsed = []
        for entry in checks(observer):
            # Through the parser a model's answer goes through (intent.spark_intent), so the saved form is
            # what `run --proposal` re-checks. A refusal is written as the proposal's error, as `propose` writes one.
            check, why = pixel.parse_candidate(entry, pixel.bindings_for(), {p["id"] for p in probes},
                                               pixel.proposed(observer))
            if check is None:
                raise intent.IntentUnavailable(f"PROPOSAL_INVALID: {entry['id']}: {why}")
            parsed.append(check)
        return {"probes": [], "candidates": [], "pixelChecks": parsed, "usage": {"model": MODEL},
                "promptSha256": None,
                "diagnostics": ["hand-written stand-in: no model was called (tools/bullet_visible_stand_in.py)"]}
    propose.model, propose.system, propose.offer = MODEL, "", OFFER
    propose.candidate, propose.observer = intent.WITHHELD, observer
    return propose


def write(out: Path, observer: str = OBSERVER) -> dict:
    """Write the stand-in proposal for ``observer`` to ``out/jit-proposal.json`` the way `propose` writes one, and
    return it. The no-model sensor plans the same frames as SAM. Refuses a probe on which the plan would ask about a frame the bench's evidence lists a bullet partly
    on screen."""
    from expectrail.contracts import load_strict
    from expectrail.jit.cli import PROFILE

    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    profile = load_strict(PROFILE, "mechanics-profile")
    report = REPORT.read_text(encoding="utf-8", errors="replace")
    probes = offer_mod.library(profile["actions"], OFFER, report)
    plans = planned([p for p in probes if p["id"] in {probe for probe, _, _ in PROBES}], profile)
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    for probe, window, _ in probes_for(observer):
        clash = sorted(set(in_window(plans[probe], window)) & bullet_edges(evidence, probe))
        if clash:
            raise ValueError(f"the observer would be asked about frames {clash} of {probe}, where a bullet is partly on screen")
    for probe, window, _ in probes_for(observer):
        if plan["probes"].get(probe, {}).get("planned") != plans[probe]:
            raise ValueError(f"the capture plan for {probe} was measured on other planned frames")
        problems = window_problems(plan, probe, window)
        if problems:
            raise ValueError("; ".join(problems))
    return intent.propose_to_file(stand_in(observer), report, "", profile, probes, out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    what = ap.add_mutually_exclusive_group(required=True)
    what.add_argument("--out", type=Path, help="write DIR/jit-proposal.json")
    what.add_argument("--measure", type=Path, metavar="CAPTURE", help="write the capture plan from a capture folder")
    ap.add_argument("--observer", default=OBSERVER, choices=("sam-3.1-anchor", "visual-sensor"),
                    help="the observer the checks name (default SAM; the no-model sensor since November 19)")
    args = ap.parse_args(argv)
    if args.measure:
        PLAN.write_text(json.dumps(measure(args.measure), indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"plan": str(PLAN.relative_to(ROOT))}))
        return 0
    doc = write(args.out, args.observer)
    print(json.dumps({"pixelChecks": [c["id"] for c in doc["pixelChecks"]], "error": doc["error"]}))
    return 0 if doc["error"] is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
