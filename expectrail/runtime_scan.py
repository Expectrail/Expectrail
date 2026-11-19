"""Runtime discovery for `expectrail init --runtime` and `expectrail inspect --runtime` (#260).

The plain `init` and `inspect` read saved scenes and never start the game, so they miss what a game
builds in code: a floor made by a script, a sprite whose image is set in `_ready`, a node added to a
group at runtime. This starts the game headless on a copy, in the replay sandbox when the machine has
one, lets it run ``TICKS`` physics ticks with no input, and lists the nodes of the current scene as
the engine has them then (``harness/godot/expectrail_scan.gd``).

Writer: ``scan`` (an ``expectrail.runtime-scan/v1`` record). Reader: ``problems``. Contract:
``contracts/runtime-scan.v1.schema.json``. ``merge`` adds a record to the saved-scene listing of
``expectrail.onboarding.inspect``.

What the scan says is the game's own report of itself: the game's code ran in the same process, so it
could change the file. It is setup information for the person who owns the game, never evidence for a
verdict. Everything read from it is bounded and checked; anything that does not read cleanly is
refused, never guessed.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from expectrail import project_config, resources

FORMAT = "expectrail.runtime-scan/v1"
RAW_FORMAT = "expectrail.runtime-scan-raw/v0"
SCHEMA = resources.ROOT / "contracts" / "runtime-scan.v1.schema.json"
SCRIPT = "expectrail_scan.gd"
AUTOLOAD = 'ExpectrailScan="*res://expectrail_scan.gd"'
TICKS = 30
MAX_NODES = 2000
MAX_RAW_BYTES = 4 * 1024 * 1024
KINDS = ("body", "platform", "area", "sprite", "animatedSprite", "polygon", "tileLayer", "camera")
DRAWN = ("sprite", "animatedSprite", "polygon")
NOTE = ("Listed by the running game after a few ticks with no input. It is the game's own report, "
        "for setting up a config, not evidence for a verdict.")


class RuntimeScanError(ValueError):
    """The scan cannot be made or read. The message names what to change."""


def _text(value, where: str, limit: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or (not value and not empty):
        raise RuntimeScanError(f"the running game's scan has an unreadable {where}; cannot tell")
    if any(ord(c) < 32 for c in value):
        raise RuntimeScanError(f"the running game's scan has a control character in {where}; cannot tell")
    return value


def _count(value, where: str, limit: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= limit:
        raise RuntimeScanError(f"the running game's scan has an unreadable {where}; cannot tell")
    return value


def _flag(value, where: str) -> bool:
    if not isinstance(value, bool):
        raise RuntimeScanError(f"the running game's scan has an unreadable {where}; cannot tell")
    return value


_COMMON = {"path", "kind", "type", "className", "groups"}
_EXTRA = {"sprite": {"visible", "images", "unsavedImages"}, "animatedSprite": {"visible", "images", "unsavedImages"},
          "polygon": {"visible", "images", "unsavedImages"}, "tileLayer": {"visible", "cells", "collides"},
          "camera": {"visible", "enabled"}, "body": {"visible"}, "platform": {"visible"}, "area": {"visible"}}


def _node(raw, index: int) -> dict:
    where = f"node {index}"
    if not isinstance(raw, dict):
        raise RuntimeScanError(f"the running game's scan has an unreadable {where}; cannot tell")
    kind = raw.get("kind")
    if kind not in KINDS:
        raise RuntimeScanError(f"the running game's scan names an unknown kind at {where}; cannot tell")
    allowed = _COMMON | _EXTRA[kind]
    extra = sorted(set(raw) - allowed)
    missing = sorted((_COMMON | (_EXTRA[kind] - {"visible"})) - set(raw))
    if extra or missing:
        raise RuntimeScanError(f"the running game's scan has {'unknown field ' + extra[0] if extra else 'no ' + missing[0]} "
                               f"at {where}; cannot tell")
    path = _text(raw["path"], f"path at {where}", 1000)
    path = "" if path == "." else path
    if path.startswith("/") or path.startswith("..") or "//" in path:
        raise RuntimeScanError(f"the running game's scan has a node path outside the scene at {where}; cannot tell")
    groups = raw["groups"]
    if not isinstance(groups, list) or len(groups) > 32:
        raise RuntimeScanError(f"the running game's scan has unreadable groups at {where}; cannot tell")
    out = {"path": path or ".", "kind": kind, "type": _text(raw["type"], f"type at {where}", 64),
           "className": _text(raw["className"], f"class name at {where}", 64, empty=True) or None,
           "groups": sorted({_text(g, f"group at {where}", 64) for g in groups})}
    if "visible" in raw:
        out["visible"] = _flag(raw["visible"], f"visible flag at {where}")
    if kind in DRAWN:
        images = raw["images"]
        if not isinstance(images, list) or len(images) > 64:
            raise RuntimeScanError(f"the running game's scan has unreadable images at {where}; cannot tell")
        out["images"] = sorted({_text(i, f"image at {where}", 200) for i in images})
        if any(not i.startswith("res://") for i in out["images"]):
            raise RuntimeScanError(f"the running game's scan names an image outside res:// at {where}; cannot tell")
        out["unsavedImages"] = _count(raw["unsavedImages"], f"unsaved image count at {where}", 100000)
    elif kind == "tileLayer":
        out["cells"] = _count(raw["cells"], f"cell count at {where}", 10 ** 8)
        out["collides"] = _flag(raw["collides"], f"collision flag at {where}")
    elif kind == "camera":
        out["enabled"] = _flag(raw["enabled"], f"enabled flag at {where}")
    return out


def read_raw(data: bytes, ticks: int) -> dict:
    """The scanner's file as checked values: nodes, the scene it ran and whether the list was cut."""
    from expectrail.contracts import ContractError, strict_loads

    if len(data) > MAX_RAW_BYTES:
        raise RuntimeScanError("the running game's scan is larger than any scan of a game this size; cannot tell")
    try:
        raw = strict_loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ContractError, ValueError) as exc:
        raise RuntimeScanError(f"the running game's scan is not readable JSON ({type(exc).__name__}); cannot tell") from exc
    if not isinstance(raw, dict) or raw.get("format") != RAW_FORMAT:
        raise RuntimeScanError("the running game's scan is not a scan record; cannot tell")
    if "error" in raw:
        raise RuntimeScanError(f"the running game had {_text(raw['error'], 'error', 200)} after {ticks} ticks; "
                               "check that the starting scene loads, then scan again")
    if set(raw) != {"format", "ticks", "scene", "nodes", "truncated"}:
        raise RuntimeScanError("the running game's scan has unknown or missing fields; cannot tell")
    if _count(raw["ticks"], "tick count", 10 ** 6) != ticks:
        raise RuntimeScanError(f"the running game's scan ran {raw['ticks']} ticks, not the {ticks} asked; cannot tell")
    scene = _text(raw["scene"], "scene", 200, empty=True)
    if not isinstance(raw["nodes"], list) or len(raw["nodes"]) > MAX_NODES:
        raise RuntimeScanError("the running game's scan lists more nodes than it may; cannot tell")
    nodes = [_node(n, i) for i, n in enumerate(raw["nodes"])]
    seen = set()
    for node in nodes:
        if node["path"] in seen:
            raise RuntimeScanError(f"the running game's scan lists {node['path']!r} twice; cannot tell")
        seen.add(node["path"])
    return {"scene": scene or None, "nodes": nodes, "truncated": _flag(raw["truncated"], "truncated flag")}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scrub(text: str, *folders: Path) -> str:
    for folder in folders:
        text = text.replace(str(folder), "<removed scan folder>")
    return text


