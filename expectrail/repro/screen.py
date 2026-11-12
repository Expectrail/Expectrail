"""What each bench defect changes on the screen, beside what it changes in the engine's record. No model.

    python3 -m expectrail.repro screen --out runs/repro-screen --jobs 2      # replays the game with frames; no model, no key
    python3 -m expectrail.repro screen-render bench/jit/public/screen.json

``expectrail.repro.visibility`` asks what a defect changes in the engine's record, because that is
all a generated check can read today. A generated check is to speak about what is drawn as well
(issue #286), so this asks the same question of the frames: every probe is replayed with its frames
captured, on the clean game twice and on each defect build once, and both the frames and the
record of the same replay are compared with the clean game's. A defect comes out as one of:

- **record-and-screen**: on some probe the record differs, and on some probe the frames do.
- **screen-only**: the frames differ on some probe and the record is the same on every probe. A
  check that reads only the record can never fail on this defect on these probes.
- **record-only**: the record differs and every frame is the same.
- **neither**: nothing differs. No probe reaches the behaviour, or nothing a probe does shows it.

A frame differs when at least one pixel does. No observer is asked what the difference is: this
says that the picture changed, where, on which probe and from which frame, and nothing about
whether an observer could name it. Whatever differs between the two replays of the clean game is
unstable and is not counted for any defect: a record field on that probe, and every pixel that
differed on any frame of that probe. A build whose frames cannot be compared with the clean game's
(another count, another size) is an error row, never a guess.

It is not a reproduction rate, and nothing under ``expectrail/jit/`` reads it.
"""
from __future__ import annotations

import json
import shutil
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from expectrail.contracts import ContractError, strict_loads
from expectrail.repro import bench

REPO = bench.REPO
SCHEMA = REPO / "contracts" / "repro-screen.v1.schema.json"
RECORD = REPO / "bench" / "jit" / "public" / "screen.json"
FORMAT = "expectrail.repro-screen/v1"
NAME = "repro-screen.json"
KINDS = ("record-and-screen", "screen-only", "record-only", "neither", "error")
NOT_FIELDS = ("tick", "frame")
MAX_BYTES = 2 * 1024 * 1024
ATTEMPTS = 3
FPS = 60
SCRIPT_ERRORS = ("SCRIPT ERROR", "Parse Error")
_TO_FF = bytes([0]) + bytes([255]) * 255     # any pixel that differs at all becomes 255


class ScreenError(ValueError):
    """A screen measurement or its record cannot be used."""


# --- two frames ---------------------------------------------------------------------------------

def decode(path: Path) -> tuple[int, int, bytes]:
    """(width, height, RGB bytes) of one frame. Pillow decodes when it is installed (milliseconds for
    a 1600 x 960 frame); otherwise the standard-library reader the Unity harness uses (seconds)."""
    try:
        from PIL import Image
    except ImportError:
        from harness.unity import png_pixels

        w, h, channels, pixels = png_pixels.read(path)
        if channels == 4:
            pixels = bytes(b for i, b in enumerate(pixels) if i % 4 != 3)
        return w, h, pixels
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        return rgb.width, rgb.height, rgb.tobytes()


