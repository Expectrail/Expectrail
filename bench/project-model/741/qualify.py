"""Reproduce both required authoring checks on the dedicated public Godot fixture."""

import argparse
import json
import os
import shutil
from pathlib import Path

from expectrail.contracts import canonical_v1, strict_loads
from expectrail.gate import record, verify
from expectrail.project_config import read_game
from expectrail.project_model import ModelError, draft_pair, read_model
from expectrail.project_model_godot import author, reference_identity
from harness.run import apply_patches, run, sha256_file, tree_digest

CASE = Path(__file__).resolve().parent
FIXTURE = CASE / "reference"
ROUTE = CASE / "out-and-back.json"
ARMS = {
    "clean": {"viewport": "pass", "rail": "pass", "movement": "pass"},
    "comment-only": {"viewport": "pass", "rail": "pass", "movement": "pass"},
    "off-rail-down": {"viewport": "pass", "rail": "fail", "movement": "fail"},
    "off-rail-up": {"viewport": "pass", "rail": "fail", "movement": "pass"},
    "frozen-actor": {"viewport": "pass", "rail": "pass", "movement": "fail"},
}


def measure(folder, route, specs, reference):
    raw_trace = folder / "trace.json"
    replay_path = folder / "replay.json"
    trace = strict_loads(raw_trace.read_text(encoding="utf-8"))
    replay = strict_loads(replay_path.read_text(encoding="utf-8"))
    trace_sha = sha256_file(raw_trace)
    if (replay["game"]["tree"] != reference["treeSha256"] or replay["route"]["sha256"] != reference["route"]["sha256"]
            or replay["trace"]["sha256"] != trace_sha
            or [row["tick"] for row in trace["rows"]] != list(range(route["ticks"]))):
        raise ValueError("the public proof replay differs from the pinned inputs or required tick window")
    replay_sha = sha256_file(replay_path)
    captured = {"trace": trace, "replaySha256": replay_sha, "engineObservations": verify.observations(trace, replay_sha)}
    verdicts = {}
    for name, spec in specs.items():
        judged = verify.judge_run(spec, captured, ticks=route["ticks"], route=route["name"],
                                  capture_fps=reference["capture"]["framesPerSecond"], rule=record.ENGINE_ONLY)
        verdicts[name] = judged["verdict"]
        if (not verdicts[name] or not verdicts[name]["coverage"]["completeWindow"]
                or verdicts[name]["framesJudged"] != route["ticks"]):
            raise ValueError(f"{name} did not judge the complete public control")
    boxes = [obj["worldBox"] for row in trace["rows"] for obj in row["roleObjects"] if obj["role"] == "player"]
    return {"traceSha256": trace_sha, "viewport": trace["viewport"], "firstActorBox": boxes[0],
            "actorX": [row["player"][0] for row in trace["rows"]], "verdicts": verdicts,
            "isolation": replay.get("isolation")}


def needs_review(path, mismatched_identity):
    try:
        read_model(path, mismatched_identity)
    except ModelError as exc:
        return str(exc)
    raise ValueError("a changed authoring input reused the reference artifact")


def qualify(godot, out):
    out.mkdir(parents=True, exist_ok=False)
    os.environ.setdefault("EXPECTRAIL_GODOT_CACHE", str(out / "cache"))
    route = strict_loads(ROUTE.read_text(encoding="utf-8"))
    config = read_game(FIXTURE)
    sources = [out / f"reference-{rep}" for rep in range(3)]
    for source in sources:
        shutil.copytree(FIXTURE, source)
    before = tree_digest(FIXTURE)
    authors = [out / f"author-{rep}" for rep in range(3)]
    first = author(sources[0], ROUTE, godot, authors[0])
    reference = first["reference"]
    paths = ("project-model.json", "checks/reference-rail.json", "checks/reference-movement.json")
    snapshot = {part: (authors[0] / part).read_bytes() for part in paths}

    candidate = out / "changed-candidate"
    shutil.copytree(FIXTURE, candidate)
    apply_patches(candidate, [CASE / "controls/off-rail-up.patch"])
    path = authors[0] / "project-model.json"
    stale_tree = reference_identity(candidate, ROUTE, route, config, reference["engine"])
    bindings = config["bindings"]
    rebound = {**config, "bindings": {**bindings, "goal": bindings["home"], "home": bindings["goal"]}}
    stale_binding = reference_identity(FIXTURE, ROUTE, route, rebound, reference["engine"])
    stale_reasons = {"candidateTree": needs_review(path, stale_tree), "binding": needs_review(path, stale_binding)}
    for source, folder in zip(sources[1:], authors[1:]):
        author(source, ROUTE, godot, folder)
        if any((folder / part).read_bytes() != content for part, content in snapshot.items()):
            raise ValueError("independent pinned derivations changed the model or drafts")

    specs = draft_pair(read_model(path, reference))
    viewport = {**specs["rail"], "id": "public-broad-viewport",
                "assertion": {**specs["rail"]["assertion"], "region": {"box": [0, 0, *config["viewport"]]}}}
    specs = {"viewport": viewport, **specs}
    summary = {"reference": reference, "modelSha256": sha256_file(authors[0] / "project-model.json"),
               "draftSha256": {part: sha256_file(authors[0] / part) for part in paths[1:]},
               "artifactDerivations": 3, "staleReference": stale_reasons, "arms": {}}
    for arm, expected in ARMS.items():
        rows = []
        for rep in range(3):
            if arm == "clean":
                directory = authors[rep] / "reference-replay"
            else:
                directory = out / f"{arm}-{rep}"
                run(ROUTE, directory, game=FIXTURE, godot=godot, fps=None, capture_frames=False,
                    project=config, patches=[CASE / "controls" / f"{arm}.patch"])
            row = measure(directory, route, specs, reference)
            results = {k: v["result"] for k, v in row["verdicts"].items()}
            if results != expected:
                raise ValueError(f"{arm} repetition {rep + 1}: expected {expected}, got {results}")
            rows.append(row)
            print(arm, rep + 1, results, flush=True)
        summary["arms"][arm] = rows
    if (before != tree_digest(FIXTURE) or sha256_file(ROUTE) != reference["route"]["sha256"]
            or any((authors[0] / part).read_bytes() != content for part, content in snapshot.items())):
        raise ValueError("candidate evaluation changed the reference, route or frozen authoring bytes")
    (out / "qualification.json").write_bytes(canonical_v1(summary))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    qualify(args.godot, args.out.resolve())
