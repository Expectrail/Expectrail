"""Pixel checks: generated checks that speak about what is drawn, not only the engine's record (#286).

A generated trace check reads the engine's position log, so a defect that only shows on the screen
(a sprite not drawn, drawn behind the scenery, drawn in the wrong place) is one no generated check
could ever fail on. A pixel check is the same kind of generated check, in a closed shape
(``expectrail.pixel-check/v1``, contracts/pixel-check.v1.schema.json), about what a trusted observer
sees in the frames:

- **The object is a bound role**, never free text. A project names its objects (#259 will make that
  ``expectrail.project/v1``); until then the bundled game's roles are ``BUNDLED_BINDINGS``.
- **The observer is a trusted one** (``OBSERVERS``), and it declares what it can and cannot tell. A
  check that asks it something it cannot tell is refused when it is proposed (``parse_candidate``),
  never passed later. ``sam-3.1-anchor`` is SAM 3.1 asked about the place the engine's record puts
  the object (agents/sam_anchor.py). ``visual-sensor`` is the no-model sensor of #262; it is declared
  so a check can name it, and refused until it exists.
- **The predicates are the reference evaluator's** (``visible``, ``inside-region``, ``never-crosses``,
  ``reaches``; expectrail/evaluator.py), and ``judge`` hands the decision to that evaluator.
- **A frame counts only where the observer and the engine's record are both there.** A frame in the
  window that the observer was not asked about (the engine puts the object outside the picture),
  could not answer, or that lacks the engine's box an ``inside-region`` check needs, is a gap; a
  check with any gap is ``needs-review`` on that run, never a pass or a fail.
- **The keep rule is the generated checks' rule** (``keep``): it passes on the clean build 3 runs of
  3 and fails on the buggy build 3 runs of 3, with the same observer setting on all six, or it is
  dropped with the reason.
- **Observer calls come out of the change's budget** (``reserve``): what a check would cost to judge
  on six runs is reserved against the per-change cap before anything is asked, and a check that
  cannot be afforded is ``not-run``.

Offered to the proposer under the pixel setting only (expectrail/jit/offer.py, ``PIXEL``): ``menu`` is what the prompt says can be judged, ``parse_answer`` reads the model's
``pixelChecks`` through ``parse_candidate``, and ``assess`` reserves and judges each one from recorded
observer answers.

What this is not, yet: the replay step does not judge pixel checks (``run`` refuses the pixel offer),
nothing here calls an observer, and no reproduction rate has been measured with it. The tests judge
recorded SAM answers (tests/data/sam-anchor/), which are one answer per frame per build: three "runs" of a recording are
the same answers three times, so they test the rule, not the observer's repeatability.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from expectrail import evaluator as reference
from expectrail.contracts import ContractError, validate_v1

FORMAT = "expectrail.pixel-check/v1"
KIND = "pixel-check"
REPEATS = 3
FIELDS = ("id", "statement", "object", "observer", "probe", "window", "predicate")
RESULTS = ("pass", "fail", "needs-review")
# The schema's patterns, matched whole: a JSON Schema "$" is the end of the string, and Python's
# re.search lets one trailing newline through (tests/test_schema_pattern.py).
NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
ROLE = re.compile(r"[a-z][a-z0-9-]{0,39}")

# role -> what the role is bound to in the bundled game, and what kind of thing is drawn. "anchor"
# says the engine's record logs a position for it that an anchored observer can be pointed at; the
# harness logs the player's body box per tick (agents/observations.py), and agents/sam_anchor.py
# points SAM at it. Node names are the game's own (game/platformer/*.tscn).
BUNDLED_BINDINGS = {
    "player": {"node": "Player", "kind": "sprite", "anchor": "engine-position"},
    "coin": {"node": "Coin", "kind": "sprite"},
    "bullet": {"node": "Bullet", "kind": "sprite"},
    "ground": {"node": "TileMapLayer", "kind": "ground"},
    "coins-counter": {"node": "CoinsCounter/Label", "kind": "text"},
}
KINDS = ("sprite", "text", "ground")


def bindings_for(profile: dict | None = None) -> dict:
    """The roles a pixel check may name. Until #259's ``expectrail.project/v1`` names a project's
    objects, every game the generator runs on is the bundled platformer, so this is BUNDLED_BINDINGS."""
    return BUNDLED_BINDINGS

# What each trusted observer can judge. "cannot" are kinds of thing it cannot tell apart on the
# screen; "anchored" observers see only roles the engine's record gives a position for, one per
# frame, so a predicate about two objects at once (reaches) is beyond them.
OBSERVERS = {
    "sam-3.1-anchor": {
        "available": True,
        "predicates": ("visible", "inside-region", "never-crosses"),
        "anchored": True,
        # docs/sam.md: SAM 3.1 does not find the ground; words found nothing useful in two outside
        # games (agents/sam_anchor.py); a box says nothing about which digits a label shows.
        "cannot": ("ground", "text"),
        "why": {
            "ground": "SAM 3.1 does not find the ground (docs/sam.md)",
            "text": "a box from SAM says nothing about what a label reads",
            "reaches": "it is asked about one object per frame, at the place the engine puts it, so it cannot judge two",
        },
    },
    "visual-sensor": {
        "available": False,
        "why": {"available": "the no-model visual sensor (#262) is not built yet"},
    },
}


class PixelError(ValueError):
    """A recording or a check cannot be used."""


# --- proposal time: the writer side ------------------------------------------------------------

def parse_candidate(entry, bindings: dict, probe_ids, observers: dict = OBSERVERS) -> tuple[dict | None, str | None]:
    """(check, None) for a model's candidate the closed language and its observer can hold, or (None, why).

    ``entry`` is untrusted: only the closed fields are read (anything else, an approval or a
    verdict, is dropped unread), the format, authority and origin are set here, the shape is checked
    against the schema, and then every name is checked against what the project binds and what the
    observer declares it can tell."""
    if not isinstance(entry, dict):
        return None, "not an object"
    doc = {"format": FORMAT, **{k: entry[k] for k in FIELDS if k in entry},
           "authority": "model_prior", "origin": "AUTO_DIFF"}
    try:
        validate_v1(doc, KIND)
    except ContractError as exc:
        return None, f"not in the closed language: {exc}"
    pred = doc["predicate"]
    roles = [doc["object"]]
    if pred["type"] == "inside-region":
        roles.append(pred["region"]["engine"])
    if pred["type"] == "reaches":
        roles.append(pred["goal"])
    if not (NAME.fullmatch(doc["id"]) and NAME.fullmatch(doc["probe"]) and all(ROLE.fullmatch(r) for r in roles)):
        return None, "not in the closed language: a name with a character outside its pattern"
    for role in roles:
        if role not in bindings:
            return None, f"{role!r} is not an object this project binds; a check names bound objects only"
    if doc["probe"] not in set(probe_ids):
        return None, f"probe {doc['probe']!r} is not on offer"
    window = doc.get("window")
    if window and "toFrame" in window and window["toFrame"] < window["fromFrame"]:
        return None, "the window ends before it starts"
    observer = observers.get(doc["observer"])
    if observer is None:
        return None, f"{doc['observer']!r} is not a trusted observer"
    if not observer.get("available"):
        return None, f"{doc['observer']} cannot judge anything yet: {observer['why']['available']}"
    if pred["type"] not in observer["predicates"]:
        return None, f"{doc['observer']} cannot judge {pred['type']}: {observer['why'].get(pred['type'], 'not declared')}"
    for role in roles:
        kind = bindings[role].get("kind")
        if kind in observer.get("cannot", ()):
            return None, f"{doc['observer']} cannot tell {role!r} ({kind}): {observer['why'][kind]}"
        if observer.get("anchored") and bindings[role].get("anchor") != "engine-position":
            return None, (f"{doc['observer']} is asked where the engine's record puts an object, and the record "
                          f"gives no position for {role!r}")
    if pred["type"] == "inside-region" and observer.get("anchored") and pred["region"]["engine"] != doc["object"]:
        return None, f"{doc['observer']} has the engine's box of {doc['object']!r} only, not of another object"
    return doc, None


# --- what the proposer is offered, and reading its answer ------------------------------------------

MAX_PIXEL_CHECKS = 4
ID_PREFIX = "jit-px-"


def judgeable(role: str, bindings: dict, name: str, observer: dict) -> str | None:
    """None when ``observer`` can be asked about ``role`` as a check's object, otherwise why not."""
    if not observer.get("available"):
        return observer["why"]["available"]
    kind = bindings[role].get("kind")
    if kind in observer.get("cannot", ()):
        return observer["why"][kind]
    if observer.get("anchored") and bindings[role].get("anchor") != "engine-position":
        return f"{name} is asked where the engine's record puts an object, and the record gives no position for it"
    return None


