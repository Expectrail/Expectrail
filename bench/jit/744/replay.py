"""Qualify the public draft exact-score check on five builds, three replays each."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from expectrail.contracts import load, load_strict, validate
from expectrail.discovery.route_compiler import compile_route
from expectrail.evaluator import evaluate
from expectrail.gate import verify
from expectrail.jit import do_nothing, offer
from harness.run import run, tree_digest

ROOT = Path(__file__).resolve().parents[3]
GAME = ROOT / "game/platformer"
DRAFT = ROOT / "specs/drafts/727/exact-score"
NAME = "hold-right-then-toggle-pause"
LABEL = "InterfaceLayer/PauseMenu/ColorRect/CoinsCounter/Label"
TICKS = 464
CAPTURE_FPS = 60
REPS = 3
ROUTE_SHA = "415e205ff9bdca6c708968238f0eba971a7b28a2b431b772b9f5e4f83bbb07d4"
PUBLIC = ROOT / "bench/jit/public"
DEFECTS = {
    "coin-counts-twice": PUBLIC / "coin-counts-twice/defect.patch",
    "coin-counter-stuck": PUBLIC / "coin-counter-stuck/defect.patch",
}
COMMENT = ROOT / "agents/fixtures/operators/comment-only.patch"
COMMENT_SHA = "48a16859864aa88fdbfd94bb0a508b9764bacf19fb6ef53def4d6f9b22b16b65"
EXPECTED = {
    "clean": (5, 5, "pass"),
    "coin-counts-twice": (5, 10, "fail"),
    "coin-counter-stuck": (5, 0, "fail"),
    "frozen-player": (0, 0, "needs-review"),
    "comment-only": (5, 5, "pass"),
}


def sha(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def fixtures():
    profile = load_strict(ROOT / "discovery/platformer.profile.json", "mechanics-profile")
    route_path = DRAFT / "routes" / f"{NAME}.json"
    route = load(route_path, "route")
    probes = offer.library(profile["actions"], offer.CONTROL, profile=profile, game=GAME)
    probe = next(probe for probe in probes if probe["id"] == NAME)
    compiled = compile_route(probe["program"], name=NAME, description=probe["description"],
                             actions=offer.route_actions(profile, probe))
    if route != compiled or route["ticks"] != TICKS or sha(route_path) != ROUTE_SHA:
        raise ValueError("the draft route differs from the 464-tick public pause route")

    spec_path = DRAFT / "checks/pause-menu-score-after-five-pickups.json"
    spec = load(spec_path, "test-spec")
    assertion = spec["assertion"]
    if (assertion["type"], assertion["labelPath"], assertion["expected"], assertion["routeTicks"]) != (
            "exact-ui-integer", LABEL, 5, TICKS):
        raise ValueError("the draft exact-score assertion differs from the qualification plan")
    if "approval" in spec or spec["coverage"]["routes"] != [NAME]:
        raise ValueError("the assertion must be a draft bound to the public pause route")
    return profile, route_path, spec_path, spec


def trace_evidence(trace: dict) -> dict:
    rows = trace["rows"]
    if trace["ticks"] != TICKS or [row["tick"] for row in rows] != list(range(TICKS)):
        raise ValueError("expected one engine row for each of the 464 route ticks")
    if trace["unknownActions"] or trace["physicsTicksPerSecond"] != 120:
        raise ValueError("the trace has an unknown route action or a different physics clock")

    counts = [len(row["coins"]) for row in rows if isinstance(row.get("coins"), list)]
    if len(counts) != TICKS or any(after > before for before, after in zip(counts, counts[1:])):
        raise ValueError("the public route should have complete, nonincreasing coin counts")
    pickups = [{"tick": tick, "count": before - after}
               for tick, (before, after) in enumerate(zip(counts, counts[1:]), 1) if after < before]
    label_rows = [row["uiLabelIntegers"] for row in rows]
    if any(set(values) != {LABEL} for values in label_rows):
        raise ValueError("the trace must record the requested Label path on each tick")
    readings = {row["tick"]: values[LABEL] for row, values in zip(rows, label_rows) if values[LABEL] is not None}
    if any(type(value) is not int for value in readings.values()) or TICKS - 1 not in readings:
        raise ValueError("the requested Label lacks an integer reading at route completion")

    return {
        "firstTick": rows[0]["tick"], "lastTick": rows[-1]["tick"],
        "initialCoins": counts[0], "finalCoins": counts[-1], "pickups": counts[0] - counts[-1],
        "pickupEvents": pickups, "firstLabelTick": min(readings), "labelValue": readings[TICKS - 1],
    }


def qualified(arm: str, evidence: dict, verdict: dict, expected_frames: list[int] | None) -> bool:
    pickups, value, outcome = EXPECTED[arm]
    coverage = verdict["coverage"]
    if (evidence["pickups"], evidence["labelValue"], verdict["result"]) != (pickups, value, outcome):
        return False
    if not expected_frames or not coverage["completeWindow"]:
        return False
    if outcome == "needs-review":
        return (coverage["semanticResult"] == "not_exercised"
                and verdict["framesJudged"] == 0 and "no pickups" in verdict["reason"])
    if verdict["framesJudged"] != 1 or coverage["semanticResult"] != outcome:
        return False
    return outcome != "fail" or (verdict["firstFrame"] == expected_frames[-1] and bool(verdict["evidence"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot", type=Path, required=True, help="Godot 4.7.2 executable")
    parser.add_argument("--out", type=Path, required=True, help="empty replay evidence directory")
    args = parser.parse_args()

    profile, route_path, spec_path, spec = fixtures()
    godot = args.godot.resolve(strict=True)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        parser.error("--out must be empty")
    os.environ.setdefault("EXPECTRAIL_GODOT_CACHE", str(out / "cache"))

    frozen = out / "frozen-player.patch"
    control = do_nothing.control(GAME, profile, "player")
    if control["mode"] != "frozen" or sha(COMMENT) != COMMENT_SHA:
        raise ValueError("the expected frozen-player or registered comment-only control is unavailable")
    frozen.write_text(control["patchText"], encoding="utf-8")
    arms = {"clean": None, **DEFECTS, "frozen-player": frozen, "comment-only": COMMENT}
    game_tree = tree_digest(GAME)
    route_sha = sha(route_path)
    result = {
        "route": NAME, "routeSha256": route_sha, "specSha256": sha(spec_path), "labelPath": LABEL,
        "gameTree": game_tree, "engineSha256": sha(godot), "arms": {},
    }
    mismatches = []
    for arm, patch in arms.items():
        patch_sha = sha(patch) if patch is not None else None
        runs = []
        for rep in range(1, REPS + 1):
            folder = out / arm / str(rep)
            replay = run(route_path, folder, game=GAME, godot=godot, patch=patch,
                         fps=CAPTURE_FPS, capture_frames=False, label_paths=(LABEL,))
            trace_file = folder / "trace.json"
            if (replay["route"]["sha256"] != route_sha or replay["game"]["tree"] != game_tree
                    or replay["game"]["patchSha256"] != patch_sha or replay["trace"]["sha256"] != sha(trace_file)
                    or replay["capture"]["fps"] != CAPTURE_FPS or replay["capture"]["frames"] != 0):
                raise ValueError(f"{arm} repetition {rep} has inconsistent replay provenance")
            trace = read(trace_file)
            evidence = trace_evidence(trace)
            observations = verify.observations(trace, sha(folder / "replay.json"))
            expected_frames = verify.window_frames(spec, TICKS, trace, CAPTURE_FPS)
            verdict = evaluate(spec, observations, route=NAME, trace=trace, source_kind="trace",
                               expected_frames=expected_frames, capture_fps=CAPTURE_FPS)
            validate(verdict, "verdict")
            write(folder / "verdict.json", verdict)
            runs.append({"repetition": rep, **evidence, "verdict": verdict, "engine": replay["engine"],
                         "isolation": replay["isolation"], "traceSha256": replay["trace"]["sha256"]})
            observed = (evidence["pickups"], evidence["labelValue"], verdict["result"])
            print(arm, rep, *observed, verdict["reason"], flush=True)
            if not qualified(arm, evidence, verdict, expected_frames):
                mismatches.append({"arm": arm, "repetition": rep, "expected": EXPECTED[arm],
                                   "observed": observed, "reason": verdict["reason"]})
        result["arms"][arm] = {"patchSha256": patch_sha, "runs": runs}
        write(out / "qualification.json", {**result, "mismatches": mismatches})
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
