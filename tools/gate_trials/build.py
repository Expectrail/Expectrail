"""Build refs using an alternate Git index. Never check out or edit the game."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

from . import KINDS

PATCHES = Path(__file__).with_name('patches')
REPOSITORY = re.compile(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+')
OID = re.compile(r'[0-9a-f]{40}(?:[0-9a-f]{24})?')


class TrialError(ValueError):
    pass


def repository_name(value):
    if (not REPOSITORY.fullmatch(value) or value.endswith('.git')
            or value.split('/')[-1] in ('.', '..')):
        raise TrialError('use a GitHub OWNER/REPOSITORY name, without a URL or .git suffix')
    if value.casefold() == 'expectrail/expectrail':
        raise TrialError('use a disposable public test repository; never seed Expectrail/Expectrail')
    return value


class Git:
    def __init__(self, repository, index):
        self.repository = Path(repository).resolve()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.env.update(GIT_INDEX_FILE=str(index), GIT_CONFIG_NOSYSTEM='1',
                        GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0',
                        GIT_NO_LAZY_FETCH='1', GIT_NO_REPLACE_OBJECTS='1')

    def run(self, *args, data=None):
        result = subprocess.run(['git', '--no-replace-objects', '-c', 'core.hooksPath=' + os.devnull,
                                 '-c', 'core.fsmonitor=false', '-c', 'commit.gpgSign=false',
                                 '-c', 'protocol.allow=never', '-C', str(self.repository), *args],
                                input=data, capture_output=True, env=self.env, timeout=60)
        if result.returncode:
            raise TrialError('local Git refused ' + args[0] + ': ' + result.stderr.decode(errors='replace')[:400])
        return result.stdout.decode().strip()

    def commit(self, parent, message, timestamp):
        self.env.update(GIT_AUTHOR_NAME='Expectrail trial', GIT_AUTHOR_EMAIL='trial@expectrail.invalid',
                        GIT_COMMITTER_NAME='Expectrail trial', GIT_COMMITTER_EMAIL='trial@expectrail.invalid',
                        GIT_AUTHOR_DATE=f'{timestamp} +0000', GIT_COMMITTER_DATE=f'{timestamp} +0000')
        return self.run('commit-tree', self.run('write-tree'), '-p', parent, data=(message+'\n').encode())

    def patch(self, name):
        self.run('apply', '--cached', '--directory=game/platformer', str(PATCHES/(name+'.patch')))


def expectation(kind):
    if kind in ('correct-fix', 'fork'):
        return ('Expectrail evidence=success; Expectrail clearance=success; both summaries "accept". '
                'The trusted comment must say the repair is demonstrated for player-stays-above-ground '
                '3 times of 3 on both sides. Missing recorded answers are FAIL, never substituted with a model.')
    if kind in ('wrong-fix', 'branch-enforcement'):
        return ('Expectrail evidence=success; Expectrail clearance=failure, summary "reject". '
                'The comment names player-stays-above-ground with after=fail and a reason. '
                'Branch enforcement additionally needs a person to observe a blocked non-bypass merge.')
    if kind == 'new-head':
        return ('Old capture must not clear the new SHA. Explicit refusal: Expectrail clearance=failure, '
                '"Superseded capture or pull request" (if judgment started), or the current-merge identity '
                'refusal. If start sees no matching current PR, it skips without reason text. '
                'The reader reports FAIL/incomplete for absence alone; see the timing instructions.')
    return ('For actual substituted downloaded bytes: Expectrail evidence=success; Expectrail '
            'clearance=failure; reason contains EVIDENCE_MISMATCH. A PR cannot replace an already '
            'uploaded artifact through the normal workflow. The local mutation is a rehearsal, not hosted proof.')


def prepare(kind, *, target, repository='.', out=None, fork=None):
    if kind not in KINDS:
        raise TrialError('unknown trial')
    target = repository_name(target)
    if kind == 'fork':
        if fork is None or repository_name(fork).casefold() == target.casefold():
            raise TrialError('--fork must name a different, existing fork of the test repository')
    elif fork is not None:
        raise TrialError('--fork is only for the fork trial')
    # No checkout, working-index update, hook, fetch, push or GitHub call occurs.
    with tempfile.TemporaryDirectory(prefix='expectrail-trial-index-') as tmp:
        git = Git(repository, Path(tmp)/'index')
        source = git.run('rev-parse', '--verify', 'refs/remotes/origin/main^{commit}')
        if not OID.fullmatch(source):
            raise TrialError('origin/main did not resolve to a full commit; fetch main yourself first')
        prefix = 'expectrail-trials/' + source[:12]
        base_ref, head_ref = prefix+'/base', prefix+'/'+kind
        destination = Path(out or ('work/gate-trials/'+kind)).resolve()
        if destination.exists():
            raise TrialError('output folder already exists; choose a new --out (nothing is overwritten)')
        timestamp = int(git.run('show', '-s', '--format=%ct', source))
        git.run('read-tree', source)
        git.patch('seed')
        base = git.commit(source, 'Expectrail trial base: public fall-through seed', timestamp+1)
        git.run('read-tree', base)
        git.patch('wrong' if kind in ('wrong-fix', 'branch-enforcement') else 'correct')
        head = git.commit(base, 'Expectrail hosted trial: '+kind, timestamp+2)
        refs = {base_ref: base, head_ref: head}
        successor = None
        if kind == 'new-head':
            blob = git.run('hash-object', '-w', '--stdin', '--no-filters',
                           data=b'Expectrail hosted trial: the second head after capture.\n')
            git.run('update-index', '--add', '--cacheinfo', '100644,'+blob+',gate-trial-next-head.txt')
            successor = git.commit(head, 'Expectrail hosted trial: second head', timestamp+3)
            refs[head_ref+'-next'] = successor
        existing = git.run('for-each-ref', '--format=%(refname) %(objectname)', 'refs/heads/'+prefix)
        old = dict(line.split() for line in existing.splitlines())
        operations = ['start']
        for name, oid in refs.items():
            ref = 'refs/heads/'+name
            if ref in old:
                if old[ref] != oid:
                    raise TrialError('a trial branch already names different work: '+name)
                operations.append(f'verify {ref} {oid}')
            else:
                operations.append(f'create {ref} {oid}')
        operations += ['prepare', 'commit']
        git.run('update-ref', '--stdin', data=('\n'.join(operations)+'\n').encode())
    url = 'https://github.com/'+target+'.git'
    head_url = 'https://github.com/'+(fork or target)+'.git'
    commands = ['git push -- '+shlex.quote(url)+' '+base_ref+':refs/heads/'+base_ref,
                'git push -- '+shlex.quote(head_url)+' '+head_ref+':refs/heads/'+head_ref]
    if successor:
        commands.append('git push -- '+shlex.quote(url)+' '+successor+':refs/heads/'+head_ref)
    plan = dict(trial=kind, target=target, fork=fork, sourceMain=source, baseBranch=base_ref,
                headBranch=head_ref, base=base, head=head, nextHead=successor,
                pushCommands=commands, expected=expectation(kind))
    destination.mkdir(parents=True)
    (destination/'plan.json').write_text(json.dumps(plan, indent=2)+'\n')
    body = f'Expectrail-Trial: {kind}\nExpectrail-Intent: fix\n'
    if successor:
        body += f'Expectrail-Capture-Head: {head}\nExpectrail-Next-Head: {successor}\n'
    body += f'\nPrepared from Expectrail main {source}. Public seed; no policy change.\n'
    (destination/'pr-body.txt').write_text(body)
    (destination/'steps.txt').write_text(render(plan)+'\n')
    return plan


def render(plan):
    lines = [f"Prepared {plan['trial']} from origin/main {plan['sourceMain']}",
             'Only local refs were created; your working tree and index were not changed.',
             'Sean runs these, from this checkout (no push was executed):',
             *plan['pushCommands'][:2],
             f"In {plan['target']}, set the disposable repository's default branch to {plan['baseBranch']}.",
             f"Open a PR into {plan['baseBranch']} from {plan['headBranch']}; paste pr-body.txt.",
             'Do not merge a seeded trial into Expectrail/Expectrail.', 'Expected: '+plan['expected']]
    if plan['nextHead']:
        lines += ['AFTER the FIRST capture finishes, push the second head:', plan['pushCommands'][2],
                  'Do not push the -next branch first. Read docs/gate-trials.md for the race and manual pause limitation.']
    if plan['trial'] == 'fork':
        lines += [f"Choose {plan['fork']} as the PR head repository; {plan['target']} is the base repository.",
                  'Confirm the candidate has contents:read, no secrets and no persisted credentials; '
                  'the trusted publisher loads default-branch code and evaluates base policy.']
    if plan['trial'] == 'tamper':
        lines += ['No PR-only hosted substitution step exists in the unchanged workflow.',
                  'Use python3 -m tools.gate_trials.tamper --capture capture.zip --out altered.zip for a local copy.',
                  'For hosted proof Sean needs a separately reviewed test-only trusted-job pause/substitution; see README.']
    if plan['trial'] == 'branch-enforcement':
        lines += ['Follow the exact settings and blocked-merge checklist in tools/gate_trials/README.md.',
                  'The public reader cannot certify branch rules or a blocked merge.']
    return '\n'.join(lines)


def script(kind, argv=None):
    parser = argparse.ArgumentParser(description='Prepare local '+kind+' trial; never pushes or calls GitHub.')
    parser.add_argument('--target', required=True, help='existing disposable public OWNER/REPOSITORY')
    parser.add_argument('--repository', default='.')
    parser.add_argument('--out')
    parser.add_argument('--fork', help='existing OWNER/REPOSITORY fork; fork trial only')
    args = parser.parse_args(argv)
    try:
        plan = prepare(kind, **vars(args))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(2, 'Expectrail trial: '+str(exc)+'\n')
    print(render(plan))
    return 0
