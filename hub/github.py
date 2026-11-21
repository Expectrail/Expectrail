"""The GitHub calls sign-in needs, through an injected transport.

A transport is `transport(method, url, headers, body) -> (status, headers, body)`. The live one uses
urllib; tests pass `tests.hub_stub.FakeGitHub`, so no test reaches github.com. A user token is a
local variable of the one request that needs it: it is never stored, logged or put in a cookie.
"""
import json
import re
from urllib.parse import urlencode
import urllib.error
import urllib.request

WEB = 'https://github.com'
API = 'https://api.github.com'
MAX_BODY = 1024 * 1024
PER_PAGE = 100
MAX_PAGES = 10          # 1,000 installations or repositories per installation, then refuse
REPO_NAME = re.compile(r'[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}')
LOGIN = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})')


class GitHubError(RuntimeError):
    """GitHub did not give a usable answer. The message is safe to show: it holds no credential."""


def urllib_transport(method, url, headers, body):
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, dict(response.headers), response.read(MAX_BODY + 1)
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers or {}), error.read(MAX_BODY + 1)
    except (urllib.error.URLError, OSError, ValueError):
        raise GitHubError('GitHub could not be reached') from None


class GitHub:
    def __init__(self, config, transport=None):
        self.config = config
        self.transport = transport or urllib_transport

    def authorize_url(self, state):
        query = urlencode({'client_id': self.config['client_id'], 'state': state,
                           'redirect_uri': self.config['origin'] + '/callback', 'allow_signup': 'true'})
        return f'{WEB}/login/oauth/authorize?{query}'

    def install_url(self):
        return f'{WEB}/apps/{self.config["app_slug"]}/installations/new'

    def _call(self, method, url, *, token=None, form=None):
        headers = {'Accept': 'application/json', 'User-Agent': 'Expectrail-hub',
                   'X-GitHub-Api-Version': '2022-11-28'}
        body = None
        if token is not None:
            headers['Authorization'] = f'Bearer {token}'
        if form is not None:
            body = urlencode(form).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        status, response_headers, data = self.transport(method, url, headers, body)
        lower = {k.lower(): v for k, v in (response_headers or {}).items()}
        if status in (403, 429) and (lower.get('x-ratelimit-remaining') == '0' or 'retry-after' in lower):
            raise GitHubError('GitHub rate limit reached; try again later')
        if status == 401:
            raise GitHubError('GitHub refused the credentials')
        if not 200 <= status < 300:
            raise GitHubError(f'GitHub answered {status}')
        if data is None or len(data) > MAX_BODY:
            raise GitHubError('GitHub answer missing or too large')
        try:
            return json.loads(data)
        except ValueError:
            raise GitHubError('GitHub answer is not JSON') from None

    def exchange_code(self, code):
        answer = self._call('POST', f'{WEB}/login/oauth/access_token', form={
            'client_id': self.config['client_id'], 'client_secret': self.config['client_secret'],
            'code': code, 'redirect_uri': self.config['origin'] + '/callback'})
        token = answer.get('access_token') if isinstance(answer, dict) else None
        if not isinstance(token, str) or not token:
            raise GitHubError('GitHub did not complete sign-in')
        return token

    def user(self, token):
        answer = self._call('GET', f'{API}/user', token=token)
        uid = answer.get('id') if isinstance(answer, dict) else None
        login = answer.get('login') if isinstance(answer, dict) else None
        if type(uid) is not int or uid <= 0 or not isinstance(login, str) or not LOGIN.fullmatch(login):
            raise GitHubError('GitHub did not name the user')
        return uid, login

    def _pages(self, url, token, key):
        """Every item, or GitHubError: a partial list is never used as the whole."""
        items = []
        for page in range(1, MAX_PAGES + 1):
            answer = self._call('GET', f'{url}?per_page={PER_PAGE}&page={page}', token=token)
            batch = answer.get(key) if isinstance(answer, dict) else None
            total = answer.get('total_count') if isinstance(answer, dict) else None
            if not isinstance(batch, list) or type(total) is not int:
                raise GitHubError('GitHub list answer is malformed')
            items.extend(batch)
            if len(items) >= total or not batch:
                if len(items) != total:
                    raise GitHubError('GitHub list answer is incomplete')
                return items
        raise GitHubError('too many items to list in full')

    def user_access(self, token):
        """{installation id: (account login, {"owner/name", ...})} the signed-in user can see."""
        access = {}
        for item in self._pages(f'{API}/user/installations', token, 'installations'):
            iid = item.get('id') if isinstance(item, dict) else None
            account = item.get('account') if isinstance(item, dict) else None
            login = account.get('login') if isinstance(account, dict) else None
            if type(iid) is not int or iid <= 0 or not isinstance(login, str) or not LOGIN.fullmatch(login):
                raise GitHubError('GitHub installation answer is malformed')
            names = set()
            for repo in self._pages(f'{API}/user/installations/{iid}/repositories', token, 'repositories'):
                name = repo.get('full_name') if isinstance(repo, dict) else None
                if not isinstance(name, str) or not REPO_NAME.fullmatch(name):
                    raise GitHubError('GitHub repository answer is malformed')
                names.add(name)
            access[iid] = (login, names)
        return access
