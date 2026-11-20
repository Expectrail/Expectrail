"""Inspect saved scenes and, when requested, measure clean public engine replays.

Static inspection and init do not start project scripts. --at-tick and calibrate
explicitly run the local pinned engine; neither invokes a visual model.
"""
from __future__ import annotations

import hashlib
import json
import math
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
    # Both sides in one spelling: a project reached through a link (every temporary folder on macOS
    # is under /var, a link to /private/var) is still the same project (#378).
    root = Path(root).resolve()
    path = (root / uri[6:]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"Restore {uri} inside the project or correct the scene reference.")
    return path


def entry_scene(root, uri):
    if not isinstance(uri, str):
        raise ValueError("Set application/run/main_scene to a Godot scene path.")
    if not uri.startswith("uid://"):
        return uri
    root = Path(root).resolve()
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


SUB = re.compile(r'SubResource\("([^"]+)"\)')
RECT = re.compile(r"Rect2\(\s*([^,()]+),\s*([^,()]+),\s*([^,()]+),\s*([^,()]+)\)")


def image_size(path):
    """``[width, height]`` from a PNG file's header, or None for any other or unreadable file."""
    try:
        with open(path, "rb") as stream:
            head = stream.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    width, height = int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    return [width, height] if width and height else None


def atlas_frame(body, external):
    """``(image path, [x, y, w, h])`` of a scene-local AtlasTexture, or ``(None, reason)``."""
    ref = EXT.fullmatch(property_value(body, "atlas") or "")
    if not ref or ref[1] not in external:
        return None, ("an AtlasTexture's atlas is not an external image file in this scene; "
                      "save the atlas image as a file and reference it")
    rect = RECT.fullmatch(property_value(body, "region") or "")
    try:
        region = [float(v) for v in rect.groups()] if rect else None
    except ValueError:
        region = None
    if not region or not all(math.isfinite(v) for v in region) or region[2] <= 0 or region[3] <= 0:
        return None, f"an AtlasTexture of {external[ref[1]]} has no readable region; set its region in the editor"
    return external[ref[1]], [int(v) if v == int(v) else v for v in region]


