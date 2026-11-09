"""Held-out detection benchmark: would the verifier catch each private bug variant?

Each held-out bug variant lives only in the private held-out set (its patch and description never
enter this repository). For one variant, this renders the game with that variant and no fix on the
smoke route and on every private route, then judges each replay with the checks the verifier runs
on a candidate:

  - engine: the ground spec on the position log against the clean level's ground line (what the
    verifier uses with SAM off);
  - hybrid: the ground spec on SAM's box for the robot against the same line (SAM on);
  - each SAM spec (player-always-visible, coins-visible) on SAM's view of the frames (SAM on);
  - gameplay: the motion check with the route's own threshold (both).

A variant is caught when a check fails on at least one route. ``--clean`` runs the same checks on
the unpatched game: any failure there is a false alarm.

``--set dev`` runs the public development variants (``bugs/<family>/vN.patch``, ids
``dev/<family>/vN``) through exactly the same routes and checks, so development and held-out
detection are measured the same way and reported separately.

Only the variant id, counts and verdicts are printed. The manifest's descriptions, route names,
frames and traces stay in the output directory, which callers must not publish. Exit is 1 when the
run decided nothing, so a green job always means the checks ran.

``--stability`` (off by default) replays every route where a check failed until it has run three
times (``--stability-runs``) and keeps a check's result only when every replay is identical and the
check said the same each time; anything else is needs-review (agents/stability.py). With SAM on,
each extra replay sends SAM its frames again.

    EXPECTRAIL_HELDOUT_DIR=../Expectrail-heldout python3 -m agents.heldout_bench --list
    EXPECTRAIL_HELDOUT_DIR=... python3 -m agents.heldout_bench --list --set dev
    EXPECTRAIL_HELDOUT_DIR=... EXPECTRAIL_OBS_PROVIDER=sam MODEL_API_KEY=... \\
        python3 -m agents.heldout_bench --variant physics-fall-through/v5 --out runs/bench
    ... --clean --out runs/bench          # the false-alarm control
    python3 -m agents.heldout_bench --annotate runs/bench/physics-fall-through_v5/bench.json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from agents import stability
from agents.gameplay import MIN_DELTA_X_HARNESS, judge_trace
from agents.patchutil import sha256_file
from agents.sam_observations import sam_images_since, sam_usage
from agents.verifier import (
    REGRESSION_SPEC, _ground_observations, _sam_verdicts, held_out_set, reference_surfaces, sam_on, sam_specs,
)
from harness.run import REPO, run as harness_run
from expectrail.contracts import load
from expectrail.evaluator import evaluate

SMOKE_ROUTE = REPO / "harness" / "routes" / "smoke.json"
BUGS = REPO / "bugs"
CLEAN = "clean"
DEV_PREFIX = "dev/"
SETS = ("held-out", "dev")
# The spec each public family is aimed at (docs/evaluation.md); informational only.
DEV_FAMILY_SPECS = {"physics-fall-through": "player-stays-above-ground", "sinking": "player-stays-above-ground",
                    "missing-texture": "coins-visible", "layering": "player-always-visible"}
RESULTS = ("fail", "needs-review", "pass")
# Which checks decide the verifier's verdict in each mode.
SAM_ON_CHECKS = ("hybrid", "gameplay")  # plus every SAM spec
SAM_OFF_CHECKS = ("engine", "gameplay")
# EXPECTRAIL_VISION_BACKEND=glimmer-engine: the vision specs on Glimmer checked against the engine, the
# ground on the position log (the verifier does the same; Glimmer's box is too loose for the hybrid).
GLIMMER_ENGINE_CHECKS = ("engine", "gameplay")  # plus every vision spec
ERRORS_FILE = "bench-errors.json"


def public_error(message: str) -> str:
    """An error message fit to print: directories stripped (they name private routes), one line, short."""
    return re.sub(r"(?<![\w:/.])(?:/[^\s/:'\"]+)+/", "", " ".join(str(message).split()))[:200]


def variant_key(entry: dict) -> str:
    return f"{entry['family']}/{entry['id']}"


def active_variants(manifest: dict) -> list[dict]:
    """Variants in the benchmark: every manifest entry not marked retired."""
    return [v for v in manifest.get("variants") or [] if not v.get("retired")]


def dev_variants(bugs: Path | None = None) -> dict[str, Path]:
    """The public development variants, ``dev/<family>/vN`` -> patch, sorted."""
    root = bugs or BUGS
    return {f"{DEV_PREFIX}{p.parent.name}/{p.stem}": p for p in sorted(root.glob("*/v*.patch"))}


def set_ids(manifest: dict, which: str) -> list[str]:
    """Every id ``--list`` offers for one set, the clean control first."""
    if which == "dev":
        return [CLEAN] + list(dev_variants())
    return [CLEAN] + [variant_key(v) for v in active_variants(manifest)]


def _routes(root: Path, manifest: dict) -> list[tuple[str, Path, float]]:
    rows = [("smoke", SMOKE_ROUTE, MIN_DELTA_X_HARNESS)]
    for entry in manifest["routes"]:
        rows.append((str(entry.get("name") or Path(entry["file"]).stem), root / entry["file"],
                     float(entry["minDeltaX"])))
    return rows


def _render(route: Path, run_dir: Path, patches: list[Path]) -> dict:
    # Godot has aborted on back-to-back imports in CI; one retry, as the verifier does.
    try:
        return harness_run(route, run_dir, patches=patches)
    except (subprocess.CalledProcessError, OSError, TimeoutError):
        return harness_run(route, run_dir, patches=patches)


def judge_route(route: Path, min_dx: float, patches: list[Path], run_dir: Path, ground_spec: dict,
                sam_spec_docs: list[dict], reference: list | None, use_sam: bool,
                hybrid: bool = True) -> dict[str, str]:
    """Every check's result on one replay. A replay or SAM failure is needs-review, never pass.

    ``hybrid=False`` (judge glimmer-engine) leaves out the hybrid ground check: the ground is judged
    on the position log only, as the verifier does under that judge.
    """
    hybrid = hybrid and use_sam
    names = ["engine", "gameplay"] + (["hybrid"] if hybrid else []) + (
        [s["id"] for s in sam_spec_docs] if use_sam else [])
    try:
        _render(route, run_dir, patches)
        trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
        replay_sha = sha256_file(run_dir / "replay.json")
    except (subprocess.CalledProcessError, OSError, TimeoutError, ValueError) as exc:
        (run_dir / "bench-error.txt").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        return {n: "needs-review" for n in names}
    return _judge_replay(trace, replay_sha, run_dir, min_dx, ground_spec, sam_spec_docs, reference, use_sam,
                         hybrid)


def _judge_replay(trace: dict, replay_sha: str, run_dir: Path, min_dx: float, ground_spec: dict,
                  sam_spec_docs: list[dict], reference: list | None, use_sam: bool, hybrid: bool) -> dict[str, str]:
    """Every check's result on a replay already in ``run_dir`` (``hybrid`` already requires SAM)."""
    frames = run_dir / "frames"
    results: dict[str, str] = {}
    errors: list[str] = []
    try:
        obs, _source = _ground_observations(ground_spec, trace, replay_sha, frames, False, reference)
        results["engine"] = evaluate(ground_spec, obs)["result"]
    except SystemExit as exc:
        results["engine"] = "needs-review"
        errors.append(f"engine: {exc}")
    results["gameplay"] = judge_trace(trace, min_delta_x=min_dx)["result"]
    if hybrid:
        try:
            obs, source = _ground_observations(ground_spec, trace, replay_sha, frames, True, reference)
            results["hybrid"] = evaluate(ground_spec, obs)["result"] if source == "hybrid" else "needs-review"
            if source != "hybrid":
                errors.append("hybrid: the replay has no engine ground line or no frames")
        except SystemExit as exc:
            results["hybrid"] = "needs-review"
            errors.append(f"hybrid: {exc}")
    if use_sam:
        for spec, verdict, error in _sam_verdicts(sam_spec_docs, trace, replay_sha, frames, run_dir):
            results[spec["id"]] = verdict["result"] if verdict else "needs-review"
            if error:
                errors.append(f"{spec['id']}: {error}")
    if errors:
        (run_dir / ERRORS_FILE).write_text(json.dumps(errors, indent=2) + "\n", encoding="utf-8")
    return results


