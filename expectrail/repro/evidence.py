"""The evidence for one bug build: what it changes against the clean game along each probe, in the
engine's record and on the screen, side by side. No model is asked anything.

    python3 -m expectrail.repro evidence --defect coin-stays --out runs/repro-evidence      # replays with frames; no key
    python3 -m expectrail.repro evidence-render runs/repro-evidence/repro-evidence.json

Issue #285, step 5: a proposer should write a check about a difference it can see, not guess one
from the bug report. Today it is given each probe's signals on the two builds and nothing else, and
a signal is a reading of the engine's record: a bug that only shows on the screen gives it nothing,
and a bug the record shows late gives it the wrong moment. This record is what it could be given
instead. For every probe, from the same three replays (the clean game twice, the bug build once):

- **record**: the fields of the engine's record that differ, each with the first tick it differs on
  and on how many ticks, and the signals that read differently.
- **screen**: how many captured frames differ, the first one, and the size and place of the
  difference (``expectrail.repro.screen.compare_probe``, exact, any pixel counting).
- **observer**: what a visual observer answered about the frames that differ, on both builds, per
  named object: on how many frames it found the object in each, on how many in one build only, and
  how far its box moved. Read from recorded answers only (below).

A frame or a field that differs between the two clean replays is unstable on that probe and counts
for nothing. A probe that cannot be replayed or compared is a row that says why, never a guess.

**The observer is read, never asked.** This module looks answers up in a folder of recorded answers
(the vision adapter's answer cache, keyed by the frame's bytes, the prompt and the model) and has no
way to send a frame anywhere. A frame with no recorded answer is counted as not answered. With no
folder given, no observer is read and the record says so. Recording answers is a separate, paid step
that a person starts.

It reports numbers and draws no conclusion from the observer: there is no threshold here for "the
observer saw the bug". Whether a box that moved 4 px is the bug or the model's own wobble is for
whoever reads it, with the anchored rule's measurements (agents/anchor_rule.py) to go by.

**It is not offered to the generator.** ``for_proposer`` makes the bounded summary a prompt could
carry, and nothing under ``expectrail/jit/`` reads it: issue #285 asks for the baseline reproduction
rate before anything changes, and that run has not been made.
"""
from __future__ import annotations

import json
import shutil
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from expectrail.contracts import ContractError, strict_loads
from expectrail.repro import bench, screen

REPO = bench.REPO
SCHEMA = REPO / "contracts" / "repro-evidence.v1.schema.json"
FORMAT = "expectrail.repro-evidence/v1"
NAME = "repro-evidence.json"
SEES = screen.SEES
MAX_BYTES = 1024 * 1024
MAX_SHOWN = 6          # probes in the summary for a proposer
MAX_PROMPTS = 8
MAX_PROMPT_CHARS = 120
# The fields a row of expectrail.trace/v0 may have (contracts/trace.schema.json), less tick and frame.
# The summary for a proposer names these and no other: a field the game added under another name is
# counted, not named.
FIELDS = ("body", "coins", "enemies", "facing", "ground", "groundFrom", "objects", "onFloor", "player", "projectiles", "view")
_ABSENT = object()


class EvidenceError(ValueError):
    """The evidence cannot be made, or its record cannot be used."""


def _one_line(text, limit: int = 280) -> str:
    return " ".join(str(text).split())[:limit].strip()


# --- the engine's record ------------------------------------------------------------------------------------

def record_difference(clean: dict[str, list], bug: dict[str, list], skip: set[str] = frozenset()) -> list[dict]:
    """[{"name", "firstTick", "ticks", "of"}] for every field that differs between two replays of a probe:
    the first tick it differs on, on how many ticks, of how many. A field one replay has and the other
    lacks, or has for fewer ticks, differs on every tick only one of them has."""
    out = []
    for name in sorted((set(clean) | set(bug)) - set(skip)):
        a, b = clean.get(name) or [], bug.get(name) or []
        if a == b:
            continue
        of = max(len(a), len(b))
        ticks = [i for i in range(of)
                 if (a[i] if i < len(a) else _ABSENT) != (b[i] if i < len(b) else _ABSENT)]
        out.append({"name": name, "firstTick": ticks[0], "ticks": len(ticks), "of": of})
    return out


