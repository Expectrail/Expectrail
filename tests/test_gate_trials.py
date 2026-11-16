"""Real local Git preparation; saved public GitHub records; no optional pixel packages."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error
import zipfile

from tools.gate_trials import APP_ID, CLEARANCE, EVIDENCE, IDENTITY_REASON, MARKER, STALE_REASON
from tools.gate_trials import build, read, tamper
from tools.gate_trials.__main__ import main

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT/'tests/fixtures/gate_trials'


def hosted(name='accept'):
    return json.loads((FIXTURES/('hosted-'+name+'.json')).read_text())


def controlled(kind='correct-fix'):
    data = hosted()
    data['repository'] = 'someone/expectrail-test'
    pull = data['pull']
    pull['base']['repo']['full_name'] = data['repository']
    pull['head']['repo']['full_name'] = data['repository']
    pull['body'] = 'Expectrail-Trial: '+kind+'\nExpectrail-Intent: fix\n'
    pull['head']['ref'] = 'expectrail-trials/a98dcb08c2d7/'+kind
    body = data['comments'][0]['body']
    body = body.replace('nothing declared: judged as a change that should break no check',
        'a fix, and the repair is demonstrated: player-stays-above-ground on smoke failed before the change '
        '3 times of 3 and passes after it 3 times of 3')
    data['comments'][0]['body'] = body
    return data


class ReaderTest(unittest.TestCase):
    def test_saved_hosted_accept_is_generic_not_seeded(self):
        result = read.evaluate(hosted())
        self.assertEqual((result['result'], result['trial']), ('PASS', 'historical-accept'))
        self.assertIn('not a seeded', ' '.join(result['evidence']))

    def test_saved_hosted_identity_refusal_uses_checks_not_overwritten_comment(self):
        data = hosted('identity')
        self.assertNotIn(data['selectedHead'][:12], data['comments'][0]['body'])
        result = read.evaluate(data)
        self.assertEqual((result['result'], result['trial']), ('PASS', 'identity-refusal'))
        self.assertIn(IDENTITY_REASON, ' '.join(result['evidence']))

    def test_correct_fix_requires_real_repair_demonstration_in_comment(self):
        data = controlled()
        self.assertEqual(read.evaluate(data)['result'], 'PASS')
        data['comments'][0]['body'] = hosted()['comments'][0]['body']
        result = read.evaluate(data)
        self.assertEqual(result['result'], 'FAIL')
        self.assertIn('3/3', result['reason'])

    def wrong(self, kind='wrong-fix'):
        data = controlled(kind)
        for row in data['check_runs']:
            row['output']['summary'] = 'reject'
            if row['name'] == CLEARANCE:
                row['conclusion'] = 'failure'
        data['comments'][0]['body'] = data['comments'][0]['body'].replace('### Expectrail: accept', '### Expectrail: reject')
        data['comments'][0]['body'] += '\n| `123456789abc` | player-stays-above-ground | smoke | fail | fail | STILL_FAILING | player falls below ground |\n'
        return data

    def test_wrong_fix_requires_failure_and_named_failing_check(self):
        data = self.wrong()
        self.assertEqual(read.evaluate(data)['result'], 'PASS')
        for change in ('check', 'reason', 'clearance'):
            with self.subTest(change=change):
                bad = copy.deepcopy(data)
                if change == 'check':
                    bad['comments'][0]['body'] = bad['comments'][0]['body'].replace('| smoke | fail | fail |', '| smoke | fail | pass |')
                elif change == 'reason':
                    bad['comments'][0]['body'] = bad['comments'][0]['body'].replace('| player falls below ground |', '|  |')
                else:
                    bad['check_runs'][1]['conclusion'] = 'success'
                self.assertEqual(read.evaluate(bad)['result'], 'FAIL')

    def test_same_named_fake_app_old_head_old_comment_and_incomplete_pairs_fail(self):
        for change in ('app', 'head', 'comment-user', 'comment-head', 'base', 'pair', 'external-id'):
            with self.subTest(change=change):
                data = controlled()
                if change == 'app':
                    data['check_runs'][1]['app']['id'] = APP_ID+1
                elif change == 'head':
                    data['check_runs'][1]['head_sha'] = '0'*40
                elif change == 'comment-user':
                    data['comments'][0]['user']['login'] = 'someone'
                elif change == 'comment-head':
                    data['comments'][0]['body'] = data['comments'][0]['body'].replace(data['selectedHead'][:12], '0'*12)
                elif change == 'base':
                    data['comments'][0]['body'] = data['comments'][0]['body'].replace(data['pull']['base']['sha'][:12], '0'*12)
                elif change == 'pair':
                    data['check_runs'].pop()
                else:
                    data['check_runs'][1]['external_id'] = 'expectrail/1/1'
                self.assertEqual(read.evaluate(data)['result'], 'FAIL')

    def test_pending_newer_attempt_never_falls_back_to_old_success(self):
        data = controlled()
        next_pair = copy.deepcopy(data['check_runs'])
        for row in next_pair:
            row['external_id'] = row['external_id'].rsplit('/', 1)[0]+'/2'
            row['status'] = 'in_progress'
            row['conclusion'] = None
        data['check_runs'] += next_pair
        result = read.evaluate(data)
        self.assertEqual(result['result'], 'FAIL')
        self.assertIn('not complete', result['reason'])

    def test_pairs_cannot_mix_attempts_or_duplicate_names(self):
        data = controlled()
        data['check_runs'].append(copy.deepcopy(data['check_runs'][0]))
        self.assertIn('duplicate', read.evaluate(data)['reason'])

    def test_half_published_pair_with_different_summaries_is_incomplete(self):
        data = controlled()
        data['check_runs'][0]['output']['summary'] = STALE_REASON
        result = read.evaluate(data)
        self.assertEqual(result['result'], 'FAIL')
        self.assertIn('publication may still be in progress', result['reason'])

    def test_unknown_conflicting_or_duplicate_trial_is_not_inferred_from_green(self):
        for body, branch in [('', 'ordinary-branch'), ('Expectrail-Trial: wrong-fix', 'expectrail-trials/a98dcb08c2d7/correct-fix'),
                             ('Expectrail-Trial: typo', 'ordinary-branch'),
                             ('Expectrail-Trial: correct-fix\nExpectrail-Trial: correct-fix', 'ordinary-branch')]:
            with self.subTest(body=body):
                data = controlled()
                data['pull']['body'], data['pull']['head']['ref'] = body, branch
                self.assertEqual(read.evaluate(data)['result'], 'FAIL')

    def test_tamper_requires_explicit_mismatch_in_check_and_bound_comment(self):
        data = controlled('tamper')
        data['check_runs'][1]['conclusion'] = 'failure'
        for row in data['check_runs']:
            row['output']['summary'] = 'EVIDENCE_MISMATCH: replay bytes differ'
        data['comments'][0]['body'] = data['comments'][0]['body'].replace('### Expectrail: accept', '### Expectrail: needs review')+'\nEVIDENCE_MISMATCH: replay bytes differ'
        self.assertEqual(read.evaluate(data)['result'], 'PASS')
        data['comments'][0]['body'] = data['comments'][0]['body'].replace('EVIDENCE_MISMATCH', 'missing')
        self.assertEqual(read.evaluate(data)['result'], 'FAIL')

    def test_fork_requires_different_repository_and_trusted_boundary_comment(self):
        data = controlled('fork')
        self.assertEqual(read.evaluate(data)['result'], 'FAIL')
        data['pull']['head']['repo']['full_name'] = 'someone-else/expectrail-test'
        self.assertEqual(read.evaluate(data)['result'], 'FAIL')
        data['comments'][0]['body'] += "\nA fork's pull request gets no secrets"
        self.assertEqual(read.evaluate(data)['result'], 'PASS')

    def test_branch_enforcement_is_never_invented_from_red_checks(self):
        result = read.evaluate(self.wrong('branch-enforcement'))
        self.assertEqual(result['result'], 'FAIL')
        self.assertIn('blocked non-bypass merge', result['reason'])

    def stale(self):
        data = controlled('new-head')
        old = data['selectedHead']
        new = 'a'*40
        data['pull']['body'] += f'Expectrail-Capture-Head: {old}\nExpectrail-Next-Head: {new}\n'
        data['pull']['head']['sha'] = data['selectedHead'] = new
        data['check_runs'][1]['conclusion'] = 'failure'
        for row in data['check_runs']:
            row['output']['summary'] = STALE_REASON
        data['captures'][0].update(updated_at='2026-11-15T22:16:41Z', status='completed')
        data['captures'].append(dict(id=999, head_sha=new, event='pull_request', created_at='2026-11-15T22:16:42Z'))
        return data

    def test_new_head_requires_old_refusal_and_after_capture_timing(self):
        data = self.stale()
        self.assertEqual(read.evaluate(data)['result'], 'PASS')
        for change in ('timing', 'refusal-before-push', 'old-success', 'no-output', 'wrong-next'):
            with self.subTest(change=change):
                bad = copy.deepcopy(data)
                if change == 'timing':
                    bad['captures'][1]['created_at'] = '2026-11-15T22:16:40Z'
                elif change == 'refusal-before-push':
                    bad['check_runs'][1]['completed_at'] = '2026-11-15T22:16:41Z'
                elif change == 'old-success':
                    bad['check_runs'][1]['conclusion'] = 'success'
                elif change == 'no-output':
                    bad['check_runs'][1]['status'] = 'in_progress'
                else:
                    bad['pull']['body'] = bad['pull']['body'].replace('Expectrail-Next-Head: '+'a'*40, 'Expectrail-Next-Head: '+'b'*40)
                self.assertEqual(read.evaluate(bad)['result'], 'FAIL')

    def test_terminal_controls_from_public_text_are_not_printed(self):
        text = read.render(dict(result='PASS', trial='example', evidence=['text\x1b[31m\nnext']))
        self.assertNotIn('\x1b', text)
        self.assertNotIn('\nnext', text)

    def test_fixture_cli_replays_both_saved_hosted_results_offline(self):
        for name, result in [('accept', 'historical-accept'), ('identity', 'identity-refusal')]:
            with self.subTest(name=name), mock.patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network')):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = main(['read', '--pr', '514', '--fixture', str(FIXTURES/('hosted-'+name+'.json'))])
                self.assertEqual(code, 0)
                self.assertIn('PASS '+result, out.getvalue())


class PublicAPITest(unittest.TestCase):
    def test_public_get_never_uses_environment_tokens_or_redirects(self):
        api = read.PublicAPI()
        seen = []
        def opened(request, **kwargs):
            seen.append(request)
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = b'{"ok":true}'
            return response
        with mock.patch.dict(os.environ, {'GH_TOKEN':'stand-in', 'GITHUB_TOKEN':'stand-in'}), mock.patch.object(api, 'open', side_effect=opened):
            self.assertEqual(api.get('/repos/Expectrail/Expectrail/pulls/514'), {'ok':True})
        self.assertEqual(seen[0].method, 'GET')
        self.assertNotIn('Authorization', seen[0].headers)
        self.assertIsNone(read.NoRedirect().redirect_request(None, None, None, None, None, None))

    def test_pagination_is_complete_or_fail_never_truncated(self):
        api = read.PublicAPI()
        with mock.patch.object(api, 'get', side_effect=[{'check_runs':list(range(100))}, {'check_runs':[100]}]) as get:
            self.assertEqual(len(api.pages('/repos/o/r/check-runs?filter=all', 'check_runs')), 101)
            self.assertIn('page=2', get.call_args.args[0])
        with mock.patch.object(read, 'MAX_PAGES', 1), mock.patch.object(api, 'get', return_value=list(range(100))):
            with self.assertRaisesRegex(build.TrialError, 'pagination'):
                api.pages('/repos/o/r/comments')

    def test_http_failures_and_oversize_are_plain_failures(self):
        api = read.PublicAPI()
        with mock.patch.object(api, 'open', side_effect=urllib.error.HTTPError('url',403,'rate limit',{},None)):
            with self.assertRaisesRegex(build.TrialError, 'no token'):
                api.get('/repos/o/r/pulls/1')
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b' '*8
        with mock.patch.object(read, 'MAX_BYTES', 7), mock.patch.object(api, 'open', return_value=response):
            with self.assertRaisesRegex(build.TrialError, 'no partial'):
                api.get('/repos/o/r/pulls/1')

    def test_collector_reads_only_public_paths_including_old_head_timing(self):
        data = ReaderTest().stale()
        api = mock.Mock()
        api.get.return_value = data['pull']
        api.pages.side_effect = lambda path,key=None: data['check_runs'] if key=='check_runs' else data['captures'] if key=='workflow_runs' else data['comments']
        found = read.collect('someone/expectrail-test', 514, api=api)
        self.assertEqual(found['selectedHead'], 'a'*40)
        self.assertEqual(api.pages.call_count, 5)
        self.assertTrue(all(c.args[0].startswith('/repos/someone/expectrail-test/') for c in api.pages.call_args_list))


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root/'repo'
        self.repo.mkdir()
        for name in ('game/platformer/player/player.tscn', 'game/platformer/player/player.gd',
                     '.github/workflows/expectrail-verify.yml', '.github/workflows/expectrail-capture.yml'):
            path = self.repo/name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT/name, path)
        self.git('init', '-q', '--initial-branch=main')
        self.git('add', '.')
        self.git('commit', '-qm', 'source main')
        self.source = self.git('rev-parse', 'HEAD')
        self.git('update-ref', 'refs/remotes/origin/main', self.source)
        self.original_index = (self.repo/'.git/index').read_bytes()
        self.original = {p.relative_to(self.repo):p.read_bytes() for p in (self.repo/'game').rglob('*') if p.is_file()}

    def git(self, *args):
        env = {k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
        return subprocess.check_output(['git', '-c', 'user.name=Expectrail test', '-c', 'user.email=test@expectrail.invalid',
             '-c', 'commit.gpgSign=false', '-c', 'core.hooksPath='+os.devnull, '-C', str(self.repo), *args], env=env).decode().strip()

    def plan(self, kind, **kw):
        return build.prepare(kind, target='someone/expectrail-test', repository=self.repo, out=self.root/kind, **kw)

    def test_all_trials_are_local_refs_built_from_main_with_patch_changes_only(self):
        with mock.patch('urllib.request.urlopen', side_effect=AssertionError('network')):
            for kind in build.KINDS:
                with self.subTest(kind=kind):
                    plan = self.plan(kind, **({'fork':'another/expectrail-test'} if kind=='fork' else {}))
                    self.assertEqual(plan['sourceMain'], self.source)
                    self.assertEqual(self.git('rev-parse', plan['base']+'^'), self.source)
                    self.assertIn('collision_mask = 14', self.git('show', plan['base']+':game/platformer/player/player.tscn'))
                    text = self.git('show', plan['head']+':game/platformer/player/player.tscn')
                    self.assertIn('collision_mask = '+('14' if kind in ('wrong-fix','branch-enforcement') else '30'), text)
                    if kind in ('wrong-fix','branch-enforcement'):
                        self.assertIn('Fixed the fall-through', self.git('show', plan['head']+':game/platformer/player/player.gd'))
                    else:
                        self.assertEqual(self.git('rev-parse', plan['head']+'^{tree}'), self.git('rev-parse', self.source+'^{tree}'))
                    self.assertIn('git push -- https://github.com/', build.render(plan))
                    self.assertEqual(self.git('diff', '--name-only', self.source, plan['base']), 'game/platformer/player/player.tscn')
        self.assertEqual((self.repo/'.git/index').read_bytes(), self.original_index)
        for name, data in self.original.items():
            self.assertEqual((self.repo/name).read_bytes(), data)
        self.assertEqual(self.git('rev-parse','HEAD'), self.source)

    def test_second_head_is_prepared_but_not_pushed_or_installed_as_first_head(self):
        plan = self.plan('new-head')
        self.assertEqual(self.git('rev-parse', plan['headBranch']), plan['head'])
        self.assertEqual(self.git('rev-parse', plan['nextHead']+'^'), plan['head'])
        self.assertNotEqual(plan['nextHead'], plan['head'])
        self.assertIn(plan['nextHead']+':refs/heads/'+plan['headBranch'], plan['pushCommands'][2])
        self.assertIn('AFTER the FIRST capture', build.render(plan))

    def test_source_repo_push_target_invalid_fork_and_existing_output_are_refused(self):
        for target in ('Expectrail/Expectrail','expectrail/expectrail','https://github.com/o/r','o/r;echo','o/r.git'):
            with self.subTest(target=target), self.assertRaises(build.TrialError):
                build.prepare('correct-fix', target=target, repository=self.repo, out=self.root/'bad')
        with self.assertRaisesRegex(build.TrialError, '--fork'):
            self.plan('fork')
        plan = self.plan('correct-fix')
        with self.assertRaisesRegex(build.TrialError, 'exists'):
            self.plan('correct-fix')
        # Existing refs are reused only when they match; user work is not overwritten.
        self.git('update-ref', 'refs/heads/'+plan['headBranch'], self.source)
        with self.assertRaisesRegex(build.TrialError, 'different work'):
            build.prepare('correct-fix', target='someone/expectrail-test', repository=self.repo, out=self.root/'other')

    def test_hooks_are_not_run_and_no_checkout_commit_or_push_command_is_executed(self):
        marker = self.root/'executed'
        hook = self.repo/'.git/hooks/reference-transaction'
        hook.write_text('#!/bin/sh\ntouch '+str(marker)+'\n')
        hook.chmod(0o755)
        real = subprocess.run
        calls = []
        def run(argv, **kw):
            calls.append(argv)
            return real(argv, **kw)
        with mock.patch.object(build.subprocess, 'run', side_effect=run):
            self.plan('correct-fix')
        self.assertFalse(marker.exists())
        self.assertTrue(calls)
        self.assertFalse(any('push' in c or 'checkout' in c or 'commit' in c or 'fetch' in c for c in calls))


class TamperTest(unittest.TestCase):
    def test_mutated_capture_is_refused_by_the_actual_judge_before_any_observer(self):
        from tests import test_ci_gate as cases
        case = cases.SplitGateTest('test_bundle_edits_fail_before_the_observer')
        try:
            case.setUp()
            case.capture()
            original = case.archive
            original_bytes = original.read_bytes()
            altered = case.root/'altered.zip'
            tamper.mutate(original, altered)
            case.archive = altered
            with self.assertRaisesRegex(ValueError, 'EVIDENCE_MISMATCH'):
                case.judge()
            self.assertEqual(original.read_bytes(), original_bytes)
            self.assertEqual(case.model.asked, [])
        finally:
            case.doCleanups()

    def test_mutator_changes_only_one_trace_and_keeps_original_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, out = root/'capture.zip', root/'altered.zip'
            with zipfile.ZipFile(source, 'w') as archive:
                archive.writestr('manifest.json', b'{"example":true}')
                archive.writestr('head-1/route/trace.json', b'{"rows":[]}')
                archive.writestr('head-1/route/frames/f00000000.png', b'frame')
            original = source.read_bytes()
            self.assertEqual(tamper.mutate(source, out), 'head-1/route/trace.json')
            self.assertEqual(source.read_bytes(), original)
            with zipfile.ZipFile(source) as a, zipfile.ZipFile(out) as b:
                self.assertEqual(a.namelist(), b.namelist())
                self.assertEqual(a.read('manifest.json'), b.read('manifest.json'))
                self.assertEqual(b.read('head-1/route/trace.json'), a.read('head-1/route/trace.json')+b' ')
            with self.assertRaises(build.TrialError):
                tamper.mutate(source, source)
            with self.assertRaises(build.TrialError):
                tamper.mutate(source, out)

    def test_source_workflows_prove_no_pr_only_between_job_replacement_hook(self):
        capture = (ROOT/'.github/workflows/expectrail-capture.yml').read_text()
        trusted = (ROOT/'.github/workflows/expectrail-comment.yml').read_text()
        checks = (ROOT/'tools/ci_checks.py').read_text()
        self.assertNotIn('secrets.', capture)
        self.assertIn('permissions:\n  contents: read', capture)
        self.assertIn('github.event.pull_request.base.sha', capture)
        self.assertIn('actions/upload-artifact@043fb46d', capture)
        self.assertIn('ref: ${{ github.workflow_sha }}', trusted)
        self.assertIn('working-directory: policy', trusted)
        self.assertIn('python3 -m tools.ci_checks download', trusted)
        self.assertIn('download differs from GitHub', checks)
        self.assertIn('candidate workflow differs from the trusted base', checks)
