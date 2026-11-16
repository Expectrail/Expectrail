"""Read back full raw public measurements and verify their saved evidence. No engine/model calls."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re

from expectrail.route import input_map
from .bench import verify_build
from .producer import make_route, reports, write_json
from .scale import trace_summary


def report_shape(report: dict, route: dict, trace: dict, commit: str) -> None:
    if set(report) != {"format", "id", "producer", "target", "route", "bug", "fault"}:
        raise ValueError("report field shape differs from issue #531")
    if report["format"] != "expectrail.playtest-report/v1" or not re.fullmatch(r"[a-z0-9][a-z0-9-]{3,63}", report["id"]):
        raise ValueError("invalid report format or id")
    if report["route"] != route or route["ticks"] > 1800 or report["target"] != {"commit": commit}:
        raise ValueError("report target or route differs from the replay")
    if not report["bug"].strip() or not 1 <= len(report["bug"]) <= 8192:
        raise ValueError("invalid player wording")
    if set(report["producer"]) != {"name", "version"}:
        raise ValueError("invalid producer fields")
    fault = report["fault"]
    if set(fault) != {"preFaultTick", "faultTick", "anchor"} or not 0 <= fault["preFaultTick"] < fault["faultTick"] < route["ticks"]:
        raise ValueError("invalid fault window")
    anchor = fault["anchor"]
    if set(anchor) != {"object", "x", "y", "tolerancePx"}:
        raise ValueError("invalid anchor shape")
    if [anchor["x"], anchor["y"]] != trace["rows"][fault["preFaultTick"]]["player"] or anchor["object"] != "Player":
        raise ValueError("anchor is not the logged previous position")


def audit(root: Path) -> dict:
    plan = json.loads((root / "plan.json").read_text())
    seeds = range(plan["startSeed"], plan["startSeed"] + plan["seedsPerBuild"])
    completed, count, retry_count = 0, 0, 0
    policy_counts = {"original": 0}
    viewport = plan.get("viewport")
    if viewport is not None:
        policy_counts["offscreen"] = 0
    for build in plan["builds"]:
        project = root / "builds" / build["id"] / "game"
        built = json.loads((project.parent / "build.json").read_text())
        verify_build(project, built["commit"])
        actions, rate, _ = input_map(project)
        for seed in seeds:
            folder = root / "runs" / build["id"] / str(seed)
            measured = json.loads((folder / "measurement.json").read_text())
            raw = gzip.decompress((folder / "trace.json.gz").read_bytes())
            actual_hash = hashlib.sha256(raw).hexdigest()
            replay = json.loads((folder / "replay.json").read_text())
            if actual_hash != measured["traceSha256"] or actual_hash != replay["trace"]["sha256"]:
                raise ValueError(f"{build['id']}/{seed}: trace hash mismatch")
            trace = json.loads(raw)
            route = json.loads((root / "routes" / f"{seed}.json").read_text())
            if route != make_route(actions, seed, plan["ticks"]):
                raise ValueError("route regeneration differs")
            if trace["ticks"] != plan["ticks"] or trace["physicsTicksPerSecond"] != rate or trace.get("unknownActions"):
                raise ValueError("trace metadata differs")
            if [row["tick"] for row in trace["rows"]] != list(range(plan["ticks"])):
                raise ValueError("trace is incomplete")
            recalculated = trace_summary(route, trace)
            if any(measured[key] != recalculated[key] for key in ("fields", "signals")):
                raise ValueError("field or signal summary differs")
            for policy in policy_counts:
                expected = reports(route, trace, built["commit"],
                                   viewport=viewport if policy == "offscreen" else None)
                report_folder = "reports" if policy == "original" else f"reports-{policy}"
                saved = [json.loads(path.read_text()) for path in (folder / report_folder).glob("*.json")]
                if sorted(saved, key=lambda r: r["id"]) != sorted(expected, key=lambda r: r["id"]):
                    raise ValueError("report regeneration differs")
                for report in saved:
                    report_shape(report, route, trace, built["commit"])
                listed = measured.get("reportsByPolicy", {}).get(policy, measured["reports"])
                if {r["id"] for r in saved} != {r["id"] for r in listed}:
                    raise ValueError("report summary omits or adds a report")
                policy_counts[policy] += len(saved)
                count += len(saved)
            completed += 1
            retry_count += len(measured["failedAttempts"])
        print(f"audited {build['id']}: {plan['seedsPerBuild']} seeds", flush=True)
    result = {"builds": len(plan["builds"]), "seedsPerBuild": plan["seedsPerBuild"],
              "completeTracesAudited": completed, "reportsRegenerated": count,
              "reportsByPolicy": policy_counts,
              "failedEngineAttempts": retry_count,
              "traceHashesMatched": True, "routeRegenerationMatched": True,
              "gameCommitsMatched": True, "fieldAndSignalSummariesMatched": True,
              "reportShapesAndAnchorsMatched": True}
    write_json(root / "audit.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(audit(args.root), indent=2))


if __name__ == "__main__":
    main()
