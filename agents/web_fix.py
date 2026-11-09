"""Second domain, end to end: Muse Code fixes each checkout-page bug, and the verifier decides.

The game's fix matrix (agents/matrix.py) on the web checkout page (apps/checkout). For each seeded
bug and each condition, the bugged page is replayed and judged; Muse Code gets a briefing in a
workspace that holds only the page (the same fixer, sandbox and guard as the game:
``agents.fixer.run_fixer``); every candidate goes to the verifier below; up to three attempts.

Conditions, as in the game:
  - ``screenshots``: screenshots of the bugged session, the route and the shopper's report in plain
    English. No spec, no verdict. Between attempts it learns only that the attempt failed.
  - ``expectrail``: the same files, plus the repair request (the approved specs that failed, the
    evaluator's verdicts with their evidence) and the verifier's reasons after a rejected attempt.
    Expectrail opens a repair only when its own checks caught the bug.

The verifier (``verify``) is the shared one, ``agents.domain_verifier``, given the page's specs, its
layout log as engine observations, the order going through as the behaviour check, both public
sessions and the private ones. It writes the game's verification contract with the same check kinds
and the same decision rule (``expectrail.evaluator.decide``): ``regression`` (every spec on both public
sessions, judged by SAM with SAM on, by the layout log without), ``gameplay`` (the order goes
through), ``clean`` (the same specs pass on the clean page, so a broken checker cannot accept), and
``held-out`` (private sessions from ``$EXPECTRAIL_HELDOUT_DIR/web/routes``, never in the fixer's
workspace or the repository; needs-review when they are not mounted).

    python3 -m agents.web_fix --list
    python3 -m agents.web_fix --case dev/layering/v1 --condition expectrail --out runs/web-fix --live
    python3 -m agents.web_fix --case dev/layering/v1 --condition expectrail --fixture-candidate fix.patch

``--adapter`` (default ``web``) names the engine that replays the page and whose project, editable
files and prompt wording the fixer gets; like ``agents.web_bench`` it takes any adapter that writes the
web trace.

Each case prints the fix matrix's annotation, so ``agents.bench_collect --matrix`` records a run.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

from agents import domain_verifier, web_bench
from agents.fixer import run_fixer
from agents.sam_observations import sam_images_since, sam_usage
from expectrail.contracts import load, validate
from harness import adapters
from harness.adapters import Adapter
from harness.run import REPO
from harness.web import layout
from harness.web.run import WebHarnessError, load_route

FORMAT = "expectrail.fix-matrix/v0"
SITE = adapters.get("web").game_root  # apps/checkout/site
CONDITIONS = ("screenshots", "expectrail")
EDITABLE = list(adapters.get("web").editable)  # checkout/index.html, checkout.css, checkout.js
ATTEMPTS = 3
SCREENSHOT_FRAMES = (0, 6, 12, 13)
BRIEFING_DIR = "bug-report"
BEHAVIOUR_SPEC = "checkout-order-goes-through"
BEHAVIOUR_INSTRUCTION = "When the shopper clicks Continue to checkout, the order goes through."
# What a shopper would say about each family: the screenshots condition's whole bug report.
REPORTS = {
    "layering": "I can't see the Continue to checkout button.",
    "missing-texture": "Part of the checkout page doesn't show up.",
    "fall-through": "The Continue to checkout button is missing.",
    "sinking": "The Continue to checkout button is in the wrong place.",
}


def dev_variants() -> dict[str, Path]:
    return web_bench.dev_variants()


def _specs() -> list[dict]:
    return [load(p, "test-spec") for p in web_bench.SPECS]


def _held_out_dir() -> Path | None:
    """The page's private sessions, ``$EXPECTRAIL_HELDOUT_DIR/web/routes``; None when the set is not mounted."""
    raw = os.environ.get("EXPECTRAIL_HELDOUT_DIR", "").strip()
    return Path(raw) / "web" / "routes" if raw else None


def _held_out_routes() -> tuple[list[Path] | None, str | None]:
    return domain_verifier.held_out_routes(_held_out_dir())


