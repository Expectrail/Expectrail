"""Local engine-only measurement for #531; no ingestion, fixer, model or gate decision."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile

from expectrail.route import input_map, read_trace
from harness import tree
from harness.run import apply_patches, run
from .producer import FALL, anomalies, play, point, write_json

REPO = Path(__file__).resolve().parents[2]


def build_commit(base: str, patch: Path | None) -> str:
    """Name the exact patched base with a local commit, without changing the real index or game.

    Fixed identity/date make these commits reconstructible by the architect. Nothing is pushed.
    """
    if patch is None:
        return base
    with tempfile.TemporaryDirectory(prefix="expectrail-playtest-index-") as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index"),
               "GIT_AUTHOR_NAME": "Expectrail", "GIT_AUTHOR_EMAIL": "expectrail@example.invalid",
               "GIT_COMMITTER_NAME": "Expectrail", "GIT_COMMITTER_EMAIL": "expectrail@example.invalid",
               "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
               "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00"}

        def git(*args, data=None):
            return subprocess.run(["git", *args], cwd=REPO, env=env, input=data,
                                  capture_output=True, text=True, check=True).stdout.strip()

        git("read-tree", base)
        git("apply", "--cached", "--directory=game/platformer", str(patch.resolve()))
        root = git("write-tree")
        return git("commit-tree", root, "-p", base,
                   data=f"Expectrail playtest build: {patch.name}\n")


def replay_result(report: dict, trace: dict) -> dict:
    """Measure the stated observation at its tick, and independently measure the Player anchor.

    This deliberately knows only this producer's three worded observations. It does not interpret
    arbitrary report text and cannot select checks or produce a verification verdict.
    """
    fault, rows = report["fault"], trace["rows"]
    tick, anchor = fault["preFaultTick"], fault["anchor"]
    at = point(rows[tick]) if 0 <= tick < len(rows) else None
    reached = (anchor["object"] == "Player" and at is not None
               and math.dist(at, [anchor["x"], anchor["y"]]) <= anchor["tolerancePx"])
    reproduced = any(f["bug"] == report["bug"] and f["fault"]["faultTick"] == fault["faultTick"]
                     for f in anomalies(report["route"], trace))
    return {"anchorReached": reached, "anomalyReproduced": reproduced}


def verify_build(project: Path, commit: str) -> None:
    """Compare only the bundled game's committed blobs to the actual replay input, including extras."""
    listing = subprocess.check_output(
        ["git", "ls-tree", "-rz", f"{commit}:game/platformer"], cwd=REPO)
    expected = {}
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        header, name = entry.split(b"\t", 1)
        mode, kind, oid = header.split()
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise ValueError("this bundled-game experiment requires plain committed files")
        expected[name.decode()] = oid.decode()
    actual = {}
    for name, path in tree.files(project, skip=tree.GODOT_SKIP):
        data = path.read_bytes()
        actual[name] = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if actual != expected:
        raise ValueError("project bytes do not match the target commit's bundled game")


def filter_result(attempts: list[dict]) -> str:
    if len(attempts) != 3:
        return "incomplete"
    if not all(a["anchorReached"] for a in attempts):
        return "anchor-desync"
    return "reproduced" if all(a["anomalyReproduced"] for a in attempts) else "not-reproduced"


