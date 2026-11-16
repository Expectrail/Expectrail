"""Public, resumable seed measurements for #531. No models, images, fixer, or gate."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from expectrail.repro import bench as repro_bench
from expectrail.route import input_map, read_trace
from expectrail.trace.normalize import normalize
from expectrail.trace.signals import summary as signal_summary
from harness import tree
from harness.run import apply_patches, run
from .bench import build_commit, verify_build
from .producer import FALL, FACING, OFFSCREEN, STUCK, make_route, reports, write_json

REPO = Path(__file__).resolve().parents[2]
OBSERVATIONS = {FALL: "below-level", STUCK: "stopped-moving", FACING: "turning", OFFSCREEN: "offscreen"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def public_builds() -> list[dict]:
    """Strict public manifest plus the reported patches it does not already list. No other walk."""
    doc = repro_bench.load()
    builds = [{"id": "clean", "patch": None, "kind": "clean"}]
    patches = set()
    for defect in doc["defects"]:
        builds.append({"id": defect["id"], "patch": defect["patch"],
                       "kind": "defect", "report": defect["report"], "family": defect["family"]})
        patches.add(defect["patch"])
    for patch in sorted((REPO / "bugs/reported").glob("*.patch")):
        rel = patch.relative_to(REPO).as_posix()
        if rel not in patches:
            # The reported manifest explicitly labels this as reapplying an upstream fix.
            builds.append({"id": patch.stem, "patch": rel, "kind": "upstream-fix"})
    return builds


def prepare_build(root: Path, build: dict, base: str) -> dict:
    project = root / "builds" / build["id"] / "game"
    patch = REPO / build["patch"] if build["patch"] else None
    commit = build_commit(base, patch)
    if not project.exists():
        project.parent.mkdir(parents=True, exist_ok=True)
        tree.copy(REPO / "game/platformer", project, skip=tree.GODOT_SKIP)
        if patch:
            apply_patches(project, [patch])
    verify_build(project, commit)
    record = {**build, "commit": commit,
              "patchSha256": digest(patch.read_bytes()) if patch else None}
    write_json(project.parent / "build.json", record)
    return record


def trace_summary(route: dict, trace: dict) -> dict:
    """Same record-vs-signal distinction as repro.visibility, without numpy or PIL."""
    fields = sorted({k for row in trace["rows"] for k in row} - {"tick", "frame"})
    return {"fields": {key: digest(json.dumps([r.get(key) for r in trace["rows"]],
                    sort_keys=True, allow_nan=False, separators=(",", ":")).encode()) for key in fields},
            "signals": signal_summary(normalize(trace, route, episode_id="playtester-scale"))}


def _batch(task: tuple) -> dict:
    root_s, build, seeds, godot_s, ticks, *options = task
    viewport = options[0] if options else None
    root, godot = Path(root_s), Path(godot_s)
    project = root / "builds" / build["id"] / "game"
    # Caches are separate per build. A cache's key is constant throughout all its seed batches.
    os.environ["EXPECTRAIL_GODOT_CACHE"] = str(root / "caches" / build["id"])
    runtime = root / "runtime" / str(os.getpid())
    for key, name in (("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache"), ("XDG_CONFIG_HOME", "config")):
        folder = runtime / name
        folder.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(folder)
    actions, rate, _ = input_map(project)
    count, failures = 0, 0
    for seed in seeds:
        dest = root / "runs" / build["id"] / str(seed)
        record_path = dest / "measurement.json"
        if record_path.exists():
            old = json.loads(record_path.read_text())
            if old["commit"] != build["commit"] or old["ticks"] != ticks:
                raise ValueError("existing measurement belongs to a different experiment")
            if viewport is not None and "offscreen" not in old.get("reportsByPolicy", {}):
                raise ValueError("existing measurement has no offscreen policy result")
            count += 1
            continue
        route = make_route(actions, seed, ticks)
        route_path = root / "routes" / f"{seed}.json"
        if route_path.exists():
            if json.loads(route_path.read_text()) != route:
                raise ValueError("the seed route changed")
        else:
            write_json(route_path, route)
        scratch = root / "scratch" / build["id"] / str(seed)
        started = time.monotonic()
        attempts = []
        for attempt in range(1, 4):
            try:
                replay = run(route_path, scratch, game=project, godot=godot, capture_frames=False)
                log = (scratch / "godot.log").read_text(errors="replace")
                if any(mark in log for mark in ("SCRIPT ERROR", "Parse Error")):
                    raise ValueError("Godot reported a script error")
                trace = read_trace(scratch / "trace.json", ticks, rate)
                if trace.get("unknownActions"):
                    raise ValueError("unknown route action")
                break
            except (Exception, SystemExit) as exc:
                attempts.append({"attempt": attempt, "error": str(exc)[:500]})
                if (scratch / "godot.log").exists():
                    dest.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(scratch / "godot.log", dest / f"failed-{attempt}.log")
        else:
            write_json(dest / "error.json", {"seed": seed, "build": build["id"], "attempts": attempts})
            failures += 1
            print(f"ERROR {build['id']} seed {seed}", flush=True)
            continue
        documents = reports(route, trace, build["commit"])
        policies = {"original": documents}
        if viewport is not None:
            policies["offscreen"] = reports(route, trace, build["commit"], viewport=viewport)
        dest.mkdir(parents=True, exist_ok=True)
        raw = (scratch / "trace.json").read_bytes()
        with gzip.open(dest / "trace.json.gz", "wb", compresslevel=1) as stream:
            stream.write(raw)
        shutil.copyfile(scratch / "replay.json", dest / "replay.json")
        shutil.copyfile(scratch / "godot.log", dest / "godot.log")
        for policy, policy_documents in policies.items():
            report_folder = "reports" if policy == "original" else f"reports-{policy}"
            for report in policy_documents:
                write_json(dest / report_folder / f"{report['id']}.json", report)
        report_summaries = {policy: [{"id": r["id"], "observation": OBSERVATIONS[r["bug"]],
                                      "fault": r["fault"]} for r in docs]
                            for policy, docs in policies.items()}
        measured = {"build": build["id"], "commit": build["commit"], "seed": seed, "ticks": ticks,
                    "traceSha256": digest(raw), "engine": replay["engine"], "isolation": replay["isolation"],
                    "reports": report_summaries["original"], "reportsByPolicy": report_summaries,
                    **trace_summary(route, trace), "failedAttempts": attempts,
                    "elapsedSeconds": round(time.monotonic() - started, 4)}
        write_json(record_path, measured)
        shutil.rmtree(scratch)
        count += 1
        if count % 20 == 0 or count == len(seeds):
            totals = ", ".join(f"{name}={len(docs)}" for name, docs in policies.items())
            print(f"{build['id']}: {count}/{len(seeds)} in batch; seed {seed}; reports {totals}", flush=True)
    return {"build": build["id"], "completed": count, "failed": failures}


def measure(root: Path, *, start: int, count: int, godot: Path, ticks: int = 1200,
            jobs: int = 4, only: str = "all", viewport=None) -> dict:
    if not (count >= 1 and start >= 0 and start + count <= 2**32 and 1 <= ticks <= 1800 and jobs >= 1):
        raise ValueError("invalid bounded seed range, ticks or jobs")
    if viewport is not None:
        from .offscreen import viewport_size
        viewport = list(viewport_size(viewport))
    root.mkdir(parents=True, exist_ok=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    seeds = list(range(start, start + count))
    builds = public_builds()
    manifest = {"baseCommit": base, "startSeed": start, "seedsPerBuild": count, "ticks": ticks,
                "producerSha256": digest((Path(__file__).parent / "producer.py").read_bytes()),
                "godot": str(godot), "godotVersion": subprocess.check_output([str(godot), "--version"], text=True).strip(),
                "builds": builds, "jobs": jobs, "viewport": viewport}
    manifest_path = root / "plan.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        for key in ("baseCommit", "startSeed", "seedsPerBuild", "ticks", "producerSha256", "godotVersion", "viewport"):
            if previous.get(key) != manifest[key]:
                raise ValueError(f"existing plan differs: {key}")
    else:
        write_json(manifest_path, manifest)
    clean = prepare_build(root, builds[0], base)
    results = []
    # Finish all clean seeds before starting any defect build. All seed ranges are disjoint batches.
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        chunks = [seeds[i::jobs] for i in range(jobs) if seeds[i::jobs]]
        futures = [pool.submit(_batch, (str(root), clean, chunk, str(godot), ticks, viewport)) for chunk in chunks]
        for future in as_completed(futures):
            results.append(future.result())
    write_json(root / "clean-completed.json", results)
    if sum(r["completed"] for r in results) != count or any(r["failed"] for r in results):
        raise ValueError("clean measurement incomplete; no defect run started")
    if only == "clean":
        return {"results": results}
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        futures = []
        for item in builds[1:]:
            built = prepare_build(root, item, base)
            futures.append(pool.submit(_batch, (str(root), built, seeds, str(godot), ticks, viewport)))
        for future in as_completed(futures):
            results.append(future.result())
            write_json(root / "completed.json", results)
    if any(r["failed"] or r["completed"] != count for r in results if r["build"] != "clean"):
        raise ValueError("defect measurement incomplete")
    return {"results": results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--ticks", type=int, default=1200)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--godot", type=Path, required=True)
    parser.add_argument("--only", choices=("clean", "all"), default="all")
    parser.add_argument("--viewport", type=int, nargs=2, metavar=("WIDTH", "HEIGHT"),
                        help="also measure the offscreen policy on each same trace")
    args = parser.parse_args(argv)
    measure(args.out.resolve(), start=args.start, count=args.count, godot=args.godot.resolve(),
            ticks=args.ticks, jobs=args.jobs, only=args.only, viewport=args.viewport)


if __name__ == "__main__":
    main()