def verify(request: dict, candidate: Path, out: Path, attempt: int = 1, adapter: str | Adapter = "web") -> dict:
    """The verifier for the checkout page: the shared verifier with the page's checks."""
    _decision, doc = domain_verifier.verify(
        adapter, request, candidate, out, specs=_specs(), observe=layout.layout_observations,
        behaviour=layout.behaviour, behaviour_spec=BEHAVIOUR_SPEC, routes=web_bench.ROUTES,
        held_out=_held_out_dir(), label="layout", vision=web_bench.SAM if web_bench.sam_on() else None,
        attempt=attempt)
    return doc


def detect(patch: Path, out: Path, use_sam: bool, adapter: str = "web") -> dict:
    """Replay the bugged page on the desktop session; every spec and the order, judged."""
    route = web_bench.ROUTES[0]
    run_dir = out / "bugged"
    specs = _specs()
    web_bench.judge_route(route, [patch], run_dir, specs, use_sam, adapter=adapter)
    failing = []
    for spec in specs:
        path = run_dir / (f"verdict-sam-{spec['id']}.json" if use_sam else f"verdict-layout-{spec['id']}.json")
        if path.is_file():
            verdict = json.loads(path.read_text(encoding="utf-8"))
            if verdict["result"] == "fail":
                failing.append({"spec": spec, "verdict": verdict})
    behaviour = layout.behaviour(json.loads((run_dir / "trace.json").read_text(encoding="utf-8")))
    detection = {"failing": [f["spec"]["id"] for f in failing], "behaviour": behaviour["result"]}
    (out / "detection.json").write_text(json.dumps(detection, indent=2) + "\n", encoding="utf-8")
    return {"route": route, "runDir": run_dir, "failing": failing, "behaviour": behaviour}


def briefing_files(detection: dict) -> dict[str, Path]:
    frames = sorted((detection["runDir"] / "frames").glob("f*.png"))
    files = {f"{BRIEFING_DIR}/screenshots/step-{n:02d}.png": frames[n] for n in SCREENSHOT_FRAMES if n < len(frames)}
    files[f"{BRIEFING_DIR}/session.json"] = detection["route"]
    return files


def _rules(attempt: int, editable: list[str] | tuple[str, ...] = tuple(EDITABLE)) -> str:
    return (f"## Rules\n- Only edit these files (relative to the workspace root): {', '.join(editable)}\n"
            f"- Do not edit anything under {BRIEFING_DIR}/ or assets/, and do not create other files.\n"
            "- Produce the smallest correct fix. When done, leave the files edited; do not commit.\n\n"
            f"Attempt {attempt} of {ATTEMPTS}.")


def screenshots_prompt(family: str, files: dict[str, Path], attempt: int, prior: bool,
                       adapter: str | Adapter = "web") -> str:
    adapter = adapters.resolve(adapter)
    shots = sorted(f for f in files if "/screenshots/" in f)
    again = "\n\nYour previous attempt did not fix the bug. Look again." if prior else ""
    return (f"You are fixing a bug in {adapter.prompt_subject} (checkout/index.html, checkout/checkout.css).\n\n"
            f"## Bug report\nA shopper filled in the checkout form and continued to checkout (the steps are in "
            f"{BRIEFING_DIR}/session.json) and reports: \"{REPORTS[family]}\"\n\n"
            f"Screenshots of that session, in order: {', '.join(shots)}. Open and look at each one.{again}\n\n"
            + _rules(attempt, adapter.editable) + "\n")


