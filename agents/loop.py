"""Overnight agent loop: triage → fix (bounded retries) → verify → morning (+ trust).

    python3 -m agents.loop --out runs/loop [--mode auto|offline|live] [--runs 1]

Modes:
  offline — fixtures only (CI default; no Meta keys required)
  live    — Wonder + Muse Code; requires keys (fails closed if missing)
  auto    — live steps when keys/muse are available, else fixtures

Live Muse honors repair-request ``budget.attempts`` (re-prompt on verify reject /
empty patch). Fixture path is always a single attempt.

What Muse is told follows agents/escalation.py (docs/report-first.md): the first attempt gets the
report (the failing check's sentence, screenshots of the failing run, the route and its log); after
any failed attempt (rejected by the verifier, or no fix at all) the next one gets the evidence (the
repair request and, after a rejection, the public checks that failed). Every candidate is verified either way.

A live run with SAM on first sends SAM one image (agents/sam_health.py). If SAM does not answer, the
run stops there, before triage or Muse Code spends anything, and the morning report says why.

When the judge itself cannot answer (SAM down or out of credit, so the verifier can only say
needs-review), agents/judge_ladder.py judges the same candidate again instead of spending a fix
attempt: the same judge once more, then Muse Glimmer checked against the engine, then stop for a
person (docs/fallbacks.md). A rejection is never re-judged.

``--stability`` (off by default; needs Godot) replays the request's failing route on the failing
base three times (``--stability-runs``) before the fixer starts, and judges each replay with the
regression check on the position log (agents/stability.py; no SAM image). Only a stable failure goes
on to the fixer. A flaky or undecided route, or one that passes every time, stops the run as
needs-review before Muse Code spends anything.

Exit 0 only if every run ends with verification accept. Crashes never forge accept.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import traceback
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

from agents import escalation, judge_ladder, sam_health, stability
from agents.fixer import run_fixer
from agents.keys import resolve_mode, seal_mode_flags
from agents.report import build_report, gameplay_film_stub, write_loop_rollup, write_preflight_stop
from agents.signing import generate_run_keys
from agents.triage import triage
from agents.trust import run_trust_check
from agents.verifier import _resolve, verify
from harness.run import REPO, run as harness_run
from expectrail.contracts import load, validate

DEFAULT_BEFORE = REPO / "agents" / "fixtures" / "frames" / "before-fall.png"
DEFAULT_AFTER = REPO / "agents" / "fixtures" / "frames" / "after-fixed.png"
# The failing base's observations when the loop runs on fixtures (the loop's bug is the fall-through).
SAMPLE_BASE_OBS = REPO / "agents" / "fixtures" / "obs-fallthrough.json"
REVIEW_ENV = "EXPECTRAIL_REVIEW"


def _unresolved(verification: dict, ladder: dict | None) -> list[str] | None:
    """What the morning report hands a person: the verifier's reasons, plus the judge ladder's note
    when the first judge did not answer (a fallback judge decided, or none did)."""
    note = judge_ladder.report_note(ladder or {})
    if note is None:
        return None  # the report's own default: the reasons, unless accepted
    reasons = [] if verification["decision"] == "accept" else list(verification.get("reasons") or [])
    return [note] + reasons


def render_report(request: dict, out: Path) -> dict[str, Path] | None:
    """Replay the failing base on the request's route for the report's screenshots. None when it
    cannot be rendered: the fixer then starts from the evidence, as before."""
    try:
        failing = request["failing"][0]
        route = out / "route.json"
        out.mkdir(parents=True, exist_ok=True)
        route.write_text(json.dumps(failing["route"], indent=2) + "\n", encoding="utf-8")
        seed = request["base"].get("patch")
        harness_run(route, out / "replay", patches=[_resolve(seed)] if seed else [])
        files = escalation.report_files(out / "replay", route)
        return files if any("/screenshots/" in k for k in files) else None
    except (Exception, SystemExit):  # noqa: BLE001 - no report screenshots is a fallback, never a crash
        (out / "report-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return None


def review_on() -> bool:
    """EXPECTRAIL_REVIEW=on adds a review against the failing base after verification. Off by default."""
    import os

    return os.environ.get(REVIEW_ENV, "").strip().lower() in ("on", "1", "true", "yes")


def run_review(request: dict, candidate: Path, verification_file: Path, out: Path, *,
               observations: Path | None, origin: str | None) -> dict:
    """The review of this run's final candidate, reusing its verification. Never raises and never
    changes the loop's decision: a failure is recorded as an INCONCLUSIVE review."""
    try:
        from agents.review_change import review

        sample = observations is not None
        record = review(request, candidate, out, mode="sample" if sample else "live", origin=origin,
                        verification_path=verification_file,
                        base_observations=SAMPLE_BASE_OBS if sample else None, observations=observations)
        doc = {"status": record["status"], "evidenceLabel": record["evidenceLabel"],
               "reasons": record["reasons"], "path": str(out / "change-evidence.json"),
               "frames": {k: (out / v["frame"]["path"]) for k, v in record["arms"].items()
                          if v and v.get("frame")}}
        doc["html"] = None
        try:
            from agents.review_html import render

            doc["html"] = str(render(out / "change-evidence.json", out))
        except Exception:  # noqa: BLE001 - the page is a view of the record; failing to draw it changes no result
            (out / "render-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return doc
    except Exception as exc:  # noqa: BLE001 - a review never breaks or alters the overnight run
        (out / "review-error.txt").parent.mkdir(parents=True, exist_ok=True)
        (out / "review-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return {"status": "INCONCLUSIVE", "evidenceLabel": "MIXED OR INCOMPLETE",
                "reasons": [f"the review itself failed: {type(exc).__name__}"], "path": None, "frames": {},
                "html": None}


def _promote_candidate(attempt_out: Path, fix_out: Path) -> None:
    fix_out.mkdir(parents=True, exist_ok=True)
    for name in (
        "candidate.patch", "candidate.json", "muse.log", "muse-prompt.txt",
        "muse-env-names.json", "sandbox.json", "repair-request.json",
        "guard.json", "guard-log.jsonl",
    ):
        src = attempt_out / name
        if src.is_file():
            shutil.copy2(src, fix_out / name)
        elif name.startswith("guard") and (fix_out / name).is_file():
            (fix_out / name).unlink()  # never let an earlier attempt's guard log describe this one
    work = attempt_out / "fixer-work"
    dest = fix_out / "fixer-work"
    if work.is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(work, dest, ignore=shutil.ignore_patterns(".godot"))


def one_run(
    out: Path,
    *,
    use_muse: bool,
    offline_triage: bool,
    observations: Path | None,
    candidate_patch: Path | None,
    skip_harness: bool,
    run_trust: bool,
    before_frames: list[Path] | None = None,
    after_frames: list[Path] | None = None,
    require_sandbox: bool = False,
    feedback: Path | None = None,
    stability_runs: int = 0,
) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    signing_key = out / "verifier-host" / ".expectrail-signing-key"
    trust = None
    t0 = time.perf_counter()
    attempt_films: list[dict] = []
    confirmed: dict | None = None  # the stability check's summary, when --stability ran

    def _with_timing(payload: dict) -> dict:
        payload["timing"] = {"wallClockMs": round((time.perf_counter() - t0) * 1000, 3)}
        payload["attempts"] = attempt_films
        payload["attemptsConsumed"] = len(attempt_films)
        if confirmed is not None:
            payload.setdefault("stability", confirmed)
        return payload

    try:
        problem = sam_health.check() if use_muse or not offline_triage else None
        if problem is not None:
            reason = sam_health.reason(problem)
            write_preflight_stop(out / "morning", reason)
            return _with_timing({
                "decision": "needs-review",
                "error": reason,
                "preflight": problem,
                "trust": None,
                "morning": None,
                "gameplay": None,
                "verificationProvenance": "none",  # stopped before anything was verified
            })
        request = triage(
            spec=load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec"),
            verdict=load(REPO / "contracts" / "examples" / "verdict.json", "verdict"),
            route=load(REPO / "harness" / "routes" / "smoke.json", "route"),
            out=out / "triage",
            offline=offline_triage,
        )
        triage_meta = json.loads((out / "triage" / "triage.json").read_text(encoding="utf-8"))
        triage_source = triage_meta.get("source")
        # Live triage means a model answered: Wonder, or the BYO provider (agents.triage.call_byo).
        if not offline_triage and triage_source in (None, "offline", "offline-fallback"):
            from expectrail.providers import byo_requested
            which = "BYO" if byo_requested("TRIAGE") else "Wonder"
            raise SystemExit(
                f"live {which} triage required; got source={triage_source!r}"
            )
        if stability_runs:
            # A failing route counts only when it fails the same way on every replay of the base.
            report = stability.confirm_failing(request, out / "stability", runs=stability_runs, run=harness_run)
            confirmed = stability.summary(report, out / "stability" / "stability.json")
            if report["result"] != "fail":
                reason = (f"the failing route did not fail the same way on {stability_runs} replays of the "
                          f"failing base ({report['status']}: {report['reason']}), so no fix was attempted")
                write_preflight_stop(out / "morning", reason)
                return _with_timing({
                    "decision": "needs-review",
                    "error": reason,
                    "trust": None,
                    "morning": None,
                    "gameplay": None,
                    "triageSource": triage_source,
                    "verificationProvenance": "none",  # stopped before anything was verified
                })

        fix_out = out / "fix"
        max_attempts = 1 if not use_muse else int(request["budget"]["attempts"])
        fixture = None if use_muse else (
            candidate_patch or REPO / "agents" / "fixtures" / "fix-collision-mask.patch"
        )
        prior_reject: dict | None = None
        verification = None
        last_meta: dict | None = None
        # The report's screenshots: only a live fixer reads them, so only a live run renders them.
        report = render_report(request, out / "report") if use_muse and escalation.mode() == "report-first" else None
        rejected_before = False
        empty_before = False
        ladder: dict | None = None

        for attempt in range(1, max_attempts + 1):
            if signing_key.exists():
                signing_key.unlink()
            pub = signing_key.with_name(signing_key.name + ".pub")
            if pub.exists():
                pub.unlink()
            attempt_out = fix_out / f"attempt-{attempt:02d}"
            brief, stage = escalation.briefing(request, report, attempt, rejected_before, empty_before=empty_before)
            meta = run_fixer(
                request,
                attempt_out,
                candidate_patch=fixture,
                attempt=attempt,
                allow_empty=use_muse,
                require_sandbox=require_sandbox,
                # The report stage carries no verifier output; the evidence stage gets the public reasons.
                prior_reject=prior_reject if stage == "evidence" else None,
                briefing=brief,
            )
            last_meta = meta
            _promote_candidate(attempt_out, fix_out)
            film = {
                "attempt": attempt,
                "source": meta.get("source"),
                "ok": meta.get("ok", True),
                "empty": meta.get("empty", False),
                "patchSha256": meta.get("patchSha256"),
                "dir": str(attempt_out.relative_to(out)) if attempt_out.is_relative_to(out) else str(attempt_out),
                "briefing": stage if use_muse else "fixture",
            }
            attempt_films.append(film)

            if meta.get("empty"):
                if prior_reject is None:
                    prior_reject = {"reason": "empty-patch", "attempt": attempt}
                empty_before = True
                film["decision"] = "retry-empty"
                continue

            fixer_work = fix_out / "fixer-work"
            if not fixer_work.is_dir():
                raise SystemExit("fixer-work missing after fixer")
            leaked = list(fixer_work.rglob(".expectrail-signing-key"))
            if leaked:
                raise SystemExit(f"signing key leaked into fixer workspace: {leaked}")

            generate_run_keys(signing_key.parent)

            if run_trust and trust is None:
                trust = run_trust_check(
                    out / "trust",
                    fixer_work=fixer_work,
                    verifier_host=signing_key.parent,
                    require_sandbox=require_sandbox,
                )
                if not trust["ok"]:
                    return _with_timing({
                        "decision": "reject",
                        "error": "trust beat failed",
                        "trust": trust,
                        "morning": None,
                        "gameplay": None,
                        "triageSource": triage_source,
                        "fixerSource": meta.get("source"),
                        "verificationProvenance": "harness" if not skip_harness else "fixture",
                    })

            # The judge ladder: if the judge did not answer, the same candidate is judged again
            # (same judge, then Glimmer checked against the engine) before anything else happens.
            verification, verify_dir, ladder = judge_ladder.judge(
                request, fix_out / "candidate.patch", out / "verify" / f"attempt-{attempt:02d}",
                verify_fn=verify,
                observations_path=observations,
                skip_harness=skip_harness or observations is not None,
            )
            # Promote latest verify to out/verify for morning consumers.
            final_verify = out / "verify"
            for name in ("verification.json", "verdict-gameplay.json"):
                src = verify_dir / name
                if src.is_file():
                    final_verify.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, final_verify / name)
            film["decision"] = verification["decision"]
            film["reasons"] = verification.get("reasons")
            film["judge"] = ladder["judgedBy"]
            if len(ladder["steps"]) > 1:
                film["judgeSteps"] = ladder["steps"]
            if verification["decision"] == "accept":
                break
            if ladder["stopped"]:
                # No judge answered: the fix may well be right, so it is not sent back to the fixer.
                # The loop stops here and the morning report hands the candidate to a person.
                film["decision"] = "needs-review"
                break
            # Escalate: the next attempt gets the evidence and the public checks that did not pass,
            # never a held-out route or its reason (agents/escalation.py).
            prior_reject = escalation.public_feedback(verification, attempt)
            rejected_before = True
            empty_before = False
            for stale in (signing_key, signing_key.with_name(signing_key.name + ".pub")):
                if stale.exists():
                    stale.unlink()

        if verification is None or not (out / "verify" / "verification.json").is_file():
            return _with_timing({
                "decision": "reject",
                "error": "budget exhausted without an acceptable candidate",
                "trust": trust,
                "morning": None,
                "gameplay": None,
                "triageSource": triage_source,
                "fixerSource": (last_meta or {}).get("source"),
                "verificationProvenance": "harness" if not skip_harness else "fixture",
            })

        review_doc = None
        if review_on():
            source = str((last_meta or {}).get("source") or "")
            # The review compares the failing base with the candidate, so both must be judged by the
            # judge that decided. After a fallback that is Glimmer checked against the engine; asking
            # SAM about the base again would leave the review INCONCLUSIVE (docs/fallbacks.md).
            same_judge = (judge_ladder.backend(judge_ladder.FALLBACK) if (ladder or {}).get("fallback")
                          else nullcontext())
            with same_judge:
                review_doc = run_review(
                    request, fix_out / "candidate.patch", verify_dir / "verification.json", out / "review",
                    observations=observations,
                    origin="fixture" if source == "fixture" else "muse" if "muse" in source else "developer",
                )
        real = (review_doc or {}).get("frames") or {}
        if before_frames is None and after_frames is None and "base" in real and "candidate" in real:
            before_frames, after_frames = [real["base"]], [real["candidate"]]  # this run's own frames
        before = list(before_frames) if before_frames is not None else [DEFAULT_BEFORE]
        after = list(after_frames) if after_frames is not None else [DEFAULT_AFTER]
        if not before or not after:
            raise SystemExit("morning report requires non-empty before and after frames")
        if not signing_key.exists():
            generate_run_keys(signing_key.parent)
        verify_out = out / "verify"
        gameplay_path = verify_out / "verdict-gameplay.json"
        summary = build_report(
            verification=verification,
            candidate=fix_out / "candidate.patch",
            out=out / "morning",
            before=before,
            after=after,
            signing_key_path=signing_key,
            gameplay_verdict=gameplay_path if gameplay_path.is_file() else None,
            verification_path=verify_out / "verification.json",
            feedback=feedback,
            guard=fix_out / "guard.json" if (fix_out / "guard.json").is_file() else None,
            frames_illustrative=before_frames is None or after_frames is None,
            review=review_doc,
            unresolved=_unresolved(verification, ladder),
        )
        payload = {
            "decision": verification["decision"],
            "morning": summary,
            "gameplay": gameplay_film_stub(summary),
            "trust": trust,
            "triageSource": triage_source,
            "fixerSource": (last_meta or {}).get("source"),
            "verificationProvenance": "harness" if not skip_harness else "fixture",
        }
        if review_doc is not None:
            payload["review"] = {k: v for k, v in review_doc.items() if k != "frames"}
        if ladder is not None:
            payload["judge"] = ladder
        return _with_timing(payload)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 — overnight loop must not forge accept
        (out / "loop-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        payload = {
            "decision": "reject",
            "error": f"{type(exc).__name__}: {exc}",
            "trust": trust,
            "morning": None,
            "gameplay": None,
            "verificationProvenance": "harness" if not skip_harness else "fixture",
        }
        if "triage_source" in locals() and triage_source is not None:
            payload["triageSource"] = triage_source
        fix_meta = out / "fix" / "candidate.json"
        if fix_meta.is_file():
            try:
                payload["fixerSource"] = json.loads(fix_meta.read_text(encoding="utf-8")).get("source")
            except (OSError, json.JSONDecodeError):
                pass
        return _with_timing(payload)