def sprite_textures(kind, body, external, frames, atlases=None):
    """Return all referenced frame images, a reason that a single image cannot be bound, and
    the AtlasTexture regions drawn of each image (an image drawn whole has no entry)."""
    atlases = atlases or {}
    if kind == "Sprite2D":
        values = [property_value(body, "texture")]
    else:
        ref = re.fullmatch(r'SubResource\("([^"]+)"\)', property_value(body, "sprite_frames") or "")
        if not ref or ref[1] not in frames:
            return [], "the SpriteFrames resource is external, missing or assigned at runtime", {}
        # Godot arrays span lines and a frame list ends before the enclosing animation list.
        data = next((record.partition("=")[2] for record in route._records(frames[ref[1]])
                     if record.partition("=")[0].strip() == "animations"), "")
        try:
            quoted = SUB.sub(lambda m: json.dumps(m[0]), EXT.sub(lambda m: json.dumps(m[0]), data))
            animations = json.loads(quoted.replace('&"', '"'))
            values = [f["texture"] for a in animations for f in a["frames"]]
        except (ValueError, KeyError, TypeError):
            return [], "the saved frame collection cannot be read as external texture references", {}
    paths, regions, reasons = set(), {}, []
    incomplete = not values
    for value in values:
        ext = EXT.fullmatch(value) if isinstance(value, str) else None
        sub = SUB.fullmatch(value) if isinstance(value, str) else None
        if ext and ext[1] in external:
            paths.add(external[ext[1]])
        elif sub and sub[1] in atlases:
            image, region = atlas_frame(atlases[sub[1]], external)
            if image is None:
                reasons.append(region)
                continue
            paths.add(image)
            if region not in regions.setdefault(image, []):
                regions[image].append(region)
        else:
            incomplete = True
    if reasons:
        reason = reasons[0]
    elif incomplete:
        reason = "a texture is missing or has no direct external file reference"
    elif len(paths) > 1:
        reason = "multiple frame textures are drawn; the binding takes one representative image"
    else:
        reason = None
    return sorted(paths), reason, regions


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
        # Validate before building lookup tables: missing or duplicate IDs must not
        # become a bare KeyError or silently select the last resource in the scene.
        ids = {"ext_resource": set(), "sub_resource": set()}
        required = {"ext_resource": ("id", "path"), "sub_resource": ("id",), "node": ("name",)}
        for tag, _, attrs, _ in sections:
            for field in required.get(tag, ()):
                if not attrs.get(field):
                    raise ValueError(f"{uri}: {tag} is missing {field}. Fix its saved scene header.")
            if tag in ids:
                if attrs["id"] in ids[tag]:
                    raise ValueError(f"{uri}: duplicate {tag} id {attrs['id']!r}. "
                                     "Fix the IDs and their references in this scene.")
                ids[tag].add(attrs["id"])
        external = {a["id"]: a["path"] for tag, _, a, _ in sections if tag == "ext_resource"}
        textures = {a["id"]: a["path"] for tag, _, a, _ in sections
                    if tag == "ext_resource" and a.get("type") == "Texture2D"}
        frames = {a["id"]: body for tag, _, a, body in sections if tag == "sub_resource" and a.get("type") == "SpriteFrames"}
        atlases = {a["id"]: body for tag, _, a, body in sections if tag == "sub_resource" and a.get("type") == "AtlasTexture"}
        for tag, header, attrs, body in sections:
            if tag != "node":
                continue
            parent = attrs.get("parent")
            path = prefix if parent is None else "/".join(
                p for p in (prefix, parent, attrs["name"]) if p not in ("", "."))
            instance = re.search(r'\binstance=ExtResource\("([^"]+)"\)', header)
            if instance:
                if instance[1] not in external:
                    raise ValueError(f"{uri}: node {attrs['name']!r} has an unknown scene reference "
                                     f"{instance[1]!r}. Fix its ExtResource reference or restore that resource.")
                visit(external[instance[1]], path, parents + (uri,))
            node = nodes.setdefault(path, {})
            if "type" in attrs:
                node["type"] = attrs["type"]
            if parent is None:
                node.setdefault("name", attrs["name"])
            else:
                node["name"] = attrs["name"]
            script = EXT.fullmatch(property_value(body, "script") or "")
            if script and script[1] in external:
                node["script"] = external[script[1]]
            label = property_value(body, "text")
            if label and label.startswith('"'):
                try:
                    node["text"] = json.loads(label)
                except ValueError:
                    pass
            if node.get("type") in ("Sprite2D", "AnimatedSprite2D"):
                if "type" in attrs or re.search(r"^(texture|sprite_frames)\s*=", body, re.M):
                    node["images"], node["reason"], node["regions"] = sprite_textures(
                        node["type"], body, textures, frames, atlases)
    visit(entry, "", ())
    return nodes, sorted(files)


def size_text(size):
    return f"{size[0]} × {size[1]}"


def region_text(regions):
    return ", ".join(f"{size_text(r[2:])} at ({r[0]}, {r[1]})" for r in regions)