def menu(bindings: dict = BUNDLED_BINDINGS, observers: dict = OBSERVERS) -> dict:
    """What the prompt offers: for each trusted observer that exists, the predicates it can judge and the
    bound objects it can be asked about; and every bound object no observer can judge, with why.

    Made from the same tables ``parse_candidate`` refuses by, so the model is never offered a check that
    would be refused, and a refusal it meets anyway names the same reason."""
    out = {"observers": {}, "notJudgeable": {}}
    reasons: dict = {role: [] for role in sorted(bindings)}
    for name, observer in sorted(observers.items()):
        roles = []
        for role in sorted(bindings):
            why = judgeable(role, bindings, name, observer)
            if why is None:
                roles.append(role)
            else:
                reasons[role].append(f"{name}: {why}")
        if observer.get("available") and roles:
            out["observers"][name] = {"predicates": list(observer["predicates"]), "objects": roles}
            if observer.get("anchored"):
                out["observers"][name]["note"] = ("asked about one object a frame, at the place the engine puts it: "
                                                  "an inside-region region names that same object")
    judged = {r for o in out["observers"].values() for r in o["objects"]}
    out["notJudgeable"] = {role: "; ".join(why) for role, why in reasons.items() if role not in judged}
    return out


def parse_answer(entries, bindings: dict, probe_ids, observers: dict = OBSERVERS) -> tuple[list[dict], list[str]]:
    """(checks, diagnostics) from the model's ``pixelChecks``: at most MAX_PIXEL_CHECKS are read, each
    through ``parse_candidate``, renamed ``jit-px-<id>``; a refused one or a repeated id is dropped and said."""
    if entries is None:
        return [], []
    if not isinstance(entries, list):
        return [], ["pixelChecks: not a list, none read"]
    checks, notes, seen = [], [], set()
    for i, entry in enumerate(entries[:MAX_PIXEL_CHECKS]):
        check, why = parse_candidate(entry, bindings, probe_ids, observers)
        label = str(entry.get("id"))[:40] if isinstance(entry, dict) else f"#{i}"
        if check is None:
            notes.append(f"dropped pixel check {label!r}: {why}"[:200])
            continue
        check["id"] = (ID_PREFIX + check["id"].removeprefix(ID_PREFIX))[:80]
        if check["id"] in seen:
            notes.append(f"dropped pixel check {label!r}: its id is used twice")
            continue
        seen.add(check["id"])
        validate_v1(check, KIND)
        checks.append(check)
    if len(entries) > MAX_PIXEL_CHECKS:
        notes.append(f"pixelChecks: {len(entries) - MAX_PIXEL_CHECKS} beyond the first {MAX_PIXEL_CHECKS} not read")
    return checks, notes


