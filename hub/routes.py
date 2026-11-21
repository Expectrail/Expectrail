"""The route registry. A module registers its handlers here; `hub.server` dispatches through it.

A route module defines `register(registry)` and calls `registry.register(...)` (or uses
`registry.route(...)` as a decorator) in it. `hub.server` builds one registry per app and calls
`register` on `hub.auth` and on every `hub/runs*.py` module, so #713 adds its routes from its own
file and never edits this one. A path is literal segments and `{name}` segments; a `{name}` matches one
non-empty segment. Registering the same method and path twice is refused, so two modules cannot
silently shadow each other.
"""
from dataclasses import dataclass
import re

SEGMENT = re.compile(r'[A-Za-z0-9._~-]+|\{[a-z_]+\}')


class RouteError(ValueError):
    pass


class NotFound(LookupError):
    pass


class MethodNotAllowed(LookupError):
    def __init__(self, allowed):
        super().__init__('method not allowed')
        self.allowed = sorted(allowed)


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    handler: object
    owner: str
    segments: tuple


class RouteRegistry:
    def __init__(self):
        self._routes = []

    def register(self, method, path, handler, *, owner):
        method = method.upper()
        if method not in ('GET', 'POST'):
            raise RouteError(f'{method}: only GET and POST')
        if not owner:
            raise RouteError('a route names its owner (the issue that owns it)')
        segments = parse(path)
        for existing in self._routes:
            if existing.method == method and same_shape(existing.segments, segments):
                raise RouteError(f'{method} {path} is already registered by #{existing.owner}')
        self._routes.append(Route(method, path, handler, str(owner), segments))

    def route(self, method, path, *, owner):
        def decorate(handler):
            self.register(method, path, handler, owner=owner)
            return handler
        return decorate

    def match(self, method, path):
        """Return (route, params). Raises NotFound or MethodNotAllowed."""
        parts = split(path)
        allowed = set()
        for candidate in self._routes:
            params = bind(candidate.segments, parts)
            if params is None:
                continue
            if candidate.method == method.upper():
                return candidate, params
            allowed.add(candidate.method)
        if allowed:
            raise MethodNotAllowed(allowed)
        raise NotFound(path)

    def routes(self):
        return list(self._routes)


def split(path):
    if not path.startswith('/'):
        return None
    return () if path == '/' else tuple(path.split('/')[1:])


def parse(path):
    parts = split(path)
    if parts is None or (path != '/' and path.endswith('/')):
        raise RouteError(f'{path!r}: a path starts with / and has no trailing /')
    for part in parts:
        if not SEGMENT.fullmatch(part):
            raise RouteError(f'{path!r}: segment {part!r} is not allowed')
    return parts


def same_shape(a, b):
    if len(a) != len(b):
        return False
    return all((x.startswith('{') and y.startswith('{')) or x == y for x, y in zip(a, b))


def bind(segments, parts):
    if parts is None or len(segments) != len(parts):
        return None
    params = {}
    for seg, part in zip(segments, parts):
        if seg.startswith('{'):
            if not part:
                return None
            params[seg[1:-1]] = part
        elif seg != part:
            return None
    return params