def inspect(root, player=None):
    """The saved-scene report. ``player`` is the node path the developer selected, if any:
    image suggestions then come only from the sprites that belong to that body (#666)."""
    from expectrail.godot_project import configured_scene, declared_settings, require_gdscript
    from harness.tree import TreeProblem

    root = Path(root).resolve()
    config = project_config.read_game(root)
    try:
        require_gdscript(root, config)
    except TreeProblem as exc:
        raise ValueError(f"cannot inspect project files or symbolic links: {exc}") from exc
    selected = configured_scene(root, config)
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
    entry = selected or entry_scene(root, json.loads(settings.get("application/run/main_scene", '""')))
    if not entry:
        raise ValueError("Set application/run/main_scene in project.godot to the game's starting scene.")
    nodes, scenes = scene_nodes(root, entry)
    bodies = [p for p, n in nodes.items() if n.get("type") in ("CharacterBody2D", "RigidBody2D", "Area2D")]
    asked = player
    if asked is not None:
        chosen = "" if asked == "." else asked
        if chosen not in bodies:
            what = (f"{asked!r} is not in the starting scene" if chosen not in nodes
                    else f"{asked!r} is a {nodes[chosen].get('type', 'node')}, not a physics body")
            raise ValueError(f"--player: {what}. Choose one of the physics bodies: "
                             + (", ".join(p or "." for p in bodies) or "none found") + ".")
        players = [chosen]
    else:
        named = [p for p in bodies if nodes[p]["name"].casefold() == "player"]
        players = named or bodies
    textures, problems, suggestions = set(), [], []
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
                    found = resource(root, image)
                except ValueError as exc:
                    problems.append(f"{path}.{prop}: {exc}")
                    continue
                textures.add(image)
                size, regions = image_size(found), node["regions"].get(image)
                suggestions.append({"sprite": path or ".", "property": prop, "image": image,
                                    "imageSize": size, "regions": regions})
                if not regions:
                    continue
                outside = [r for r in regions if size and (r[0] < 0 or r[1] < 0 or r[0] + r[2] > size[0]
                                                           or r[1] + r[3] > size[1])]
                source = f"{image} ({size_text(size)})" if size else f"{image} (size not read)"
                if outside:
                    problems.append(f"{path}.{prop}: an AtlasTexture region {region_text(outside)} lies outside "
                                    f"{source}; correct the region in the editor.")
                else:
                    problems.append(f"{path}.{prop}: draws regions {region_text(regions)} of {source} through an "
                                    "AtlasTexture. A binding names a whole image, so confirm this image by hand.")
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
                        "the starting scene has no unique player. Or choose one with --player NODE.")

    def paths(kind):
        return [p or "." for p, n in nodes.items() if n.get("type") == kind]
    from expectrail.input_discovery import hints
    return {"inputHints": hints(root, nodes, players, actions, fallback), "entryScene": entry, "scenes": scenes, "players": [p or "." for p in players],
            "textures": sorted(textures), "unresolvedBindings": problems, "cameras": paths("Camera2D"), "groundLayers": paths("TileMapLayer"),
            "platformBodies": paths("StaticBody2D") + paths("AnimatableBody2D"),
            "otherCharacters": [p for p in paths("CharacterBody2D") if p not in [s or "." for s in players]],
            "actions": actions, "builtInActions": fallback, "physicsTicksPerSecond": rate,
            "viewport": declared_settings(root)[0],
            **({"imageSuggestions": suggestions} if len(players) == 1 else {}),
            **({"selectedPlayer": players[0] or "."} if asked is not None else {})}


def describe(report):
    def listed(key):
        return ", ".join(report[key]) or "none found"
    print(f"Starting scene: {report['entryScene']}")
    if "selectedPlayer" in report:
        print("Selected player:", report["selectedPlayer"])
    else:
        print("Player candidates:", listed("players"))
    print("Player texture candidates:", listed("textures"))
    for s in report.get("imageSuggestions", []):
        size = size_text(s["imageSize"]) if s["imageSize"] else "size not read"
        drawn = f", regions {region_text(s['regions'])}" if s["regions"] else ", drawn whole"
        print(f"  {s['image']} ({size}){drawn}, from {s['sprite']}.{s['property']}")
    for problem in report["unresolvedBindings"]:
        print(problem)
    print("Input actions" + (" (built-in fallback)" if report["builtInActions"] else "") + ":", listed("actions"))
    h = report.get("inputHints", {})
    for pointer in h.get("pointer", []):
        print(f"No authored movement actions; {pointer['node']} reads pointer position in {pointer['script']}. "
              "Pointer steering is a candidate; replay must demonstrate movement.")
    if h.get("startControls") or h.get("menus"):
        print("Possible start/menu controls:", ", ".join(dict.fromkeys(h.get("startControls", []) + h.get("menus", []))))
        print("init and route --auto use a disposable engine probe to measure their positions and pressed connections.")
    print("Cameras:", listed("cameras"))
    print("Ground layers:", listed("groundLayers"))
    print("Static or animated platform bodies:", listed("platformBodies"))
    print("Viewport:", *report["viewport"], "pixels. Physics ticks per second:", report["physicsTicksPerSecond"])
    if report["otherCharacters"]:
        print("Other character bodies (possible moving surfaces):", listed("otherCharacters"))
    runtime = report.get("runtime")
    if runtime is not None:
        describe_runtime(report, runtime)
    if not report["unresolvedBindings"]:
        print("The player and input map can be bound for a movement replay.")
    if report["groundLayers"] or report["platformBodies"] or report["otherCharacters"] or (runtime or {}).get("groundLayers"):
        print("Ground candidates found. Replay to check which surfaces actually support the player.")
    elif runtime is not None:
        print("No ground layer or platform body found, saved or at runtime. A ground check needs other evidence.")
    else:
        print("No authored ground layer or platform body found. A ground check needs other evidence.")
    if runtime is None:
        print("This reads saved scenes. Runtime visibility, input coverage and replay stability need a replay.")
    else:
        print("Input coverage and replay stability need a replay.")


