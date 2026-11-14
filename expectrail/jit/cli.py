"""Command line for per-change check generation (docs/jit.md).

    python -m expectrail.jit.cli run --report-file report.txt --candidate fix.patch \
        [--base bugs/reported/air-jump.patch] --out runs/jit [--model spark|off] [--budget-usd 2]
    python -m expectrail.jit.cli report runs/jit/jit-run.json
    python -m expectrail.jit.cli gate-summary runs/jit/jit-run.json [--out generated-checks.json]

In CI the model call and the replays are separate steps, so the key and the change's code never meet:

    python -m expectrail.jit.cli propose --report-file r.txt --candidate c.patch --out runs/jit-proposal
    python -m expectrail.jit.cli run --report-file r.txt --candidate c.patch --out runs/jit \
        --proposal runs/jit-proposal/jit-proposal.json [--game path/to/the/reference/game]

Every step of one change takes the same ``--offer`` (expectrail/jit/offer.py): ``baseline``, the default,
is the generator as it was before issue #285's steps 3 and 4; ``signals-reach`` also offers the three
held-back signals and the reach probes; the evidence setting (``offer.EVIDENCE``) also gives the proposer step 5's
evidence, which ``measure`` makes (replays with frames, expectrail/jit/offer.py) and ``propose`` and
``revise`` read with ``--evidence``. A proposal is replayed only under the offer it was made with.
``measure`` and ``propose`` also take the pixel setting (``offer.PIXEL``, #286), under which the proposal
carries pixel checks; ``run`` and ``revise`` do not take it yet, because the replay does not judge them.

``--withhold-candidate`` on ``propose``, ``revise`` and ``run`` gives the model no byte of the candidate
patch (issue #285, step 6): the checks then come from the report and the bug build alone, and a fix
cannot shape the checks that judge it. Every step of one change takes it or none does; a proposal made
one way is refused by a run made the other.

``run`` always exits 0 once it has written a record: a run that generated nothing is a result, and
nothing here accepts or rejects a change. Bad arguments exit 2.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from expectrail.contracts import load_strict
from expectrail.jit.offer import ALL as ALL_OFFERS, DEFAULT as DEFAULT_OFFER, OFFERS
from expectrail.jit.offer import library as offered_library
from expectrail.jit.offer import attach_evidence, make_evidence, shows_evidence
from expectrail.jit.run import DEFAULT_BUDGET_USD, RECORD_NAME, from_base_alone, gate_summary, generate

PROFILE = Path(__file__).resolve().parents[2] / "discovery" / "platformer.profile.json"


def render(doc: dict) -> str:
    """The run as Markdown, for the job summary and the record folder."""
    lines = [f"# Generated checks: {doc['runId']}", "",
             "Report-only. A generated check never accepts or rejects a change (docs/jit.md).", ""]
    if doc["status"] != "complete":
        lines += [f"**No generated checks.** {doc['reason']}", ""]
    c = doc["counts"]
    lines += [f"- Proposed: {c['proposed']}, valid: {c['valid']}, catches: {c['strong']} strong, {c['weak']} weak",
              f"- Near-miss variants: {len(doc['variants'])}",
              f"- Spend: ${doc['spend']['usd']:.4f} of ${doc['spend']['capUsd']:.2f} "
              f"({doc['spend']['replays']} replays, {doc['spend']['promptTokens']} prompt and "
              f"{doc['spend']['completionTokens']} completion tokens; prices {doc['spend']['prices']['source']})"]
    base = from_base_alone(doc)
    if base["candidate"] == "withheld":
        lines.append(f"- The model was not shown the candidate (issue #285, step 6). Checks that pass on the clean game "
                     f"and fail on the bug build: {len(base['reproducing'])}, all derived from the report and the "
                     f"bug build alone")
    else:
        lines.append(f"- The model was shown the candidate. Checks that pass on the clean game and fail on the bug "
                     f"build: {len(base['reproducing'])}; none of them is derived without the candidate")
    if "pixelChecks" in doc:
        rows = doc["pixelChecks"]
        lines.append(f"- Pixel checks (#286): {len(rows)} proposed, {len(base.get('pixelReproducing', []))} pass on the clean "
                     f"game and fail on the bug build, "
                     f"{sum(1 for r in rows if r['outcome'] == 'catch')} fail on the candidate")
    lines.append("")
    if doc.get("pixelChecks"):
        lines += ["| Pixel check | Observer | Clean | Bug | Candidate | Result | Why |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for r in doc["pixelChecks"]:
            lines.append(f"| `{r['check']['id']}` | {r['check']['observer']} | {', '.join(r['clean']) or 'not run'} | "
                         f"{', '.join(r['bug']) or 'not run'} | {', '.join(r['candidate']) or 'not run'} | "
                         f"{r['status']}, {r['outcome']} | {(r['reason'] or '').replace('|', '/')} |")
        lines.append("")
    if doc["catches"]:
        lines += ["| Check | Strength | Says | Candidate | Base | Variants killed |", "| --- | --- | --- | --- | --- | --- |"]
        for k in doc["catches"]:
            lines.append(f"| `{k['specId']}` | {k['strength']} | {k['statement']} | {', '.join(k['candidate'])} | "
                         f"{', '.join(k['base']) if k['base'] is not None else 'not run'} | {len(k['killed'])} |")
        lines.append("")
    if doc["validity"]:
        lines += ["| Check | Valid | Reference | Outcome | Why not valid |", "| --- | --- | --- | --- | --- |"]
        for v in doc["validity"]:
            lines.append(f"| `{v['specId']}` | {'yes' if v['valid'] else 'no'} | {', '.join(v['reference']) or 'not run'} | "
                         f"{v['outcome']} | {'; '.join(v['reasons'])} |")
        lines.append("")
    return "\n".join(lines)


def diff_games(base: Path, head: Path) -> str:
    """A unified diff (``-p1`` paths relative to the game) from one game folder to another: text files
    only, in sorted order, so two jobs that diff the same two commits write the same bytes. Engine
    caches (``.godot``) are left out; a binary file that changed is named in a comment line."""
    import difflib

    import os

    def files(root: Path, linked: dict[str, str]) -> dict[str, Path]:
        # A symlink is never followed: a pull request's game is untrusted, and a link to, say,
        # /proc/self/environ would put whatever the reading process holds into the patch, which goes
        # to the model and into an artifact. A link (or anything under a linked folder) is named, not read.
        found: dict[str, Path] = {}
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(root)
            if ".godot" in rel.parts:
                continue
            if any((root.joinpath(*rel.parts[:k])).is_symlink() for k in range(1, len(rel.parts) + 1)):
                linked[rel.as_posix()] = os.readlink(p) if p.is_symlink() else "(under a linked folder)"
                continue
            if p.is_file():
                found[rel.as_posix()] = p
        return found

    links_a: dict[str, str] = {}
    links_b: dict[str, str] = {}
    a, b = files(base, links_a), files(head, links_b)
    # Only links that were added, removed or pointed elsewhere are named; an unchanged link is no change.
    out: list[str] = [f"# symbolic link, not read: {rel}\n" for rel in sorted(set(links_a) | set(links_b))
                      if links_a.get(rel) != links_b.get(rel)]
    for rel in sorted(set(a) | set(b)):
        old = a[rel].read_bytes() if rel in a else b""
        new = b[rel].read_bytes() if rel in b else b""
        if old == new:
            continue
        try:
            old_t, new_t = old.decode("utf-8"), new.decode("utf-8")
        except UnicodeDecodeError:
            out.append(f"# binary file changed, not in this patch: {rel}\n")
            continue
        out += difflib.unified_diff(old_t.splitlines(keepends=True), new_t.splitlines(keepends=True),
                                    fromfile=f"a/{rel}" if rel in a else "/dev/null",
                                    tofile=f"b/{rel}" if rel in b else "/dev/null")
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n\\ No newline at end of file\n"
    return "".join(out)


def attach_measurements(probes: list[dict], path: Path | None, base: list[Path]) -> list[str]:
    """Put each probe's measurements on it for the prompt. Returns diagnostics: empty when they were
    attached; otherwise why not, and the proposal goes ahead without them (it is never refused)."""
    if path is None:
        return ["measurements: none given"]
    from expectrail.jit.measure import MeasurementsUnusable, load

    try:
        table = load(path, probe_ids={p["id"] for p in probes}, base_patches=base)
    except (MeasurementsUnusable, OSError) as exc:
        return [f"measurements: not used: {exc}"[:200]]
    for p in probes:
        if p["id"] in table:
            p["measured"] = table[p["id"]]
    return []


def _candidate(args) -> str:
    return "withheld" if getattr(args, "withhold_candidate", False) else "shown"


def _intent_settings(args) -> dict:
    # ``candidate`` only when it is withheld, so the default call is the one it always was.
    return {"offer": args.offer, **({"candidate": "withheld"} if _candidate(args) == "withheld" else {})}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="expectrail.jit.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--profile", type=Path, default=PROFILE)
    r.add_argument("--report-file", type=Path, required=True)
    r.add_argument("--candidate", type=Path, required=True)
    r.add_argument("--base", type=Path, action="append", default=[])
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--model", choices=("spark", "off"), default="spark")
    r.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    r.add_argument("--reps", type=int, default=3)
    r.add_argument("--variant-limit", type=int, default=8)
    r.add_argument("--spark-usd-per-mtok-in", type=float)
    r.add_argument("--spark-usd-per-mtok-out", type=float)
    r.add_argument("--run-id")
    r.add_argument("--proposal", type=Path, help="replay a saved proposal instead of calling the model")
    r.add_argument("--game", type=Path, help="the reference game (default: game/platformer in this checkout)")
    r.add_argument("--withhold-candidate", action="store_true",
                    help="give the model no byte of the candidate patch (issue #285, step 6)")
    r.add_argument("--offer", choices=OFFERS, default=DEFAULT_OFFER,
                    help="what the generator is offered (expectrail/jit/offer.py); the same for every step")
    pp = sub.add_parser("propose")
    pp.add_argument("--profile", type=Path, default=PROFILE)
    pp.add_argument("--report-file", type=Path, required=True)
    pp.add_argument("--candidate", type=Path, required=True)
    pp.add_argument("--out", type=Path, required=True)
    pp.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    pp.add_argument("--spark-usd-per-mtok-in", type=float)
    pp.add_argument("--spark-usd-per-mtok-out", type=float)
    pp.add_argument("--base", type=Path, action="append", default=[],
                    help="the bug's patches, read only to check the measurements were taken against them")
    pp.add_argument("--measurements", type=Path, help="jit-measurements.json from the measure command")
    pp.add_argument("--evidence", type=Path,
                    help="the evidence file the measure command wrote; read only under the evidence setting")
    pp.add_argument("--withhold-candidate", action="store_true",
                    help="give the model no byte of the candidate patch (issue #285, step 6)")
    pp.add_argument("--offer", choices=ALL_OFFERS, default=DEFAULT_OFFER,
                    help="what the generator is offered (expectrail/jit/offer.py); the same for every step")
    rv = sub.add_parser("revise")
    rv.add_argument("--profile", type=Path, default=PROFILE)
    rv.add_argument("--report-file", type=Path, required=True)
    rv.add_argument("--candidate", type=Path, required=True)
    rv.add_argument("--proposal", type=Path, required=True, help="the first proposal")
    rv.add_argument("--record", type=Path, required=True, help="the first replay's jit-run.json")
    rv.add_argument("--out", type=Path, required=True)
    rv.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    rv.add_argument("--spark-usd-per-mtok-in", type=float)
    rv.add_argument("--spark-usd-per-mtok-out", type=float)
    rv.add_argument("--base", type=Path, action="append", default=[])
    rv.add_argument("--measurements", type=Path)
    rv.add_argument("--evidence", type=Path,
                    help="the evidence file the measure command wrote; read only under the evidence setting")
    rv.add_argument("--github-output", type=Path, help="append revised=true|false here (a workflow's GITHUB_OUTPUT)")
    rv.add_argument("--withhold-candidate", action="store_true",
                    help="give the model no byte of the candidate patch (issue #285, step 6)")
    rv.add_argument("--offer", choices=OFFERS, default=DEFAULT_OFFER,
                    help="what the generator is offered (expectrail/jit/offer.py); the same for every step")
    ms = sub.add_parser("measure")
    ms.add_argument("--profile", type=Path, default=PROFILE)
    ms.add_argument("--base", type=Path, action="append", default=[])
    ms.add_argument("--out", type=Path, required=True)
    ms.add_argument("--game", type=Path, help="the reference game (default: game/platformer in this checkout)")
    ms.add_argument("--offer", choices=ALL_OFFERS, default=DEFAULT_OFFER,
                    help="what the generator is offered (expectrail/jit/offer.py); the same for every step")
    ms.add_argument("--report-file", type=Path,
                    help="the bug report; with --offer signals-reach it only orders the reach probes")
    ms.add_argument("--evidence-jobs", type=int, default=1,
                    help="replays at once for the evidence (the evidence setting only)")
    bp = sub.add_parser("bench-pins", help="print the pins a bench registration records")
    bc = sub.add_parser("bench-check", help="exit 1 unless the bench registration is signed and its pins hold")
    bc.add_argument("--prereg", type=Path)
    bs = sub.add_parser("bench-score")
    bs.add_argument("--records", type=Path, required=True, help="a folder with <case>/jit-run.json per case")
    bs.add_argument("--prereg", type=Path)
    bs.add_argument("--cases", type=Path)
    bs.add_argument("--out", type=Path, required=True)
    del bp
    dg = sub.add_parser("diff-games")
    dg.add_argument("base", type=Path)
    dg.add_argument("head", type=Path)
    dg.add_argument("--out", type=Path, required=True)
    for name in ("report", "gate-summary"):
        s = sub.add_parser(name)
        s.add_argument("record", type=Path)
        if name == "gate-summary":
            s.add_argument("--out", type=Path)
    args = ap.parse_args(argv)

    if args.cmd == "diff-games":
        text = diff_games(args.base, args.head)
        args.out.write_text(text, encoding="utf-8")
        print(json.dumps({"bytes": len(text.encode("utf-8")), "empty": not text.strip()}))
        return 0
    if args.cmd == "measure":
        from expectrail.jit.measure import measure

        profile = load_strict(args.profile, "mechanics-profile")
        report = args.report_file.read_text(encoding="utf-8", errors="replace") if args.report_file else ""
        if not 1 <= args.evidence_jobs <= 8:
            ap.error("--evidence-jobs is between 1 and 8")
        probes = offered_library(profile["actions"], args.offer, report)
        doc = measure(profile, args.base, args.out, probes=probes, game=args.game)
        made = None
        if shows_evidence(args.offer) and args.base:
            # Under this setting the evidence is part of what is offered: a run that cannot make it
            # stops here instead of proposing as if it had been offered.
            made = make_evidence(profile, probes, args.base, args.out, game=args.game,
                                 jobs=args.evidence_jobs)["totals"]
        print(json.dumps({"probes": len(doc["probes"]), "bugBuild": bool(args.base), "evidence": made}))
        return 0
    if args.cmd in ("bench-pins", "bench-check", "bench-score"):
        from expectrail.jit import bench

        if args.cmd == "bench-pins":
            print(json.dumps(bench.pins(), indent=1, sort_keys=True))
            return 0
        prereg = json.loads((args.prereg or bench.PREREG).read_text(encoding="utf-8"))
        if args.cmd == "bench-check":
            problems = bench.check_registration(prereg)
            for p in problems:
                print(f"::error::{p}")
            print(json.dumps({"ok": not problems, "problems": len(problems)}))
            return 1 if problems else 0
        doc = bench.score(bench.load_cases(args.cases or bench.CASES), args.records, prereg["bar"])
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "jit-bench.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        (args.out / "jit-bench.md").write_text(bench.render(doc), encoding="utf-8")
        print(json.dumps({"verdict": doc["verdict"], **doc["totals"]}))
        return 0
    if args.cmd == "revise":
        from expectrail.jit.intent import IntentUnavailable, revise_to_file, spark_intent

        profile = load_strict(args.profile, "mechanics-profile")
        if args.budget_usd < 0:
            ap.error("budget must not be negative")
        prices = {k: v for k, v in (("sparkUsdPerMTokIn", args.spark_usd_per_mtok_in),
                                    ("sparkUsdPerMTokOut", args.spark_usd_per_mtok_out)) if v is not None}
        report = args.report_file.read_text(encoding="utf-8", errors="replace")
        probes = offered_library(profile["actions"], args.offer, report)
        notes = attach_measurements(probes, args.measurements, args.base)
        notes += attach_evidence(probes, args.evidence, args.base, args.offer)
        try:
            doc = revise_to_file(spark_intent(**_intent_settings(args)), report,
                                 args.candidate.read_bytes().decode("utf-8", errors="replace"), profile, probes,
                                 args.proposal, args.record, args.out, budget_usd=args.budget_usd, prices=prices,
                                 notes=notes)
            revised, skipped = doc["revision"]["revised"], doc["revision"]["skipped"]
        except (IntentUnavailable, ValueError, KeyError, OSError) as exc:
            # The first round's record stands; nothing here can turn into a pass or a catch.
            revised, skipped = False, " ".join(str(exc).split())[:200]
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as fh:
                fh.write(f"revised={'true' if revised else 'false'}\n")
        print(json.dumps({"revised": revised, "skipped": skipped}))
        return 0
    if args.cmd == "propose":
        from expectrail.jit.intent import propose_to_file, spark_intent

        profile = load_strict(args.profile, "mechanics-profile")
        if args.budget_usd < 0:
            ap.error("budget must not be negative")
        prices = {k: v for k, v in (("sparkUsdPerMTokIn", args.spark_usd_per_mtok_in),
                                    ("sparkUsdPerMTokOut", args.spark_usd_per_mtok_out)) if v is not None}
        report = args.report_file.read_text(encoding="utf-8", errors="replace")
        probes = offered_library(profile["actions"], args.offer, report)
        notes = attach_measurements(probes, args.measurements, args.base)
        measured = not notes
        notes += attach_evidence(probes, args.evidence, args.base, args.offer)
        doc = propose_to_file(spark_intent(**_intent_settings(args)), report,
                              args.candidate.read_bytes().decode("utf-8", errors="replace"), profile,
                              probes, args.out, budget_usd=args.budget_usd, prices=prices, notes=notes)
        print(json.dumps({"error": doc["error"], "candidates": len(doc["candidates"]), "probes": len(doc["probes"]),
                          "measured": measured,
                          "evidence": any("differs" in p for p in probes)}))
        return 0

    if args.cmd == "run":
        if args.budget_usd < 0 or args.reps < 1 or args.variant_limit < 0:
            ap.error("budget, reps and variant limit must not be negative (reps at least 1)")
        intent = None
        if args.proposal is not None:
            from expectrail.jit.intent import IntentUnavailable, from_proposal

            try:
                intent = from_proposal(args.proposal, offer=args.offer, candidate=_candidate(args))
            except IntentUnavailable as exc:
                reason = str(exc)

                def intent(*_a, _reason=reason):
                    raise IntentUnavailable(_reason)
                intent.model, intent.system, intent.offer = None, "", args.offer
                intent.candidate = _candidate(args)
        elif args.model == "spark":
            from expectrail.jit.intent import spark_intent

            intent = spark_intent(**_intent_settings(args))
        prices = {}
        if args.spark_usd_per_mtok_in is not None:
            prices["sparkUsdPerMTokIn"] = args.spark_usd_per_mtok_in
        if args.spark_usd_per_mtok_out is not None:
            prices["sparkUsdPerMTokOut"] = args.spark_usd_per_mtok_out
        report = args.report_file.read_text(encoding="utf-8", errors="replace")
        doc = generate(args.profile, report, args.candidate, args.base, args.out, intent=intent,
                       budget_usd=args.budget_usd, prices=prices, reps=args.reps, variant_limit=args.variant_limit,
                       run_id=args.run_id, game=args.game, offer=args.offer,
                       candidate_to_model=_candidate(args))
        (args.out / "jit-report.md").write_text(render(doc) + "\n", encoding="utf-8")
        print(json.dumps({"status": doc["status"], "reason": doc["reason"], "counts": doc["counts"],
                          "spendUsd": doc["spend"]["usd"], "record": str(args.out / RECORD_NAME)}))
        return 0
    doc = load_strict(args.record, "jit-run")
    if args.cmd == "report":
        print(render(doc))
    else:
        text = json.dumps(gate_summary(doc), indent=1)
        if args.out:
            args.out.write_text(text + "\n", encoding="utf-8")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
