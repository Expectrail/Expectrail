"""The do-nothing control (#675, piece 1): the actor a generated check is about does nothing.

A check that still passes when the actor it is about does nothing at all states no obligation: a
paddle frozen solid passes "the paddle stays inside the play area". The near misses (dodgy.py) are
changes close to the candidate, and a near miss may still move. This control is one more build a
check must not pass, built from the check's own subject, never written by hand for a game:

1. The subject is the check's ``scope.class`` (``player``, ``enemy`` or ``projectile``).
2. The profile's ``selectors`` name the node for that class (``Player``, ``Enemy``, ``Bullet``).
3. The scene is the one ``.tscn`` whose root node has that name, and the script is its root's script.
4. The change:
   - a class whose scene a script makes at run time (``preload``/``load`` of the scene, then
     ``instantiate``) is **never made**: each function in that script that calls ``instantiate``
     returns at once (``return``, ``return false``, ``return 0`` or ``return 0.0`` by its declared
     return type);
   - any other class is **frozen**: its script's per-tick and input callbacks (``_process``,
     ``_physics_process``, ``_input``, ``_unhandled_input``, ``_unhandled_key_input``) return at once.

Where a step finds nothing, or more than one, there is no control for that class and the record says
why ("cannot tell"); nothing is guessed. The game copy is only read, and each control is a unified
diff applied to the clean game, so a replay of it is ``patches=[control]``.

Advisory: a check that passes the control is dropped by the generator (assess.validity), like a check
that kills no near miss. Nothing here changes what may count or clear a change.
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path

CLASSES = ("player", "enemy", "projectile")
CALLBACKS = ("_process", "_physics_process", "_input", "_unhandled_input", "_unhandled_key_input")
DEFAULT_RETURN = {None: "return", "void": "return", "bool": "return false", "int": "return 0", "float": "return 0.0"}

_NODE = re.compile(r'^\[node\s+name="([^"]+)"([^\]]*)\]\s*$')
_EXT = re.compile(r'^\[ext_resource\b[^\]]*\bpath="(res://[^"]+)"[^\]]*\bid="([^"]+)"[^\]]*\]\s*$')
_EXT_ID_FIRST = re.compile(r'^\[ext_resource\b[^\]]*\bid="([^"]+)"[^\]]*\bpath="(res://[^"]+)"[^\]]*\]\s*$')
_SCRIPT = re.compile(r'^script\s*=\s*ExtResource\(\s*"([^"]+)"\s*\)\s*$')
_FUNC = re.compile(r'^(static\s+)?func\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(.*\)\s*(?:->\s*([A-Za-z_][A-Za-z0-9_]*))?\s*:\s*(.*)$')


class NoControl(ValueError):
    """No do-nothing control can be made for this class; the message says why."""


def _rel(game: Path, path: Path) -> str:
    return path.relative_to(game).as_posix()


def _text_files(game: Path, suffix: str) -> list[Path]:
    return sorted(p for p in game.rglob(f"*{suffix}") if ".godot" not in p.relative_to(game).parts
                  and p.is_file() and not p.is_symlink())


def _root_scene(game: Path, node: str) -> tuple[Path, str]:
    """(scene, res:// path of its root's script) for the one scene whose root node is named ``node``."""
    found = []
    for scene in _text_files(game, ".tscn"):
        lines = scene.read_text(encoding="utf-8", errors="replace").splitlines()
        ext = {}
        root_at = None
        for i, line in enumerate(lines):
            if m := _EXT.match(line):
                ext[m.group(2)] = m.group(1)
            elif m := _EXT_ID_FIRST.match(line):
                ext[m.group(1)] = m.group(2)
            elif (m := _NODE.match(line)) and root_at is None:
                if "parent=" in m.group(2):
                    break
                root_at = i if m.group(1) == node else -1
                if root_at < 0:
                    break
        if root_at is None or root_at < 0:
            continue
        script = None
        for line in lines[root_at + 1:]:
            if line.startswith("["):
                break
            if m := _SCRIPT.match(line.strip()):
                script = ext.get(m.group(1))
        found.append((scene, script))
    if len(found) != 1:
        raise NoControl(f"{len(found)} scenes have a root node named {node!r}; exactly one is needed")
    scene, script = found[0]
    if not script or not script.endswith(".gd"):
        raise NoControl(f"the root node of {_rel(game, scene)} has no GDScript")
    return scene, script


def _res(game: Path, res: str) -> Path:
    path = (game / res.removeprefix("res://")).resolve()
    if not path.is_relative_to(game.resolve()) or not path.is_file():
        raise NoControl(f"{res} is not a file in the game")
    return path


def _functions(lines: list[str]) -> list[dict]:
    """Top-level functions: {name, at (the func line), ret, body (index of the first body line), indent}."""
    out = []
    for i, line in enumerate(lines):
        m = _FUNC.match(line)
        if not m:
            continue
        if m.group(4).strip() and not m.group(4).lstrip().startswith("#"):
            out.append({"name": m.group(2), "at": i, "ret": m.group(3), "body": None, "indent": None,
                        "end": i + 1, "oneLine": True})
            continue
        j = i + 1
        while j < len(lines) and (not lines[j].strip() or lines[j].lstrip().startswith("#")):
            j += 1
        if j >= len(lines) or not lines[j][:1].isspace():
            continue
        indent = lines[j][: len(lines[j]) - len(lines[j].lstrip())]
        end = j
        while end < len(lines) and (not lines[end].strip() or lines[end].startswith(indent)):
            end += 1
        out.append({"name": m.group(2), "at": i, "ret": m.group(3), "body": j, "indent": indent, "end": end,
                    "oneLine": False})
    return out


def _returning(lines: list[str], funcs: list[dict], rel: str) -> list[str]:
    """``lines`` with ``return`` (by declared type) as the first statement of each of ``funcs``."""
    after = list(lines)
    for f in sorted(funcs, key=lambda f: f["at"], reverse=True):
        if f["oneLine"]:
            raise NoControl(f"{rel}: {f['name']} is written on one line")
        if f["ret"] not in DEFAULT_RETURN:
            raise NoControl(f"{rel}: {f['name']} returns {f['ret']}, which has no do-nothing value here")
        after.insert(f["body"], f"{f['indent']}{DEFAULT_RETURN[f['ret']]}")
    return after


def _diff(rel: str, before: list[str], after: list[str]) -> str:
    return "".join(difflib.unified_diff([s + "\n" for s in before], [s + "\n" for s in after],
                                        fromfile=f"a/{rel}", tofile=f"b/{rel}"))


def _makers(game: Path, scene_res: str) -> list[Path]:
    """Scripts that load ``scene_res`` and call ``instantiate``."""
    loads = re.compile(r'\b(pre)?load\(\s*"' + re.escape(scene_res) + r'"\s*\)')
    return [p for p in _text_files(game, ".gd")
            if loads.search(t := p.read_text(encoding="utf-8", errors="replace")) and "instantiate(" in t]


def control(game: Path, profile: dict, cls: str) -> dict:
    """{class, id, mode, file, patchText} for one class, or NoControl with the reason."""
    game = Path(game).resolve()
    if cls not in CLASSES:
        raise NoControl(f"unknown class {cls!r}")
    node = (profile.get("selectors") or {}).get(cls)
    if not isinstance(node, str) or not node:
        raise NoControl(f"the profile names no node for {cls}")
    scene, script_res = _root_scene(game, node)
    scene_res = "res://" + _rel(game, scene)
    makers = _makers(game, scene_res)
    if makers:
        mode, patches = "never-made", []
        for path in makers:
            rel = _rel(game, path)
            lines = path.read_text(encoding="utf-8").splitlines()
            funcs = [f for f in _functions(lines)
                     if any("instantiate(" in lines[k] for k in range(f["at"], f["end"]))]
            if not funcs:
                raise NoControl(f"{rel} calls instantiate outside a function")
            patches.append(_diff(rel, lines, _returning(lines, funcs, rel)))
        files = [_rel(game, p) for p in makers]
    else:
        mode = "frozen"
        path = _res(game, script_res)
        rel = _rel(game, path)
        lines = path.read_text(encoding="utf-8").splitlines()
        funcs = [f for f in _functions(lines) if f["name"] in CALLBACKS]
        if not funcs:
            raise NoControl(f"{rel} defines none of {', '.join(CALLBACKS)}")
        patches, files = [_diff(rel, lines, _returning(lines, funcs, rel))], [rel]
    return {"class": cls, "id": f"do-nothing:{cls}", "mode": mode, "files": files, "patchText": "".join(patches)}


def controls(game: Path, profile: dict, classes) -> list[dict]:
    """One row per class: a control, or ``patchText: None`` and the reason."""
    out = []
    for cls in sorted(set(classes)):
        try:
            out.append(dict(control(game, profile, cls), reason=None))
        except (NoControl, OSError, UnicodeDecodeError) as exc:
            out.append({"class": cls, "id": f"do-nothing:{cls}", "mode": None, "files": [], "patchText": None,
                        "reason": " ".join(str(exc).split())[:300]})
    return out
