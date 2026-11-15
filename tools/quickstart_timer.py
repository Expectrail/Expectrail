"""Time the published no-credentials quickstart, or read its timing record.

    python3 -m tools.quickstart_timer --out runs/quickstart-timer
    python3 -m tools.quickstart_timer --read runs/quickstart-timer/quickstart-timing.json

The output directory must be new. Commands run in one clean Bash shell in a
fresh temporary copy of the install inputs, never in the source checkout.
Only pip's install and doctor's documented engine fetch may need the network.
No model credentials, shell startup files or user pip configuration are used.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from expectrail.contracts import strict_loads
from expectrail.gate.record import errors
from tools import quickstart

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / 'contracts/quickstart-timing.v1.schema.json'
FORMAT = 'expectrail.quickstart-timing/v1'
DEPENDENCIES = {'install': (), 'doctor': ('install',), 'sample': ('doctor',),
                'project': (), 'verify': ('doctor', 'project'), 'report': ('verify',)}


def validate_timing(doc):
    """Validate the small schema plus relations JSON Schema cannot express."""
    found = errors(doc, json.loads(SCHEMA.read_text(encoding='utf-8')))
    if found:
        raise ValueError('quickstart timing: ' + found[0])
    names = [s['name'] for s in doc['steps']]
    if len(names) != len(set(names)):
        raise ValueError('quickstart timing: duplicate step name')
    if {d['path'] for d in doc['documents']} != {'README.md', 'docs/quickstart.html'}:
        raise ValueError('quickstart timing: both source documents must be named')
    for step in doc['steps']:
        if step['seconds'] is not None and not math.isfinite(step['seconds']):
            raise ValueError('quickstart timing: seconds must be finite')
        if step['status'] == 'completed' and step['exit_code'] != step['expected_exit']:
            raise ValueError('quickstart timing: completed step has an unexpected exit')
    if doc['evidence_check']['status'] == 'completed' and any(s['status'] != 'completed' for s in doc['steps']):
        raise ValueError('quickstart timing: incomplete commands cannot have checked evidence')
    return doc


def write_timing(doc, path):
    validate_timing(doc)
    Path(path).write_text(json.dumps(doc, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def read_timing(path):
    """Offline reader for the dossier or a person; never executes a recorded command."""
    return validate_timing(strict_loads(Path(path).read_text(encoding='utf-8')))


def documented_steps(root=ROOT):
    # Reuse the CI reader so commands and expected nonzero exits cannot drift.
    steps = quickstart.commands(Path(root) / 'docs/quickstart.html')
    readme = (Path(root) / 'README.md').read_text(encoding='utf-8')
    blocks = re.findall(r'```sh\s*\n(.*?)```', readme, re.S)
    if not blocks or blocks[0].strip() not in steps[0]['command']:
        raise ValueError('README install block is not in the documented quickstart install step')
    # Today neither document teaches app. Refuse a new app instruction instead
    # of silently claiming to time a walkthrough while leaving it out.
    if re.search(r'\bexpectrail\s+app\b', readme + (Path(root)/'docs/quickstart.html').read_text()):
        raise ValueError('app is now documented: update the timer to measure its interactive startup explicitly')
    return steps


def clean_environment(work, inherited):
    """Allowlist runtime paths only; do not even copy unknown key/provider settings."""
    env = {k: inherited[k] for k in ('PATH', 'LANG', 'LC_ALL', 'DISPLAY', 'XAUTHORITY') if k in inherited}
    # Network routing/CA configuration is a machine prerequisite, not a model key.
    # Never inherit an authenticated proxy or a URL carrying query credentials.
    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        value = inherited.get(name, '')
        parsed = urlsplit(value)
        if value and not (parsed.username or parsed.password or parsed.query or parsed.fragment):
            env[name] = value
    for name in ('NO_PROXY', 'no_proxy', 'SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE'):
        if name in inherited:
            env[name] = inherited[name]
    for name, folder in (('HOME', 'home'), ('TMPDIR', 'tmp'), ('XDG_CACHE_HOME', 'cache'),
                         ('XDG_CONFIG_HOME', 'config')):
        path = work / folder
        path.mkdir()
        env[name] = str(path)
    env.update(PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK='1', PIP_NO_INPUT='1')
    if inherited.get('EXPECTRAIL_GODOT'):
        env['EXPECTRAIL_GODOT'] = str(Path(inherited['EXPECTRAIL_GODOT']).resolve())
    return env


class Shell:
    """One Bash process retains activation and PROJECT/JOB between exact blocks."""
    def __init__(self, cwd, env):
        self.proc = subprocess.Popen(['bash', '--noprofile', '--norc'], cwd=cwd, env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, start_new_session=True)

    def close(self):
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.proc.wait()
        try:
            self.proc.stdin.close()
        except BrokenPipeError:
            pass
        self.proc.stdout.close()

    def run(self, command, stdout, stderr, timeout):
        # A brace group, not a subshell: the documented variables persist.
        script = ('{\n' + command + '\n} > ' + shlex.quote(str(stdout)) + ' 2> ' + shlex.quote(str(stderr))
                  + '\nquickstart_timer_exit=$?\nprintf "%s\\n" "$quickstart_timer_exit"\n')
        self.proc.stdin.write(script.encode())
        self.proc.stdin.flush()
        if not select.select([self.proc.stdout], [], [], timeout)[0]:
            self.close()
            return self.proc.returncode, f'Command exceeded the {timeout:g}-second limit; the shell process group was stopped.'
        line = self.proc.stdout.readline()
        if not line:
            self.proc.wait()
            return self.proc.returncode, 'The command ended the shared shell before returning a step status.'
        return int(line.strip()), None


def not_run(step, reason):
    return dict(name=step['name'], command=step['command'], expected_exit=step['exit'],
                status='not run', exit_code=None, seconds=None, reason=reason,
                error_lines=[], stdout=None, stderr=None)


def first_lines(path):
    if not path.exists():
        return []
    with path.open(encoding='utf-8', errors='replace') as stream:
        return [line.rstrip()[:1000] for _, line in zip(range(5), stream)]


def doctor_blocker(cwd):
    from expectrail.doctor import problems
    doc = strict_loads((cwd / 'doctor.json').read_text(encoding='utf-8'))
    found = problems(doc)
    if found:
        raise ValueError('doctor document: ' + found[0])
    missing = [c for c in doc['checks'] if c['required'] and c['status'] != 'ok'
               and c['id'] not in ('vision-key', 'vision-cap')]
    if missing:
        return 'Doctor found missing prerequisites: ' + '; '.join(c['id'] + ': ' + c['found'] for c in missing)
    return None


def run_steps(steps, cwd, env, out, timeout=600, *, shell_factory=Shell, clock=time.perf_counter):
    """Measure executed steps, explicitly retaining blocked ones in document order."""
    (out / 'commands').mkdir()
    results, previous = [], {}
    blocker = None
    shell = None
    try:
        try:
            shell = shell_factory(cwd, env)
        except OSError as exc:
            blocker = f'Cannot start Bash: {exc}'
        for index, step in enumerate(steps):
            name = step['name']
            reason = None
            if shell is None:
                reason = blocker
            elif shell.proc.poll() is not None:
                reason = 'The shared shell is no longer running.'
            elif name == 'install' and shutil.which('python3', path=env.get('PATH', os.defpath)) is None:
                reason = 'python3 is not available on PATH; the install block was not run.'
            else:
                failed = [n for n in DEPENDENCIES.get(name, ()) if previous.get(n, {}).get('status') != 'completed']
                if failed:
                    reason = 'Required earlier step did not complete: ' + ', '.join(failed)
                elif name in ('sample', 'verify') and blocker:
                    reason = blocker
            if reason:
                item = not_run(step, reason)
            else:
                stdout = out / 'commands' / f'{index+1:02d}-{name}.stdout.txt'
                stderr = stdout.with_name(stdout.name.replace('.stdout.', '.stderr.'))
                start = clock()
                try:
                    code, problem = shell.run(step['command'], stdout, stderr, timeout)
                except (OSError, ValueError) as exc:
                    code, problem = None, f'Could not execute command: {exc}'
                seconds = max(0., clock() - start)
                # An interrupted process is a failed attempt, not "not run".
                status = 'completed' if problem is None and code == step['exit'] else 'failed'
                reason = problem or (None if status == 'completed' else f'Exit {code}; documented exit is {step["exit"]}.')
                error_lines = first_lines(stderr)
                if status == 'failed' and not error_lines:
                    error_lines = first_lines(stdout)
                item = dict(name=name, command=step['command'], expected_exit=step['exit'], status=status,
                            exit_code=code, seconds=seconds, reason=reason, error_lines=error_lines,
                            stdout=stdout.relative_to(out).as_posix(), stderr=stderr.relative_to(out).as_posix())
                if name == 'doctor' and status == 'completed':
                    try:
                        blocker = doctor_blocker(cwd)
                        item['reason'] = blocker
                    except (OSError, ValueError) as exc:
                        item.update(status='failed', reason=f'Cannot read doctor evidence: {exc}')
            results.append(item)
            previous[name] = item
    finally:
        if shell is not None:
            shell.close()
    return results


def measure(out, *, root=ROOT, timeout=600):
    root, out = Path(root).resolve(), Path(out).resolve()
    steps = documented_steps(root)
    for game in ('game/platformer', 'game/unity-platformer'):
        if out.is_relative_to(root / game):
            raise ValueError('Output cannot be inside a source game')
    out.mkdir(parents=True, exist_ok=False)
    try:
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        commit = ''  # A source archive can still be timed without installing Git.
    doc = dict(format=FORMAT, started_at=datetime.now(timezone.utc).isoformat(),
               source_commit=commit if re.fullmatch('[0-9a-f]{40}', commit) else None,
               documents=[dict(path=n, sha256=hashlib.sha256((root/n).read_bytes()).hexdigest())
                          for n in ('README.md', 'docs/quickstart.html')],
               environment=dict(platform=platform.platform(), python=platform.python_version(), configured_godot=None),
               steps=[], evidence_check=dict(status='not run', reason='Commands have not completed.'),
               notes=['Machine wall seconds per exact command block, including its child processes; not human minutes to first verdict.',
                      'Completed means the documented exit was observed, not a verification accept. No keys or spending caps were supplied.',
                      'app is not documented in these quickstart/README instructions and was not run.',
                      'Source preparation is not timed as a quickstart step. The temporary checkout, home and caches are removed; command logs and diagnostic JSON are retained.',
                      'Only the documented pip install and engine fetch may need network access. Existing unauthenticated proxy and CA settings are preserved; no extra dependencies or model calls are added.'])
    with tempfile.TemporaryDirectory(prefix='expectrail-quickstart-timer-') as temporary:
        work = Path(temporary)
        env = clean_environment(work, os.environ)
        doc['environment']['configured_godot'] = env.get('EXPECTRAIL_GODOT')
        cwd = work / 'checkout'
        try:
            quickstart.copy_checkout(root, cwd)
        except OSError as exc:
            doc['steps'] = [not_run(s, f'Cannot prepare a fresh checkout: {exc}') for s in steps]
        else:
            doc['steps'] = run_steps(steps, cwd, env, out, timeout)
            if all(s['status'] == 'completed' for s in doc['steps']):
                try:
                    quickstart.validate_results(cwd)
                    doc['evidence_check'] = dict(status='completed', reason='The existing quickstart evidence checks passed: sample decisions and the unapproved project boundary.')
                except (AssertionError, ValueError, OSError, KeyError) as exc:
                    doc['evidence_check'] = dict(status='failed', reason=f'Quickstart evidence did not meet its documented expectations: {exc}')
            else:
                doc['evidence_check']['reason'] = 'Not all documented commands completed; no successful walkthrough is claimed.'
            for name in ('doctor.json', 'sample.json', 'verification.json'):
                if (cwd/name).is_file():
                    shutil.copy2(cwd/name, out/name)
    write_timing(doc, out / 'quickstart-timing.json')
    return doc


def summary(doc):
    lines = ['Machine timings; completed commands are not verification accepts.']
    for step in doc['steps']:
        elapsed = 'not measured' if step['seconds'] is None else f'{step["seconds"]:.3f} s'
        lines.append(f'{step["name"]}: {step["status"]}; exit {step["exit_code"]}; {elapsed}')
        if step['reason']:
            lines.append('  ' + step['reason'])
    lines.append('Evidence check: ' + doc['evidence_check']['status'] + ' — ' + doc['evidence_check']['reason'])
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--out', type=Path, help='new directory for quickstart-timing.json and command logs')
    mode.add_argument('--read', type=Path, help='validate and summarize a saved record offline')
    parser.add_argument('--timeout', type=float, default=600, help='maximum seconds per block (default: 600)')
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be finite and positive')
    try:
        doc = read_timing(args.read) if args.read else measure(args.out, timeout=args.timeout)
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Quickstart timer: {exc}\n')
    print(summary(doc))
    return 0 if args.read or doc['evidence_check']['status'] == 'completed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
