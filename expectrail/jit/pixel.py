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
  the object (agents/sam_anchor.py). ``visual-sensor`` is the no-model sensor of #262 over a frozen
  template bank (expectrail/jit/template_observer.py). A run is judged by one observer, so the proposer
  is offered only the one that will judge the run (``proposed``): SAM unless the propose step is told
  otherwise, and a proposal records which (expectrail/jit/intent.py, ``observer``).
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

In the replay (expectrail/jit/run.py, under the pixel setting): each pixel check's probe is replayed with
frames on the clean game, the bug build and, for a kept check, the candidate, ``reps`` times each; the
observer ``run.generate`` is given is asked about every one of those runs (``observe``, which reads its
answer as untrusted data); and the keep rule decides. The rows go into the run record's
``pixelChecks`` (``record_row``), and ``kept_rows`` reads them back, deciding from the runs, never from a
row's own status.

**Objects the game has many of** (``named``: the enemy and the bullet, bound with ``"anchor":
"engine-boxes"``). The observer is asked about each one on screen, at its own logged box, one image a box
and at most ``MAX_BOXES`` a frame (sam_observer.py); ``judge`` judges each by its id on its own frames and
the check holds only when it holds for every one (``_judge_named``). A frame with more of them on screen
than are asked about, or without the engine's boxes, is a gap; none on screen in the window is
``needs-review``, never a pass.

What this is not, yet: nothing here calls an observer. The SAM observer is expectrail/jit/sam_observer.py;
the command line's ``run`` builds it (``--observer``) and the reproduction score counts pixel checks on
their own (expectrail/repro/score.py), but the workflow does not, and no reproduction rate has been
measured with pixel checks. The tests judge
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
# says what the engine's record logs that an anchored observer can be pointed at:
# - "engine-position": one object, the player, whose body box the harness logs per tick
#   (agents/observations.py); agents/sam_anchor.py ``anchors`` points SAM at it.
# - "engine-boxes": every object of the role, each with its own collision box and id, logged per tick
#   since November 15, 2026 (``enemyBoxes``, ``projectileBoxes``; agents/sam_anchor.py ``object_boxes``).
#   An anchored observer is asked about each box on screen, one image a box (``MAX_BOXES`` a frame).
# Node names are the game's own (game/platformer/*.tscn).
ANCHORS = ("engine-position", "engine-boxes")
BUNDLED_BINDINGS = {
    "player": {"node": "Player", "kind": "sprite", "anchor": "engine-position"},
    "coin": {"node": "Coin", "kind": "sprite"},
    "bullet": {"node": "Bullet", "kind": "sprite", "anchor": "engine-boxes"},
    "enemy": {"node": "Enemy", "kind": "sprite", "anchor": "engine-boxes"},
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
        # The "engine-boxes" roles it can be pointed at (sam_observer.py, ``objects``).
        "boxes": ("bullet", "enemy"),
        # docs/sam.md: SAM 3.1 does not find the ground; words found nothing useful in two outside
        # games (agents/sam_anchor.py); a box says nothing about which digits a label shows.
        "cannot": ("ground", "text"),
        "why": {
            "ground": "SAM 3.1 does not find the ground (docs/sam.md)",
            "text": "a box from SAM says nothing about what a label reads",
            "reaches": "it is asked about one object per frame, at the place the engine puts it, so it cannot judge two",
        },
    },
    # The no-model template sensor of #262 (agents/template_observations.py), built into an observer in
    # expectrail/jit/template_observer.py: a frozen bank of the player's templates from a trusted clean
    # replay, searched for near the engine's body box. Nothing is sent anywhere and nothing is charged.
    "visual-sensor": {
        "available": True,
        "predicates": ("visible", "inside-region", "never-crosses"),
        "anchored": True,
        # Its bank holds the player's templates only: a second sprite needs its own templates and its own
        # prediction map (docs/template-sensor.md), which nothing supplies yet.
        "boxes": (),
        "cannot": ("ground", "text"),
        "why": {
            "ground": "the template sensor matches sprites against clean templates; it does not segment the ground",
            "text": "the template sensor reads no text (docs/template-sensor.md)",
            "reaches": "it looks for one object near the place the engine puts it, so it cannot judge two",
        },
    },
}