def signal_moves(clean: dict, bug: dict, skip: set[str] = frozenset()) -> dict[str, dict]:
    """{signal: {"clean", "bugBuild"}} for every signal that reads differently (None is "no reading")."""
    return {name: {"clean": clean.get(name), "bugBuild": bug.get(name)}
            for name in sorted((set(clean) | set(bug)) - set(skip)) if clean.get(name) != bug.get(name)}


def _signals(got: dict, work: Path, probe_id: str) -> dict:
    from expectrail.jit.measure import _clean
    from expectrail.trace.normalize import from_run_dir
    from expectrail.trace.signals import summary

    route = json.loads((work / "routes" / f"{probe_id}.json").read_text(encoding="utf-8"))
    return _clean(summary(from_run_dir(Path(got["dir"]), route, episode_id=f"evidence-{probe_id}")))


def _rates(run_dir: Path) -> tuple[int | None, int | None]:
    """(physics ticks a second, captured frames a second) as the replay states them, or None."""
    def whole(v):
        return v if isinstance(v, int) and not isinstance(v, bool) and 0 < v <= 1000 else None

    tps = fps = None
    try:
        tps = whole(json.loads((run_dir / "trace.json").read_text(encoding="utf-8")).get("physicsTicksPerSecond"))
    except (OSError, ValueError, AttributeError):
        pass
    try:
        fps = whole(json.loads((run_dir / "replay.json").read_text(encoding="utf-8"))["capture"]["fps"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return tps, fps


# --- a visual observer's recorded answers -------------------------------------------------------------------

class Recorded:
    """Recorded answers of a visual observer: the vision adapter's answer cache, read and never filled.

    ``root`` is the folder; ``prompts`` {object name: what the observer was asked to find}; ``model``
    and ``base`` name whose answers they are (default: the adapter's own). ``get`` returns the
    detections recorded for one frame and one object, or None when none is recorded."""

    def __init__(self, root: Path, prompts: dict[str, str], *, model: str | None = None, base: str | None = None):
        try:
            from agents import sam_observations as sam
        except ImportError as exc:
            raise EvidenceError("this copy of Expectrail does not carry the vision adapter, so recorded answers "
                                "cannot be read") from exc
        import re

        if not Path(root).is_dir():
            raise EvidenceError(f"no folder of recorded answers at {root}")
        if not prompts or len(prompts) > MAX_PROMPTS:
            raise EvidenceError(f"recorded answers need between 1 and {MAX_PROMPTS} objects to read them for")
        for name, text in prompts.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", str(name)) or not isinstance(text, str) \
                    or not text.strip() or len(text) > MAX_PROMPT_CHARS or text != _one_line(text, MAX_PROMPT_CHARS):
                raise EvidenceError(f"object {str(name)[:60]!r}: a name of letters, digits, - and _, and a prompt of "
                                    f"one line of at most {MAX_PROMPT_CHARS} characters")
        self.root = Path(root)
        self.prompts = dict(sorted(prompts.items()))
        self.model = _one_line(model or sam.MODEL, 80)
        if not self.model:
            raise EvidenceError("recorded answers are a model's: its name is one line that is not empty")
        self.base = str(sam.API_BASE if base is None else base)
        self._cache = None   # made on first use, so this can be handed to another process

    def get(self, frame_sha256: str, name: str) -> list[dict] | None:
        from agents.sam_observations import Cache

        if self._cache is None:
            self._cache = Cache(self.root)
        return self._cache.get(Cache.key(frame_sha256, self.prompts[name], self.model, self.base))

    def describe(self) -> dict:
        return {"source": "recorded-answers", "model": self.model, "prompts": dict(self.prompts)}


def _top(detections: list[dict]) -> dict | None:
    """The detection the observer was surest of, or None when it found nothing."""
    return max(detections, key=lambda d: d["score"]) if detections else None


def observer_reading(clean_frames: list[str], bug_frames: list[str], frames: list[int], recorded: Recorded) -> dict:
    """What the recorded observer answered on ``frames`` of the two replays, per object.

    {"frames": [...], "objects": {name: {"asked", "answered", "seenClean", "seenBugBuild", "inOneOnly",
    "firstInOneOnly", "largestMovePx"}}}. A frame is answered when both builds have a recorded
    answer for it. The object is seen where the answer has at least one detection. ``inOneOnly``
    counts answered frames where it is seen on one build and not the other; ``largestMovePx`` is the
    most any edge of the surest box moved between the builds, over the frames where both saw it
    (None when there is none)."""
    objects = {}
    for name in recorded.prompts:
        answered = seen_clean = seen_bug = one_only = 0
        first, largest = None, None
        for i in frames:
            a, b = recorded.get(clean_frames[i], name), recorded.get(bug_frames[i], name)
            if a is None or b is None:
                continue
            answered += 1
            top_a, top_b = _top(a), _top(b)
            seen_clean += top_a is not None
            seen_bug += top_b is not None
            if (top_a is None) != (top_b is None):
                one_only += 1
                first = i if first is None else first
            elif top_a is not None:
                move = max(abs(x - y) for x, y in zip(top_a["box"], top_b["box"]))
                largest = move if largest is None else max(largest, move)
        objects[name] = {"asked": len(frames), "answered": answered, "seenClean": seen_clean,
                         "seenBugBuild": seen_bug, "inOneOnly": one_only, "firstInOneOnly": first,
                         "largestMovePx": None if largest is None else round(float(largest), 2)}
    return {"frames": list(frames), "objects": objects}


# --- one probe ----------------------------------------------------------------------------------------------

def _one_probe(args) -> tuple[dict, dict]:
    """One probe on the three replays. (its row, {"renderer", "frame", "tps", "fps", "retries"})."""
    profile, probe, patches, work, runner, recorded, keep = args
    runner = runner or screen._default_runner()
    pid, work = probe["id"], Path(work)
    meta = {"renderer": None, "frame": None, "tps": None, "fps": None, "retries": 0}
    try:
        builds = {}
        for name, with_patches in (("clean-a", []), ("clean-b", []), ("bug", patches)):
            builds[name], n = screen.capture_probe(profile, probe, with_patches, work / name, runner)
            meta["retries"] += n
        a, b, d = builds["clean-a"], builds["clean-b"], builds["bug"]
        meta["renderer"] = a["renderer"]
        meta["tps"], meta["fps"] = _rates(Path(a["dir"]))
        noisy_frames, noisy_fields = screen.unstable({pid: a}, {pid: b}).get(pid, (set(), set()))
        signals = {name: _signals(builds[name], work / name, pid) for name in builds}
        noisy_signals = set(signal_moves(signals["clean-a"], signals["clean-b"]))
        got = screen.compare_probe(a, d, noisy_frames, noisy_fields)
        fields = record_difference(a["fields"], d["fields"], noisy_fields)
        moved = signal_moves(signals["clean-a"], signals["bug"], noisy_signals)
        if [f["name"] for f in fields] != got["fields"]:
            raise EvidenceError("two readings of the same record disagree about which fields differ")
        if moved and not fields:
            raise EvidenceError("a signal reads differently and no field of the record differs")
        shown = got["screen"]
        if shown:
            meta["frame"] = {"width": shown["width"], "height": shown["height"]}
        else:
            first = sorted((Path(a["dir"]) / "frames").glob("f*.png"))[0]
            size = screen.frame_difference(first, first)
            meta["frame"] = {"width": size["width"], "height": size["height"]}
        observer = None
        if recorded is not None and shown:
            differing = [i for i, (x, y) in enumerate(zip(a["frames"], d["frames"])) if x != y and i not in noisy_frames]
            observer = observer_reading(a["frames"], d["frames"], screen._sample(differing), recorded)
        row = {"probe": pid, "sees": screen._sees(got["fields"], shown),
               "record": {"fields": fields, "signals": moved} if fields else None,
               "screen": {k: v for k, v in shown.items() if k not in ("width", "height")} if shown else None,
               "observer": observer,
               "unstable": {"frames": len(noisy_frames), "fields": sorted(noisy_fields), "signals": sorted(noisy_signals)}}
        return row, meta
    except Exception as exc:  # noqa: BLE001 - a probe that cannot be replayed or compared is a row that says so
        return ({"probe": pid, "sees": "error", "record": None, "screen": None, "observer": None,
                 "unstable": {"frames": 0, "fields": [], "signals": []},
                 "error": _one_line(f"{type(exc).__name__}: {exc}")}, meta)
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)


# --- the evidence -------------------------------------------------------------------------------------------

def totals(rows: list[dict]) -> dict:
    return {"probes": len(rows), **{k: sum(r["sees"] == k for r in rows) for k in SEES}}


def evidence(profile: dict, probes: list[dict], base_patches: list[Path], out: Path, *, runner=None, jobs: int = 1,
             recorded: Recorded | None = None, keep_frames: bool = False) -> dict:
    """Replay every probe on the clean game twice and on the bug build once, with frames, and write
    ``out/repro-evidence.json``. ``base_patches`` make the bug build; there is no candidate here."""
    from harness.run import GODOT_VERSION

    from expectrail.jit.measure import base_digests

    if not base_patches:
        raise EvidenceError("no bug build: evidence is the bug build against the clean game")
    if not probes or len({p["id"] for p in probes}) != len(probes):
        raise EvidenceError("the probes must be at least one and each named once")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    patches = [str(p) for p in base_patches]
    tasks = [(profile, p, patches, str(out / "work" / p["id"]), runner, recorded, keep_frames) for p in probes]
    try:
        if jobs > 1:
            with ProcessPoolExecutor(max_workers=jobs) as pool:
                done = list(pool.map(_one_probe, tasks))
        else:
            done = [_one_probe(t) for t in tasks]
    finally:
        if not keep_frames:
            shutil.rmtree(out / "work", ignore_errors=True)
    rows = [row for row, _meta in done]
    good = [meta for row, meta in done if row["sees"] != "error"]

    def one(key):
        values = {json.dumps(m[key], sort_keys=True) for m in good if m[key] is not None}
        return json.loads(values.pop()) if len(values) == 1 else None

    renderer = one("renderer")
    record = {"format": FORMAT, "engine": f"Godot {GODOT_VERSION}",
              "renderer": renderer[:120] if isinstance(renderer, str) else None, "frame": one("frame"),
              "ticksPerSecond": one("tps"), "framesPerSecond": one("fps"),
              "basePatchSha256": base_digests([Path(p) for p in base_patches]),
              "probes": [p["id"] for p in probes], "replaysPerBuild": {"clean": 2, "bugBuild": 1},
              "maxFramesExamined": screen.MAX_EXAMINED, "engineRetries": sum(m["retries"] for _row, m in done),
              "observer": recorded.describe() if recorded is not None else None,
              "rows": rows, "totals": totals(rows)}
    found = problems(record)
    if found:
        raise EvidenceError("; ".join(found))
    (out / NAME).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return record


def _finite(value) -> bool:
    """No NaN and no infinity anywhere: a schema's "number" lets both through on a record built in memory."""
    import math

    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite(v) for v in value.values())
    if isinstance(value, list):
        return all(_finite(v) for v in value)
    return True


