"""One configured-project request path for the CLI and the local app.

The base config chooses policy. Snapshots keep the existing gate's folder-based interface:
unchanged game trees under project/, selected policy bytes under routes/ and specs/.
No check is approved here, and no observer rule is replaced.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile

from harness import tree
from expectrail import project_config
from expectrail.gate import record, verify
from expectrail.orchestrator import request


def read_config(root):
    root = Path(root).resolve()
    try:
        data = regular(root, project_config.FILENAME, 65536)
        return project_config.validate(record.strict_loads(data.decode('utf-8')), root)
    except (ValueError, OSError) as exc:
        guidance = 'Use expectrail init to draft a config, then review it.'
        if not os.path.lexists(root / project_config.FILENAME):
            guidance = pending_guidance(root) or guidance
        raise request.RequestError(f'Project config: {exc}. {guidance}') from exc


def pending_guidance(root):
    from expectrail.onboard import PENDING

    path = root / PENDING
    if not os.path.lexists(path):
        return None
    invalid = f'Check that {PENDING} is a regular, readable init review draft inside the project.'
    if path.is_symlink() or not path.is_file():
        return invalid
    try:
        doc = record.strict_loads(regular(root, PENDING, 65536).decode('utf-8'))
    except (ValueError, OSError):
        return invalid
    if not isinstance(doc, dict) or doc.get('draft') is not True:
        return invalid
    config = doc.get('config')
    problems = doc.get('unresolvedBindings')
    if (not isinstance(config, dict) or config.get('format') != project_config.FORMAT
            or config.get('draft') is not True or config.get('approvedContracts')
            or not isinstance(problems, list) or not problems or not all(isinstance(p, str) for p in problems)):
        return invalid
    step = 'Resolve the choices listed in unresolvedBindings.'
    if any('bindings.player.texture' in problem for problem in problems):
        step += ' Choose a representative game image for bindings.player.texture (a res:// path).'
    return f'Open this folder in the local app and choose Check folders to review {PENDING}. {step}'


def regular(root, relative, cap):
    verify.safe_relative(relative, 'a configured file')
    root = Path(root).resolve()
    path = root / relative
    for part in [path, *path.parents]:
        if part == root:
            break
        if part.is_symlink():
            raise request.RequestError(f'Configured file {relative} is a symlink; use a regular file inside the project')
    if not path.resolve().is_relative_to(root):
        raise request.RequestError(f'Configured file {relative} leaves the project')
    return record.read_bytes_capped(path, cap, relative)


def selection(root, config):
    """Use the gate's route matcher; refuse unreadable or linked selections, never omit them."""
    unlisted = set()
    patterns = config.get('routes', [])
    for pattern in patterns:
        verify.safe_relative(pattern, 'a configured route', glob=True)
    files, links, outside = verify.match_routes(root, patterns, unlisted)
    if links or outside or unlisted:
        raise request.RequestError('Configured routes include a link, an outside path or an unreadable folder')
    return ([p.relative_to(root).as_posix() for p in sorted(files)],
            list(config.get('approvedContracts', [])))


def copy_policy(root, destination, selected, *, required=True):
    for group, names, cap in [('routes', selected[0], verify.ROUTE_CAP),
                              ('specs', selected[1], verify.SPEC_CAP)]:
        folder = destination / group
        folder.mkdir(parents=True, exist_ok=True)
        for i, name in enumerate(names):
            if not required and not (root / name).exists():
                continue  # The gate records a removed head policy file as changed.
            data = regular(root, name, cap)
            # Stable names also work for contracts in several folders or sharing a basename.
            (folder / f'{i:03d}.json').write_bytes(data)


def visual_settings(config):
    providers = config.get('providers', {})
    vision = providers.get('vision')
    calibration = providers.get('vision-calibration')
    if vision is None and calibration is None:
        return None
    if vision == 'env:MODEL_API_KEY' and calibration is None:
        return None  # The normal observer still requires the environment's spending cap.
    if not all(isinstance(v, str) and v.startswith('ref:') for v in (vision, calibration)):
        raise request.RequestError('Recorded vision needs providers.vision and providers.vision-calibration as ref: files; '
                                   'live vision uses env:MODEL_API_KEY and EXPECTRAIL_SAM_USD_CAP')
    result = {'type': 'anchored-recorded'}
    for field, value in [('recording', vision), ('calibration', calibration)]:
        relative = verify.safe_relative(value[4:], f'providers.{field}')
        result[field] = 'project/' + relative
    return result


