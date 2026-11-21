"""The hub as a WSGI application, and `python3 -m hub` to serve it on this machine.

`make_app()` builds one route registry, registers `hub.auth`, `hub.installations` and every
`hub/runs*.py` module (#713's) that defines `register(registry)`, and dispatches through it. Every
response carries the security headers in `hub.web`; dynamic pages are never cached.
"""
from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import pkgutil
import sys
import time
import traceback

import hub
from hub import auth, installations
from hub.config import Config
from hub.github import GitHub
from hub.routes import MethodNotAllowed, NotFound, RouteRegistry
from hub.store import MemoryStore
from hub.web import SECURITY_HEADERS, STATUS, Request, Response, first_values, message, parse_cookies

from urllib.parse import parse_qs

PACKAGE = Path(__file__).resolve().parent
ASSETS = PACKAGE.parent / 'docs' / 'assets'
CSS = 'text/css; charset=utf-8'
STATIC = {
    '/assets/expectrail.css': (ASSETS / 'expectrail.css', CSS),
    '/assets/hub.css': (ASSETS / 'hub.css', CSS),
    '/assets/hub-fonts.css': (PACKAGE / 'fonts.css', CSS),
    '/assets/fonts/texgyreadventor-regular.woff': (ASSETS / 'fonts/texgyreadventor-regular.woff', 'font/woff'),
    '/assets/fonts/texgyreadventor-bold.woff': (ASSETS / 'fonts/texgyreadventor-bold.woff', 'font/woff'),
}
MAX_BODY = 1024 * 1024 + 1


@dataclass
class Hub:
    config: Config
    store: object
    github: GitHub
    clock: object
    registry: RouteRegistry


def route_modules(package_path=None, prefix='hub.'):
    """`hub.auth`, `hub.installations`, then each `hub/runs*.py` module, in name order."""
    found = [auth, installations]
    names = sorted(m.name for m in pkgutil.iter_modules(package_path or hub.__path__) if m.name.startswith('runs'))
    for name in names:
        found.append(importlib.import_module(prefix + name))
    return found


def build_registry(modules):
    registry = RouteRegistry()
    for module in modules:
        register = getattr(module, 'register', None)
        if callable(register):
            register(registry)
    return registry


def make_app(config=None, *, store=None, transport=None, clock=time.time, modules=None):
    config = config if config is not None else Config.from_env(os.environ)
    state = Hub(config, store or MemoryStore(), GitHub(config, transport), clock,
                build_registry(modules if modules is not None else route_modules()))

    def application(environ, start_response):
        response = dispatch(state, environ)
        headers = [('Content-Type', response.content_type), ('Content-Length', str(len(response.body))),
                   ('Cache-Control', 'no-store'), *SECURITY_HEADERS, *response.headers]
        start_response(f'{response.status} {STATUS.get(response.status, "")}'.strip(), headers)
        return [response.body]

    application.hub = state
    return application


def read_body(environ):
    try:
        length = int(environ.get('CONTENT_LENGTH') or 0)
    except ValueError:
        return None
    if length < 0 or length > MAX_BODY:
        return None
    return environ['wsgi.input'].read(length) if length else b''


def dispatch(state, environ):
    method = environ.get('REQUEST_METHOD', 'GET').upper()
    path = environ.get('PATH_INFO', '/') or '/'
    if method == 'GET' and path in STATIC:
        asset, content_type = STATIC[path]
        try:
            data = asset.read_bytes()
        except OSError:
            return Response(404, b'not found', [], 'text/plain; charset=utf-8')
        return Response(200, data, [], content_type)
    body = read_body(environ)
    if body is None:
        return Response(413, b'request too large', [], 'text/plain; charset=utf-8')
    headers = {k[5:].replace('_', '-').lower(): v for k, v in environ.items() if k.startswith('HTTP_')}
    if environ.get('CONTENT_TYPE'):
        headers['content-type'] = environ['CONTENT_TYPE']
    request = Request(method, path, first_values(parse_qs(environ.get('QUERY_STRING', ''), keep_blank_values=True)),
                      headers, parse_cookies(environ.get('HTTP_COOKIE')), body, state)
    try:
        found, params = state.registry.match(method, path)
    except NotFound:
        return message('Not found', 'There is no page at this address.', status=404, link=('/', 'Back to the hub'))
    except MethodNotAllowed as error:
        response = message('Not allowed', 'This page does not take that kind of request.', status=405)
        response.headers.append(('Allow', ', '.join(error.allowed)))
        return response
    request.params = params
    try:
        return found.handler(request)
    except Exception:  # a handler bug is a plain 500, and its trace goes to stderr without request data
        traceback.print_exc(limit=5, file=sys.stderr)
        return message('Something went wrong', 'The hub could not answer this request.', status=500)


def main(argv=None):
    import argparse
    from wsgiref.simple_server import make_server

    parser = argparse.ArgumentParser(prog='python3 -m hub', description='Serve the Expectrail hub on this machine.')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--host', default='127.0.0.1')
    args = parser.parse_args(argv)
    app = make_app()
    config = app.hub.config
    if config.sign_in_ready:
        print(f'GitHub sign-in configured for {config["origin"]}')
    else:
        print('GitHub sign-in is unconfigured. Missing: ' + ', '.join(config.missing()))
        for problem in config.problems:
            print(f'Unusable: {problem}')
    print(f'Serving the hub on http://{args.host}:{args.port}/')
    with make_server(args.host, args.port, app) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return 0
    return 0