def scan(root: Path, *, ticks: int = TICKS, godot: Path | None = None, sandbox: str | None = None) -> dict:
    """Start the game at ``root`` headless on a copy, let it run ``ticks`` physics ticks with no input,
    and return the ``expectrail.runtime-scan/v1`` record. Raises RuntimeScanError."""
    from expectrail.godot_project import configured_scene, require_declared_settings, require_gdscript
    from harness import run as harness, sandbox as box, tree

    root = Path(root).resolve()
    if not (root / "project.godot").is_file():
        raise RuntimeScanError(f"{root} has no project.godot; give the folder that holds the Godot project")
    if not isinstance(ticks, int) or isinstance(ticks, bool) or not 1 <= ticks <= 600:
        raise RuntimeScanError("a runtime scan runs from 1 to 600 physics ticks")
    try:
        config = project_config.read_game(root)
        config_path = project_config.find(root)
        require_gdscript(root, config)
        scene = configured_scene(root, config)
        require_declared_settings(root, config)
    except tree.TreeProblem as exc:
        raise RuntimeScanError(f"the game cannot be started as it stands: {exc}") from exc
    except (ValueError, OSError) as exc:
        raise RuntimeScanError(str(exc)) from exc
    try:
        tool, isolation = box.choose(sandbox, display=False)
    except box.SandboxError as exc:
        raise RuntimeScanError(str(exc)) from exc
    try:
        game_tree = harness.tree_digest(root)
    except tree.TreeProblem as exc:
        raise RuntimeScanError(f"the game cannot be started as it stands: {exc}") from exc
    try:
        godot = godot or harness.find_godot()
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeScanError(f"Godot could not be found or fetched ({type(exc).__name__}); "
                               "run `expectrail doctor` to see what is missing") from exc
    env = harness.game_env()
    cache = harness.ensure_import_cache(root, godot, env, tool, None, game_tree)
    with tempfile.TemporaryDirectory(prefix="expectrail-scan-") as tmp:
        work, out = Path(tmp) / "work", Path(tmp) / "out"
        out.mkdir()
        if tree.copy(root, work, skip=tree.GODOT_SKIP) != game_tree:
            raise RuntimeScanError("the game folder changed while the scan was being set up; nothing was run. "
                                   "Scan again when it is unchanged")
        if cache and (cache / "imported").is_dir():
            shutil.copytree(cache, work / ".godot")
        shutil.copy(harness.REPO / "harness" / "godot" / SCRIPT, work / SCRIPT)
        settings = (work / "project.godot").read_text(encoding="utf-8")
        if "[autoload]\n" in settings:
            settings = settings.replace("[autoload]\n", "[autoload]\n\n" + AUTOLOAD + "\n", 1)
        else:
            settings += "\n[autoload]\n\n" + AUTOLOAD + "\n"
        (work / "project.godot").write_text(settings, encoding="utf-8")
        try:
            harness.godot_import(godot, work, env, tool)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeScanError("Godot's import of the game timed out; nothing was scanned") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeScanError(f"Godot's import of the game failed (exit {exc.returncode}); "
                                   "open the project in the editor once and fix the errors it shows") from exc
        except box.DiskBoundError as exc:
            raise RuntimeScanError(f"the game's import was stopped: {exc}") from exc
        if tool is not None:
            engine, project, target = box.ENGINE_BINARY, box.GAME, f"{box.OUT}/scan.json"
        else:
            engine, project, target = str(godot), str(work), str((out / "scan.json").resolve())
        cmd = [engine, "--headless", "--path", project, "--audio-driver", "Dummy", "--fixed-fps", "60"]
        if scene is not None:
            cmd.append(scene)
        cmd += ["--disable-vsync", "--", f"--scan={target}", f"--ticks={ticks}"]
        try:
            if tool is not None:
                proc = box.run(tool, cmd, timeout=300, game=work, out=out, engine=godot, env=env)
            else:
                proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeScanError(f"the game ran past the scan's time limit without reaching tick {ticks}; "
                                   "nothing was scanned") from exc
        except box.DiskBoundError as exc:
            raise RuntimeScanError(f"the scan was stopped: {exc}") from exc
        found = out / "scan.json"
        if found.is_symlink() or not found.is_file():
            tail = _scrub((proc.stdout + proc.stderr)[-400:], work, out).strip().splitlines()
            raise RuntimeScanError(f"the game stopped before the scan was written (exit {proc.returncode})"
                                   + (f"; its last line: {json.dumps(tail[-1][:200])}" if tail else "")
                                   + ". Check that the game starts headless, then scan again")
        with found.open("rb") as stream:
            data = stream.read(MAX_RAW_BYTES + 1)
        log = proc.stdout + proc.stderr
    raw = read_raw(data, ticks)
    version = next((line.split()[2] for line in log.splitlines() if line.startswith("Godot Engine v")), None)
    doc = {"format": FORMAT,
           "project": {"entryScene": scene, "scene": raw["scene"], "gameTree": game_tree,
                       "configSha256": _sha256(config_path) if config_path is not None else None},
           "ticks": ticks,
           "engine": {"name": "godot", "version": (version or harness.GODOT_VERSION).removeprefix("v")[:64]},
           "isolation": {"sandbox": tool is not None, "reason": isolation.get("reason")},
           "truncated": raw["truncated"], "nodes": raw["nodes"], "note": NOTE}
    found = problems(doc)
    if found:
        raise RuntimeScanError("the scan record does not match its contract: " + "; ".join(found[:3]))
    return doc


