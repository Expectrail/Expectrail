"""Measure before proposing: what every probe's signals read on the clean game and on the bug build.

    measure(profile, base_patches, out) -> expectrail.jit-measurements/v1

The intent model used to get the signal names and nothing else, so it guessed which signal would
show the bug. In live run 42908014398 it guessed height, under a platform that caps every jump at
the same height, and neither check it wrote could tell the bug from a fix. With the numbers in front
of it, the model can pick a probe and a signal where the build the report describes differs from
the clean game, and set a threshold between them.

What is measured and what is not:

- **clean**: the reference game (``patches=[]``).
- **bugBuild**: ``[*base]``, the build the bug report describes. A developer fixing the bug can run
  it too; it is the report's own evidence.
- **Never the candidate.** A check fitted to the candidate's numbers would "catch" it by construction.
  ``measure`` takes no candidate argument, and the record names only the base patches.

Like the replay job, this runs the game and holds no secret. What it hands to the job that holds the
key is numbers keyed by known probe and signal names, and ``load`` re-checks that shape before the
prompt is built, so nothing the game prints reaches the model as text.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
from pathlib import Path

from expectrail.discovery.route_compiler import compile_route
from expectrail.trace.normalize import from_run_dir
from expectrail.trace.signals import SIGNALS, summary

FORMAT = "expectrail.jit-measurements/v1"
NAME = "jit-measurements.json"
MAX_BYTES = 512 * 1024
MAX_ABS = 1e7


class MeasurementsUnusable(ValueError):
    """The measurements cannot be used; the proposal goes ahead without them and says why."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def base_digests(base_patches: list[Path]) -> list[str]:
    return [_sha(Path(p).read_bytes()) for p in base_patches]


def measure(profile: dict, base_patches: list[Path], out: Path, *, probes: list[dict], runner=None,
            game: Path | None = None) -> dict:
    """Replay each probe once on the clean game and once on the bug build; write ``out/jit-measurements.json``."""
    if runner is None:
        from expectrail.jit.run import _default_runner

        runner = _default_runner(game)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    work = out / "jit-measure-replays"
    builds = [("clean", [])] + ([("bugBuild", [Path(p) for p in base_patches])] if base_patches else [])
    table: dict[str, dict] = {}
    for p in probes:
        route = compile_route(p["program"], name=p["id"], description=p["description"], actions=profile["actions"])
        route_path = work / "routes" / f"{p['id']}.json"
        route_path.parent.mkdir(parents=True, exist_ok=True)
        route_path.write_text(json.dumps(route, indent=1) + "\n", encoding="utf-8")
        row: dict[str, dict | None] = {"clean": None, "bugBuild": None}
        for name, patches in builds:
            run_dir = work / name / p["id"]
            if run_dir.exists():
                shutil.rmtree(run_dir)
            runner(route_path, run_dir, patches=patches)
            row[name] = _clean(summary(from_run_dir(run_dir, route, episode_id=f"measure-{name}-{p['id']}")))
        table[p["id"]] = row
    doc = {"format": FORMAT, "basePatchSha256": base_digests(base_patches), "runsPerBuild": 1, "probes": table}
    (out / NAME).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return doc


def _clean(values: dict) -> dict:
    return {k: _number(v) for k, v in sorted(values.items()) if k in SIGNALS}


def _number(v):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > MAX_ABS:
        raise MeasurementsUnusable(f"a signal value is not a plain number: {type(v).__name__}")
    return round(float(v), 2) if isinstance(v, float) else int(v)


def load(path: Path, *, probe_ids: set[str], base_patches: list[Path]) -> dict[str, dict]:
    """{probeId: {"clean": {signal: number|None}, "bugBuild": ... | None}}, re-checked as untrusted data.

    Raises MeasurementsUnusable when the file is not exactly that shape, names a probe or a signal
    that does not exist, or was measured against different base patches than this proposal's."""
    from expectrail.contracts import ContractError, strict_loads

    raw = Path(path).read_bytes()
    if len(raw) > MAX_BYTES:
        raise MeasurementsUnusable(f"over {MAX_BYTES} bytes")
    try:
        doc = strict_loads(raw.decode("utf-8"))
    except (ValueError, ContractError) as exc:
        raise MeasurementsUnusable(f"unreadable: {exc}"[:200]) from exc
    if not isinstance(doc, dict) or set(doc) != {"format", "basePatchSha256", "runsPerBuild", "probes"} \
            or doc["format"] != FORMAT:
        raise MeasurementsUnusable("not a jit measurements record")
    if doc["basePatchSha256"] != base_digests(base_patches):
        raise MeasurementsUnusable("measured against different base patches")
    table = doc["probes"]
    if not isinstance(table, dict):
        raise MeasurementsUnusable("probes is not an object")
    out: dict[str, dict] = {}
    for pid, row in table.items():
        if pid not in probe_ids:
            raise MeasurementsUnusable(f"unknown probe {str(pid)[:60]!r}")
        if not isinstance(row, dict) or set(row) != {"clean", "bugBuild"}:
            raise MeasurementsUnusable(f"{pid}: not a clean/bugBuild row")
        clean_row = {}
        for build in ("clean", "bugBuild"):
            values = row[build]
            if values is None:
                if build == "clean" or base_patches:
                    raise MeasurementsUnusable(f"{pid}: no {build} values")
                clean_row[build] = None
                continue
            if not isinstance(values, dict) or set(values) - set(SIGNALS):
                raise MeasurementsUnusable(f"{pid}: unknown signal")
            clean_row[build] = {k: _number(v) for k, v in values.items()}
        out[pid] = clean_row
    return out
