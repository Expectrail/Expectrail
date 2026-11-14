"""Read an expectrail.project/v1 file.

The file sits next to project.godot. It names bindings (a node path or a group, and the texture
the object is drawn with), the input actions and the tick and capture rates. It does not name
sizes. A file that is missing is fine: the caller keeps its own defaults. A file that is present
and not valid is an error that names what to fix; nothing then pretends the file was absent.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

FORMAT = "expectrail.project/v1"
FILENAME = "expectrail.project.json"
_ROLES = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
_PROVIDER = re.compile(r"^(?:ref:|env:)[A-Za-z0-9_./-]+$")
_ROOT_FIELDS = {
    "format", "adapter", "version", "toolchain", "entryScene", "viewport",
    "physicsTicksPerSecond", "captureFps", "inputActions", "bindings",
    "routes", "approvedContracts", "providers",
}
_REQUIRED = (
    "format", "adapter", "entryScene", "viewport", "physicsTicksPerSecond",
    "captureFps", "inputActions", "bindings",
)
_BINDING_FIELDS = {"node", "group", "texture"}


class ProjectConfigError(ValueError):
    """The project config is present and cannot be used. The message names the field."""


def find(game: Path) -> Path | None:
    """The config beside a game's project file, or None when that game has none."""
    path = Path(game) / FILENAME
    return path if path.is_file() else None


def read_game(game: Path) -> dict | None:
    """The game's config, or None when it has none. Present but invalid raises."""
    path = find(game)
    return None if path is None else load(path, game)


def load(path: Path, root: Path | None = None) -> dict:
    """Read one config. ``root`` is the project the res:// paths must stay inside."""
    path = Path(path)
    root = Path(root) if root is not None else path.parent
    name = path.name
    if not path.is_file():
        raise ProjectConfigError(f"{name}: no such file")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProjectConfigError(f"{name}: not valid JSON ({exc.msg} at line {exc.lineno})") from exc
    if not isinstance(doc, dict):
        raise ProjectConfigError(f"{name}: the file must be a JSON object")
    extra = sorted(set(doc) - _ROOT_FIELDS)
    if extra:
        raise ProjectConfigError(f"{name}: unknown field {extra[0]!r}; remove it")
    for field in _REQUIRED:
        if field not in doc:
            raise ProjectConfigError(f"{name}: missing {field!r}")
    if doc["format"] != FORMAT:
        raise ProjectConfigError(f"{name}: format must be {FORMAT}, not {doc['format']!r}")
    if doc["adapter"] not in ("godot", "unity"):
        raise ProjectConfigError(f"{name}: adapter must be \"godot\" or \"unity\", not {doc['adapter']!r}")
    _text(doc, "version", name, required=False)
    _toolchain(doc.get("toolchain"), name)
    _res_file(doc["entryScene"], root, f"{name}: entryScene")
    _pair(doc["viewport"], f"{name}: viewport")
    _whole(doc["physicsTicksPerSecond"], f"{name}: physicsTicksPerSecond", 1, 1000)
    _whole(doc["captureFps"], f"{name}: captureFps", 1, 240)
    _strings(doc["inputActions"], f"{name}: inputActions", unique=True)
    _bindings(doc["bindings"], root, name)
    if "routes" in doc:
        _strings(doc["routes"], f"{name}: routes", rooted=True)
    if "approvedContracts" in doc:
        _strings(doc["approvedContracts"], f"{name}: approvedContracts", rooted=True)
    _providers(doc.get("providers"), name)
    return doc


