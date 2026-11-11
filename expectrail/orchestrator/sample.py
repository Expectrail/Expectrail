"""A real verification of the bundled game, three ways, so a first run shows what the verdicts mean.

    python3 -m expectrail.orchestrator sample [--json]

It copies the bundled Godot game twice (as it is, and with the seeded bug
bugs/physics-fall-through/v1.patch applied) and runs three jobs through the orchestrator:

    the game as it is                     accept
    a change that breaks it               reject   (the bug, compared with the game as it is)
    the change that repairs it            accept   (the game as it is, compared with the bug)

These are real runs: Godot replays the smoke route each time, and no model key is used. They are a
sample, on a game and a bug that ship with Expectrail; they say nothing about any other project.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from expectrail.orchestrator import request as req
from expectrail.orchestrator import runner
from expectrail.orchestrator import store as st

ROOT = Path(__file__).resolve().parent.parent.parent
GAME = "game/platformer"
ROUTE = "harness/routes/smoke.json"
SPECS = "agents/specs"
BUG = "bugs/physics-fall-through/v1.patch"
# (name, what the head is, what the base is, the decision a working install gives)
CASES = (
    ("the game as it is", "clean", None, "accept"),
    ("a change that breaks it (the seeded fall-through bug)", "bug", "clean", "reject"),
    ("the change that repairs it", "clean", "bug", "accept"),
)


class SampleError(Exception):
    """The sample's own files could not be prepared."""


def checkout(target: Path, *, bug: bool, root: Path = ROOT) -> Path:
    """A folder holding the game, the smoke route and the approved specs, with the bug applied or not."""
    for needed in (GAME, ROUTE, SPECS, BUG):
        if not (root / needed).exists():
            raise SampleError(f"{needed} is not in this copy of Expectrail")
    shutil.copytree(root / GAME, target / GAME, ignore=shutil.ignore_patterns(".godot"))
    (target / ROUTE).parent.mkdir(parents=True)
    shutil.copy(root / ROUTE, target / ROUTE)
    shutil.copytree(root / SPECS, target / SPECS)
    if bug:
        try:
            done = subprocess.run(["patch", "-p1", "--forward", "--batch", "-d", str(target / GAME), "-i", str(root / BUG)],
                                  capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise SampleError("the patch program is not installed; the sample needs it to put its seeded bug "
                              "into a copy of the game") from exc
        if done.returncode != 0:
            raise SampleError(f"the seeded bug did not apply: {done.stdout.strip() or done.stderr.strip()}")
    return target


def run(store: st.JobStore, *, timeout_seconds: int = 600, engines: dict | None = None, on_case=None,
        root: Path = ROOT) -> list[dict]:
    """Run the three cases one after another and return, for each, its name, the expected decision and
    the job's final status. With ``engines`` the jobs run in this process (tests); without, each runs
    in a worker of its own, as `verify` does."""
    results = []
    with tempfile.TemporaryDirectory(prefix="expectrail-sample-") as tmp:
        trees = {"clean": checkout(Path(tmp) / "clean", bug=False, root=root),
                 "bug": checkout(Path(tmp) / "bug", bug=True, root=root)}
        for name, head, base, expected in CASES:
            request = req.build(adapter="godot", head=trees[head], base=trees[base] if base else None, game=GAME,
                                routes=[ROUTE], specs=SPECS, timeout_seconds=timeout_seconds)
            status, _ = store.create(request)
            if engines is not None:
                status = runner.work(store, status["id"], engines=engines)
            else:
                status = runner.wait(store, status["id"], runner.spawn(store, status["id"]))
            result = {"case": name, "expected": expected, "status": status,
                      "asExpected": status["phase"] == "completed" and status["decision"] == expected}
            results.append(result)
            if on_case is not None:
                on_case(result)
    return results


def line(result: dict) -> str:
    status = result["status"]
    got = status["decision"] or status["phase"]
    mark = "as expected" if result["asExpected"] else f"NOT as expected (a working install gives {result['expected']})"
    text = f"{result['case']}: {got}, {mark}"
    for d in status["diagnostics"]:
        text += f"\n    {d['code']}: {d['detail']} Fix: {d['fix']}"
    return text