# --- recorded observer answers -----------------------------------------------------------------

def load_recording(path) -> dict:
    """A recorded agents/sam_anchor.py answer file: {"setting": {...}, "runs": {name: run}}."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        runs = {str(r["run"]): r for r in doc["runs"]}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PixelError(f"{path}: not a readable anchor recording ({type(exc).__name__})") from exc
    return {"setting": setting_of(doc), "source": doc.get("source"), "runs": runs}


def setting_of(doc: dict) -> dict:
    """How the observer was asked. Two runs are compared only under the same setting: on the same
    clean game, SAM's lowest score was 0.5 asked with a point and 0.87 asked with a box."""
    setting = {"model": doc.get("model")}
    if doc.get("box") is not None:
        setting["box"] = list(doc["box"])
    setting["lift"] = doc.get("lift")
    return setting


def observations(check: dict, run: dict) -> tuple[dict, list[dict]]:
    """The run's answers for the check's object, in the reference evaluator's shape, and the gaps.

    An answer that does not hold the point it was asked about is about something else drawn there:
    the object was looked for and not found, which is an observation, not a gap."""
    role = check["object"]
    window = check.get("window") or {}
    lo, hi = window.get("fromFrame", 0), window.get("toFrame")
    need_engine_box = check["predicate"]["type"] == "inside-region"
    frames, gaps = [], []
    for f in sorted(run.get("frames") or [], key=lambda f: f["frame"]):
        n = f["frame"]
        if n < lo or (hi is not None and n > hi):
            continue
        if not f.get("asked"):
            gaps.append({"frame": n, "why": f"not asked: {f.get('note') or 'no engine position'}"})
            continue
        if f.get("error") or f.get("box") is None:
            gaps.append({"frame": n, "why": "the observer gave no answer"})
            continue
        objects: dict = {role: []}
        if f.get("holdsPoint"):
            objects[role].append({"box": list(f["box"]), "score": float(f.get("score") or 0.0)})
        if need_engine_box:
            if f.get("promptBox") is None:
                gaps.append({"frame": n, "why": "the engine's box was not recorded"})
                continue
            objects["engine-" + role] = [{"box": list(f["promptBox"]), "score": 1.0}]
        frames.append({"frame": n, "objects": objects})
    return {"format": "expectrail.observations/v0", "frames": frames}, gaps


