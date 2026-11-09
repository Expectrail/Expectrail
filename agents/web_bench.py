"""Detection bench for the second domain, a web checkout page: would the verifier catch each bug?

The game's held-out bench (agents/heldout_bench.py), on a web app. For the clean page and each seeded
bug, every route is replayed in Chromium (harness/web) and every check is judged by the same
evaluator, on the same kind of evidence:

- ``layout``: every spec in apps/checkout/specs judged on the page's layout log (the game's
  ``engine`` check: what the layout says, as the engine's position log says where the robot is);
- ``behaviour``: the shopper's checkout click went through and the order was submitted (the game's
  ``gameplay`` check);
- with SAM on, each spec whose objects SAM can see judged on SAM 3.1's view of the frames, and
  ``hybrid``: the inside-the-form spec judged on SAM's box for the button against the form's layout
  box (the game's hybrid ground check: SAM's robot box against the engine's ground line).

The output and its annotation are the held-out bench's, so ``agents.bench_collect`` records a run
unchanged. Development variants are apps/checkout/bugs/<family>/vN.patch; held-out variants come
from ``$EXPECTRAIL_HELDOUT_DIR/web/manifest.json`` (patches only, ids and counts printed, nothing
else).

    python3 -m agents.web_bench --list --set dev
    python3 -m agents.web_bench --variant dev/layering/v1 --out runs/web-bench [--adapter web]

``--adapter`` names the engine that replays the page (harness/adapters.py). It takes any registered
adapter whose replays write the web trace (``expectrail.web-trace/v0``), since every check here reads
that trace; today that is ``web``, Chromium through Playwright.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from agents import domain_verifier
from agents.domain_verifier import Vision, worst
from agents.heldout_bench import CLEAN, DEV_PREFIX, RESULTS, annotation, caught, public_error
from expectrail.contracts import load
from expectrail.evaluator import evaluate
from harness import adapters
from harness.run import REPO
from harness.web import layout
from harness.web.run import TRACE_FORMAT

APP = REPO / "apps" / "checkout"
ROUTES = sorted((REPO / "harness" / "web" / "routes").glob("*.json"))
SPECS = sorted((APP / "specs").glob("*.json"))
HYBRID_SPEC = "checkout-button-inside-form"
SAM_ON_CHECKS = ("hybrid", "behaviour")  # plus every SAM spec
SAM_OFF_CHECKS = ("layout", "behaviour")
ERRORS_FILE = "bench-errors.json"


def dev_variants() -> dict[str, Path]:
    return {f"{DEV_PREFIX}{p.parent.name}/{p.stem}": p for p in sorted((APP / "bugs").glob("*/v*.patch"))}


def held_out() -> tuple[Path | None, dict | None]:
    raw = os.environ.get("EXPECTRAIL_HELDOUT_DIR", "").strip()
    if not raw:
        return None, None
    root = Path(raw) / "web"
    manifest = root / "manifest.json"
    if not manifest.is_file():
        return root, None
    return root, json.loads(manifest.read_text(encoding="utf-8"))


def held_out_variants() -> dict[str, Path]:
    root, manifest = held_out()
    if manifest is None:
        return {}
    return {f"{v['family']}/{v['id']}": root / v["patch"] for v in manifest.get("variants") or []
            if not v.get("retired")}


def set_ids(which: str) -> list[str]:
    return [CLEAN] + sorted(dev_variants() if which == "dev" else held_out_variants())


def web_adapters() -> list[str]:
    """The registered adapters whose replays write the web trace these checks read."""
    return [n for n in adapters.names() if adapters.get(n).trace_format == TRACE_FORMAT]


def sam_on() -> bool:
    return os.environ.get("EXPECTRAIL_OBS_PROVIDER", "trace").strip().lower() == "sam"


def sam_visible(spec: dict) -> bool:
    """A spec SAM judges on its own: every object it names is one SAM is asked to find."""
    return spec["id"] != HYBRID_SPEC


def _sam_names(specs: list[dict]) -> list[str]:
    return ["hybrid"] + [s["id"] for s in specs if sam_visible(s)]


def _sam_judge(trace: dict, replay_sha: str, run_dir: Path, specs: list[dict]) -> tuple[dict[str, str], list[str]]:
    """SAM 3.1 on one replay's frames: each spec SAM can see on its own, and the hybrid inside-the-form
    spec (SAM's box for the button against the form's layout box). A SAM box counts only on the page's
    paint box for that element (layout.agreeing)."""
    from agents.sam_observations import SamError, from_replay

    results: dict[str, str] = {}
    errors: list[str] = []
    for spec in specs:
        key = "hybrid" if not sam_visible(spec) else spec["id"]
        engine = {n for n, o in spec["objects"].items() if n == "form"}
        try:
            seen = [n for n in spec["objects"] if n not in engine]
            obs = from_replay(trace, replay_sha, frames_dir=run_dir / "frames", spec=spec,
                              engine_objects=layout.engine_objects(trace, sorted(engine)) if engine else None,
                              keep=layout.agreeing(trace, seen))
            obs["model"]["pageCheck"] = layout.PAGE_CHECK
            verdict = evaluate(spec, obs)
            results[key] = verdict["result"]
            (run_dir / f"sam-{spec['id']}.json").write_text(json.dumps(obs, indent=1) + "\n", encoding="utf-8")
            (run_dir / f"verdict-sam-{spec['id']}.json").write_text(json.dumps(verdict, indent=1) + "\n",
                                                                    encoding="utf-8")
        except SamError as exc:
            results[key] = "needs-review"
            errors.append(f"{key}: {exc}")
    return results, errors


SAM = Vision(label="sam", judge=_sam_judge, names=_sam_names)


def judge_route(route: Path, patches: list[Path], run_dir: Path, specs: list[dict], use_sam: bool,
                adapter: str = "web") -> dict[str, str]:
    """One route on the page, judged by the shared verifier's judge: every spec on the layout log
    (``layout``), the order (``behaviour``) and, with SAM on, SAM's checks."""
    return domain_verifier.judge_route(adapter, route, patches, run_dir, specs, layout.layout_observations,
                                       layout.behaviour, label="layout", vision=SAM if use_sam else None)


