"""python3 -m expectrail.repro check | visibility | render | screen | screen-render | evidence | evidence-render
| reach | menu | cases | score | score-render | breakdown"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from expectrail.jit.offer import DEFAULT as DEFAULT_OFFER, OFFERS
from expectrail.repro import bench, breakdown, evidence, menu, reach, score, screen, visibility

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
    v.add_argument("--reach", action="store_true",
                   help="replay the reach probes (expectrail/repro/reach.py) in place of the library probes")
    g = sub.add_parser("reach", help="print the reach probes for a bug report: routes for pairs of actions no "
                                     "library probe uses together; no model, no engine")
    g.add_argument("--bench", type=Path, default=bench.BENCH)
    g.add_argument("--profile", type=Path, default=PROFILE)
    g.add_argument("--report", type=Path, default=None, help="a bug report; it only orders the probes")
    m = sub.add_parser("menu", help="print the menu probes: a library walk, then the game's menu opened; no model, "
                                    "no engine")
    m.add_argument("--bench", type=Path, default=bench.BENCH)
    m.add_argument("--profile", type=Path, default=PROFILE)
    m.add_argument("--menu-action", action="append", required=True,
                   help="an input action that opens the game's menu (repeatable); the game must declare it")
    r = sub.add_parser("render", help="print a visibility record as a table")
    r.add_argument("record", type=Path)
    r.add_argument("--bench", type=Path, default=bench.BENCH)
    sc = sub.add_parser("screen", help="replay the clean game and every defect build with frames, and compare the "
                                       "frames and the record; no model, no key")
    sc.add_argument("--bench", type=Path, default=bench.BENCH)
    sc.add_argument("--profile", type=Path, default=PROFILE)
    sc.add_argument("--out", type=Path, required=True)
    sc.add_argument("--jobs", type=int, default=1)
    sc.add_argument("--only", action="append", default=[], help="a defect id (repeatable); default: all")
    sc.add_argument("--reach", action="store_true", help="replay the reach probes in place of the library probes")
    sc.add_argument("--keep-frames", action="store_true", help="leave the captured frames under <out>/work")
    scr = sub.add_parser("screen-render", help="print a screen record as a table")
    scr.add_argument("record", type=Path)
    scr.add_argument("--bench", type=Path, default=bench.BENCH)
    ev = sub.add_parser("evidence", help="replay every probe on the clean game and on one bug build with frames, and "
                                         "write what differs in the record and on the screen; no model, no key")
    ev.add_argument("--bench", type=Path, default=bench.BENCH)
    ev.add_argument("--profile", type=Path, default=PROFILE)
    ev.add_argument("--defect", default=None, help="a defect id of the bench: its patch makes the bug build")
    ev.add_argument("--patch", type=Path, action="append", default=[],
                    help="a patch that makes the bug build (repeatable), in place of --defect")
    ev.add_argument("--out", type=Path, required=True)
    ev.add_argument("--jobs", type=int, default=1)
    ev.add_argument("--probe", action="append", default=[], help="a probe id (repeatable); default: all")
    ev.add_argument("--reach", action="store_true", help="the reach probes as well as the library probes")
    ev.add_argument("--menu-action", action="append", default=[],
                    help="an input action that opens the game's menu (repeatable): add the menu probes "
                         "(expectrail/repro/menu.py); the game must declare it")
    ev.add_argument("--menu-only", action="store_true", help="with --menu-action: the menu probes alone")
    ev.add_argument("--recorded-answers", type=Path, default=None,
                    help="a folder of a visual observer's recorded answers to read; nothing is ever asked")
    ev.add_argument("--object", action="append", default=[], metavar="NAME=PROMPT",
                    help="an object to read recorded answers for, with the prompt it was recorded under (repeatable)")
    ev.add_argument("--keep-frames", action="store_true", help="leave the captured frames under <out>/work")
    evr = sub.add_parser("evidence-render", help="print an evidence record as a table, or with --for-proposer the "
                                                 "bounded summary a prompt could carry")
    evr.add_argument("record", type=Path)
    evr.add_argument("--bench", type=Path, default=bench.BENCH)
    evr.add_argument("--for-proposer", action="store_true")
    evr.add_argument("--profile", type=Path, default=PROFILE)
    evr.add_argument("--object", action="append", default=[], metavar="NAME",
                     help="with --for-proposer: an object name the summary may show (repeatable); any other is counted")
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
    s.add_argument("--offer", choices=OFFERS, default=DEFAULT_OFFER,
                   help="count only records made with this setting (expectrail/jit/offer.py)")
    bd = sub.add_parser("breakdown", help="print a score's misses by reason, with the hand findings; no model, no engine")
    bd.add_argument("--score", type=Path, required=True, help="a repro-score.json")
    bd.add_argument("--hand", type=Path, default=breakdown.HAND, help="the hand findings (expectrail.repro-hand-reasons/v1)")
    bd.add_argument("--bench", type=Path, default=bench.BENCH)
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
                                 source=args.source, bench_path=args.bench, offer=args.offer)
            score.write(record, args.out)
            print(json.dumps(record["totals"]))
            return 0
        if args.cmd == "breakdown":
            record = score.load(args.score)
            hand = breakdown.load(args.hand)
            for line in score.stale(record, doc, bench_path=args.bench) + breakdown.unknown(hand, doc):
                print(f"repro breakdown: stale: {line}", file=sys.stderr)
            sys.stdout.write(breakdown.render(record, hand))
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
        if args.cmd == "reach":
            from expectrail.contracts import load_strict
            from expectrail.jit.probes import jit_library

            profile = load_strict(args.profile, "mechanics-profile")
            report = args.report.read_text(encoding="utf-8", errors="replace") if args.report else ""
            print(json.dumps(reach.reach(report, profile["actions"], jit_library(profile["actions"])), indent=1))
            return 0
        if args.cmd == "menu":
            from expectrail.contracts import load_strict
            from expectrail.jit.probes import jit_library

            profile = load_strict(args.profile, "mechanics-profile")
            print(json.dumps(_menu_probes(profile, jit_library(profile["actions"]), args.menu_action), indent=1))
            return 0
        if args.cmd == "evidence-render":
            record = evidence.load(args.record)
            if args.for_proposer:
                from expectrail.contracts import load_strict
                from expectrail.jit.probes import jit_library

                # The names a summary may show are this command's own, never the record's.
                profile = load_strict(args.profile, "mechanics-profile")
                library = jit_library(profile["actions"])
                known = [p["id"] for p in library + reach.reach_probes(profile["actions"], library)]
                print(json.dumps(evidence.for_proposer(record, probes=known, objects=args.object), indent=1))
            else:
                sys.stdout.write(evidence.render(record))
            return 0
        if args.cmd == "evidence":
            from expectrail.contracts import load_strict
            from expectrail.jit.probes import jit_library

            if bool(args.defect) == bool(args.patch):
                raise evidence.EvidenceError("give the bug build as --defect or as --patch, one of the two")
            if args.defect:
                found = [d for d in doc["defects"] if d["id"] == args.defect]
                if not found:
                    raise evidence.EvidenceError(f"no defect {args.defect[:60]!r} in the bench")
                patches = [bench.REPO / found[0]["patch"]]
            else:
                patches = args.patch
            profile = load_strict(args.profile, "mechanics-profile")
            probes = jit_library(profile["actions"])
            if args.reach:
                probes = probes + reach.reach_probes(profile["actions"], probes)
            if args.menu_only and not args.menu_action:
                raise evidence.EvidenceError("--menu-only needs at least one --menu-action")
            if args.menu_action:
                made = _menu_probes(profile, jit_library(profile["actions"]), args.menu_action)
                probes = made if args.menu_only else probes + made
                profile = menu.with_menu_actions(profile, args.menu_action)
            if args.probe:
                unknown = sorted(set(args.probe) - {p["id"] for p in probes})
                if unknown:
                    raise evidence.EvidenceError(f"no probe {unknown[0][:60]!r}")
                probes = [p for p in probes if p["id"] in args.probe]
            recorded = None
            if args.recorded_answers is not None or args.object:
                if args.recorded_answers is None or not args.object or any("=" not in o for o in args.object):
                    raise evidence.EvidenceError("recorded answers are read with --recorded-answers and at least one "
                                                 "--object NAME=PROMPT")
                pairs = [o.split("=", 1) for o in args.object]
                if len({name for name, _prompt in pairs}) != len(pairs):
                    raise evidence.EvidenceError("an --object is named twice")
                recorded = evidence.Recorded(args.recorded_answers, dict(pairs))
            record = evidence.evidence(profile, probes, patches, args.out, jobs=args.jobs, recorded=recorded,
                                       keep_frames=args.keep_frames)
            print(json.dumps(record["totals"]))
            return 1 if record["totals"]["error"] else 0
        if args.cmd == "screen":
            from expectrail.contracts import load_strict
            from expectrail.jit.probes import jit_library

            profile = load_strict(args.profile, "mechanics-profile")
            probes = jit_library(profile["actions"])
            if args.reach:
                probes = reach.reach_probes(profile["actions"], probes)
            record = screen.measure(doc, profile, probes, args.out, jobs=args.jobs, only=args.only or None,
                                    bench_path=args.bench, keep_frames=args.keep_frames)
            print(json.dumps(record["totals"]))
            return 1 if record["totals"]["error"] else 0
        if args.cmd == "screen-render":
            record = screen.load(args.record)
            for line in screen.stale(record, doc, bench_path=args.bench):
                print(f"repro screen-render: stale: {line}", file=sys.stderr)
            sys.stdout.write(screen.render(record, doc))
            return 0
        if args.cmd == "visibility":
            from expectrail.contracts import load_strict
            from expectrail.jit.probes import jit_library

            profile = load_strict(args.profile, "mechanics-profile")
            probes = jit_library(profile["actions"])
            if args.reach:
                probes = reach.reach_probes(profile["actions"], probes)
            record = visibility.measure(doc, profile, probes, args.out, jobs=args.jobs,
                                        only=args.only or None, bench_path=args.bench)
            print(json.dumps(record["totals"]))
            return 1 if record["totals"]["error"] else 0
        record = visibility.load(args.record)
        for line in visibility.stale(record, doc, bench_path=args.bench):
            print(f"repro render: stale: {line}", file=sys.stderr)
        sys.stdout.write(visibility.render(record, doc))
        return 0
    except (bench.BenchError, visibility.VisibilityError, screen.ScreenError, score.ScoreError, reach.ReachError,
            evidence.EvidenceError, breakdown.BreakdownError, menu.MenuError, OSError) as exc:
        print(f"repro: {exc}", file=sys.stderr)
        return 1


def _menu_probes(profile: dict, library: list[dict], menu_actions: list[str]) -> list[dict]:
    """The menu probes for the profile's game, its menu actions checked against the game's own project file."""
    game = bench.REPO / profile["game"]["path"]
    if not game.resolve().is_relative_to(bench.REPO.resolve()):
        raise menu.MenuError("the profile's game is outside the repository")
    declared = menu.declared_actions(game / "project.godot")
    return menu.menu_probes(library, menu_actions, profile["actions"], declared)


if __name__ == "__main__":
    raise SystemExit(main())