def expectrail_prompt(request: dict, files: dict[str, Path], attempt: int, adapter: str | Adapter = "web") -> str:
    adapter = adapters.resolve(adapter)
    shots = sorted(f for f in files if "/screenshots/" in f)
    blocks = []
    for i, item in enumerate(request["failing"]):
        spec, verdict = item["spec"], item["verdict"]
        blocks.append("\n".join([f"### Failing check {i + 1}", f"- Spec id: {spec['id']}",
                                 f"- Instruction: {spec['instruction']}",
                                 f"- Assertion: {json.dumps(spec['assertion'], sort_keys=True)}",
                                 f"- Verdict: {verdict['result']} - {verdict['reason']}",
                                 f"- First failing step (frame): {verdict.get('firstFrame')}",
                                 f"- Evidence: {json.dumps((verdict.get('evidence') or [])[:3])}"]))
    return (f"You are fixing a bug in {adapter.prompt_subject} (checkout/index.html, checkout/checkout.css).\n\n"
            f"Read the repair request at repair-request.json: the checks that failed on the shopper's session "
            f"and the evaluator's evidence. The bug is already applied in this workspace.\n\n"
            f"## Failing checks and evidence\n" + ("\n\n".join(blocks) or "(none)") + "\n\n"
            f"{request.get('notes', '')}\n\n"
            f"Screenshots of the failing session (open and look at each one): {', '.join(shots)}; "
            f"the session's steps are in {BRIEFING_DIR}/session.json.\n"
            "- Do not read or search for signing keys, held-out sessions or evaluator code.\n\n"
            + _rules(attempt, adapter.editable) + "\n")


def build_request(key: str, patch: Path, detection: dict, files: dict[str, Path],
                  adapter: str | Adapter = "web") -> dict:
    adapter = adapters.resolve(adapter)
    route_doc = load_route(detection["route"])
    frames = sorted(f for f in files if "/screenshots/" in f)
    notes = "Held-out sessions, the evaluator and the behaviour check are not in your workspace."
    doc = {"format": "expectrail.repair-request/v0", "id": f"rr-web-{key.replace('/', '-')}",
           "base": {"tree": adapter.tree_digest(), "patch": str(patch.relative_to(REPO))},
           "editable": list(adapter.editable),
           "failing": [{"spec": f["spec"], "verdict": f["verdict"], "route": route_doc, "keyFrames": frames}
                       for f in detection["failing"]],
           "budget": {"attempts": ATTEMPTS, "minutesPerAttempt": 15}, "notes": notes}
    if detection["behaviour"]["result"] == "fail":
        # The behaviour check is the harness's, not a test spec; it goes in as one failing item.
        doc["failing"].append({"spec": {"id": BEHAVIOUR_SPEC, "instruction": BEHAVIOUR_INSTRUCTION,
                                        "assertion": {"type": "behaviour", "step": "click Continue to checkout"}},
                               "verdict": {"result": "fail", "reason": detection["behaviour"]["reason"],
                                           "firstFrame": None, "evidence": []},
                               "route": route_doc, "keyFrames": frames})
    if not doc["failing"]:
        # Nothing caught it (the screenshots condition still runs): the request records the session only.
        doc["failing"] = [{"spec": {"id": "none", "instruction": "no check failed"},
                           "verdict": {"result": "pass", "reason": "no check failed"}, "route": route_doc}]
    validate(doc, "repair-request")
    return doc


