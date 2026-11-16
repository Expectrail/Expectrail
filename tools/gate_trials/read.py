"""Read public GitHub evidence. No token lookup, authentication or mutation API."""
from __future__ import annotations

from datetime import datetime
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from . import APP_ID, APP_SLUG, CLEARANCE, EVIDENCE, IDENTITY_REASON, KINDS, MARKER, SPEC, STALE_REASON
from .build import OID, REPOSITORY, TrialError

API = 'https://api.github.com'
MAX_BYTES = 8*1024**2
MAX_PAGES = 10
HISTORICAL = {
    ('Expectrail/Expectrail', 514, '6740d7e5cdcab974e9aa492b898c976e0a76e4d1', 'expectrail/43768258238/1'): 'historical-accept',
    ('Expectrail/Expectrail', 514, 'cd2e9eeb44bac37a15a150f891331391cd8ac8d9', 'expectrail/43766433329/1'): 'identity-refusal',
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class PublicAPI:
    def __init__(self):
        self.open = urllib.request.build_opener(NoRedirect()).open

    def get(self, path):
        if not path.startswith('/repos/') or any(ord(c)<32 for c in path):
            raise TrialError('not a public repository API path')
        request = urllib.request.Request(API+path, method='GET', headers={
            'User-Agent': 'Expectrail-gate-trials', 'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with self.open(request, timeout=30) as response:
                data = response.read(MAX_BYTES+1)
            if len(data)>MAX_BYTES:
                raise TrialError('public API response exceeds 8 MiB; no partial result is credited')
            return json.loads(data)
        except (OSError, ValueError) as exc:
            if isinstance(exc, TrialError):
                raise
            raise TrialError('public GitHub GET failed (missing/public access, rate limit or invalid response); '
                             'no token is used: '+str(exc)) from exc

    def pages(self, path, key=None):
        rows = []
        for page in range(1, MAX_PAGES+1):
            result = self.get(path+('&' if '?' in path else '?')+f'per_page=100&page={page}')
            items = result[key] if key else result
            if not isinstance(items, list):
                raise TrialError('public API did not return a list')
            rows.extend(items)
            if len(items)<100:
                return rows
        raise TrialError('public evidence exceeds pagination bound; no truncated result is credited')


def field(body, name):
    found = re.findall(r'^'+re.escape(name)+r':[ \t]*(\S+)[ \t]*$', body or '', flags=re.M)
    if len(found)>1:
        raise TrialError('duplicate '+name+' declaration')
    return found[0] if found else None


def pair(rows, head, app_id):
    groups = {}
    for row in rows:
        if (row.get('name') not in (EVIDENCE, CLEARANCE) or row.get('head_sha') != head
                or row.get('app', {}).get('id') != app_id or row.get('app', {}).get('slug') != APP_SLUG):
            continue
        match = re.fullmatch(r'expectrail/(\d+)/(\d+)', row.get('external_id') or '')
        if not match:
            continue
        groups.setdefault(tuple(map(int, match.groups())), []).append(row)
    if not groups:
        raise TrialError('no dedicated-App check pair for the selected full head')
    key = max(groups)
    chosen = groups[key]
    by_name = {}
    for row in chosen:
        if row['name'] in by_name:
            raise TrialError('duplicate checks in the latest capture attempt')
        by_name[row['name']] = row
    if set(by_name) != {EVIDENCE, CLEARANCE}:
        raise TrialError('latest capture attempt has an incomplete check pair')
    if any(r.get('status') != 'completed' for r in chosen):
        raise TrialError('latest capture attempt is not complete; older success is not reused')
    return by_name


def comment_for(rows, head):
    found = [r for r in rows if r.get('user', {}).get('login') == 'github-actions[bot]'
             and r.get('user', {}).get('type') == 'Bot' and r.get('body', '').startswith(MARKER)
             and f'Commit `{head[:12]}`' in r['body']]
    if not found:
        raise TrialError('no trusted bot comment bound to this head (old comments are not reused)')
    return max(found, key=lambda r:(r.get('updated_at', ''), r.get('id', 0)))


def collect(repo, number, *, api=None, head=None):
    if not REPOSITORY.fullmatch(repo) or not isinstance(number, int) or number<=0:
        raise TrialError('give --repo OWNER/REPOSITORY and a positive --pr number')
    api = api or PublicAPI()
    root = '/repos/'+repo
    pull = api.get(root+f'/pulls/{number}')
    selected = head or pull['head']['sha']
    if not OID.fullmatch(selected):
        raise TrialError('--head must be a full commit ID')
    heads = {selected}
    previous = field(pull.get('body'), 'Expectrail-Capture-Head')
    if previous:
        if not OID.fullmatch(previous):
            raise TrialError('Expectrail-Capture-Head must be a full commit ID')
        heads.add(previous)
    checks = []
    for sha in sorted(heads):
        checks.extend(api.pages(root+f'/commits/{sha}/check-runs?filter=all', 'check_runs'))
    comments = api.pages(root+f'/issues/{number}/comments')
    # Stale-head timing needs actual capture-run timestamps, not a local commit date.
    captures = []
    if previous:
        for sha in sorted(heads):
            query = urllib.parse.urlencode({'event':'pull_request', 'head_sha':sha})
            captures.extend(api.pages(root+'/actions/workflows/expectrail-verify.yml/runs?'+query, 'workflow_runs'))
    return dict(repository=repo, pull=pull, selectedHead=selected, check_runs=checks, comments=comments, captures=captures)


def identify(snapshot, selected, checks):
    pull = snapshot['pull']
    declared = field(pull.get('body'), 'Expectrail-Trial')
    branch = re.fullmatch(r'expectrail-trials/[a-f0-9]{12}/('+ '|'.join(KINDS)+')', pull['head']['ref'])
    inferred = branch.group(1) if branch else None
    if declared and inferred and declared != inferred:
        raise TrialError('PR trial declaration conflicts with its branch')
    trial = declared or inferred
    if trial:
        if trial not in KINDS:
            raise TrialError('unknown trial declaration')
        return trial
    key = (snapshot['repository'], pull['number'], selected, checks[CLEARANCE]['external_id'])
    if key not in HISTORICAL:
        raise TrialError('no matching trial; an arbitrary green PR is not a seeded-fix proof')
    return HISTORICAL[key]


def require(condition, reason):
    if not condition:
        raise TrialError(reason)


def lines(checks):
    return [f"{name}: {checks[name]['conclusion']}; {checks[name].get('output', {}).get('summary', '')}; "
            f"{checks[name].get('html_url', '')}" for name in (EVIDENCE, CLEARANCE)]


def evaluate(snapshot, *, app_id=APP_ID):
    trial, evidence = 'unmatched', []
    try:
        pull = snapshot['pull']
        selected = snapshot.get('selectedHead') or pull['head']['sha']
        require(bool(OID.fullmatch(selected)), 'selected head is not a full commit ID')
        # new-head expectations examine the old pair, while pinning the current PR head separately.
        declared = field(pull.get('body'), 'Expectrail-Trial')
        matched = re.fullmatch(r'expectrail-trials/[a-f0-9]{12}/('+ '|'.join(KINDS)+')', pull['head']['ref'])
        trial = declared or (matched.group(1) if matched else 'unmatched')
        stale = declared == 'new-head' or pull['head']['ref'].endswith('/new-head')
        old = field(pull.get('body'), 'Expectrail-Capture-Head') if stale else None
        check_head = old or selected
        checks = pair(snapshot['check_runs'], check_head, app_id)
        trial = identify(snapshot, selected, checks)
        evidence += lines(checks)
        require(trial in ('historical-accept', 'identity-refusal') or selected == pull['head']['sha'],
                'a controlled trial must judge the current PR head')
        summary = checks[CLEARANCE].get('output', {}).get('summary', '')
        require(checks[EVIDENCE]['conclusion'] == 'success', 'Expectrail evidence did not finish successfully')
        require(checks[EVIDENCE].get('output', {}).get('summary', '') == summary,
                'check-pair summaries disagree; publication may still be in progress')
        if trial == 'identity-refusal':
            require(checks[CLEARANCE]['conclusion'] == 'failure' and IDENTITY_REASON in summary,
                    'the saved identity-refusal pair did not refuse for its recorded reason')
            evidence.append('Historical identity refusal only. Its earlier bot comment was overwritten; '
                            'the current comment is retained as context, not old-head proof.')
        elif trial == 'new-head':
            require(old and OID.fullmatch(old) and old != pull['head']['sha'], 'the PR has not advanced from its capture head')
            require(field(pull.get('body'), 'Expectrail-Next-Head') == pull['head']['sha'], 'current head is not the prepared second commit')
            require(checks[CLEARANCE]['conclusion'] == 'failure' and
                    any(reason in summary for reason in (STALE_REASON, IDENTITY_REASON, 'the candidate ran on a different PR or base')),
                    'no explicit stale-capture refusal; missing/pending old checks alone are incomplete evidence')
            run_id = int(checks[CLEARANCE]['external_id'].split('/')[1])
            captured = [r for r in snapshot.get('captures', []) if r.get('id') == run_id and r.get('head_sha') == old
                        and r.get('conclusion') == 'success' and r.get('status') == 'completed']
            newer = [r for r in snapshot.get('captures', []) if r.get('head_sha') == selected and r.get('event') == 'pull_request']
            require(bool(captured and newer), 'capture timing records are missing')
            end = datetime.fromisoformat(captured[0]['updated_at'].replace('Z', '+00:00'))
            refused = datetime.fromisoformat(checks[CLEARANCE]['completed_at'].replace('Z', '+00:00'))
            require(any(end < datetime.fromisoformat(r['created_at'].replace('Z', '+00:00')) < refused for r in newer),
                    'timing does not prove first capture, new head, then stale refusal in that order')
            # A current-head success is allowed only from its own, distinct capture pair.
            for row in snapshot['check_runs']:
                require(not (row.get('head_sha') == selected and row.get('name') == CLEARANCE
                    and row.get('app', {}).get('id') == app_id and row.get('conclusion') == 'success'
                    and row.get('external_id') == checks[CLEARANCE]['external_id']), 'old capture granted current-head clearance')
            evidence.append(f'Old head {old}; current head {selected}; explicit refusal and after-capture timing recorded.')
        else:
            comment = comment_for(snapshot['comments'], selected)
            body = comment['body']
            evidence.append('Comment: '+comment.get('html_url', '')+'; head '+selected[:12])
            if trial == 'tamper':
                require(checks[CLEARANCE]['conclusion'] == 'failure' and 'EVIDENCE_MISMATCH' in summary
                        and 'EVIDENCE_MISMATCH' in body, 'no EVIDENCE_MISMATCH in both check and head-bound comment')
            else:
                require(f"from the base commit `{pull['base']['sha'][:12]}`" in body
                        and 'The trusted job judged the saved replays.' in body, 'comment does not identify trusted base-side judgment')
                if trial in ('wrong-fix', 'branch-enforcement'):
                    require(checks[CLEARANCE]['conclusion'] == 'failure' and summary == 'reject'
                            and '### Expectrail: reject' in body, 'wrong fix was not rejected')
                    failures = []
                    for line in body.splitlines():
                        cells = [c.strip().strip('`*') for c in line.split('|')[1:-1]]
                        if len(cells) == 7 and cells[1] == SPEC and cells[4] == 'fail' and cells[6]:
                            failures.append(line)
                    require(bool(failures), 'comment does not name the failing player-stays-above-ground check and reason')
                    evidence.append(failures[0])
                    require(trial != 'branch-enforcement', 'public checks/comment cannot prove branch settings or a blocked non-bypass merge; complete the manual checklist')
                else:
                    require(checks[CLEARANCE]['conclusion'] == 'success' and summary == 'accept'
                            and '### Expectrail: accept' in body, 'expected accept is missing')
                    if trial != 'historical-accept':
                        require(SPEC in body and 'repair is demonstrated:' in body
                                and '3 times of 3 and passes after it 3 times of 3' in body, 'a seeded repair was not demonstrated 3/3 on both sides')
                    else:
                        evidence.append('Historical generic accept only; not a seeded correct-fix trial.')
                    if trial == 'fork':
                        require(pull['head']['repo']['full_name'] != pull['base']['repo']['full_name'], 'this is a same-repository PR, not a fork')
                        require("A fork's pull request gets no secrets" in body, 'fork boundary statement missing from the trusted comment')
                        evidence.append('PASS covers public fork checks/comment; inspect candidate permissions and trusted checkout using the checklist.')
        return dict(result='PASS', trial=trial, evidence=evidence)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        return dict(result='FAIL', trial=trial, reason=str(exc), evidence=evidence)


def render(result):
    def plain(value):
        return ''.join(c if ord(c)>=32 and ord(c)!=127 else ' ' for c in str(value))[:1600]
    text = plain(result['result'])+' '+plain(result['trial'])
    if result.get('reason'):
        text += ': '+plain(result['reason'])
    for row in result['evidence']:
        # Public text is information, not terminal control or executable instructions.
        text += '\n  '+plain(row)
    return text
