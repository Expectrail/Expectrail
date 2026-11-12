"""What runs a job's verification, per adapter. An engine verifies; none of them starts a fixer or
reads saved data in place of a run.

An engine has two parts:

- ``preflight(request)`` returns the diagnostics that stop the job before anything runs (a missing
  tool, a project that is not there). The job then completes as needs-review, never as a pass.
- ``execute(request, paths, advance)`` runs the verification, writes its evidence into
  ``paths.staging`` and returns a Result. It may call ``advance(phase)`` as it moves on.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from expectrail.orchestrator import request as req
from expectrail.orchestrator import store as st


@dataclass(frozen=True)
class Result:
    decision: str
    reasons: list[str] = field(default_factory=list)
    evidence_grade: str = "diagnostic"
    # The game trees the evidence names ({"headTree": ..., "baseTree": ...}), when the engine knows
    # them. The worker holds them against the job's recorded inputs: a decision about another tree
    # than the one asked about is not this job's decision.
    trees: dict | None = None
    # The digest of the checks the verdict was judged with, when the engine knows it. Held against
    # the job's policyDigest the same way.
    policy: str | None = None


class GodotGate:
    """The Godot verification the CI gate runs (expectrail.gate.verify.run_gate): the head, and the
    base when there is one, replayed on the routes and judged by the approved specs from the base."""

    name = "godot"

    def __init__(self, replay: Callable | None = None):
        self._replay = replay   # a stand-in for the harness, for tests; None runs Godot

    def preflight(self, request: dict) -> list[dict]:
        found: list[dict] = []
        head = Path(request["head"]["checkout"])
        game = head / request["project"]["game"]
        if not (game.is_dir() and (game / "project.godot").is_file()):
            found.append(st.diagnostic("INPUT_INVALID", stage="preparing",
                                       detail=f"no Godot project at {request['project']['game']} in the head checkout"))
        base = request["base"]
        if base is not None and not Path(base["checkout"]).is_dir():
            found.append(st.diagnostic("INPUT_INVALID", stage="preparing", detail="the base checkout is not a folder"))
        if request["executionClass"] == "isolated":
            from harness import sandbox as box

            tool, why = box.probe(True)
            if tool is None:
                found.append(st.diagnostic("TOOL_MISSING", stage="preparing",
                                           detail=f"the isolated execution class needs the replay sandbox and this "
                                                  f"machine cannot provide it ({why}); nothing was run unsandboxed "
                                                  f"in its place"))
        if self._replay is None and not found:
            found += self._tools()
        return found

    @staticmethod
    def _tools() -> list[dict]:
        """What every run needs and this machine lacks: the list `expectrail doctor` reports
        (expectrail.doctor.for_run), checked by the same functions, so `doctor` and a run cannot
        disagree about a tool. Each diagnostic names the fix."""
        from expectrail import doctor

        return [st.diagnostic("TOOL_MISSING", stage="preparing", detail=f"{c.found}. Fix: {c.fix}")
                for c in doctor.missing(doctor.for_run())]

    def execute(self, request: dict, paths: st.JobPaths, advance: Callable[[str], object]) -> Result:
        from expectrail.gate import verify as gate

        project = request["project"]
        base = request["base"]
        # The checks are read here, once, by the gate's own reader, and must be the ones the job
        # names. The gate is then given what was read: it opens no spec or route file itself, so
        # there is no second reading and no other source to fall back to.
        checks = req.read_checks(request)
        named = json.loads(paths.status.read_text(encoding="utf-8"))["inputs"]["policyDigest"]
        if checks.digest != named:
            raise gate.ConfigError("the checks changed after the job was created; ask again")
        document = gate.run_gate(
            repo=Path(request["head"]["checkout"]), game=project["game"], routes=project["routes"],
            specs=project["specs"], out=paths.staging, work=paths.work / "gate",
            base=Path(base["checkout"]) if base else None,
            # The isolated class: every replay in the sandbox, or the gate refuses and nothing is accepted.
            require_sandbox=request["executionClass"] == "isolated",
            checks=checks,
            **({"replay": self._replay} if self._replay is not None else {}))
        # The grade stays `diagnostic` even when every replay was sandboxed: the ledger's `isolated`
        # also needs a separate trusted job that judges and signs (#254, #255). What the sandbox did
        # is in the evidence: findings.json, `isolation`.
        game = document.get("game") or {}
        return Result(document["decision"], list(document.get("reasons", [])),
                      trees={"headTree": game.get("headTree"), "baseTree": game.get("baseTree")},
                      policy=checks.digest)


ENGINES = {GodotGate.name: GodotGate()}