def bench(key: str, out: Path, adapter: str = "web") -> dict:
    dev, held = dev_variants(), held_out_variants()
    if key == CLEAN:
        patches: list[Path] = []
    elif key in dev:
        patches = [dev[key]]
    elif key in held:
        patches = [held[key]]
    else:
        raise SystemExit(f"{key}: no such web variant")
    use_sam = sam_on()
    specs = [load(p, "test-spec") for p in SPECS]
    from agents.sam_observations import sam_images_since, sam_usage

    before = sam_usage()
    work = out / key.replace("/", "_")
    per_route = [{"route": r.stem, "checks": judge_route(r, patches, work / r.stem, specs, use_sam, adapter=adapter)}
                 for r in ROUTES]
    errors: list[str] = []
    for row in per_route:
        path = work / row["route"] / ERRORS_FILE
        if path.is_file():
            for message in json.loads(path.read_text(encoding="utf-8")):
                if public_error(message) not in errors:
                    errors.append(public_error(message))
    names = list(per_route[0]["checks"])
    per_check = {c: {r: sum(row["checks"].get(c) == r for row in per_route) for r in RESULTS} for c in names}
    sam_checks = list(SAM_ON_CHECKS) + [s["id"] for s in specs if sam_visible(s)]
    doc = {"format": "expectrail.web-bench/v0", "variant": key, "app": "checkout", "sam": use_sam, "judge": "sam" if use_sam else "layout",
           "routes": len(per_route), "checks": per_check,
           "caughtWithSamOn": caught(per_check, sam_checks) if use_sam else None,
           "caughtWithGlimmerEngine": None,
           "caughtWithSamOff": caught(per_check, list(SAM_OFF_CHECKS)),
           "errors": errors[:5], "samImages": sam_images_since(before), "perRoute": per_route}
    work.mkdir(parents=True, exist_ok=True)
    (work / "bench.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def detail_lines(doc: dict, out: Path) -> list[str]:
    """Public variants only: each route's checks with the evaluator's reason, so a reader can see which
    session a check failed on and why (a held-out variant prints counts only)."""
    work = out / doc["variant"].replace("/", "_")
    lines = []
    for row in doc["perRoute"]:
        parts = []
        for check, result in row["checks"].items():
            reason = ""
            if check == "layout":
                failed = []
                for path in sorted((work / row["route"]).glob("verdict-layout-*.json")):
                    v = json.loads(path.read_text(encoding="utf-8"))
                    if v.get("result") != "pass":
                        failed.append(f"{path.stem[len('verdict-layout-'):]}: {v.get('reason', '')}")
                reason = "; ".join(failed)
            for prefix in ("verdict-sam-", "verdict-layout-"):
                spec_id = HYBRID_SPEC if check == "hybrid" else check
                path = work / row["route"] / f"{prefix}{spec_id}.json"
                if check != "layout" and path.is_file():
                    reason = json.loads(path.read_text(encoding="utf-8")).get("reason", "")
                    break
            parts.append(f"{check} {result}" + (f" ({' '.join(reason.split())[:120]})" if reason and result != "pass" else ""))
        parts += sam_seen(work / row["route"])
        lines.append(f"::notice title=Bench detail {doc['variant']} {row['route']}::" + "; ".join(parts))
    return lines


def iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def sam_seen(run_dir: Path) -> list[str]:
    """What SAM found against what the page drew, for calibrating prompts and thresholds: on the last
    frame SAM looked at, its best box and score for each object it was asked for, how many other
    matches cleared the evaluator's default score, and where the page drew the element; then, over
    every frame SAM looked at, the lowest score of a match on the drawn element (IoU 0.5 or more) and
    the highest score of anything else. A minScore between the two separates them."""
    from expectrail.evaluator import DEFAULT_MIN_SCORE

    try:
        trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = {row["frame"]: row for row in trace["rows"]}
    seen: dict[str, str] = {}
    for path in sorted(run_dir.glob("sam-*.json")):
        obs = json.loads(path.read_text(encoding="utf-8"))
        frames = [f for f in obs.get("frames", []) if f["frame"] in rows]
        if not frames:
            continue
        last = max(frames, key=lambda f: f["frame"])
        for name in obs.get("model", {}).get("prompts", {}):
            found = last["objects"].get(name) or []
            if name in seen:
                continue
            element = rows[last["frame"]]["elements"].get(name) or {}
            drawn = [round(v) for v in element.get("painted", [])] if element.get("shown") else "hidden"
            ranked = sorted(found, key=lambda d: -(d.get("score") or 0))
            if not ranked:
                seen[name] = f"SAM {name}: none (drawn at {drawn})"
                continue
            best = ranked[0]
            others = sum((d.get("score") or 0) >= DEFAULT_MIN_SCORE for d in ranked[1:])
            seen[name] = (f"SAM {name}: {[round(v) for v in best['box']]} @{best.get('score', 0):.2f}"
                          f" +{others} (drawn at {drawn})")
    for name in list(seen):
        matches, other = [], 0.0
        for path in sorted(run_dir.glob("sam-*.json")):
            obs = json.loads(path.read_text(encoding="utf-8"))
            if name not in obs.get("model", {}).get("prompts", {}):
                continue
            for frame in obs.get("frames", []):
                element = (rows.get(frame["frame"]) or {}).get("elements", {}).get(name) or {}
                truth = element.get("painted") if element.get("shown") else None
                found = frame["objects"].get(name) or []
                hit = [d.get("score") or 0 for d in found if truth and iou(d["box"], truth) >= 0.5]
                other = max([other] + [d.get("score") or 0 for d in found if not (truth and iou(d["box"], truth) >= 0.5)])
                if hit:
                    matches.append(max(hit))
            break
        seen[name] += (f"; match min {min(matches):.2f} ({len(matches)} frames)" if matches else "; no match") + \
            f", other max {other:.2f}"
    return list(seen.values())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--list", action="store_true", help="print the variant ids of --set as JSON")
    p.add_argument("--set", choices=("dev", "held-out"), default="dev")
    p.add_argument("--variant", help="clean, dev/<family>/vN or a held-out <family>/<id>")
    p.add_argument("--out", type=Path, default=REPO / "runs" / "web-bench")
    p.add_argument("--adapter", choices=web_adapters(), default="web",
                   help="the engine that replays the page (default web: Chromium through Playwright)")
    args = p.parse_args(argv)
    if args.list:
        print(json.dumps(set_ids(args.set)))
        return 0
    if not args.variant:
        p.error("--variant or --list")
    start = time.monotonic()
    doc = bench(args.variant, args.out, args.adapter)
    print(annotation(doc))
    if args.variant == CLEAN or args.variant.startswith(DEV_PREFIX):
        for line in detail_lines(doc, args.out):
            print(line)
    print(f"::notice title=Bench time {args.variant}::{round(time.monotonic() - start)} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
