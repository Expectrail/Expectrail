"""Can a pixel check, as it is offered today, fail on the bench's screen-only defects? No model.

    python3 -m expectrail.repro pixel-reach --out runs/repro-pixel-reach --jobs 2   # replays with frames; no model, no key
    python3 -m expectrail.repro pixel-reach-render bench/jit/public/pixel-reach.json

A pixel check (expectrail/jit/pixel.py, issue #286) is judged from what a trusted observer says it sees
inside one box a frame: for ``sam-3.1-anchor``, the logged body box of a bound object the engine gives
a position for, widened by a few game pixels (expectrail/jit/sam_observer.py), on the frames the
observer plans from the route (every 10th and the last, at most 30). Whatever the observer would
say, it is shown only the pixels inside that box on those frames. So before any money is spent on
asking it, one thing can be measured with no model at all: on the defect build, does any pixel inside
that box differ from the clean game's, on any frame the observer would be asked about?

- **inside-a-box**: on some probe, some planned frame differs inside the box of an object the menu
  offers. An observer *could* answer differently there. It is necessary, not enough: whether it does
  is what a live run measures.
- **outside-every-box**: frames differ on some probe, and on every planned frame the difference is
  outside every offered box. No pixel check offered today can fail on this defect along these probes,
  whatever the observer says, because the observer is never shown the pixels that change.
- **no-difference**: no planned frame differs at all on any probe (the difference, if any, falls
  between the frames the observer is asked about).
- **error**: the build could not be measured; the row says why.

The boxes come from the same code the observer uses (agents/sam_anchor.py ``anchors``, with the body
box and the observer's padding), on each build's own position log, and the pixels are counted in both
boxes when the two builds put the object in different places. Frames are compared exactly, which is
sound only because the capture is repeatable here: the screen record (bench/jit/public/screen.json)
replayed the clean game twice on every library probe with the same renderer and found no frame that
differed. This measurement replays the clean game once and says so in its record.

What this is not: no observer is asked anything, and nothing here is a reproduction rate. It says
which defects the pixel menu can reach at all, so a live pixel run is not dispatched to find a number
this measurement already decides.
"""
from __future__ import annotations

import json
import shutil
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from expectrail.contracts import ContractError, strict_loads
from expectrail.repro import bench, screen

REPO = bench.REPO
SCHEMA = REPO / "contracts" / "repro-pixel-reach.v1.schema.json"
RECORD = REPO / "bench" / "jit" / "public" / "pixel-reach.json"
FORMAT = "expectrail.repro-pixel-reach/v1"
NAME = "repro-pixel-reach.json"
REACH = ("inside-a-box", "outside-every-box", "no-difference", "error")
OBSERVER = "sam-3.1-anchor"
MAX_BYTES = 1024 * 1024


class PixelReachError(ValueError):
    """The measurement cannot be made, or its record cannot be used."""


def offered(menu: dict | None = None) -> list[str]:
    """The bound objects ``sam-3.1-anchor`` can be asked about, as the proposer's menu offers them.

    Only an object the engine logs a body box for can be measured here (agents/sam_anchor.py points at
    the player's); any other offered object stops the measurement rather than being skipped."""
    from expectrail.jit import pixel

    menu = pixel.menu() if menu is None else menu
    roles = list((menu.get("observers") or {}).get(OBSERVER, {}).get("objects") or [])
    unmeasurable = [r for r in roles if r != "player"]
    if unmeasurable:
        raise PixelReachError(f"the menu offers {unmeasurable[0]!r} to {OBSERVER}, and only the player's box is logged; "
                              "this measurement would miss it")
    return roles


def _observer():
    from expectrail.jit.sam_observer import SamAnchorObserver

    return SamAnchorObserver(client=False)   # never asked: only its frame plan and box are used


def setting() -> dict:
    from agents.sam_anchor import BODY, DEFAULT_PAD
    from expectrail.jit import sam_observer

    return {"name": OBSERVER, "box": BODY, "pad": DEFAULT_PAD, "every": sam_observer.DEFAULT_EVERY,
            "maxFrames": sam_observer.MAX_FRAMES}


# --- one frame, one probe -----------------------------------------------------------------------------

