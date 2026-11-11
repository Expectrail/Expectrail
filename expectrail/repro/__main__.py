"""python3 -m expectrail.repro check | visibility | render"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from expectrail.repro import bench, visibility

PROFILE = bench.REPO / "discovery" / "platformer.profile.json"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m expectrail.repro")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="read the bench strictly and check every patch against a copy of the game")
    c.add_argument("--bench", type=Path, default=bench.BENCH)
    v = sub.add_parser("visibility", help="replay the clean game and every defect build; no model, no key")
    v.add_argument("--bench", type=Path, default=bench.BENCH)
    v.add_argument("--profile", type=Path, default=PROFILE)
    v.add_argument("--out", type=Path, required=True)
    v.add_argument("--jobs", type=int, default=1)
    v.add_argument("--only", action="append", default=[], help="a defect id (repeatable); default: all")
    r = sub.add_parser("render", help="print a visibility record as a table")
    r.add_argument("record", type=Path)
    r.add_argument("--bench", type=Path, default=bench.BENCH)
    args = ap.parse_args(argv)
    try:
        doc = bench.load(args.bench)
        if args.cmd == "check":
            failed = [(d["id"], why) for d in doc["defects"] if (why := bench.applies(d)) is not None]
            for did, why in failed:
                print(f"repro check: {did}: does not apply: {why}", file=sys.stderr)
            print(json.dumps({"defects": len(doc["defects"]), "apply": len(doc["defects"]) - len(failed),
                              "families": bench.families(doc)}))
            return 1 if failed else 0
        if args.cmd == "visibility":
            from expectrail.contracts import load_strict
            from expectrail.jit.probes import jit_library

            profile = load_strict(args.profile, "mechanics-profile")
            record = visibility.measure(doc, profile, jit_library(profile["actions"]), args.out, jobs=args.jobs,
                                        only=args.only or None, bench_path=args.bench)
            print(json.dumps(record["totals"]))
            return 1 if record["totals"]["error"] else 0
        record = visibility.load(args.record)
        for line in visibility.stale(record, doc, bench_path=args.bench):
            print(f"repro render: stale: {line}", file=sys.stderr)
        sys.stdout.write(visibility.render(record, doc))
        return 0
    except (bench.BenchError, visibility.VisibilityError, OSError) as exc:
        print(f"repro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
