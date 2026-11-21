"""Hub sign-in, installation and sign-out against the offline GitHub stub (#712). No test opens a socket."""
import base64
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from hub import session
from hub.config import Config
from hub.routes import MethodNotAllowed, NotFound, RouteError, RouteRegistry
from hub.server import build_registry, make_app, route_modules
from tests import hub_stub
from tests.hub_stub import FakeGitHub, WsgiClient, delivery

NOW = 1_800_000_000


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


def no_sockets(*args, **kwargs):
    raise AssertionError('a hub test tried to open a socket')


class HubCase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(socket, 'socket', no_sockets)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.github = FakeGitHub()
        self.clock = Clock()
        self.app = make_app(Config.from_env(hub_stub.ENV), transport=self.github, clock=self.clock)
        self.store = self.app.hub.store
        self.client = WsgiClient(self.app)
        self.github.add_user(7, 'ada', 'code-ada')
        self.github.add_installation(41, 'ada', ['ada/platformer', 'ada/breakout'], users={7})
        self.github.add_installation(42, 'studio', ['studio/kart'], users={7, 8})
        self.github.add_installation(43, 'other', ['other/secret'], users={8})

    def start(self):
        response = self.client.get('/sign-in')
        self.assertEqual(response.status, 302)
        location = urlsplit(response.header('Location'))
        return response, location, parse_qs(location.query)

    def sign_in(self, code='code-ada'):
        _, _, query = self.start()
        return self.client.get(f'/callback?code={code}&state={query["state"][0]}')

    def deliver(self, event, payload, secret=hub_stub.WEBHOOK_SECRET):
        body, headers = delivery(event, payload, secret)
        return self.client.post('/github/events', body=body, headers=headers)


class UnconfiguredTest(unittest.TestCase):
    def setUp(self):
        self.client = WsgiClient(make_app(Config.from_env({}), transport=FakeGitHub()))

    def test_home_says_unconfigured_and_names_what_is_missing(self):
        response = self.client.get('/')
        self.assertEqual(response.status, 200)
        self.assertIn('GitHub sign-in is not configured on this server', response.text)
        for name in ('EXPECTRAIL_HUB_CLIENT_ID', 'EXPECTRAIL_HUB_CLIENT_SECRET', 'EXPECTRAIL_HUB_APP_SLUG',
                     'EXPECTRAIL_HUB_COOKIE_KEY', 'EXPECTRAIL_HUB_ORIGIN', 'EXPECTRAIL_HUB_WEBHOOK_SECRET'):
            self.assertIn(name, response.text)

    def test_every_sign_in_route_refuses_while_unconfigured(self):
        for method, path in (('GET', '/sign-in'), ('GET', '/callback?code=a&state=b'),
                             ('POST', '/sign-out'), ('GET', '/projects')):
            with self.subTest(path=path):
                response = self.client.request(method, path)
                self.assertEqual(response.status, 503)
                self.assertIsNone(response.header('Location'))
                self.assertEqual(response.cookies(), [])
        self.assertEqual(self.client.post('/github/events', body=b'{}').status, 503)

    def test_unusable_values_are_named_but_never_shown(self):
        env = dict(hub_stub.ENV, EXPECTRAIL_HUB_COOKIE_KEY='short-key-value',
                   EXPECTRAIL_HUB_ORIGIN='http://hub.example')
        config = Config.from_env(env)
        self.assertFalse(config.sign_in_ready)
        response = WsgiClient(make_app(config, transport=FakeGitHub())).get('/')
        self.assertIn('EXPECTRAIL_HUB_COOKIE_KEY: shorter than 32 bytes', response.text)
        self.assertIn('EXPECTRAIL_HUB_ORIGIN: must be https', response.text)
        self.assertNotIn('short-key-value', response.text)
        self.assertNotIn(hub_stub.CLIENT_SECRET, response.text)
        self.assertNotIn(hub_stub.CLIENT_SECRET, repr(config))

    def test_origin_rules(self):
        for origin, ok in (('https://hub.example', True), ('http://127.0.0.1:8765', True),
                           ('http://hub.example', False), ('https://hub.example/path', False),
                           ('https://user@hub.example', False), ('ftp://hub.example', False)):
            with self.subTest(origin=origin):
                config = Config.from_env(dict(hub_stub.ENV, EXPECTRAIL_HUB_ORIGIN=origin))
                self.assertEqual(config.sign_in_ready, ok)

    def test_cookies_are_secure_only_on_https(self):
        self.assertTrue(Config.from_env(hub_stub.ENV).secure_cookies)
        local = Config.from_env(dict(hub_stub.ENV, EXPECTRAIL_HUB_ORIGIN='http://localhost:8765'))
        self.assertFalse(local.secure_cookies)