def _marks(path_a: Path, path_b: Path) -> tuple[int, int, bytes | None]:
    """(width, height, one byte a pixel, zero where the two frames agree in red, green and blue), with
    None for the bytes when no pixel differs."""
    from harness.unity import png_pixels

    try:
        wa, ha, ca, pa = png_pixels._decode(Path(path_a))
        wb, hb, cb, pb = png_pixels._decode(Path(path_b))
    except Exception as exc:  # whatever the decoder raises, the frame cannot be read
        raise PixelReachError(f"a frame cannot be read: {type(exc).__name__}: {' '.join(str(exc).split())}"[:200]) from exc
    if (wa, ha) != (wb, hb):
        raise PixelReachError("two frames of one probe have different sizes")
    mask = 0
    for a, b in zip(screen._planes(wa, ha, ca, pa), screen._planes(wb, hb, cb, pb)):
        mask |= a ^ b
    return wa, ha, (mask.to_bytes(wa * ha, "big") if mask else None)


def _inside(marks: bytes, width: int, box: list[int]) -> int:
    x0, y0, x1, y1 = box
    return sum((x1 - x0) - marks[y * width + x0:y * width + x1].count(0) for y in range(y0, y1))


def _union(a: list[int], b: list[int]) -> list[list[int]]:
    return [a] if a == b else [a, b]


def probe_reach(clean_dir: Path, defect_dir: Path, route: dict, observer=None) -> dict:
    """One probe of one defect: on the frames the observer plans for ``route``, how many differ at all,
    how many differ inside the offered object's box, the most pixels inside it, and how many planned
    frames have no box on one build or the other (the observer would not be asked there: a gap)."""
    from agents.sam_anchor import BODY, DEFAULT_PAD, anchors, load_trace
    from agents.sam_observations import frame_files

    observer = observer or _observer()
    planned = observer.frames(route)
    files_c, files_d = frame_files(Path(clean_dir) / "frames"), frame_files(Path(defect_dir) / "frames")
    if len(files_c) != len(files_d):
        raise PixelReachError(f"the defect build's capture has {len(files_d)} frames and the clean game's has "
                              f"{len(files_c)}: the two cannot be compared frame by frame")
    planned = [n for n in planned if n in files_c]
    if not planned:
        return {"framesAsked": 0, "framesDiffer": 0, "framesDifferInBox": 0, "maxPixelsInBox": 0, "gaps": 0,
                "boxesMoved": 0}
    width, height, _ = _marks(files_c[planned[0]], files_c[planned[0]])
    trace_c, trace_d = load_trace(Path(clean_dir)), load_trace(Path(defect_dir))
    at_c = anchors(trace_c, (width, height), planned, box=BODY, pad=DEFAULT_PAD)
    at_d = anchors(trace_d, (width, height), planned, box=BODY, pad=DEFAULT_PAD)
    differ = in_box = most = gaps = moved = 0
    for n in planned:
        box_c, box_d = at_c[n].get("promptBox"), at_d[n].get("promptBox")
        if "why" in at_c[n] or "why" in at_d[n] or not box_c or not box_d:
            gaps += 1
        w, _h, marks = _marks(files_c[n], files_d[n])
        if marks is None:
            continue
        differ += 1
        if box_c and box_d and "why" not in at_c[n] and "why" not in at_d[n]:
            moved += box_c != box_d
            count = max(_inside(marks, w, b) for b in _union(box_c, box_d))
            if count:
                in_box += 1
                most = max(most, count)
    return {"framesAsked": len(planned), "framesDiffer": differ, "framesDifferInBox": in_box,
            "maxPixelsInBox": most, "gaps": gaps, "boxesMoved": moved}


def reach_of(rows: list[dict]) -> str:
    if any(r["framesDifferInBox"] for r in rows):
        return "inside-a-box"
    if any(r["framesDiffer"] for r in rows):
        return "outside-every-box"
    return "no-difference"


# --- the measurement ----------------------------------------------------------------------------------

def _route(work: Path, probe_id: str) -> dict:
    return json.loads((Path(work) / "routes" / f"{probe_id}.json").read_text(encoding="utf-8"))


