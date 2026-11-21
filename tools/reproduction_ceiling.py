"""Validate the hand-written reproduction checks of issue #762 on the local engine.

For each defect under ``bench/jit/ceiling/<defect>/`` the round files (``round1.json``, and ``round2.json``
when a revision was written) are answers in the generator's own planner format, written by hand from the
report, the clean game and the probe library. Each is turned into a proposal by the generator's own code
(``intent.spark_intent`` with a transport that returns the hand answer, then ``intent.propose_to_file``),
under the ``signals-reach-evidence-menu-control`` offer with the candidate withheld, so a check the closed
language or the offer refuses is refused here too. Each check is then replayed three times on four arms:

- ``clean``: the bundled game;
- ``defect``: the game with the defect's patch (never read here, only applied by the harness);
- ``control``: the do-nothing control for the check's class (expectrail/jit/do_nothing.py), judged as the
  generator judges it (``do_nothing.judge``), so a frozen player's floor state can make a run "cannot tell";
- ``harmless``: the game with the registered comment-only edit (``agents/fixtures/operators/comment-only.patch``).

Each run is judged by the generator's own evaluation (``run._evaluate``). The clearance is by how much the
clean runs clear the check's bound at their tightest (positive: passes by that much), and the defect's
margin by how much its runs miss it at their loosest (negative: fails by that much). Where a defect has more
than one check, ``compound`` judges every check on the same run together: a run passes only when every check
passes, and fails when any check fails.

    python3 tools/reproduction_ceiling.py --work NEW_FOLDER --rows bench/jit/ceiling/rows.json

No model is called, nothing is dispatched and nothing is spent beyond the local engine. Public defects only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from expectrail.contracts import digest_v1  # noqa: E402
from expectrail.jit import assess, bench  # noqa: E402

FORMAT = "expectrail.reproduction-ceiling/v1"
OFFER = "signals-reach-evidence-menu-control"
CEILING = REPO / "bench/jit/ceiling"
HARMLESS = REPO / "agents/fixtures/operators/comment-only.patch"
DEFECTS = {
    "slow-left": {"report": "bench/jit/public/slow-left/report.txt",
                  "patch": "bench/jit/public/slow-left/defect.patch", "shape": "a directional magnitude asymmetry"},
    "slides-after-stop": {"report": "bench/jit/public/slides-after-stop/report.txt",
                          "patch": "bench/jit/public/slides-after-stop/defect.patch", "shape": "a decay after release"},
    "air-jump": {"report": "bench/jit/known/air-jump/report.txt",
                 "patch": "bugs/reported/air-jump.patch", "shape": "a bound on an event count"},
}
ARMS = ("clean", "defect", "control", "harmless")
ROUND_FILES = ("round1.json", "round2.json")


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --- pure parts (tested without the engine) -----------------------------------------------------------------

def margin(op: dict, left, right) -> float | None:
    """How far ``right`` clears the relation's bound against ``left`` (positive passes, negative fails)."""
    if left is None or right is None:
        return None
    t = op["toleranceAbs"]
    cmp = op["comparator"]
    if cmp == "lt":
        value = left - (right + t)
    elif cmp == "gt":
        value = right - (left + t)
    elif cmp == "lte":
        value = (left + t) - right
    elif cmp == "gte":
        value = right - (left - t)
    elif cmp == "eq":
        value = t - abs(right - left)
    else:
        raise ValueError(f"unknown comparator {cmp!r}")
    return round(value, 4)


def summarise(runs: list[str]) -> str:
    """``pass 3/3``, ``fail 3/3``, or the runs as they came."""
    if len(runs) == assess.REPS and len(set(runs)) == 1:
        return f"{runs[0]} {assess.REPS}/{assess.REPS}"
    return ", ".join(runs) if runs else "not run"


def compound_run(results: list[str]) -> str:
    """One run of several checks judged together: fail if any fails, pass only if all pass."""
    if any(r == "fail" for r in results):
        return "fail"
    if results and all(r == "pass" for r in results):
        return "pass"
    return "insufficient_observation"


def verdict(arms: dict) -> dict:
    """Whether the generator's keep rule would keep this check as a reproduction, with the reasons."""
    reasons = []
    if arms["clean"]["runs"] != ["pass"] * assess.REPS:
        reasons.append("does not pass the clean game 3/3")
    control = assess.do_nothing(arms["control"]["runs"])
    if control == "passes":
        reasons.append("passes the do-nothing control")
    if arms["defect"]["runs"] != ["fail"] * assess.REPS:
        reasons.append("does not fail the defect 3/3")
    harmless = assess.harmless_outcome(arms["clean"]["runs"], arms["harmless"]["runs"])
    if harmless != "pass":
        reasons.append(f"harmless edit: {harmless}")
    return {"reproduces": not reasons, "control": control, "harmless": harmless, "reasons": reasons}


# --- the engine part --------------------------------------------------------------------------------------

