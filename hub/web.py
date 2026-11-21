"""Requests, responses and pages for the hub. Standard library only."""
from dataclasses import dataclass, field
from html import escape
from http.cookies import CookieError, SimpleCookie
from urllib.parse import parse_qs

from hub import session

MAX_FORM = 64 * 1024
STATUS = {200: 'OK', 202: 'Accepted', 204: 'No Content', 302: 'Found', 303: 'See Other',
          400: 'Bad Request', 401: 'Unauthorized', 403: 'Forbidden', 404: 'Not Found',
          405: 'Method Not Allowed', 413: 'Content Too Large', 500: 'Internal Server Error',
          502: 'Bad Gateway', 503: 'Service Unavailable'}
SECURITY_HEADERS = [
    ('Content-Security-Policy', "default-src 'none'; style-src 'self'; img-src 'self'; "
                                "form-action 'self' https://github.com; frame-ancestors 'none'; base-uri 'none'"),
    ('X-Content-Type-Options', 'nosniff'),
    # same-origin, not no-referrer: a browser sends `Origin: null` on a form POST under no-referrer, and
    # sign-out's origin check would refuse it. Other sites still get no Referer (no callback code leaks).
    ('Referrer-Policy', 'same-origin'),
    ('X-Frame-Options', 'DENY'),
]


@dataclass
class Request:
    method: str
    path: str
    query: dict
    headers: dict          # lower-case names
    cookies: dict
    body: bytes
    app: object            # the Hub: config, store, github, clock
    params: dict = field(default_factory=dict)

    def form(self):
        if self.headers.get('content-type', '').split(';')[0].strip() != 'application/x-www-form-urlencoded':
            return {}
        return first_values(parse_qs(self.body.decode('utf-8', 'replace'), keep_blank_values=True))

    def user(self):
        """The signed-in (uid, login), or None. A bad, foreign or expired cookie is signed out."""
        config = self.app.config
        if not config.sign_in_ready:
            return None
        payload = session.verify(config['cookie_key'], 'session', self.cookies.get(session.SESSION_COOKIE),
                                 self.app.clock())
        return (payload['uid'], payload['login']) if payload else None


@dataclass
class Response:
    status: int = 200
    body: bytes = b''
    headers: list = field(default_factory=list)
    content_type: str = 'text/html; charset=utf-8'


def first_values(parsed):
    return {k: v[0] for k, v in parsed.items() if v}


def parse_cookies(header):
    jar = SimpleCookie()
    try:
        jar.load(header or '')
    except CookieError:
        return {}
    return {k: m.value for k, m in jar.items()}


def redirect(location, status=302, headers=()):
    return Response(status, b'', [('Location', location), *headers])


def page(title, body, *, status=200, headers=(), signed_in=None):
    account = ''
    if signed_in:
        account = (f'<form class="account" method="post" action="/sign-out"><span>Signed in as '
                   f'<strong>{escape(signed_in)}</strong></span> <button type="submit">Sign out</button></form>')
    html = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · Expectrail</title>
<link rel="stylesheet" href="/assets/expectrail.css"><link rel="stylesheet" href="/assets/hub.css">
</head>
<body>
<header class="mast"><div class="bar"><a class="wordmark" href="/">Expectrail</a><span class="place">Hub</span>{account}</div></header>
<main id="main">
{body}
</main>
</body>
</html>
'''
    return Response(status, html.encode('utf-8'), list(headers))


def message(title, text, *, status, link=None, signed_in=None):
    extra = f'<p><a class="action-link" href="{escape(link[0])}">{escape(link[1])}</a></p>' if link else ''
    return page(title, f'<section><h1>{escape(title)}</h1><p>{escape(text)}</p>{extra}</section>',
                status=status, signed_in=signed_in)


def plain(status, text):
    return Response(status, text.encode('utf-8'), [], 'text/plain; charset=utf-8')
