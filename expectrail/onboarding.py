"""Inspect saved scenes and, when requested, measure clean public engine replays.

Static inspection and init do not start project scripts. --at-tick and calibrate
explicitly run the local pinned engine; neither invokes a visual model.
"""
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
            if node.get("type") in ("Sprite2D", "AnimatedSprite2D"):
                if "type" in attrs or re.search(r"^(texture|sprite_frames)\s*=", body, re.M):
                    node["images"], node["reason"] = sprite_textures(node["type"], body, textures, frames)
    visit(entry, "", ())
    return nodes, sorted(files)


def inspect(root):
    from expectrail.godot_project import configured_scene, require_gdscript
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
              "physicsTicksPerSecond": info["physicsTicksPerSecond"],
              "captureFps": next(n for n in range(min(info["physicsTicksPerSecond"],60),0,-1)
                                 if info["physicsTicksPerSecond"] % n == 0),
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
    if doc['mode'] == 'inspect':
        if len(doc['runs']) != 1 or doc['inspection'] is None or doc['calibration'] is not None or (doc['stability'] is not None):
            raise ValueError('An inspection needs one run and its measured tick only.')
        if doc['inspection']['tick'] + 1 >= src['routeTicks']:
            raise ValueError('Inspection tick is outside its replay.')
        for obj in doc['inspection']['objects']:
            if obj['role'] not in src['bindingRoles']:
                raise ValueError('Inspection contains an unbound role.')
            b = obj['screenBox']
            w, h = src['viewport']
            inside = b[2] > 0 and b[3] > 0 and (b[0] < w) and (b[1] < h)
            if obj['onScreen'] != inside:
                raise ValueError('Inspection onScreen disagrees with its measured box.')
    else:
        if len(doc['runs']) != 3 or doc['inspection'] is not None or doc['calibration'] is None or (doc['stability'] is None):
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

def runtime_setup(root, *, mode, at_tick=0, route_path=None, out=None, godot=None):
    """Read-only public-project replay diagnostics; no model, approval or tolerance tuning."""
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
    if mode == 'inspect':
        if type(at_tick) is not int or not 0 <= at_tick <= 7200:
            raise ValueError('Set --at-tick to an integer from 0 to 7200.')
        document = {'format': 'expectrail.route/v0', 'name': 'setup-inspect', 'seed': 1, 'ticks': at_tick + 2, 'events': []}
    else:
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
            for n in range(1, 2 if mode == 'inspect' else 4):
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
        report = {'format': 'expectrail.setup-report/v1', 'mode': mode, 'source': source, 'runs': runs, 'inspection': None, 'calibration': None, 'stability': None}
        if mode == 'inspect':
            row = traces[0]['rows'][at_tick]
            width, height = source['viewport']
            objects = []
            for obj in row['roleObjects']:
                box = obj['box']
                on_screen = box[2] > 0 and box[3] > 0 and (box[0] < width) and (box[1] < height)
                objects.append({'role': obj['role'], 'nodePath': obj['id'], 'screenBox': box, 'worldBox': obj['worldBox'], 'visible': obj['visible'], 'onScreen': on_screen, 'boundsSource': obj['boundsSource']})
            report['inspection'] = {'tick': at_tick, 'objects': objects}
        else:
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
    if command in ("inspect", "calibrate"):
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--godot", type=Path, help="local pinned engine; setup never downloads one")
        parser.add_argument("--out", type=Path, help="new evidence folder outside the project")
        if command == "inspect":
            parser.add_argument("--at-tick", type=int, metavar="N",
                                help="replay the config's bindings headless and report each bound object at tick N")
            parser.add_argument("--route", type=Path, help="with --at-tick: the route to replay (default: the config's first)")
        else:
            parser.add_argument("--route", type=Path, required=True, help="public clean route, relative to project or absolute")
    else:
        parser.add_argument("--adapter", choices=["godot"], default="godot")
        parser.add_argument("--dry-run", action="store_true", help="print both drafts without writing")
        parser.add_argument("--force", action="store_true", help="replace an existing project config")
    try:
        args = parser.parse_args(argv)
        root = (args.game or args.project).resolve()
        if command == "inspect" and args.route is not None and args.at_tick is None:
            raise ValueError("--route is used with --at-tick N; add --at-tick, or drop --route for the saved-scene listing")
        if command == "inspect" and args.at_tick is not None and (args.out or args.godot):
            # Evidence-writing measurement (#260): the same runtime setup as calibrate, at one tick.
            print(json.dumps(runtime_setup(root, mode=command, at_tick=args.at_tick, route_path=args.route,
                                           out=args.out, godot=args.godot), indent=2))
            return 0
        if command == "inspect" and args.at_tick is not None:
            if not 0 <= args.at_tick <= 7200:
                raise ValueError('Set --at-tick to an integer from 0 to 7200.')
            from expectrail import inspection

            doc = inspection.document(root, args.at_tick, args.route)
            print(json.dumps(doc, indent=2) if args.json else "\n".join(inspection.describe(doc)))
            return 0
        if command == 'calibrate':
            report=runtime_setup(root,mode=command,at_tick=0,
                                 route_path=args.route,out=args.out,godot=args.godot)
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
