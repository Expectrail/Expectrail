"""A loopback-only, token-authenticated front end for the existing job orchestrator."""
from __future__ import annotations

import argparse
import base64
import hashlib
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import islice
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import threading
import tempfile
import webbrowser
from urllib.parse import parse_qs, unquote, urlsplit

from expectrail import app_page, auto_fix, project_job, viewer
from expectrail.gate import record as rec
from expectrail.orchestrator import request as req, runner
from expectrail.orchestrator import commits
from expectrail.orchestrator.store import JobStore, StoreError, UnknownJob, FINAL

LIMIT = 64 * 1024
OUTCOMES = {
    'accept': 'Accept — the verifier accepted this change under the checks used.',
    'reject': 'Reject — the verifier rejected this change.',
    'needs-review': 'Needs review — the verifier could not accept this change.',
    'failed': 'Failed — verification failed. There is no verdict.',
    'cancelled': 'Cancelled — no verdict was issued.',
    'running': 'Verification is unfinished. No verdict yet.',
}


def judged_by(doc, record):
    block = doc.get('observers') or (record or {}).get('observers') or {}
    if doc['phase'] != 'completed':
        words = 'No completed judgement is recorded.'
    elif block.get('rule') == 'both':
        words = ("The engine's record and the vision model judged every check."
                 if 'visual' not in block or block['visual'] is not None else
                 'This run required both observers, but the vision model was not available. No full accept is possible.')
    else:
        words = ("Only the engine's record judged; Expectrail's rule is that an accept needs the vision model too, "
                 'so this result is diagnostic.')
        if not record and not doc.get('output'):
            words = 'No completed judgement is recorded. An accept needs the engine and the vision model too.'
    visual = block.get('visual') or {}
    if doc['phase'] == 'completed' and '(recorded ' in visual.get('provider', ''):
        words = 'The verifier used the engine and looked up vision answers in the recording. No live model was called.'
    if doc['decision'] == 'needs-review':
        diagnostics = json.dumps(doc.get('diagnostics', []))
        for name, help_text in (
            ('MODEL_API_KEY', 'the secret key from your vision model provider'),
            ('EXPECTRAIL_SAM_USD_CAP', 'the maximum amount in US dollars you allow the vision model to spend on a run'),
        ):
            if name in diagnostics:
                words += (f' Vision setup needs {name}. Ask the person who starts the app to set {name} '
                          f'to {help_text} before starting the app, then verify again.')
    return words


def field(body, name, default=None):
    value = body.get(name, default)
    if not isinstance(value, str) or not value.strip() or '\0' in value:
        raise ValueError(f'Enter {name} as text. Nothing was run.')
    return value.strip()


def execution_class(body):
    selected = body.get('executionClass', 'diagnostic')
    if not isinstance(selected, str) or selected not in req.EXECUTION_CLASSES:
        raise ValueError('Choose diagnostic or isolated execution. Nothing was run.')
    return selected


def build(body, *, inspect=False):
    head = Path(field(body, 'folder' if inspect else 'after')).expanduser()
    configured(body)
    return req.build(adapter='godot', head=head,
                     base=None if inspect else Path(field(body, 'before')).expanduser(),
                     game=field(body, 'game', '.'),
                     routes=field(body, 'routes', 'routes/*.json').replace(',', ' ').split(),
                     specs=field(body, 'specs', 'specs'), execution_class=execution_class(body))


def configured(body):
    if body.get('preset'):
        raise ValueError('Project presets are no longer used. Choose a folder with an expectrail.project.json config.')
    value = body.get('projectConfig', not any(k in body for k in ('game', 'routes', 'specs')))
    if type(value) is not bool:
        raise ValueError('projectConfig must be true or false.')
    return value


class InvalidProjectPath(ValueError):
    """The submitted path could not identify a local project folder."""


def project_folder(body, name):
    path = Path(field(body, name)).expanduser()
    if path.name == 'project.godot':
        if path.is_symlink():
            raise InvalidProjectPath(f'{path} is a symbolic link. Choose the original project.godot or its folder.')
        if path.is_file():
            return path.parent
    if path.is_dir():
        return path
    raise InvalidProjectPath(f'Choose an existing project folder or its project.godot file. Could not use {path}.')


def choose_folder():
    # Keep the GUI event loop out of the HTTP worker, including on macOS.
    script = '''
import json
import tkinter as tk
from tkinter import filedialog

root = tk.Tk()
root.withdraw()
try:
    folder = filedialog.askdirectory(parent=root, title="Choose a Godot project", mustexist=True)
    print(json.dumps(folder or None))
finally:
    root.destroy()
'''
    try:
        result = subprocess.run([sys.executable, '-I', '-c', script], capture_output=True,
                                text=True, timeout=300, check=True)
    except subprocess.TimeoutExpired as exc:
        raise ValueError('The folder chooser timed out. Open it again or enter a path.') from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError('The folder chooser needs a desktop session and Python Tk. Enter a path instead.') from exc
    return json.loads(result.stdout)


def godot_folder(folder):
    marker = folder / 'project.godot'
    return not marker.is_symlink() and marker.is_file()