# The observers a proposal may be made for (``proposed``). A run is judged by the one observer it is given
# (expectrail/jit/run.py: a check naming another is not run), so the proposer is offered exactly one: the
# observer that will judge the run, which the propose step is told (expectrail/jit/intent.py, ``observer``)
# and the proposal records, and a replay of the proposal for another observer is refused. ``DEFAULT_OBSERVER``
# is SAM, the observer jit.yml's pixel jobs build; with it every prompt and proposal is as it was before
# the setting existed.
PROPOSABLE = ("sam-3.1-anchor", "visual-sensor")
DEFAULT_OBSERVER = "sam-3.1-anchor"


def check_observer(observer) -> str:
    """``observer`` if a proposal may be made for it, otherwise ValueError."""
    if observer not in PROPOSABLE:
        raise ValueError(f"unknown observer for pixel checks {str(observer)[:40]!r}: one of {', '.join(PROPOSABLE)}")
    return observer


def proposed(observer: str = DEFAULT_OBSERVER) -> dict:
    """The observers a proposal for a run judged by ``observer`` may name: that one only."""
    return {check_observer(observer): OBSERVERS[observer]}


def not_proposed(observers: dict) -> str:
    """Why an observer outside ``observers`` may not be named in a proposal."""
    return ("a run is judged by one observer, and the proposer is offered only the one that will judge this run: "
            + ", ".join(sorted(observers)))


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
        if doc["observer"] in OBSERVERS:
            return None, f"{doc['observer']} is not offered to the proposer: {not_proposed(observers)}"
        return None, f"{doc['observer']!r} is not a trusted observer"
    if not observer.get("available"):
        return None, f"{doc['observer']} cannot judge anything yet: {observer['why']['available']}"
    if pred["type"] not in observer["predicates"]:
        return None, f"{doc['observer']} cannot judge {pred['type']}: {observer['why'].get(pred['type'], 'not declared')}"
    for role in roles:
        kind = bindings[role].get("kind")
        if kind in observer.get("cannot", ()):
            return None, f"{doc['observer']} cannot tell {role!r} ({kind}): {observer['why'][kind]}"
        if observer.get("anchored"):
            why = _anchor_refusal(role, bindings, doc["observer"], observer)
            if why:
                return None, why
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
    if observer.get("anchored"):
        return _anchor_refusal(role, bindings, name, observer, short=True)
    return None


def _anchor_refusal(role: str, bindings: dict, name: str, observer: dict, short: bool = False) -> str | None:
    """None when an anchored observer can be pointed at ``role`` from the engine's record, otherwise why not."""
    anchor = bindings[role].get("anchor")
    it = "it" if short else repr(role)
    if anchor == "engine-position":
        return None
    if anchor == "engine-boxes":
        if role in observer.get("boxes", ()):
            return None
        return f"{name} is not pointed at the boxes the engine logs for {it}"
    return f"{name} is asked where the engine's record puts an object, and the record gives no position for {it}"


def named(role: str, bindings: dict = BUNDLED_BINDINGS) -> bool:
    """True for a role with many objects, each with its own logged box (``engine-boxes``)."""
    return (bindings.get(role) or {}).get("anchor") == "engine-boxes"


def menu(bindings: dict = BUNDLED_BINDINGS, observers: dict | None = None) -> dict:
    """What the prompt offers: for each trusted observer that exists, the predicates it can judge and the
    bound objects it can be asked about; and every bound object no observer can judge, with why.

    Made from the same tables ``parse_candidate`` refuses by, so the model is never offered a check that
    would be refused, and a refusal it meets anyway names the same reason."""
    if observers is None:
        observers = proposed()
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
                note = ("asked about each object at the place the engine puts it: an inside-region region names "
                        "that same object")
                many = [r for r in roles if named(r, bindings)]
                if many:
                    note += (f". For an object the game has many of ({', '.join(many)}), the check must hold for "
                             "every one on screen, each judged on its own")
                out["observers"][name]["note"] = note
    judged = {r for o in out["observers"].values() for r in o["objects"]}
    out["notJudgeable"] = {role: "; ".join(why) for role, why in reasons.items() if role not in judged}
    return out