def main(argv: list[str] | None = None) -> int:
    from agents.keys import load_dotenv
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=Path("runs/loop"))
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--mode", choices=("auto", "offline", "live"), default="auto")
    p.add_argument("--use-muse", action="store_true", help="force Muse Code (sealed: not with --mode offline)")
    p.add_argument("--online-triage", action="store_true", help="force Wonder triage (sealed)")
    p.add_argument("--offline-triage", action="store_true", help="force offline triage (sealed: not with --mode live)")
    p.add_argument("--observations", type=Path,
                   default=REPO / "agents" / "fixtures" / "obs-fixed.json")
    p.add_argument("--candidate-patch", type=Path)
    p.add_argument("--skip-harness", action="store_true", default=True)
    p.add_argument("--no-skip-harness", action="store_true")
    p.add_argument("--no-trust", action="store_true", help="skip trust beat (not for demo path)")
    p.add_argument("--require-sandbox", action="store_true",
                   help="require OS sandbox for Muse + trust blocked canary")
    p.add_argument("--before", type=Path, action="append", default=[],
                   help="before frame(s) for morning report (default: fixture PNG)")
    p.add_argument("--after", type=Path, action="append", default=[],
                   help="after frame(s) for morning report (default: fixture PNG)")
    p.add_argument("--feedback", type=Path,
                   help="feedback-intake.json from agents.feedback, shown in each morning report")
    p.add_argument("--stability", action="store_true",
                   help="replay the failing route on the failing base before the fixer starts; only a "
                        "stable failure is fixed (off by default; needs Godot)")
    p.add_argument("--stability-runs", type=int, default=stability.STABILITY_RUNS,
                   help="with --stability: replays of the failing base (default 3)")
    args = p.parse_args(argv)
    if args.stability and args.stability_runs < 2:
        p.error("--stability-runs must be at least 2")
    # A mistyped EXPECTRAIL_OBS_PROVIDER is a configuration error: stop here, before the fixer
    # runs, rather than let verify fail later and be recorded as a rejected candidate.
    from agents.observations import resolve_provider
    resolve_provider()
    if args.feedback is not None:
        validate(load(args.feedback, "feedback-intake"), "feedback-intake")  # fail now, not mid-run

    resolved = seal_mode_flags(
        resolve_mode(args.mode),
        force_offline_triage=args.offline_triage,
        force_online_triage=args.online_triage,
        force_muse=args.use_muse,
    )
    offline_triage = resolved["offline_triage"]
    use_muse = resolved["use_muse"]
    if use_muse:
        from agents.keys import require_separate_byo_keys, require_separate_sam_key
        require_separate_sam_key()
        require_separate_byo_keys()
    skip_harness = False if args.no_skip_harness else args.skip_harness
    observations = None if args.no_skip_harness else args.observations
    provenance = "harness" if not skip_harness else "fixture"
    before_frames = args.before or None
    after_frames = args.after or None

    from agents.keys import byo_fixer_agent
    from expectrail.providers import byo_requested
    live_triage = "byo" if byo_requested("TRIAGE") else "wonder"
    live_fixer = byo_fixer_agent() or "muse"
    print(
        f"mode={resolved['mode']} triage={'offline' if offline_triage else live_triage} "
        f"fixer={live_fixer if use_muse else 'fixture'} harness={provenance}"
    )

    started = datetime.now(timezone.utc)
    t_loop = time.perf_counter()
    results = []
    for i in range(args.runs):
        run_out = args.out / f"run-{i:02d}"
        results.append(one_run(
            run_out,
            use_muse=use_muse,
            offline_triage=offline_triage,
            observations=observations,
            candidate_patch=args.candidate_patch,
            skip_harness=skip_harness,
            run_trust=not args.no_trust,
            before_frames=before_frames,
            after_frames=after_frames,
            require_sandbox=args.require_sandbox,
            feedback=args.feedback,
            stability_runs=args.stability_runs if args.stability else 0,
        ))
        print(f"run {i}: {results[-1]['decision']}"
              + (f" ({results[-1].get('error')})" if results[-1].get("error") else ""))

    finished = datetime.now(timezone.utc)
    accepted = sum(1 for r in results if r["decision"] == "accept")
    if offline_triage and not use_muse:
        cost = {
            "modelCalls": 0,
            "costUsd": None,
            "costProvenance": "unmetered-offline",
        }
    else:
        # Only Muse attempts count as model calls; fixture/auto-without-muse stays 0.
        muse_calls = 0
        if use_muse:
            muse_calls = sum(int(r.get("attemptsConsumed") or 0) for r in results)
        cost = {
            "modelCalls": muse_calls,
            "costUsd": None,
            "costProvenance": "unmetered-live-unset",
        }
    summary = {
        "format": "expectrail.overnight-summary/v0",
        "mode": resolved,
        "runs": args.runs,
        "accepted": accepted,
        "verificationProvenance": provenance,
        "cost": cost,
        "timing": {
            "wallClockMs": round((time.perf_counter() - t_loop) * 1000, 3),
            "startedAt": started.isoformat(),
            "finishedAt": finished.isoformat(),
        },
        "results": results,
    }
    validate(summary, "overnight-summary")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    rollup = write_loop_rollup(args.out, summary=summary)
    print(f"{accepted} of {args.runs} accepted; morning rollup: {rollup}")
    return 0 if accepted == args.runs else 1


if __name__ == "__main__":
    sys.exit(main())