def picker_path(body, side):
    if not Path(field(body, side)).expanduser().is_absolute():
        raise InvalidProjectPath('Choose a project folder or enter its full path.')
    folder = project_folder(body, side).resolve()
    if not godot_folder(folder):
        raise InvalidProjectPath('This folder has no project.godot file of its own. Choose the folder containing it.')
    return folder


def checkout_layout(folder):
    try:
        working, gitdir, common = commits.layout(folder)
        if working is None or not folder.is_relative_to(working):
            return None
        marker = working / '.git'
        if gitdir == common == marker:
            return working, common
        # A project's gitdir pointer alone cannot authorize a different checkout.
        if gitdir.parent == common / 'worktrees':
            back = os.fsdecode(commits.regular(gitdir / 'gitdir', 8192)).rstrip('\n')
            if Path(back) == marker:
                return working, common
    except (OSError, ValueError, RuntimeError):
        return None
    return None


def before_suggestion(after, layout):
    stem = after.name.removesuffix('-after')
    if stem and not stem.endswith('-before'):
        sibling = after.with_name(stem + '-before')
        if not sibling.is_symlink() and godot_folder(sibling):
            return {'folder': str(sibling), 'source': 'sibling'}
    if layout is None:
        return None
    working, common = layout
    relative = after.relative_to(working)
    registrations = common / 'worktrees'
    roots = [common.parent] if common.name == '.git' else []
    if not registrations.is_symlink() and registrations.is_dir():
        for registration in sorted(islice(registrations.iterdir(), 32)):
            if registration.is_symlink() or not registration.is_dir():
                continue
            try:
                marker = Path(os.fsdecode(commits.regular(registration / 'gitdir', 8192)).rstrip('\n'))
                if not marker.is_absolute() or marker.name != '.git' or marker.resolve() != marker:
                    continue
                _, gitdir, _ = commits.layout(marker.parent)
                if gitdir == registration:
                    roots.append(marker.parent)
            except (OSError, ValueError, RuntimeError):
                continue
    for root in roots:
        candidate = root / relative
        try:
            if (root != working and candidate.resolve() == candidate
                    and checkout_layout(candidate) == (root, common) and godot_folder(candidate)):
                return {'folder': str(candidate), 'source': 'worktree'}
        except (OSError, RuntimeError):
            continue
    return None


def checked_field(body, side):
    try:
        folder = picker_path(body, side)
    except (ValueError, OSError, RuntimeError) as exc:
        return {'folder': None, 'problem': str(exc)}, None
    config = None
    problem = None
    try:
        config = project_job.read_config(folder)
        if config['adapter'] != 'godot':
            problem = 'Choose a project with a Godot setup in expectrail.project.json.'
        elif config.get('draft'):
            problem = 'The project setup is a draft. Review its bindings before verifying.'
        elif side == 'before':
            problem = ' '.join(project_job.unready(folder)) or None
    except (ValueError, OSError) as exc:
        problem = str(exc)
    return {'folder': str(folder), 'problem': problem}, config


def saved_route_guidance(root, saved, info):
    """Read init's content-addressed first route without running input discovery."""
    from expectrail import onboard

    _, actions = onboard.check_pending(root, saved, info)
    return onboard.route_guidance(actions)


class MissingConfig(req.RequestError):
    def __init__(self, detail, preview):
        super().__init__(detail)
        self.preview = preview


def setup_preview(root, player=None, remember=None):
    """Explain the missing configuration from authored scenes, without starting a job."""
    from expectrail import onboard, onboarding

    pending = root / onboard.PENDING
    has_draft = pending.exists() or pending.is_symlink()
    saved = {}
    if has_draft:
        saved = rec.strict_loads(project_job.regular(root, onboard.PENDING, LIMIT).decode('utf-8'))
        if not isinstance(saved, dict):
            raise ValueError(f'{onboard.PENDING} must contain a saved setup.')
    selected = saved.get('selectedPlayer')
    if 'selectedPlayer' in saved and not isinstance(selected, str):
        raise ValueError(f'selectedPlayer in {onboard.PENDING} must be a node path.')
    if has_draft and player is not None:
        raise ValueError('A draft already exists. Check folders again to review the saved setup.')
    if player is not None:
        selected = player
    info = onboarding.inspect(root, selected)
    route_guidance = saved_route_guidance(root, saved, info) if has_draft else None
    title = 'Saved draft preview' if has_draft else 'Setup preview'
    players = (f'Selected player: {selected}' if selected else
               'Player candidates: ' + (', '.join(info['players']) or 'none found'))
    lines = [f'{title} for {root.name}', f'Starting scene: {info["entryScene"]}', players]
    if len(info['players']) == 1:
        lines.append('Player images: ' + (', '.join(info['textures']) or 'none found for this player'))
    else:
        lines.append('Identify the player in the starting scene before selecting its image.')
    if route_guidance:
        lines.append(route_guidance)
    lines.extend(info['unresolvedBindings'])
    if not has_draft and not info['unresolvedBindings']:
        lines.append('Select the player to review a draft setup, or run expectrail init on this folder.')
    preview = None
    if not has_draft and info['players']:
        preview = {key: info[key] for key in ('entryScene', 'players', 'unresolvedBindings')}
        preview.update(selectedPlayer=selected, imageSuggestions=info.get('imageSuggestions', []))
        if selected is not None and remember:
            preview['saveReview'] = remember(root, info)
    return '\n'.join(lines), preview


