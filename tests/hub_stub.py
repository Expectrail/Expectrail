"""An offline stand-in for the GitHub App and GitHub's API, for the hub's tests (#712).

`FakeGitHub` is a hub transport: `fake(method, url, headers, body) -> (status, headers, body)`. It
answers the calls `hub.github` makes, from state a test sets up, and records each call so a test can
see which credential reached which endpoint. It opens no socket. `WsgiClient` drives a WSGI app in
process with a cookie jar, so a whole sign-in runs without a server.

The values here are fixtures that look nothing like real credentials.
"""
import hashlib
import hmac
import io
import json
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlencode, urlsplit

CLIENT_ID = 'fixture-client-id'
CLIENT_SECRET = 'fixture-client-secret'
WEBHOOK_SECRET = 'fixture-webhook-secret'
COOKIE_KEY = 'fixture-cookie-key-' + 'x' * 32
ORIGIN = 'https://hub.test'

ENV = {
    'EXPECTRAIL_HUB_CLIENT_ID': CLIENT_ID,
    'EXPECTRAIL_HUB_CLIENT_SECRET': CLIENT_SECRET,
    'EXPECTRAIL_HUB_APP_SLUG': 'expectrail-fixture',
    'EXPECTRAIL_HUB_COOKIE_KEY': COOKIE_KEY,
    'EXPECTRAIL_HUB_WEBHOOK_SECRET': WEBHOOK_SECRET,
    'EXPECTRAIL_HUB_ORIGIN': ORIGIN,
}


class FakeGitHub:
    def __init__(self):
        self.users = {}           # token -> (id, login)
        self.codes = {}           # code -> token, each usable once
        self.installations = {}   # id -> {'account': login, 'repositories': [names], 'users': {uid}}
        self.calls = []           # (method, path, authorization or None)
        self.rate_limited = set() # paths that answer 403 with x-ratelimit-remaining: 0
        self.fail = {}            # path -> status
        self.short = set()        # list paths whose pages run out before total_count

    # setup helpers
    def add_user(self, uid, login, code):
        token = f'fixture-token-{uid}'
        self.users[token] = (uid, login)
        self.codes[code] = token
        return token

    def add_installation(self, iid, account, repositories, users):
        self.installations[iid] = {'account': account, 'repositories': list(repositories), 'users': set(users)}

    def tokens_seen(self):
        return [auth for _, _, auth in self.calls if auth]

    # the transport
    def __call__(self, method, url, headers, body):
        parts = urlsplit(url)
        auth = headers.get('Authorization')
        self.calls.append((method, parts.path, auth))
        if parts.path in self.fail:
            return self.fail[parts.path], {}, b'{}'
        if parts.path in self.rate_limited:
            return 403, {'X-RateLimit-Remaining': '0'}, b'{"message":"API rate limit exceeded"}'
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        if parts.netloc == 'github.com' and parts.path == '/login/oauth/access_token' and method == 'POST':
            form = {k: v[0] for k, v in parse_qs((body or b'').decode()).items()}
            if form.get('client_id') != CLIENT_ID or form.get('client_secret') != CLIENT_SECRET:
                return 200, {}, b'{"error":"incorrect_client_credentials"}'
            if form.get('redirect_uri') != ORIGIN + '/callback':
                return 200, {}, b'{"error":"redirect_uri_mismatch"}'
            token = self.codes.pop(form.get('code'), None)
            if token is None:
                return 200, {}, b'{"error":"bad_verification_code"}'
            return 200, {}, json.dumps({'access_token': token, 'token_type': 'bearer'}).encode()
        if parts.netloc != 'api.github.com':
            return 404, {}, b'{}'
        user = self.users.get((auth or '').removeprefix('Bearer '))
        if user is None:
            return 401, {}, b'{"message":"Bad credentials"}'
        uid, login = user
        page, per = int(query.get('page', 1)), int(query.get('per_page', 30))
        if parts.path == '/user':
            return 200, {}, json.dumps({'id': uid, 'login': login}).encode()
        if parts.path == '/user/installations':
            mine = [{'id': i, 'account': {'login': v['account']}}
                    for i, v in sorted(self.installations.items()) if uid in v['users']]
            return 200, {}, json.dumps({'total_count': len(mine),
                                        'installations': mine[(page - 1) * per: page * per]}).encode()
        segments = parts.path.split('/')
        if len(segments) == 5 and segments[1:3] == ['user', 'installations'] and segments[4] == 'repositories':
            inst = self.installations.get(int(segments[3]))
            if inst is None or uid not in inst['users']:
                return 404, {}, b'{}'
            repos = [{'full_name': n} for n in inst['repositories']]
            total = len(repos) + (5 if parts.path in self.short else 0)
            return 200, {}, json.dumps({'total_count': total,
                                        'repositories': repos[(page - 1) * per: page * per]}).encode()
        return 404, {}, b'{}'


def delivery(event, payload, secret=WEBHOOK_SECRET):
    body = json.dumps(payload).encode()
    signature = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {'X-GitHub-Event': event, 'X-Hub-Signature-256': signature}


class Result:
    def __init__(self, status, headers, body):
        self.status = int(status.split()[0])
        self.headers = headers
        self.body = body
        self.text = body.decode('utf-8', 'replace')

    def header(self, name):
        return next((v for k, v in self.headers if k.lower() == name.lower()), None)

    def cookies(self):
        return [v for k, v in self.headers if k.lower() == 'set-cookie']


class WsgiClient:
    def __init__(self, app):
        self.app = app
        self.jar = {}

    def request(self, method, path, *, body=b'', headers=None, form=None, cookies=True):
        path, _, query = path.partition('?')
        if form is not None:
            body = urlencode(form).encode()
            headers = {'Content-Type': 'application/x-www-form-urlencoded', **(headers or {})}
        environ = {'REQUEST_METHOD': method, 'PATH_INFO': path, 'QUERY_STRING': query,
                   'CONTENT_LENGTH': str(len(body)), 'wsgi.input': io.BytesIO(body),
                   'SERVER_NAME': 'hub.test', 'SERVER_PORT': '443', 'wsgi.url_scheme': 'https'}
        for name, value in (headers or {}).items():
            if name.lower() == 'content-type':
                environ['CONTENT_TYPE'] = value
            else:
                environ['HTTP_' + name.upper().replace('-', '_')] = value
        if cookies and self.jar:
            environ['HTTP_COOKIE'] = '; '.join(f'{k}={v}' for k, v in self.jar.items())
        captured = {}

        def start_response(status, response_headers):
            captured['status'], captured['headers'] = status, response_headers

        data = b''.join(self.app(environ, start_response))
        result = Result(captured['status'], captured['headers'], data)
        for raw in result.cookies():
            jar = SimpleCookie()
            jar.load(raw)
            for name, morsel in jar.items():
                if morsel['max-age'] == '0':
                    self.jar.pop(name, None)
                else:
                    self.jar[name] = morsel.value
        return result

    def get(self, path, **kw):
        return self.request('GET', path, **kw)

    def post(self, path, **kw):
        return self.request('POST', path, **kw)
