"""What each bench defect changes on the screen, beside what it changes in the engine's record. No model.

    python3 -m expectrail.repro screen --out runs/repro-screen --jobs 2     # replays the game with frames; no model, no key
    python3 -m expectrail.repro screen-render bench/jit/public/screen.json

Expectrail verifies by observing, so a generated check has to be able to speak about what is drawn
(issue #286), and a defect that only shows on the screen is one the engine's record can never
reproduce. Which defects those are was a label written by the bench's author and two replays made by
hand. This measures it: every probe is replayed with its frames captured, on the clean game twice
and on each defect build once, and the frames and the record of the same replay are both compared
with the clean game's. Each defect is then one of:

- **record-and-screen**: the record differs on some probe and the frames differ on some probe.
- **screen-only**: frames differ on some probe; the record is the same on every probe. No check
  that reads only the record can fail on this defect along these probes.
- **record-only**: the record differs and every frame is the same.
- **neither**: nothing differs on any probe. No probe reaches the behaviour, or nothing along these
  probes shows it either way. This measurement cannot tell the two apart.

Frames are compared exactly, byte for byte of the decoded picture: a frame differs when any pixel
does. That is only sound because the capture is repeatable (fixed frame rate, not real time, a
software renderer), and the measurement checks it instead of assuming it: a frame that differs
between the two clean replays of a probe is unstable there and is counted for no defect, as is a
field of the record. Any difference counts, however small, so each row keeps how many frames
differ, the first one, and the size and place of the difference for a reader to judge. A
difference in a frame says the picture changed; it does not say a player would notice.

How large a difference is comes from at most ``MAX_EXAMINED`` of a probe's differing frames (the
first, the last, and evenly between), not from all of them: decoding every frame of every replay
would take longer than the replays. So ``pixels`` is the most found among the frames examined, and
``box`` is the smallest rectangle that holds every differing pixel of those frames.

This is what a watcher of the frames could be shown, not what any observer reports: no visual
observer (SAM or another) was asked anything, and nothing here is a reproduction rate.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from expectrail.contracts import ContractError, strict_loads
from expectrail.repro import bench, visibility

REPO = bench.REPO
SCHEMA = REPO / "contracts" / "repro-screen.v1.schema.json"
RECORD = REPO / "bench" / "jit" / "public" / "screen.json"
FORMAT = "expectrail.repro-screen/v1"
NAME = "repro-screen.json"
SEES = ("record-and-screen", "screen-only", "record-only", "neither", "error")
MAX_EXAMINED = 8
MAX_BYTES = 1024 * 1024
ATTEMPTS = visibility.ATTEMPTS


class ScreenError(ValueError):
    """A screen measurement cannot be made, or its record cannot be used."""


# --- two frames ------------------------------------------------------------------------------------------

def _planes(width: int, height: int, channels: int, pixels: bytes) -> list[int]:
    """Red, green and blue as three whole numbers, one byte a pixel each (alpha is not compared)."""
    if channels not in (3, 4) or len(pixels) != width * height * channels:
        raise ScreenError("a frame is not 8-bit RGB or RGBA")
    return [int.from_bytes(pixels[i::channels], "big") for i in range(3)]


def frame_difference(path_a: Path, path_b: Path) -> dict:
    """{"width", "height", "pixels", "box"}: how many pixels differ in any of red, green and blue, and
    the smallest rectangle [left, top, right, bottom] that holds them (right and bottom are one past
    the last pixel), or None when none differs. Two frames of different sizes differ everywhere.

    The comparison is done on whole planes at once (exclusive-or of three large numbers), so a
    1600 x 960 frame takes milliseconds without any library beyond the decoder."""
    from harness.unity import png_pixels

    try:
        wa, ha, ca, pa = png_pixels._decode(Path(path_a))
        wb, hb, cb, pb = png_pixels._decode(Path(path_b))
    except Exception as exc:  # noqa: BLE001 - whatever the decoder raises (OSError, zlib.error, Pillow's own), the frame cannot be read
        raise ScreenError(f"a frame cannot be read: {type(exc).__name__}: {' '.join(str(exc).split())}"[:200]) from exc
    if (wa, ha) != (wb, hb):
        return {"width": wa, "height": ha, "pixels": wa * ha, "box": [0, 0, wa, ha]}
    mask = 0
    for a, b in zip(_planes(wa, ha, ca, pa), _planes(wb, hb, cb, pb)):
        mask |= a ^ b
    if not mask:
        return {"width": wa, "height": ha, "pixels": 0, "box": None}
    marks = mask.to_bytes(wa * ha, "big")           # one byte a pixel: zero where the two frames agree
    left, right, top, bottom = wa, 0, None, 0
    for y in range(ha):
        row = marks[y * wa:(y + 1) * wa]
        if row.count(0) == wa:
            continue
        top = y if top is None else top
        bottom = y + 1
        left = min(left, wa - len(row.lstrip(b"\0")))
        right = max(right, len(row.rstrip(b"\0")))
    return {"width": wa, "height": ha, "pixels": wa * ha - marks.count(0), "box": [left, top, right, bottom]}


def _sample(indexes: list[int], limit: int | None = None) -> list[int]:
    """At most ``limit`` (MAX_EXAMINED) of the indexes: the first, the last, and evenly between."""
    limit = MAX_EXAMINED if limit is None else limit
    if len(indexes) <= limit:
        return list(indexes)
    step = (len(indexes) - 1) / (limit - 1)
    return sorted({indexes[round(i * step)] for i in range(limit)})


# --- one build --------------------------------------------------------------------------------------------

def _default_runner():
    from functools import partial

    from harness.run import run as harness_run

    return partial(harness_run, capture_frames=True)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture_probe(profile: dict, probe: dict, patches: list[str], work: Path, runner) -> tuple[dict, int]:
    """Replay one probe with frames. ({"frames": [sha256 per frame], "fields": {name: [value per tick]},
    "dir": the folder that holds frames/, "renderer": str | None}, replays made again)."""
    from expectrail.discovery.route_compiler import compile_route

    route = compile_route(probe["program"], name=probe["id"], description=probe["description"],
                          actions=profile["actions"])
    route_path = work / "routes" / f"{probe['id']}.json"
    route_path.parent.mkdir(parents=True, exist_ok=True)
    route_path.write_text(json.dumps(route, indent=1) + "\n", encoding="utf-8")
    run_dir = work / "replays" / probe["id"]
    retries = 0
    for attempt in range(1, ATTEMPTS + 1):
        if run_dir.exists():
            shutil.rmtree(run_dir)
        try:
            runner(route_path, run_dir, patches=[Path(x) for x in patches])
            break
        except (Exception, SystemExit) as exc:  # noqa: BLE001 - the harness exits when the engine fails
            if attempt == ATTEMPTS:
                raise ScreenError(f"probe {probe['id']} could not be replayed in {ATTEMPTS} attempts: "
                                  f"{' '.join(str(exc).split())}"[:280]) from exc
            retries += 1
    log = run_dir / "godot.log"
    if log.is_file() and any(mark in log.read_text(encoding="utf-8", errors="replace")
                             for mark in visibility.SCRIPT_ERRORS):
        raise ScreenError(f"the engine logged a script error on probe {probe['id']}: the patch breaks a script")
    rows = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))["rows"]
    names = sorted({k for r in rows for k in r} - set(visibility.NOT_FIELDS))
    frames = sorted((run_dir / "frames").glob("f*.png"))
    if not frames:
        raise ScreenError(f"probe {probe['id']}: the replay wrote no frames")
    renderer = None
    try:
        replay = json.loads((run_dir / "replay.json").read_text(encoding="utf-8"))
        renderer = replay["engine"]["device"] if isinstance(replay["engine"]["device"], str) else None
    except (OSError, ValueError, KeyError, TypeError):
        pass
    shutil.rmtree(run_dir / "work", ignore_errors=True)   # the game's copy; the frames and the record are what is read
    return {"frames": [_sha(f) for f in frames], "fields": {n: [r.get(n) for r in rows] for n in names},
            "dir": str(run_dir), "renderer": renderer}, retries


def compare_probe(clean: dict, defect: dict, skip_frames: set[int], skip_fields: set[str]) -> dict:
    """One probe of one defect against the clean game's first replay: the record fields that differ, and
    what differs in the frames ({"frames", "of", "firstFrame", "examined", "pixels", "atFrame", "box"} or None).
    The frames of both replays must still be on disk."""
    fields = sorted({n for n in set(clean["fields"]) | set(defect["fields"])
                     if clean["fields"].get(n) != defect["fields"].get(n)} - skip_fields)
    a, d = clean["frames"], defect["frames"]
    if len(a) != len(d):
        raise ScreenError(f"the defect build's capture has {len(d)} frames and the clean game's has {len(a)}: "
                          "the two cannot be compared frame by frame")
    differing = [i for i, (x, y) in enumerate(zip(a, d)) if x != y and i not in skip_frames]
    if not differing:
        return {"fields": fields, "screen": None}
    names_a = sorted((Path(clean["dir"]) / "frames").glob("f*.png"))
    names_d = sorted((Path(defect["dir"]) / "frames").glob("f*.png"))
    most, at, box, examined, same_picture = 0, None, None, 0, 0
    width = height = 0
    for i in _sample(differing):
        diff = frame_difference(names_a[i], names_d[i])
        examined += 1
        width, height = diff["width"], diff["height"]
        if diff["box"] is None:      # the two files differ and the pictures do not (an encoder's choice)
            same_picture += 1
            continue
        if diff["pixels"] > most:
            most, at = diff["pixels"], i
        box = diff["box"] if box is None else [min(box[0], diff["box"][0]), min(box[1], diff["box"][1]),
                                               max(box[2], diff["box"][2]), max(box[3], diff["box"][3])]
    if box is None:
        if same_picture == len(differing):   # every differing file was looked at, and every picture is the same
            return {"fields": fields, "screen": None}
        raise ScreenError(f"{len(differing)} frame files differ, and none of the {examined} examined differs as a "
                          "picture: whether the screen changed cannot be told")
    return {"fields": fields, "screen": {"frames": len(differing), "of": len(a), "firstFrame": differing[0],
                                         "examined": examined, "pixels": most, "atFrame": at, "box": box,
                                         "width": width, "height": height}}


def _clean_build(args) -> tuple[str, dict | None, str | None, int]:
    name, profile, probes, work, runner, keep = args
    runner = runner or _default_runner()
    out, retries = {}, 0
    try:
        for p in probes:
            got, n = capture_probe(profile, p, [], Path(work), runner)
            retries += n
            if not keep:
                shutil.rmtree(got["dir"], ignore_errors=True)
            out[p["id"]] = got
        return name, out, None, retries
    except Exception as exc:  # noqa: BLE001 - reported by the caller: no clean game, no record
        return name, None, f"{type(exc).__name__}: {' '.join(str(exc).split())}"[:300], 0


def _defect_build(args) -> tuple[str, dict | None, str | None, int]:
    """One defect build: every probe replayed, compared with the clean frames while both are on disk, and
    its own frames removed. {probeId: compare_probe's result}."""
    name, profile, probes, patches, work, runner, clean, noisy = args
    runner = runner or _default_runner()
    out, retries = {}, 0
    try:
        for p in probes:
            got, n = capture_probe(profile, p, patches, Path(work), runner)
            retries += n
            skip_frames, skip_fields = noisy.get(p["id"], (set(), set()))
            try:
                out[p["id"]] = compare_probe(clean[p["id"]], got, skip_frames, skip_fields)
            except ScreenError as exc:
                raise ScreenError(f"probe {p['id']}: {exc}"[:280]) from exc
            finally:
                shutil.rmtree(got["dir"], ignore_errors=True)
        return name, out, None, retries
    except Exception as exc:  # noqa: BLE001 - a build that cannot be measured is a row that says so, never a guess
        return name, None, f"{type(exc).__name__}: {' '.join(str(exc).split())}"[:300], 0


# --- the measurement --------------------------------------------------------------------------------------

def unstable(clean_a: dict, clean_b: dict) -> dict[str, tuple[set[int], set[str]]]:
    """Per probe, the frame numbers and the record fields that differ between the two clean replays."""
    out = {}
    for pid in clean_a:
        a, b = clean_a[pid], clean_b[pid]
        if len(a["frames"]) != len(b["frames"]):
            raise ScreenError(f"probe {pid}: two replays of the clean game captured {len(a['frames'])} and "
                              f"{len(b['frames'])} frames; the capture is not repeatable here")
        frames = {i for i, (x, y) in enumerate(zip(a["frames"], b["frames"])) if x != y}
        fields = {n for n in set(a["fields"]) | set(b["fields"]) if a["fields"].get(n) != b["fields"].get(n)}
        if frames or fields:
            out[pid] = (frames, fields)
    return out


def _sees(record_fields: list[str], screen: dict | None) -> str:
    if record_fields:
        return "record-and-screen" if screen else "record-only"
    return "screen-only" if screen else "neither"


def summarize(by_probe: dict[str, dict]) -> dict:
    """One defect's row, less its id and digest, from compare_probe's result for every probe."""
    fields = sorted({f for r in by_probe.values() for f in r["fields"]})
    shown = {pid: r["screen"] for pid, r in by_probe.items() if r["screen"]}
    screen = None
    if shown:   # the probe where the most frames differ; then the larger difference; then the name
        pid = sorted(shown, key=lambda k: (-shown[k]["frames"], -shown[k]["pixels"], k))[0]
        screen = {"probe": pid, **{k: v for k, v in shown[pid].items() if k not in ("width", "height")}}
    return {"sees": _sees(fields, screen), "recordFields": fields,
            "probesRecordChanged": sum(bool(r["fields"]) for r in by_probe.values()),
            "probesScreenChanged": len(shown), "screen": screen}


def totals(rows: list[dict]) -> dict:
    return {"defects": len(rows), **{k: sum(r["sees"] == k for r in rows) for k in SEES}}


def measure(doc: dict, profile: dict, probes: list[dict], out: Path, *, runner=None, jobs: int = 1,
            only: list[str] | None = None, root: Path = REPO, bench_path: Path = bench.BENCH,
            keep_frames: bool = False) -> dict:
    """Replay the clean game twice and every defect build once, with frames; write ``out/repro-screen.json``."""
    from harness.run import GODOT_VERSION

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    work = out / "work"
    defects = [d for d in doc["defects"] if not only or d["id"] in only]
    cleans = [("clean-a", profile, probes, str(work / "clean-a"), runner, True),
              ("clean-b", profile, probes, str(work / "clean-b"), runner, False)]
    try:
        if jobs > 1:
            with ProcessPoolExecutor(max_workers=jobs) as pool:
                done = list(pool.map(_clean_build, cleans))
        else:
            done = [_clean_build(t) for t in cleans]
        for name, data, err, _n in done:
            if data is None:
                raise ScreenError(f"the clean game could not be replayed: {err}")
        clean, noisy = done[0][1], unstable(done[0][1], done[1][1])
        retries = sum(n for _name, _data, _err, n in done)
        tasks = [(d["id"], profile, probes, [str(root / d["patch"])], str(work / d["id"]), runner, clean, noisy)
                 for d in defects]
        if jobs > 1:
            with ProcessPoolExecutor(max_workers=jobs) as pool:
                built = list(pool.map(_defect_build, tasks))
        else:
            built = [_defect_build(t) for t in tasks]
        first = sorted((Path(clean[probes[0]["id"]]["dir"]) / "frames").glob("f*.png"))[0]
        size = frame_difference(first, first)
    finally:
        if not keep_frames:
            shutil.rmtree(work, ignore_errors=True)
    results = {name: (data, err) for name, data, err, _n in built}
    retries += sum(n for _name, _data, _err, n in built)
    rows = []
    for d in defects:
        data, err = results[d["id"]]
        row = {"id": d["id"], "patchSha256": bench.sha256(root / d["patch"])}
        if data is None:
            row.update(sees="error", recordFields=[], probesRecordChanged=0, probesScreenChanged=0, screen=None,
                       error=err)
        else:
            row.update(summarize(data))
        rows.append(row)
    renderers = sorted({v["renderer"] for v in clean.values() if v["renderer"]})
    record = {"format": FORMAT, "benchSha256": bench.sha256(bench_path), "engine": f"Godot {GODOT_VERSION}",
              "renderer": renderers[0][:120] if len(renderers) == 1 else None,
              "frame": {"width": size["width"], "height": size["height"]},
              "probes": [p["id"] for p in probes], "replaysPerBuild": {"clean": 2, "defect": 1},
              "maxFramesExamined": MAX_EXAMINED, "engineRetries": retries,
              "unstable": [{"probe": pid, "frames": len(f), "fields": sorted(s)} for pid, (f, s) in sorted(noisy.items())],
              "defects": rows, "totals": totals(rows)}
    found = problems(record)
    if found:
        raise ScreenError("; ".join(found))
    (out / NAME).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return record


# --- the record -------------------------------------------------------------------------------------------

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
    width, height, probes = record["frame"]["width"], record["frame"]["height"], len(record["probes"])
    for r in record["defects"]:
        s = r["screen"]
        if r["sees"] == "error":
            ok = not r["recordFields"] and s is None and bool(r.get("error")) \
                and r["probesRecordChanged"] == 0 and r["probesScreenChanged"] == 0
        else:
            ok = r["sees"] == _sees(r["recordFields"], s) and "error" not in r
        if not ok:
            out.append(f"repro-screen: {r['id']}: {r['sees']!r} does not follow from its row")
        if (r["probesRecordChanged"] > 0) != bool(r["recordFields"]) or (r["probesScreenChanged"] > 0) != bool(s) \
                or max(r["probesRecordChanged"], r["probesScreenChanged"]) > probes:
            out.append(f"repro-screen: {r['id']}: the probe counts do not agree with its row")
        if s is None:
            continue
        left, top, right, bottom = s["box"]
        if s["probe"] not in record["probes"] or s["frames"] > s["of"] or s["firstFrame"] >= s["of"] \
                or s["atFrame"] >= s["of"] or s["atFrame"] < s["firstFrame"] \
                or s["examined"] > min(s["frames"], record["maxFramesExamined"]) \
                or not (left < right <= width and top < bottom <= height) \
                or s["pixels"] > (right - left) * (bottom - top):
            out.append(f"repro-screen: {r['id']}: the screen difference does not agree with itself")
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
    return visibility.stale(record, doc, root, bench_path)


def render(record: dict, doc: dict | None = None) -> str:
    """The record as a table. With the bench, each row also gets its family and what its author expected."""
    t = record["totals"]
    meta = {d["id"]: d for d in doc["defects"]} if doc else {}
    f = record["frame"]
    lines = [f"{t['defects']} defects, {len(record['probes'])} probes, {record['engine']}, frames of "
             f"{f['width']} x {f['height']}, no model. The record and the screen both differ: "
             f"{t['record-and-screen']}. Only the screen differs: {t['screen-only']}. Only the record differs: "
             f"{t['record-only']}. Nothing differs on any probe: {t['neither']}."
             + (f" Could not be measured: {t['error']}." if t["error"] else "")
             + (f" Replays made again after the engine failed: {record['engineRetries']}." if record["engineRetries"] else ""),
             "",
             "| Defect | Family | Author expected | Measured | Record fields that differ (probes) "
             "| On the screen: the probe where most frames differ | Frames that differ | Most pixels in one frame "
             "| Where (left, top, right, bottom) |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in record["defects"]:
        m = meta.get(r["id"], {})
        s = r["screen"]
        fields = (", ".join(f"`{x}`" for x in r["recordFields"]) + f" ({r['probesRecordChanged']})") \
            if r["recordFields"] else "none"
        if s:
            cells = [f"`{s['probe']}` (of {r['probesScreenChanged']})",
                     f"{s['frames']} of {s['of']}, from frame {s['firstFrame']}",
                     f"{s['pixels']} (frame {s['atFrame']})", ", ".join(str(v) for v in s["box"])]
        else:
            cells = ["none", "", "", ""]
        lines.append(f"| `{r['id']}` | {m.get('family', '')} | {m.get('authorExpects', '')} | {r['sees']} | {fields} | "
                     + " | ".join(cells) + " |")
    if record["unstable"]:
        lines += ["", "Unstable between two replays of the clean game, and so not counted: "
                  + "; ".join(f"`{u['probe']}` ({u['frames']} frames" + (", " + ", ".join(u["fields"]) if u["fields"] else "")
                              + ")" for u in record["unstable"]) + "."]
    return "\n".join(lines) + "\n"