def inspect_project(body, *, remember=None):
    if configured(body):
        from expectrail import project_config, renderer
        root = project_folder(body, 'folder')
        descriptor = root / 'project.godot'
        if not os.path.lexists(root / project_config.FILENAME) and not descriptor.is_symlink() and descriptor.is_file():
            try:
                player = body.get('player')
                if 'player' in body and not isinstance(player, str):
                    raise ValueError('Choose a player node from the starting scene.')
                detail, preview = setup_preview(root.resolve(), player, remember)
            except (ValueError, OSError) as exc:
                detail, preview = f'Could not read the setup preview: {exc}', None
            raise MissingConfig(f'Project config: no {project_config.FILENAME}.\n{detail}', preview)
        if 'player' in body:
            raise ValueError('The folder no longer has an available player preview. Check folders again.')
        result = project_job.inspect(root)
        result['rendering'] = renderer.project_report(root)
        return result
    doc = build(body, inspect=True)
    root = Path(doc['head']['checkout'])
    game = root / doc['project']['game']
    from harness.adapters import get

    found = root.is_dir() and get('godot').is_project(game)
    checks = req.read_checks(doc)
    help_text = []
    if not root.is_dir():
        help_text.append('This folder does not exist. Paste the full path to an existing folder.')
    elif not found:
        help_text.append('No Godot project found. Choose the folder containing project.godot, '
                         'or set the game folder below.')
    if not checks.routes:
        help_text.append('No usable routes found. Choose your route files in the settings below. '
                         'If you have none, ask your game developer to record routes for these checks.')
    if not checks.specs:
        help_text.append('No approved checks found. Choose the checks folder below. '
                         'A person must review and approve checks before they can judge a change.')
    if checks.problems:
        help_text.append('Correct the listed file problems before verifying.')
    return {'folder': str(root), 'godot': found, 'routes': len(checks.routes),
            'checks': len(checks.specs), 'drafts': checks.drafts, 'problems': checks.problems,
            'help': ' '.join(help_text) or 'Project, routes and approved checks found.'}


def job_screen(phase, decision, output):
    """(state, screen) for a job record: which of the app's screens a person sees."""
    state = decision if phase == 'completed' else phase if phase in FINAL else 'running'
    if phase == 'queued':
        return state, 'queued'
    if state == 'needs-review' and not output:
        return state, 'could-not-be-carried-out'
    return state, state


