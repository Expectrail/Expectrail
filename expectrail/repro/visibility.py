"""What each bench defect changes in the engine's record on the library probes, before any model is asked anything.

    python3 -m expectrail.repro visibility --out runs/repro-visibility      # replays the game; no model, no key
    python3 -m expectrail.repro render bench/jit/public/visibility.json

A generated check can only fail on a defect when some probe it may use reads a signal differently on
the defect build than on the clean game. So, for every defect of the public bench, this replays every
probe (expectrail/jit/probes.py) on the clean game and on the defect build and sorts the defect into:

- **signal**: a trace signal (expectrail/trace/signals.py) reads differently on at least one probe.
  Reproduction may be possible with today's probes and signals; whether the model proposes the check
  is a different question, answered only by a live run. Any difference counts, however small, so the
  record keeps each signal's largest move for a reader to judge: a hundredth of a pixel is a side
  effect, not a symptom.
- **trace-only**: the engine's record differs on some probe, and no signal does. The route reaches
  the behaviour and the harness logs it; the closed language has no signal for it.
- **none**: the record is the same on every probe. Either no probe reaches the behaviour, or the
  defect only shows on screen. This measurement cannot tell the two apart.

This says what the library probes can see and is never a reproduction rate. The model may also
propose up to four probes of its own for a change, which this does not replay. The clean game is replayed twice;
a field or signal that differs between those two replays is unstable on that probe and is not
counted for any defect. Each defect build is replayed once.
"""
from __future__ import annotations

import json
import shutil
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from expectrail.contracts import ContractError, strict_loads
from expectrail.repro import bench
from expectrail.trace.signals import SIGNALS

REPO = bench.REPO
SCHEMA = REPO / "contracts" / "repro-visibility.v1.schema.json"
RECORD = REPO / "bench" / "jit" / "public" / "visibility.json"
FORMAT = "expectrail.repro-visibility/v1"
NAME = "repro-visibility.json"
KINDS = ("signal", "trace-only", "none", "error")
NOT_FIELDS = ("tick", "frame")
MAX_BYTES = 1024 * 1024
ATTEMPTS = 3
SCRIPT_ERRORS = ("SCRIPT ERROR", "Parse Error")   # a defect must change behaviour, not stop a script loading


class VisibilityError(ValueError):
    """A visibility record cannot be used."""


def replay_build(profile: dict, probes: list[dict], patches: list[str], work: str, runner=None) -> tuple[dict, int]:
    """{probeId: {"signals": {name: number|None}, "fields": {name: [value per tick]}}} for one build, and
    how many replays had to be made again.

    The same replay the measure step makes (trace only, no frames), keeping the raw rows as well. The
    engine can crash on its own: Godot 4.7.2 ended with a segmentation fault once while this was being
    built, on one replay of one build with two builds running at once, and not again in two full
    runs. So a replay that fails is made again, at most ATTEMPTS times in all, and counted."""
    from expectrail.discovery.route_compiler import compile_route
    from expectrail.jit.measure import _clean
    from expectrail.trace.normalize import from_run_dir
    from expectrail.trace.signals import summary

    if runner is None:
        from expectrail.jit.run import _default_runner

        runner = _default_runner(None)
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
                    raise VisibilityError(f"probe {p['id']} could not be replayed in {ATTEMPTS} attempts: "
                                          f"{' '.join(str(exc).split())}"[:280]) from exc
                retries += 1
        log = run_dir / "godot.log"
        if log.is_file() and any(mark in log.read_text(encoding="utf-8", errors="replace") for mark in SCRIPT_ERRORS):
            raise VisibilityError(f"the engine logged a script error on probe {p['id']}: the patch breaks a script")
        rows = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))["rows"]
        names = sorted({k for r in rows for k in r} - set(NOT_FIELDS))
        out[p["id"]] = {"signals": _clean(summary(from_run_dir(run_dir, route, episode_id=f"visibility-{p['id']}"))),
                        "fields": {n: [r.get(n) for r in rows] for n in names}}
        shutil.rmtree(run_dir, ignore_errors=True)  # a replay copies the whole game; keep the disk small
    return out, retries


