// The request handlers follow hub/auth.py and hub/installations.py. Time is Unix seconds.
import { sign, verify, macKey, validLogin, SESSION_SECONDS, STATE_SECONDS } from './session.js';
import { GitHubError, githubAccess, validRepo, boundedBytes } from './github.js';

export const securityHeaders = {
  'Content-Security-Policy':
    "default-src 'none'; style-src 'self'; img-src 'self'; font-src 'self'; form-action 'self' https://github.com; frame-ancestors 'none'; base-uri 'none'",
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Referrer-Policy': 'same-origin',
  'Cache-Control': 'no-store',
};
const esc = (s) =>
  String(s)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
function html(status, title, body = '', login = null) {
  const account = login
    ? `<form class="account" method="post" action="/sign-out">
    <span>Signed in as <strong>${esc(login)}</strong></span> <button>Sign out</button></form>`
    : '';
  const document = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)} · Expectrail</title>
<link rel="stylesheet" href="/assets/expectrail.css"><link rel="stylesheet" href="/assets/hub.css">
<link rel="stylesheet" href="/assets/hub-fonts.css"></head><body>
<header class="mast"><div class="bar"><a class="wordmark" href="/">Expectrail</a>
<span class="place">Hub</span>${account}</div></header>
<main id="main"><h1>${esc(title)}</h1>${body}</main></body></html>`;
  return new Response(document, {
    status,
    headers: { ...securityHeaders, 'Content-Type': 'text/html; charset=utf-8' },
  });
}
function plain(status, message) {
  return new Response(message, {
    status,
    headers: { ...securityHeaders, 'Content-Type': 'text/plain; charset=utf-8' },
  });
}
function redirect(location, status = 302) {
  return new Response(null, { status, headers: { ...securityHeaders, Location: location } });
}
function cookie(response, name, value, age, secure) {
  response.headers.append(
    'Set-Cookie',
    name +
      '=' +
      value +
      '; Path=/; Max-Age=' +
      age +
      '; HttpOnly; SameSite=Lax' +
      (secure ? '; Secure' : ''),
  );
  return response;
}
function readCookie(request, name) {
  const part = (request.headers.get('cookie') || '')
    .split(';')
    .map((x) => x.trim())
    .find((x) => x.startsWith(name + '='));
  return part?.slice(name.length + 1);
}
function settings(env) {
  const c = {},
    missing = [];
  for (const key of [
    'origin',
    'client_id',
    'client_secret',
    'app_slug',
    'cookie_key',
    'webhook_secret',
  ]) {
    const name = 'EXPECTRAIL_HUB_' + key.toUpperCase();
    c[key] = (env[name] || '').trim();
    let reason = '';
    if (key === 'origin' && c[key]) {
      try {
        const u = new URL(c[key]);
        if (
          ![u.origin, u.origin + '/'].includes(c[key]) ||
          !(
            u.protocol === 'https:' ||
            (u.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(u.hostname))
          )
        )
          throw Error();
        c[key] = u.origin;
      } catch {
        c[key] = '';
        reason = ': must be https on a bare origin (http allowed locally)';
      }
    }
    if (key === 'cookie_key' && c[key] && new TextEncoder().encode(c[key]).length < 32) {
      c[key] = '';
      reason = ': shorter than 32 bytes';
    }
    if (key === 'app_slug' && c[key] && !/^[a-z0-9-]+$/i.test(c[key])) {
      c[key] = '';
      reason = ': not a GitHub App slug';
    }
    if (!c[key] && key !== 'webhook_secret') missing.push(name + reason);
  }
  return { c, missing };
}
async function delivery(req, secret, store) {
  if (!secret) return plain(503, 'Installation deliveries are not configured');
  let bytes;
  try {
    bytes = await boundedBytes(req.body, 1024 * 1024);
  } catch (e) {
    return plain(e instanceof RangeError ? 413 : 400, 'Invalid delivery body');
  }
  const sig = req.headers.get('x-hub-signature-256') || '';
  if (
    !/^sha256=[0-9a-f]{64}$/.test(sig) ||
    !(await crypto.subtle.verify(
      'HMAC',
      await macKey(secret),
      Uint8Array.from(sig.slice(7).match(/../g), (v) => parseInt(v, 16)),
      bytes,
    ))
  )
    return plain(401, 'Signature does not match');
  let data;
  try {
    data = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return plain(400, 'Malformed delivery');
  }
  const event = req.headers.get('x-github-event') || '';
  if (typeof data?.action !== 'string' || !/^[a-z_]{1,64}$/.test(event))
    return plain(400, 'Malformed delivery');
  if (!['installation', 'installation_repositories'].includes(event)) return plain(202, 'Event unused');
  const id = data.installation?.id,
    login = data.installation?.account?.login;
  if (!Number.isSafeInteger(id) || id <= 0 || !validLogin(login))
    return plain(400, 'Malformed installation');
  const op = event + '/' + data.action;
  if (op === 'installation/deleted') await store.uninstalled(id);
  else if (op === 'installation/suspend') await store.suspended(id);
  else if (
    [
      'installation/created',
      'installation_repositories/added',
      'installation_repositories/removed',
    ].includes(op)
  ) {
    const field = event === 'installation' ? 'repositories' : 'repositories_' + data.action;
    const rows = data[field] ?? [];
    if (!Array.isArray(rows) || !rows.every((r) => validRepo(r?.full_name)))
      return plain(400, 'Malformed repository list');
    const names = [...new Set(rows.map((r) => r.full_name))];
    if (data.action === 'created') await store.installed(id, login, names);
    else if (data.action === 'added') await store.repositoriesAdded(id, login, names);
    else await store.repositoriesRemoved(id, names);
  } else return plain(202, 'Action unused');
  return plain(200, 'Recorded');
}
const methods = new Map([
  ['/', 'GET'],
  ['/sign-in', 'GET'],
  ['/callback', 'GET'],
  ['/projects', 'GET'],
  ['/sign-out', 'POST'],
  ['/installed', 'GET'],
  ['/github/events', 'POST'],
]);
export function createService({
  env,
  store,
  transport = fetch,
  clock = () => Math.floor(Date.now() / 1000),
}) {
  const { c, missing } = settings(env),
    secure = c.origin.startsWith('https:');
  async function handle(req) {
    const url = new URL(req.url),
      path = url.pathname,
      now = clock();
    if (!methods.has(path)) return html(404, 'Page not found');
    if (methods.get(path) !== req.method) return html(405, 'Method not allowed');
    if (path === '/github/events') return delivery(req, c.webhook_secret, store);
    if (path === '/installed') {
      const user =
        c.cookie_key && (await verify(c.cookie_key, 'session', readCookie(req, 'er_session'), now));
      return html(
        200,
        'Back from GitHub',
        '<p>Refresh your access to see the repositories GitHub now lets you see.</p><a href="/sign-in">Refresh from GitHub</a>',
        user?.login,
      );
    }
    if (missing.length)
      return html(
        path === '/' ? 200 : 503,
        'GitHub sign-in is unconfigured',
        'Missing or unusable settings: ' +
          [...missing, ...(c.webhook_secret ? [] : ['EXPECTRAIL_HUB_WEBHOOK_SECRET'])].join(', '),
      );
    const user = await verify(c.cookie_key, 'session', readCookie(req, 'er_session'), now);
    if (path === '/')
      return user
        ? redirect('/projects')
        : html(
            200,
            'Your projects, verified in your own CI',
            '<a href="/sign-in">Sign in with GitHub</a>',
          );
    if (path === '/sign-in') {
      const state = Array.from(crypto.getRandomValues(new Uint8Array(32)), (b) =>
        b.toString(16).padStart(2, '0'),
      ).join('');
      const query = new URLSearchParams({
        client_id: c.client_id,
        state,
        redirect_uri: c.origin + '/callback',
        allow_signup: 'true',
      });
      return cookie(
        redirect('https://github.com/login/oauth/authorize?' + query),
        'er_state',
        await sign(c.cookie_key, 'state', { state, exp: now + STATE_SECONDS }),
        STATE_SECONDS,
        secure,
      );
    }
    if (path === '/callback') {
      const clear = (res) => cookie(res, 'er_state', '', 0, secure);
      const state = url.searchParams.get('state'),
        code = url.searchParams.get('code');
      const held = await verify(c.cookie_key, 'state', readCookie(req, 'er_state'), now);
      if (url.searchParams.has('error'))
        return clear(html(400, 'Sign-in was not completed', 'Nothing was saved.'));
      if (
        !held ||
        !state ||
        !code ||
        code.length > 512 ||
        held.state !== state ||
        !(await store.consumeState(state, held.exp, now))
      )
        return clear(html(400, 'Sign-in could not be checked'));
      let access;
      try {
        access = await githubAccess(c, code, transport);
      } catch (error) {
        return clear(
          html(
            502,
            'GitHub sign-in did not finish',
            (error instanceof GitHubError ? esc(error.message) + ' ' : '') + 'Nothing was saved.',
          ),
        );
      }
      const { uid, login, repositories, accounts } = access,
        exp = now + SESSION_SECONDS;
      await store.setAccess(uid, { expires: exp, repositories, accounts }, now);
      return cookie(
        clear(redirect('/projects')),
        'er_session',
        await sign(c.cookie_key, 'session', { uid, login, exp }),
        SESSION_SECONDS,
        secure,
      );
    }
    if (path === '/sign-out') {
      const origin = req.headers.get('origin'),
        ref = req.headers.get('referer') || '';
      if (origin !== null ? origin !== c.origin : ref !== c.origin && !ref.startsWith(c.origin + '/'))
        return html(403, 'Sign-out refused');
      if (user) await store.forgetUser(user.uid);
      return cookie(redirect('/', 303), 'er_session', '', 0, secure);
    }
    if (!user) return redirect('/');
    const access = await store.access(user.uid, now);
    if (!access) return cookie(redirect('/'), 'er_session', '', 0, secure);
    const groups = Object.entries(access.repositories).map(
      ([id, names]) =>
        '<h2>' +
        esc(access.accounts[id]) +
        '</h2><ul>' +
        names.map((n) => '<li>' + esc(n) + '</li>').join('') +
        '</ul>',
    );
    return html(
      200,
      'Your projects',
      (groups.join('') || '<p>No repositories connected</p>') +
        '<p>As GitHub reported them when you signed in. <a href="/sign-in">Refresh from GitHub</a>.</p>' +
        '<p><a href="https://github.com/apps/' +
        c.app_slug +
        '/installations/new">Install the Expectrail App</a> · <a href="https://github.com/settings/installations">Manage installations</a></p>',
      user.login,
    );
  }
  return {
    async handle(req) {
      try {
        return await handle(req);
      } catch {
        return html(500, 'The hub could not answer this request');
      }
    },
  };
}
