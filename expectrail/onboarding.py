"""Inspect saved Godot text scenes. No game, editor, or project script is started."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

from expectrail import project_config, route

# Text scene sections and their quoted header attributes. Ignore unrelated properties
# (including scripts); resolve resource IDs only in the scene that declares them.
HEADER = re.compile(r"^\[(\w+)([^\n]*)\]\s*$", re.M)
ATTR = re.compile(r'(\w+)=("(?:\\.|[^"\\])*")')
EXT = re.compile(r'ExtResource\("([^"]+)"\)')


def resource(root, uri):
    if not isinstance(uri, str) or not uri.startswith("res://"):
        raise ValueError(f"Use a res:// path in the project for {uri!r}.")
    path = (root / uri[6:]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"Restore {uri} inside the project or correct the scene reference.")
    return path


def entry_scene(root, uri):
    if not isinstance(uri, str):
        raise ValueError("Set application/run/main_scene to a Godot scene path.")
    if not uri.startswith("uid://"):
        return uri
    matches = []
    for directory, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in names:
            if name.endswith(".tscn"):
                path = Path(directory, name)
                if path.resolve().is_relative_to(root):
                    with path.open(encoding="utf-8-sig") as stream:
                        if dict(ATTR.findall(stream.readline())).get("uid") == json.dumps(uri):
                            matches.append("res://" + path.relative_to(root).as_posix())
    if len(matches) != 1:
        raise ValueError(f"Set application/run/main_scene to a unique res:// text scene; {uri} matched {len(matches)}.")
    return matches[0]


def property_value(body, key):
    match = re.search(r"^" + re.escape(key) + r"\s*=\s*(.*)$", body, re.M)
    return match[1].strip() if match else None


def sprite_textures(kind, body, external, frames):
    """Return all referenced frame images, or a reason that a single image cannot be bound."""
    if kind == "Sprite2D":
        values = [property_value(body, "texture")]
    else:
        ref = re.fullmatch(r'SubResource\("([^"]+)"\)', property_value(body, "sprite_frames") or "")
        if not ref or ref[1] not in frames:
            return [], "the SpriteFrames resource is external, missing or assigned at runtime"
        # Godot arrays span lines and a frame list ends before the enclosing animation list.
        data = next((record.partition("=")[2] for record in route._records(frames[ref[1]])
                     if record.partition("=")[0].strip() == "animations"), "")
        try:
            animations = json.loads(EXT.sub(lambda m: json.dumps(m[0]), data).replace('&"', '"'))
            values = [f["texture"] for a in animations for f in a["frames"]]
        except (ValueError, KeyError, TypeError):
            return [], "the saved frame collection cannot be read as external texture references"
    paths = set()
    incomplete = not values
    for value in values:
        ref = EXT.fullmatch(value) if isinstance(value, str) else None
        if ref and ref[1] in external:
            paths.add(external[ref[1]])
        else:
            incomplete = True
    if incomplete:
        reason = "a texture is missing or has no direct external file reference"
    elif len(paths) > 1:
        reason = "multiple frame textures are drawn; the binding takes one representative image"
    else:
        reason = None
    return sorted(paths), reason


def scene_nodes(root, entry):
    nodes, files = {}, set()

    @lru_cache(maxsize=None)
    def read(uri):
        path = resource(root, uri)
        if path.suffix != ".tscn":
            raise ValueError(f"Save {uri} as a text scene (.tscn) so inspect can read its nodes.")
        text = path.read_text(encoding="utf-8-sig")
        headers = list(HEADER.finditer(text))
        return [(m[1], m[2], {k: json.loads(v) for k, v in ATTR.findall(m[2])},
                 text[m.end():headers[i + 1].start() if i + 1 < len(headers) else len(text)])
                for i, m in enumerate(headers)]

    def visit(uri, prefix, parents):
        if uri in parents or len(parents) >= 64 or len(nodes) > 50000:
            raise ValueError(f"Check the nested scene references at {uri}: circular or too large.")
        files.add(uri)
        sections = read(uri)
        external = {a["id"]: a["path"] for tag, _, a, _ in sections if tag == "ext_resource"}
        textures = {a["id"]: a["path"] for tag, _, a, _ in sections
                    if tag == "ext_resource" and a.get("type") == "Texture2D"}
        frames = {a["id"]: body for tag, _, a, body in sections if tag == "sub_resource" and a.get("type") == "SpriteFrames"}
        for tag, header, attrs, body in sections:
            if tag != "node":
                continue
            parent = attrs.get("parent")
            path = prefix if parent is None else "/".join(
                p for p in (prefix, parent, attrs["name"]) if p not in ("", "."))
            instance = re.search(r'\binstance=ExtResource\("([^"]+)"\)', header)
            if instance:
                visit(external[instance[1]], path, parents + (uri,))
            node = nodes.setdefault(path, {})
            if "type" in attrs:
                node["type"] = attrs["type"]
            if parent is None:
                node.setdefault("name", attrs["name"])
            else:
                node["name"] = attrs["name"]
            if node.get("type") in ("Sprite2D", "AnimatedSprite2D"):
                if "type" in attrs or re.search(r"^(texture|sprite_frames)\s*=", body, re.M):
                    node["images"], node["reason"] = sprite_textures(node["type"], body, textures, frames)
    visit(entry, "", ())
    return nodes, sorted(files)


def inspect(root):
    settings_file = resource(root, "res://project.godot")
    text = settings_file.read_text(encoding="utf-8-sig")
    actions, rate, fallback = route.authored_input_map(text)
    settings, section = {}, ""
    for record in route._records(text):
        if record.startswith("["):
            section = record[1:-1]
        elif "=" in record and section in ("application", "display"):
            key, _, value = record.partition("=")
            settings[section + "/" + key.strip()] = value.strip()
    entry = entry_scene(root, json.loads(settings.get("application/run/main_scene", '""')))
    if not entry:
        raise ValueError("Set application/run/main_scene in project.godot to the game's starting scene.")
    nodes, scenes = scene_nodes(root, entry)
    bodies = [p for p, n in nodes.items() if n.get("type") in ("CharacterBody2D", "RigidBody2D", "Area2D")]
    named = [p for p in bodies if nodes[p]["name"].casefold() == "player"]
    players = named or bodies
    textures, problems = set(), []
    if len(players) == 1:
        player = players[0]
        for path, node in nodes.items():
            if "images" not in node:
                continue
            # A sprite belongs to its nearest physics-body ancestor, including the scene root.
            owner = path
            while owner and owner not in bodies:
                owner = owner.rpartition("/")[0]
            if owner != player:
                continue
            prop = "sprite_frames" if node["type"] == "AnimatedSprite2D" else "texture"
            reason = node["reason"]
            for image in node["images"]:
                try:
                    resource(root, image)
                    textures.add(image)
                except ValueError as exc:
                    problems.append(f"{path}.{prop}: {exc}")
            if reason:
                problems.append(f"{path}.{prop}: {reason}.")
        if not textures and not problems:
            problems.append(f"{player or '.'}: no saved sprite texture found.")
        if len(textures) > 1 and not problems:
            problems.append(f"{player or '.'}: the player has several sprite images.")
        if problems:
            problems.append("Supply one image from the game as a res:// path in bindings.player.texture.")
    else:
        problems.append("Supply the player node path and its res:// image in bindings.player; "
                        "the starting scene has no unique player.")

    def paths(kind):
        return [p or "." for p, n in nodes.items() if n.get("type") == kind]
    return {"entryScene": entry, "scenes": scenes, "players": [p or "." for p in players],
            "textures": sorted(textures), "unresolvedBindings": problems, "cameras": paths("Camera2D"), "groundLayers": paths("TileMapLayer"),
            "platformBodies": paths("StaticBody2D") + paths("AnimatableBody2D"),
            "otherCharacters": [p for p in paths("CharacterBody2D") if p not in [s or "." for s in players]],
            "actions": actions, "builtInActions": fallback, "physicsTicksPerSecond": rate,
            "viewport": [int(settings.get(f"display/window/size/viewport_{axis}", default))
                         for axis, default in (("width", 1152), ("height", 648))]}


def describe(report):
    def listed(key):
        return ", ".join(report[key]) or "none found"
    print(f"Starting scene: {report['entryScene']}")
    print("Player candidates:", listed("players"))
    print("Player texture candidates:", listed("textures"))
    for problem in report["unresolvedBindings"]:
        print(problem)
    print("Input actions" + (" (built-in fallback)" if report["builtInActions"] else "") + ":", listed("actions"))
    print("Cameras:", listed("cameras"))
    print("Ground layers:", listed("groundLayers"))
    print("Static or animated platform bodies:", listed("platformBodies"))
    print("Viewport:", *report["viewport"], "pixels. Physics ticks per second:", report["physicsTicksPerSecond"])
    if report["otherCharacters"]:
        print("Other character bodies (possible moving surfaces):", listed("otherCharacters"))
    if not report["unresolvedBindings"]:
        print("The player and input map can be bound for a movement replay.")
    if report["groundLayers"] or report["platformBodies"] or report["otherCharacters"]:
        print("Ground candidates found. Replay to check which surfaces actually support the player.")
    else:
        print("No authored ground layer or platform body found. A ground check needs other evidence.")
    print("This reads saved scenes. Runtime visibility, input coverage and replay stability need a replay.")


def proposal(root, info):
    if any(len(action) > 64 for action in info["actions"]):
        raise ValueError("Shorten input action names to 64 characters for the project config.")
    draft = route.make_route(info["actions"], info["physicsTicksPerSecond"])
    draft.update(name="draft-first-route", description="Draft from the input map. Review the actions and replay before use.")
    filename = "routes/draft-first-" + hashlib.sha256(encode(draft)).hexdigest()[:16] + ".json"
    config = {"format": project_config.FORMAT, "adapter": "godot", "draft": True,
              "entryScene": info["entryScene"], "viewport": info["viewport"],
              "physicsTicksPerSecond": info["physicsTicksPerSecond"], "captureFps": 60,
              "bindings": {},
              "inputActions": info["actions"], "routes": [filename]}
    if len(info["players"]) == 1:
        config["bindings"]["player"] = {"node": info["players"][0]}
    if info["unresolvedBindings"]:
        return {"config": config, "route": draft, "unresolvedBindings": info["unresolvedBindings"],
                "textureCandidates": info["textures"], "playerCandidates": info["players"], "draft": True}
    config["bindings"]["player"]["texture"] = info["textures"][0]
    return {"config": project_config.validate(config, root), "route": draft}


def encode(doc):
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode()


def publish(root, docs, force):
    live = root / project_config.FILENAME
    config = root / "expectrail.project.draft.json" if "unresolvedBindings" in docs else live
    dest = root / docs["config"]["routes"][0]
    if config.is_symlink() or dest.parent.is_symlink() or dest.is_symlink():
        raise ValueError("Use ordinary files and a routes directory inside the game; an output is a symbolic link.")
    if live != config and (live.exists() or live.is_symlink()) and not force:
        raise ValueError(f"{live.name} exists. Review it or use --force to write a separate review draft.")
    if config.exists() and not force:
        raise ValueError(f"{config.name} already exists. Review it or use --force to replace it.")
    if config.exists() and not config.is_file():
        raise ValueError(f"Move the directory at {config.name} before running init.")
    # Publish a complete, immutable route first. Replacing the config then switches
    # between complete pairs, including on retry and simultaneous init calls.
    with tempfile.TemporaryDirectory(dir=root, prefix=".expectrail-init-") as tmp:
        staged = Path(tmp)
        payload = docs["config"] if config == live else {k: v for k, v in docs.items() if k != "route"}
        (staged / "config").write_bytes(encode(payload))
        (staged / "route").write_bytes(encode(docs["route"]))
        dest.parent.mkdir(exist_ok=True)
        try:
            os.link(staged / "route", dest)
        except FileExistsError:
            if dest.is_symlink() or dest.read_bytes() != encode(docs["route"]):
                raise ValueError(f"Move the conflicting route at {dest}. Its contents were preserved.")
        if force:
            os.replace(staged / "config", config)
        else:
            os.link(staged / "config", config)
    return config.name


def main(command, argv):
    parser = route.Parser(prog=f"expectrail {command}", description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("game", type=Path, nargs="?")
    group.add_argument("--project", type=Path)
    if command == "inspect":
        parser.add_argument("--json", action="store_true")
    else:
        parser.add_argument("--adapter", choices=["godot"], default="godot")
        parser.add_argument("--dry-run", action="store_true", help="print both drafts without writing")
        parser.add_argument("--force", action="store_true", help="replace an existing project config")
    try:
        args = parser.parse_args(argv)
        root = (args.game or args.project).resolve()
        info = inspect(root)
        if command == "inspect":
            if args.json:
                print(json.dumps(info, indent=2))
            else:
                describe(info)
        else:
            docs = proposal(root, info)
            if args.dry_run:
                print(json.dumps(docs, indent=2))
            else:
                filename = publish(root, docs, args.force)
                print(f"Wrote draft {filename} and draft {docs['config']['routes'][0]}.")
                if "unresolvedBindings" in docs:
                    for problem in docs["unresolvedBindings"]:
                        print(problem)
                    print("Complete the config object in the review draft, then save that object alone "
                          "as expectrail.project.json. Existing active bindings were preserved.")
                print(f"Review these bindings offline with expectrail onboard --project GAME --source {filename} "
                      "(use this game folder for GAME).")
                print("Replay on a clean game and choose the checks to approve.")
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"expectrail {command}: {exc}", file=sys.stderr)
        return 5
