"""One verifier for every domain: replay a candidate through an engine adapter, judge, decide.

This is the checkout page's verifier (it was ``agents.web_fix.verify``) with the engine and the domain
handed in instead of imported. The adapter (``harness/adapters.py``) replays each route. The domain
supplies the rest:

- ``specs``: its approved test specs;
- ``observe(trace, spec, replay_sha256)``: its engine observations, the engine's own record of where
  each object a spec names is, as ``expectrail.observations/v0`` the unchanged evaluator reads (for
  the page, ``harness.web.layout.layout_observations``);
- ``behaviour(trace)``: its behaviour check on the trace, ``{"result", "reason"}`` (for the page, the
  order goes through), recorded under ``behaviour_spec``;
- ``routes``: its public routes, and ``held_out``: the folder of its private routes
  (``<private set>/<domain>/routes``), or None when the private set is not mounted;
- optionally ``vision``: a second judge of the frames (SAM 3.1 on the page). When it is given, each
  spec is decided on its verdict instead of the engine observations'.

The checks, the decision rule (``expectrail.evaluator.decide``) and the document
(``expectrail.verification/v0``) are the game's:

- ``regression``: every spec on every public route, with the behaviour check (kind ``gameplay``) on each;
- ``clean``: every spec on the first public route of the clean project, so a broken checker cannot accept;
- ``held-out``: every spec and the behaviour check on each private route, named only by the aggregate
  route ``held-out-routes``; needs-review when no private route is mounted.

``verify`` returns the decision and the document, and writes ``verification.json`` (and
``held-out-note.txt`` when the private routes were missing). The Godot verifier, ``agents/verifier.py``,
is not on this module yet; docs/harness.md (Adapters) says what moving it takes.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from expectrail import __version__ as eval_version
from expectrail.contracts import digest, validate
from expectrail.evaluator import decide, evaluate
from harness import adapters
from harness.adapters import Adapter, sha256_file
from harness.run import REPO

HELD_OUT_ROUTE = "held-out-routes"
ERRORS_FILE = "bench-errors.json"
ZERO = "0" * 64

Observe = Callable[[dict, dict, str], dict]
Behaviour = Callable[[dict], dict]


@dataclass(frozen=True)
class Vision:
    """A judge of the frames beside the engine observations (SAM 3.1 for the checkout page)."""

    label: str
    """Names its verdict files, ``verdict-<label>-<spec id>.json``, which decide each spec when it is on."""
    judge: Callable[[dict, str, Path, list[dict]], tuple[dict[str, str], list[str]]]
    """``judge(trace, replay_sha256, run_dir, specs) -> (results by check name, errors)``; writes its files."""
    names: Callable[[list[dict]], list[str]]
    """The check names ``judge`` reports, so a replay that failed can mark each needs-review."""


def worst(results: list[str]) -> str:
    return "fail" if "fail" in results else "needs-review" if "needs-review" in results else "pass"


def judge_route(adapter: str | Adapter, route: Path, patches: list[Path], run_dir: Path, specs: list[dict],
                observe: Observe, behaviour: Behaviour, *, label: str = "engine",
                vision: Vision | None = None) -> dict[str, str]:
    """Replay one route and judge it: ``{check name: result}``, and the verdicts on disk.

    Writes ``verdict-<label>-<spec>.json`` for each spec on the engine observations, plus whatever
    ``vision`` writes. Returns the worst engine result under ``label``, the behaviour check under
    ``behaviour`` and vision's results. A replay that fails (SystemExit, a failed subprocess, an
    unreadable trace) is needs-review for every check, never pass, and leaves ``bench-error.txt``
    naming the original error.
    """
    adapter = adapters.resolve(adapter)
    names = [label, "behaviour"] + (vision.names(specs) if vision is not None else [])
    try:
        adapter.run(route, run_dir, patches)
        trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
        replay_sha = sha256_file(run_dir / "replay.json")
    except (SystemExit, subprocess.CalledProcessError, OSError, ValueError) as exc:
        cause = exc.__cause__ if isinstance(exc, SystemExit) and isinstance(exc.__cause__, Exception) else exc
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "bench-error.txt").write_text(f"{type(cause).__name__}: {cause}\n", encoding="utf-8")
        return {n: "needs-review" for n in names}
    verdicts = {spec["id"]: evaluate(spec, observe(trace, spec, replay_sha)) for spec in specs}
    results = {label: worst([v["result"] for v in verdicts.values()]), "behaviour": behaviour(trace)["result"]}
    errors: list[str] = []
    if vision is not None:
        seen, problems = vision.judge(trace, replay_sha, run_dir, specs)
        results.update(seen)
        errors += problems
    for spec_id, verdict in verdicts.items():
        (run_dir / f"verdict-{label}-{spec_id}.json").write_text(json.dumps(verdict, indent=1) + "\n", encoding="utf-8")
    if errors:
        (run_dir / ERRORS_FILE).write_text(json.dumps(errors, indent=2) + "\n", encoding="utf-8")
    return results


def held_out_routes(directory: Path | None) -> tuple[list[Path] | None, str | None]:
    """The private routes in ``directory`` (``<private set>/<domain>/routes``), or None and why."""
    if directory is None:
        return None, "the private held-out set is not mounted"
    routes = sorted(Path(directory).glob("*.json"))
    return (routes, None) if routes else (None, f"the private set has no {Path(directory).parent.name} routes")


def spec_checks(kind: str, route_name: str, run_dir: Path, specs: list[dict], decider: str) -> list[dict]:
    """One check per spec, from the ``verdict-<decider>-<spec>.json`` files judge_route wrote."""
    checks = []
    for spec in specs:
        path = run_dir / f"verdict-{decider}-{spec['id']}.json"
        if path.is_file():
            verdict = json.loads(path.read_text(encoding="utf-8"))
            checks.append({"spec": spec["id"], "kind": kind, "route": route_name, "result": verdict["result"],
                           "verdictSha256": digest(verdict)})
        else:
            checks.append({"spec": spec["id"], "kind": kind, "route": route_name, "result": "needs-review",
                           "verdictSha256": ZERO})
    return checks


def behaviour_check(behaviour: Behaviour, spec_id: str, kind: str, route_name: str, run_dir: Path) -> dict:
    path = run_dir / "trace.json"
    result = behaviour(json.loads(path.read_text(encoding="utf-8")))["result"] if path.is_file() else "needs-review"
    return {"spec": spec_id, "kind": kind, "route": route_name, "result": result}


def verify(adapter: str | Adapter, request: dict, candidate: Path, out: Path, *, specs: list[dict],
           observe: Observe, behaviour: Behaviour, behaviour_spec: str, routes: list[Path],
           held_out: Path | None, label: str = "engine", vision: Vision | None = None,
           attempt: int = 1) -> tuple[str, dict]:
    """Verify ``candidate`` (a patch on the request's base) for one domain; ``(decision, verification)``."""
    adapter = adapters.resolve(adapter)
    out.mkdir(parents=True, exist_ok=True)
    base = request["base"].get("patch")
    patches = ([REPO / base] if base else []) + ([candidate] if candidate.read_text(encoding="utf-8").strip() else [])
    decider = vision.label if vision is not None else label

    def judged(route: Path, route_patches: list[Path], run_dir: Path) -> None:
        judge_route(adapter, route, route_patches, run_dir, specs, observe, behaviour, label=label, vision=vision)

    checks: list[dict] = []
    for route in routes:
        run_dir = out / "candidate" / route.stem
        judged(route, patches, run_dir)
        checks += spec_checks("regression", route.stem, run_dir, specs, decider)
        checks.append(behaviour_check(behaviour, behaviour_spec, "gameplay", route.stem, run_dir))
    clean_route = routes[0]
    clean_dir = out / "clean" / clean_route.stem
    judged(clean_route, [], clean_dir)
    checks += spec_checks("clean", clean_route.stem, clean_dir, specs, decider)
    held, problem = held_out_routes(held_out)
    if held is None:
        checks.append({"spec": "held-out-unavailable", "kind": "held-out", "route": HELD_OUT_ROUTE,
                       "result": "needs-review", "verdictSha256": ZERO})
    else:
        # Private routes: judged like the public ones; only the aggregate route name leaves here.
        for n, route in enumerate(held):
            run_dir = out / "held-out" / f"r{n}"
            judged(route, patches, run_dir)
            checks += spec_checks("held-out", HELD_OUT_ROUTE, run_dir, specs, decider)
            checks.append(behaviour_check(behaviour, behaviour_spec, "held-out", HELD_OUT_ROUTE, run_dir))
    decision, reasons = decide(checks)
    doc = {"format": "expectrail.verification/v0",
           "candidate": {"patchSha256": sha256_file(candidate), "baseTree": request["base"]["tree"],
                         "attempt": attempt, "request": request["id"], "requestSha256": digest(request)},
           "evaluator": {"name": "expectrail.evaluator", "version": eval_version},
           "checks": checks, "decision": decision, "reasons": reasons}
    validate(doc, "verification")
    (out / "verification.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    if problem:
        (out / "held-out-note.txt").write_text(problem + "\n", encoding="utf-8")
    return decision, doc