def _differs(a: dict, b: dict) -> tuple[set[str], set[str]]:
    """The trace fields and the signals that differ between two replays of one probe."""
    fields = {n for n in set(a["fields"]) | set(b["fields"]) if a["fields"].get(n) != b["fields"].get(n)}
    signals = {n for n in set(a["signals"]) | set(b["signals"]) if a["signals"].get(n) != b["signals"].get(n)}
    return fields, signals


def _size(a, b) -> float:
    """How far a signal moved; a reading that appears or disappears counts as the largest move."""
    return float("inf") if a is None or b is None else abs(a - b)


def unstable(clean_a: dict, clean_b: dict) -> dict[str, tuple[set[str], set[str]]]:
    out = {}
    for pid in clean_a:
        fields, signals = _differs(clean_a[pid], clean_b[pid])
        if fields or signals:
            out[pid] = (fields, signals)
    return out


def compare(clean: dict, defect: dict, noisy: dict[str, tuple[set[str], set[str]]]) -> dict:
    """One defect's row, less its id and digest: visibility, the signals that moved, the fields that differ."""
    signals: dict[str, dict] = {}
    fields: set[str] = set()
    changed = 0
    for pid in sorted(clean):
        f, s = _differs(clean[pid], defect[pid])
        skip_f, skip_s = noisy.get(pid, (set(), set()))
        f, s = f - skip_f, s - skip_s
        if f or s:
            changed += 1
        fields |= f
        for name in sorted(s):
            a, b = clean[pid]["signals"].get(name), defect[pid]["signals"].get(name)
            entry = signals.setdefault(name, {"probes": 0, "probe": pid, "clean": a, "defect": b})
            entry["probes"] += 1
            if _size(a, b) > _size(entry["clean"], entry["defect"]):   # keep the probe where it moved most
                entry.update(probe=pid, clean=a, defect=b)
    return {"visibility": "signal" if signals else ("trace-only" if fields else "none"),
            "signals": dict(sorted(signals.items())), "traceFields": sorted(fields), "probesChanged": changed}


def totals(rows: list[dict]) -> dict:
    return {"defects": len(rows), **{k: sum(r["visibility"] == k for r in rows) for k in KINDS}}


def _one_build(args) -> tuple[str, dict | None, str | None, int]:
    name, profile, probes, patches, work, runner = args
    try:
        data, retries = replay_build(profile, probes, patches, work, runner)
        return name, data, None, retries
    except Exception as exc:  # noqa: BLE001 - a build that cannot be replayed is a row that says so, never a guess
        return name, None, f"{type(exc).__name__}: {' '.join(str(exc).split())}"[:300], 0


def measure(doc: dict, profile: dict, probes: list[dict], out: Path, *, runner=None, jobs: int = 1,
            only: list[str] | None = None, root: Path = REPO, bench_path: Path = bench.BENCH) -> dict:
    """Replay the clean game twice and every defect build once; write ``out/repro-visibility.json``."""
    from harness.run import GODOT_VERSION

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    defects = [d for d in doc["defects"] if not only or d["id"] in only]
    builds = [("clean-a", []), ("clean-b", [])] + [(d["id"], [str(root / d["patch"])]) for d in defects]
    tasks = [(name, profile, probes, patches, str(out / "work" / name), runner) for name, patches in builds]
    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            done = list(pool.map(_one_build, tasks))
    else:
        done = [_one_build(t) for t in tasks]
    results = {name: (data, err) for name, data, err, _n in done}
    retries = sum(n for _name, _data, _err, n in done)
    for name in ("clean-a", "clean-b"):
        if results[name][0] is None:
            raise VisibilityError(f"the clean game could not be replayed: {results[name][1]}")
    clean, noisy = results["clean-a"][0], unstable(results["clean-a"][0], results["clean-b"][0])
    rows = []
    for d in defects:
        data, err = results[d["id"]]
        row = {"id": d["id"], "patchSha256": bench.sha256(root / d["patch"])}
        if data is None:
            row.update(visibility="error", signals={}, traceFields=[], probesChanged=0, error=err)
        else:
            row.update(compare(clean, data, noisy))
        rows.append(row)
    record = {"format": FORMAT, "benchSha256": bench.sha256(bench_path), "engine": f"Godot {GODOT_VERSION}",
              "probes": [p["id"] for p in probes], "replaysPerBuild": {"clean": 2, "defect": 1},
              "engineRetries": retries,
              "unstable": [{"probe": pid, "fields": sorted(f), "signals": sorted(s)} for pid, (f, s) in sorted(noisy.items())],
              "defects": rows, "totals": totals(rows)}
    found = problems(record)
    if found:
        raise VisibilityError("; ".join(found))
    (out / NAME).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return record