class Replays:
    """Three replays of (arm, route), kept only when the three traces are identical."""

    def __init__(self, work: Path, game: Path, runner=None):
        self.work, self.game, self.runner = work, game, runner
        self.episodes: dict[tuple[str, str], list | None] = {}
        self.evidence: dict[str, list] = {}

    def get(self, arm: str, patches: list[Path], route: dict):
        from harness.run import run
        from expectrail.trace.normalize import from_run_dir

        sha = digest_v1(route)
        key = (arm, sha)
        if key in self.episodes:
            return self.episodes[key]
        folder = self.work / "replays" / f"{arm}-{route['name']}-{sha[:12]}"
        folder.mkdir(parents=True)
        path = folder / "route.json"
        path.write_text(json.dumps(route, indent=1) + "\n")
        eps, runs = [], []
        for rep in range(assess.REPS):
            out = folder / f"run-{rep + 1}"
            try:
                rec = (self.runner or run)(path, out, game=self.game, patches=list(patches), capture_frames=False)
                runs.append({"trace": _sha(out / "trace.json"), "engine": rec.get("engine"),
                             "isolation": (rec.get("isolation") or {}).get("mode"),
                             "sandbox": (rec.get("isolation") or {}).get("sandbox"),
                             "patchSha256": rec.get("game", {}).get("patchSha256")})
                eps.append(from_run_dir(out, route, episode_id=f"{arm}-{route['name']}-{rep}"))
            except Exception as exc:  # noqa: BLE001 - recorded; the rows for this route are not run
                runs.append({"error": " ".join(str(exc).split())[:300]})
                break
        stable = len(eps) == assess.REPS and len({r.get("trace") for r in runs}) == 1
        self.evidence[folder.name] = runs
        self.episodes[key] = eps if stable else None
        return self.episodes[key]


def proposal_for(defect: str, answer_path: Path, out: Path, profile: dict, probes: list[dict]) -> dict:
    """The generator's own proposal from a hand answer: same parser, same offer, candidate withheld."""
    from expectrail.jit import intent

    content = answer_path.read_text(encoding="utf-8")

    def transport(body: dict) -> dict:
        return {"choices": [{"message": {"content": content}}], "usage": {}}

    hand = intent.spark_intent(transport=transport, model="hand-written", offer=OFFER, candidate=intent.WITHHELD)
    report = (REPO / DEFECTS[defect]["report"]).read_text(encoding="utf-8")
    return intent.propose_to_file(hand, report, "", profile, probes, out)