def differing(a: bytes, b: bytes) -> bytes:
    """One byte per pixel: 255 where any channel of two RGB frames differs, else 0. The work is done on
    whole frames as integers, so a 1600 x 960 frame takes milliseconds without numpy."""
    n = len(a)
    x = (int.from_bytes(a, "little") ^ int.from_bytes(b, "little")).to_bytes(n, "little")
    merged = int.from_bytes(x[0::3], "little") | int.from_bytes(x[1::3], "little") | int.from_bytes(x[2::3], "little")
    return merged.to_bytes(n // 3, "little").translate(_TO_FF)


def without(mask: bytes, ignore: bytes | None) -> bytes:
    """``mask`` with the pixels of ``ignore`` cleared."""
    if ignore is None:
        return mask
    n = len(mask)
    keep = int.from_bytes(ignore, "little") ^ int.from_bytes(b"\xff" * n, "little")
    return (int.from_bytes(mask, "little") & keep).to_bytes(n, "little")


def union(a: bytes | None, b: bytes) -> bytes:
    if a is None:
        return b
    return (int.from_bytes(a, "little") | int.from_bytes(b, "little")).to_bytes(len(b), "little")


def extent(mask: bytes, width: int) -> tuple[int, list[int] | None]:
    """(pixels set, [left, top, right, bottom]) of a mask; right and bottom are one past the last pixel."""
    count = len(mask) - mask.count(0)
    if not count:
        return 0, None
    height = len(mask) // width
    top = (len(mask) - len(mask.lstrip(b"\0"))) // width
    bottom = (len(mask.rstrip(b"\0")) - 1) // width + 1
    left, right = width, 0
    for y in range(top, bottom):
        row = mask[y * width:(y + 1) * width]
        stripped = row.lstrip(b"\0")
        if stripped:
            left = min(left, width - len(stripped))
            right = max(right, len(row.rstrip(b"\0")))
    assert 0 <= top < bottom <= height and 0 <= left < right <= width
    return count, [left, top, right, bottom]


def _join(a: list[int] | None, b: list[int] | None) -> list[int] | None:
    if a is None or b is None:
        return a or b
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def frames_of(folder: Path) -> list[Path]:
    return sorted(Path(folder).glob("f*.png"))


def compare_frames(clean: Path, other: Path, ignore: bytes | None = None, *, keep_mask: bool = False) -> dict:
    """How one replay's frames differ from the clean game's on the same probe.

    {"frames", "size", "differing", "first", "maxPixels", "box"} and, with ``keep_mask``, "mask": every pixel
    that differed on any frame. Raises ScreenError when the two cannot be compared frame for frame."""
    a, b = frames_of(clean), frames_of(other)
    if not a:
        raise ScreenError("the clean replay has no frames")
    if len(a) != len(b):
        raise ScreenError(f"{len(b)} frames against the clean game's {len(a)}: they cannot be compared frame for frame")
    size, differ, first, most, box, seen = None, 0, None, 0, None, None
    for i, (pa, pb) in enumerate(zip(a, b)):
        raw_a, raw_b = pa.read_bytes(), pb.read_bytes()
        if raw_a == raw_b and size is not None:
            continue                       # the same file is the same picture; nothing to decode
        wa, ha, pix_a = decode(pa)
        if size is None:
            size = [wa, ha]
        if raw_a == raw_b:
            continue
        wb, hb, pix_b = decode(pb)
        if [wa, ha] != size or [wb, hb] != size:
            raise ScreenError(f"frame {i} is {wb} x {hb} against {wa} x {ha}: frames of two sizes cannot be compared")
        mask = without(differing(pix_a, pix_b), ignore)
        count, where = extent(mask, wa)
        if not count:
            continue
        differ += 1
        first = i if first is None else first
        most = max(most, count)
        box = _join(box, where)
        if keep_mask:
            seen = union(seen, mask)
    out = {"frames": len(a), "size": size, "differing": differ, "first": first, "maxPixels": most, "box": box}
    if keep_mask:
        out["mask"] = seen
    return out


# --- one build ----------------------------------------------------------------------------------

def _default_runner():
    from functools import partial

    from harness.run import run as harness_run

    return partial(harness_run, capture_frames=True, fps=FPS)


def replay_build(profile: dict, probes: list[dict], patches: list[str], work: str, *, runner=None,
                 keep: str | None = None, clean: str | None = None, ignore: str | None = None) -> tuple[dict, int]:
    """Replay every probe on one build with its frames and return ({probeId: {...}}, replays made again).

    ``keep``: a folder to move each probe's frames into (the clean game's, to compare the others with).
    ``clean``: the folder the clean game's frames were kept in; each probe's frames are compared with
    them and then deleted. ``ignore``: a folder with ``<probe>.mask`` for the probes that have unstable pixels.

    Per probe: "fields" (the record, a list of values per tick for each field), "frames", and with
    ``clean`` "screen" (see compare_frames)."""
    from expectrail.discovery.route_compiler import compile_route

    runner = runner or _default_runner()
    work_dir = Path(work)
    out: dict[str, dict] = {}
    retries = 0
    for p in probes:
        route = compile_route(p["program"], name=p["id"], description=p["description"], actions=profile["actions"])
        route_path = work_dir / "routes" / f"{p['id']}.json"
        route_path.parent.mkdir(parents=True, exist_ok=True)
        route_path.write_text(json.dumps(route, indent=1) + "\n", encoding="utf-8")
        run_dir = work_dir / "replays" / p["id"]
        for attempt in range(1, ATTEMPTS + 1):
            if run_dir.exists():
                shutil.rmtree(run_dir)
            try:
                runner(route_path, run_dir, patches=[Path(x) for x in patches])
                break
            except (Exception, SystemExit) as exc:  # noqa: BLE001 - the harness exits when the engine fails
                if attempt == ATTEMPTS:
                    raise ScreenError(f"probe {p['id']} could not be replayed in {ATTEMPTS} attempts: "
                                      f"{' '.join(str(exc).split())}"[:280]) from exc
                retries += 1
        log = run_dir / "godot.log"
        if log.is_file() and any(mark in log.read_text(encoding="utf-8", errors="replace") for mark in SCRIPT_ERRORS):
            raise ScreenError(f"the engine logged a script error on probe {p['id']}: the patch breaks a script")
        rows = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))["rows"]
        names = sorted({k for r in rows for k in r} - set(NOT_FIELDS))
        entry = {"fields": {n: [r.get(n) for r in rows] for n in names},
                 "frames": len(frames_of(run_dir / "frames"))}
        if not entry["frames"]:
            raise ScreenError(f"probe {p['id']} was replayed and no frame was captured")
        if clean is not None:
            mask_path = Path(ignore) / f"{p['id']}.mask" if ignore else None
            mask = mask_path.read_bytes() if mask_path is not None and mask_path.is_file() else None
            try:
                entry["screen"] = compare_frames(Path(clean) / p["id"], run_dir / "frames", mask)
            except ScreenError as exc:
                raise ScreenError(f"probe {p['id']}: {exc}") from exc
        if keep is not None:
            kept = Path(keep) / p["id"]
            if kept.exists():
                shutil.rmtree(kept)
            kept.mkdir(parents=True)
            for f in frames_of(run_dir / "frames"):
                shutil.move(str(f), str(kept / f.name))
        out[p["id"]] = entry
        shutil.rmtree(run_dir, ignore_errors=True)  # a replay copies the whole game and its frames; keep the disk small
    return out, retries


