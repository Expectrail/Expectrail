"""Measure the mirror-inputs metamorphic checks (#675, piece 3, slice 3) on a game the team did not write.

The project comes from the outside list (``tests/outside/projects.json``) and is fetched at its pinned commit
(``tools/outside_trial.fetch``), or read from a clone that already holds it (``--source``). Nothing of it is
copied into this repository. The default project is ``kinematic-character``: a keyboard platformer that moves
with ``move_left``/``move_right``/``jump``, the actions the mirror pairs use.

What is measured, with no model and nothing judged by hand:

- **The checks.** The project's own input map (``project.godot``) is the action catalog. Every probe in the
  generator's library that uses a left/right pair gets its mirrored twin and one check per signal
  (``expectrail/jit/metamorphic.py``). Twin pairs that are the same two routes are measured once.
- **The builds.** Each route is replayed
  - on the project as pinned, three times: a check must pass all three to be usable;
  - on the player's do-nothing control, three times, made by ``expectrail/jit/do_nothing.py`` from the
    project's ``Player`` scene (the harness's default player name): a check that passes all three is dropped;
  - once on each change the outside list declares for the project. A change expected to be rejected is a
    **defect** (a kept check failing on it is a catch). Any other change leaves the player's motion as it
    was (a tint, a hidden sprite), so a kept check failing on it is a **false reject**;
  - once on a seeded direction-dependent fault, made here at run time and never committed against the
    project: an autoload that pushes the player 1 px back to the right on each tick ``move_left`` is held
    (``drag-left``, the outside counterpart of the bundled ``slow-left``).
- Every replay runs in the replay sandbox (``--sandbox require`` by default), as the outside trial requires.

Judged with the generator's own evaluation, as ``tools/metamorphic_public.py`` judges the bundled game.

    python -m tools.metamorphic_outside --fetch --out runs/metamorphic-outside        # in CI
    python -m tools.metamorphic_outside --source CLONE --out NEW_FOLDER               # a clone already made

Writes ``rows.json`` and ``metamorphic-outside.md`` in ``--out``. Exit 0 when the measurement was made,
whatever it says; 3 when no route completed on the project as pinned; 5 when the project cannot be read.

Advisory: this changes no record and no rule.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "tools") not in sys.path:
    sys.path.insert(0, str(REPO / "tools"))

import metamorphic_public as public  # noqa: E402

from expectrail.jit import assess, do_nothing  # noqa: E402
from tools import outside_trial  # noqa: E402

PROJECT = "kinematic-character"
PLAYER = "Player"   # the harness's default player node name (harness/godot/expectrail_harness.gd)
SEED = "drag-left"
SEED_FILE = "expectrail_seed_drag_left.gd"
SEED_NAME = "ExpectrailSeedDragLeft"
SEED_PX = 1.0


class OutsideError(ValueError):
    """The project cannot be measured; the message says why."""


def seed_script(action: str = "move_left", node: str = PLAYER, px: float = SEED_PX) -> str:
    return (
        "extends Node\n"
        f"# Seeded by Expectrail (#675) for a measurement only: while {action} is held, the player is pushed\n"
        f"# {px:g} px back to the right on each physics tick, so walking left covers less ground than walking right.\n"
        "\n"
        "func _physics_process(_delta):\n"
        f"\tif not Input.is_action_pressed(\"{action}\"):\n"
        "\t\treturn\n"
        "\tvar scene = get_tree().current_scene\n"
        "\tif scene == null:\n"
        "\t\treturn\n"
        f"\tvar player = scene if scene.name == \"{node}\" else scene.find_child(\"{node}\", true, false)\n"
        "\tif player is Node2D:\n"
        f"\t\tplayer.position.x += {px:.1f}\n"
    )


def _unified(rel: str, before: str | None, after: str) -> str:
    """A unified diff from ``before`` (None: a new file) to ``after``, with the no-newline marker when needed."""
    old = [] if before is None else before.splitlines(keepends=True)
    new = after.splitlines(keepends=True)
    out = []
    for line in difflib.unified_diff(old, new, "/dev/null" if before is None else f"a/{rel}", f"b/{rel}"):
        out.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(out)


def seed_patch(game: Path) -> str:
    """The ``drag-left`` fault as a unified diff against ``game``: a new autoload script and its entry."""
    game = Path(game)
    if (game / SEED_FILE).exists():
        raise OutsideError(f"{SEED_FILE} already exists in the project")
    project = (game / "project.godot").read_text(encoding="utf-8")
    entry = f'{SEED_NAME}="*res://{SEED_FILE}"\n'
    if "\n[autoload]\n" in "\n" + project:
        at = ("\n" + project).index("\n[autoload]\n") + len("[autoload]\n")
        changed = project[:at] + "\n" + entry + project[at:]
    else:
        changed = project + ("" if project.endswith("\n") else "\n") + "\n[autoload]\n\n" + entry
    return _unified(SEED_FILE, None, seed_script()) + _unified("project.godot", project, changed)


def catalog(game: Path) -> list[str]:
    """The project's own input actions; ``OutsideError`` when it declares none (no fallback is guessed)."""
    from expectrail.route import authored_input_map

    actions, _rate, fallback = authored_input_map((Path(game) / "project.godot").read_text(encoding="utf-8"))
    if fallback:
        raise OutsideError("project.godot declares no input action, so there is no left/right pair to mirror")
    return actions