def measure(work: Path, defects=None, runner=None, game: Path = REPO / "game/platformer") -> dict:
    from expectrail.discovery.route_compiler import compile_route
    from expectrail.jit import do_nothing
    from expectrail.jit.probes import jit_library
    from expectrail.jit.run import _evaluate
    from expectrail.trace.evaluator import evaluate
    from harness.run import tree_digest

    work = Path(work)
    if bench.private_name(work) or bench.private_name(work.resolve()):
        raise ValueError("public-only: a held-out or fresh-* work folder is refused")
    work.mkdir(parents=True, exist_ok=False)
    profile = json.loads((REPO / "discovery/platformer.profile.json").read_text())
    library = jit_library(profile["actions"])
    controls = {c["class"]: c for c in do_nothing.controls(game, profile, do_nothing.CLASSES)}
    control_patches = {}
    for cls, c in controls.items():
        if c["patchText"]:
            control_patches[cls] = work / f"do-nothing-{cls}.patch"
            control_patches[cls].write_text(c["patchText"])
    replays = Replays(work, game, runner)
    doc = {"format": FORMAT, "offer": OFFER, "candidate": "withheld", "reps": assess.REPS,
           "gameTree": tree_digest(game), "harmlessPatchSha256": _sha(HARMLESS),
           "doNothing": {cls: {"mode": c["mode"], "patchSha256": hashlib.sha256(c["patchText"].encode()).hexdigest()
                               if c["patchText"] else None, "reason": c.get("reason")}
                         for cls, c in sorted(controls.items())},
           "defects": []}
    for defect in defects or DEFECTS:
        spec = DEFECTS[defect]
        patch = REPO / spec["patch"]
        row = {"id": defect, "shape": spec["shape"], "report": spec["report"],
               "reportSha256": _sha(REPO / spec["report"]), "patch": spec["patch"], "patchSha256": _sha(patch),
               "rounds": []}
        for name in ROUND_FILES:
            answer = CEILING / defect / name
            if not answer.exists():
                continue
            proposal = proposal_for(defect, answer, work / defect / name.removesuffix(".json"), profile, library)
            if proposal.get("error"):
                raise ValueError(f"{defect} {name}: the generator refused the answer: {proposal['error']}")
            probes = {p["id"]: p for p in library}
            probes.update({p["id"]: p for p in proposal["probes"]})
            routes = {pid: compile_route(p["program"], name=pid, description=p.get("description", ""),
                                         actions=profile["actions"]) for pid, p in probes.items()}
            checks = []
            per_run: dict[str, list[list[str]]] = {arm: [[] for _ in range(assess.REPS)] for arm in ARMS}
            for entry in proposal["candidates"]:
                a = entry["applies"]
                if a["kind"] != "pair":
                    raise ValueError(f"{defect} {name}: only relation checks are measured here")
                ids = [a["left"], a["right"]]
                cls = entry["spec"]["scope"]["class"]
                arm_patches = {"clean": [], "defect": [patch], "harmless": [HARMLESS],
                               "control": [control_patches[cls]] if cls in control_patches else None}
                arms = {}
                for arm in ARMS:
                    if arm_patches[arm] is None:
                        arms[arm] = {"runs": [], "metrics": []}
                        continue
                    eps = {pid: replays.get(arm, arm_patches[arm], routes[pid]) for pid in ids}
                    if any(v is None for v in eps.values()):
                        arms[arm] = {"runs": ["execution_error"], "metrics": []}
                        continue
                    runs, metrics, reasons = [], [], []
                    for rep in range(assess.REPS):
                        one = {pid: eps[pid][rep] for pid in ids}
                        if arm == "control":
                            outcome, reason = do_nothing.judge(entry, ids, one, _evaluate, controls[cls]["mode"])
                            if reason:
                                reasons.append(reason)
                        else:
                            outcome = _evaluate(entry, ids, one)
                        m = evaluate(entry["spec"], one[ids[0]], one[ids[1]])["metrics"]
                        runs.append(outcome)
                        metrics.append({"left": m.get("left"), "right": m.get("right")})
                    arms[arm] = {"runs": runs, "metrics": metrics}
                    if reasons:
                        arms[arm]["reasons"] = sorted(set(reasons))
                for arm in ARMS:
                    for rep, outcome in enumerate(arms[arm]["runs"][:assess.REPS]):
                        per_run[arm][rep].append(outcome)
                op = entry["spec"]["operation"]
                clean_m = [margin(op, m["left"], m["right"]) for m in arms["clean"]["metrics"]]
                defect_m = [margin(op, m["left"], m["right"]) for m in arms["defect"]["metrics"]]
                checks.append({
                    "specId": entry["spec"]["id"], "specSha256": digest_v1(entry["spec"]),
                    "statement": entry["spec"]["statement"], "claimId": entry["spec"]["expectationRef"]["claimId"],
                    "class": cls, "operation": op, "probes": ids,
                    "routeSha256": {pid: digest_v1(routes[pid]) for pid in ids},
                    "arms": arms,
                    "clearance": {"clean": min(clean_m) if clean_m and None not in clean_m else None,
                                  "defect": max(defect_m) if defect_m and None not in defect_m else None},
                    **verdict(arms)})
            rnd = {"round": int(name[5]), "answerSha256": _sha(answer),
                   "proposalSha256": digest_v1(proposal), "checks": checks}
            if len(checks) > 1:
                arms = {arm: {"runs": [compound_run(rs) for rs in per_run[arm] if rs]} for arm in ARMS}
                rnd["compound"] = {"specIds": [c["specId"] for c in checks], "arms": arms, **verdict(arms)}
            row["rounds"].append(rnd)
        doc["defects"].append(row)
    doc["replays"] = replays.evidence
    engines = {json.dumps(r.get("engine"), sort_keys=True) for runs in replays.evidence.values() for r in runs
               if r.get("engine")}
    doc["engines"] = sorted(json.loads(e) for e in engines) if engines else []
    return doc


# --- the published table ------------------------------------------------------------------------------------

def _fmt(x) -> str:
    if x is None:
        return "no reading"
    return f"{x:g}"


def render(doc: dict) -> str:
    lines = ["| Defect | Round | Check | Clean | Defect | Do-nothing control | Harmless edit | Clearance (clean) "
             "| Defect margin | Kept as a reproduction |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for d in doc["defects"]:
        for rnd in d["rounds"]:
            for c in rnd["checks"]:
                a = c["arms"]
                lines.append(f"| `{d['id']}` | {rnd['round']} | `{c['specId']}` {c['operation']['comparator']} "
                             f"`{c['operation']['signal']}` | {summarise(a['clean']['runs'])} | "
                             f"{summarise(a['defect']['runs'])} | {c['control']} ({summarise(a['control']['runs'])}) | "
                             f"{c['harmless']} | {_fmt(c['clearance']['clean'])} px | {_fmt(c['clearance']['defect'])} px | "
                             f"{'yes' if c['reproduces'] else 'no: ' + '; '.join(c['reasons'])} |")
            if "compound" in rnd:
                k = rnd["compound"]
                a = k["arms"]
                lines.append(f"| `{d['id']}` | {rnd['round']} | both, judged together | {summarise(a['clean']['runs'])} | "
                             f"{summarise(a['defect']['runs'])} | {k['control']} ({summarise(a['control']['runs'])}) | "
                             f"{k['harmless']} | | | "
                             f"{'yes, if one check could say both' if k['reproduces'] else 'no: ' + '; '.join(k['reasons'])} |")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--work", type=Path, required=True, help="a new folder for routes, patches and traces")
    p.add_argument("--rows", type=Path, required=True, help="where to write the rows (JSON)")
    p.add_argument("--defect", action="append", choices=sorted(DEFECTS), help="only this defect (repeatable)")
    args = p.parse_args(argv)
    doc = measure(args.work, args.defect)
    args.rows.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    print(render(doc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
