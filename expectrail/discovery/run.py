"""One advisory discovery job: run generic probes, evaluate profile contracts, reproduce what fails.

    discover(profile, snapshots, out, runner=harness_run, planner=None) -> expectrail.discovery-run/v1

A job has one **reference** snapshot (the approved healthy game, when there is one) and any number of
**base** snapshots (the game as it is, which may already be broken). The same probes run on every
snapshot. Every contract the profile's templates instantiate is evaluated on every episode it applies
to, and every relation on its twin probes.

- A contract that fails on the reference is miscalibrated, not a finding: it is **rejected**, and
  whatever it says about a base snapshot is reported as such, never as a bug.
- A contract that fails on a base snapshot and not on the reference is a **finding**. Its probe is
  replayed from a fresh process until it has run three times; three failures out of three make it
  ``reproduced``, anything less ``flaky_candidate`` with the counts.
- An optional planner (Muse Spark, expectrail/discovery/planner.py) sees the profile and each base
  snapshot's signal summaries, never a bug report or a patch, and may propose more probes and more
  contracts in the closed language. Its contracts go through the same reference check.

Nothing here accepts or rejects a fix; the verifier is unchanged. A completed job with no findings
means no confirmed defect within the probes run and the contracts evaluated, nothing more.
"""
from __future__ import annotations

import json
import shutil
import time
import traceback
from pathlib import Path

from expectrail.contracts import digest_v1, load_strict, validate_v1
from expectrail.discovery.probes import library
from expectrail.discovery.route_compiler import ProgramError, compile_route
from expectrail.discovery.templates import applies_to, instantiate
from expectrail.trace import signals
from harness.run import needs_ui_integers
from expectrail.trace.evaluator import evaluate
from expectrail.trace.normalize import EpisodeError, from_run_dir

REPRO_RUNS = 3
DEFAULT_BUDGET = {"maxEpisodes": 160, "maxJobWallSeconds": 3000, "maxPlannerProbes": 4, "maxPlannerCandidates": 8}


def _sha_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Budget:
    def __init__(self, limits: dict):
        self.limits = {**DEFAULT_BUDGET, **(limits or {})}
        self.episodes = 0
        self.t0 = time.monotonic()
        self.stop: str | None = None

    def take_episode(self) -> bool:
        if self.stop:
            return False
        if self.episodes >= self.limits["maxEpisodes"]:
            self.stop = f"episode cap {self.limits['maxEpisodes']} reached"
            return False
        if time.monotonic() - self.t0 > self.limits["maxJobWallSeconds"]:
            self.stop = f"wall-clock cap {self.limits['maxJobWallSeconds']} s reached"
            return False
        self.episodes += 1
        return True