def builds(game: Path, project: dict, work: Path) -> tuple[list[dict], list[dict]]:
    """(plan, notes). The plan: clean, the do-nothing control when one can be made, each declared change and
    the seeded fault. A note says why something planned could not be made."""
    plan = [{"id": "clean", "kind": "clean", "patches": [], "reps": assess.REPS, "mode": None}]
    notes = []
    profile = {"selectors": {"player": PLAYER}}
    control = do_nothing.controls(game, profile, ["player"])[0]
    if control["patchText"]:
        path = work / "do-nothing-player.patch"
        path.write_text(control["patchText"], encoding="utf-8")
        plan.append({"id": "do-nothing", "kind": "control", "patches": [path], "reps": assess.REPS,
                     "mode": control["mode"], "patchSha256": _sha(control["patchText"])})
    else:
        notes.append({"build": "do-nothing", "reason": f"cannot tell: {control['reason']}"})
    for change in project.get("changes", []):
        patch = outside_trial.contained(REPO, change["patch"])
        kind = "defect" if change.get("expect") == "reject" else "harmless"
        plan.append({"id": change["name"], "kind": kind, "what": change.get("what", ""), "patches": [patch],
                     "reps": 1, "mode": None, "patchSha256": _sha(patch.read_text(encoding="utf-8"))})
    try:
        text = seed_patch(game)
    except (OutsideError, OSError, UnicodeDecodeError) as exc:
        notes.append({"build": SEED, "reason": f"not made: {exc}"})
    else:
        path = work / f"{SEED}.patch"
        path.write_text(text, encoding="utf-8")
        plan.append({"id": SEED, "kind": "defect", "what": f"seeded here: while move_left is held, the player is "
                     f"pushed {SEED_PX:g} px back to the right each tick", "patches": [path], "reps": 1,
                     "mode": None, "patchSha256": _sha(text)})
    return plan, notes


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def measure(game: Path, project: dict, work: Path, runner=None, workers: int = 3, sandbox: str = "require") -> dict:
    work = Path(work)
    work.mkdir(parents=True, exist_ok=False)
    actions = catalog(game)
    pairs, routes, skipped = public.checks({"actions": actions})
    if not pairs:
        raise OutsideError("no probe in the library has a mirror with this project's actions")
    plan, notes = builds(game, project, work)
    replays = public.replay_all(work, game, routes, plan, runner=runner, workers=workers, sandbox=sandbox)
    rows = public.judge(pairs, plan, replays["episodes"])
    for row in rows:
        row["falseRejects"] = sorted(b["id"] for b in plan if b["kind"] == "harmless"
                                     and "fail" in row["runs"].get(b["id"], []))
    doc = {"project": {k: project.get(k) for k in ("name", "repository", "commit", "path", "licence")},
           "actions": actions, "sandbox": sandbox,
           "pairs": [{k: p[k] for k in ("left", "right")} for p in pairs], "skipped": skipped, "notes": notes,
           "builds": [{k: b.get(k) for k in ("id", "kind", "what", "reps", "mode", "patchSha256")} |
                      {"patches": [_shown(p) for p in b["patches"]]} for b in plan],
           "evidence": replays["evidence"], "rows": rows}
    (work / "rows.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return doc


def _shown(path) -> str:
    path = Path(path)
    return str(path.relative_to(REPO)) if path.is_relative_to(REPO) else path.name


def summary(doc: dict) -> dict:
    rows, builds_ = doc["rows"], doc["builds"]
    kept = [r for r in rows if r["kept"]]
    of = lambda kind: [b["id"] for b in builds_ if b["kind"] == kind]  # noqa: E731
    failing = {b: sorted(r["check"] for r in kept if r["runs"].get(b) == ["fail"]) for b in of("defect") + of("harmless")}
    return {"pairs": len(doc["pairs"]), "checks": len(rows),
            "cleanOutcomes": public._count(",".join(sorted(set(r["runs"].get("clean", [])))) or "not-run" for r in rows),
            "cleanPass": sum(r["usable"] for r in rows),
            "controlOutcomes": public._count(r["control"] for r in rows if r["usable"]),
            "kept": len(kept),
            "catches": {b: failing[b] for b in of("defect")},
            "falseRejects": {b: failing[b] for b in of("harmless")},
            "replaysCompleted": sum(len(e.get("traces", [])) for e in doc["evidence"].values()),
            "replayErrors": sum(1 for e in doc["evidence"].values() if e.get("error"))}


def markdown(doc: dict) -> str:
    s = summary(doc)
    p = doc["project"]
    engines = sorted({str(e["engine"]) for e in doc["evidence"].values() if e.get("engine")})
    changes = [b for b in doc["builds"] if b["kind"] in ("defect", "harmless")]
    lines = [f"# Mirror-inputs metamorphic checks on {p['name']} (#675, piece 3, slice 3)", "",
             f"Project: `{p['repository']}`, `{p['path']}`, commit `{p['commit']}`, {p['licence']}. "
             f"Actions from its `project.godot`: {', '.join(f'`{a}`' for a in doc['actions'])}. "
             f"Sandbox: `{doc['sandbox']}`. Engine: {', '.join(engines) or 'no completed replay'}. "
             "No model was called. Advisory: no record or counting rule changed.", "",
             "## Counts", "",
             f"- Pairs: {s['pairs']}. Checks: {s['checks']}. Replays completed: {s['replaysCompleted']}; "
             f"routes with a failed replay or differing runs: {s['replayErrors']}.",
             f"- As pinned, outcomes over the three runs: {public._fmt(s['cleanOutcomes'])}. "
             f"**{s['cleanPass']} pass 3 of 3** and are usable.",
             f"- Of those, on the do-nothing control: {public._fmt(s['controlOutcomes']) or 'none'}. "
             f"**{s['kept']} are kept.**"]
    for b in changes:
        got = (s["catches"] if b["kind"] == "defect" else s["falseRejects"])[b["id"]]
        word = "catch it" if b["kind"] == "defect" else "fail it (false rejects)"
        lines.append(f"- `{b['id']}` ({b['kind']}: {b['what']}): **{len(got)} kept checks {word}**"
                     f"{': ' + ', '.join(f'`{c}`' for c in got) if got else ''}.")
    lines += [f"- Not made: `{n['build']}`, {n['reason']}." for n in doc["notes"]]
    lines += ["", "## Per check", "",
              "| Check | Pair | As pinned (3) | Do-nothing (3) | Kept | " + " | ".join(f"{b['id']} (1)" for b in changes) + " |",
              "| --- | --- | --- | --- | --- | " + " | ".join("---" for _ in changes) + " |"]
    for r in doc["rows"]:
        cells = [", ".join(r["runs"].get(b["id"], [])) or "-" for b in changes]
        lines.append(f"| `{r['check']}` | {r['left']} / {r['right']} | {', '.join(r['runs'].get('clean', [])) or '-'} | "
                     f"{', '.join(r['runs'].get('do-nothing', [])) or '-'} | {'yes' if r['kept'] else 'no'} | "
                     + " | ".join(cells) + " |")
    errors = {k: e["error"] for k, e in doc["evidence"].items() if e.get("error")}
    if errors:
        lines += ["", "## Replay errors", ""] + [f"- `{k}`: {v}" for k, v in sorted(errors.items())]
    lines += ["", "## Probes with no mirror", ""] + [f"- `{k['probe']}`: {k['reason']}" for k in doc["skipped"]]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--fetch", action="store_true", help="fetch the project at its pinned commit")
    where.add_argument("--source", type=Path, help="a clone that already holds the project's folder")
    ap.add_argument("--out", type=Path, required=True, help="a new folder")
    ap.add_argument("--project", default=PROJECT)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--sandbox", default="require", choices=("require", "auto", "off"),
                    help="the harness's sandbox mode; keep require for a project the team did not write")
    args = ap.parse_args(argv)
    try:
        project = next((p for p in outside_trial.load_list() if p["name"] == args.project), None)
        if project is None:
            raise OutsideError(f"no outside project named {args.project}")
        args.out.mkdir(parents=True, exist_ok=False)
        work = args.out.parent / (args.out.name + "-work")   # the source and its copy stay out of --out
        source = outside_trial.fetch(project, work / "sources") if args.fetch else args.source
        game = outside_trial.contained(Path(source), project["path"], directory=True)
        doc = measure(game, project, args.out / "measure", workers=args.workers, sandbox=args.sandbox)
    except (OutsideError, outside_trial.TrialError, OSError) as exc:
        print(f"metamorphic outside: {exc}", file=sys.stderr)
        return 5
    text = markdown(doc)
    (args.out / "metamorphic-outside.md").write_text(text, encoding="utf-8")
    (args.out / "rows.json").write_text((args.out / "measure" / "rows.json").read_text(encoding="utf-8"), encoding="utf-8")
    print(text)
    print(json.dumps(summary(doc)))
    return 0 if any(r["runs"].get("clean") for r in doc["rows"]) else 3


if __name__ == "__main__":
    sys.exit(main())
