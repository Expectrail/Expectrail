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


DEFAULT_VIEWPORT = (1152, 648)  # Godot 4's display/window/size/viewport_* when unset
DEFAULT_TICKS = 60  # Godot 4's physics/common/physics_ticks_per_second when unset
_SETTINGS = {
    ("display", "window/size/viewport_width"): (1, 16384),
    ("display", "window/size/viewport_height"): (1, 16384),
    ("physics", "common/physics_ticks_per_second"): (1, 1000),
}


class SettingsMismatch(ValueError):
    """The config and the game's project.godot disagree, or the game's setting cannot be read."""


def declared_settings(root: Path) -> tuple[list[int], int]:
    """The logical viewport and physics tick rate the game's project.godot declares.

    Only the base keys count: a feature override such as ``viewport_width.mobile`` applies on other
    platforms, not to this replay. A value that is present and not a plain whole number in range,
    or a key given twice, is refused rather than replaced by a default.
    """
    from expectrail.route import _records

    path = Path(root)/'project.godot'
    try:
        text = path.read_text(encoding='utf-8-sig')
    except (OSError, UnicodeDecodeError) as exc:
        raise SettingsMismatch(f'cannot read project.godot to compare with the config: {exc}. '
                               'No game was started.') from exc
    found, section = {}, ''
    for record in _records(text):
        if record.startswith('[') and record.endswith(']'):
            section = record[1:-1].strip()
            continue
        key, eq, value = record.partition('=')
        key = (section, key.strip())
        if not eq or key not in _SETTINGS:
            continue
        name = '/'.join(key)
        if key in found:
            raise SettingsMismatch(f'project.godot sets {name} more than once; keep one. No game was started.')
        low, high = _SETTINGS[key]
        value = value.strip()
        if not re.fullmatch('[0-9]+', value) or not low <= int(value) <= high:
            raise SettingsMismatch(f'project.godot sets {name} to {value!r}; expected a whole number from '
                                   f'{low} to {high}. No game was started.')
        found[key] = int(value)
    viewport = [found.get(('display', f'window/size/viewport_{axis}'), default)
                for axis, default in zip(('width', 'height'), DEFAULT_VIEWPORT)]
    return viewport, found.get(('physics', 'common/physics_ticks_per_second'), DEFAULT_TICKS)


def require_declared_settings(root: Path, config: dict | None, *, changed: bool = False) -> None:
    """Refuse a Godot config whose viewport or tick rate is not the game's own.

    The replay runs with what project.godot declares, so a config that says otherwise would be kept
    as metadata that nothing checks. ``changed`` says the folder is the copy with the change under
    test applied, so the message can say the change moved the setting.
    """
    if config is None or config.get('adapter', 'godot') != 'godot':
        return
    viewport, ticks = declared_settings(root)
    where = 'after the change under test, project.godot' if changed else "the game's project.godot"
    problems = []
    if list(config['viewport']) != viewport:
        problems.append(f'viewport is {list(config["viewport"])}, but {where} declares {viewport} '
                        '(display/window/size/viewport_width and viewport_height)')
    if config['physicsTicksPerSecond'] != ticks:
        problems.append(f'physicsTicksPerSecond is {config["physicsTicksPerSecond"]}, but {where} declares '
                        f'{ticks} (physics/common/physics_ticks_per_second)')
    if problems:
        raise SettingsMismatch('expectrail.project.json: ' + '; '.join(problems) +
                               '. Make the config and the game agree. No game was started.')


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