def _spec(check: dict, bindings: dict) -> dict:
    """The check as the reference evaluator's spec. Never written out and never approved."""
    pred = check["predicate"]
    role = check["object"]
    score = pred.get("minScore", reference.DEFAULT_MIN_SCORE)
    objects = {role: {"prompt": f"what is drawn where the engine puts {bindings[role]['node']}", "minScore": score}}
    if pred["type"] == "visible":
        assertion = {"type": "visible", "object": role, "minFraction": pred.get("minFraction", 1.0)}
    elif pred["type"] == "inside-region":
        ref = "engine-" + pred["region"]["engine"]
        objects[ref] = {"prompt": "the engine's box", "minScore": 0.0}
        assertion = {"type": "inside-region", "object": role,
                     "region": {"relativeTo": ref, "marginPx": pred["region"].get("marginPx", 0)},
                     "tolerancePx": pred.get("tolerancePx", 0)}
    elif pred["type"] == "never-crosses":
        assertion = {"type": "never-crosses", "object": role, "boundary": dict(pred["boundary"])}
    else:
        raise PixelError(f"{pred['type']} has no anchored reading")
    spec = {"format": "expectrail.test-spec/v0", "id": check["id"], "instruction": check["statement"],
            "objects": objects, "assertion": assertion}
    if check.get("window"):
        spec["window"] = dict(check["window"])
    return spec


def judge(check: dict, run: dict, bindings: dict = BUNDLED_BINDINGS) -> dict:
    """One run of one check: pass, fail or needs-review, with the frames judged and the gaps."""
    route = (run.get("route") or {}).get("name")
    if route != check["probe"]:
        return {"result": "needs-review", "reason": f"the run replayed {route!r}, the check judges {check['probe']!r}",
                "framesJudged": 0, "gaps": []}
    obs, gaps = observations(check, run)
    if gaps:
        return {"result": "needs-review",
                "reason": f"{len(gaps)} frames without both the observer and the engine's record "
                          f"(first {gaps[0]['frame']}: {gaps[0]['why']})",
                "framesJudged": 0, "gaps": gaps}
    verdict = reference.evaluate(_spec(check, bindings), obs)
    return {"result": verdict["result"], "reason": verdict["reason"], "framesJudged": verdict["framesJudged"],
            "gaps": [], "firstFrame": verdict["firstFrame"]}


# --- the keep rule ------------------------------------------------------------------------------