def experiment(out: Path, seeds: int, ticks: int, godot: Path | None):
    if out.exists():
        raise ValueError(f"output already exists: {out}")
    if not 1 <= seeds <= 100:
        raise ValueError("seeds must be from 1 to 100")
    # Bound ticks before creating output or build commits.
    from .producer import make_route
    make_route(["move_right"], 0, ticks)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    clean = REPO / "game/platformer"
    if subprocess.check_output(["git", "diff", base, "--", "game/platformer"], cwd=REPO):
        raise ValueError("bundled game differs from HEAD")
    out.mkdir(parents=True)
    builds, entries = [], []
    patches = [None, *sorted((REPO / "bugs/reported").glob("*.patch"))]
    for patch in patches:
        name = patch.stem if patch else "clean"
        commit = build_commit(base, patch)
        project = out / "builds" / name / "game"
        project.parent.mkdir(parents=True)
        tree.copy(clean, project, skip=tree.GODOT_SKIP)
        if patch:
            apply_patches(project, [patch])
        verify_build(project, commit)
        record = {"build": name, "commit": commit, "patch": str(patch.relative_to(REPO)) if patch else None,
                  "patchSha256": hashlib.sha256(patch.read_bytes()).hexdigest() if patch else None,
                  "seeds": seeds, "reports": 0}
        for seed in range(seeds):
            folder = out / "discovery" / name / str(seed)
            docs = play(project, commit, seed, folder, ticks=ticks, godot=godot)
            # Re-reading the same actual trace must produce exactly the same report bytes.
            from .producer import reports
            trace = json.loads((folder / "replay/trace.json").read_text())
            assert docs == reports(json.loads((folder / "route.json").read_text()), trace, commit)
            record["reports"] += len(docs)
            for doc in docs:
                entries.append((name, "producer", doc, project))
            print(f"{name} seed {seed}: {len(docs)} report(s)", flush=True)
        builds.append(record)
        write_json(out / "builds.json", builds)

    # Two hand-written false reports. One claims falling on an idle clean route; the other
    # retains a real symptom and route but displaces only the anchor by 10,000 world pixels.
    route = {"format": "expectrail.route/v0", "name": "false-idle", "seed": 0,
             "ticks": 240, "events": []}
    path = out / "false-idle-route.json"
    write_json(path, route)
    clean_project = out / "builds/clean/game"
    run(path, out / "false-idle-source", game=clean_project, godot=godot, capture_frames=False)
    _, rate, _ = input_map(clean_project)
    trace = read_trace(out / "false-idle-source/trace.json", 240, rate)
    position = point(trace["rows"][99])
    if position is None:
        raise ValueError("no player at the hand-written report's anchor")
    idle = {"format": "expectrail.playtest-report/v1", "id": "false-idle-fall",
            "producer": {"name": "Expectrail", "version": "manual-1"}, "target": {"commit": base},
            "route": route, "bug": FALL, "fault": {"preFaultTick": 99, "faultTick": 100,
                "anchor": {"object": "Player", "x": position[0], "y": position[1], "tolerancePx": 2}}}
    wrong = copy.deepcopy(entries[0][2] if entries else idle)
    wrong.update(id="false-wrong-anchor", producer={"name": "Expectrail", "version": "manual-1"})
    wrong["fault"]["anchor"]["x"] += 10000
    wrong_build, wrong_project = (entries[0][0], entries[0][3]) if entries else ("clean", clean_project)
    entries.extend([("clean", "manual-no-anomaly", idle, clean_project),
                    (wrong_build, "manual-wrong-anchor", wrong, wrong_project)])

    measured = []
    for build, kind, report, project in entries:
        folder = out / "filter" / report["id"]
        write_json(folder / "report.json", report)
        write_json(folder / "route.json", report["route"])
        _, rate, _ = input_map(project)
        attempts = []
        traces = []
        for n in range(1, 4):
            dest = folder / str(n)
            run(folder / "route.json", dest, game=project, godot=godot, capture_frames=False)
            trace = read_trace(dest / "trace.json", report["route"]["ticks"], rate)
            traces.append(trace)
            attempts.append(replay_result(report, trace))
        row = {"id": report["id"], "build": build, "kind": kind,
               "attempts": attempts, "result": filter_result(attempts),
               "identicalTraces": traces[0] == traces[1] == traces[2]}
        measured.append(row)
        write_json(out / "filter.json", measured)
        print(f"filter {report['id']}: {row['result']}", flush=True)
    summary = {"baseCommit": base, "seedsPerBuild": seeds, "ticksPerRoute": ticks,
               "builds": builds, "filter": measured, "modelCalls": 0, "fixerCalls": 0}
    write_json(out / "experiment.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seeds", type=int, default=4)
    parser.add_argument("--ticks", type=int, default=1200)
    parser.add_argument("--godot", type=Path)
    args = parser.parse_args(argv)
    experiment(args.out.resolve(), args.seeds, args.ticks, args.godot)


if __name__ == "__main__":
    main()
