"""python3 -m expectrail.repro check | visibility | render | cases | score | score-render"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from expectrail.repro import bench, score, visibility

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
    k = sub.add_parser("cases", help="the cases a live run on the bench covers: each defect with the no-fix candidate")
    k.add_argument("--bench", type=Path, default=bench.BENCH)
    k.add_argument("--github-output", action="store_true", help="print cases= and budget= lines for a workflow step")
    s = sub.add_parser("score", help="read a live run's records and write the reproduction rate; no model, no engine")
    s.add_argument("--bench", type=Path, default=bench.BENCH)
    s.add_argument("--records", type=Path, required=True, help="a folder with repro-<defect>/jit-run.json for each defect")
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--visibility", type=Path, default=visibility.RECORD,
                   help="the visibility record a miss's reason is read from")
    s.add_argument("--no-visibility", action="store_true")
    s.add_argument("--source", default=None, help="where the records came from, for example 'run 123456'")
    sr = sub.add_parser("score-render", help="print a score record as a page")
    sr.add_argument("record", type=Path)
    sr.add_argument("--bench", type=Path, default=bench.BENCH)
    args = ap.parse_args(argv)
    try:
        doc = bench.load(args.bench)
        if args.cmd == "cases":
            found = score.cases(doc)
            if args.github_output:
                print("cases=" + json.dumps(found))
                print(f"budget={score.CAP_USD:g}")
            else:
                print(json.dumps(found, indent=1))
            return 0
        if args.cmd == "score":
            record = score.score(doc, args.records, visibility_path=None if args.no_visibility else args.visibility,
                                 source=args.source, bench_path=args.bench)
            score.write(record, args.out)
            print(json.dumps(record["totals"]))
            return 0
        if args.cmd == "score-render":
            record = score.load(args.record)
            for line in score.stale(record, doc, bench_path=args.bench):
                print(f"repro score-render: stale: {line}", file=sys.stderr)
            sys.stdout.write(score.render(record))
            return 0
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
    except (bench.BenchError, visibility.VisibilityError, score.ScoreError, OSError) as exc:
        print(f"repro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