def describe_runtime(report, runtime):
    def listed(values):
        return ", ".join(values) or "none found"
    how = "in the replay sandbox" if runtime["sandboxed"] else "without the sandbox"
    print(f"Running game, after {runtime['ticks']} ticks with no input ({how}):")
    print("  Player candidates:", listed(runtime["players"]))
    if "playerImages" in runtime:
        print("  Images drawn under the player:", listed(runtime["playerImages"]))
        for line in runtime["playerDrawnWithout"]:
            print("  " + line)
    if "playerProblem" in runtime:
        print("  " + runtime["playerProblem"])
    if report.get("textureFrom") == "runtime":
        print("  The player's image comes from the running game; the saved scenes do not name it.")
    print("  Solid tile layers with tiles:", listed(runtime["groundLayers"]))
    if runtime["emptyOrNonSolidLayers"]:
        print("  Tile layers with no tiles or no collision:", listed(runtime["emptyOrNonSolidLayers"]))
    print("  Found only at runtime:", listed(runtime["onlyAtRuntime"]))
    for group, paths in runtime["groups"].items():
        print(f"  Group {group}:", listed(paths))
    for name, paths in runtime["classes"].items():
        print(f"  Class {name}:", listed(paths))
    if runtime["truncated"]:
        print("  The scene has more nodes than the scan lists; this list is incomplete.")
    print("  " + runtime["note"])


def with_runtime(root, info):
    """``info`` with a runtime scan of the game merged in (expectrail.runtime_scan)."""
    from expectrail import runtime_scan

    doc = runtime_scan.scan(root)
    nodes, _ = scene_nodes(Path(root).resolve(), info["entryScene"])
    return runtime_scan.merge(info, doc, nodes)


def proposal(root, info, *, planned_route=None):
    if any(len(action) > 64 for action in info["actions"]):
        raise ValueError("Shorten input action names to 64 characters for the project config.")
    from expectrail.input_discovery import plan, needed
    draft = plan(root, info) if planned_route is None else dict(planned_route)
    draft["name"] = "draft-first-route"
    if not needed(info):
        draft["description"] = "Draft from the input map. Review the actions and replay before use."
    filename = "routes/draft-first-" + hashlib.sha256(encode(draft)).hexdigest()[:16] + ".json"
    config = {"format": project_config.FORMAT, "adapter": "godot", "draft": True,
              "entryScene": info["entryScene"], "viewport": info["viewport"],
              "physicsTicksPerSecond": info["physicsTicksPerSecond"],
              "captureFps": next(n for n in range(min(info["physicsTicksPerSecond"],60),0,-1)
                                 if info["physicsTicksPerSecond"] % n == 0),
              "bindings": {},
              "inputActions": info["actions"], "routes": [filename]}
    if len(info["players"]) == 1:
        config["bindings"]["player"] = {"node": info["players"][0]}
    if info["unresolvedBindings"]:
        docs = {"config": config, "route": draft, "unresolvedBindings": info["unresolvedBindings"],
                "textureCandidates": info["textures"], "playerCandidates": info["players"], "draft": True}
        for key in ("selectedPlayer", "imageSuggestions"):
            if key in info:
                docs[key] = info[key]
        return docs
    config["bindings"]["player"]["texture"] = info["textures"][0]
    docs = {"config": project_config.validate(config, root), "route": draft}
    for key in ("selectedPlayer", "imageSuggestions"):
        if key in info:
            docs[key] = info[key]
    if info.get("textureFrom") == "runtime":
        docs["textureFrom"] = "runtime"
    return docs


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


