"""Measure the mirror-inputs metamorphic checks (#675, piece 3) on the bundled game and the public bugs.

Every probe in the generator's library that uses a left/right action gets its mirrored twin and one check per
signal (expectrail/jit/metamorphic.py). Twin pairs that are the same two routes are measured once. Each
route is replayed:

- on the clean game, three times (``assess.REPS``): a check must pass all three to be usable;
- on the do-nothing control for the player (expectrail/jit/do_nothing.py), three times: a check that
  passes all three states no obligation and would be dropped;
- on each public bench defect (``bench.public_cases()``), once. The engine replays a route the same way
  every time on one build (the clean runs show it), so one run per defect is recorded and said to be one.

Judged with the generator's own evaluation (``run._evaluate``). No model is called and nothing is spent
beyond the local engine. Public bugs only: a held-out or ``fresh-*`` path is refused.

    python3 tools/metamorphic_public.py --work NEW_FOLDER --out docs/measurements/675-metamorphic-mirror.md

``--resume`` reads replays already saved in the work folder (same route file, same patch, trace digest
as recorded) instead of running them again, so a change to the evaluation alone is judged again cheaply.

Advisory: this changes no record and no rule.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from expectrail.jit import assess, bench, do_nothing, metamorphic  # noqa: E402


def checks(profile: dict) -> tuple[list[dict], dict[str, dict], list[dict]]:
    """(pairs, routes by probe id, probes with no mirror). A pair: {left, right, entries}."""
    from expectrail.discovery.route_compiler import compile_route
    from expectrail.jit.probes import jit_library

    routes, pairs, skipped, seen = {}, [], [], set()
    for probe in jit_library(profile["actions"]):
        d = metamorphic.derive(probe, profile["actions"])
        if d["mirror"] is None:
            skipped.append({"probe": probe["id"], "reason": d["reason"]})
            continue
        key = frozenset((_program(probe), _program(d["mirror"])))
        if key in seen:
            skipped.append({"probe": probe["id"], "reason": "the same two programs as a pair already measured"})
            continue
        seen.add(key)
        for p in (probe, d["mirror"]):
            routes[p["id"]] = compile_route(p["program"], name=p["id"], description=p["description"],
                                            actions=profile["actions"])
        pairs.append({"left": probe["id"], "right": d["mirror"]["id"], "entries": d["entries"]})
    return pairs, routes, skipped


def _program(probe: dict) -> str:
    return hashlib.sha256(json.dumps(probe["program"], sort_keys=True).encode()).hexdigest()


def builds(game: Path, profile: dict, work: Path) -> list[dict]:
    out = [{"id": "clean", "kind": "clean", "patches": [], "reps": assess.REPS, "mode": None}]
    control = next(c for c in do_nothing.controls(game, profile, ["player"]) if c["class"] == "player")
    if control["patchText"]:
        path = work / "do-nothing-player.patch"
        path.write_text(control["patchText"])
        out.append({"id": "do-nothing", "kind": "control", "patches": [path], "reps": assess.REPS,
                    "mode": control["mode"], "patchSha256": hashlib.sha256(control["patchText"].encode()).hexdigest()})
    for d in bench.public_cases()["defects"]:
        patch = REPO / d["patch"]
        if bench.private_name(Path(d["patch"])) or bench.private_name(patch.resolve()):
            raise ValueError(f"public-only: {d['patch']} refused")
        out.append({"id": d["id"], "kind": "defect", "family": d["family"], "patches": [patch], "reps": 1,
                    "mode": None})
    return out


def _saved(out: Path, route_file: Path, patches: list) -> dict | None:
    """The record of a replay already in ``out``, when it is of this route on this build; else None."""
    try:
        rec = json.loads((out / "replay.json").read_text())
    except (OSError, ValueError):
        return None
    want = hashlib.sha256(Path(patches[0]).read_bytes()).hexdigest() if len(patches) == 1 else None
    same_route = rec.get("route", {}).get("sha256") == hashlib.sha256(route_file.read_bytes()).hexdigest()
    same_build = (rec.get("game") or {}).get("patchSha256") == want if patches else not (rec.get("game") or {}).get("patch")
    trace_ok = (out / "trace.json").is_file() and rec.get("trace", {}).get("sha256") == \
        hashlib.sha256((out / "trace.json").read_bytes()).hexdigest()
    return rec if same_route and same_build and trace_ok else None


def replay_all(work: Path, game: Path, routes: dict, plan: list[dict], runner=None, workers: int = 2,
               resume: bool = False, sandbox: str | None = None) -> dict:
    """{(build, probe): [episode, ...] or None}: None when a run failed or the runs' traces differed. With
    ``resume``, a replay already saved in the work folder for the same route and build is read, not run.
    ``sandbox`` goes to the harness as is (``require`` for a game the team did not write)."""
    from expectrail.trace.normalize import from_run_dir
    from harness.run import run

    run = runner or run
    route_files = {}
    for pid, route in routes.items():
        path = work / "routes" / f"{pid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(route, indent=1) + "\n")
        route_files[pid] = path

    def one(job):
        b, pid = job
        eps, traces = [], []
        for rep in range(b["reps"]):
            out = work / "replays" / b["id"] / f"{pid}-{rep + 1}"
            try:
                rec = _saved(out, route_files[pid], b["patches"]) if resume else None
                if rec is None:
                    if out.exists():
                        shutil.rmtree(out)
                    rec = run(route_files[pid], out, game=game, patches=b["patches"], capture_frames=False,
                              ui_integers=False, **({"sandbox": sandbox} if sandbox else {}))
                traces.append(hashlib.sha256((out / "trace.json").read_bytes()).hexdigest())
                eps.append(from_run_dir(out, routes[pid], episode_id=f"{b['id']}-{pid}-{rep}"))
                engine = (rec.get("engine") or {}).get("version")
            except Exception as exc:  # noqa: BLE001 - recorded; the checks on this route are not run
                return (b["id"], pid), None, {"error": " ".join(str(exc).split())[:300]}
        stable = len(set(traces)) == 1
        return (b["id"], pid), (eps if stable else None), {"traces": traces, "engine": engine}

    jobs = [(b, pid) for b in plan for pid in sorted(routes)]
    episodes, evidence = {}, {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for key, eps, ev in pool.map(one, jobs):
            episodes[key], evidence[f"{key[0]}/{key[1]}"] = eps, ev
    return {"episodes": episodes, "evidence": evidence}


def judge(pairs: list[dict], plan: list[dict], episodes: dict) -> list[dict]:
    from expectrail.jit.run import _evaluate

    rows = []
    for pair in pairs:
        ids = [pair["left"], pair["right"]]
        for entry in pair["entries"]:
            row = {"check": entry["spec"]["id"], "left": ids[0], "right": ids[1],
                   "signal": entry["spec"]["operation"]["signal"], "runs": {}, "reasons": {}}
            for b in plan:
                left, right = episodes.get((b["id"], ids[0])), episodes.get((b["id"], ids[1]))
                if left is None or right is None:
                    row["runs"][b["id"]] = []
                    row["reasons"][b["id"]] = "a replay failed or its runs differed"
                    continue
                runs = []
                for rep in range(b["reps"]):
                    eps = {ids[0]: left[rep], ids[1]: right[rep]}
                    if b["kind"] == "control":
                        outcome, why = do_nothing.judge(entry, ids, eps, _evaluate, b["mode"])
                        if why:
                            row["reasons"][b["id"]] = why
                    else:
                        outcome = _evaluate(entry, ids, eps)
                    runs.append(outcome)
                row["runs"][b["id"]] = runs
            clean = row["runs"].get("clean", [])
            row["usable"] = assess.all_of(clean, "pass", assess.REPS)
            row["control"] = assess.do_nothing(row["runs"].get("do-nothing", []))
            row["kept"] = row["usable"] and row["control"] != "passes"
            row["catches"] = sorted(b["id"] for b in plan if b["kind"] == "defect"
                                    and row["runs"].get(b["id"]) == ["fail"])
            rows.append(row)
    return rows


def measure(work: Path, game: Path = REPO / "game/platformer", runner=None, workers: int = 2,
            resume: bool = False) -> dict:
    work = Path(work)
    work.mkdir(parents=True, exist_ok=resume)
    profile = json.loads((REPO / "discovery/platformer.profile.json").read_text())
    pairs, routes, skipped = checks(profile)
    plan = builds(game, profile, work)
    replays = replay_all(work, game, routes, plan, runner=runner, workers=workers, resume=resume)
    rows = judge(pairs, plan, replays["episodes"])
    doc = {"pairs": [{k: p[k] for k in ("left", "right")} for p in pairs], "skipped": skipped,
           "builds": [{k: b.get(k) for k in ("id", "kind", "family", "reps", "mode", "patchSha256")} |
                      {"patches": [str(Path(p).relative_to(REPO)) if Path(p).is_relative_to(REPO) else Path(p).name
                                   for p in b["patches"]]} for b in plan],
           "evidence": replays["evidence"], "rows": rows}
    (work / "rows.json").write_text(json.dumps(doc, indent=1) + "\n")
    return doc


def summary(doc: dict) -> dict:
    rows = doc["rows"]
    defects = [b["id"] for b in doc["builds"] if b["kind"] == "defect"]
    kept = [r for r in rows if r["kept"]]
    caught = {d: sorted(r["check"] for r in kept if d in r["catches"]) for d in defects}
    outcome = lambda r, b: ",".join(sorted(set(r["runs"].get(b, [])))) or "not-run"  # noqa: E731
    return {"pairs": len(doc["pairs"]), "checks": len(rows),
            "cleanPass": sum(r["usable"] for r in rows),
            "cleanOutcomes": _count(outcome(r, "clean") for r in rows),
            "controlOutcomes": _count(r["control"] for r in rows if r["usable"]),
            "kept": len(kept),
            "defectsCaught": sorted(d for d, c in caught.items() if c),
            "caughtBy": {d: c for d, c in caught.items() if c},
            "defects": len(defects)}


def _count(values) -> dict:
    out: dict = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items()))


def markdown(doc: dict, engine: str) -> str:
    s = summary(doc)
    defects = [b for b in doc["builds"] if b["kind"] == "defect"]
    lines = ["# Mirror-inputs metamorphic checks on the bundled game and the public bugs (#675, piece 3)", "",
             "Each library probe that uses a left/right action was paired with its mirror (left and right swapped), "
             "and one check per signal was made from the pair (`expectrail/jit/metamorphic.py`). Each route was "
             "replayed three times on the clean game, three times on the player's do-nothing control, and once on "
             "each public bench defect, and judged by the generator's own evaluation. No model was called. "
             "Advisory: the generator does not offer these checks yet, and no record or counting rule changed.", "",
             f"Engine: {engine}. Produced by `python3 tools/metamorphic_public.py`.", "",
             "## Counts", "",
             f"- Pairs: {s['pairs']} (twin pairs that are the same two routes measured once). Checks: {s['checks']}.",
             f"- Clean game, outcomes over the three runs: {_fmt(s['cleanOutcomes'])}. "
             f"**{s['cleanPass']} pass 3 of 3** and are usable.",
             f"- Of those, on the do-nothing control: {_fmt(s['controlOutcomes'])}. "
             f"**{s['kept']} are kept** (usable, and not passing the control).",
             f"- Public defects with at least one kept check failing on them: **{len(s['defectsCaught'])} of "
             f"{s['defects']}**{': ' + ', '.join(f'`{d}`' for d in s['defectsCaught']) if s['defectsCaught'] else ''}.",
             "", "## Per check", "",
             "| Check | Pair | Clean (3) | Do-nothing (3) | Kept | Fails on (one run each) |",
             "| --- | --- | --- | --- | --- | --- |"]
    for r in doc["rows"]:
        fails = [b["id"] for b in defects if r["runs"].get(b["id"]) == ["fail"]]
        lines.append(f"| `{r['check']}` | {r['left']} / {r['right']} | {', '.join(r['runs'].get('clean', [])) or '-'} | "
                     f"{', '.join(r['runs'].get('do-nothing', [])) or '-'} | {'yes' if r['kept'] else 'no'} | "
                     f"{', '.join(fails) or '-'} |")
    lines += ["", "## Per defect", "", "| Public defect | Family | Kept checks failing | Outcomes of kept checks |",
              "| --- | --- | --- | --- |"]
    kept = [r for r in doc["rows"] if r["kept"]]
    for b in defects:
        outs = _count(o for r in kept for o in r["runs"].get(b["id"], []) or ["not-run"])
        lines.append(f"| {b['id']} | {b['family']} | {len(s['caughtBy'].get(b['id'], []))} | {_fmt(outs) or '-'} |")
    lines += ["", "## Probes with no mirror", ""]
    lines += [f"- `{k['probe']}`: {k['reason']}" for k in doc["skipped"]]
    return "\n".join(lines) + "\n"


def _fmt(counts: dict) -> str:
    return ", ".join(f"{v} {k}" for k, v in counts.items())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--work", type=Path, required=True, help="a new folder for routes, replays and rows.json")
    ap.add_argument("--out", type=Path, required=True, help="the markdown measurement to write")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--resume", action="store_true",
                    help="read the replays already saved in --work for the same route and build instead of running them")
    args = ap.parse_args(argv)
    doc = measure(args.work, workers=args.workers, resume=args.resume)
    engines = sorted({str(e.get("engine")) for e in doc["evidence"].values() if e.get("engine")})
    args.out.write_text(markdown(doc, ", ".join(engines) or "no completed replay"))
    print(json.dumps(summary(doc)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