class App:
    def __init__(self, store, start):
        self.store, self.start = store, start
        self.owned = set()
        self.lock = threading.RLock()
        self.waiters = []
        self.closing = False
        self.setup_lock = threading.Lock()
        self.setup_reviews = {}
        self.chooser_lock = threading.Lock()
        self.previous_lock = threading.Lock()
        self.previous_copy = None
        self.previous_origins = {}

    def recent_projects(self):
        try:
            raw = commits.regular(self.store.root / 'recent-projects.json', LIMIT)
            folders = json.loads(raw)
        except (OSError, ValueError):
            return []
        if not isinstance(folders, list):
            return []
        return [folder for folder in folders[:6]
                if isinstance(folder, str) and '\0' not in folder and Path(folder).is_absolute()]

    def remember_project(self, folder):
        with self.lock:
            folders = [recent for recent in self.recent_projects() if recent != str(folder)]
            self.store.root.mkdir(parents=True, exist_ok=True)
            # Publish the short list whole, even if another app instance reads it now.
            with tempfile.NamedTemporaryFile(mode='w', dir=self.store.root, delete=False) as output:
                path = Path(output.name)
                try:
                    json.dump([str(folder), *folders[:5]], output)
                    output.close()
                    path.replace(self.store.root / 'recent-projects.json')
                finally:
                    path.unlink(missing_ok=True)

    def choose_project(self, body):
        if body:
            raise ValueError('Choose the folder in the desktop dialog.')
        if not self.chooser_lock.acquire(blocking=False):
            raise ValueError('A folder chooser is already open.')
        try:
            chosen = choose_folder()
            if chosen is None:
                return {'folder': None}
            folder = picker_path({'folder': chosen}, 'folder')
            self.remember_project(folder)
            return {'folder': str(folder)}
        finally:
            self.chooser_lock.release()

    def check_projects(self, body):
        if not body or set(body) - {'before', 'after'}:
            raise ValueError('Supply the Before or After project path.')
        result = {'beforeSuggestion': None, 'hasGitCheckout': False}
        fields = {side: checked_field(body, side) for side in ('before', 'after') if side in body}
        for side, (checked, _) in fields.items():
            result[side] = checked
        if result.get('after', {}).get('folder'):
            after = Path(result['after']['folder'])
            if 'before' not in fields:
                layout = checkout_layout(after)
                result['beforeSuggestion'] = before_suggestion(after, layout)
                result['hasGitCheckout'] = layout is not None and shutil.which('git') is not None
            else:
                _, config = fields['before']
                if config and not result['after']['problem']:
                    scene = config['entryScene'].removeprefix('res://')
                    scene_path = after / scene
                    if not scene_path.resolve().is_relative_to(after) or not scene_path.is_file():
                        result['after']['problem'] = (f'The versions have different layouts. After is missing {scene} '
                                                      'at the location used by Before.')
        return result

    def previous_project(self, body):
        if set(body) != {'after'}:
            raise ValueError('Choose the After project before using its previous commit.')
        after = picker_path(body, 'after')
        layout = checkout_layout(after)
        if layout is None:
            raise ValueError('After is not a Git checkout. Choose a Before folder.')
        working, _ = layout
        with self.previous_lock, tempfile.TemporaryDirectory(prefix='expectrail-git-') as git:
            if self.closing:
                raise ValueError('The app is stopping.')
            objects = commits.Objects(working, Path(git) / 'objects-view', timeout=10)
            try:
                try:
                    commit = objects.resolve('HEAD^')
                except commits.CommitError as exc:
                    raise ValueError('There is no readable previous local commit. Choose a Before folder.') from exc
                saved = tempfile.TemporaryDirectory(prefix='expectrail-before-')
                try:
                    root = Path(saved.name) / 'project'
                    objects.extract(commit, root)
                    folder = picker_path({'before': str(root / after.relative_to(working))}, 'before')
                except Exception:
                    saved.cleanup()
                    raise
            finally:
                objects.close()
            if self.previous_copy is not None:
                self.previous_copy.cleanup()
            self.previous_copy = saved
            self.previous_origins = {folder: (after, commit)}
            return {'folder': str(folder), 'source': 'previous-commit', 'commit': commit}

    def inspect(self, body):
        side = body.get('side')
        if side not in ('before', 'after'):
            return inspect_project(body)

        def remember(root, info):
            from expectrail import input_discovery, onboard
            from harness import tree
            if input_discovery.needed(info) and execution_class(body) == 'isolated':
                return {'blocked': 'This setup needs a headless game probe. Setup cannot require the replay '
                                   'sandbox. Supply a reviewed route and config for isolated verification.'}
            review = secrets.token_urlsafe(24)
            self.setup_reviews[side] = (review, root, info, tree.digest(root, skip=tree.GODOT_SKIP))
            return {'id': review, 'folder': str(root), 'runsProject': input_discovery.needed(info),
                    'setupFile': onboard.PENDING if info['unresolvedBindings'] else onboard.ACTIVE}

        with self.setup_lock:
            self.setup_reviews.pop(side, None)
            return inspect_project(body, remember=remember)

    def save_setup(self, body):
        from expectrail import input_discovery, onboard, onboarding
        from harness import tree

        if set(body) != {'side', 'folder', 'player', 'review'}:
            raise ValueError('Choose a player, review the proposed save and confirm it.')
        side, root = field(body, 'side'), project_folder(body, 'folder').resolve()
        with self.setup_lock:
            record = self.setup_reviews.get(side)
            if record is None:
                raise ValueError('Check folders and choose a player to review first.')
            review, reviewed_root, info, digest = record
            if (field(body, 'review'), root, field(body, 'player')) != (review, reviewed_root, info['selectedPlayer']):
                raise ValueError('This selection has no current review. Check folders and choose the player again.')
            del self.setup_reviews[side]

            def check_destination():
                if any(os.path.lexists(root / name) for name in (onboard.ACTIVE, onboard.PENDING)):
                    raise ValueError('A setup file already exists. Check folders to review it.')
                if tree.digest(root, skip=tree.GODOT_SKIP) != digest:
                    raise ValueError('The project changed. Check folders and review the player again.')

            check_destination()
            if onboarding.inspect(root, info['selectedPlayer']) != info:
                raise ValueError('The selected player changed. Check folders again.')
            if input_discovery.needed(info):
                # Execute only the reviewed bytes, even if the source changes during the probe.
                with tempfile.TemporaryDirectory(prefix='expectrail-setup-') as tmp:
                    snapshot = Path(tmp) / 'game'
                    if tree.copy(root, snapshot, skip=tree.GODOT_SKIP) != digest:
                        raise ValueError('The project changed before the probe. Check folders again.')
                    docs = onboarding.proposal(snapshot, info)
            else:
                docs = onboarding.proposal(root, info)
            check_destination()
            name = onboarding.publish(root, docs, force=False)
            return {'setupFile': name, 'route': docs['config']['routes'][0]}

    def own(self, job_id):
        with self.lock:
            if job_id not in self.owned:
                raise UnknownJob('No job from this app session has that address.')

    def create(self, body):
        after = None
        if configured(body):
            after = project_folder(body, 'after').resolve()
            # A second tab may replace the temporary Before copy while a job is being prepared.
            with self.previous_lock:
                before = project_folder(body, 'before').resolve()
                doc = project_job.prepare(self.store, after, before,
                                          execution_class=execution_class(body), require_ready=True)
                # Save the selection that produced these snapshots before another tab replaces the copy.
                display_before, before_commit = self.previous_origins.get(before, (before, None))
        else:
            doc = build(body)
        settings, _ = auto_fix.configure(body.get('autoFix', False), body.get('attempts'), body.get('usdCap'), agent=body.get('repairAgent'))
        if settings:
            doc['autoFix'] = settings
        from harness.adapters import get

        for side in ('base', 'head'):
            root = Path(doc[side]['checkout'])
            if not root.is_dir() or not get('godot').is_project(root / doc['project']['game']):
                raise ValueError(f'Choose an existing Godot project for {"Before" if side == "base" else "After"}. '
                                 'Use Check folders for help. Nothing was run.')
        with self.lock:
            if self.closing:
                raise ValueError('The app is stopping. Nothing was run.')
            status, created = self.store.create(doc)
            job_id = status['id']
            self.owned.add(job_id)
            try:
                proc = None
                if created:
                    if after is not None:
                        try:
                            self.record_folders(job_id, display_before, after, before_commit)
                        except OSError:
                            pass  # The snapshots can still run and identify the recorded checkouts.
                    if settings:
                        proc = auto_fix.launch(self.store, job_id, None)
                    else:
                        proc = self.start(self.store, job_id)
            except Exception:
                self.store.finish(job_id, 'failed', reasons=['The worker could not be started. No verdict.'])
                raise
            waiter = threading.Thread(target=runner.wait, args=(self.store, job_id, proc), daemon=True)
            waiter.start()
            self.waiters.append(waiter)
        if after is not None:
            try:
                self.remember_project(after)
            except OSError:
                pass  # A recent-path write cannot change the result of a started job.
        return self.status(job_id)

    def record_folders(self, job_id, before, after, before_commit=None):
        # Local display data, outside the worker request and all evidence exports.
        # A reader sees either both selections or the recorded checkout fallback.
        fields = {'before': str(before), 'after': str(after)}
        if before_commit is not None:
            fields['beforeCommit'] = before_commit
        with tempfile.NamedTemporaryFile(mode='w', dir=self.store.root, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                json.dump(fields, stream)
                stream.close()
                temporary.replace(self.store.root / f'app-folders-{job_id}.json')
            finally:
                temporary.unlink(missing_ok=True)

    def result_folders(self, job_id, request):
        before = (request['base'] or {}).get('checkout')
        after = request['head']['checkout']
        head = Path(after)
        pair = head.parent
        if not (request['project']['game'] == 'project' and head.name == 'head'
                and pair.parent == self.store.root and pair.name.startswith('project-')
                and (before is None or Path(before) == pair / 'base')):
            return before, after
        try:
            # status() has already validated the job ID. Never open a path from the sidecar.
            fields = rec.strict_loads(commits.regular(self.store.root / f'app-folders-{job_id}.json', LIMIT))
            commit = None
            if isinstance(fields, dict) and 'beforeCommit' in fields:
                commit = fields.pop('beforeCommit')
                if not isinstance(commit, str) or not commits.OID.fullmatch(commit):
                    raise ValueError('Invalid saved Before commit.')
            if isinstance(fields, dict) and set(fields) == {'before', 'after'} and all(
                    isinstance(v, str) and '\0' not in v and Path(v).is_absolute() for v in fields.values()):
                label = fields['before']
                if commit is not None:
                    label += f' (copy opened from Git commit {commit})'
                return label, fields['after']
        except (OSError, ValueError, RecursionError):
            pass
        return tuple(f'Recorded checkout: {path} (original selection unavailable)' if path else None
                     for path in (before, after))

    def status(self, job_id, *, past=False):
        if not past:
            self.own(job_id)
        doc = self.store.status(job_id)  # validates the record; unfinished/empty is never success
        phase = doc['phase']
        state, screen = job_screen(phase, doc['decision'], doc['output'])
        report = None
        if job_id in self.owned and phase == 'completed' and doc['output']:
            try:
                self.report(job_id, ['index.html'])
                report = f'/reports/{job_id}/index.html'
            except (OSError, UnknownJob):
                pass
        request = self.store.request(job_id)
        before, after = self.result_folders(job_id, request)
        repair = doc.get('repair') or {}
        summary = OUTCOMES[state]
        if state == 'reject':
            if repair:
                summary += ' ' + viewer.auto_fix_words(doc)
                if 'review' in repair:
                    summary += ' ' + repair['review']
            else:
                summary += (' No repair was recorded. To try one on a new run, select '
                            '“Try to fix the game if verification rejects it” and set '
                            '“Maximum fixer spend in US dollars” before choosing Verify.')
        findings = self.findings(job_id, doc)
        return {key: doc[key] for key in ('id', 'phase', 'decision', 'history', 'reasons', 'diagnostics', 'createdAt')} | {
            'state': state, 'screen': screen, 'summary': summary, 'sessionOwned': job_id in self.owned, 'report': report,
            'repairRunning': repair.get('state') == 'running',
            'repairUrl': f'/repairs/{job_id}/repair-run.json' if 'record' in repair and job_id in self.owned else None,
            'before': before, 'after': after,
            'judgedBy': judged_by(doc, findings),
            'isolation': rec.isolation_words(findings.get('isolation')) if findings is not None else None,
            'viewer': f'/viewers/{job_id}/index.html' if job_id in self.owned and phase in FINAL else None}

    def history(self):
        jobs = self.store.root / 'jobs'
        rows = []
        if jobs.exists():
            for folder in jobs.iterdir():
                if folder.is_dir() and not folder.is_symlink():
                    rows.append(self.status(folder.name, past=True))
        return {'jobs': sorted(rows, key=lambda row: (row['createdAt'], row['id']), reverse=True)}

    def findings(self, job_id, doc):
        if doc['phase'] == 'completed' and doc['output']:
            try:
                record = rec.strict_loads(self.read_file(job_id, ['output', 'findings.json']).decode('utf-8'))
                rec.check_record(record)
                return record
            except (OSError, UnicodeError, rec.RecordError):
                pass
        return None

    def viewer_file(self, job_id, parts):
        self.own(job_id)
        doc = self.store.status(job_id)
        if doc['phase'] not in FINAL or not (parts in (['index.html'], [viewer.EXPORT_NAME])
                                            or viewer.FRAME_NAME.fullmatch('/'.join(parts))):
            raise UnknownJob('No such finished viewer file.')
        if doc['output']:
            try:
                data = self.read_file(job_id, ['output', 'viewer', *parts])
                if len(parts) == 1 and doc['decision'] == 'reject':
                    # The gate wrote the frame viewer before the parent knew its repair outcome.
                    # Replace just that section. Keep the viewer, frames and script intact.
                    link = None
                    download = parts == [viewer.EXPORT_NAME]
                    if (doc.get('repair') or {}).get('record'):
                        if download:
                            encoded = base64.b64encode(self.repair_file(job_id)).decode('ascii')
                            link = 'data:application/json;base64,' + encoded
                        else:
                            link = f'/repairs/{job_id}/repair-run.json'
                    section = viewer.auto_fix_section(doc, link, download=download).encode()
                    data = data.replace(b'<section id="auto-fix"></section>', section, 1)
                return data
            except FileNotFoundError:
                pass
        if len(parts) != 1:
            raise UnknownJob('No such viewer frame.')
        # Jobs without a gate viewer still use the existing viewer's state rules. No job files are written.
        with tempfile.TemporaryDirectory(prefix='expectrail-app-viewer-') as folder:
            viewer.write(Path(folder), self.findings(job_id, doc), status=doc, request=self.store.request(job_id))
            return (Path(folder) / parts[0]).read_bytes()

    def repair_file(self, job_id):
        self.own(job_id)
        path = (self.store.status(job_id).get('repair') or {}).get('record', '')
        if not viewer.REPAIR_RECORD.fullmatch(path):
            raise UnknownJob('This job has no finished repair record.')
        return self.read_file(job_id, path.split('/'))

    def report(self, job_id, parts):
        self.own(job_id)
        doc = self.store.status(job_id)
        if doc['phase'] != 'completed' or not doc['output']:
            raise UnknownJob('This job has no finished report.')
        # Only the gate's existing page and its PNG copies. Walk with directory descriptors so a
        # link (even one swapped during the read) cannot turn a report request into a file server.
        if not (parts == ['index.html'] or len(parts) == 2 and parts[0] == 'assets'
                and parts[1].endswith('.png')) or any(p in ('', '.', '..') or '/' in p or '\\' in p for p in parts):
            raise UnknownJob('No such report file.')
        return self.read_file(job_id, ['output', 'review', *parts])

    def read_file(self, job_id, parts):
        self.store.paths(job_id)  # validate the identifier before walking directories
        if any(p in ('', '.', '..') or '/' in p or '\\' in p for p in parts):
            raise UnknownJob('No such file.')
        fd = os.open(self.store.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in ['jobs', job_id, *parts[:-1]]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(file_fd, 'rb') as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise UnknownJob('No such report file.')
                data = source.read(64 * 1024 * 1024 + 1)
                if len(data) > 64 * 1024 * 1024:
                    raise UnknownJob('Report file exceeds the local app size limit.')
                return data
        finally:
            os.close(fd)

    def close(self):
        with self.lock:
            self.closing = True
            for job_id in self.owned:
                if self.store.status(job_id)['phase'] not in FINAL:
                    self.store.cancel(job_id)
        for waiter in self.waiters:
            waiter.join(6)
        with self.previous_lock:
            if self.previous_copy is not None:
                self.previous_copy.cleanup()


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_close(self):
        super().server_close()
        if hasattr(self, 'app'):
            self.app.close()


class Handler(BaseHTTPRequestHandler):
    server_version = 'Expectrail'

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *args):
        pass  # Never log the opening URL or its token.

    def reply(self, code, data, content_type='application/json; charset=utf-8', *, cookie=False, report=False, evidence=False):
        if isinstance(data, dict):
            data = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        policy = ("sandbox allow-same-origin; default-src 'none'; script-src 'none'; "
                  "style-src 'unsafe-inline'; img-src 'self'; " if report else
                  f"default-src 'none'; script-src 'nonce-{self.server.nonce}'; "
                  f"style-src 'nonce-{self.server.nonce}'; connect-src 'self'; ")
        if evidence:
            digest = base64.b64encode(hashlib.sha256(viewer.SCRIPT.encode()).digest()).decode()
            policy = (f"default-src 'none'; script-src 'sha256-{digest}'; "
                      "style-src 'unsafe-inline'; img-src 'self' data:; ")
        self.send_header('Content-Security-Policy', policy + "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        if cookie:
            self.send_header('Set-Cookie', f'{self.server.cookie}={self.server.token}; Path=/; HttpOnly; SameSite=Strict')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def problem(self, code, detail, **fields):
        self.reply(code, {'state': 'could-not-be-carried-out', 'detail': detail, **fields})

    def authorized(self, path, query):
        hosts = [f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}']
        host = self.headers.get_all('Host', [])
        if len(host) != 1 or host[0] not in hosts:
            self.problem(403, 'This address is not allowed. Use the address printed by Expectrail.')
            return False
        origins = self.headers.get_all('Origin', [])
        if origins and origins != ['http://' + host[0]]:
            self.problem(403, 'Requests from another page are not allowed.')
            return False
        values = self.headers.get_all('X-Expectrail-Token', [])
        # APIs always require the header, never a URL parameter or an ambient browser cookie.
        if not path.startswith('/api/') and not values:
            if path == '/' and 'token' in query:
                values = query['token']
            else:
                cookie = SimpleCookie()
                try:
                    cookie.load(self.headers.get('Cookie', ''))
                    if self.server.cookie in cookie:
                        values = [cookie[self.server.cookie].value]
                except CookieError:
                    pass
        if len(values) != 1 or not secrets.compare_digest(values[0].encode(), self.server.token.encode()):
            self.problem(401, 'Open the full address printed by Expectrail, including its token.')
            return False
        return True

    def body(self):
        sizes = self.headers.get_all('Content-Length', [])
        if self.headers.get('Transfer-Encoding') or len(sizes) != 1:
            raise ValueError('A single Content-Length is required.')
        size = int(sizes[0])
        if not 0 < size <= LIMIT:
            raise ValueError('Request body is missing or too large.')
        if self.headers.get_content_type() != 'application/json':
            raise ValueError('Send application/json.')
        doc = json.loads(self.rfile.read(size))
        if not isinstance(doc, dict):
            raise ValueError('Send a JSON object.')
        return doc

    def dispatch(self):
        try:
            url = urlsplit(self.path)
            path = unquote(url.path)
            query = parse_qs(url.query, max_num_fields=4)
            if not self.authorized(path, query):
                return
            if url.scheme or url.netloc:
                raise ValueError('Use a local path.')
            if self.command not in ('GET', 'POST'):
                return self.problem(405, 'Use POST for actions and GET to read.')
            app = self.server.app
            if path == '/':
                if self.command != 'GET':
                    return self.problem(405, 'Use GET to open the app.')
                page = app_page.PAGE.replace('__NONCE__', self.server.nonce).replace('__TOKEN__', self.server.token)
                return self.reply(200, page.encode(), 'text/html; charset=utf-8', cookie=True)
            if path.startswith('/api/projects/'):
                if query:
                    raise ValueError('Project selection does not take URL parameters.')
                if path == '/api/projects/recent':
                    if self.command != 'GET':
                        return self.problem(405, 'Use GET to read recent projects.')
                    return self.reply(200, {'folders': app.recent_projects()})
                actions = {'/api/projects/choose': app.choose_project, '/api/projects/check': app.check_projects,
                           '/api/projects/previous': app.previous_project}
                if path in actions:
                    if self.command != 'POST':
                        return self.problem(405, 'This action requires POST.')
                    return self.reply(200, actions[path](self.body()))
            if path in ('/api/inspect', '/api/setup/save', '/api/jobs') or path.startswith('/api/jobs/') and path.endswith('/cancel'):
                if self.command != 'POST':
                    return self.problem(405, 'This action requires POST.')
                body = self.body()
                if path == '/api/inspect':
                    return self.reply(200, app.inspect(body))
                if path == '/api/setup/save':
                    return self.reply(201, app.save_setup(body))
                if path == '/api/jobs':
                    return self.reply(201, app.create(body))
                job_id = path.removeprefix('/api/jobs/').removesuffix('/cancel')
                app.own(job_id)
                app.store.cancel(job_id)
                return self.reply(200, app.status(job_id))
            if self.command != 'GET':
                return self.problem(405, 'Use GET to read.')
            if path == '/api/history':
                return self.reply(200, app.history())
            if path.startswith('/api/jobs/'):
                return self.reply(200, app.status(path.removeprefix('/api/jobs/')))
            if path.startswith('/viewers/'):
                job_id, *parts = path.removeprefix('/viewers/').split('/')
                try:
                    data = app.viewer_file(job_id, parts)
                except OSError:
                    raise UnknownJob('No such viewer file.') from None
                return self.reply(200, data, 'text/html; charset=utf-8' if len(parts) == 1 else 'image/png',
                                  evidence=True)
            if path.startswith('/repairs/'):
                job_id, *parts = path.removeprefix('/repairs/').split('/')
                if parts != ['repair-run.json']:
                    raise UnknownJob('No such repair file.')
                try:
                    return self.reply(200, app.repair_file(job_id), report=True)
                except OSError:
                    raise UnknownJob('No such repair file.') from None
            if path.startswith('/reports/'):
                job_id, *parts = path.removeprefix('/reports/').split('/')
                try:
                    data = app.report(job_id, parts)
                except OSError:
                    raise UnknownJob('No such report file.') from None
                return self.reply(200, data, 'text/html; charset=utf-8' if parts == ['index.html'] else 'image/png',
                                  report=True)
            raise UnknownJob('No such page.')
        except InvalidProjectPath as exc:
            self.problem(400, str(exc), jobStarted=False)
        except project_job.ProjectNotReady as exc:
            self.problem(400, f'Before is not ready for verification. {exc}', jobStarted=False)
        except MissingConfig as exc:
            self.problem(400, str(exc), **({'setupPreview': exc.preview} if exc.preview else {}))
        except UnknownJob as exc:
            self.problem(404, str(exc))
        except (ValueError, OSError, StoreError) as exc:
            self.problem(400, str(exc))
        except Exception:
            self.problem(500, 'The app could not complete this request. No result is available here.')

    def __getattr__(self, name):
        # Authenticate unsupported HTTP methods too, before rejecting them.
        if name.startswith('do_'):
            return self.dispatch
        raise AttributeError(name)

    do_GET = do_POST = do_HEAD = do_OPTIONS = do_PUT = do_DELETE = do_PATCH = dispatch


def create_server(store=None, *, start=runner.spawn):
    server = Server(('127.0.0.1', 0), Handler)
    server.token = secrets.token_urlsafe(32)
    server.nonce = secrets.token_urlsafe(24)
    server.cookie = f'expectrail_{server.server_port}'
    server.app = App(store if store is not None else JobStore(Path.home() / '.local/share/expectrail/app-jobs'), start)
    return server


def install_launcher():
    """Create the current Python environment's launcher in the user's account."""
    python = str(Path(sys.executable).absolute())
    if any(ord(char) < 32 for char in python):
        raise ValueError('The Python path contains a control character.')
    args = ['-I', '-m', 'expectrail.cli', 'app', '--open-browser']
    if sys.platform.startswith('linux'):
        data_home = Path(os.environ.get('XDG_DATA_HOME', ''))
        if not data_home.is_absolute():
            data_home = Path.home() / '.local/share'
        path = data_home / 'applications' / 'expectrail.desktop'
        # Apply Exec quoting first, then the desktop file string escaping.
        special = ('\\', '"', '$', chr(96))
        quoted = ''.join(('\\' if char in special else '') + char for char in python)
        quoted = quoted.replace('%', '%%').replace('\\', '\\\\')
        command = ' '.join(['/usr/bin/env', f'"{quoted}"', *args])
        body = ('[Desktop Entry]\nType=Application\nName=Expectrail\n'
                f'Exec={command}\nTerminal=false\n')
    elif sys.platform == 'darwin':
        path = Path.home() / 'Applications' / 'Expectrail.command'
        body = '#!/bin/sh\nexec ' + shlex.join([python, *args]) + '\n'
    else:
        raise ValueError('Expectrail launchers are available for Linux and macOS.')
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replace the generated entry atomically without following an old file link.
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(body)
            stream.close()
            temporary.chmod(0o700)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(prog='expectrail app', description='Open Expectrail locally on 127.0.0.1.')
    parser.add_argument('--jobs-root', type=Path, help='Job storage outside both game folders.')
    launch = parser.add_mutually_exclusive_group()
    launch.add_argument('--install-launcher', action='store_true', help='Create a launcher for this installed copy.')
    launch.add_argument('--open-browser', action='store_true', help='Open the local page in your default browser.')
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 5  # 2 belongs to a verifier's needs-review decision
    if args.install_launcher:
        try:
            print(f'Expectrail launcher created at {install_launcher()}')
        except (OSError, ValueError) as exc:
            print(f'Expectrail could not create a launcher: {exc}', file=sys.stderr)
            return 5
        return 0
    try:
        server = create_server(JobStore(args.jobs_root) if args.jobs_root else None)
    except OSError as exc:
        print(f'Expectrail could not start: {exc}. No verification was run.', file=sys.stderr)
        return 5
    url = f'http://127.0.0.1:{server.server_port}/?token={server.token}'
    print(f'Open {url}', flush=True)
    if args.open_browser:
        def open_page():
            try:
                if webbrowser.open(url):
                    return
            except (OSError, webbrowser.Error):
                pass
            print('Your browser did not open. Copy the local address above into your browser.', flush=True)

        threading.Thread(target=open_page, daemon=True).start()
    print('Keep this process running. Press Ctrl+C to stop the app and cancel unfinished jobs.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
