"""Sign-in with GitHub, sign-out, and the signed-in developer's connected repositories (#712).

Flow: `/sign-in` sets a ten-minute state cookie and sends the browser to GitHub. `/callback` checks
the state (signed, unexpired, equal to the query's, never used before), exchanges the code for a user
token, reads who the user is and which installations and repositories they can see, drops the token,
and sets the one-hour session cookie. Anything that fails leaves the browser signed out.
"""
from html import escape
import secrets

from hub import session
from hub.config import SIGN_IN
from hub.github import GitHubError
from hub.store import Access
from hub.web import message, page, redirect

OWNER = '712'


def register(registry):
    registry.register('GET', '/', home, owner=OWNER)
    registry.register('GET', '/sign-in', sign_in, owner=OWNER)
    registry.register('GET', '/callback', callback, owner=OWNER)
    registry.register('POST', '/sign-out', sign_out, owner=OWNER)
    registry.register('GET', '/projects', projects, owner=OWNER)


def unconfigured(request, status=503):
    config = request.app.config
    names = ''.join(f'<li><code>{escape(n)}</code></li>' for n in config.missing(SIGN_IN + ('webhook_secret',)))
    problems = ''.join(f'<li>{escape(p)}</li>' for p in config.problems)
    body = f'''<section aria-labelledby="unconfigured"><p class="caption">Not configured</p>
<h1 id="unconfigured">GitHub sign-in is not configured on this server</h1>
<p>This hub has no GitHub App credentials yet, so nobody can sign in. Nothing is broken and nothing is
being collected: the service serves this page until its operator sets the values below.</p>
<h2>Settings missing</h2><ul>{names or '<li>None</li>'}</ul>
{f'<h2>Settings present but unusable</h2><ul>{problems}</ul>' if problems else ''}
<p><a class="action-link" href="https://expectrail.tech/hub/">See the recorded hub on expectrail.tech</a></p></section>'''
    return page('Sign-in unavailable', body, status=status)


def home(request):
    if not request.app.config.sign_in_ready:
        return unconfigured(request, status=200)
    user = request.user()
    if user:
        return redirect('/projects')
    body = '''<section aria-labelledby="welcome"><h1 id="welcome">Your projects, verified in your own CI</h1>
<p>Sign in with GitHub, then install the Expectrail App on the repositories you choose. Your CI runs
your game and publishes its verdict, receipt and evidence; this hub shows them to you. Expectrail
never checks out, downloads or runs your repository.</p>
<form method="get" action="/sign-in"><button type="submit">Sign in with GitHub</button></form>
<p class="note">The hub keeps your GitHub user id, the installations and repository names you choose,
and run references. It keeps nothing from inside your game.</p></section>'''
    return page('Hub', body)


def sign_in(request):
    config = request.app.config
    if not config.sign_in_ready:
        return unconfigured(request)
    state = secrets.token_urlsafe(32)
    cookie = session.new_state(config['cookie_key'], state, request.app.clock())
    return redirect(request.app.github.authorize_url(state), headers=[
        session.set_cookie(session.STATE_COOKIE, cookie, session.STATE_SECONDS, config.secure_cookies)])


def callback(request):
    app, config = request.app, request.app.config
    if not config.sign_in_ready:
        return unconfigured(request)
    clear_state = session.clear_cookie(session.STATE_COOKIE, config.secure_cookies)
    now = app.clock()

    def refuse(title, text, status=400):
        response = message(title, text, status=status, link=('/', 'Back to the hub'))
        response.headers.append(clear_state)
        return response

    if 'error' in request.query:
        return refuse('Sign-in was not completed', 'GitHub returned without signing you in. Nothing was saved.')
    state, code = request.query.get('state', ''), request.query.get('code', '')
    held = session.verify(config['cookie_key'], 'state', request.cookies.get(session.STATE_COOKIE), now)
    if (not held or not state or not code or len(code) > 512
            or not secrets.compare_digest(held['state'].encode(), state.encode())):
        return refuse('Sign-in could not be checked',
                      'This sign-in did not start in this browser in the last ten minutes. Start again.')
    if not app.store.consume_state(held['state'], held['exp'], now):
        return refuse('Sign-in could not be checked', 'This sign-in link was already used. Start again.')
    try:
        token = app.github.exchange_code(code)
        uid, login = app.github.user(token)
        seen = app.github.user_access(token)
    except GitHubError as error:
        return refuse('Sign-in did not finish', f'{error}. You are not signed in and nothing was saved.', 502)
    finally:
        token = None  # the user token lives for this request only
    expires = int(now) + session.SESSION_SECONDS
    app.store.set_access(uid, Access(expires, {i: names for i, (_, names) in seen.items()},
                                     {i: account for i, (account, _) in seen.items()}))
    cookie = session.new_session(config['cookie_key'], uid, login, now)
    return redirect('/projects', headers=[
        clear_state, session.set_cookie(session.SESSION_COOKIE, cookie, session.SESSION_SECONDS, config.secure_cookies)])


def same_origin(request):
    """A state-changing POST must come from a page of this hub. Missing both headers is refused."""
    origin = request.app.config['origin']
    sent = request.headers.get('origin')
    if sent is not None:
        return sent == origin
    referer = request.headers.get('referer', '')
    return referer == origin or referer.startswith(origin + '/')


def sign_out(request):
    config = request.app.config
    if not config.sign_in_ready:
        return unconfigured(request)
    if not same_origin(request):
        return message('Sign-out refused', 'This request did not come from a page of this hub.', status=403)
    user = request.user()
    if user:
        request.app.store.forget_user(user[0])
    return redirect('/', status=303, headers=[session.clear_cookie(session.SESSION_COOKIE, config.secure_cookies)])


def projects(request):
    if not request.app.config.sign_in_ready:
        return unconfigured(request)
    user = request.user()
    access = request.app.store.access(user[0], request.app.clock()) if user else None
    if not user or access is None:
        response = redirect('/')
        if user:  # the session outlived its access record (a restart): sign the browser out
            response.headers.append(session.clear_cookie(session.SESSION_COOKIE, request.app.config.secure_cookies))
        return response
    install = escape(request.app.github.install_url())
    groups = []
    for iid in sorted(access.repositories):
        names = sorted(access.repositories[iid])
        items = ''.join(f'<li><code>{escape(n)}</code></li>' for n in names) or \
            '<li class="note">No repositories selected in this installation.</li>'
        groups.append(f'<section aria-label="Installation on {escape(access.accounts.get(iid, ""))}">'
                      f'<h2>{escape(access.accounts.get(iid, ""))}</h2><ul class="runs">{items}</ul></section>')
    if groups:
        listing = ''.join(groups)
    else:
        listing = (f'<section class="empty"><h2>No repositories connected</h2><p>Install the Expectrail App on '
                   f'a repository to connect it. Verification then runs in that repository\'s own CI.</p></section>')
    body = f'''<div class="workspace-head"><section class="project"><p class="caption">Connected repositories</p>
<h1>Your projects</h1>
<p class="note">As GitHub reported them when you signed in. Installed or changed the App since?
<a href="/sign-in">Refresh from GitHub</a>.</p></section></div>
{listing}
<section><h2>Connect or disconnect</h2>
<p><a class="action-link" href="{install}">Install the Expectrail App on a repository</a></p>
<p>To disconnect, uninstall the App in <a href="https://github.com/settings/installations">your GitHub settings</a>.
The hub drops that installation and its run references as soon as GitHub tells it.</p></section>'''
    return page('Your projects', body, signed_in=user[1], headers=[])