def _one_build(args) -> tuple[str, dict | None, str | None, int]:
    name, profile, probes, patches, work, runner, kw, cache = args
    cached = Path(cache)
    if cached.is_file():                      # a measurement that was stopped goes on from the builds it finished
        doc = json.loads(cached.read_text(encoding="utf-8"))
        return name, doc["data"], None, doc["retries"]
    try:
        data, retries = replay_build(profile, probes, patches, work, runner=runner, **kw)
        result = (name, data, None, retries)
    except Exception as exc:  # noqa: BLE001 - a build that cannot be replayed is a row that says so, never a guess
        result = (name, None, f"{type(exc).__name__}: {' '.join(str(exc).split())}"[:300], 0)
    shutil.rmtree(Path(work) / "replays", ignore_errors=True)
    if result[2] is None:                     # a failure is never kept: the same command tries that build again
        cached.parent.mkdir(parents=True, exist_ok=True)
        tmp = cached.with_suffix(".tmp")
        tmp.write_text(json.dumps({"data": result[1], "retries": result[3]}), encoding="utf-8")
        tmp.replace(cached)
    return result


# --- the measurement ----------------------------------------------------------------------------

def _first_tick(a: list, b: list) -> int:
    for t, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return t
    return min(len(a), len(b))


def compare(clean: dict, defect: dict, noisy: dict[str, set[str]]) -> dict:
    """One defect's row, less its id and digest: where it shows, and each probe on which anything differs."""
    probes, fields = [], set()
    for pid in sorted(clean):
        a, b = clean[pid]["fields"], defect[pid]["fields"]
        differ = {n for n in set(a) | set(b) if a.get(n) != b.get(n)} - noisy.get(pid, set())
        first = min((_first_tick(a.get(n) or [], b.get(n) or []) for n in differ), default=None)
        s = defect[pid]["screen"]
        if not differ and not s["differing"]:
            continue
        fields |= differ
        probes.append({"probe": pid, "recordFields": sorted(differ), "recordFirstTick": first,
                       "frames": s["frames"], "screenFrames": s["differing"], "screenFirstFrame": s["first"],
                       "maxPixels": s["maxPixels"], "box": s["box"]})
    return {"shows": _shows(probes), "recordFields": sorted(fields), "probes": probes}