class SignInTest(HubCase):
    def test_sign_in_sends_the_browser_to_github_with_a_state_cookie(self):
        response, location, query = self.start()
        self.assertEqual((location.netloc, location.path), ('github.com', '/login/oauth/authorize'))
        self.assertEqual(query['client_id'], [hub_stub.CLIENT_ID])
        self.assertEqual(query['redirect_uri'], [hub_stub.ORIGIN + '/callback'])
        self.assertNotIn(hub_stub.CLIENT_SECRET, response.header('Location'))
        state_cookie = next(c for c in response.cookies() if c.startswith('er_state='))
        for attribute in ('HttpOnly', 'Secure', 'SameSite=Lax', 'Max-Age=600', 'Path=/'):
            self.assertIn(attribute, state_cookie)

    def test_a_developer_signs_in_and_sees_only_the_repositories_github_lets_them_see(self):
        response = self.sign_in()
        self.assertEqual((response.status, response.header('Location')), (302, '/projects'))
        self.assertNotIn('er_state', self.client.jar)
        page = self.client.get('/projects')
        self.assertEqual(page.status, 200)
        for name in ('ada/platformer', 'ada/breakout', 'studio/kart', 'Signed in as'):
            self.assertIn(name, page.text)
        self.assertNotIn('other/secret', page.text)
        self.assertIn('https://github.com/apps/expectrail-fixture/installations/new', page.text)

    def test_the_session_cookie_holds_a_user_id_login_and_expiry_and_nothing_else(self):
        response = self.sign_in()
        raw = next(c for c in response.cookies() if c.startswith('er_session='))
        for attribute in ('HttpOnly', 'Secure', 'SameSite=Lax', 'Max-Age=3600'):
            self.assertIn(attribute, raw)
        body = self.client.jar['er_session'].split('.')[0]
        payload = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
        self.assertEqual(payload, {'uid': 7, 'login': 'ada', 'exp': NOW + 3600})

    def test_the_user_token_reaches_only_github_and_only_during_the_callback(self):
        self.sign_in()
        token = 'fixture-token-7'
        calls_after_callback = len(self.github.calls)
        page = self.client.get('/projects')
        self.assertEqual(len(self.github.calls), calls_after_callback)  # listing reads no token
        self.assertNotIn(token, page.text)
        self.assertTrue(all(c[2] in (None, f'Bearer {token}') for c in self.github.calls))
        self.assertNotIn(token, repr(vars(self.store)))
        self.assertNotIn(token, ''.join(self.client.jar.values()))

    def test_a_wrong_missing_expired_or_reused_state_signs_nobody_in(self):
        _, _, query = self.start()
        state = query['state'][0]
        with self.subTest('wrong state'):
            response = self.client.get(f'/callback?code=code-ada&state={state}x')
            self.assertEqual(response.status, 400)
            self.assertNotIn('er_session', self.client.jar)
        with self.subTest('no state cookie'):
            self.start()
            self.client.jar.pop('er_state')
            self.assertEqual(self.client.get(f'/callback?code=code-ada&state={state}').status, 400)
        with self.subTest('expired'):
            _, _, query = self.start()
            self.clock.now += 601
            self.assertEqual(self.client.get(f'/callback?code=code-ada&state={query["state"][0]}').status, 400)
        with self.subTest('reused'):
            self.github.add_user(7, 'ada', 'code-two')
            _, _, query = self.start()
            held = self.client.jar['er_state']
            self.assertEqual(self.client.get(f'/callback?code=code-ada&state={query["state"][0]}').status, 302)
            self.client.jar = {'er_state': held}
            self.assertEqual(self.client.get(f'/callback?code=code-two&state={query["state"][0]}').status, 400)
            self.assertNotIn('er_session', self.client.jar)

    def test_a_state_cookie_cannot_stand_in_for_a_session(self):
        _, _, query = self.start()
        self.client.jar['er_session'] = self.client.jar['er_state']
        self.assertEqual(self.client.get('/projects').header('Location'), '/')

    def test_github_cancelled_or_failed_leaves_the_browser_signed_out(self):
        _, _, query = self.start()
        response = self.client.get(f'/callback?error=access_denied&state={query["state"][0]}')
        self.assertEqual(response.status, 400)
        self.assertIn('Nothing was saved', response.text)
        for case in ('bad code', 'rate limit', 'server error'):
            with self.subTest(case):
                self.github.add_user(7, 'ada', 'code-ada')
                self.github.rate_limited.clear()
                self.github.fail.clear()
                code = 'code-unknown' if case == 'bad code' else 'code-ada'
                if case == 'rate limit':
                    self.github.rate_limited.add('/user/installations/41/repositories')
                if case == 'server error':
                    self.github.fail['/user'] = 500
                response = self.sign_in(code)
                self.assertEqual(response.status, 502)
                self.assertNotIn('er_session', self.client.jar)
                self.assertIsNone(self.store.access(7, self.clock()))
                if case == 'rate limit':
                    self.assertIn('rate limit', response.text)

    def test_a_partial_repository_list_is_never_taken_as_the_whole(self):
        self.github.add_installation(41, 'ada', [f'ada/game-{n}' for n in range(250)], users={7})
        self.assertEqual(self.sign_in().status, 302)
        page = self.client.get('/projects').text
        self.assertIn('ada/game-0', page)
        self.assertIn('ada/game-249', page)
        self.github.add_user(7, 'ada', 'code-again')
        with mock.patch('hub.github.MAX_PAGES', 2):
            self.assertEqual(self.sign_in('code-again').status, 502)
        self.github.add_user(7, 'ada', 'code-short')
        self.github.short.add('/user/installations/42/repositories')
        response = self.sign_in('code-short')
        self.assertEqual(response.status, 502)
        self.assertIn('incomplete', response.text)

    def test_a_tampered_or_expired_session_is_signed_out(self):
        self.sign_in()
        good = self.client.jar['er_session']
        body, mac = good.split('.')
        forged = base64.urlsafe_b64encode(json.dumps({'uid': 8, 'login': 'eve', 'exp': NOW + 3600}).encode())
        self.client.jar['er_session'] = forged.decode().rstrip('=') + '.' + mac
        self.assertEqual(self.client.get('/projects').header('Location'), '/')
        self.client.jar['er_session'] = good
        self.assertEqual(self.client.get('/projects').status, 200)
        self.clock.now += 3601
        self.assertEqual(self.client.get('/projects').header('Location'), '/')

    def test_a_session_signed_with_another_key_is_not_ours(self):
        foreign = session.new_session('another-cookie-key-' + 'y' * 32, 7, 'ada', NOW)
        self.client.jar['er_session'] = foreign
        self.assertEqual(self.client.get('/projects').header('Location'), '/')

    def test_a_restart_that_lost_the_access_record_signs_the_browser_out(self):
        self.sign_in()
        self.store.forget_user(7)
        response = self.client.get('/projects')
        self.assertEqual(response.header('Location'), '/')
        self.assertNotIn('er_session', self.client.jar)


