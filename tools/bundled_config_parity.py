"""Does the bundled game give the same results with a project config as without one? (#259)

    python3 -m tools.bundled_config_parity [--out FILE] [--traces-only]

#259 asks that the bundled game get an ``expectrail.project.json`` that reproduces today's results
exactly. Sean put it beside ``project.godot`` (``game/platformer/expectrail.project.json``) on
November 19, 2026. This tool compares throwaway copies of the game that carry it with copies that
have it removed.

Two comparisons, both on this machine, no model called:

- **Traces.** Each public route is replayed headless without and with the config. Everything the
  unconfigured trace holds must be equal in the configured one. The configured replay may only add
  what a config adds (``CONFIG_ADDS``: the role boxes, the bindings, the declared viewport). Any other
  difference, a missing row or an extra row is a difference.
- **Decisions.** The Run it samples run through the real job, gate and both observers
  (``expectrail.runit``), with recorded vision answers looked up by each frame's exact bytes. Equal
  decisions and an equal count of answered questions mean the configured game drew the same frames
  (a frame that differs by one byte has no recorded answer).

It prints one line per case and writes ``expectrail.bundled-config-parity/v1`` with ``--out``. Exit 0
when everything is equal, 1 when anything differs, 5 when it could not be run (no engine, a sample
that failed to run). A difference is reported, never hidden: it is what #259 has to fix before the
config may sit beside the game.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
GAME = ROOT / "game" / "platformer"
CONFIG = GAME / "expectrail.project.json"
ROUTES = ("smoke", "combat", "coins", "traversal")
SAMPLES = ("clean", "fall-through-bug", "fall-through-repair")
FORMAT = "expectrail.bundled-config-parity/v1"
# What a configured trace may carry beyond an unconfigured one. Nothing else may differ.
CONFIG_ADDS = {"header": {"bindings", "viewport"}, "capabilities": {"roleBoxes"}, "row": {"roleObjects"}}


class CannotRun(RuntimeError):
    """The comparison could not be made; the message says why."""


def load_config(game: Path = GAME) -> dict:
    """The bundled config, checked against the game it is for."""
    from expectrail import project_config

    return project_config.load(CONFIG, game)


# What `expectrail init` proposes and a config's reader does not compare with the game itself.
DECLARED = ("entryScene", "viewport", "physicsTicksPerSecond", "inputActions", "bindings")


def declared_mismatches(config: dict, game: Path = GAME) -> list[str]:
    """Where the config says something other than `expectrail init` reads from the game's own files.

    The replay does not compare a config's viewport or tick rate with project.godot (it draws what
    the game declares), so a wrong value would sit in the config unnoticed. This holds the bundled
    config to init's proposal for every field init proposes; init's ``draft`` flag and its draft
    route are the only parts left out."""
    from expectrail import onboarding

    root = Path(game).resolve()
    proposed = onboarding.proposal(root, onboarding.inspect(root))
    if "unresolvedBindings" in proposed:
        return ["init cannot bind this game: " + "; ".join(proposed["unresolvedBindings"])]
    found = []
    for field in DECLARED:
        if config.get(field) != proposed["config"].get(field):
            found.append(f"{field} is {json.dumps(config.get(field))} in the config, but init reads "
                         f"{json.dumps(proposed['config'].get(field))} from the game")
    return found


def trace_differences(plain: dict, configured: dict, limit: int = 20) -> list[str]:
    """Where the configured trace says something other than the unconfigured one.

    Only the fields in ``CONFIG_ADDS`` may be added. A field the plain trace has must be present and
    equal; a row count must match. Returns at most ``limit`` plain sentences (empty when equal)."""
    found: list[str] = []
    if not isinstance(plain, dict) or not isinstance(configured, dict):
        return ["a trace is not a JSON object"]
    for key in sorted(set(plain) | set(configured)):
        if key == "rows":
            continue
        if key not in plain:
            if key not in CONFIG_ADDS["header"]:
                found.append(f"the configured trace adds {key!r}, which a config does not add")
            continue
        if key not in configured:
            found.append(f"the configured trace has no {key!r}")
            continue
        if key == "capabilities" and isinstance(plain[key], dict) and isinstance(configured[key], dict):
            extra = set(configured[key]) - set(plain[key]) - CONFIG_ADDS["capabilities"]
            same = {k: configured[key].get(k) for k in plain[key]} == plain[key]
            if extra or not same:
                found.append("capabilities differ: " + json.dumps({"plain": plain[key], "configured": configured[key]},
                                                                  sort_keys=True)[:300])
            continue
        if plain[key] != configured[key]:
            found.append(f"{key} differs")
    rows_a, rows_b = plain.get("rows"), configured.get("rows")
    if not isinstance(rows_a, list) or not isinstance(rows_b, list):
        return found + ["a trace has no list of rows"]
    if len(rows_a) != len(rows_b):
        found.append(f"{len(rows_a)} rows without the config, {len(rows_b)} with it")
    for n, (a, b) in enumerate(zip(rows_a, rows_b)):
        if len(found) >= limit:
            break
        if not isinstance(a, dict) or not isinstance(b, dict):
            found.append(f"row {n} is not an object")
            continue
        extra = sorted(set(b) - set(a) - CONFIG_ADDS["row"])
        changed = sorted(k for k in a if a[k] != b.get(k, _MISSING))
        if extra or changed:
            found.append(f"row {n}: " + "; ".join([f"{k} differs" for k in changed] + [f"adds {k}" for k in extra]))
    return found[:limit]


_MISSING = object()


def _engine() -> Path:
    from harness import run as hr

    engine = hr.find_godot()
    if not Path(engine).is_file():
        raise CannotRun(f"no Godot engine at {engine}: run harness/get_godot.sh (or set EXPECTRAIL_GODOT)")
    return Path(engine)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare_traces(work: Path, config: dict, routes=ROUTES) -> list[dict]:
    """Replay each route headless, without and with the config, in copies of the game."""
    from harness import run as hr

    engine = _engine()
    plain_game, conf_game = work / "plain" / "platformer", work / "configured" / "platformer"
    shutil.copytree(GAME, plain_game, ignore=shutil.ignore_patterns(".godot", CONFIG.name))
    shutil.copytree(GAME, conf_game, ignore=shutil.ignore_patterns(".godot"))
    (conf_game / "expectrail.project.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    results = []
    for route in routes:
        path = ROOT / "harness" / "routes" / f"{route}.json"
        traces = {}
        for side, game in (("plain", plain_game), ("configured", conf_game)):
            out = work / "runs" / route / side
            try:
                hr.run(path, out, game=game, godot=engine, capture_frames=False, sandbox="off", fps=None)
            except SystemExit as exc:
                raise CannotRun(f"{route} {side}: the replay stopped: {exc}") from exc
            traces[side] = (json.loads((out / "trace.json").read_text(encoding="utf-8")), _sha(out / "trace.json"))
        found = trace_differences(traces["plain"][0], traces["configured"][0])
        if config_applied(traces["plain"][0], config):
            found.insert(0, "the copy without a config was replayed with one")
        if not config_applied(traces["configured"][0], config):
            found.insert(0, "the config was not applied to the configured replay, so this compares nothing")
        results.append({"route": route, "rows": len(traces["plain"][0].get("rows") or []),
                        "plainSha256": traces["plain"][1], "configuredSha256": traces["configured"][1],
                        "configApplied": config_applied(traces["configured"][0], config),
                        "equal": not found, "differences": found})
    return results


def config_applied(trace: dict, config: dict) -> bool:
    """The replay used this config: its bindings are in the header and every row has role boxes."""
    rows = trace.get("rows") if isinstance(trace, dict) else None
    return (isinstance(rows, list) and bool(rows) and trace.get("bindings") == config["bindings"]
            and all(isinstance(r, dict) and "roleObjects" in r for r in rows))


@contextlib.contextmanager
def _watch_replays(config: dict, seen: list[bool]):
    """Note, for each replay the job makes, whether it used the config."""
    from harness import run as hr

    original = hr.run

    def watched(route, out, *args, **kwargs):
        doc = original(route, out, *args, **kwargs)
        try:
            trace = json.loads((Path(out) / "trace.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            trace = {}
        seen.append(config_applied(trace, config))
        return doc

    with mock.patch.object(hr, "run", watched):
        yield


def _without_config():
    """Every sample checkout has the config removed, for the unconfigured side."""
    from expectrail.orchestrator import sample as smp

    original = smp.checkout

    def checkout(target, *, bug, root=ROOT):
        made = original(target, bug=bug, root=root)
        (Path(made) / smp.GAME / CONFIG.name).unlink(missing_ok=True)
        return made

    return mock.patch.object(smp, "checkout", checkout)


def _with_config(config: dict):
    """Every sample checkout gets the config beside project.godot."""
    from expectrail.orchestrator import sample as smp

    original = smp.checkout

    def checkout(target, *, bug, root=ROOT):
        made = original(target, bug=bug, root=root)
        game = Path(made) / smp.GAME
        (game / "expectrail.project.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        return made

    return mock.patch.object(smp, "checkout", checkout)


def _run_sample(sample: str, out: Path) -> dict:
    from expectrail import runit

    try:
        doc = runit.run(sample, out)
    except runit.RunItError as exc:
        raise CannotRun(f"{sample}: {exc}") from exc
    vision = doc.get("vision") or {}
    return {"phase": doc.get("phase"), "decision": doc.get("decision"), "asked": vision.get("asked"),
            "answered": vision.get("answered"), "notRecorded": vision.get("notRecorded"),
            "diagnostics": [d.get("code") for d in doc.get("diagnostics") or []]}


def compare_decisions(work: Path, config: dict, samples=SAMPLES) -> list[dict]:
    """Each Run it sample, without and with the config, through the real job."""
    _engine()
    results = []
    for sample in samples:
        plain_seen: list[bool] = []
        conf_seen: list[bool] = []
        with _without_config(), _watch_replays(config, plain_seen):
            plain = _run_sample(sample, work / "samples" / sample / "plain")
        with _with_config(config), _watch_replays(config, conf_seen):
            configured = _run_sample(sample, work / "samples" / sample / "configured")
        found = [f"{k}: {plain[k]!r} without the config, {configured[k]!r} with it"
                 for k in plain if plain[k] != configured[k]]
        if not conf_seen or not all(conf_seen):
            found.insert(0, f"the config was applied to {sum(conf_seen)} of {len(conf_seen)} configured replays")
        if any(plain_seen):
            found.insert(0, "a replay without the config used one")
        configured["replays"], configured["configApplied"] = len(conf_seen), sum(conf_seen)
        plain["replays"] = len(plain_seen)
        if len(plain_seen) != len(conf_seen):
            found.append(f"{len(plain_seen)} replays without the config, {len(conf_seen)} with it")
        if plain["phase"] != "completed":
            found.append(f"the sample did not complete without the config ({plain['phase']}), so nothing was compared")
        results.append({"sample": sample, "plain": plain, "configured": configured, "equal": not found,
                        "differences": found})
    return results


def report(traces: list[dict], decisions: list[dict] | None, declared: list[str]) -> dict:
    cases = traces + (decisions or [])
    return {"format": FORMAT, "config": "game/platformer/expectrail.project.json", "configSha256": _sha(CONFIG),
            "declared": declared, "traces": traces, "decisions": decisions,
            "equal": not declared and bool(cases) and all(c["equal"] for c in cases)}


def lines(doc: dict) -> list[str]:
    said = [("declared settings: as init reads them from the game" if not doc["declared"]
             else "declared settings: DIFFERENT: " + doc["declared"][0])]
    for t in doc["traces"]:
        word = "same" if t["equal"] else "DIFFERENT"
        said.append(f"trace {t['route']}: {word} ({t['rows']} rows, config applied: {t['configApplied']})" + ("" if t["equal"] else ": " + t["differences"][0]))
    for d in doc["decisions"] or []:
        word = "same" if d["equal"] else "DIFFERENT"
        c = d["configured"]
        said.append(f"sample {d['sample']}: {word} ({c['decision']}, {c['answered']}/{c['asked']} recorded answers, "
                    f"config used in {c.get('configApplied', 0)} of {c.get('replays', 0)} replays)"
                    + ("" if d["equal"] else ": " + d["differences"][0]))
    if doc["decisions"] is None:
        said.append("decisions: not compared (--traces-only)")
    said.append("parity: " + ("every case is the same" if doc["equal"] else "the config changes something; see above"))
    return said


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m tools.bundled_config_parity",
                                     description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=None, help="write the parity record here")
    parser.add_argument("--traces-only", action="store_true", help="skip the Run it samples (no frames drawn)")
    args = parser.parse_args(argv)
    os.environ.setdefault("EXPECTRAIL_SANDBOX", "off")
    try:
        config = load_config()
        declared = declared_mismatches(config)
        with tempfile.TemporaryDirectory(prefix="expectrail-parity-") as tmp:
            traces = compare_traces(Path(tmp), config)
            decisions = None if args.traces_only else compare_decisions(Path(tmp), config)
    except CannotRun as exc:
        print(f"cannot tell: {exc}", file=sys.stderr)
        return 5
    doc = report(traces, decisions, declared)
    for line in lines(doc):
        print(line)
    if args.out:
        args.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if doc["equal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