def _shows(probes: list[dict]) -> str:
    record = any(p["recordFields"] for p in probes)
    screen = any(p["screenFrames"] for p in probes)
    return ("record-and-screen" if record and screen else "screen-only" if screen else
            "record-only" if record else "neither")


def totals(rows: list[dict]) -> dict:
    return {"defects": len(rows), **{k: sum(r["shows"] == k for r in rows) for k in KINDS}}


def measure(doc: dict, profile: dict, probes: list[dict], out: Path, *, runner=None, jobs: int = 1,
            only: list[str] | None = None, root: Path = REPO, bench_path: Path = bench.BENCH) -> dict:
    """Replay the clean game twice and every defect build once, with frames; write ``out/repro-screen.json``.

    The work is kept under ``out/work`` build by build, so the same command run again after a stop
    replays only the builds that had not finished. Delete ``out`` to measure from nothing."""
    from harness.run import GODOT_VERSION

    out = Path(out)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    key = {"bench": bench.sha256(bench_path), "probes": [p["id"] for p in probes],
           "programs": bench_digest(probes)}
    key_path = work / "key.json"
    if key_path.is_file() and json.loads(key_path.read_text(encoding="utf-8")) != key:
        raise ScreenError(f"{work} holds a measurement of another bench or other probes; delete it to measure again")
    key_path.write_text(json.dumps(key), encoding="utf-8")
    defects = [d for d in doc["defects"] if not only or d["id"] in only]
    clean_frames, clean_b_frames, masks = work / "clean-frames", work / "clean-b-frames", work / "unstable"

    def task(name, patches, **kw):
        return (name, profile, probes, patches, str(work / "builds" / name), runner, kw, str(work / "done" / f"{name}.json"))

    def run_all(tasks):
        if jobs > 1 and len(tasks) > 1:
            with ProcessPoolExecutor(max_workers=jobs) as pool:
                return list(pool.map(_one_build, tasks))
        return [_one_build(t) for t in tasks]

    cleans = run_all([task("clean-a", [], keep=str(clean_frames)), task("clean-b", [], keep=str(clean_b_frames))])
    for name, data, err, _n in cleans:
        if data is None:
            raise ScreenError(f"the clean game could not be replayed: {err}")
    clean_a, clean_b = cleans[0][1], cleans[1][1]
    unstable_rows, noisy = [], {}
    unstable_path = work / "done" / "unstable.json"
    if unstable_path.is_file():
        unstable_rows = json.loads(unstable_path.read_text(encoding="utf-8"))
    else:
        masks.mkdir(parents=True, exist_ok=True)
        for p in probes:
            pid = p["id"]
            a, b = clean_a[pid]["fields"], clean_b[pid]["fields"]
            fields = sorted(n for n in set(a) | set(b) if a.get(n) != b.get(n))
            try:
                s = compare_frames(clean_frames / pid, clean_b_frames / pid, keep_mask=True)
            except ScreenError as exc:
                raise ScreenError(f"the two replays of the clean game cannot be compared on probe {pid}: {exc}") from exc
            if s["differing"]:
                (masks / f"{pid}.mask").write_bytes(s["mask"])
            if fields or s["differing"]:
                unstable_rows.append({"probe": pid, "fields": fields, "frames": s["differing"],
                                      "pixels": len(s["mask"]) - s["mask"].count(0) if s["differing"] else 0})
        unstable_path.write_text(json.dumps(unstable_rows), encoding="utf-8")
        shutil.rmtree(clean_b_frames, ignore_errors=True)
    noisy = {u["probe"]: set(u["fields"]) for u in unstable_rows}
    size = decode(frames_of(clean_frames / probes[0]["id"])[0])[:2]

    done = run_all([task(d["id"], [str(root / d["patch"])], clean=str(clean_frames), ignore=str(masks)) for d in defects])
    results = {name: (data, err) for name, data, err, _n in done}
    retries = sum(n for _name, _data, _err, n in cleans + done)
    rows = []
    for d in defects:
        data, err = results[d["id"]]
        row = {"id": d["id"], "patchSha256": bench.sha256(root / d["patch"])}
        if data is None:
            row.update(shows="error", recordFields=[], probes=[], error=err)
        else:
            row.update(compare(clean_a, data, noisy))
        rows.append(row)
    record = {"format": FORMAT, "benchSha256": key["bench"], "engine": f"Godot {GODOT_VERSION}",
              "probes": key["probes"],
              "capture": {"fps": FPS, "width": size[0], "height": size[1],
                          "frames": sum(clean_a[p["id"]]["frames"] for p in probes)},
              "replaysPerBuild": {"clean": 2, "defect": 1}, "engineRetries": retries,
              "unstable": unstable_rows, "defects": rows, "totals": totals(rows)}
    found = problems(record)
    if found:
        raise ScreenError("; ".join(found))
    (out / NAME).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return record