def _episode(runner, route: dict, route_path: Path, run_dir: Path, patches: list[Path], episode_id: str,
             diagnostics: list[str], *, trace_specs=()) -> dict | None:
    if run_dir.exists():
        shutil.rmtree(run_dir)
    try:
        extra = {"trace_specs": list(trace_specs)} if needs_ui_integers(trace_specs) else {}
        runner(route_path, run_dir, patches=patches, **extra)
        return from_run_dir(run_dir, route, episode_id=episode_id)
    except (EpisodeError, OSError, ValueError, TimeoutError, Exception) as exc:  # noqa: BLE001
        diagnostics.append(f"{episode_id}: {type(exc).__name__}: {' '.join(str(exc).split())[:160]}")
        run_dir.parent.mkdir(parents=True, exist_ok=True)
        (run_dir.parent / f"{run_dir.name}-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return None


def _evaluate_all(entries: list[dict], probes: list[dict], episodes: dict[str, dict | None]) -> list[dict]:
    """[{entry, probeIds, verdict}] for every contract on every episode or pair it applies to."""
    out = []
    for entry in entries:
        if entry["applies"]["kind"] == "pair":
            left, right = episodes.get(entry["applies"]["left"]), episodes.get(entry["applies"]["right"])
            ids = [entry["applies"]["left"], entry["applies"]["right"]]
            if left is None or right is None:
                out.append({"entry": entry, "probeIds": ids, "verdict": None})
                continue
            out.append({"entry": entry, "probeIds": ids, "verdict": evaluate(entry["spec"], left, right)})
            continue
        for probe in probes:
            if not applies_to(entry, probe):
                continue
            ep = episodes.get(probe["id"])
            out.append({"entry": entry, "probeIds": [probe["id"]],
                        "verdict": evaluate(entry["spec"], ep) if ep is not None else None})
    return out


def _result(row: dict) -> str:
    return row["verdict"]["result"] if row["verdict"] is not None else "execution_error"


def discover(profile_path: Path, snapshots: list[dict], out: Path, *, runner=None, planner=None,
             budget: dict | None = None, evidence_label: str = "FRESH LIVE", run_id: str | None = None,
             probe_ids: list[str] | None = None) -> dict:
    """snapshots: [{"name", "role": "reference"|"base", "patch": Path | None}], at most one reference."""
    if runner is None:
        from functools import partial

        from harness.run import run as harness_run

        # Discovery reads the trace only: headless, no frames, about four times faster. The physics is
        # the same; only the camera's view transform differs, and no contract reads it.
        runner = partial(harness_run, capture_frames=False)
    from harness.run import REPO, tree_digest

    out.mkdir(parents=True, exist_ok=True)
    profile = load_strict(Path(profile_path), "mechanics-profile")
    bud = Budget(budget or {})
    diagnostics: list[str] = []
    stages: list[dict] = []
    refs = [s for s in snapshots if s["role"] == "reference"]
    if len(refs) > 1:
        raise ValueError("at most one reference snapshot")
    probes = library(profile["actions"])
    if probe_ids:
        probes = [p for p in probes if p["id"] in set(probe_ids)]
    routes: dict[str, tuple[dict, Path]] = {}
    route_dir = out / "routes"
    route_dir.mkdir(exist_ok=True)

    def add_route(probe: dict) -> bool:
        try:
            route = compile_route(probe["program"], name=probe["id"], description=probe["description"],
                                  actions=profile["actions"])
        except ProgramError as exc:
            diagnostics.append(f"probe {probe['id']} refused by the route compiler: {exc}")
            return False
        path = route_dir / f"{probe['id']}.json"
        path.write_text(json.dumps(route, indent=1) + "\n", encoding="utf-8")
        routes[probe["id"]] = (route, path)
        return True

    probes = [p for p in probes if add_route(p)]
    for p in probes:
        p["source"] = "library"
    entries = instantiate(profile, probes)
    game = REPO / "game" / "platformer"
    snap_meta = []
    episodes: dict[str, dict[str, dict | None]] = {}

    def specs_for(probe):
        return [e["spec"] for e in entries if applies_to(e, probe) or
                (e["applies"]["kind"] == "pair" and probe["id"] in
                 (e["applies"]["left"], e["applies"]["right"]))]

    def run_probes(snap: dict, plist: list[dict]) -> None:
        eps = episodes.setdefault(snap["name"], {})
        patches = [Path(snap["patch"])] if snap.get("patch") else []
        for probe in plist:
            if not bud.take_episode():
                break
            route, path = routes[probe["id"]]
            ep = _episode(runner, route, path, out / snap["name"] / probe["id"], patches,
                          f"{snap['name']}-{probe['id']}", diagnostics, trace_specs=specs_for(probe))
            eps[probe["id"]] = ep
            if ep is not None:
                (out / snap["name"] / probe["id"] / "episode.json").write_text(json.dumps(ep) + "\n", encoding="utf-8")

    for snap in snapshots:
        snap_meta.append({"name": snap["name"], "role": snap["role"],
                          "patchSha256": _sha_file(snap["patch"]) if snap.get("patch") else None,
                          "treeSha256": tree_digest(game)})
        run_probes(snap, probes)
    stages.append({"name": "library probes", "status": "partial" if bud.stop else "complete",
                   "detail": f"{len(probes)} probes on {len(snapshots)} snapshots" + (f"; {bud.stop}" if bud.stop else "")})

    # The planner: more probes and more contracts, from the profile and the base snapshots' signals.
    planner_candidates: list[dict] = []
    if planner is None:
        stages.append({"name": "planner", "status": "skipped", "detail": "no planner configured"})
    else:
        try:
            # Builds are numbered, not named: a snapshot's name may say what is wrong with it.
            bases = [s for s in snapshots if s["role"] == "base"]
            summaries = {f"build-{i + 1}": {pid: signals.summary(ep) for pid, ep in episodes.get(s["name"], {}).items()
                                            if ep is not None}
                         for i, s in enumerate(bases)}
            plan = planner(profile, probes, summaries, bud.limits)
            new = [dict(p, source="planner", tags=sorted(set(p.get("tags") or []))) for p in plan.get("probes", [])
                   ][: bud.limits["maxPlannerProbes"]]
            new = [p for p in new if p["id"] not in routes and add_route(p)]
            already_requested = {p["id"] for p in probes if needs_ui_integers(specs_for(p))}
            planner_candidates = plan.get("candidates", [])[: bud.limits["maxPlannerCandidates"]]
            entries += planner_candidates
            # Existing probes were captured before the planner's spec existed. Recapture only
            # those newly requiring UI data; ordinary planned checks reuse the original trace.
            recapture = [p for p in probes if p["id"] not in already_requested
                         and needs_ui_integers(specs_for(p))]
            probes += new
            for snap in snapshots:
                run_probes(snap, [*new, *recapture])
            stages.append({"name": "planner", "status": "complete",
                           "detail": f"{len(new)} probes and {len(planner_candidates)} contracts proposed; "
                                     f"{plan.get('usage', {})}"})
            for note in plan.get("diagnostics", []):
                diagnostics.append(f"planner: {note}")
        except Exception as exc:  # noqa: BLE001 - an unavailable planner is a recorded stage, never a pass
            stages.append({"name": "planner", "status": "unavailable",
                           "detail": f"{type(exc).__name__}: {' '.join(str(exc).split())[:200]}"})

    # Evaluate everything on every snapshot.
    rows: dict[str, list[dict]] = {s["name"]: _evaluate_all(entries, probes, episodes.get(s["name"], {}))
                                   for s in snapshots}
    rejected: dict[str, str] = {}
    if refs:
        for row in rows[refs[0]["name"]]:
            if _result(row) == "fail":
                sid = row["entry"]["spec"]["id"]
                rejected.setdefault(sid, f"fails on the reference ({refs[0]['name']}) on {', '.join(row['probeIds'])}")
    stages.append({"name": "reference check", "status": "complete" if refs else "skipped",
                   "detail": f"{len(rejected)} contracts fail on the healthy reference and are rejected" if refs
                   else "no reference snapshot: no contract could be falsified"})

    # Findings: failures on a base snapshot, deduplicated by contract, then reproduced.
    findings = []
    for snap in snapshots:
        if snap["role"] != "base":
            continue
        patches = [Path(snap["patch"])] if snap.get("patch") else []
        by_spec: dict[str, list[dict]] = {}
        for row in rows[snap["name"]]:
            if _result(row) == "fail" and row["entry"]["spec"]["id"] not in rejected:
                by_spec.setdefault(row["entry"]["spec"]["id"], []).append(row)
        for sid, failing in by_spec.items():
            first = failing[0]
            entry = first["entry"]
            runs, failures = 1, 1
            for n in range(2, REPRO_RUNS + 1):
                eps = {}
                for pid in first["probeIds"]:
                    if not bud.take_episode():
                        break
                    route, path = routes[pid]
                    eps[pid] = _episode(runner, route, path, out / snap["name"] / f"{pid}-repro{n}", patches,
                                        f"{snap['name']}-{pid}-repro{n}", diagnostics, trace_specs=[entry["spec"]])
                if len(eps) < len(first["probeIds"]):
                    break
                runs += 1
                again = _evaluate_all([entry], [p for p in probes if p["id"] in first["probeIds"]], eps)
                if again and _result(again[0]) == "fail":
                    failures += 1
            v = first["verdict"]
            findings.append({
                "id": f"{snap['name']}-{sid}",
                "snapshot": snap["name"],
                "specId": sid,
                "origin": entry["spec"]["origin"],
                "expectationRef": dict(entry["spec"]["expectationRef"], source=entry.get("source", "template")),
                "probeIds": first["probeIds"],
                "lifecycle": "reproduced" if failures == REPRO_RUNS else ("flaky_candidate" if runs >= REPRO_RUNS or failures < runs else "proposed"),
                "reproduction": {"runs": runs, "failures": failures},
                "observation": (v["evidence"][0]["detail"] if v["evidence"] else entry["spec"]["statement"]),
                "evidence": v["evidence"][:4] + [{"failingProbes": [",".join(r["probeIds"]) for r in failing][:8],
                                                   "metrics": v["metrics"]}],
                "alternatives": _alternatives(entry),
            })
    stages.append({"name": "reproduction", "status": "partial" if bud.stop else "complete",
                   "detail": f"{len(findings)} findings, each replayed up to {REPRO_RUNS} times"})

    verdict_rows = [{"snapshot": name, "specId": r["entry"]["spec"]["id"], "probeIds": r["probeIds"],
                     "result": _result(r), "triggeredCount": (r["verdict"] or {}).get("triggeredCount", 0),
                     "evaluatedCount": (r["verdict"] or {}).get("evaluatedCount", 0)}
                    for name, rs in rows.items() for r in rs]
    candidates = [{"specId": e["spec"]["id"], "source": e.get("source", "template"),
                   "lifecycle": "rejected" if e["spec"]["id"] in rejected else "proposed",
                   "referenceResult": _ref_result(rows, refs, e["spec"]["id"]),
                   "detail": rejected.get(e["spec"]["id"]) or e["spec"]["statement"]}
                  for e in entries]
    coverage = {name: {"episodes": sum(1 for ep in episodes.get(name, {}).values() if ep is not None),
                       "results": {res: sum(1 for r in rs if _result(r) == res)
                                   for res in ("pass", "fail", "not_exercised", "insufficient_observation",
                                               "execution_error")}}
                for name, rs in rows.items()}
    doc = {
        "format": "expectrail.discovery-run/v1",
        "runId": run_id or out.name,
        "mode": "discover",
        "evidenceLabel": evidence_label,
        "contextManifest": {
            "condition": "development-reproduction",
            "supplied": ["mechanics profile (claims read from the clean game's code and settings)",
                         "generic probe library", "per-probe signal summaries of the base snapshots (planner only)"],
            "withheld": ["bug reports", "patches and diffs", "the reported bugs' routes",
                         "the hand-written trace rules and guards of the reported-bug bench"],
        },
        "profile": {"id": profile["id"], "sha256": digest_v1(profile)},
        "snapshots": snap_meta,
        "stages": stages,
        "probes": [{"id": p["id"], "family": p["family"], "source": p["source"],
                    "routeSha256": digest_v1(routes[p["id"]][0]), "ticks": routes[p["id"]][0]["ticks"]} for p in probes],
        "verdicts": verdict_rows,
        "findings": findings,
        "candidates": candidates,
        "coverage": coverage,
        "usage": {"episodes": bud.episodes, "wallSeconds": round(time.monotonic() - bud.t0, 1)},
        "completion": "partial" if bud.stop else "complete",
        "stopReason": bud.stop,
        "diagnostics": diagnostics[:50],
    }
    validate_v1(doc, "discovery-run")
    (out / "discovery-run.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return doc


def _ref_result(rows: dict, refs: list[dict], spec_id: str) -> str | None:
    if not refs:
        return None
    results = {_result(r) for r in rows[refs[0]["name"]] if r["entry"]["spec"]["id"] == spec_id}
    for res in ("fail", "execution_error", "insufficient_observation", "pass", "not_exercised"):
        if res in results:
            return res
    return None


def _alternatives(entry: dict) -> list[str]:
    """What else could explain a failure, for the person reviewing it."""
    alts = ["the profile's claim is wrong for this game, or its exceptions are incomplete"]
    if entry["spec"]["expectationRef"]["authority"] in ("inferred_code", "inferred_behavior", "model_prior"):
        alts.append("the claim was inferred, not approved: the game may intend this behaviour")
    if entry["spec"]["operation"]["type"] == "relation":
        alts.append("the twin probes differ in more than the one thing the relation assumes")
    return alts
