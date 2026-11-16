"""Summarize recorded public playtests using the repro bench's existing miss vocabulary."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from .producer import write_json

# These are the existing repro bench's labels, not a second reason vocabulary.
MISS_REASONS = ("route-never-reaches", "no-signal", "probe-language", "wrong-predicate",
                "flaky", "budget", "undetermined")
OBSERVATIONS = ("below-level", "stopped-moving", "turning")


def differences(clean: dict, defect: dict) -> tuple[list[str], list[str]]:
    return tuple(sorted(k for k in set(clean[group]) | set(defect[group])
                        if clean[group].get(k) != defect[group].get(k)) for group in ("fields", "signals"))


def miss_reason(fields: set[str], signals: set[str], defect_id: str) -> tuple[str, str]:
    """Current trace comparisons take priority; old public hand evidence is labelled as such.

    Like the repro scorer, signal changes can be incidental: this never proves a symptom was reached.
    No new frame run is claimed by these hand-evidence explanations.
    """
    if signals:
        return "wrong-predicate", "At least one existing repro signal changes, but the three observations do not report it."
    if fields:
        return "no-signal", "The current trace changes, but none of the existing repro signals changes."
    if defect_id in ("coin-counts-twice", "coin-counter-stuck"):
        return "route-never-reaches", "The routes never open the pause menu; its counter is also absent from the trace (repro.menu and public menu evidence)."
    if defect_id in ("enemy-walks-backwards", "bullet-behind-scenery", "platform-z-order-pr927"):
        return "probe-language", "Public screen evidence describes a draw/animation effect that these traces do not record; no new rendered measurement was made."
    return "undetermined", "The traces and signals match; trace-only measurement cannot distinguish unreached behavior from an unrecorded effect."


def observations(record: dict) -> set[str]:
    return {r["observation"] for r in record["reports"]}


def summarize(root: Path, *, require_complete: bool = True, policy: str = "original") -> dict:
    if policy not in ("original", "offscreen"):
        raise ValueError("unknown observation policy")
    active_observations = OBSERVATIONS + (("offscreen",) if policy == "offscreen" else ())
    plan = json.loads((root / "plan.json").read_text())
    seeds = list(range(plan["startSeed"], plan["startSeed"] + plan["seedsPerBuild"]))
    records = {}
    for build in plan["builds"]:
        paths = root / "runs" / build["id"]
        records[build["id"]] = {int(p.parent.name): json.loads(p.read_text())
                                for p in paths.glob("*/measurement.json")}
        if policy != "original":
            for row in records[build["id"]].values():
                if policy not in row.get("reportsByPolicy", {}):
                    raise ValueError(f"{build['id']}: policy {policy} was not measured")
                row["reports"] = row["reportsByPolicy"][policy]
        if require_complete and set(records[build["id"]]) != set(seeds):
            raise ValueError(f"{build['id']}: {len(records[build['id']])}/{len(seeds)} seeds complete")
    clean = records["clean"]
    counts = Counter(r["observation"] for row in clean.values() for r in row["reports"])
    examples = {}
    for name in active_observations:
        examples[name] = [{"seed": seed, "report": report} for seed, row in sorted(clean.items())
                          for report in row["reports"] if report["observation"] == name][:2]
    output = {"policy": policy, "startSeed": plan["startSeed"], "seedsPerBuild": len(seeds),
              "clean": {"completed": len(clean), "reports": sum(counts.values()),
                        "reportingSeeds": sum(bool(r["reports"]) for r in clean.values()),
                        "byObservation": {name: counts[name] for name in active_observations}, "examples": examples},
              "defects": []}
    for build in plan["builds"][1:]:
        rows = records[build["id"]]
        common = sorted(set(rows) & set(clean))
        raw_counts = Counter(r["observation"] for row in rows.values() for r in row["reports"])
        novel = {name: [seed for seed in common if name in observations(rows[seed])
                        and name not in observations(clean[seed])] for name in active_observations}
        candidate_seeds = sorted({seed for values in novel.values() for seed in values})
        changed_fields, changed_signals, changed_seeds = set(), set(), []
        for seed in common:
            fields, signals = differences(clean[seed], rows[seed])
            changed_fields.update(fields)
            changed_signals.update(signals)
            if fields or signals:
                changed_seeds.append(seed)
        reason, basis = (None, None) if candidate_seeds else miss_reason(
            changed_fields, changed_signals, build["id"])
        output["defects"].append({"id": build["id"], "kind": build["kind"], "completed": len(rows),
            "candidateFound": bool(candidate_seeds), "candidateSeeds": len(candidate_seeds),
            "firstSeed": candidate_seeds[0] if candidate_seeds else None,
            "novelObservationSeeds": {name: len(values) for name, values in novel.items()},
            "firstSeedByObservation": {name: min(values) if values else None for name, values in novel.items()},
            "rawReports": sum(raw_counts.values()), "rawByObservation": {name: raw_counts[name] for name in active_observations},
            "effectDifferenceSeeds": len(changed_seeds), "firstDifferenceSeed": min(changed_seeds) if changed_seeds else None,
            "changedFields": sorted(changed_fields), "changedSignals": sorted(changed_signals),
            "missReason": reason, "missBasis": basis})
    return output


def render(record: dict) -> str:
    clean = record["clean"]
    lines = [f"Clean: {clean['reports']} reports in {clean['completed']} seeds, "
             f"{clean['reportingSeeds']} seeds with a report.", "", "| Observation | False reports | Examples |",
             "| --- | ---: | --- |"]
    for name in clean["byObservation"]:
        examples = ", ".join(f"seed {e['seed']}, tick {e['report']['fault']['faultTick']}" for e in clean["examples"][name])
        lines.append(f"| {name} | {clean['byObservation'][name]} | {examples or 'none occurred'} |")
    lines += ["", "Found below means a candidate observation absent on the same clean seed, not a confirmed known symptom.", "",
              "| Patch | Completed | Candidate found | Seeds | First seed | Observation counts (new vs clean) | Miss reason |",
              "| --- | ---: | --- | ---: | ---: | --- | --- |"]
    for row in record["defects"]:
        obs = ", ".join(f"{key}: {value}" for key, value in row["novelObservationSeeds"].items() if value) or "none"
        lines.append(f"| {row['id']} | {row['completed']} | {'yes' if row['candidateFound'] else 'no'} | "
                     f"{row['candidateSeeds']} | {row['firstSeed'] if row['firstSeed'] is not None else '-'} | "
                     f"{obs} | {row['missReason'] or '-'} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--partial", action="store_true")
    parser.add_argument("--policy", choices=("original", "offscreen"), default="original")
    args = parser.parse_args(argv)
    measured = summarize(args.root, require_complete=not args.partial, policy=args.policy)
    suffix = f"-{args.policy}" + ("-partial" if args.partial else "")
    write_json(args.root / f"summary{suffix}.json", measured)
    (args.root / f"summary{suffix}.md").write_text(render(measured))
    print(render(measured))


if __name__ == "__main__":
    main()