def _probe_task(args) -> tuple[str, dict, str | None, int]:
    """One probe: the clean game once, then each defect build, compared while both are on disk.
    (probe id, {defect id: row or {"error": why}}, an error that stops the probe, replays made again)."""
    profile, probe, defects, work, runner = args
    runner = runner or screen._default_runner()
    work = Path(work)
    out, retries = {}, 0
    try:
        clean, n = screen.capture_probe(profile, probe, [], work / "clean", runner)
        retries += n
    except Exception as exc:  # noqa: BLE001 - no clean game on this probe: reported, never guessed
        return probe["id"], {}, f"{type(exc).__name__}: {' '.join(str(exc).split())}"[:300], retries
    route = _route(work / "clean", probe["id"])
    try:
        for did, patch in defects:
            try:
                got, n = screen.capture_probe(profile, probe, [patch], work / did, runner)
                retries += n
                try:
                    out[did] = {"probe": probe["id"], **probe_reach(Path(clean["dir"]), Path(got["dir"]), route)}
                finally:
                    shutil.rmtree(got["dir"], ignore_errors=True)
            except Exception as exc:  # noqa: BLE001 - one defect build that cannot be measured is its own row
                out[did] = {"error": f"probe {probe['id']}: {type(exc).__name__}: {' '.join(str(exc).split())}"[:300]}
    finally:
        shutil.rmtree(clean["dir"], ignore_errors=True)
    return probe["id"], out, None, retries


def screen_only(screen_record: dict) -> list[str]:
    """The defects the screen record says only the screen shows."""
    return [r["id"] for r in screen_record["defects"] if r["sees"] == "screen-only"]


def measure(doc: dict, profile: dict, probes: list[dict], out: Path, defects: list[str], *, runner=None,
            jobs: int = 1, root: Path = REPO, bench_path: Path = bench.BENCH, menu: dict | None = None) -> dict:
    """Replay each probe on the clean game once and on each named defect build once, with frames; write
    ``out/repro-pixel-reach.json``."""
    from harness.run import GODOT_VERSION

    roles = offered(menu)
    by_id = {d["id"]: d for d in doc["defects"]}
    unknown = [d for d in defects if d not in by_id]
    if unknown or not defects:
        raise PixelReachError(f"no defect {unknown[0][:60]!r} in the bench" if unknown else "no defect to measure")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    work = out / "work"
    pairs = [(d, str(root / by_id[d]["patch"])) for d in defects]
    tasks = [(profile, p, pairs, str(work / p["id"]), runner) for p in probes]
    try:
        if jobs > 1:
            with ProcessPoolExecutor(max_workers=jobs) as pool:
                done = list(pool.map(_probe_task, tasks))
        else:
            done = [_probe_task(t) for t in tasks]
    finally:
        shutil.rmtree(work, ignore_errors=True)
    stops = [(pid, err) for pid, _o, err, _n in done if err]
    if stops:
        raise PixelReachError(f"the clean game could not be replayed on probe {stops[0][0]}: {stops[0][1]}")
    retries = sum(n for *_x, n in done)
    rows = []
    for did in defects:
        found = [o[did] for _pid, o, _e, _n in done]
        errors = [f["error"] for f in found if "error" in f]
        row = {"id": did, "patchSha256": bench.sha256(root / by_id[did]["patch"])}
        if errors:
            row.update(reach="error", probesMeasured=0, probes=[], error=errors[0])
        else:
            shown = [f for f in found if f["framesDiffer"]]
            row.update(reach=reach_of(found), probesMeasured=len(found), probes=shown)
        rows.append(row)
    record = {"format": FORMAT, "benchSha256": bench.sha256(bench_path), "engine": f"Godot {GODOT_VERSION}",
              "observer": setting(), "objects": roles, "probes": [p["id"] for p in probes],
              "replaysPerBuild": {"clean": 1, "defect": 1}, "engineRetries": retries,
              "defects": rows, "totals": totals(rows)}
    found = problems(record)
    if found:
        raise PixelReachError("; ".join(found))
    (out / NAME).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return record


def totals(rows: list[dict]) -> dict:
    return {"defects": len(rows), **{k: sum(r["reach"] == k for r in rows) for k in REACH}}


# --- the record ---------------------------------------------------------------------------------------