def choose(library: list[dict], wanted: list[str]) -> list[dict]:
    """The library's probes, or the ones named, in the library's order. A name the library does not have is refused."""
    if not wanted:
        return list(library)
    unknown = sorted(set(wanted) - {p["id"] for p in library})
    if unknown:
        raise ScreenError("not a library probe: " + ", ".join(repr(u)[:70] for u in unknown[:5]))
    return [p for p in library if p["id"] in set(wanted)]


def bench_digest(probes: list[dict]) -> str:
    import hashlib

    return hashlib.sha256(json.dumps([[p["id"], p["program"]] for p in probes], sort_keys=True).encode()).hexdigest()


# --- the record ---------------------------------------------------------------------------------

def problems(record) -> list[str]:
    """What is wrong with a screen record: the schema first, then what must agree inside it."""
    import jsonschema

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(record), key=lambda e: list(e.path))
    if errors:
        return [f"repro-screen: {'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}"[:300]
                for e in errors[:10]]
    out = []
    ids = [r["id"] for r in record["defects"]]
    if len(set(ids)) != len(ids):
        out.append("repro-screen: a defect is listed twice")
    width, height = record["capture"]["width"], record["capture"]["height"]
    known = set(record["probes"])
    for u in record["unstable"]:
        if u["probe"] not in known or not (u["fields"] or u["frames"]) or (u["frames"] > 0) != (u["pixels"] > 0):
            out.append(f"repro-screen: the unstable entry for {u['probe']} does not agree with itself")
    for r in record["defects"]:
        if r["shows"] == "error":
            if r["probes"] or r["recordFields"] or not r.get("error"):
                out.append(f"repro-screen: {r['id']}: an error row carries a reason and no measurement")
            continue
        if "error" in r or r["shows"] != _shows(r["probes"]):
            out.append(f"repro-screen: {r['id']}: shows {r['shows']!r} does not follow from its probes")
        if r["recordFields"] != sorted({f for p in r["probes"] for f in p["recordFields"]}):
            out.append(f"repro-screen: {r['id']}: recordFields is not what its probes list")
        names = [p["probe"] for p in r["probes"]]
        if len(set(names)) != len(names) or not set(names) <= known:
            out.append(f"repro-screen: {r['id']}: a probe is listed twice or is not one of the record's")
        for p in r["probes"]:
            where = f"repro-screen: {r['id']} on {p['probe']}"
            if not p["recordFields"] and not p["screenFrames"]:
                out.append(f"{where}: listed, and nothing differs")
            if bool(p["recordFields"]) != (p["recordFirstTick"] is not None):
                out.append(f"{where}: the first tick does not agree with the fields")
            shown = p["screenFrames"] > 0
            if (shown != (p["screenFirstFrame"] is not None) or shown != (p["box"] is not None)
                    or shown != (p["maxPixels"] > 0) or p["screenFrames"] > p["frames"]):
                out.append(f"{where}: the frames, the first frame, the pixels and the box do not agree")
                continue
            if shown:
                left, top, right, bottom = p["box"]
                if (not (0 <= left < right <= width and 0 <= top < bottom <= height)
                        or p["maxPixels"] > (right - left) * (bottom - top)
                        or p["screenFirstFrame"] + p["screenFrames"] > p["frames"]):
                    out.append(f"{where}: the box, the pixels or the first frame cannot be right for the capture")
    if record["totals"] != totals(record["defects"]):
        out.append("repro-screen: the totals do not match the rows")
    return out