def inspect(root):
    root = Path(root).expanduser().resolve()
    config = read_config(root)
    selected = selection(root, config)
    visual = visual_settings(config)
    with tempfile.TemporaryDirectory(prefix='expectrail-config-check-') as tmp:
        policy = Path(tmp)
        copy_policy(root, policy, selected)
        checks = verify.read_checks(policy, 'specs', ['routes/*.json'])
    help_text = []
    if config.get('draft'):
        help_text.append('This config is a draft. Review its bindings; it cannot give an accept.')
    if not checks.routes:
        help_text.append('No usable routes: name route files in the config routes list.')
    if not checks.specs:
        help_text.append('No approved checks: name existing checks in approvedContracts. A person must approve them.')
    if visual:
        help_text.append('Vision uses saved answers only; an unmatched image and question needs review.')
    else:
        help_text.append('Vision needs MODEL_API_KEY and EXPECTRAIL_SAM_USD_CAP. No key is entered on this page.')
    from harness.adapters import get
    return {'folder': str(root), 'godot': config['adapter'] == 'godot' and get('godot').is_project(root),
            'adapter': config['adapter'], 'version': config.get('toolchain', {}).get('version', config.get('version')),
            'routes': len(checks.routes), 'checks': len(checks.specs), 'drafts': checks.drafts,
            'routeNames': [r[0] for r in checks.routes], 'checkNames': [s['id'] for s in checks.specs],
            'configDraft': config.get('draft', False), 'problems': checks.problems, 'help': ' '.join(help_text)}


def prepare(store, head, base=None, **options):
    """Snapshot a configured project, returning a normal request for the normal worker."""
    head = Path(head).expanduser().resolve()
    base = Path(base).expanduser().resolve() if base is not None else None
    for folder in (head, base):
        if folder is not None and store.root.resolve().is_relative_to(folder):
            raise request.RequestError('The job store must be outside both project folders')
    original = base or head
    config = read_config(original)
    selected = selection(original, config)
    # Check the source paths before tree.copy materializes internal links. Inspection and
    # submission must refuse the same linked policy files, not change meaning during copying.
    for folder in (head, base):
        if folder is None:
            continue
        for names, cap in ((selected[0], verify.ROUTE_CAP), (selected[1], verify.SPEC_CAP)):
            for name in names:
                if folder == original or (folder / name).exists() or (folder / name).is_symlink():
                    regular(folder, name, cap)
    store.root.mkdir(parents=True, exist_ok=True)
    pair = Path(tempfile.mkdtemp(prefix='project-', dir=store.root))
    try:
        for side, source in [('head', head), ('base', base)]:
            if source is not None:
                tree.copy(source, pair / side / 'project', within=source, skip=tree.GODOT_SKIP)
        source = pair / ('base' if base is not None else 'head') / 'project'
        config = read_config(source)
        if config['adapter'] != 'godot':
            raise request.RequestError('Configured-project verification currently supports Godot')
        selected = selection(source, config)
        for side, original in [('head', head), ('base', base)]:
            if original is not None:
                copy_policy(pair / side / 'project', pair / side, selected,
                            required=(side == 'base' or base is None))
        doc = request.build(adapter=config['adapter'], head=pair / 'head',
                            base=pair / 'base' if base is not None else None, game='project',
                            routes=['routes/*.json'], specs='specs', **options)
        visual = visual_settings(config)
        if visual is not None:
            doc['project']['visual'] = visual
        request.check(doc)
        return doc
    except Exception:
        shutil.rmtree(pair)
        raise


def observer(doc):
    """Resolve only the base's recorded observer. Never fall back to a paid provider."""
    from expectrail import anchored, recorded
    from agents.sam_observations import SamError, sha256_bytes

    root = Path((doc['base'] or doc['head'])['checkout'])
    settings = doc['project']['visual']
    recording = record.strict_loads(regular(root, settings['recording'], recorded.MAX_BYTES).decode('utf-8'))
    calibration = record.strict_loads(regular(root, settings['calibration'], 4 * 1024 * 1024).decode('utf-8'))

    class ExactAnswers(recorded.RecordedClient):
        def _answer(self, kind, png, prompt):
            try:
                return super()._answer(kind, png, prompt)
            except SamError as exc:
                if exc.kind == 'not-recorded':
                    print('Recorded vision has no answer: ' + json.dumps({
                        'kind': kind, 'frame': Path(png).name, 'frameSha256': sha256_bytes(Path(png)),
                        'prompt': prompt}, sort_keys=True), flush=True)
                raise

    # Keep the recorded-image diagnosis (#515): which environment the recording was made under.
    return recorded.with_recorded_diagnostics(
        anchored.AnchoredObserver(ExactAnswers(recording), anchored.check_calibration(calibration)))