def problems(doc) -> list[str]:
    """What is wrong with a runtime-scan record; empty when it can be read. It uses the gate's own
    schema reader, so a machine without jsonschema (an installed Expectrail) reads it the same way."""
    from expectrail.contracts import ContractError, canonical_v1
    from expectrail.gate import record as rec

    try:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"runtime-scan: the schema could not be read ({type(exc).__name__})"]
    try:
        canonical_v1(doc)
    except ContractError as exc:
        return [f"runtime-scan: {exc}"]
    found = [f"runtime-scan: {e}" for e in rec.errors(doc, schema)]
    if found:
        return found
    out = []
    paths = [n["path"] for n in doc["nodes"]]
    if len(set(paths)) != len(paths):
        out.append("a node path is listed twice")
    for node in doc["nodes"]:
        # Exactly the fields of its kind, no more and no fewer (the schema alone cannot say this).
        wanted = _EXTRA[node["kind"]] - {"visible"}
        present = set(node) - _COMMON - {"visible"}
        if present != wanted:
            out.append(f"{node['path']}: a {node['kind']} carries exactly "
                       + (", ".join(sorted(wanted)) or "no kind-specific field"))
        for field in ("groups", "images"):
            if field in node and len(set(node[field])) != len(node[field]):
                out.append(f"{node['path']}: {field} lists a value twice")
    return out