class SignOutTest(HubCase):
    def test_sign_out_clears_the_cookie_and_forgets_the_access_record(self):
        self.sign_in()
        response = self.client.post('/sign-out', headers={'Origin': hub_stub.ORIGIN})
        self.assertEqual((response.status, response.header('Location')), (303, '/'))
        self.assertNotIn('er_session', self.client.jar)
        self.assertIsNone(self.store.access(7, self.clock()))
        self.assertIn('Sign in with GitHub', self.client.get('/').text)

    def test_sign_out_from_another_site_or_without_an_origin_is_refused(self):
        self.sign_in()
        for headers in ({'Origin': 'https://evil.test'}, {}, {'Origin': 'null'}, {'Referer': 'https://evil.test/'},
                        {'Referer': hub_stub.ORIGIN + '.evil.test/'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.client.post('/sign-out', headers=headers).status, 403)
                self.assertIn('er_session', self.client.jar)
        self.assertEqual(self.client.post('/sign-out', headers={'Referer': hub_stub.ORIGIN + '/projects'}).status, 303)

    def test_sign_out_is_post_only(self):
        response = self.client.get('/sign-out')
        self.assertEqual(response.status, 405)
        self.assertEqual(response.header('Allow'), 'POST')


class InstallationTest(HubCase):
    def test_an_unsigned_or_wrongly_signed_delivery_changes_nothing(self):
        self.sign_in()
        payload = {'action': 'deleted', 'installation': {'id': 41, 'account': {'login': 'ada'}}}
        self.assertEqual(self.deliver('installation', payload, secret='not-the-secret').status, 401)
        body, headers = delivery('installation', payload)
        headers.pop('X-Hub-Signature-256')
        self.assertEqual(self.client.post('/github/events', body=body, headers=headers).status, 401)
        self.assertIn('ada/platformer', self.client.get('/projects').text)

    def test_uninstalling_the_app_removes_it_for_signed_in_users_at_once(self):
        self.sign_in()
        self.deliver('installation', {'action': 'created', 'installation': {'id': 41, 'account': {'login': 'ada'}},
                                      'repositories': [{'full_name': 'ada/platformer'}]})
        self.assertIn(41, self.store.installations)
        response = self.deliver('installation', {'action': 'deleted',
                                                 'installation': {'id': 41, 'account': {'login': 'ada'}}})
        self.assertEqual(response.status, 200)
        self.assertNotIn(41, self.store.installations)
        page = self.client.get('/projects').text
        self.assertNotIn('ada/platformer', page)
        self.assertIn('studio/kart', page)

    def test_repositories_added_and_removed(self):
        self.sign_in()
        inst = {'id': 42, 'account': {'login': 'studio'}}
        self.deliver('installation_repositories', {'action': 'added', 'installation': inst,
                                                   'repositories_added': [{'full_name': 'studio/racer'}]})
        self.assertIn('studio/racer', self.store.installations[42]['repositories'])
        self.deliver('installation_repositories', {'action': 'removed', 'installation': inst,
                                                   'repositories_removed': [{'full_name': 'studio/kart'}]})
        self.assertNotIn('studio/kart', self.client.get('/projects').text)

    def test_malformed_or_oversized_deliveries_change_nothing(self):
        before = dict(self.store.installations)
        for payload in ({'action': 'created'}, {'action': 'created', 'installation': {'id': '41'}},
                        {'action': 'created', 'installation': {'id': 41, 'account': {'login': 'ada'}},
                         'repositories': [{'full_name': '../etc'}]}, ['not', 'an', 'object']):
            with self.subTest(payload=payload):
                self.assertEqual(self.deliver('installation', payload).status, 400)
        body, headers = delivery('installation', {'action': 'created'})
        self.assertEqual(self.client.post('/github/events', body=b'{' * 10, headers=dict(
            headers, **{'X-Hub-Signature-256': delivery_signature(b'{' * 10)})).status, 400)
        self.assertEqual(self.store.installations, before)
        big = b' ' * (1024 * 1024 + 1)
        self.assertEqual(self.client.post('/github/events', body=big,
                                          headers={'X-Hub-Signature-256': delivery_signature(big)}).status, 413)

    def test_other_events_are_acknowledged_and_ignored(self):
        response = self.deliver('push', {'action': 'whatever'})
        self.assertEqual(response.status, 202)

    def test_the_setup_return_trusts_nothing_in_its_query(self):
        response = self.client.get('/installed?installation_id=43&setup_action=install')
        self.assertEqual(response.status, 200)
        self.assertIn('Refresh from GitHub', response.text)
        self.assertEqual(self.store.installations, {})
        self.sign_in()
        self.assertNotIn('other/secret', self.client.get('/projects').text)

    def test_installing_shows_after_a_refresh_from_github(self):
        self.sign_in()
        self.github.add_installation(44, 'ada', ['ada/new-game'], users={7})
        self.assertNotIn('ada/new-game', self.client.get('/projects').text)
        self.github.add_user(7, 'ada', 'code-refresh')
        self.sign_in('code-refresh')
        self.assertIn('ada/new-game', self.client.get('/projects').text)

    def test_no_repositories_gives_the_install_link(self):
        self.github.add_user(9, 'newcomer', 'code-new')
        self.sign_in('code-new')
        page = self.client.get('/projects').text
        self.assertIn('No repositories connected', page)
        self.assertIn('installations/new', page)


def delivery_signature(body):
    import hashlib
    import hmac
    return 'sha256=' + hmac.new(hub_stub.WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


class ServerTest(HubCase):
    def test_security_headers_and_no_caching_on_every_response(self):
        for path in ('/', '/projects', '/nowhere', '/assets/hub.css'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.header('Cache-Control'), 'no-store')
                self.assertIn("frame-ancestors 'none'", response.header('Content-Security-Policy'))
                self.assertEqual(response.header('Referrer-Policy'), 'same-origin')
                self.assertEqual(response.header('X-Content-Type-Options'), 'nosniff')

    def test_only_the_two_stylesheets_are_served(self):
        self.assertEqual(self.client.get('/assets/expectrail.css').status, 200)
        self.assertEqual(self.client.get('/assets/hub.css').header('Content-Type'), 'text/css; charset=utf-8')
        for path in ('/assets/../../AGENTS.md', '/assets/home.js', '/docs/assets/hub.css', '/assets/'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status, 404)

    def test_a_handler_error_is_a_plain_500(self):
        registry_owner = self.app.hub.registry
        registry_owner.register('GET', '/boom', lambda request: 1 / 0, owner='test')
        with mock.patch('sys.stderr'):
            response = self.client.get('/boom')
        self.assertEqual(response.status, 500)
        self.assertNotIn('ZeroDivisionError', response.text)

    def test_the_whole_flow_opens_no_socket(self):
        # setUp replaced socket.socket with a function that fails the test; a full flow still works.
        self.sign_in()
        self.client.post('/sign-out', headers={'Origin': hub_stub.ORIGIN})
        self.assertGreater(len(self.github.calls), 3)


class RegistryTest(unittest.TestCase):
    def test_params_404_and_405(self):
        registry = RouteRegistry()
        registry.register('GET', '/repos/{owner}/{name}/runs', 'runs', owner='713')
        found, params = registry.match('GET', '/repos/ada/platformer/runs')
        self.assertEqual((found.handler, params), ('runs', {'owner': 'ada', 'name': 'platformer'}))
        for path in ('/repos/ada/runs', '/repos/ada//runs', '/repos/ada/platformer/runs/', '/x'):
            with self.subTest(path=path):
                with self.assertRaises(NotFound):
                    registry.match('GET', path)
        with self.assertRaises(MethodNotAllowed):
            registry.match('POST', '/repos/ada/platformer/runs')

    def test_two_owners_cannot_take_the_same_route(self):
        registry = RouteRegistry()
        registry.register('GET', '/repos/{owner}', 'a', owner='712')
        with self.assertRaisesRegex(RouteError, 'already registered by #712'):
            registry.register('GET', '/repos/{name}', 'b', owner='713')
        registry.register('POST', '/repos/{owner}', 'c', owner='713')

    def test_bad_routes_are_refused(self):
        registry = RouteRegistry()
        for method, path, owner in (('GET', 'projects', 'x'), ('GET', '/projects/', 'x'), ('PUT', '/a', 'x'),
                                    ('GET', '/a', ''), ('GET', '/a b', 'x')):
            with self.subTest(path=path, method=method):
                with self.assertRaises(RouteError):
                    registry.register(method, path, 'h', owner=owner)

    def test_runs_modules_are_found_by_name_and_register_themselves(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / 'hubfixture'
            package.mkdir()
            (package / '__init__.py').write_text('')
            (package / 'runs.py').write_text(
                "def register(registry):\n    registry.register('GET', '/runs', lambda r: None, owner='713')\n")
            (package / 'other.py').write_text("raise AssertionError('must not be imported')\n")
            with mock.patch('sys.path', [tmp, *__import__('sys').path]):
                modules = route_modules([str(package)], prefix='hubfixture.')
                registry = build_registry(modules)
        owners = {(r.method, r.path): r.owner for r in registry.routes()}
        self.assertEqual(owners[('GET', '/runs')], '713')
        self.assertEqual(owners[('GET', '/callback')], '712')
        self.assertEqual(owners[('POST', '/github/events')], '712')


class SessionTest(unittest.TestCase):
    KEY = 'k' * 40

    def test_round_trip_and_rejections(self):
        token = session.new_session(self.KEY, 7, 'ada', NOW)
        self.assertEqual(session.verify(self.KEY, 'session', token, NOW)['login'], 'ada')
        self.assertIsNone(session.verify(self.KEY, 'state', token, NOW))
        self.assertIsNone(session.verify(self.KEY, 'session', token, NOW + 3600))
        self.assertIsNone(session.verify(self.KEY, 'session', token + 'x', NOW))
        self.assertIsNone(session.verify(self.KEY, 'session', None, NOW))
        self.assertIsNone(session.verify(self.KEY, 'session', 'a' * 5000, NOW))

    def test_payload_shape_is_closed(self):
        for payload in ({'uid': 7, 'login': 'ada', 'exp': NOW, 'token': 't'}, {'uid': True, 'login': 'ada', 'exp': NOW},
                        {'uid': 7, 'login': '../x', 'exp': NOW}, {'uid': 0, 'login': 'ada', 'exp': NOW}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    session.sign(self.KEY, 'session', payload)


HOSTILE = ('é.abc', '"é.abc"', '"\\u00e9.abc"', '.', 'a.', '.b', '..', 'a..b', 'a.b.c', '=', '"',
           'x' * 5000, 'a' * 2000 + '.' + 'b' * 43, '\u2603' * 10 + '.' + 'b' * 43, '%00.%00', 'a.' + '\u00ff' * 43)


class HostileCookieTest(HubCase):
    """A cookie the hub did not sign is "signed out", never a 500 (merge guard on #763)."""

    def test_verify_is_total(self):
        for purpose in ('session', 'state'):
            for value in HOSTILE + (None, 7, b'a.b', ['a', 'b']):
                with self.subTest(purpose=purpose, value=value):
                    self.assertIsNone(session.verify(hub_stub.COOKIE_KEY, purpose, value, NOW))

    def test_a_valid_mac_over_a_non_json_or_non_utf8_body_is_none(self):
        for body in ('_w', '__8', 'bnVsbA', 'W10', 'eyJ1aWQiOjd9'):  # b'\xff', junk, null, [], {"uid":7}
            token = body + '.' + session._mac(hub_stub.COOKIE_KEY, 'session', body)
            with self.subTest(body=body):
                self.assertIsNone(session.verify(hub_stub.COOKIE_KEY, 'session', token, NOW))

    def test_every_page_treats_a_hostile_cookie_as_signed_out(self):
        for value in HOSTILE:
            for name in ('er_session', 'er_state'):
                header = f'{name}={value}'.encode('utf-8').decode('latin-1')  # as a WSGI server passes it
                for method, path in (('GET', '/'), ('GET', '/projects'), ('GET', '/installed'),
                                     ('GET', '/callback?code=c&state=s'), ('POST', '/sign-out')):
                    with self.subTest(name=name, value=value[:20], path=path):
                        response = self.client.request(method, path, cookies=False, headers={
                            'Cookie': header, 'Origin': hub_stub.ORIGIN})
                        self.assertLess(response.status, 500)
                        self.assertNotIn('Signed in as', response.text)


class SuspendTest(HubCase):
    def test_a_suspended_installation_disappears_until_a_refresh(self):
        self.sign_in()
        response = self.deliver('installation', {'action': 'suspend',
                                                 'installation': {'id': 42, 'account': {'login': 'studio'}}})
        self.assertEqual(response.status, 200)
        page = self.client.get('/projects').text
        self.assertNotIn('studio/kart', page)
        self.assertIn('ada/platformer', page)


if __name__ == '__main__':
    unittest.main()