def check_setup_report(doc):
    """Schema and semantic reader shared by CLI output and saved setup reports. No extras."""
    from expectrail import resources
    from expectrail.gate.record import errors
    json.dumps(doc, allow_nan=False)
    schema = json.loads((resources.ROOT / 'contracts/setup-report.v1.schema.json').read_text())
    problems = errors(doc, schema)
    if problems:
        raise ValueError('Setup report is invalid: ' + problems[0])
    src = doc['source']
    step = src['physicsTicksPerSecond'] // src['captureFps']
    if src['physicsTicksPerSecond'] % src['captureFps'] or step < 1:
        raise ValueError('Setup captureFps must divide physicsTicksPerSecond; correct the project config.')
    if len(doc['runs']) != 3 or doc['calibration'] is None or doc['stability'] is None:
        raise ValueError('A calibration needs three runs, measurements and stability.')
    from agents.unity_observations import calibrate
    data = doc['calibration']['frameMeasurements']
    if len(data) != src['routeTicks'] // step or any((r['frame'] != i or r['tick'] != (i + 1) * step - 1 for i, r in enumerate(data))):
        raise ValueError('Calibration must account for every captured frame at its actual physics tick.')
    if calibrate({}, measured=data) != doc['calibration']:
        raise ValueError('Calibration statistics disagree with their measured frames.')
    stable = doc['stability']
    if stable['identical'] != (not stable['changedTicks'] and (not stable['changedHeaders'])):
        raise ValueError('Stability disagrees with its recorded differences.')
    if stable['identical'] and len({r['traceSha256'] for r in doc['runs']}) != 1:
        raise ValueError('Identical stability requires the same complete trace digest on all three runs.')

def read_setup_report(path):
    from expectrail.contracts import strict_loads
    doc = strict_loads(Path(path).read_text(encoding='utf-8'))
    check_setup_report(doc)
    return doc