def _owner(path: str, bodies: set[str]) -> str | None:
    """The nearest physics body at or above ``path`` (scene root spelled ""), or None."""
    while True:
        if path in bodies:
            return path
        if not path:
            return None
        path = path.rpartition("/")[0]


def merge(info: dict, doc: dict, static_paths) -> dict:
    """The saved-scene listing ``info`` with what the running game showed added to it.

    Runtime findings are listed under ``runtime``. The player's image is taken from the running game
    only when the saved scenes gave none, there is one player candidate, and exactly one saved image is
    drawn under it; otherwise the listing says why it cannot be bound. Nothing found at runtime
    replaces a saved-scene finding."""
    if problems(doc):
        raise RuntimeScanError("the runtime scan record cannot be read: " + "; ".join(problems(doc)))
    static = {"" if p == "." else p for p in static_paths}
    nodes = {("" if n["path"] == "." else n["path"]): n for n in doc["nodes"]}
    bodies = {p for p, n in nodes.items() if n["kind"] in ("body", "area")}
    named = [p for p in bodies if p.rpartition("/")[2].casefold() == "player"
             or (p == "" and info.get("players") == ["."])]
    players = sorted(named or bodies)

    def spell(p):
        return p or "."

    ground = [spell(p) for p, n in nodes.items() if n["kind"] == "tileLayer" and n["collides"] and n["cells"] > 0]
    empty = [spell(p) for p, n in nodes.items() if n["kind"] == "tileLayer" and not (n["collides"] and n["cells"] > 0)]
    groups: dict[str, list[str]] = {}
    for p, n in nodes.items():
        for g in n["groups"]:
            groups.setdefault(g, []).append(spell(p))
    classes: dict[str, list[str]] = {}
    for p, n in nodes.items():
        if n["className"]:
            classes.setdefault(n["className"], []).append(spell(p))
    runtime = {"ticks": doc["ticks"], "sandboxed": doc["isolation"]["sandbox"],
               "players": [spell(p) for p in players],
               "groundLayers": sorted(ground), "emptyOrNonSolidLayers": sorted(empty),
               "onlyAtRuntime": sorted(spell(p) for p in nodes if p not in static),
               "groups": {g: sorted(v) for g, v in sorted(groups.items())},
               "classes": {c: sorted(v) for c, v in sorted(classes.items())},
               "truncated": doc["truncated"], "note": NOTE}
    images, drawn_without, why = set(), [], None
    if len(players) == 1:
        player = players[0]
        for p, n in nodes.items():
            if n["kind"] not in DRAWN or _owner(p, bodies) != player:
                continue
            images.update(n["images"])
            if n["unsavedImages"]:
                drawn_without.append(f"{spell(p)}: {n['type']} draws {n['unsavedImages']} image(s) made in code, "
                                     "with no file to bind")
            elif not n["images"]:
                drawn_without.append(f"{spell(p)}: {n['type']} draws no image file"
                                     + (" (a filled polygon)" if n["kind"] == "polygon" else ""))
        runtime["playerImages"] = sorted(images)
        runtime["playerDrawnWithout"] = drawn_without
    else:
        why = ("the running game has no physics body for the player" if not players else
               "the running game has several player candidates: " + ", ".join(spell(p) for p in players))
    merged = dict(info)
    merged["runtime"] = runtime
    if why:
        runtime["playerProblem"] = why + "; bind the player by hand"
    if info.get("unresolvedBindings") and not info.get("textures") and len(players) == 1:
        if len(info.get("players") or []) <= 1 and spell(players[0]) in (info.get("players") or [spell(players[0])]):
            if len(images) == 1 and not drawn_without:
                merged["players"] = [spell(players[0])]
                merged["textures"] = sorted(images)
                merged["unresolvedBindings"] = []
                merged["textureFrom"] = "runtime"
            else:
                reasons = list(drawn_without)
                if len(images) > 1:
                    reasons.append(f"{spell(players[0])}: the running player draws several images: " + ", ".join(sorted(images)))
                merged["unresolvedBindings"] = list(info["unresolvedBindings"][:-1]) + reasons + info["unresolvedBindings"][-1:]
    return merged
