"""Signed cookies: the browser session and the one-use sign-in state.

A token is `<payload>.<mac>`: the payload is base64url JSON, the mac is HMAC-SHA256 over a purpose
label and the payload, so a state cookie can never be replayed as a session. The session payload
holds exactly a GitHub user id, login and expiry, and nothing else: no token, no repository names,
no installation ids (docs/hub-design.md, "Browser session").
"""
import base64
import hashlib
import hmac
import json
import re

SESSION_COOKIE = 'er_session'
STATE_COOKIE = 'er_state'
SESSION_SECONDS = 60 * 60
STATE_SECONDS = 10 * 60
MAX_TOKEN_CHARS = 2048
LOGIN = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})')
SHAPES = {
    'session': {'uid': int, 'login': str, 'exp': int},
    'state': {'state': str, 'exp': int},
}


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _unb64(text):
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def _mac(key, purpose, payload):
    msg = f'expectrail-hub/v1|{purpose}|{payload}'.encode('ascii')
    return _b64(hmac.new(key.encode(), msg, hashlib.sha256).digest())


def sign(key, purpose, payload):
    check_shape(purpose, payload)
    body = _b64(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode())
    return f'{body}.{_mac(key, purpose, body)}'


def verify(key, purpose, token, now):
    """The payload when `token` is ours, for `purpose`, well formed and unexpired; otherwise None."""
    if not isinstance(token, str) or len(token) > MAX_TOKEN_CHARS or token.count('.') != 1:
        return None
    body, mac = token.split('.')
    if not hmac.compare_digest(mac, _mac(key, purpose, body)):
        return None
    try:
        payload = json.loads(_unb64(body))
        check_shape(purpose, payload)
    except (ValueError, TypeError):
        return None
    if payload['exp'] <= now:
        return None
    return payload


def check_shape(purpose, payload):
    shape = SHAPES[purpose]
    if not isinstance(payload, dict) or set(payload) != set(shape):
        raise ValueError('cookie payload has the wrong fields')
    for name, kind in shape.items():
        value = payload[name]
        if type(value) is not kind:  # bool is not an int here
            raise ValueError(f'cookie field {name} has the wrong type')
    if purpose == 'session' and (payload['uid'] <= 0 or not LOGIN.fullmatch(payload['login'])):
        raise ValueError('session names no GitHub user')


def new_session(key, uid, login, now):
    return sign(key, 'session', {'uid': uid, 'login': login, 'exp': int(now) + SESSION_SECONDS})


def new_state(key, state, now):
    return sign(key, 'state', {'state': state, 'exp': int(now) + STATE_SECONDS})


def set_cookie(name, value, max_age, secure):
    parts = [f'{name}={value}', 'Path=/', f'Max-Age={max_age}', 'HttpOnly', 'SameSite=Lax']
    if secure:
        parts.append('Secure')
    return ('Set-Cookie', '; '.join(parts))


def clear_cookie(name, secure):
    return set_cookie(name, '', 0, secure)
