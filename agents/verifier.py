"""Verify a candidate patch outside the fixer's reach.

    python3 -m agents.verifier --request rr.json --candidate runs/fix/candidate.patch \\
        --out runs/verify [--observations path.json] [--skip-harness]

Applies base seed + candidate, replays the route (unless --skip-harness with
pre-built observations), runs regression + gameplay + clean + held-out checks,
and emits expectrail.verification/v0 via expectrail.evaluator.decide.

Clean uses a distinct observation source (never the candidate obs object).
Held-out: when EXPECTRAIL_HELDOUT_DIR points at a checkout of the private held-out set,
the verifier replays seed + candidate on each private route the fixer never sees and
requires both the visual spec and the gameplay check to pass there. Without it (offline,
fixture runs, forks) it falls back to the interim fixture, labeled interim-fixture. A candidate
that has already failed is not replayed on the private routes, since they could not change a
reject (EXPECTRAIL_HELDOUT_AFTER_FAIL=run replays them anyway).

Optional `suite` on the verification document records candidate/clean/held-out
provenance (harness vs fixture vs fixture-fallback vs unavailable).

With EXPECTRAIL_OBS_PROVIDER=sam, the specs in SAM_SPECS (player always visible, coins
visible) are also judged on SAM 3.1's view of the candidate, clean and held-out replays, and
every one must pass. SAM cannot see the ground in this game's art, so the ground spec is judged
against the clean level's ground line (from an unpatched reference replay, so a candidate cannot
move it): on SAM's box for the robot when SAM is on, on the position log otherwise (docs/sam.md).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

from agents.gameplay import (
    MIN_DELTA_X_FIXTURE,
    MIN_DELTA_X_HARNESS,
    judge_trace,
)
from agents.isolation import arm
from agents.observations import (
    engine_ground_by_frame, from_trace, has_engine_ground, resolve_provider, with_reference_ground,
)
from agents.patchutil import assert_editable, sha256_file
from harness.run import REPO, run as harness_run, tree_digest
from expectrail import timing
from expectrail.contracts import digest, load, validate
from expectrail.evaluator import decide, evaluate

REGRESSION_SPEC = REPO / "agents" / "specs" / "player-stays-above-ground.json"
# Opaque check id for verification / filmable rows. Judged by agents.gameplay from
# the harness/fixture trace — not evaluate(reaches) and not a SAM goal.
# Retired label player-reaches-end-of-route stays on FIXER_FORBIDDEN forever.
GAMEPLAY_SPEC_ID = "player-motion-on-smoke"
CLEAN_OBS = REPO / "agents" / "fixtures" / "obs-clean.json"
HELD_OUT_OBS = REPO / "agents" / "fixtures" / "obs-held-out.json"
TRACE_FIXTURES = {
    "obs-fixed.json": REPO / "agents" / "fixtures" / "trace-fixed.json",
    "obs-freeze.json": REPO / "agents" / "fixtures" / "trace-freeze.json",
    "obs-fallthrough.json": REPO / "agents" / "fixtures" / "trace-fallthrough.json",
}

_NOT_RUN = arm(source="not-run", detail="suite checks skipped (early reject)")

# Checkout of the private held-out repository (manifest.json, routes/, bugs/). Set only on
# the verifier's machine; never on the fixer's.
HELDOUT_ENV = "EXPECTRAIL_HELDOUT_DIR"

# Any failed check rejects (expectrail.evaluator.decide), so once a candidate has failed, the private
# routes cannot change the decision: they are not replayed, which saves four renders and SAM's look
# at every frame of them. Set to "run" to replay them anyway, for a run that reports how a candidate
# fares on every private route (the SAM and Glimmer probes' verify mode).
HELDOUT_AFTER_FAIL_ENV = "EXPECTRAIL_HELDOUT_AFTER_FAIL"


def held_out_after_fail() -> bool:
    return os.environ.get(HELDOUT_AFTER_FAIL_ENV, "").strip().lower() in ("run", "1", "true", "yes")

# Specs SAM 3.1 can judge in this game, approved after the live probes (docs/sam.md). With
# EXPECTRAIL_OBS_PROVIDER=sam they are judged on SAM's view of every replay the verifier makes
# (candidate, clean and held-out routes), in addition to the ground spec. SAM cannot see the
# ground in this art, so the ground spec compares the robot with the clean level's ground line.
SAM_SPECS = ("specs/player-always-visible.json", "specs/coins-visible.json")
SAM_SPECS_ENV = "EXPECTRAIL_SAM_SPECS"  # comma-separated repo paths, to override SAM_SPECS

# The lowest per-frame score SAM may give a prompted object on the CLEAN replay before the drop
# is reported instead of passed. From the Oct 28 clean probes (runs 40656097298, 40656100304):
# observed minima 0.644 (player) and 0.688 (coins) over the sampled frames.
SAM_CLEAN_SCORE_FLOOR = 0.60


def sam_on() -> bool:
    """True when SAM should judge the visual specs. An unknown provider fails here, early."""
    return resolve_provider() == "sam"


# Ids a SAM spec may not take: its evidence files and held-out results would collide with these.
RESERVED_SPEC_IDS = frozenset({"clean", "held-out", "gameplay", GAMEPLAY_SPEC_ID})


def sam_specs(ground_id: str | None = None) -> list[dict]:
    raw = os.environ.get(SAM_SPECS_ENV, "")
    paths = [p.strip() for p in raw.split(",") if p.strip()] or list(SAM_SPECS)
    specs = [load(REPO / p, "test-spec") for p in paths]
    ids = [s["id"] for s in specs]
    clash = sorted({i for i in ids if i in RESERVED_SPEC_IDS or i == ground_id or ids.count(i) > 1})
    if clash:
        raise SystemExit(f"{SAM_SPECS_ENV}: spec id(s) {clash} repeat or clash with the ground spec or the "
                         "verifier's own evidence files; give each SAM spec its own id")
    return specs


def _min_prompt_score(spec: dict, obs: dict) -> float | None:
    """The lowest per-frame best-detection score SAM gave any prompted object (None: none detected)."""
    best = []
    for frame in obs.get("frames") or []:
        for name in spec["objects"]:
            scores = [d["score"] for d in frame["objects"].get(name) or [] if d.get("score") is not None]
            if scores:
                best.append(max(scores))
    return min(best) if best else None


def _sam_verdicts(specs: list[dict], trace: dict | None, replay_sha: str, frames_dir: Path | None,
                  out_dir: Path, prefix: str = "", floor: float | None = None) -> list[tuple[dict, dict | None, str | None]]:
    """SAM's verdict on one replay for each SAM spec: (spec, verdict, None) or (spec, None, error).

    Observations and verdicts are written next to the replay's other evidence. Every verdict carries
    ``samMinScore``, the score margin SAM gave the prompted objects. With ``floor`` set (the clean
    replay), a pass whose margin fell below the floor becomes needs-review: our art got harder for
    SAM to see, and that is reported instead of passing quietly. A replay without
    frames (offline fixtures, a failed harness run) or a SAM failure gives no verdict, which the
    callers turn into needs-review, never a pass.
    """
    results: list[tuple[dict, dict | None, str | None]] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for spec in specs:
        name = f"{prefix}{spec['id']}"
        if frames_dir is None or not Path(frames_dir).is_dir():
            error = "no captured frames for this replay (offline fixtures or a failed harness run)"
        else:
            try:
                obs = from_trace(trace or {}, replay_sha256=replay_sha, frames_dir=str(frames_dir), spec=spec,
                                 provider="sam")
            except SystemExit as exc:
                error = str(exc)
            else:
                (out_dir / f"observations-{name}.json").write_text(json.dumps(obs, indent=2) + "\n", encoding="utf-8")
                verdict = evaluate(spec, obs)
                verdict["samMinScore"] = _min_prompt_score(spec, obs)
                if floor is not None and verdict["result"] == "pass" and (
                        verdict["samMinScore"] is None or verdict["samMinScore"] < floor):
                    verdict["result"] = "needs-review"
                    verdict["reason"] = (f"score margin: SAM's lowest frame score for the prompted objects "
                                         f"({verdict['samMinScore']}) is below the floor ({floor})")
                (out_dir / f"verdict-{name}.json").write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
                results.append((spec, verdict, None))
                continue
        (out_dir / f"observations-{name}-error.txt").write_text(f"{error}\n", encoding="utf-8")
        results.append((spec, None, error))
    return results


# A two-tick replay of the unpatched game: enough for the harness to report the level's surfaces.
LEVEL_REFERENCE_ROUTE = {"format": "expectrail.route/v0", "name": "level-reference",
                         "description": "Two idle ticks of the clean game, to read its level surfaces.",
                         "ticks": 2, "seed": 1, "events": []}
_REFERENCE_SURFACES: dict[str, list] = {}


def reference_surfaces(out: Path) -> list | None:
    """The clean game's level surfaces (every solid tile polygon, world coordinates), or None.

    Read from a replay of the unpatched game, never from a candidate's, so a candidate that edits
    the level cannot move the ground it is judged against. Memoized per game tree; one retry, since
    Godot has aborted on back-to-back imports in CI.
    """
    key = tree_digest(REPO / "game" / "platformer")
    if key in _REFERENCE_SURFACES:
        return _REFERENCE_SURFACES[key]
    run_dir = out / "level-reference"
    run_dir.mkdir(parents=True, exist_ok=True)
    route = run_dir / "route.json"
    route.write_text(json.dumps(LEVEL_REFERENCE_ROUTE) + "\n", encoding="utf-8")
    for _attempt in range(2):
        try:
            with timing.arm("reference"):
                harness_run(route, run_dir / "replay", patches=[])
            surfaces = json.loads((run_dir / "replay" / "trace.json").read_text(encoding="utf-8")).get("levelSurfaces")
        except (subprocess.CalledProcessError, OSError, TimeoutError, ValueError):
            continue
        if surfaces:
            _REFERENCE_SURFACES[key] = surfaces
            return surfaces
        return None
    return None


def _ground_observations(spec: dict, trace: dict, replay_sha: str, frames_dir: Path | None,
                         use_sam: bool, reference: list | None) -> tuple[dict, str]:
    """Observations for the ground spec, and how they were made.

    Traces from the current harness (they carry the camera, ``view``) are judged against the clean
    game's ground (``reference``), never the ground the candidate shipped; without a reference
    that is needs-review. Then: with SAM on, "hybrid", SAM's box for the robot against that ground
    line in frame pixels, which also catches a robot only drawn inside the ground; otherwise
    "engine", the position log against the same line. Older traces keep the old check. Any failure
    raises SystemExit, which callers turn into needs-review.
    """
    if use_sam:
        from agents.sam_observations import SamError, vision_backend

        try:
            # Glimmer's boxes are 15-20 px taller than the robot (Oct 29, run 40941969395): too loose for
            # the 20 px ground tolerance, so under glimmer-engine the ground is judged on the position log.
            if vision_backend() == "glimmer-engine":
                use_sam = False
        except SamError:
            pass
    if any(r.get("view") for r in trace.get("rows") or []):
        if not reference:
            raise SystemExit("no clean-level reference for the ground line (its replay failed), so the "
                             "candidate's own level cannot be trusted as the yardstick")
        trace = with_reference_ground(trace, reference)
    if use_sam and has_engine_ground(trace) and frames_dir is not None and Path(frames_dir).is_dir():
        from agents.sam_observations import SamError, frame_files, png_size

        try:
            frames = frame_files(Path(frames_dir))
            size = png_size(next(iter(frames.values()))) if frames else None
        except (SamError, OSError) as exc:
            raise SystemExit(f"sam observations unavailable: {exc}") from exc
        if frames:
            engine = engine_ground_by_frame(trace, size, list(frames))
            obs = from_trace(trace, replay_sha256=replay_sha, frames_dir=str(frames_dir), spec=spec, provider="sam",
                             engine_objects=engine)
            return obs, "hybrid"
    return from_trace(trace, replay_sha256=replay_sha, spec=spec, provider="trace"), "engine"


GROUND_SOURCES = {
    "hybrid": "ground spec judged on SAM's robot box against the clean level's ground line",
    "engine": "ground spec judged on the position log against the clean level's ground line",
}


def _sam_checks(specs: list[dict], kind: str, route_name: str, trace: dict | None, replay_sha: str,
                frames_dir: Path | None, out: Path, prefix: str = "", floor: float | None = None) -> list[dict]:
    checks = []
    for spec, verdict, _error in _sam_verdicts(specs, trace, replay_sha, frames_dir, out, prefix, floor):
        if verdict is None:
            checks.append({"spec": spec["id"], "kind": kind, "route": route_name, "result": "needs-review",
                           "verdictSha256": "0" * 64})
        else:
            checks.append(_check(kind, spec["id"], route_name, verdict))
    return checks


def held_out_set() -> tuple[Path | None, dict | None, str | None]:
    """Return (root, manifest, problem). All None when EXPECTRAIL_HELDOUT_DIR is unset.

    A set directory that is missing or malformed returns a problem string so the
    held-out check fails closed (needs-review) instead of falling back to a fixture.
    """
    raw = os.environ.get(HELDOUT_ENV, "").strip()
    if not raw:
        return None, None, None
    root = Path(raw)
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        routes = manifest["routes"]
        if not routes:
            raise ValueError("manifest lists no held-out routes")
        for entry in routes:
            if not (root / entry["file"]).is_file():
                raise ValueError(f"held-out route file missing: {entry['file']}")
            if float(entry["minDeltaX"]) <= 0:
                raise ValueError(f"held-out route {entry['file']} needs a positive minDeltaX")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return root, None, f"{type(exc).__name__}: {exc}"
    return root, manifest, None


def _run_held_out_routes(
    root: Path, manifest: dict, spec: dict, patches: list[Path], out: Path, use_sam: bool = False,
    reference: list | None = None,
) -> tuple[dict, dict]:
    """Replay seed + candidate on each private route; return (verdict, suite arm).

    A route passes only if every visual spec and the gameplay check pass on it: the ground
    spec against the clean level's ground line (see _ground_observations), plus the SAM specs
    on SAM's view when ``use_sam``.
    A harness failure on any route makes the whole check needs-review, never pass.
    """
    sam_spec_docs = sam_specs(spec["id"]) if use_sam else []
    rows = []
    for position, entry in enumerate(manifest["routes"], start=1):
        name = str(entry.get("name") or Path(entry["file"]).stem)
        run_dir = out / "held-out" / name
        row: dict = {"route": name, "minDeltaX": float(entry["minDeltaX"])}
        # timing.json is kept as a public artifact: a private route is timed under its position, not its name.
        label = f"held-out-{position}"
        try:
            # Godot has aborted on back-to-back imports in CI; one retry, and it is recorded.
            try:
                with timing.arm(label):
                    harness_run(root / entry["file"], run_dir, patches=patches)
            except (subprocess.CalledProcessError, OSError, TimeoutError):
                row["harnessRetried"] = True
                with timing.arm(label):
                    harness_run(root / entry["file"], run_dir, patches=patches)
            trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
            replay_sha = sha256_file(run_dir / "replay.json")
            try:
                obs, ground_source = _ground_observations(spec, trace, replay_sha, run_dir / "frames", use_sam,
                                                          reference)
            except SystemExit as exc:
                (run_dir / f"observations-{spec['id']}-error.txt").write_text(f"{exc}\n", encoding="utf-8")
                obs, ground_source = None, "unavailable"
            visuals = {spec["id"]: evaluate(spec, obs)["result"] if obs is not None else "needs-review"}
            for sam_spec, verdict, _error in _sam_verdicts(sam_spec_docs, trace, replay_sha, run_dir / "frames",
                                                           run_dir):
                visuals[sam_spec["id"]] = verdict["result"] if verdict else "needs-review"
            visual = ("fail" if "fail" in visuals.values()
                      else "pass" if all(v == "pass" for v in visuals.values()) else "needs-review")
            play = judge_trace(trace, min_delta_x=float(entry["minDeltaX"]))
            parts = (visual, play["result"])
            if use_sam:
                row["visuals"] = visuals  # only with SAM on, so default-provider evidence is unchanged
                row["groundSource"] = ground_source
            row.update(
                visual=visual,
                gameplay=play["result"],
                gameplayReason=play["reason"],
                observationsSha256=digest(obs) if obs is not None else "0" * 64,
                result=("pass" if parts == ("pass", "pass")
                        else "fail" if "fail" in parts else "needs-review"),
            )
        except (subprocess.CalledProcessError, SystemExit, OSError, TimeoutError, ValueError) as exc:
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "harness-error.txt").write_text(
                f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}", encoding="utf-8",
            )
            row.update(result="needs-review", error=f"{type(exc).__name__}: held-out harness run failed")
        rows.append(row)
    results = [r["result"] for r in rows]
    overall = "fail" if "fail" in results else "needs-review" if "needs-review" in results else "pass"
    verdict = {"spec": spec["id"], "result": overall, "routes": rows}
    held_arm = arm(
        source="harness",
        path=str(out / "held-out"),
        observations_sha256=digest(verdict),
        detail=(f"{len(rows)} private held-out route(s) via {HELDOUT_ENV}"
                + (f"; ground spec judged by {', '.join(sorted({r['groundSource'] for r in rows if r.get('groundSource')})) or 'nothing'}"
                   " (hybrid means SAM's robot box against the clean level's ground line), SAM specs on SAM's view"
                   if use_sam else "")),
    )
    return verdict, held_arm


def _resolve(repo_relative: str | Path) -> Path:
    path = Path(repo_relative)
    return path if path.is_absolute() else REPO / path


def _check(kind: str, spec_id: str, route_name: str, verdict: dict) -> dict:
    return {
        "spec": spec_id,
        "kind": kind,
        "route": route_name,
        "result": verdict["result"],
        "verdictSha256": digest(verdict),
    }


def _early_suite(*, gate: str, detail: str) -> dict:
    return {
        "candidate": dict(_NOT_RUN),
        "clean": dict(_NOT_RUN),
        "heldOut": dict(_NOT_RUN),
        "earlyReject": {"gate": gate, "detail": detail},
    }


def _resolve_gameplay_trace(
    out: Path,
    *,
    observations_path: Path | None,
) -> tuple[dict, str, float]:
    """Return (trace, source_label, min_delta_x).

    When --observations is set (offline / skip-harness), mapped fixture traces win
    so a leftover out/replay/trace.json cannot override freeze fixtures.
    Otherwise use the live harness candidate trace.
    """
    if observations_path is not None:
        mapped = TRACE_FIXTURES.get(observations_path.name)
        if mapped is not None and mapped.is_file():
            return (
                json.loads(mapped.read_text(encoding="utf-8")),
                f"fixture-trace:{mapped.name}",
                MIN_DELTA_X_FIXTURE,
            )
        raise SystemExit(
            f"no mapped fixture gameplay trace for observations {observations_path.name}"
        )
    harness_trace = out / "replay" / "trace.json"
    if harness_trace.is_file():
        return (
            json.loads(harness_trace.read_text(encoding="utf-8")),
            "harness-trace",
            MIN_DELTA_X_HARNESS,
        )
    raise SystemExit("gameplay requires candidate replay/trace.json when observations are unset")


TIMED = ("One verification by agents.verifier.verify, from the request to verification.json: the replays it "
         "asks the harness for, and judging them")


def verify(
    request: dict,
    candidate: Path,
    out: Path,
    *,
    route: Path | None = None,
    observations_path: Path | None = None,
    clean_observations_path: Path | None = None,
    held_out_observations_path: Path | None = None,
    skip_harness: bool = False,
    attempt: int = 1,
) -> dict:
    """Verify one candidate and write verification.json, with timing.json (expectrail.timing) beside it.

    The timing is written after the decision and is never read back here. If it cannot be written, for
    any reason, the verification stands and timing-error.txt says why.
    """
    with timing.recording() as recorder:
        doc = _verify(
            request, candidate, out, route=route, observations_path=observations_path,
            clean_observations_path=clean_observations_path,
            held_out_observations_path=held_out_observations_path, skip_harness=skip_harness, attempt=attempt,
        )
    try:
        timing.write(recorder, out / "timing.json", TIMED, decision=doc["decision"], sam=sam_on())
    except Exception as exc:  # noqa: BLE001 - the verdict is written; no fault in a side record may lose it
        _timing_failed(out, exc)
    else:
        with contextlib.suppress(OSError):
            (out / "timing-error.txt").unlink(missing_ok=True)  # an earlier run's error is not this run's
    return doc


def _timing_failed(out: Path, exc: BaseException) -> None:
    """Say why there is no timing for this verdict, and leave no earlier run's numbers beside it.

    Never raises: verification.json is already written. What cannot be removed is named in
    timing-error.txt, and when that file cannot be written either the reason goes to stderr.
    """
    notes = [f"{type(exc).__name__}: {exc}"]
    stale = out / "timing.json"
    try:
        stale.unlink(missing_ok=True)
    except OSError as err:
        notes.append(f"timing.json is not this run's and could not be removed: {type(err).__name__}: {err}")
    try:
        (out / "timing-error.txt").write_text("\n".join(notes) + "\n", encoding="utf-8")
    except OSError as err:
        notes.append(f"timing-error.txt could not be written: {type(err).__name__}: {err}")
        print("verifier: no timing for this verification: " + "; ".join(notes), file=sys.stderr)


def _verify(
    request: dict,
    candidate: Path,
    out: Path,
    *,
    route: Path | None = None,
    observations_path: Path | None = None,
    clean_observations_path: Path | None = None,
    held_out_observations_path: Path | None = None,
    skip_harness: bool = False,
    attempt: int = 1,
) -> dict:
    validate(request, "repair-request")
    out.mkdir(parents=True, exist_ok=True)
    patch_text = candidate.read_text(encoding="utf-8")
    bad = assert_editable(patch_text, request["editable"])
    if bad:
        detail = f"candidate touches paths outside editable: {bad}"
        decision, reasons = "reject", [detail]
        checks = [{
            "spec": "editable-globs", "kind": "regression", "route": "n/a", "result": "fail",
        }]
        return _write_verification(
            out, request, candidate, attempt, checks, decision, reasons,
            suite=_early_suite(gate="editable-globs", detail=detail),
        )

    game = REPO / "game" / "platformer"
    if request["base"]["tree"] != tree_digest(game):
        detail = "base.tree does not match game/platformer"
        decision, reasons = "reject", [detail]
        checks = [{
            "spec": "base-tree", "kind": "regression", "route": "n/a", "result": "fail",
        }]
        return _write_verification(
            out, request, candidate, attempt, checks, decision, reasons,
            suite=_early_suite(gate="base-tree", detail=detail),
        )

    failing = request["failing"][0]
    route_doc = failing["route"]
    # Always materialize the request's route so verify is bound to the RR, not only
    # the default smoke file on disk.
    route_path = out / "route.json"
    route_path.write_text(json.dumps(route_doc, indent=2) + "\n", encoding="utf-8")
    if route is None:
        route = route_path

    patches: list[Path] = []
    seed = request["base"].get("patch")
    if seed:
        patches.append(_resolve(seed))
    patches.append(candidate)

    # Regression: the ground spec (never-crosses) against the clean level's ground line, on SAM's
    # robot box when SAM is on (see _ground_observations). With SAM on, the SAM specs as well.
    reg_spec = load(REGRESSION_SPEC, "test-spec")
    if failing.get("spec", {}).get("id") == reg_spec["id"]:
        reg_spec = failing["spec"]
    use_sam = sam_on()
    sam_spec_docs = sam_specs(reg_spec["id"]) if use_sam else []
    from agents.sam_observations import vision_label

    sam_note = (f"; {vision_label()} judges {', '.join(s['id'] for s in sam_spec_docs)} on its own observations"
                if use_sam else "")
    trace, replay_sha, frames_dir = None, "0" * 64, None
    # The clean game's level surfaces: the ground every replay here is judged against.
    reference = None if (skip_harness or observations_path is not None) else reference_surfaces(out)

    if observations_path is not None:
        observations = load(observations_path, "observations")
        candidate_arm = arm(
            source="fixture",
            path=str(observations_path),
            observations_sha256=digest(observations),
        )
    elif skip_harness:
        raise SystemExit("--skip-harness requires --observations")
    else:
        with timing.arm("candidate"):
            harness_run(route, out / "replay", patches=patches)
        trace = json.loads((out / "replay" / "trace.json").read_text(encoding="utf-8"))
        replay_sha = sha256_file(out / "replay" / "replay.json")
        frames_dir = out / "replay" / "frames"
        try:
            observations, ground_source = _ground_observations(reg_spec, trace, replay_sha, frames_dir, use_sam,
                                                               reference)
        except SystemExit as exc:
            # The engine observations could not be built: the regression check is needs-review,
            # never a pass, and the other checks still run.
            observations = None
            (out / "observations-error.txt").write_text(f"{exc}\n", encoding="utf-8")
            candidate_arm = arm(source="unavailable", detail=f"candidate observations unavailable: {exc}")
        else:
            (out / "observations.json").write_text(json.dumps(observations, indent=2) + "\n", encoding="utf-8")
            candidate_arm = arm(
                source="harness",
                path=str(out / "observations.json"),
                observations_sha256=digest(observations),
                detail=f"{GROUND_SOURCES[ground_source]}{sam_note}" if use_sam else None,
            )

    route_name = route_doc.get("name", route.stem)
    checks = []
    if observations is None:
        checks.append({
            "spec": reg_spec["id"],
            "kind": "regression",
            "route": route_name,
            "result": "needs-review",
            "verdictSha256": "0" * 64,
        })
    else:
        reg_verdict = evaluate(reg_spec, observations)
        (out / f"verdict-{reg_spec['id']}.json").write_text(
            json.dumps(reg_verdict, indent=2) + "\n", encoding="utf-8"
        )
        checks.append(_check("regression", reg_spec["id"], route_name, reg_verdict))
    if use_sam:
        checks += _sam_checks(sam_spec_docs, "regression", route_name, trace, replay_sha, frames_dir, out)

    # Gameplay: same agents.gameplay predicate for harness trace and offline fixtures.
    gameplay_trace, gameplay_source, min_dx = _resolve_gameplay_trace(
        out, observations_path=observations_path,
    )
    gameplay = judge_trace(gameplay_trace, min_delta_x=min_dx)
    metrics = dict(gameplay.get("metrics") or {})
    metrics.setdefault("minDeltaX", float(min_dx))
    gameplay_doc = {
        "format": "expectrail.gameplay-verdict/v0",
        "spec": GAMEPLAY_SPEC_ID,
        "result": gameplay["result"],
        "reason": gameplay["reason"],
        "metrics": metrics,
        "source": gameplay_source,
        "minDeltaX": float(min_dx),
        "evaluator": {"name": "agents.gameplay", "version": "0.1.0"},
    }
    validate(gameplay_doc, "gameplay-verdict")
    (out / "verdict-gameplay.json").write_text(json.dumps(gameplay_doc, indent=2) + "\n", encoding="utf-8")
    # Non-contract extract for operators; morning uses verdict-gameplay.json.
    (out / "gameplay-metrics.json").write_text(
        json.dumps(gameplay.get("metrics", {}), indent=2) + "\n", encoding="utf-8"
    )
    checks.append({
        "spec": GAMEPLAY_SPEC_ID,
        "kind": "gameplay",
        "route": route_name,
        "result": gameplay["result"],
        "verdictSha256": digest(gameplay_doc),
    })

    # Clean control: distinct obs source — never reuse the candidate observations object.
    # Harness clean-replay can SIGABRT on back-to-back Godot imports in CI; fall back to the
    # fixture so verify still emits a four-kind decision (fail still beats unclear).
    clean_path = clean_observations_path or CLEAN_OBS
    clean_spec = load(REGRESSION_SPEC, "test-spec")
    clean_trace, clean_replay_sha, clean_frames = None, "0" * 64, None
    if skip_harness or observations_path is not None:
        clean_obs = load(clean_path, "observations")
        if digest(clean_obs) == digest(observations):
            raise SystemExit(
                "clean observations must be a distinct document from candidate observations "
                f"(same digest {digest(observations)[:12]}…)"
            )
        clean_route = "clean-control"
        clean_arm = arm(
            source="fixture",
            path=str(clean_path),
            observations_sha256=digest(clean_obs),
        )
    else:
        try:
            with timing.arm("clean"):
                harness_run(route, out / "clean-replay", patches=[])
            clean_trace = json.loads((out / "clean-replay" / "trace.json").read_text(encoding="utf-8"))
            clean_replay_sha = sha256_file(out / "clean-replay" / "replay.json")
        except (subprocess.CalledProcessError, SystemExit, OSError, TimeoutError) as exc:
            (out / "clean-harness-error.txt").write_text(
                f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}",
                encoding="utf-8",
            )
            clean_obs = load(clean_path, "observations")
            if observations is not None and digest(clean_obs) == digest(observations):
                raise SystemExit(
                    "clean fixture-fallback must be distinct from candidate observations "
                    f"(same digest {digest(observations)[:12]}…)"
                ) from exc
            clean_route = "clean-control-fixture-fallback"
            clean_arm = arm(
                source="fixture-fallback",
                path=str(clean_path),
                observations_sha256=digest(clean_obs),
                detail=f"clean harness failed; see {out / 'clean-harness-error.txt'}",
            )
        else:
            # The harness rendered the clean game. If its observations cannot be built, that is
            # needs-review: falling back to the fixture here would pass the clean check on data
            # nobody looked at.
            clean_route = "clean-control"
            clean_frames = out / "clean-replay" / "frames"
            try:
                clean_obs, clean_ground_source = _ground_observations(clean_spec, clean_trace, clean_replay_sha,
                                                                      clean_frames, use_sam, reference)
            except SystemExit as exc:
                clean_obs = None
                (out / "observations-clean-error.txt").write_text(f"{exc}\n", encoding="utf-8")
                clean_arm = arm(source="unavailable", detail=f"clean observations unavailable: {exc}")
            else:
                (out / "observations-clean.json").write_text(
                    json.dumps(clean_obs, indent=2) + "\n", encoding="utf-8"
                )
                clean_arm = arm(
                    source="harness",
                    path=str(out / "observations-clean.json"),
                    observations_sha256=digest(clean_obs),
                    detail=f"{GROUND_SOURCES[clean_ground_source]}{sam_note}" if use_sam else None,
                )
    if clean_obs is None:
        checks.append({
            "spec": clean_spec["id"],
            "kind": "clean",
            "route": clean_route,
            "result": "needs-review",
            "verdictSha256": "0" * 64,
        })
    else:
        clean_verdict = evaluate(clean_spec, clean_obs)
        (out / "verdict-clean.json").write_text(json.dumps(clean_verdict, indent=2) + "\n", encoding="utf-8")
        checks.append(_check("clean", clean_spec["id"], clean_route, clean_verdict))
    if use_sam:
        # A fixture clean run has no frames, so SAM's clean checks are needs-review there.
        checks += _sam_checks(sam_spec_docs, "clean", clean_route, clean_trace, clean_replay_sha, clean_frames, out,
                              "clean-", SAM_CLEAN_SCORE_FLOOR)

    # Held-out: private routes when the held-out set is mounted on this (verifier) machine
    # and we are replaying for real; otherwise the labeled interim fixture.
    held_spec = load(REGRESSION_SPEC, "test-spec")
    held_root, held_manifest, held_problem = held_out_set()
    use_private = (
        held_root is not None and not skip_harness and observations_path is None
        and held_out_observations_path is None
    )
    held_path = held_out_observations_path or HELD_OUT_OBS
    already_failed = [c for c in checks if c["result"] == "fail"]
    if use_private and held_problem is not None:
        checks.append({
            "spec": held_spec["id"],
            "kind": "held-out",
            "route": "held-out-routes",
            "result": "needs-review",
            "verdictSha256": "0" * 64,
        })
        held_arm = arm(source="unavailable", detail=f"held-out set unusable: {held_problem}")
    elif use_private and already_failed and not held_out_after_fail():
        # The decision is already reject: no held-out check is added, and the arm says why.
        first = already_failed[0]
        held_arm = arm(source="not-run", detail=(
            f"private routes not replayed: the candidate already failed the {first['kind']} check "
            f"{first['spec']}, so they could not change the decision ({HELDOUT_AFTER_FAIL_ENV}=run replays them)"))
    elif use_private:
        held_verdict, held_arm = _run_held_out_routes(held_root, held_manifest, held_spec, patches, out,
                                                      use_sam=use_sam, reference=reference)
        (out / "verdict-held-out.json").write_text(json.dumps(held_verdict, indent=2) + "\n", encoding="utf-8")
        checks.append(_check("held-out", held_spec["id"], "held-out-routes", held_verdict))
    elif held_path.is_file():
        held_obs = load(held_path, "observations")
        held_spec = load(REGRESSION_SPEC, "test-spec")
        held_verdict = evaluate(held_spec, held_obs)
        (out / "verdict-held-out.json").write_text(json.dumps(held_verdict, indent=2) + "\n", encoding="utf-8")
        checks.append(_check("held-out", held_spec["id"], "held-out-interim", held_verdict))
        held_source = "path" if held_out_observations_path is not None else "interim-fixture"
        held_arm = arm(
            source=held_source,
            path=str(held_path),
            observations_sha256=digest(held_obs),
        )
    else:
        checks.append({
            "spec": "held-out-unavailable",
            "kind": "held-out",
            "route": "held-out-unavailable",
            "result": "needs-review",
            "verdictSha256": "0" * 64,
        })
        held_arm = arm(source="unavailable", detail="held-out observations path missing")

    if use_sam and not use_private:
        # SAM never looked at a held-out replay here (interim fixture, an override, or no
        # private set mounted): its held-out checks are needs-review, never silently skipped.
        route = "held-out-interim" if held_path.is_file() else "held-out-unavailable"
        checks += [{"spec": s["id"], "kind": "held-out", "route": route, "result": "needs-review",
                    "verdictSha256": "0" * 64} for s in sam_spec_docs]

    suite = {"candidate": candidate_arm, "clean": clean_arm, "heldOut": held_arm}
    decision, reasons = decide(checks)
    return _write_verification(
        out, request, candidate, attempt, checks, decision, reasons, suite=suite,
    )


def _write_verification(
    out, request, candidate, attempt, checks, decision, reasons, *, suite: dict | None = None,
) -> dict:
    from expectrail import __version__ as eval_version

    doc = {
        "format": "expectrail.verification/v0",
        "candidate": {
            "patchSha256": sha256_file(candidate),
            "baseTree": request["base"]["tree"],
            "attempt": attempt,
            "request": request["id"],
            "requestSha256": digest(request),
        },
        "evaluator": {"name": "expectrail.evaluator", "version": eval_version},
        "checks": checks,
        "decision": decision,
        "reasons": reasons,
    }
    if suite is not None:
        doc["suite"] = suite
        (out / "suite-provenance.json").write_text(json.dumps(suite, indent=2) + "\n", encoding="utf-8")
    validate(doc, "verification")
    (out / "verification.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def public_route_identity(request: dict) -> dict:
    """What a public-route check depends on besides the patches: two arms with the same identity
    were judged the same way, so their outcomes can be compared."""
    from expectrail import __version__ as eval_version
    from agents.sam_observations import vision_label

    failing = request["failing"][0]
    reg_spec = load(REGRESSION_SPEC, "test-spec")
    if failing.get("spec", {}).get("id") == reg_spec["id"]:
        reg_spec = failing["spec"]
    use_sam = sam_on()
    specs = {reg_spec["id"]: digest(reg_spec)}
    if use_sam:
        specs.update({s["id"]: digest(s) for s in sam_specs(reg_spec["id"])})
    return {
        "specs": specs,
        "routeSha256": digest(failing["route"]),
        "evaluator": eval_version,
        "observer": vision_label() if use_sam else "engine",
    }


def public_route_checks(
    request: dict,
    patches: list[Path],
    out: Path,
    *,
    observations_path: Path | None = None,
) -> tuple[list[dict], dict]:
    """The public-route checks verify() makes for a candidate, for any list of patches.

    A review compares the failing base (the request's seed patch alone) with the candidate on the
    same checks. This replays ``patches`` on the request's public route and judges the regression
    spec (on SAM's view when SAM is on, plus the SAM specs) and the gameplay check, step for step as
    verify() does for seed plus candidate; tests/test_base_arm.py holds the two together. The clean
    and held-out arms are not run here: they do not depend on the patches being compared.

    Returns (checks, arm). The checks have verify()'s shape. The arm says where the observations
    came from, with the replay and observation digests (None when there is none, never a zero
    digest), the regression verdict's first failing frame and the frames directory.
    """
    validate(request, "repair-request")
    out.mkdir(parents=True, exist_ok=True)
    if request["base"]["tree"] != tree_digest(REPO / "game" / "platformer"):
        raise SystemExit("base.tree does not match game/platformer")
    failing = request["failing"][0]
    route_doc = failing["route"]
    route = out / "route.json"
    route.write_text(json.dumps(route_doc, indent=2) + "\n", encoding="utf-8")

    reg_spec = load(REGRESSION_SPEC, "test-spec")
    if failing.get("spec", {}).get("id") == reg_spec["id"]:
        reg_spec = failing["spec"]
    use_sam = sam_on()
    sam_spec_docs = sam_specs(reg_spec["id"]) if use_sam else []
    trace, replay_sha, frames_dir, ground_source = None, "0" * 64, None, None

    if observations_path is not None:
        observations = load(observations_path, "observations")
        source = "fixture"
    else:
        reference = reference_surfaces(out)
        harness_run(route, out / "replay", patches=patches)
        trace = json.loads((out / "replay" / "trace.json").read_text(encoding="utf-8"))
        replay_sha = sha256_file(out / "replay" / "replay.json")
        frames_dir = out / "replay" / "frames"
        try:
            observations, ground_source = _ground_observations(reg_spec, trace, replay_sha, frames_dir, use_sam,
                                                               reference)
        except SystemExit as exc:
            observations, source = None, "unavailable"
            (out / "observations-error.txt").write_text(f"{exc}\n", encoding="utf-8")
        else:
            source = "harness"
            (out / "observations.json").write_text(json.dumps(observations, indent=2) + "\n", encoding="utf-8")

    route_name = route_doc.get("name", route.stem)
    checks: list[dict] = []
    first_frame = None
    if observations is None:
        checks.append({"spec": reg_spec["id"], "kind": "regression", "route": route_name,
                       "result": "needs-review", "verdictSha256": "0" * 64})
    else:
        reg_verdict = evaluate(reg_spec, observations)
        (out / f"verdict-{reg_spec['id']}.json").write_text(json.dumps(reg_verdict, indent=2) + "\n",
                                                            encoding="utf-8")
        checks.append(_check("regression", reg_spec["id"], route_name, reg_verdict))
        first_frame = reg_verdict.get("firstFrame")
    if use_sam:
        checks += _sam_checks(sam_spec_docs, "regression", route_name, trace, replay_sha, frames_dir, out)

    gameplay_trace, gameplay_source, min_dx = _resolve_gameplay_trace(out, observations_path=observations_path)
    gameplay = judge_trace(gameplay_trace, min_delta_x=min_dx)
    metrics = dict(gameplay.get("metrics") or {})
    metrics.setdefault("minDeltaX", float(min_dx))
    gameplay_doc = {
        "format": "expectrail.gameplay-verdict/v0",
        "spec": GAMEPLAY_SPEC_ID,
        "result": gameplay["result"],
        "reason": gameplay["reason"],
        "metrics": metrics,
        "source": gameplay_source,
        "minDeltaX": float(min_dx),
        "evaluator": {"name": "agents.gameplay", "version": "0.1.0"},
    }
    validate(gameplay_doc, "gameplay-verdict")
    (out / "verdict-gameplay.json").write_text(json.dumps(gameplay_doc, indent=2) + "\n", encoding="utf-8")
    checks.append({"spec": GAMEPLAY_SPEC_ID, "kind": "gameplay", "route": route_name,
                   "result": gameplay["result"], "verdictSha256": digest(gameplay_doc)})

    arm_doc = {
        "source": source,
        "patchesSha256": [sha256_file(p) for p in patches],
        "replaySha256": replay_sha if trace is not None else None,
        "observationsSha256": digest(observations) if observations is not None else None,
        "groundSource": ground_source,
        "firstFailFrame": first_frame,
        "framesDir": str(frames_dir) if frames_dir is not None and frames_dir.is_dir() else None,
        "identity": public_route_identity(request),
    }
    return checks, arm_doc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--route", type=Path)
    p.add_argument("--observations", type=Path)
    p.add_argument("--clean-observations", type=Path, help="clean-control observations (default: fixtures/obs-clean.json)")
    p.add_argument("--held-out-observations", type=Path,
                   help="held-out observations (default: fixtures/obs-held-out.json interim)")
    p.add_argument("--skip-harness", action="store_true")
    p.add_argument("--attempt", type=int, default=1)
    args = p.parse_args(argv)
    request = load(args.request, "repair-request")
    doc = verify(
        request, args.candidate, args.out, route=args.route,
        observations_path=args.observations,
        clean_observations_path=args.clean_observations,
        held_out_observations_path=args.held_out_observations,
        skip_harness=args.skip_harness, attempt=args.attempt,
    )
    print(f"{doc['decision']}: {'; '.join(doc['reasons'])}")
    return 0 if doc["decision"] == "accept" else 1


if __name__ == "__main__":
    sys.exit(main())
