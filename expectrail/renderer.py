"""Readiness for exact recorded answers. No model, download or selected project is run.

A matching environment is necessary provenance, not proof that every image/question is recorded.
This check never supplies an answer or changes a gate verdict. Legacy recordings remain readable,
but cannot establish renderer compatibility. CI requires complete provenance for every recording.
"""
import os
from pathlib import Path

FIELDS = ('name', 'version', 'renderer', 'device')
FIX = ('Re-record on this rendering environment (only Sean dispatches the shared recordings), or '
       'select live vision in the project config and set MODEL_API_KEY and EXPECTRAIL_SAM_USD_CAP '
       'in the verifier environment. Adding a key alone does not replace a configured recording.')


def describe(environment):
    if not environment:
        return 'unknown rendering environment'
    return '; '.join(f'{key}: {environment.get(key) or "unknown"}' for key in FIELDS)


def probed(engine, display, drawing):
    """Combine the existing doctor's version/display/empty-project probes."""
    for check in (engine, display, drawing):
        if check.status != 'ok':
            return {'environment': None, 'reason': check.id + ': ' + check.found, 'fix': check.fix}
    environment = {**(engine.environment or {}), **(drawing.environment or {})}
    if not all(environment.get(k) for k in FIELDS):
        return {'environment': None, 'reason': 'renderer: the probe did not report a complete rendering environment',
                'fix': 'Run expectrail doctor and check the engine and display installation.'}
    return {'environment': environment, 'reason': None, 'fix': None}


def machine():
    from expectrail import doctor
    engine, path = doctor.godot(False)
    shown = doctor.display()
    return probed(engine, shown, doctor.opengl(path, shown))


def compare(recording, environment):
    """Strict provenance comparison, independent of exact image matching at verdict time."""
    environments = recording.get('renderingEnvironments')
    if not environments or any(not isinstance(e, dict) or not all(e.get(k) for k in FIELDS)
                               for e in environments):
        return 'unknown'
    if not environment or not all(environment.get(k) for k in FIELDS):
        return 'unavailable'
    return 'match' if all(all(e[k] == environment[k] for k in FIELDS) for e in environments) else 'mismatch'


def recording_report(recording, environment):
    status = compare(recording, environment)
    recorded = ' | '.join(describe(e) for e in recording.get('renderingEnvironments', [])) or 'not recorded'
    message = f'This machine: {describe(environment)}. Recording: {recorded}.'
    if status == 'match':
        message += ' Rendering environments match. Images and questions must still match exactly.'
    elif status == 'mismatch':
        message += (' Rendering environments differ. Expect needs-review: changed images will not match recorded '
                    'answers. An engine failure can still reject the change.')
    elif status == 'unknown':
        message += (' The recording does not identify every rendering environment; compatibility cannot be checked. '
                    'Unmatched images get needs-review, never a guessed answer.')
    else:
        message += ' No renderer is available to compare. Fix the engine/display before running.'
    return {'status': status, 'message': message, 'warning': status != 'match',
            'fix': None if status == 'match' else FIX}


def project_report(root, probe=None):
    """Read only the configured recording, using the same bounded, no-symlink reader as the job."""
    from expectrail import project_job, recorded
    from expectrail.gate import record
    from expectrail.orchestrator.request import RequestError
    probe = machine() if probe is None else probe
    environment = probe['environment']
    name = None
    try:
        config = project_job.read_config(root)
        settings = project_job.visual_settings(config)
        if settings is None:
            return {'recording': None, 'status': 'live', 'warning': False, 'fix': None,
                    'message': f'This machine: {describe(environment)}. No recorded vision selected; '
                               'live vision requires MODEL_API_KEY and EXPECTRAIL_SAM_USD_CAP.'}
        name = settings['recording'].removeprefix('project/')
        doc = record.strict_loads(project_job.regular(root, name, recorded.MAX_BYTES).decode('utf-8'))
        recorded.check(doc)
        report = recording_report(doc, environment)
    except (RequestError, OSError, ValueError, UnicodeError):
        # Do not echo file contents, arbitrary parser exceptions or credential values.
        report = {'status': 'unreadable', 'warning': True,
                  'message': f'This machine: {describe(environment)}. The configured recording could not be read safely.',
                  'fix': 'Check the project config and use a valid vision recording in a regular file inside the project.'}
    if environment is None:
        report['message'] += ' ' + (probe['reason'] or 'Renderer unavailable.')
        report['fix'] = (probe['fix'] or 'Run expectrail doctor.') + ' ' + (report['fix'] or '')
    return {'recording': name, **report}


def drift_problems(root, environment):
    """All public sample/outside recording files, never any held-out material."""
    from expectrail import recorded
    root = Path(root)
    paths = sorted((root / 'docs/run-it/vision').glob('*.json'))
    # Walk only the public recordings tree. Prune links and prohibited/private names before descent.
    outside = root / 'tests/outside/recordings'
    for directory, dirs, files in os.walk(outside, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith('fresh-') and 'heldout' not in d.lower()
                         and not (Path(directory) / d).is_symlink())
        for filename in sorted(files):
            if filename.endswith('.json'):
                path = Path(directory) / filename
                if path.is_symlink():
                    paths.append(path)
                    continue
                # Calibration/summary JSON is not a recording. Bad JSON in a recording is a failure.
                try:
                    from expectrail.gate import record
                    doc = record.strict_loads(record.read_bytes_capped(path, recorded.MAX_BYTES, 'recording').decode('utf-8'))
                    if isinstance(doc, dict) and doc.get('format') == recorded.FORMAT:
                        paths.append(path)
                    elif filename == 'vision-recording.json':
                        paths.append(path)
                except (OSError, ValueError):
                    paths.append(path)
    if not paths:
        return ['No checked-in vision recordings found; renderer drift was not checked.']
    problems = []
    for path in paths:
        name = path.relative_to(root).as_posix()
        try:
            if path.is_symlink():
                raise ValueError('link')
            report = recording_report(recorded.read_recording(path), environment)
        except (OSError, ValueError):
            problems.append(f'{name}: recording unreadable; this machine: {describe(environment)}')
            continue
        if report['warning']:
            problems.append(f'{name}: {report["message"]} {report["fix"]}')
    return problems