def load(path: Path = RECORD) -> dict:
    raw = Path(path).read_bytes()
    if len(raw) > MAX_BYTES:
        raise ScreenError(f"repro-screen: over {MAX_BYTES} bytes")
    try:
        record = strict_loads(raw.decode("utf-8"))
    except (ValueError, ContractError) as exc:
        raise ScreenError(f"repro-screen: unreadable: {exc}"[:300]) from exc
    found = problems(record)
    if found:
        raise ScreenError("; ".join(found))
    return record


def stale(record: dict, doc: dict, root: Path = REPO, bench_path: Path = bench.BENCH) -> list[str]:
    """Why the record no longer describes the bench: [] when it covers exactly these defects and patches."""
    out = []
    now = {d["id"]: bench.sha256(root / d["patch"]) for d in doc["defects"]}
    then = {r["id"]: r["patchSha256"] for r in record["defects"]}
    for did in sorted(set(now) | set(then)):
        if did not in then:
            out.append(f"{did}: not measured")
        elif did not in now:
            out.append(f"{did}: measured, and no longer in the bench")
        elif now[did] != then[did]:
            out.append(f"{did}: the patch changed after it was measured")
    if not out and record["benchSha256"] != bench.sha256(bench_path):
        out.append("the bench file changed after it was measured")
    return out


def clearest(row: dict) -> dict | None:
    """The probe a reader should look at first for a defect's screen: the one where the most frames differ
    (then the earliest first frame, then the name)."""
    shown = [p for p in row["probes"] if p["screenFrames"]]
    return min(shown, key=lambda p: (-p["screenFrames"], p["screenFirstFrame"], p["probe"])) if shown else None


def render(record: dict, doc: dict | None = None) -> str:
    """The record as a table. With the bench, each row also gets its family and what its author expected."""
    t, c = record["totals"], record["capture"]
    meta = {d["id"]: d for d in doc["defects"]} if doc else {}
    lines = [f"{t['defects']} defects, {len(record['probes'])} probes, {c['frames']} frames a build at "
             f"{c['width']} x {c['height']}, {record['engine']}, no model. "
             f"The record and the screen both differ: {t['record-and-screen']}. Only the screen differs: {t['screen-only']}. "
             f"Only the record differs: {t['record-only']}. Nothing differs: {t['neither']}."
             + (f" Could not be measured: {t['error']}." if t["error"] else "")
             + (f" Replays made again after the engine failed: {record['engineRetries']}." if record["engineRetries"] else ""),
             "",
             "| Defect | Family | Author expected | Measured | Record differs on | Screen differs on "
             "| Where the screen shows it most: probe, frames that differ, from frame, most pixels in a frame, box |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in record["defects"]:
        m = meta.get(r["id"], {})
        if r["shows"] == "error":
            lines.append(f"| `{r['id']}` | {m.get('family', '')} | {m.get('authorExpects', '')} | error | | | |")
            continue
        rec = sum(1 for p in r["probes"] if p["recordFields"])
        scr = sum(1 for p in r["probes"] if p["screenFrames"])
        fields = ", ".join(f"`{f}`" for f in r["recordFields"])
        best = clearest(r)
        where = "" if best is None else (
            f"`{best['probe']}`, {best['screenFrames']} of {best['frames']}, from {best['screenFirstFrame']}, "
            f"{best['maxPixels']}, {best['box'][0]},{best['box'][1]} to {best['box'][2]},{best['box'][3]}")
        lines.append(f"| `{r['id']}` | {m.get('family', '')} | {m.get('authorExpects', '')} | {r['shows']} | "
                     f"{f'{rec} ({fields})' if rec else 'none'} | {scr or 'none'} | {where} |")
    if record["unstable"]:
        lines += ["", "Unstable between two replays of the clean game, and so not counted: "
                  + "; ".join(f"`{u['probe']}` ("
                              + ", ".join(u["fields"] + ([f"{u['pixels']} pixels on {u['frames']} frames"] if u["frames"] else []))
                              + ")" for u in record["unstable"]) + "."]
    return "\n".join(lines) + "\n"