def parse_answer(entries, bindings: dict, probe_ids, observers: dict | None = None) -> tuple[list[dict], list[str]]:
    """(checks, diagnostics) from the model's ``pixelChecks``: at most MAX_PIXEL_CHECKS are read, each
    through ``parse_candidate`` against the observers the proposer is offered (``proposed``, unless
    ``observers`` is given), renamed ``jit-px-<id>``; a refused one or a repeated id is dropped and said."""
    if observers is None:
        observers = proposed()
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
    if isinstance(doc.get("box"), str):
        # agents/sam_anchor.py --box body: the logged body box, widened by ``pad`` (expectrail/jit/sam_observer.py).
        setting["box"] = doc["box"]
        setting["pad"] = doc.get("pad")
    elif doc.get("box") is not None:
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
        absent = f.get("absent") is True and f.get("box") is None and not f.get("error")
        if (f.get("error") or f.get("box") is None) and not absent:
            gaps.append({"frame": n, "why": "the observer gave no answer"})
            continue
        objects: dict = {role: []}
        # ``absent``: the observer searched readable pixels around the engine's box and found nothing
        # (expectrail/jit/template_observer.py, ``not-found``): an observation, not a gap.
        if f.get("holdsPoint") and not absent:
            objects[role].append({"box": list(f["box"]), "score": float(f.get("score") or 0.0)})
        if need_engine_box:
            if f.get("promptBox") is None:
                gaps.append({"frame": n, "why": "the engine's box was not recorded"})
                continue
            objects["engine-" + role] = [{"box": list(f["promptBox"]), "score": 1.0}]
        frames.append({"frame": n, "objects": objects})
    return {"format": "expectrail.observations/v0", "frames": frames}, gaps


def named_observations(check: dict, run: dict) -> tuple[dict, list[dict]]:
    """For a role the game has many of (``named``): {id: observations} in the reference evaluator's shape,
    one per object the engine logged on screen in the window, and the gaps.

    Read from the run's ``objects[role]`` (sam_observer.py), one row a planned frame: a frame not asked
    about (no camera, more of them on screen than the observer asks about, a trace without boxes) is a gap
    for every object; so is a box the observer gave no answer for. An answer that does not hold the middle
    of the box it was asked about is about something else drawn there: that object was looked for and not
    found, an observation and not a gap. An object wholly off screen is not drawn and is not judged."""
    role = check["object"]
    window = check.get("window") or {}
    lo, hi = window.get("fromFrame", 0), window.get("toFrame")
    need_engine_box = check["predicate"]["type"] == "inside-region"
    rows = (run.get("objects") or {}).get(role)
    if not isinstance(rows, list):
        return {}, [{"frame": None, "why": f"the observer was not asked about {role} on this run"}]
    per: dict = {}
    gaps = []
    for f in sorted(rows, key=lambda f: f["frame"]):
        n = f["frame"]
        if n < lo or (hi is not None and n > hi):
            continue
        if not f.get("asked"):
            gaps.append({"frame": n, "why": f"not asked: {f.get('note') or 'no engine boxes'}"})
            continue
        for b in f.get("boxes") or []:
            ident = b.get("id")
            if b.get("error") or b.get("box") is None:
                gaps.append({"frame": n, "why": f"the observer gave no answer for {role} {ident}"})
                continue
            if need_engine_box and b.get("promptBox") is None:
                gaps.append({"frame": n, "why": f"the engine's box of {role} {ident} was not recorded"})
                continue
            objects: dict = {role: []}
            if b.get("holdsPoint"):
                objects[role].append({"box": list(b["box"]), "score": float(b.get("score") or 0.0)})
            if need_engine_box:
                objects["engine-" + role] = [{"box": list(b["promptBox"]), "score": 1.0}]
            per.setdefault(ident, []).append({"frame": n, "objects": objects})
    return ({ident: {"format": "expectrail.observations/v0", "frames": frames} for ident, frames in per.items()},
            gaps)


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
    if named(check["object"], bindings):
        return _judge_named(check, run, bindings)
    obs, gaps = observations(check, run)
    if gaps:
        return {"result": "needs-review",
                "reason": f"{len(gaps)} frames without both the observer and the engine's record "
                          f"(first {gaps[0]['frame']}: {gaps[0]['why']})",
                "framesJudged": 0, "gaps": gaps}
    verdict = reference.evaluate(_spec(check, bindings), obs)
    return {"result": verdict["result"], "reason": verdict["reason"], "framesJudged": verdict["framesJudged"],
            "gaps": [], "firstFrame": verdict["firstFrame"]}