def confirm_route(route: Path, min_dx: float, patches: list[Path], run_dir: Path, first: dict[str, str],
                  ground_spec: dict, sam_spec_docs: list[dict], reference: list | None, use_sam: bool,
                  hybrid: bool, runs: int) -> dict:
    """Replay a route where a check failed until it has run ``runs`` times (the first replay, in
    ``run_dir``, counts) and judge every replay with the same checks. Returns the stability report;
    its ``checks`` are the results that held on every identical replay, needs-review otherwise."""
    hybrid = hybrid and use_sam

    def judge(_replay: dict, replay_dir: Path) -> dict[str, str]:
        trace = json.loads((replay_dir / "trace.json").read_text(encoding="utf-8"))
        return _judge_replay(trace, sha256_file(replay_dir / "replay.json"), replay_dir, min_dx, ground_spec,
                             sam_spec_docs, reference, use_sam, hybrid)

    try:
        replay = json.loads((run_dir / "replay.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        replay = None  # the first replay left no document: replay it again as well
    return stability.check(_render, route, run_dir / "stability", judge=judge, patches=patches, runs=runs,
                           first=(replay, run_dir, first) if replay is not None else None,
                           baselines=stability.BASELINES)


def caught(per_check: dict[str, dict[str, int]], checks: list[str]) -> str:
    """'yes' when any of these checks failed on a route, 'needs-review' when none failed but one
    could not decide, else 'no'."""
    present = [c for c in checks if c in per_check]
    if any(per_check[c]["fail"] for c in present):
        return "yes"
    if any(per_check[c]["needs-review"] for c in present):
        return "needs-review"
    return "no"


def bench(key: str, out: Path, stability_runs: int = 0) -> dict:
    root, manifest, problem = held_out_set()
    if manifest is None:
        raise SystemExit(f"held-out set unavailable: {problem or 'EXPECTRAIL_HELDOUT_DIR is not set'}")
    if key == CLEAN:
        patches: list[Path] = []
        expected = None
    elif key.startswith(DEV_PREFIX):
        dev = dev_variants()
        if key not in dev:
            raise SystemExit(f"{key}: no such development variant under bugs/")
        patches = [dev[key]]
        expected = DEV_FAMILY_SPECS.get(key.split("/")[1])
    else:
        matches = [v for v in active_variants(manifest) if variant_key(v) == key]
        if len(matches) != 1:
            raise SystemExit(f"{key}: not one active variant in the held-out manifest")
        patches = [root / matches[0]["patch"]]
        expected = matches[0].get("spec")
    use_sam = sam_on()
    sam_before = sam_usage()
    judge = None
    if use_sam:
        from agents.sam_observations import vision_backend

        judge = vision_backend()  # sam, both or glimmer-engine (SamError for anything else)
    glimmer_engine = judge == "glimmer-engine"
    ground_spec = load(REGRESSION_SPEC, "test-spec")
    sam_spec_docs = sam_specs(ground_spec["id"]) if use_sam else []
    work = out / key.replace("/", "_")
    work.mkdir(parents=True, exist_ok=True)
    reference = reference_surfaces(work)
    per_route = []
    for name, route, min_dx in _routes(root, manifest):
        checks = judge_route(route, min_dx, patches, work / name, ground_spec, sam_spec_docs, reference, use_sam,
                             hybrid=not glimmer_engine)
        row = {"route": name, "checks": checks}
        if stability_runs and "fail" in checks.values():
            report = confirm_route(route, min_dx, patches, work / name, checks, ground_spec, sam_spec_docs,
                                   reference, use_sam, not glimmer_engine, stability_runs)
            row["checks"] = {c: (report["checks"] or {}).get(c, "needs-review") for c in checks}
            row["stability"] = {"status": report["status"], "counts": report["counts"],
                                "distinctReplays": report["distinctReplays"], "firstReplay": checks}
        per_route.append(row)
    errors: list[str] = []
    for row in per_route:
        paths = [work / row["route"] / ERRORS_FILE] + sorted(
            (work / row["route"] / "stability").glob(f"replay-*/{ERRORS_FILE}"))
        for path in (p for p in paths if p.is_file()):
            for message in json.loads(path.read_text(encoding="utf-8")):
                if glimmer_engine:
                    # The kind only: Glimmer's error text can quote its answer about a held-out frame.
                    from agents.glimmer_client import error_kind

                    check, _, text = message.partition(": ")
                    message = f"{check}: {error_kind(text)}"
                if public_error(message) not in errors:
                    errors.append(public_error(message))
    check_names = list(per_route[0]["checks"])
    per_check = {c: {r: sum(row["checks"].get(c) == r for row in per_route) for r in RESULTS} for c in check_names}
    sam_on_checks = list(SAM_ON_CHECKS) + [s["id"] for s in sam_spec_docs]
    doc = {
        "format": "expectrail.held-out-bench/v0",
        "variant": key,
        "expectedSpec": expected,
        "sam": use_sam and not glimmer_engine,
        "judge": judge or "engine",
        "routes": len(per_route),
        "checks": per_check,
        "caughtWithSamOn": caught(per_check, sam_on_checks) if use_sam and not glimmer_engine else None,
        "caughtWithGlimmerEngine": (caught(per_check, list(GLIMMER_ENGINE_CHECKS) + [s["id"] for s in sam_spec_docs])
                                    if glimmer_engine else None),
        "caughtWithSamOff": caught(per_check, list(SAM_OFF_CHECKS)),
        "errors": errors[:5],  # distinct, directories stripped: why a check could not decide
        "samImages": sam_images_since(sam_before),  # a count only, for the run's cost
        "perRoute": per_route,  # route names: private, never printed
    }
    if stability_runs:
        replayed = [row["stability"]["status"] for row in per_route if "stability" in row]
        doc["stability"] = {"runs": stability_runs, "routesReplayed": len(replayed),
                            **{s: replayed.count(s) for s in ("stable-fail", "stable-pass", "flaky", "undecided")}}
    (work / "bench.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def annotation(doc: dict) -> str:
    """One public line: the variant id, counts and verdicts, nothing from the private manifest."""
    n = doc["routes"]
    parts = []
    for check, counts in doc["checks"].items():
        bits = [f"{counts[r]} {r}" for r in RESULTS if counts[r]]
        parts.append(f"{check} {', '.join(bits)}")
    label = "false alarm" if doc["variant"] == CLEAN else "caught"
    head = f"{label} with SAM on: {doc['caughtWithSamOn']}; " if doc["sam"] else ""
    if doc.get("caughtWithGlimmerEngine") is not None:
        head = f"{label} with Glimmer+engine (no SAM): {doc['caughtWithGlimmerEngine']}; "
    head += f"{label} with SAM off: {doc['caughtWithSamOff']}"
    title = f"{'Dev' if doc['variant'].startswith(DEV_PREFIX) else 'Held-out'} bench {doc['variant']}"
    lines = [f"::notice title={title}::{head}; over {n} routes: " + "; ".join(parts)]
    lines += [f"::error title={title} error::{public_error(e)}" for e in doc.get("errors") or []]
    st = doc.get("stability")
    if st:
        lines.append(f"::notice title=Bench stability {doc['variant']}::{st['routesReplayed']} routes with a "
                     f"failing check replayed until {st['runs']} runs: {st['stable-fail']} stable fail, "
                     f"{st['flaky']} flaky, {st['undecided']} undecided, {st['stable-pass']} stable pass")
    if doc.get("samImages") is not None:
        lines.append(f"::notice title=Bench SAM images {doc['variant']}::{doc['samImages']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="print the active variant ids (and clean) as JSON")
    g.add_argument("--variant", help="family/id of one held-out variant, or dev/family/id of a public one")
    g.add_argument("--clean", action="store_true", help="the unpatched game (false-alarm control)")
    g.add_argument("--annotate", type=Path, help="print the public annotation for a bench.json")
    p.add_argument("--only", default="", help="with --list: keep only these comma-separated ids (all must exist)")
    p.add_argument("--set", choices=SETS, default="held-out", dest="which",
                   help="with --list: the private held-out variants or the public development ones")
    p.add_argument("--out", type=Path, default=REPO / "runs" / "held-out-bench")
    p.add_argument("--stability", action="store_true",
                   help="replay every route with a failing check before it counts (off by default)")
    p.add_argument("--stability-runs", type=int, default=stability.STABILITY_RUNS,
                   help="with --stability: replays per failing route, the first included (default 3)")
    args = p.parse_args(argv)
    if args.stability and args.stability_runs < 2:
        p.error("--stability-runs must be at least 2")
    if args.annotate:
        print(annotation(json.loads(args.annotate.read_text(encoding="utf-8"))))
        return 0
    if args.list:
        _root, manifest, problem = held_out_set()
        if manifest is None:
            raise SystemExit(f"held-out set unavailable: {problem or 'EXPECTRAIL_HELDOUT_DIR is not set'}")
        ids = set_ids(manifest, args.which)
        wanted = [w.strip() for w in args.only.split(",") if w.strip()]
        unknown = sorted(set(wanted) - set(ids))
        if unknown:
            raise SystemExit(f"--only: no active variant {unknown}")
        print(json.dumps([i for i in ids if not wanted or i in wanted]))
        return 0
    doc = bench(CLEAN if args.clean else args.variant, args.out,
                stability_runs=args.stability_runs if args.stability else 0)
    print(annotation(doc))
    # A run that decided nothing is not a result: fail, so a green job means the checks ran.
    decided = (doc.get("caughtWithGlimmerEngine") or (doc["caughtWithSamOn"] if doc["sam"] else None)
               or doc["caughtWithSamOff"])
    return 1 if decided == "needs-review" else 0


if __name__ == "__main__":
    sys.exit(main())