def problems(record) -> list[str]:
    """What is wrong with a visibility record: the schema first, then what must agree inside it."""
    import jsonschema

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(record), key=lambda e: list(e.path))
    if errors:
        return [f"repro-visibility: {'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}"[:300]
                for e in errors[:10]]
    out = []
    ids = [r["id"] for r in record["defects"]]
    if len(set(ids)) != len(ids):
        out.append("repro-visibility: a defect is listed twice")
    for r in record["defects"]:
        if r["visibility"] == "error":
            expected = "error" if not r["signals"] and not r["traceFields"] and r.get("error") else None
        else:
            expected = "signal" if r["signals"] else ("trace-only" if r["traceFields"] else "none")
            if "error" in r:
                expected = None
        if expected != r["visibility"]:
            out.append(f"repro-visibility: {r['id']}: visibility {r['visibility']!r} does not follow from its row")
        if (r["probesChanged"] > 0) != bool(r["signals"] or r["traceFields"]) or r["probesChanged"] > len(record["probes"]):
            out.append(f"repro-visibility: {r['id']}: probesChanged does not agree with its row")
        for name, s in r["signals"].items():
            if name not in SIGNALS:
                out.append(f"repro-visibility: {r['id']}: {name} is not a trace signal")
            if s["probe"] not in record["probes"] or s["probes"] > r["probesChanged"] or s["clean"] == s["defect"]:
                out.append(f"repro-visibility: {r['id']}: signal {name} does not agree with its row")
    if record["totals"] != totals(record["defects"]):
        out.append("repro-visibility: the totals do not match the rows")
    return out


def load(path: Path = RECORD) -> dict:
    raw = Path(path).read_bytes()
    if len(raw) > MAX_BYTES:
        raise VisibilityError(f"repro-visibility: over {MAX_BYTES} bytes")
    try:
        record = strict_loads(raw.decode("utf-8"))
    except (ValueError, ContractError) as exc:
        raise VisibilityError(f"repro-visibility: unreadable: {exc}"[:300]) from exc
    found = problems(record)
    if found:
        raise VisibilityError("; ".join(found))
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


def _show(v) -> str:
    return "no reading" if v is None else f"{v:g}"


def render(record: dict, doc: dict | None = None) -> str:
    """The record as a table. With the bench, each row also gets its family and what its author expected."""
    t = record["totals"]
    meta = {d["id"]: d for d in doc["defects"]} if doc else {}
    lines = [f"{t['defects']} defects, {len(record['probes'])} probes, {record['engine']}, no model. "
             f"A signal moves: {t['signal']}. The record differs and no signal does: {t['trace-only']}. "
             f"The record is the same on every probe: {t['none']}."
             + (f" Could not be replayed: {t['error']}." if t["error"] else "")
             + (f" Replays made again after the engine failed: {record['engineRetries']}." if record["engineRetries"] else ""),
             "",
             "| Defect | Family | Author expected | Measured | Signals that moved: largest move, clean to defect (probes) "
             "| Record fields that differ |",
             "| --- | --- | --- | --- | --- | --- |"]
    for r in record["defects"]:
        m = meta.get(r["id"], {})
        signals = ", ".join(f"`{n}` {_show(s['clean'])} to {_show(s['defect'])} ({s['probes']})"
                            for n, s in r["signals"].items()) or "none"
        fields = ", ".join(f"`{f}`" for f in r["traceFields"]) or "none"
        lines.append(f"| `{r['id']}` | {m.get('family', '')} | {m.get('authorExpects', '')} | {r['visibility']} | "
                     f"{signals} | {fields} |")
    if record["unstable"]:
        lines += ["", "Unstable between two replays of the clean game, and so not counted: "
                  + "; ".join(f"`{u['probe']}` ({', '.join(u['fields'] + u['signals'])})" for u in record["unstable"]) + "."]
    return "\n".join(lines) + "\n"