# --- the record ---------------------------------------------------------------------------------------------

def problems(record) -> list[str]:
    """What is wrong with an evidence record: the schema first, then what must agree inside it."""
    import jsonschema

    from expectrail.trace.signals import SIGNALS

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(record), key=lambda e: list(e.path))
    if errors:
        return [f"repro-evidence: {'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}"[:300]
                for e in errors[:10]]
    out = []
    if not _finite(record):
        return ["repro-evidence: a number that is not finite"]
    if [r["probe"] for r in record["rows"]] != record["probes"]:
        out.append("repro-evidence: the rows are not one for each probe, in the probes' order")
    names = sorted(record["observer"]["prompts"]) if record["observer"] else None
    frame = record["frame"]
    for r in record["rows"]:
        pid, rec, s, obs = r["probe"], r["record"], r["screen"], r["observer"]
        if r["sees"] == "error":
            if rec is not None or s is not None or obs is not None or not r.get("error"):
                out.append(f"repro-evidence: {pid}: an error row carries a reason and nothing else")
            continue
        if "error" in r or r["sees"] != screen._sees(rec["fields"] if rec else [], s):
            out.append(f"repro-evidence: {pid}: {r['sees']!r} does not follow from its row")
        if rec is not None:
            listed = [f["name"] for f in rec["fields"]]
            if listed != sorted(set(listed)) or any(f["firstTick"] >= f["of"] or f["ticks"] > f["of"] - f["firstTick"]
                                                    for f in rec["fields"]):
                out.append(f"repro-evidence: {pid}: the record's fields do not agree with themselves")
            for name, move in rec["signals"].items():
                if name not in SIGNALS or move["clean"] == move["bugBuild"]:
                    out.append(f"repro-evidence: {pid}: signal {name} is not a trace signal that moved")
            if set(listed) & set(r["unstable"]["fields"]) or set(rec["signals"]) & set(r["unstable"]["signals"]):
                out.append(f"repro-evidence: {pid}: something unstable on the clean game is counted")
        if s is not None:
            left, top, right, bottom = s["box"]
            if frame is None or s["frames"] > s["of"] or s["firstFrame"] >= s["of"] or s["atFrame"] >= s["of"] \
                    or s["atFrame"] < s["firstFrame"] or s["frames"] > s["of"] - s["firstFrame"] \
                    or s["examined"] > min(s["frames"], record["maxFramesExamined"]) \
                    or not (left < right <= frame["width"] and top < bottom <= frame["height"]) \
                    or s["pixels"] > (right - left) * (bottom - top):
                out.append(f"repro-evidence: {pid}: the screen difference does not agree with itself")
        if obs is None:
            continue
        if names is None or s is None:
            out.append(f"repro-evidence: {pid}: an observer's reading with no observer, or where no frame differs")
            continue
        asked = obs["frames"]
        if asked != sorted(set(asked)) or len(asked) > min(s["frames"], record["maxFramesExamined"]) \
                or asked[0] != s["firstFrame"] or asked[-1] >= s["of"] or sorted(obs["objects"]) != names:
            out.append(f"repro-evidence: {pid}: the observer's frames or objects do not agree with the record")
            continue
        for name, o in obs["objects"].items():
            # Of the answered frames: seen on both builds, on the clean game only, on the bug build only, on neither.
            twice = o["seenClean"] + o["seenBugBuild"] - o["inOneOnly"]     # two for every frame seen on both
            if o["asked"] != len(asked) or o["answered"] > o["asked"] \
                    or o["inOneOnly"] < abs(o["seenClean"] - o["seenBugBuild"]) or twice < 0 or twice % 2 \
                    or twice // 2 + o["inOneOnly"] > o["answered"] \
                    or (o["firstInOneOnly"] is None) != (o["inOneOnly"] == 0) \
                    or (o["firstInOneOnly"] is not None and o["firstInOneOnly"] not in asked) \
                    or (o["largestMovePx"] is None) != (twice == 0):
                out.append(f"repro-evidence: {pid}: the observer's counts for {name} do not agree with themselves")
    if record["totals"] != totals(record["rows"]):
        out.append("repro-evidence: the totals do not match the rows")
    return out