def keep(check: dict, clean: list[tuple[dict, dict]], bug: list[tuple[dict, dict]],
         bindings: dict = BUNDLED_BINDINGS, repeats: int = REPEATS) -> dict:
    """Kept only when it passes on every clean run and fails on every bug run, ``repeats`` of each,
    all under one observer setting. ``clean`` and ``bug`` are lists of (setting, run).

    The reasons, in the order they are tried: too-few-runs, mixed-settings, needs-review (a run could
    not be decided: a gap, or the object looked for and not found where the predicate needs it),
    fails-on-clean, does-not-fail-on-bug."""
    rows = {"clean": [judge(check, r, bindings) for _, r in clean], "bug": [judge(check, r, bindings) for _, r in bug]}
    out = {"check": check["id"], "kept": False, "reason": None, "runs": rows}
    settings = {json.dumps(s, sort_keys=True) for s, _ in [*clean, *bug]}
    if len(clean) < repeats or len(bug) < repeats:
        out["reason"] = f"too-few-runs: {len(clean)} clean and {len(bug)} bug runs, {repeats} of each needed"
    elif len(settings) > 1:
        out["reason"] = "mixed-settings: the observer was not asked the same way on every run"
    elif any(r["result"] == "needs-review" for r in [*rows["clean"], *rows["bug"]]):
        first = next(r for r in [*rows["clean"], *rows["bug"]] if r["result"] == "needs-review")
        out["reason"] = f"needs-review: a run could not be decided ({first['reason']})"
    elif any(r["result"] != "pass" for r in rows["clean"]):
        out["reason"] = "fails-on-clean"
    elif any(r["result"] != "fail" for r in rows["bug"]):
        out["reason"] = "does-not-fail-on-bug"
    else:
        out["kept"], out["reason"] = True, f"passes {len(clean)} of {len(clean)} clean, fails {len(bug)} of {len(bug)} bug"
    return out


# --- the budget ---------------------------------------------------------------------------------

def frames_to_ask(check: dict, frames_probed) -> list[int]:
    window = check.get("window") or {}
    lo, hi = window.get("fromFrame", 0), window.get("toFrame")
    return [n for n in frames_probed if n >= lo and (hi is None or n <= hi)]


def cost(check: dict, frames_probed, usd_per_image: float, runs: int = 2 * REPEATS) -> float:
    """What judging the check costs at list price: one image a frame in its window, on every run."""
    if check["observer"] != "sam-3.1-anchor":
        return 0.0
    return len(frames_to_ask(check, frames_probed)) * runs * usd_per_image


def reserve(check: dict, frames_probed, spend) -> dict:
    """Reserve the check's observer calls against the change's cap (expectrail.jit.run.Spend), or say
    it was not run. Nothing is spent here; the caller adds what was actually sent."""
    from expectrail.jit.run import OutOfBudget

    usd = cost(check, frames_probed, spend.prices["samUsdPerImage"])
    try:
        spend.reserve(usd, f"pixel check {check['id']} ({check['observer']})")
    except OutOfBudget as exc:
        return {"check": check["id"], "status": "not-run", "reason": str(exc), "reservedUsd": 0.0}
    return {"check": check["id"], "status": "reserved", "reason": None, "reservedUsd": round(usd, 4)}


# --- judging a proposal's pixel checks -------------------------------------------------------------

def assess(checks: list[dict], clean: list[tuple[dict, dict]], bug: list[tuple[dict, dict]], spend,
           frames_probed, bindings: dict = BUNDLED_BINDINGS, repeats: int = REPEATS) -> list[dict]:
    """Each check: its observer calls reserved against the change's cap, together with the checks before it
    (as ``reserve`` does for one), then the keep rule
    over the observer's answers (``keep``). A check that cannot be afforded is ``not-run`` and is never
    judged. ``clean`` and ``bug`` are (setting, run) pairs of answers already recorded: nothing is asked
    here, so the reservation is what judging would cost if the answers had to be bought, and the caller
    adds to ``spend`` what was actually sent."""
    from expectrail.jit.run import OutOfBudget

    # Spend.reserve compares one amount with what is already spent; reservations do not add up by
    # themselves. So every check is reserved together with the ones before it, and four checks that
    # each fit under the cap alone cannot together pass it.
    rows, held = [], 0.0
    for check in checks:
        usd = cost(check, frames_probed, spend.prices["samUsdPerImage"])
        try:
            spend.reserve(held + usd, f"pixel check {check['id']} ({check['observer']}) with the {len(rows)} before it")
        except OutOfBudget as exc:
            rows.append({"check": check["id"], "status": "not-run", "kept": False, "reason": str(exc),
                         "reservedUsd": 0.0})
            continue
        held += usd
        row = keep(check, clean, bug, bindings, repeats)
        rows.append({"check": check["id"], "status": "kept" if row["kept"] else "dropped", "kept": row["kept"],
                     "reason": row["reason"], "reservedUsd": round(usd, 4), "runs": row["runs"]})
    return rows
