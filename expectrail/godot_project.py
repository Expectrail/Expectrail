"""Static Godot project support checks shared by onboarding, doctor and replay.

No engine, project script, image library or model is loaded. This is a support
boundary, not a security sandbox: projects carrying C# sources need .NET support
that the current replay/import path does not provide.
"""
from __future__ import annotations

import json
from pathlib import Path
import re


class UnsupportedProject(ValueError):
    pass


def require_gdscript(root: Path, config: dict | None = None, *, within: Path | None = None) -> None:
    from harness import tree
    from expectrail.route import _records

    root = Path(root)
    files = tree.files(root, within=within, skip=tree.GODOT_SKIP)
    names = [name for name, _ in files]
    detected = None
    # Prefer the build declaration over an arbitrary script when both exist.
    for suffix in ('.csproj', '.cs'):
        found = next((name for name in names if name.casefold().endswith(suffix)), None)
        if found:
            detected = json.dumps(found, ensure_ascii=True)
            break
    if detected is None:
        for name, path in files:
            if path.suffix not in ('.tscn', '.tres'):
                continue
            for item in _records(path.read_text(encoding='utf-8-sig')):
                if not item.startswith('[ext_resource '):
                    continue
                attrs = {k: json.loads(v) for k, v in
                         re.findall(r'(\w+)=("(?:\\.|[^"\\])*")', item)}
                if attrs.get('type') in ('Script', 'CSharpScript') and attrs.get('path', '').casefold().endswith('.cs'):
                    detected = f'{json.dumps(name)} referencing C# script {json.dumps(attrs["path"])}'
                    break
            if detected:
                break
    if detected is None:
        section = ''
        for item in _records((root/'project.godot').read_text(encoding='utf-8-sig')):
            if item.startswith('['):
                section = item[1:-1]
                if section == 'dotnet':
                    detected = 'project.godot [dotnet] settings'
                    break
            elif section == 'application' and '=' in item:
                key, _, value = item.partition('=')
                if key.strip() == 'config/features':
                    features = [json.loads('"'+s+'"').casefold()
                                for s in re.findall(r'"((?:\\.|[^"\\])*)"', value)]
                    if any(s in ('c#', 'mono', '.net', 'dotnet') for s in features):
                        detected = 'project.godot config/features declaring C#/.NET'
                        break
    if detected is None and config is not None:
        toolchain = config.get('toolchain', {})
        declared = ' '.join(str(toolchain.get(k, '')) for k in ('engine', 'version'))
        if re.search(r'(?i)(?:^|[^a-z])(?:mono|dotnet|c#|\.net)(?:$|[^a-z])', declared):
            detected = 'expectrail.project.json toolchain declaring Mono/.NET'
    if detected is not None:
        raise UnsupportedProject(f'Detected {detected}: this project needs Godot .NET; '
                                 'only GDScript projects are supported today. '
                                 'Use a GDScript-only project; installing a Mono/.NET binary alone '
                                 'does not add support to Expectrail. No game was started.')


def configured_scene(root: Path, config: dict | None) -> str | None:
    """Validate the selected scene also on a head receiving the base's policy."""
    if config is None:
        return None  # Preserve the unconfigured game's implicit entry exactly.
    uri = config.get('entryScene')
    if not isinstance(uri, str) or not uri.startswith('res://'):
        raise ValueError('entryScene must name a res:// text scene inside the project.')
    relative = uri[6:]
    path = Path(root)/relative
    if ('\\' in relative or '..' in Path(relative).parts or Path(relative).is_absolute()
            or not path.resolve().is_relative_to(Path(root).resolve()) or not path.is_file()):
        raise ValueError(f'entryScene {uri!r} must be an existing file inside this project; '
                         'restore the selected scene. No game was started.')
    if path.suffix != '.tscn':
        raise ValueError(f'entryScene {uri!r}: only .tscn text scenes can be inspected and replayed '
                         'through config; save the scene as .tscn. No game was started.')
    return uri