def load(path: Path, *, base_patches: list[Path] | None = None) -> dict:
    """The record, re-checked as untrusted data. With ``base_patches``, it must be about that bug build."""
    from expectrail.jit.measure import base_digests

    raw = Path(path).read_bytes()
    if len(raw) > MAX_BYTES:
        raise EvidenceError(f"repro-evidence: over {MAX_BYTES} bytes")
    try:
        record = strict_loads(raw.decode("utf-8"))
    except (ValueError, ContractError) as exc:
        raise EvidenceError(_one_line(f"repro-evidence: unreadable: {exc}", 300)) from exc
    found = problems(record)
    if found:
        raise EvidenceError("; ".join(found))
    if base_patches is not None and record["basePatchSha256"] != base_digests([Path(p) for p in base_patches]):
        raise EvidenceError("repro-evidence: made for a different bug build")
    return record


# --- what a proposer could be given -------------------------------------------------------------------------

def for_proposer(record: dict, *, probes, objects=(), limit: int = MAX_SHOWN) -> dict:
    """The bounded summary a prompt could carry: at most ``limit`` probes on which the bug build differs.

    Numbers, and names the caller already has. ``probes`` is the caller's own list of probe ids (its
    library and reach probes) and ``objects`` its own object names: the record is untrusted data and
    is not believed about either. A row whose probe is not in ``probes`` is counted under
    ``probesNotKnown`` and not shown; an observed object not in ``objects`` is counted under
    ``otherObjects`` and not named; a record field that is not one of the trace's own row fields is
    counted under ``otherFields``. Signals are the trace's signals or the record is refused. So
    every string in the summary is a key of this function's own, one of ``probes``, one of
    ``objects``, a trace field or a trace signal. No free text: no error reason, no prompt, no
    model, no renderer.

    Probes where the record and the screen both differ come first, then those with more signals
    moved, then those with the larger share of frames differing. Nothing reads this yet."""
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 25:
        raise EvidenceError("the summary shows between 1 and 25 probes")
    if isinstance(probes, (str, bytes)) or isinstance(objects, (str, bytes)):
        raise EvidenceError("the probes and the objects are lists of names, not one name")
    probes, objects = set(probes), set(objects)
    if not all(isinstance(x, str) for x in probes | objects):
        raise EvidenceError("the probes and the objects are lists of names")
    found = problems(record)     # a prompt is built from a record that holds together, or from nothing
    if found:
        raise EvidenceError("; ".join(found))
    differing = [r for r in record["rows"] if r["sees"] not in ("neither", "error")]
    known_rows = [r for r in differing if r["probe"] in probes]

    def order(r):
        s = r["screen"]
        return (r["sees"] != "record-and-screen", -len(r["record"]["signals"]) if r["record"] else 0,
                -(s["frames"] / s["of"]) if s else 0.0, r["probe"])

    shown = []
    for r in sorted(known_rows, key=order)[:limit]:
        entry = {"probe": r["probe"], "record": None, "screen": None, "observer": None}
        if r["record"]:
            known = {f["name"]: {k: f[k] for k in ("firstTick", "ticks", "of")}
                     for f in r["record"]["fields"] if f["name"] in FIELDS}
            other = sum(f["name"] not in FIELDS for f in r["record"]["fields"])
            entry["record"] = {"fields": known, **({"otherFields": other} if other else {}),
                               "signals": {k: dict(v) for k, v in r["record"]["signals"].items()}}
        if r["screen"]:
            entry["screen"] = {k: r["screen"][k] for k in ("frames", "of", "firstFrame", "pixels", "atFrame", "box")}
        if r["observer"]:
            seen = r["observer"]["objects"]
            other = sum(k not in objects for k in seen)
            entry["observer"] = {"frames": list(r["observer"]["frames"]),
                                 "objects": {k: dict(v) for k, v in seen.items() if k in objects},
                                 **({"otherObjects": other} if other else {})}
        shown.append(entry)
    return {"ticksPerSecond": record["ticksPerSecond"], "framesPerSecond": record["framesPerSecond"],
            "frame": dict(record["frame"]) if record["frame"] else None,
            "probesThatDiffer": len(known_rows), "probesNotKnown": len(differing) - len(known_rows),
            "probesNotCompared": record["totals"]["error"],
            "observerRead": record["observer"] is not None, "probes": shown}