def run_case(key: str, condition: str, out: Path, *, live: bool, fixture: Path | None = None,
             require_sandbox: bool = False, adapter: str = "web") -> dict:
    if condition not in CONDITIONS:
        raise SystemExit(f"unknown condition {condition!r}")
    dev = dev_variants()
    if key not in dev:
        raise SystemExit(f"{key}: no such web variant")
    patch, family = dev[key], key.split("/")[1]
    use_sam = web_bench.sam_on()
    work = out / key.replace("/", "_") / condition
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    t0 = time.perf_counter()
    row: dict = {"case": key, "condition": condition, "live": live, "sam": use_sam, "private": False,
                 "attempts": [], "_samBefore": sam_usage(), "app": "checkout"}
    try:
        detection = detect(patch, work, use_sam, adapter)
        caught = bool(detection["failing"]) or detection["behaviour"]["result"] == "fail"
        row["detected"] = "fail" if caught else "pass"
        if condition == "expectrail" and not caught:
            row.update(outcome="not-detected", detail="Expectrail's checks did not catch it on the desktop session")
            return _finish(row, work, t0)
        files = briefing_files(detection)
        request = build_request(key, patch, detection, files, adapter)
        (work / "repair-request.json").write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
        offline = fixture or (work / "empty.patch")
        if fixture is None:
            offline.write_text("", encoding="utf-8")
        prior: dict | None = None
        for attempt in range(1, ATTEMPTS + 1):
            attempt_out = work / f"attempt-{attempt:02d}"
            if condition == "screenshots":
                briefing = {"prompt": screenshots_prompt(family, files, attempt, prior is not None, adapter),
                            "policy": "web-matrix-screenshots-v1", "files": files, "withRequest": False}
                feedback = {"attempt": attempt - 1, "decision": "reject"} if prior else None
            else:
                briefing = {"prompt": expectrail_prompt(request, files, attempt, adapter),
                            "policy": "web-matrix-expectrail-v1", "files": files, "withRequest": True}
                feedback = prior
            meta = run_fixer(request, attempt_out, candidate_patch=None if live else offline,
                             game=adapters.resolve(adapter).game_root, attempt=attempt, allow_empty=True,
                             prior_reject=feedback, briefing=briefing, require_sandbox=require_sandbox,
                             adapter=adapter)
            film = {"attempt": attempt, "source": meta.get("source"), "empty": meta.get("empty", False),
                    "patchSha256": meta.get("patchSha256")}
            if meta.get("timedOut"):
                film["timedOut"] = True
            row["attempts"].append(film)
            candidate = attempt_out / "candidate.patch"
            if meta.get("empty") or not candidate.read_text(encoding="utf-8").strip():
                film["decision"] = "timeout" if meta.get("timedOut") else "empty"
                prior = {"decision": "reject", "attempt": attempt,
                         "reasons": ["the attempt changed no editable file"]}
                if not live:
                    break
                continue
            v = verify(request, candidate, work / "verify" / f"attempt-{attempt:02d}", attempt=attempt, adapter=adapter)
            film["decision"] = v["decision"]
            film["reasons"] = v["reasons"]
            if use_sam:
                # Public sessions only: what SAM found against where the candidate page drew it.
                film["samSeen"] = {r.stem: web_bench.sam_seen(work / "verify" / f"attempt-{attempt:02d}" / "candidate" / r.stem)
                                   for r in web_bench.ROUTES}
            if v["decision"] == "accept" or not live:
                break
            prior = {"decision": v["decision"], "reasons": v["reasons"], "attempt": attempt}
        decisions = [a.get("decision") for a in row["attempts"]]
        row["outcome"] = "fixed" if "accept" in decisions else "needs-review" if "needs-review" in decisions else "not-fixed"
        return _finish(row, work, t0)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - a crash is recorded, never counted as a fix
        (work / "matrix-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        row.update(outcome="error", detail=f"{type(exc).__name__}: {exc}"[:300])
        return _finish(row, work, t0)


def _finish(row: dict, work: Path, t0: float) -> dict:
    row["format"] = FORMAT
    row["wallClockSeconds"] = round(time.perf_counter() - t0, 1)
    row["samImages"] = sam_images_since(row.pop("_samBefore"))
    row["attemptsUsed"] = len(row["attempts"])
    (work / "result.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    return row


def annotation(row: dict) -> str:
    """The fix matrix's annotation, so agents.bench_collect --matrix reads a run unchanged."""
    tries = "; ".join(f"{a['attempt']}: {a.get('decision')}" for a in row["attempts"])
    line = (f"::notice title=Fix matrix {row['case']} {row['condition']}::detected {row.get('detected')}; "
            f"outcome {row['outcome']}; attempts {row['attemptsUsed']} ({tries}); {row['wallClockSeconds']} s; "
            f"live={row['live']}" + (f"; SAM images {row['samImages']}" if row.get("samImages") is not None else ""))
    if row.get("detail"):
        line += f"\n::warning title=Fix matrix {row['case']} {row['condition']} detail::{' '.join(row['detail'].split())[:300]}"
    for a in row["attempts"]:
        if not a.get("reasons"):
            continue
        # The decision's own reasons (a held-out check is named by spec and kind only, on the aggregate
        # route "held-out-routes", as the fixer's retry prompt already gets it), then SAM's view of the
        # public sessions. Nothing from a private session's contents.
        seen = "; ".join(f"{route}: {', '.join(lines)}" for route, lines in (a.get("samSeen") or {}).items() if lines)
        line += (f"\n::notice title=Verify {row['case']} {row['condition']} attempt-{a['attempt']:02d}::{a['decision']}: "
                 + "; ".join(a["reasons"][:6]) + (f" (+{len(a['reasons']) - 6} more)" if len(a["reasons"]) > 6 else "")
                 + (f" | SAM {seen}" if seen else ""))
    return line


def check_held_out(out: Path, use_sam: bool = False, adapter: str = "web") -> list[str]:
    """Each private session on the clean page, judged as the verifier will judge a candidate: layout
    and behaviour, and with ``use_sam`` every SAM check too (two sessions, about 90 SAM images). A
    session the clean page fails would reject every candidate, so it is caught before Muse spends.
    The layout-only check missed one: the clean page passed it but failed the SAM inside-the-form
    check at the private screen sizes, and the first full run rejected every correct fix for it.
    Prints only a session's number and the public check names that failed, never its contents."""
    held, problem = _held_out_routes()
    if held is None:
        return [f"held-out: {problem}"]
    specs = _specs()
    lines = []
    for n, route in enumerate(held):
        try:
            load_route(route)
        except (WebHarnessError, OSError, ValueError):
            lines.append(f"held-out r{n}: not a valid web route")
            continue
        run_dir = out / "held-out-check" / f"r{n}"
        checks = web_bench.judge_route(route, [], run_dir, specs, use_sam=use_sam, adapter=adapter)
        bad = [c if r == "fail" else f"{c} ({r})" for c, r in checks.items() if r != "pass"]
        failing_specs = [s["id"] for s in specs
                         if json.loads((run_dir / f"verdict-layout-{s['id']}.json").read_text(encoding="utf-8")
                                       if (run_dir / f"verdict-layout-{s['id']}.json").is_file()
                                       else '{"result": "needs-review"}')["result"] != "pass"]
        if bad:
            lines.append(f"held-out r{n}: the clean page fails {', '.join(bad)}"
                         + (f" (layout: {', '.join(failing_specs)})" if "layout" in bad and failing_specs else ""))
        else:
            lines.append(f"held-out r{n}: the clean page passes")
    return lines


def main(argv: list[str] | None = None) -> int:
    from agents.keys import load_dotenv

    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--case")
    g.add_argument("--check-held-out", action="store_true",
                   help="replay each private session on the clean page and say whether it passes "
                        "(with EXPECTRAIL_OBS_PROVIDER=sam, SAM's checks too)")
    p.add_argument("--condition", choices=CONDITIONS)
    p.add_argument("--out", type=Path, default=REPO / "runs" / "web-fix")
    p.add_argument("--live", action="store_true", help="run Muse Code (spends Meta credit)")
    p.add_argument("--fixture-candidate", type=Path, help="offline: verify this patch instead of an empty one")
    p.add_argument("--require-sandbox", action="store_true")
    p.add_argument("--adapter", choices=web_bench.web_adapters(), default="web",
                   help="the engine that replays the page (default web: Chromium through Playwright)")
    args = p.parse_args(argv)
    if args.list:
        print(json.dumps(sorted(dev_variants())))
        return 0
    if args.check_held_out:
        lines = check_held_out(args.out, use_sam=web_bench.sam_on(), adapter=args.adapter)
        print("\n".join(lines))
        # Not mounted is not an error here: every verdict is then needs-review, and run_case says so.
        return 1 if any(" fails " in line or "not a valid" in line for line in lines) else 0
    if not args.condition:
        p.error("--condition is required with --case")
    row = run_case(args.case, args.condition, args.out, live=args.live, fixture=args.fixture_candidate,
                   require_sandbox=args.require_sandbox, adapter=args.adapter)
    print(annotation(row))
    return 0 if row["outcome"] != "error" else 1


if __name__ == "__main__":
    sys.exit(main())