def harness_arguments(doc: dict) -> list[str]:
    """The values the Godot harness needs, and no path on this machine.

    The replay may run inside the sandbox, where the game is a copy and a path from the host
    does not exist. The harness is given the bindings themselves.
    """
    blob = json.dumps(doc["bindings"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return [f"--bindings={blob}"]


def _fail(message: str) -> None:
    raise ProjectConfigError(message)


def _text(doc: dict, field: str, name: str, *, required: bool) -> None:
    if field not in doc:
        if required:
            _fail(f"{name}: missing {field!r}")
        return
    value = doc[field]
    if not isinstance(value, str) or not value.strip() or len(value) > 40 or "\n" in value:
        _fail(f"{name}: {field} must be a short line of text")


def _toolchain(value, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        _fail(f"{name}: toolchain must be an object with \"engine\" and \"version\"")
    extra = sorted(set(value) - {"engine", "version"})
    if extra:
        _fail(f"{name}: toolchain has unknown field {extra[0]!r}; remove it")
    for field in ("engine", "version"):
        if field not in value:
            _fail(f"{name}: toolchain is missing {field!r}")
        got = value[field]
        if not isinstance(got, str) or not got.strip() or len(got) > 40 or "\n" in got:
            _fail(f"{name}: toolchain.{field} must be a short line of text")


def _whole(value, what: str, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        _fail(f"{what} must be a whole number from {low} to {high}")


def _pair(value, what: str) -> None:
    if not isinstance(value, list) or len(value) != 2:
        _fail(f"{what} must be [width, height] in pixels")
    for item in value:
        _whole(item, what, 1, 10000)


def _strings(value, what: str, *, unique: bool = False, rooted: bool = False) -> None:
    if not isinstance(value, list) or len(value) > 64:
        _fail(f"{what} must be a list of names")
    seen = set()
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > 200 or "\n" in item or "\\" in item:
            _fail(f"{what} has a name that is empty, too long or not one line")
        if rooted and (item.startswith("/") or ".." in Path(item).parts):
            _fail(f"{what} path leaves the project: {item}")
        if unique and item in seen:
            _fail(f"{what} lists {item!r} twice")
        seen.add(item)


def _res_file(value, root: Path, what: str) -> None:
    if not isinstance(value, str) or not value.startswith("res://") or value.startswith("res:///") or "\\" in value:
        _fail(f"{what} must be a res:// path inside the project, not {value!r}")
    rel = value[len("res://"):]
    parts = Path(rel).parts
    if not rel or rel.startswith("/") or ".." in parts or any(part == "" for part in parts):
        _fail(f"{what} leaves the project root: {value}")
    target = (root / rel)
    try:
        target.resolve().relative_to(root.resolve())
    except ValueError:
        _fail(f"{what} leaves the project root: {value}")
    if not target.is_file():
        _fail(f"{what} is not a file in the project: {value}")


def _bindings(value, root: Path, name: str) -> None:
    if not isinstance(value, dict) or not value or len(value) > 32:
        _fail(f"{name}: bindings must name at least one object")
    claimed: dict[tuple[str, str], str] = {}
    for role, binding in value.items():
        where = f"{name}: bindings.{role}"
        if not isinstance(role, str) or _ROLES.fullmatch(role) is None:
            _fail(f"{name}: binding role {role!r} must be a short name like \"player\"")
        if not isinstance(binding, dict):
            _fail(f"{where} must be an object")
        extra = sorted(set(binding) - _BINDING_FIELDS)
        if extra:
            _fail(f"{where} has unknown field {extra[0]!r}; a binding is a node or a group, and a texture, not a size")
        has_node, has_group = "node" in binding, "group" in binding
        if has_node and has_group:
            _fail(f"{where} has both \"node\" and \"group\"; give one of them")
        if not has_node and not has_group:
            _fail(f"{where} needs a \"node\" path or a \"group\"")
        if "texture" not in binding:
            _fail(f"{where} needs the \"texture\" the object is drawn with")
        if has_node:
            _selector(binding["node"], f"{where} node")
            _one(claimed, ("node", binding["node"]), role, where)
        else:
            _selector(binding["group"], f"{where} group")
            if "/" in binding["group"]:
                _fail(f"{where} group must be a name, not a path")
            _one(claimed, ("group", binding["group"]), role, where)
        _res_file(binding["texture"], root, f"{where} texture")


def _selector(value, what: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 200 or "\n" in value or "\\" in value:
        _fail(f"{what} must be a short path or name")
    if ".." in Path(value).parts:
        _fail(f"{what} must not contain '..'")


def _one(claimed: dict, key: tuple[str, str], role: str, where: str) -> None:
    if key in claimed:
        kind, name = key
        _fail(f"{where} uses {kind} {name!r}, which {claimed[key]!r} already uses; a binding must be unambiguous")
    claimed[key] = role


def _providers(value, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict) or len(value) > 8:
        _fail(f"{name}: providers must be an object of ref: or env: names")
    for key, item in value.items():
        if not isinstance(key, str) or _ROLES.fullmatch(key) is None:
            _fail(f"{name}: provider {key!r} must be a short name")
        if not isinstance(item, str) or _PROVIDER.fullmatch(item) is None:
            _fail(f"{name}: providers.{key} must be a ref: or env: reference, never an inline secret")