# --- the page -----------------------------------------------------------------------------------------------

def _show(v) -> str:
    return "no reading" if v is None else f"{v:g}"


def render(record: dict) -> str:
    """The record as a table, one row a probe on which anything differs, and a line for the rest."""
    t = record["totals"]
    f = record["frame"]
    lines = [f"{t['probes']} probes, {record['engine']}"
             + (f", frames of {f['width']} x {f['height']}" if f else "")
             + (f", {record['ticksPerSecond']} ticks and {record['framesPerSecond']} frames a second"
                if record["ticksPerSecond"] and record["framesPerSecond"] else "")
             + f", no model asked. The record and the screen both differ: {t['record-and-screen']}. Only the "
             f"screen differs: {t['screen-only']}. Only the record differs: {t['record-only']}. Nothing differs: "
             f"{t['neither']}." + (f" Could not be compared: {t['error']}." if t["error"] else "")
             + (f" Replays made again after the engine failed: {record['engineRetries']}." if record["engineRetries"] else ""),
             ""]
    if record["observer"]:
        o = record["observer"]
        lines += ["A visual observer's recorded answers were read (`" + o["model"].replace("`", "'") + "`; "
                  + ", ".join(f"`{k}`" for k in o["prompts"]) + "). None was asked anything.", ""]
    else:
        lines += ["No visual observer was read: no recorded answers were given.", ""]
    lines += ["| Probe | Sees | Record fields that differ: first tick, ticks | Signals that moved, clean to bug build "
              "| Frames that differ | Most pixels in one frame | Where (left, top, right, bottom) | Observer |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in record["rows"]:
        if r["sees"] in ("neither", "error"):
            continue
        rec, s, obs = r["record"], r["screen"], r["observer"]
        fields = ", ".join(f"`{x['name']}` from {x['firstTick']}, {x['ticks']} of {x['of']}" for x in rec["fields"]) \
            if rec else "none"
        signals = ", ".join(f"`{k}` {_show(v['clean'])} to {_show(v['bugBuild'])}" for k, v in rec["signals"].items()) \
            if rec and rec["signals"] else "none"
        cells = [f"{s['frames']} of {s['of']}, from frame {s['firstFrame']}", f"{s['pixels']} (frame {s['atFrame']})",
                 ", ".join(str(v) for v in s["box"])] if s else ["none", "", ""]
        seen = "not read"
        if obs:
            seen = "; ".join(
                f"`{k}`: answered {o['answered']} of {o['asked']}, seen {o['seenClean']} clean and {o['seenBugBuild']} "
                f"bug build, in one only {o['inOneOnly']}"
                + (f" (first at frame {o['firstInOneOnly']})" if o["firstInOneOnly"] is not None else "")
                + (f", box moved up to {o['largestMovePx']:g} px" if o["largestMovePx"] is not None else "")
                for k, o in obs["objects"].items())
        lines.append(f"| `{r['probe']}` | {r['sees']} | {fields} | {signals} | " + " | ".join(cells) + f" | {seen} |")
    same = [r["probe"] for r in record["rows"] if r["sees"] == "neither"]
    if same:
        lines += ["", "Nothing differs on: " + ", ".join(f"`{p}`" for p in same) + "."]
    for r in record["rows"]:
        if r["sees"] == "error":
            lines += ["", f"`{r['probe']}` could not be compared: `{r['error'].replace('`', chr(39))}`"]
    noisy = [r for r in record["rows"] if r["unstable"]["frames"] or r["unstable"]["fields"] or r["unstable"]["signals"]]
    if noisy:
        lines += ["", "Unstable between two replays of the clean game, and so not counted: "
                  + "; ".join(f"`{r['probe']}` ({r['unstable']['frames']} frames"
                              + "".join(f", {x}" for x in r["unstable"]["fields"] + r["unstable"]["signals"]) + ")"
                              for r in noisy) + "."]
    return "\n".join(lines) + "\n"