def _local_engine(explicit):
    import shutil, subprocess
    from harness.run import GODOT_VERSION, tools_dir
    choices = [Path(explicit)] if explicit else [tools_dir() / 'godot' / f'Godot_v{GODOT_VERSION}_linux.x86_64']
    if not explicit:
        choices += [Path(p) for name in ('godot', 'godot4') if (p := shutil.which(name))]
    for binary in choices:
        if not binary.is_file():
            continue
        try:
            found = subprocess.run([str(binary), '--version'], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        version = found.stdout.strip()
        wanted = GODOT_VERSION.replace('-', '.')
        if found.returncode == 0 and (version == wanted or version.startswith(wanted + '.')):
            return binary.resolve()
    raise ValueError('Use --godot PATH to an executable local Godot ' + GODOT_VERSION + ', or install the pinned engine with expectrail doctor. No engine was downloaded.')

def _runtime_config(root):
    config = project_config.read_game(root)
    if config is None:
        proposed = proposal(root, inspect(root))
        if proposed.get('unresolvedBindings'):
            raise ValueError('Set bindings.player.node/group and texture in expectrail.project.json: ' + '; '.join(proposed['unresolvedBindings']))
        config = proposed['config']
    return config

def _setup_replay(root, config, route_path, target, engine):
    import subprocess, contextlib
    from harness import run as harness
    target.mkdir(parents=True, exist_ok=True)
    try:
        with (target / 'command.log').open('w') as output, contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            replay = harness.run(route_path, target, game=root, project=config, godot=engine, capture_frames=False, fps=None)
        trace = route.read_trace(target / 'trace.json', json.loads(route_path.read_bytes())['ticks'], config['physicsTicksPerSecond'])
        if trace.get('capabilities', {}).get('roleBoxes') is not True:
            raise ValueError('No bound role geometry was logged. Use the current pinned harness and correct bindings in expectrail.project.json.')
        return (replay, trace)
    except (SystemExit, OSError, ValueError, subprocess.SubprocessError) as exc:
        detail = []
        for file in (target / 'godot.log', target / 'command.log'):
            if file.is_file() and (not file.is_symlink()):
                for line in file.read_text(errors='replace').splitlines():
                    if 'expectrail:' in line or 'bindings.' in line:
                        detail.append(line.strip()[:300])
        reason = '; '.join(dict.fromkeys(detail)) or str(exc)
        raise ValueError(f"{reason}. Fix the named binding/project setting or engine error; replay log: {target / 'godot.log'}") from exc

def _measured_frames(trace, replay):
    from agents.observations import from_trace_synthetic
    fps = replay['capture']['fps']
    step = trace['physicsTicksPerSecond'] // fps
    observed = from_trace_synthetic(trace, fps=fps)
    by_frame = {f['frame']: f for f in observed['frames']}
    result = []
    for frame in range(trace['ticks'] // step):
        tick = (frame + 1) * step - 1
        objects = by_frame.get(frame, {}).get('objects', {})
        ground = objects.get('ground', [])
        floor = trace['rows'][tick].get('onFloor')
        result.append({'frame': frame, 'tick': tick, 'playerBoxes': [d['box'] for d in objects.get('player', [])], 'coinBoxes': [d['box'] for d in objects.get('coin', [])], 'ground': ground[0]['box'][1] if len(ground) == 1 else None, 'onFloor': floor if type(floor) is bool else None})
    return result


def runtime_setup(root, *, route_path=None, out=None, godot=None):
    """Read-only public-project replay diagnostics for `calibrate`; no model, approval or tolerance
    tuning. `inspect --at-tick` has one implementation, expectrail.inspection (#604)."""
    from expectrail.contracts import digest, strict_loads
    from agents.unity_observations import calibrate
    root = Path(root).resolve()
    config = _runtime_config(root)
    if config['physicsTicksPerSecond'] % config['captureFps']:
        raise ValueError('Set captureFps in expectrail.project.json to a divisor of physicsTicksPerSecond.')
    if out is not None:
        out = Path(out).absolute()
        if out.exists() or out.is_symlink() or out.resolve() == root or (root in out.resolve().parents):
            raise ValueError('Choose a new --out folder outside the project; existing files were preserved.')
    if route_path is None:
        raise ValueError('Supply --route PATH to a clean public route JSON file.')
    candidate = Path(route_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError(f'Restore --route {candidate} as a regular public route JSON file or choose another --route.')
    try:
        from expectrail.contracts import schema
        from expectrail.gate.record import errors
        document = strict_loads(candidate.read_text(encoding='utf-8'))
        problems = errors(document, schema('route'))
        if problems:
            raise ValueError(problems[0])
        if any((e['tick'] >= document['ticks'] for e in document['events'])):
            raise ValueError('each event tick must be before the route ends')
    except (OSError, ValueError, KeyError) as exc:
        raise ValueError(f'Fix --route {candidate}: {exc}') from exc
    if document['ticks'] > 7200:
        raise ValueError('Shorten --route to at most 7200 physics ticks for setup calibration.')
    if document['ticks'] < config['physicsTicksPerSecond'] // config['captureFps']:
        raise ValueError('Extend --route to include at least one captured frame.')
    unknown = {e['action'] for e in document['events'] if 'action' in e} - set(config['inputActions'] or route.FALLBACK_ACTIONS)
    if unknown:
        raise ValueError('Add these --route actions to inputActions in expectrail.project.json or fix the route: ' + ', '.join(sorted(unknown)))
    engine = _local_engine(godot)
    with tempfile.TemporaryDirectory(prefix='expectrail-setup-') as temp:
        work = out or Path(temp)
        if out is not None:
            work.mkdir(parents=True)
        route_file = work / 'route.json'
        route_file.write_bytes(encode(document))
        (work / 'config.json').write_bytes(encode(config))
        runs = []
        traces = []
        replays = []
        try:
            for n in range(1, 4):
                replay, trace = _setup_replay(root, config, route_file, work / str(n), engine)
                runs.append({'replaySha256': digest(replay), 'traceSha256': hashlib.sha256((work / str(n) / 'trace.json').read_bytes()).hexdigest(), 'engineVersion': replay['engine']['version']})
                traces.append(trace)
                replays.append(replay)
        except ValueError as exc:
            if out is not None:
                raise
            raise route._retain_failure(work, root.parent / 'expectrail-setup', exc) from exc
        if len({r['game']['tree'] for r in replays}) != 1:
            raise ValueError('Keep the clean project unchanged between calibration replays; its tree digest changed.')
        source = {'gameTreeSha256': replays[0]['game']['tree'], 'configSha256': digest(config), 'routeSha256': digest(document), 'routeTicks': document['ticks'], 'physicsTicksPerSecond': config['physicsTicksPerSecond'], 'captureFps': config['captureFps'], 'viewport': traces[0]['viewport'], 'entryScene': config['entryScene'], 'bindingRoles': sorted(config['bindings'])}
        report = {'format': 'expectrail.setup-report/v1', 'source': source, 'runs': runs, 'calibration': None, 'stability': None}
        changed, headers = route.differences(traces)
        report['calibration'] = calibrate({}, measured=_measured_frames(traces[0], replays[0]))
        report['stability'] = {'identical': not changed and (not headers), 'changedTicks': changed, 'changedHeaders': headers}
        check_setup_report(report)
        if out is not None:
            (work / 'report.json').write_bytes(encode(report))
        return report


def main(command, argv):
    parser = route.Parser(prog=f"expectrail {command}", description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("game", type=Path, nargs="?")
    group.add_argument("--project", type=Path)
    parser.add_argument("--player", metavar="NODE",
                        help="the player's node path in the starting scene; images are suggested from its sprites only")
    if command == "inspect":
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--at-tick", type=int, metavar="N",
                            help="replay the config's bindings headless and report each bound object at tick N")
        parser.add_argument("--route", type=Path, help="with --at-tick: the route to replay (default: the config's first)")
        parser.add_argument("--runtime", action="store_true",
                            help="also start the game headless for a few ticks and list the nodes it has then")
    elif command == "calibrate":
        # inspect has one implementation, #604's expectrail.inspection (the merge guard's point 2 on
        # #601). Evidence-writing runtime setup belongs to calibrate alone.
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--godot", type=Path, help="local pinned engine; setup never downloads one")
        parser.add_argument("--out", type=Path, help="new evidence folder outside the project")
        parser.add_argument("--route", type=Path, required=True, help="public clean route, relative to project or absolute")
    else:
        parser.add_argument("--adapter", choices=["godot"], default="godot")
        parser.add_argument("--dry-run", action="store_true", help="print both drafts without writing")
        parser.add_argument("--force", action="store_true", help="replace an existing project config")
        parser.add_argument("--runtime", action="store_true",
                            help="also start the game headless for a few ticks and use what it builds in code")
    try:
        args = parser.parse_args(argv)
        root = (args.game or args.project).resolve()
        if command == "inspect" and args.route is not None and args.at_tick is None:
            raise ValueError("--route is used with --at-tick N; add --at-tick, or drop --route for the saved-scene listing")
        if command == "inspect" and args.at_tick is not None and args.runtime:
            raise ValueError("--runtime lists the nodes of the running game; --at-tick reports the bound objects. "
                             "Use one of them")
        if command == "inspect" and args.at_tick is not None and args.player is not None:
            raise ValueError("--at-tick reports the config's bindings; --player selects a node for the saved-scene "
                             "listing. Use one of them")
        if command == "inspect" and args.at_tick is not None:
            from expectrail import inspection

            doc = inspection.document(root, args.at_tick, args.route)
            print(json.dumps(doc, indent=2) if args.json else "\n".join(inspection.describe(doc)))
            return 0
        if command == 'calibrate':
            report=runtime_setup(root,route_path=args.route,out=args.out,godot=args.godot)
            if args.json:print(json.dumps(report,indent=2))
            else:
                from agents.unity_observations import calibration_line
                c = report['calibration']
                print('Engine-record calibration: ' + calibration_line(c))
                print(f"Unjudgeable frames: {c['unjudgeableRows']}; see JSON for frame, tick and reason.")
                print(f"Three complete traces identical: {report['stability']['identical']}. Engine diagnostics only; no vision or tolerance was tuned.")
            if report['stability'] is not None and not report['stability']['identical']:
                print('Fix replay nondeterminism in the clean project (seed, clock, input or camera); compare the saved differing ticks/headers.',file=sys.stderr)
                return 5
            return 0
        info = inspect(root, args.player)
        if args.runtime:
            info = with_runtime(root, info)
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
