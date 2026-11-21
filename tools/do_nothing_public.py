"""Measure the do-nothing control (#675, piece 1) on the public bench's recorded generated checks.

For every trace check in the committed public records (``bench/jit/recordings/public-43465090517``), the
check's probes are replayed three times on the clean game with the do-nothing control for the check's class
(expectrail/jit/do_nothing.py) and judged with the generator's own evaluation (``run._evaluate``). Nothing
else is replayed: the clean-reference runs are the recorded ones. No model is called and nothing is spent
beyond the local engine.

    python3 tools/do_nothing_public.py --work NEW_FOLDER --out docs/measurements/675-do-nothing-control.md

Public records only: a held-out or ``fresh-*`` path is refused. The work folder keeps every control patch,
route, trace and the per-check rows (``rows.json``). Each row names its record and its check by digest
(``sourceRun``, ``specSha256``), so ``expectrail.jit.counting public-bench --do-nothing-rows`` can bind it. A
model-proposed probe's route is used when it is supplied in ``jit-routes`` beside its record with the digest the
record names; otherwise its checks are not run. Advisory: this changes no record and no rule.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from expectrail.contracts import digest_v1  # noqa: E402
from expectrail.jit import assess, bench, do_nothing  # noqa: E402
from expectrail.jit.counting import public_custom_route  # noqa: E402

RECORDS = REPO / "bench/jit/recordings/public-43465090517/repro"


def library_routes(profile: dict) -> dict[str, dict]:
    from expectrail.discovery.route_compiler import compile_route
    from expectrail.jit.probes import jit_library

    out = {}
    for p in jit_library(profile["actions"]):
        route = compile_route(p["program"], name=p["id"], description=p["description"], actions=profile["actions"])
        out[digest_v1(route)] = route
    return out


class Replays:
    """Replays of (control class, route), REPS times each, kept only when the three traces are identical."""

    def __init__(self, work: Path, game: Path, runner=None):
        self.work, self.game = work, game
        self.runner = runner
        self.episodes: dict[tuple[str, str, bool], list | None] = {}
        self.evidence: dict[str, list] = {}

    def get(self, cls: str, patch: Path, sha: str, route: dict, ui: bool):
        from harness.run import run
        from expectrail.trace.normalize import from_run_dir

        key = (cls, sha, ui)
        if key in self.episodes:
            return self.episodes[key]
        folder = self.work / "replays" / f"{cls}-{sha[:16]}{'-ui' if ui else ''}"
        folder.mkdir(parents=True)
        path = folder / "route.json"
        path.write_text(json.dumps(route, indent=1) + "\n")
        eps, runs = [], []
        for rep in range(assess.REPS):
            out = folder / f"run-{rep + 1}"
            try:
                rec = (self.runner or run)(path, out, game=self.game, patches=[patch], capture_frames=False,
                                           ui_integers=ui)
                runs.append({"trace": hashlib.sha256((out / "trace.json").read_bytes()).hexdigest(),
                             "engine": rec.get("engine"), "patchSha256": rec.get("game", {}).get("patchSha256")})
                eps.append(from_run_dir(out, route, episode_id=f"{cls}-{sha[:8]}-{rep}"))
            except Exception as exc:  # noqa: BLE001 - recorded, and the rows for this route are not-run
                runs.append({"error": " ".join(str(exc).split())[:300]})
                break
        stable = len(eps) == assess.REPS and len({r.get("trace") for r in runs}) == 1
        self.evidence[folder.name] = runs
        self.episodes[key] = eps if stable else None
        return self.episodes[key]


def measure(work: Path, records: Path = RECORDS, game: Path = REPO / "game/platformer", runner=None) -> dict:
    from expectrail.jit.run import _evaluate
    from harness.run import needs_ui_integers

    if bench.private_name(records) or bench.private_name(Path(records).resolve()):
        raise ValueError("public-only: held-out/fresh record roots refused")
    work = Path(work)
    work.mkdir(parents=True, exist_ok=False)
    profile = json.loads((REPO / "discovery/platformer.profile.json").read_text())
    routes = library_routes(profile)
    controls = {c["class"]: c for c in do_nothing.controls(game, profile, do_nothing.CLASSES)}
    patches = {}
    for cls, c in controls.items():
        if c["patchText"]:
            patches[cls] = work / f"do-nothing-{cls}.patch"
            patches[cls].write_text(c["patchText"])
    replays = Replays(work, game, runner)
    rows = []
    for defect in bench.public_cases()["defects"]:
        path = Path(records) / f"repro-{defect['id']}" / "jit-run.json"
        if path.resolve() != path.absolute():
            raise ValueError("public record path cannot be a link")
        run = json.loads(path.read_text())
        probes = {p["id"]: p["routeSha256"] for p in run["probes"]}
        validity = {v["specId"]: v for v in run["validity"]}
        for entry in run["proposed"]:
            spec = entry["spec"]
            cls = spec["scope"]["class"]
            v = validity.get(spec["id"], {})
            row = {"defect": defect["id"], "check": spec["id"], "specSha256": digest_v1(spec),
                   "sourceRun": digest_v1(run), "class": cls,
                   "operation": spec["operation"]["type"], "signal": spec["operation"].get("signal"),
                   "recordedReference": v.get("reference", []), "recordedValid": bool(v.get("valid")),
                   "runs": [], "outcome": "not-run", "reason": None}
            rows.append(row)
            if cls not in patches:
                row["reason"] = controls[cls]["reason"]
                continue
            # A model-proposed probe's route is used when it is supplied beside the record (``jit-routes``,
            # from the run's public artifact) with the digest the record names; otherwise the check is not run.
            found = {pid: routes.get(probes.get(pid)) or public_custom_route(path.parent, pid, probes.get(pid))
                     for pid in entry["probeIds"]}
            missing = [pid for pid, route in found.items() if route is None]
            if missing:
                row["reason"] = ("route not in the probe library (a model-proposed probe) and not supplied beside "
                                 "the record: " + ", ".join(missing))
                continue
            ui = needs_ui_integers([spec])
            eps_by_probe = {}
            for pid in entry["probeIds"]:
                eps_by_probe[pid] = replays.get(cls, patches[cls], probes[pid], found[pid], ui)
            if any(e is None for e in eps_by_probe.values()):
                row["reason"] = "replay failed or its three traces differed"
                continue
            for rep in range(assess.REPS):
                outcome, why = do_nothing.judge(entry, entry["probeIds"],
                                                {pid: eps[rep] for pid, eps in eps_by_probe.items()},
                                                _evaluate, controls[cls]["mode"])
                row["runs"].append(outcome)
                row["reason"] = why or row["reason"]
            row["outcome"] = assess.do_nothing(row["runs"])
    doc = {"controls": [{k: c[k] for k in ("class", "mode", "files", "reason")} |
                        {"patchSha256": hashlib.sha256(c["patchText"].encode()).hexdigest() if c["patchText"] else None}
                        for c in controls.values()],
           "records": str(Path(records).relative_to(REPO)) if Path(records).is_relative_to(REPO) else str(records),
           "evidence": replays.evidence, "rows": rows}
    (work / "rows.json").write_text(json.dumps(doc, indent=1) + "\n")
    return doc


def summary(doc: dict) -> dict:
    rows = doc["rows"]
    on_ref = [r for r in rows if r["recordedReference"] == ["pass"] * assess.REPS]
    count = lambda rs, o: sum(1 for r in rs if r["outcome"] == o)  # noqa: E731
    outcomes = ("passes", "fails", "indeterminate", "not-run")
    return {"checks": len(rows), "onReference": len(on_ref),
            "onReferenceOutcomes": {o: count(on_ref, o) for o in outcomes},
            "keptByOldRule": sum(1 for r in rows if r["recordedValid"]),
            "keptByOldRuleNowDropped": sum(1 for r in rows if r["recordedValid"] and r["outcome"] == "passes"),
            "byClass": {cls: {o: count([r for r in on_ref if r["class"] == cls], o) for o in outcomes}
                        for cls in do_nothing.CLASSES}}


def markdown(doc: dict, engine: str) -> str:
    s = summary(doc)
    lines = ["# Do-nothing control on the public bench's recorded checks (#675, piece 1)", "",
             "Each trace check in the committed public records was replayed three times on the clean game with the "
             "do-nothing control for its class, and judged by the generator's own evaluation. The clean-reference "
             "runs are the recorded ones; they were not replayed here. No model was called. Advisory: no record or "
             "counting rule changed.", "",
             f"Engine: {engine}. Records: `{doc['records']}`.", "",
             "## Controls made from the game", "",
             "| Class | Mode | File | Patch SHA-256 |", "| --- | --- | --- | --- |"]
    for c in doc["controls"]:
        lines.append(f"| {c['class']} | {c['mode'] or 'none: ' + str(c['reason'])} | {', '.join(c['files'])} | "
                     f"`{c['patchSha256'] or '-'}` |")
    o = s["onReferenceOutcomes"]
    lines += ["", "## Counts", "",
              f"- Checks in the records: {s['checks']}. Recorded as passing the clean reference 3 of 3: {s['onReference']}.",
              f"- Of those {s['onReference']}: **{o['passes']} pass the control** (would now be dropped), "
              f"{o['fails']} fail it, {o['indeterminate']} are indeterminate (not exercised, mixed, or depending on "
              f"the frozen player's floor state), "
              f"{o['not-run']} not run.",
              f"- Kept by the old rule (recorded valid): {s['keptByOldRule']}; of these, "
              f"**{s['keptByOldRuleNowDropped']} pass the control** and would now be dropped.", "",
              "| Class | Passes (dropped) | Fails | Indeterminate | Not run |", "| --- | --- | --- | --- | --- |"]
    for cls, b in s["byClass"].items():
        lines.append(f"| {cls} | {b['passes']} | {b['fails']} | {b['indeterminate']} | {b['not-run']} |")
    lines += ["", "## Per check", "",
              "| Public defect | Check | Class | Predicate | Recorded valid | Control runs | Outcome |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in doc["rows"]:
        pred = r["operation"] + (f" `{r['signal']}`" if r["signal"] else "")
        why = f" ({r['reason']})" if r["reason"] else ""
        lines.append(f"| {r['defect']} | `{r['check']}` | {r['class']} | {pred} | {'yes' if r['recordedValid'] else 'no'} | "
                     f"{', '.join(r['runs']) or '-'} | {r['outcome']}{why} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--work", type=Path, required=True, help="a new folder for patches, replays and rows.json")
    ap.add_argument("--out", type=Path, required=True, help="the markdown measurement to write")
    ap.add_argument("--records", type=Path, default=RECORDS)
    args = ap.parse_args(argv)
    doc = measure(args.work, args.records)
    engines = sorted({(r.get("engine") or {}).get("version", "?") for runs in doc["evidence"].values()
                      for r in runs if "engine" in r})
    args.out.write_text(markdown(doc, ", ".join(str(e) for e in engines) or "no completed replay"))
    print(json.dumps(summary(doc)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
