"""From a game with no config to a verdict, as a new developer would get there (#260, Done-when).

    python -m tools.setup_rehearsal --project crate-run --out runs/setup-rehearsal
    python -m tools.setup_rehearsal --project bundled --out runs/setup-rehearsal --json

On a disposable copy of the project, with its config removed, it runs the installed command's steps:

1. ``init --dry-run``: a proposal is printed and no file in the game changes;
2. ``init``: a draft config (or, when init cannot choose the player's image, a review draft) and a
   first route are written;
3. ``verify --project`` on what init wrote: it cannot judge yet, and says what to change (exit 5);
4. the person's step, which this rehearsal takes on the copy and says so: the player's image where
   init could not choose one, ``draft`` removed, and an existing approved check named in
   ``approvedContracts``, copied unchanged with its approval. Nothing is approved here;
5. ``verify --project`` with the game unchanged: the engine's check passes; with no vision settings
   that is needs-review, never accept (exit 2);
6. ``verify --project`` with a seeded bug that makes the player fall through the floor: reject (exit 1).

Each step is recorded with its command, exit code, seconds and the lines a developer reads. The
rehearsal fails when a step ends differently from what is written above. No model is called: the
vision settings are removed from the environment of every command it runs. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FORMAT = "expectrail.setup-rehearsal/v0"
APPROVED = REPO / "agents" / "specs" / "player-stays-above-ground.json"
CONFIG = "expectrail.project.json"
PENDING = "expectrail.project.draft.json"
CHECK = "checks/player-stays-above-ground.json"
SKIP = (".godot", ".git")


def _bundled_bug(game: Path) -> str:
    patch = REPO / "bugs" / "physics-fall-through" / "v1.patch"
    done = subprocess.run(["patch", "-s", "-p1", "-d", str(game), "-i", str(patch)], capture_output=True, text=True)
    if done.returncode:
        raise RehearsalError(f"the seeded bug did not apply: {done.stdout}{done.stderr}")
    return "bugs/physics-fall-through/v1.patch: the player's collision mask drops the ground layer"


def _crate_bug(game: Path) -> str:
    script = game / "player.gd"
    solid, broken = "\tmove_and_slide()\n", "\tposition += velocity * delta\n"
    text = script.read_text(encoding="utf-8")
    if text.count(solid) != 1:
        raise RehearsalError("player.gd no longer has the one line this rehearsal breaks")
    script.write_text(text.replace(solid, broken), encoding="utf-8")
    return "player.gd moves the crate without collision, so it falls through the floor"


# For each project: where its game is, the image a person would choose when init cannot (None when
# init chooses one), and the seeded bug.
PROJECTS = {
    "bundled": {"source": REPO / "game" / "platformer", "image": None, "bug": _bundled_bug},
    "crate-run": {"source": REPO / "tests" / "projects" / "crate-run" / "project",
                  # The image the shipped Crate Run config names; the crate is drawn as a polygon.
                  "image": "res://crate.svg", "bug": _crate_bug},
}


class RehearsalError(Exception):
    """A step ended differently from what the rehearsal expects."""


def _digest(folder: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        h.update(path.relative_to(folder).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def _environment() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("MODEL_API_KEY", "EXPECTRAIL_SAM_USD_CAP")}
    env["PYTHONPATH"] = os.pathsep.join([str(REPO), *filter(None, [os.environ.get("PYTHONPATH")])])
    return env


def _run(args: list[str], cwd: Path, timeout: int) -> tuple[int, str, float]:
    start = time.monotonic()
    done = subprocess.run([sys.executable, "-m", "expectrail.cli", *args], cwd=cwd, env=_environment(),
                          capture_output=True, text=True, timeout=timeout)
    return done.returncode, (done.stdout + done.stderr), round(time.monotonic() - start, 1)


def _said(text: str, keep: int = 12) -> list[str]:
    """The lines a developer reads, without progress lines and with no local path."""
    lines = [line.rstrip() for line in text.splitlines()
             if line.strip() and (not line.startswith("job ") or "completed," in line)]
    return [line for line in lines if "file://" not in line][:keep]


def rehearse(name: str, out: Path, *, timeout: int = 1800) -> dict:
    project = PROJECTS[name]
    work = out / name
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    game = work / "game"
    shutil.copytree(project["source"], game, ignore=shutil.ignore_patterns(*SKIP))
    (game / CONFIG).unlink(missing_ok=True)
    (game / PENDING).unlink(missing_ok=True)
    jobs = work / "jobs"
    steps: list[dict] = []

    def step(title, args, expected, *, folder=game, check=None):
        code, text, seconds = _run(args, work, timeout)
        row = {"step": title, "command": "expectrail " + " ".join(a if not a.startswith(str(work)) else
                                                                      Path(a).relative_to(work).as_posix()
                                                                      for a in args),
               "exit": code, "expectedExit": expected, "seconds": seconds, "said": _said(text)}
        problem = None if code == expected else f"exit {code}, expected {expected}"
        if problem is None and check is not None:
            problem = check(text)
        row["ok"] = problem is None
        if problem:
            row["problem"] = problem
        steps.append(row)
        return row, text

    before = _digest(game)
    row, text = step("init --dry-run", ["init", "--project", str(game), "--adapter", "godot", "--dry-run"], 0,
         check=lambda _t: None if _digest(game) == before else "the dry run changed the game")
    if row["ok"]:
        row["said"] = [f"printed a proposal ({len(text.splitlines())} lines); no file in the game changed"]
    step("init", ["init", "--project", str(game), "--adapter", "godot"], 0,
         check=lambda _t: None if (game / CONFIG).is_file() or (game / PENDING).is_file()
         else "init wrote neither a config nor a review draft")
    wrote = CONFIG if (game / CONFIG).is_file() else PENDING
    step("verify what init wrote", ["verify", "--project", str(game), "--jobs-root", str(jobs)], 5,
         check=lambda t: None if ("A person approves a check" in t or "unresolvedBindings" in t)
         else "the refusal does not say what to change")

    # The person's step, taken on the copy. The check keeps the approval it already has.
    doc = json.loads((game / wrote).read_text(encoding="utf-8"))
    config = doc["config"] if wrote == PENDING else doc
    person = []
    if "texture" not in config.get("bindings", {}).get("player", {}):
        if project["image"] is None:
            raise RehearsalError("init chose no player image and this project names none to choose")
        config["bindings"]["player"]["texture"] = project["image"]
        person.append(f"chose {project['image']} as the player's image")
    config.pop("draft", None)
    person.append('removed "draft" after reading the bindings')
    (game / "checks").mkdir(exist_ok=True)
    shutil.copyfile(APPROVED, game / CHECK)
    config["approvedContracts"] = [CHECK]
    person.append(f"named {CHECK} in approvedContracts, copied unchanged from agents/specs with its existing approval")
    (game / CONFIG).write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    (game / PENDING).unlink(missing_ok=True)
    steps.append({"step": "the person's step (taken by this rehearsal on the copy)", "did": person, "ok": True})

    head = work / "head"
    shutil.copytree(game, head)
    step("verify, game unchanged", ["verify", "--project", str(head), "--base", str(game), "--jobs-root", str(jobs)], 2,
         check=lambda t: None if "needs-review" in t and "nothing here is accepted" in t
         else "an unchanged game without vision is not the expected needs-review")
    shutil.rmtree(head)
    shutil.copytree(game, head)
    bug = project["bug"](head)
    row, _ = step("verify, seeded bug", ["verify", "--project", str(head), "--base", str(game), "--jobs-root", str(jobs)],
                  1, check=lambda t: None if "reject" in t else "the seeded bug was not rejected")
    row["bug"] = bug
    route = json.loads((game / config["routes"][0]).read_text(encoding="utf-8"))
    return {"format": FORMAT, "project": name, "initWrote": wrote, "route": {"ticks": route["ticks"],
            "events": len(route["events"])}, "steps": steps, "ok": all(s["ok"] for s in steps)}


def markdown(result: dict) -> str:
    lines = [f"## {result['project']}", "",
             f"init wrote `{result['initWrote']}` and a route of {result['route']['ticks']} ticks with "
             f"{result['route']['events']} input events.", "",
             "| Step | Command | Exit (expected) | Seconds | What it said |", "| --- | --- | --- | --- | --- |"]
    for s in result["steps"]:
        if "did" in s:
            lines.append(f"| {s['step']} | | | | {'; '.join(s['did'])} |")
            continue
        said = "<br>".join(line.strip().replace("|", "\\|") for line in s["said"][:4])
        mark = "" if s["ok"] else f" **{s['problem']}**"
        lines.append(f"| {s['step']} | `{s['command']}` | {s['exit']} ({s['expectedExit']}){mark} | {s['seconds']} | {said} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.setup_rehearsal", description=__doc__.split("\n")[0])
    parser.add_argument("--project", choices=sorted(PROJECTS), action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    results = []
    for name in args.project:
        try:
            results.append(rehearse(name, out))
        except (RehearsalError, subprocess.TimeoutExpired, OSError, ValueError, KeyError) as exc:
            results.append({"format": FORMAT, "project": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    (out / "setup-rehearsal.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for result in results:
            print(markdown(result) if "steps" in result else f"## {result['project']}\n\n{result['error']}\n")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