def problems(record) -> list[str]:
    """What is wrong with a pixel-reach record: the schema first, then what must agree inside it."""
    import jsonschema

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(record), key=lambda e: list(e.path))
    if errors:
        return [f"repro-pixel-reach: {'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}"[:300]
                for e in errors[:10]]
    out = []
    ids = [r["id"] for r in record["defects"]]
    if len(set(ids)) != len(ids):
        out.append("repro-pixel-reach: a defect is listed twice")
    names = set(record["probes"])
    for r in record["defects"]:
        if r["reach"] == "error":
            if r["probes"] or r["probesMeasured"] or not r.get("error"):
                out.append(f"repro-pixel-reach: {r['id']}: an error row carries results")
            continue
        if "error" in r or r["probesMeasured"] != len(names):
            out.append(f"repro-pixel-reach: {r['id']}: the probe count does not agree with the record")
        seen = [p["probe"] for p in r["probes"]]
        if len(set(seen)) != len(seen) or not set(seen) <= names:
            out.append(f"repro-pixel-reach: {r['id']}: a probe is unknown or listed twice")
        for p in r["probes"]:
            if not (0 < p["framesDiffer"] <= p["framesAsked"] and p["framesDifferInBox"] <= p["framesDiffer"]
                    and p["gaps"] <= p["framesAsked"] and p["boxesMoved"] <= p["framesDiffer"]
                    and (p["maxPixelsInBox"] > 0) == (p["framesDifferInBox"] > 0)):
                out.append(f"repro-pixel-reach: {r['id']}: probe {p['probe']} does not agree with itself")
        if r["reach"] != reach_of(r["probes"]):
            out.append(f"repro-pixel-reach: {r['id']}: {r['reach']!r} does not follow from its probes")
    if record["totals"] != totals(record["defects"]):
        out.append("repro-pixel-reach: the totals do not match the rows")
    return out


def load(path: Path = RECORD) -> dict:
    raw = Path(path).read_bytes()
    if len(raw) > MAX_BYTES:
        raise PixelReachError(f"repro-pixel-reach: over {MAX_BYTES} bytes")
    try:
        record = strict_loads(raw.decode("utf-8"))
    except (ValueError, ContractError) as exc:
        raise PixelReachError(f"repro-pixel-reach: unreadable: {exc}"[:300]) from exc
    found = problems(record)
    if found:
        raise PixelReachError("; ".join(found))
    return record


def stale(record: dict, doc: dict, root: Path = REPO, bench_path: Path = bench.BENCH) -> list[str]:
    """Why the record no longer describes the bench: a defect it names is gone or its patch changed."""
    out = []
    if record["benchSha256"] != bench.sha256(bench_path):
        out.append("the bench file changed since the record was made")
    by_id = {d["id"]: d for d in doc["defects"]}
    for r in record["defects"]:
        d = by_id.get(r["id"])
        if d is None:
            out.append(f"{r['id']}: no longer in the bench")
        elif bench.sha256(root / d["patch"]) != r["patchSha256"]:
            out.append(f"{r['id']}: its patch changed since the record was made")
    return out


def render(record: dict) -> str:
    t, o = record["totals"], record["observer"]
    lines = [f"{t['defects']} defects, {len(record['probes'])} probes, {record['engine']}, observer {o['name']} "
             f"(the {o['box']} box widened by {o['pad']:g} game px, every {o['every']}th frame and the last, at most "
             f"{o['maxFrames']}), objects offered: {', '.join(record['objects']) or 'none'}. No model, nothing asked. "
             f"A difference inside an offered box: {t['inside-a-box']}. Frames differ, never inside an offered box: "
             f"{t['outside-every-box']}. No planned frame differs: {t['no-difference']}."
             + (f" Could not be measured: {t['error']}." if t["error"] else ""), "",
             "| Defect | Reach | Probes where a planned frame differs | Planned frames differing inside the box, of those differing (probes) | Most pixels inside the box |",
             "| --- | --- | --- | --- | --- |"]
    for r in record["defects"]:
        if r["reach"] == "error":
            lines.append(f"| `{r['id']}` | error | {r['error'][:120]} | | |")
            continue
        ps = r["probes"]
        inside = sum(p["framesDifferInBox"] for p in ps)
        lines.append(f"| `{r['id']}` | {r['reach']} | {len(ps)} of {r['probesMeasured']} | "
                     f"{inside} of {sum(p['framesDiffer'] for p in ps)} ({sum(bool(p['framesDifferInBox']) for p in ps)}) | "
                     f"{max([p['maxPixelsInBox'] for p in ps], default=0)} |")
    return "\n".join(lines) + "\n"
