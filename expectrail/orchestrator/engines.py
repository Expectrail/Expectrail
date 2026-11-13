"""What runs a job's verification, per adapter. An engine verifies; none of them starts a fixer or
reads saved data in place of a run.

The engines are picked through the adapter registry (``harness.adapters``): ``ENGINES`` has one for
every registered adapter that has a verify path (``verify_run``), and no other. A request that names
an adapter the registry does not hold, or one with no verify path, completes as needs-review with
``INPUT_INVALID`` and nothing runs.

An engine has two parts:

- ``preflight(request)`` returns the diagnostics that stop the job before anything runs (a missing
  tool, a project that is not there). The job then completes as needs-review, never as a pass.
- ``execute(request, paths, advance)`` runs the verification, writes its evidence into
  ``paths.staging`` and returns a Result. It may call ``advance(phase)`` as it moves on.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from collections.abc import Mapping
from pathlib import Path
from typing import Callable

from expectrail.observers import FramesObserver

from expectrail.orchestrator import request as req
from expectrail.orchestrator import store as st

_AUTO_VISUAL = object()


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
    observers: dict | None = None


class Gate:
    """The verification the CI gate runs (expectrail.gate.verify.run_gate), on one engine adapter:
    the head, and the base when there is one, replayed on the routes and judged by the approved
    specs from the base.

    Everything about the engine comes from the adapter's entry in the registry (harness.adapters):
    the replay, how a project folder is recognised, what a run needs on this machine. The entry is
    read when it is used, so the engine follows the registry.

    ``rule`` is which observers judge (expectrail.gate.record.RULES). With ``both`` every check
    needs the engine's record and ``visual`` (an expectrail.observers.FramesObserver) to pass, and
    with no ``visual`` the engine accepts nothing (#327). The registered engines use both observers.
    Engine-only is available only to code explicitly constructing a Gate for development."""

    def __init__(self, adapter: str = "godot", replay: Callable | None = None, *, rule: str = "both",
                 visual=_AUTO_VISUAL):
        self.name = adapter
        self._replay = replay   # a stand-in for the harness, for tests; None runs the adapter's
        self._rule = rule
        self._visual = (FramesObserver() if rule == "both" else None) if visual is _AUTO_VISUAL else visual

        self._needs_vision_settings = isinstance(self._visual, FramesObserver) and self._visual._client is None

    def _adapter(self):
        from harness import adapters

        return adapters.get(self.name)

    def preflight(self, request: dict) -> list[dict]:
        found: list[dict] = []
        try:
            adapter = self._adapter()
        except KeyError:
            adapter = None
        if adapter is None or not adapter.can_verify():
            # The registry changed after this engine was made. Nothing is run on a guess.
            return [st.diagnostic("INPUT_INVALID", stage="preparing", detail=why_not(self.name))]
        head = Path(request["head"]["checkout"])
        game = head / request["project"]["game"]
        if not adapter.is_project(game):
            found.append(st.diagnostic("INPUT_INVALID", stage="preparing",
                                       detail=f"no {adapter.label()} project at {request['project']['game']} "
                                              f"in the head checkout"))
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
        if not found and self._rule == "both" and self._needs_vision_settings:
            from expectrail import doctor

            for check in doctor.vision_checks():
                if doctor.missing([check]):
                    diagnostic = st.diagnostic("PROVIDER_FAILED", stage="preparing", detail=check.found)
                    diagnostic["fix"] = check.fix
                    found.append(diagnostic)
        if self._replay is None and not found:
            found += self._tools()
        return found

    def _tools(self) -> list[dict]:
        """What every run on this engine needs and this machine lacks, by the adapter's own account
        (``missing``). Each diagnostic names the fix."""
        return _tools(self.name)

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
            checks=checks, rule=self._rule, visual=self._visual, on_phase=advance, adapter=self.name,
            **({"replay": self._replay} if self._replay is not None else {}))
        # The grade stays `diagnostic` even when every replay was sandboxed: the ledger's `isolated`
        # also needs a separate trusted job that judges and signs (#254, #255). What the sandbox did
        # is in the evidence: findings.json, `isolation`.
        game = document.get("game") or {}
        return Result(document["decision"], list(document.get("reasons", [])),
                      trees={"headTree": game.get("headTree"), "baseTree": game.get("baseTree")},
                      policy=checks.digest, observers=document.get("observers"))


def _tools(adapter: str) -> list[dict]:
    from harness import adapters

    missing = adapters.get(adapter).missing
    return [st.diagnostic("TOOL_MISSING", stage="preparing", detail=line) for line in (missing() if missing else [])]


class GodotGate(Gate):
    """The gate's verification on the ``godot`` adapter."""

    name = "godot"

    def __init__(self, replay: Callable | None = None, *, rule: str = "both", visual=_AUTO_VISUAL):
        super().__init__("godot", replay, rule=rule, visual=visual)

    @staticmethod
    def _tools() -> list[dict]:
        """What every run needs and this machine lacks: the list `expectrail doctor` reports
        (expectrail.doctor.for_run), which the adapter asks by the same functions, so `doctor` and a
        run cannot disagree about a tool. Each diagnostic names the fix."""
        return _tools("godot")


def why_not(name: str) -> str:
    """Why no engine verifies with the adapter ``name``, in one sentence for a diagnostic."""
    from harness import adapters

    if name not in adapters.names():
        return f"no adapter named {name!r}"
    return (f"the adapter {name!r} has no verify path yet; those that have one: "
            f"{', '.join(adapters.verifying()) or 'none'}")


class Engines(Mapping):
    """The engines, picked through the adapter registry (harness.adapters): one for every adapter
    that has a verify path, and none for any other name. The registry is read at each lookup, so an
    adapter registered later has an engine and one that was removed has none."""

    def __init__(self):
        self._made: dict[str, Gate] = {}

    def _names(self) -> tuple[str, ...]:
        from harness import adapters

        return adapters.verifying()

    def __getitem__(self, name: str) -> Gate:
        if not isinstance(name, str) or name not in self._names():
            raise KeyError(name)
        if name not in self._made:
            self._made[name] = GodotGate() if name == GodotGate.name else Gate(name)
        return self._made[name]

    def __iter__(self):
        return iter(self._names())

    def __len__(self) -> int:
        return len(self._names())


ENGINES = Engines()
