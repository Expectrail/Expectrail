"""GitHub App installation: the setup return page and authenticated installation deliveries (#712).

GitHub posts `installation` and `installation_repositories` events to `/github/events`, signed with the
webhook secret (`X-Hub-Signature-256`). An unsigned or wrongly signed delivery changes nothing. A
removal takes effect at once, for every signed-in user. The setup return page (`/installed`) trusts
nothing in its query: it only offers to refresh access from GitHub.
"""
import hashlib
import hmac
import json
import re

from hub.github import LOGIN, REPO_NAME
from hub.web import page, plain

OWNER = '712'
MAX_DELIVERY = 1024 * 1024


def register(registry):
    registry.register('GET', '/installed', installed, owner=OWNER)
    registry.register('POST', '/github/events', events, owner=OWNER)


def installed(request):
    body = '''<section aria-labelledby="installed"><h1 id="installed">Back from GitHub</h1>
<p>If you installed or changed the Expectrail App, refresh your access so the hub lists the
repositories GitHub now lets you see. Your CI runs the verification; the hub never runs your code.</p>
<form method="get" action="/sign-in"><button type="submit">Refresh from GitHub</button></form></section>'''
    user = request.user()
    return page('App installation', body, signed_in=user[1] if user else None)


def signature_ok(secret, body, header):
    if not isinstance(header, str) or not header.startswith('sha256='):
        return False
    expected = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


class Malformed(ValueError):
    pass


def _installation(payload):
    inst = payload.get('installation')
    iid = inst.get('id') if isinstance(inst, dict) else None
    account = inst.get('account') if isinstance(inst, dict) else None
    login = account.get('login') if isinstance(account, dict) else None
    if type(iid) is not int or iid <= 0 or not isinstance(login, str) or not LOGIN.fullmatch(login):
        raise Malformed('installation')
    return iid, login


def _names(items):
    if items is None:
        return set()
    if not isinstance(items, list):
        raise Malformed('repositories')
    names = set()
    for item in items:
        name = item.get('full_name') if isinstance(item, dict) else None
        if not isinstance(name, str) or not REPO_NAME.fullmatch(name):
            raise Malformed('repository')
        names.add(name)
    return names


def events(request):
    config = request.app.config
    if 'webhook_secret' not in config.values:
        return plain(503, 'installation deliveries are not configured')
    if len(request.body) > MAX_DELIVERY:
        return plain(413, 'delivery too large')
    if not signature_ok(config['webhook_secret'], request.body, request.headers.get('x-hub-signature-256')):
        return plain(401, 'signature does not match')
    event = request.headers.get('x-github-event', '')
    try:
        payload = json.loads(request.body)
        if not isinstance(payload, dict) or not isinstance(payload.get('action'), str):
            raise Malformed('payload')
        action = payload['action']
        store = request.app.store
        if event == 'installation':
            iid, login = _installation(payload)
            if action == 'created':
                store.installed(iid, login, _names(payload.get('repositories')))
            elif action == 'deleted':
                store.uninstalled(iid)
            elif action == 'suspend':
                store.suspended(iid)
            else:
                return plain(202, f'installation {action}: nothing kept changes')
        elif event == 'installation_repositories':
            iid, login = _installation(payload)
            if action == 'added':
                store.repositories_added(iid, login, _names(payload.get('repositories_added')))
            elif action == 'removed':
                store.repositories_removed(iid, _names(payload.get('repositories_removed')))
            else:
                return plain(202, f'installation_repositories {action}: nothing kept changes')
        elif re.fullmatch(r'[a-z_]{1,64}', event):
            return plain(202, 'event not used by the hub')
        else:
            raise Malformed('event')
    except (ValueError, RecursionError):
        return plain(400, 'delivery is malformed; nothing changed')
    return plain(200, 'recorded')