def _judge_named(check: dict, run: dict, bindings: dict) -> dict:
    """``judge`` for a role the game has many of: every object on screen is judged on its own frames; the
    check fails when any one fails, passes when every one passes, and is needs-review on any gap or when
    none was on screen in the window (nothing seen is never a pass)."""
    role = check["object"]
    per, gaps = named_observations(check, run)
    if gaps:
        where = "" if gaps[0]["frame"] is None else f"first {gaps[0]['frame']}: "
        return {"result": "needs-review",
                "reason": f"{len(gaps)} frames or boxes without both the observer and the engine's record "
                          f"({where}{gaps[0]['why']})",
                "framesJudged": 0, "gaps": gaps}
    if not per:
        return {"result": "needs-review", "reason": f"no {role} was on screen in the window", "framesJudged": 0,
                "gaps": []}
    spec = _spec(check, bindings)
    verdicts = {ident: reference.evaluate(spec, obs) for ident, obs in per.items()}
    judged = sum(v["framesJudged"] for v in verdicts.values())
    failed = sorted(((v["firstFrame"] if v["firstFrame"] is not None else 10**9), str(ident))
                    for ident, v in verdicts.items() if v["result"] == "fail")
    if failed:
        first, ident = failed[0]
        v = next(v for i, v in verdicts.items() if str(i) == ident)
        first = v["firstFrame"]
        return {"result": "fail", "reason": f"{role} {ident}: {v['reason']} ({len(failed)} of {len(per)} failed)",
                "framesJudged": judged, "gaps": [], "firstFrame": first}
    unsure = sorted(str(i) for i, v in verdicts.items() if v["result"] != "pass")
    if unsure:
        v = verdicts[next(i for i in verdicts if str(i) == unsure[0])]
        return {"result": "needs-review", "reason": f"{role} {unsure[0]}: {v['reason']}", "framesJudged": judged,
                "gaps": []}
    return {"result": "pass", "reason": f"every {role} on screen passed ({len(per)}, {judged} frames)",
            "framesJudged": judged, "gaps": [], "firstFrame": None}


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


# At most this many objects of one role are asked about in a frame, one image each; a frame with more of
# them on screen is not asked about, and is a gap (sam_observer.py). It bounds what a frame can cost.
MAX_BOXES = 3


def asks_player(checks, bindings: dict = BUNDLED_BINDINGS) -> bool:
    """True when a check in ``checks`` is about an object the engine gives one position a frame (the
    player): only then is the observer asked about the player on that probe. A probe whose checks name
    only roles the game has many of (``named``) pays for their boxes and nothing else."""
    return any(not named(c["object"], bindings) for c in checks)


def images_per_frame(player: bool, objects=()) -> int:
    """The most images one planned frame can take: one for the player when it is asked about, and up to
    MAX_BOXES for each named role in ``objects``."""
    return (1 if player else 0) + MAX_BOXES * len(tuple(objects))


def images_a_frame(check: dict, bindings: dict = BUNDLED_BINDINGS) -> int:
    """The most images one frame of the check's object can take: one, or MAX_BOXES for a role with many."""
    return MAX_BOXES if named(check["object"], bindings) else 1


def cost(check: dict, frames_probed, usd_per_image: float, runs: int = 2 * REPEATS,
         bindings: dict = BUNDLED_BINDINGS) -> float:
    """What judging the check costs at list price, at most: one image a frame in its window (MAX_BOXES for a
    role with many), on every run."""
    if check["observer"] != "sam-3.1-anchor":
        return 0.0
    return len(frames_to_ask(check, frames_probed)) * images_a_frame(check, bindings) * runs * usd_per_image


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


# --- the observer the replay asks -----------------------------------------------------------------
#
# ``run.generate(..., observer=...)`` asks an observer about each pixel replay. An observer is a callable
#
#     observer(run_dir: Path, route: dict) -> {"setting": {...}, "run": {...}, "images": int}
#
# with ``observer.name`` (one of OBSERVERS) and ``observer.frames(route) -> [frame, ...]``, the frames it
# will ask about on a run of ``route`` (what the budget reserves for, before any replay). ``run`` is one
# run of an agents/sam_anchor.py answer file: {"route": {"name": ...}, "frames": [...]}; ``setting`` is how
# it asked (``setting_of``); ``images`` is how many images it actually sent, which the change is charged.

RESULT_ROWS = ("kept", "dropped", "not-run")
OUTCOMES = ("catch", "no-catch", "needs-review", "not-evaluated")


NOT_ASKED_PLAYER = "the player is not asked about: no check on this probe names it"


def observe(observer, run_dir, route: dict, objects=(), player: bool = True) -> tuple[dict, dict, int]:
    """(setting, run, images) from one observer call, checked as untrusted data: a malformed answer is a
    PixelError, never a pass. ``objects`` are the roles the game has many of (``named``) that the observer
    is also asked about; its run must then carry ``objects[role]`` for each, one row a frame. With
    ``player`` False (``asks_player``: no check on the probe names the player) the observer is not asked
    about the player, and an answer that says it asked about the player anyway is refused."""
    objects = tuple(objects)
    if not player and not objects:
        raise PixelError("the observer would be asked about nothing: neither the player nor a named object")
    kwargs = {}
    if objects:
        kwargs["objects"] = objects
    if not player:
        kwargs["player"] = False
    try:
        answer = observer(Path(run_dir), route, **kwargs)
    except PixelError:
        raise
    except Exception as exc:  # noqa: BLE001 - an observer that fails decides nothing
        raise PixelError(f"the observer failed: {type(exc).__name__}: {' '.join(str(exc).split())[:120]}") from exc
    if not isinstance(answer, dict) or set(answer) != {"setting", "run", "images"}:
        raise PixelError("the observer's answer is not {setting, run, images}")
    setting, run, images = answer["setting"], answer["run"], answer["images"]
    if not isinstance(setting, dict) or not isinstance(run, dict) or not isinstance(run.get("frames"), list) \
            or not isinstance(run.get("route"), dict):
        raise PixelError("the observer's answer has no setting, route or frames")
    if not isinstance(images, int) or isinstance(images, bool) or images < 0:
        raise PixelError("the observer's image count is not a whole number")
    for f in run["frames"]:
        if not isinstance(f, dict) or not isinstance(f.get("frame"), int) or isinstance(f.get("frame"), bool):
            raise PixelError("the observer's answer has a frame without a frame number")
    if not player and any(f.get("asked") for f in run["frames"]):
        raise PixelError("the observer was not asked about the player, and its answer says it asked")
    asked = run.get("objects", {})
    if not isinstance(asked, dict) or set(asked) != set(objects):
        raise PixelError(f"the observer was asked about {', '.join(objects) or 'no named object'}, and its "
                         f"answer is about {', '.join(sorted(map(str, asked))) if isinstance(asked, dict) else 'something else'}")
    for role, rows in asked.items():
        if not isinstance(rows, list):
            raise PixelError(f"the observer's answer about {role} is not a list of frames")
        for f in rows:
            if not isinstance(f, dict) or not isinstance(f.get("frame"), int) or isinstance(f.get("frame"), bool):
                raise PixelError(f"the observer's answer about {role} has a frame without a frame number")
            boxes = f.get("boxes", [])
            if not isinstance(boxes, list) or not all(isinstance(b, dict) for b in boxes) or len(boxes) > MAX_BOXES:
                raise PixelError(f"the observer's answer about {role} at frame {f['frame']} is not a list of "
                                 f"at most {MAX_BOXES} boxes")
    return setting, run, images


def record_row(check: dict, status: str, reason: str | None, reserved_usd: float = 0.0, setting: dict | None = None,
               clean=(), bug=(), candidate=(), outcome: str = "not-evaluated") -> dict:
    """One row of the run record's ``pixelChecks`` (contracts/jit-run.v1.schema.json)."""
    if status not in RESULT_ROWS or outcome not in OUTCOMES:
        raise PixelError(f"not a pixel row: {status}/{outcome}")
    return {"check": check, "status": status, "reason": None if reason is None else " ".join(str(reason).split())[:300],
            "reservedUsd": round(float(reserved_usd), 4), "setting": setting,
            "clean": [r["result"] for r in clean], "bug": [r["result"] for r in bug],
            "candidate": [r["result"] for r in candidate], "outcome": outcome}


def kept_rows(doc: dict) -> list[dict]:
    """The pixel rows of a run record that the keep rule keeps, decided from the rows' runs, not their
    status: the check must be a pixel check again (``validate_v1``), have one observer setting, and have
    passed ``reps`` of ``reps`` runs on the clean game and failed ``reps`` of ``reps`` on the bug build. A record that did not
    complete keeps none."""
    reps = doc["settings"]["reps"]
    if doc.get("status") != "complete":
        return []
    out = []
    for row in doc.get("pixelChecks") or []:
        validate_v1(row["check"], KIND)
        if row.get("setting") is not None and len(row["clean"]) == reps and len(row["bug"]) == reps \
                and all(r == "pass" for r in row["clean"]) \
                and all(r == "fail" for r in row["bug"]):
            out.append(row)
    return out
