import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { createService } from '../service.js';
import { verify } from '../session.js';
import { fixture } from '../fixtures/stub.mjs';
const origin = 'https://hub.example';
function setup() {
  const f = fixture();
  f.service = () =>
    createService({ env: f.env, store: f.store, transport: f.transport, clock: () => f.now });
  f.req = (path, options = {}) => f.service().handle(new Request(origin + path, options));
  f.start = async () => {
    const res = await f.req('/sign-in'),
      url = new URL(res.headers.get('Location'));
    assert.equal(url.origin + url.pathname, 'https://github.com/login/oauth/authorize');
    assert.equal(url.searchParams.get('redirect_uri'), origin + '/callback');
    const header = res.headers.get('set-cookie');
    for (const attr of ['Max-Age=600', 'HttpOnly', 'SameSite=Lax', 'Secure'])
      assert.ok(header.includes(attr));
    return {
      headers: { cookie: header.split(';')[0] },
      path: '/callback?' + new URLSearchParams({ state: url.searchParams.get('state'), code: f.code }),
    };
  };
  f.login = async () => {
    const flow = await f.start(),
      res = await f.req(flow.path, { headers: flow.headers });
    assert.equal(res.status, 302);
    assert.equal(res.headers.get('location'), '/projects');
    const c = res.headers.getSetCookie().find((x) => x.startsWith('er_session='));
    assert.match(c, /Max-Age=3600/);
    return c.split(';')[0];
  };
  f.deliver = async (event, payload, { key = f.env.EXPECTRAIL_HUB_WEBHOOK_SECRET, signature } = {}) => {
    const body = typeof payload === 'string' ? payload : JSON.stringify(payload);
    return f.req('/github/events', {
      method: 'POST',
      body,
      headers: {
        'x-github-event': event,
        'x-hub-signature-256':
          signature ?? 'sha256=' + createHmac('sha256', key).update(body).digest('hex'),
      },
    });
  };
  return f;
}
test('unconfigured service serves the home page and refuses sign-in routes', async () => {
  const f = setup();
  f.env = {};
  const res = await f.req('/');
  assert.equal(res.status, 200);
  assert.match(await res.text(), /unconfigured/);
  for (const path of ['/sign-in', '/callback', '/projects', '/sign-out', '/github/events']) {
    const res = await f.req(path, {
      method: ['/sign-out', '/github/events'].includes(path) ? 'POST' : 'GET',
    });
    assert.equal(res.status, 503);
    assert.equal(res.headers.get('Location'), null);
  }
});
test('only a usable origin, slug and signing key enable sign-in', async () => {
  for (const value of [
    'http://hub.example',
    'https://user@hub.example',
    'https://hub.example/path',
    'ftp://hub.example',
  ]) {
    const f = setup();
    f.env.EXPECTRAIL_HUB_ORIGIN = value;
    assert.equal((await f.req('/sign-in')).status, 503);
  }
  for (const name of ['COOKIE_KEY', 'APP_SLUG']) {
    const f = setup();
    f.env['EXPECTRAIL_HUB_' + name] = 'bad!';
    const res = await f.req('/sign-in');
    assert.equal(res.status, 503);
    assert.ok(!(await res.text()).includes('bad!'));
  }
  const f = setup();
  f.env.EXPECTRAIL_HUB_ORIGIN = 'http://localhost:8765';
  assert.doesNotMatch((await f.req('/sign-in')).headers.get('set-cookie'), /Secure/);
});
test('callback saves only access, projects lists that access, sign-out forgets it', async () => {
  const f = setup(),
    cookie = await f.login();
  assert.equal(f.calls.length, 4);
  assert.deepEqual(await verify(f.env.EXPECTRAIL_HUB_COOKIE_KEY, 'session', cookie.slice(11), f.now), {
    uid: 9,
    login: 'dev',
    exp: 4600,
  });
  assert.ok(!JSON.stringify([...f.users]).includes(f.token));
  const res = await f.req('/projects', { headers: { cookie } });
  assert.match(await res.text(), /studio\/game/);
  assert.equal((await f.req('/', { headers: { cookie } })).headers.get('Location'), '/projects');
  for (const headers of [
    {},
    { origin: 'null' },
    { origin: 'https://elsewhere.example' },
    { referer: origin + '.evil/' },
  ])
    assert.equal(
      (await f.req('/sign-out', { method: 'POST', headers: { cookie, ...headers } })).status,
      403,
    );
  assert.equal((await f.req('/sign-out')).status, 405);
  const out = await f.req('/sign-out', {
    method: 'POST',
    headers: { cookie, referer: origin + '/projects' },
  });
  assert.equal(out.status, 303);
  assert.match(out.headers.get('set-cookie'), /Max-Age=0/);
  assert.equal((await f.req('/projects', { headers: { cookie } })).headers.get('location'), '/');
});
test('wrong, missing, expired, cancelled or replayed state cannot start an exchange', async () => {
  for (const kind of ['missing', 'wrong', 'expired', 'cancel', 'reuse', 'purpose']) {
    const f = setup(),
      flow = await f.start();
    let { path, headers } = flow;
    if (kind === 'missing') headers = {};
    if (kind === 'wrong') path = path.replace('state=', 'state=wrong');
    if (kind === 'expired') f.now += 600;
    if (kind === 'cancel') path += '&error=denied';
    if (kind === 'reuse') await f.req(path, { headers });
    if (kind === 'purpose') headers = { cookie: (await f.login()).replace('er_session', 'er_state') };
    const before = f.calls.length,
      res = await f.req(path, { headers });
    assert.equal(res.status, 400, kind);
    assert.equal(f.calls.length, before);
    assert.match(res.headers.get('set-cookie'), /er_state=;.*Max-Age=0/);
  }
});
test('partial lists, rejected credentials, rate limits, malformed replies yield no access', async () => {
  for (const [path, response] of [
    ['/user', () => new Response(null, { status: 401 })],
    ['/user', () => new Response(null, { status: 429 })],
    ['/user/installations', () => Response.json({ total_count: 1, installations: [] })],
    ['/user/installations/2/repositories', () => Response.json({ total_count: 1, repositories: [] })],
    ['/user', () => Response.json({ id: 0, login: 'dev' })],
    ['/user', () => new Response('invalid')],
    ['/login/oauth/access_token', () => Response.json({ error: 'denied' })],
  ]) {
    const f = setup();
    f.override = (p) => (p === path ? response() : null);
    const flow = await f.start(),
      res = await f.req(flow.path, { headers: flow.headers });
    assert.equal(res.status, 502);
    assert.equal(f.users.size, 0);
    assert.doesNotMatch(res.headers.get('set-cookie'), /er_session/);
  }
});
test('unsigned cookies at every browser entry point stay signed out', async () => {
  const f = setup();
  for (const value of ['"é.abc"', '..', '', 'x'.repeat(2049), 'foreign']) {
    const headers = { cookie: 'er_session=' + value + '; er_state=' + value, origin };
    for (const [path, status] of [
      ['/', 200],
      ['/projects', 302],
      ['/callback?state=a&code=b', 400],
      ['/installed', 200],
      ['/sign-out', 303],
    ]) {
      assert.equal(
        (await f.req(path, { headers, method: path === '/sign-out' ? 'POST' : 'GET' })).status,
        status,
      );
    }
  }
});
test('authenticated installation changes and service error responses', async () => {
  for (const [event, action] of [
    ['installation', 'suspend'],
    ['installation', 'deleted'],
    ['installation_repositories', 'removed'],
  ]) {
    const f = setup(),
      cookie = await f.login();
    const data = {
      action,
      installation: { id: 2, account: { login: 'studio' } },
      repositories_removed: [{ full_name: 'studio/game' }],
    };
    assert.equal((await f.deliver(event, data, { signature: 'bad' })).status, 401);
    assert.match(await (await f.req('/projects', { headers: { cookie } })).text(), /studio\/game/);
    assert.equal((await f.deliver(event, data)).status, 200);
    assert.doesNotMatch(
      await (await f.req('/projects', { headers: { cookie } })).text(),
      /studio\/game/,
    );
  }
  const f = setup();
  for (const [event, data, status] of [
    ['ping', { action: 'unused' }, 202],
    ['installation', '{', 400],
    ['installation', { action: 'created' }, 400],
    ['installation', 'x'.repeat(1024 * 1024 + 1), 413],
  ])
    assert.equal((await f.deliver(event, data)).status, status);
  assert.equal((await f.req('/unknown')).status, 404);
  const cookie = await f.login();
  f.store.access = () => {
    throw Error('private diagnostic');
  };
  const res = await f.req('/projects', { headers: { cookie } });
  assert.equal(res.status, 500);
  assert.doesNotMatch(await res.text(), /private diagnostic/);
  for (const path of ['/', '/projects', '/installed', '/missing']) {
    const h = (await f.req(path)).headers;
    assert.equal(h.get('Cache-Control'), 'no-store');
    assert.equal(h.get('Referrer-Policy'), 'same-origin');
    assert.match(h.get('Content-Security-Policy'), /frame-ancestors 'none'/);
  }
});
test('installed page ignores query parameters; additions await fresh GitHub access', async () => {
  const f = setup();
  let names = [];
  f.override = (path) =>
    path === '/user/installations'
      ? Response.json({
          total_count: names.length ? 1 : 0,
          installations: names.length ? [{ id: 2, account: { login: 'studio' } }] : [],
        })
      : path.endsWith('/repositories')
        ? Response.json({
            total_count: names.length,
            repositories: names.map((full_name) => ({ full_name })),
          })
        : null;
  const cookie = await f.login(),
    list = async () => await (await f.req('/projects', { headers: { cookie } })).text();
  assert.match(await list(), /No repositories connected/);
  assert.match(await list(), /github.com\/apps\/sample\/installations\/new/);
  assert.doesNotMatch(
    await (await f.req('/installed?installation_id=2&setup_action=install')).text(),
    /installation_id/,
  );
  const calls = [];
  f.store.installed = (...args) => calls.push(args);
  f.store.repositoriesAdded = (...args) => calls.push(args);
  for (const [event, action, field] of [
    ['installation', 'created', 'repositories'],
    ['installation_repositories', 'added', 'repositories_added'],
  ]) {
    assert.equal(
      (
        await f.deliver(event, {
          action,
          installation: { id: 2, account: { login: 'studio' } },
          [field]: [{ full_name: 'studio/added' }],
        })
      ).status,
      200,
    );
    assert.deepEqual(calls.at(-1), [2, 'studio', ['studio/added']]);
  }
  names = ['studio/added'];
  assert.doesNotMatch(await list(), /studio\/added/);
  await f.login();
  assert.match(await list(), /studio\/added/);
  f.now += 3600;
  assert.equal((await f.req('/projects', { headers: { cookie } })).headers.get('Location'), '/');
});
test('paginated repository names stay scoped to the user; malformed pages never produce a session', async () => {
  const f = setup();
  f.override = (path, u) =>
    path.endsWith('/repositories')
      ? Response.json({
          total_count: 2,
          repositories: [
            { full_name: u.searchParams.get('page') === '1' ? 'studio/one' : 'studio/two' },
          ],
        })
      : null;
  const cookie = await f.login(),
    page = await (await f.req('/projects', { headers: { cookie } })).text();
  assert.match(page, /studio\/one/);
  assert.match(page, /studio\/two/);
  assert.doesNotMatch(page, /elsewhere/);
  for (const docs of [[{ full_name: '<script>' }], null]) {
    f.override = (path) =>
      path.endsWith('/repositories') ? Response.json({ total_count: 1, repositories: docs }) : null;
    const flow = await f.start();
    assert.equal((await f.req(flow.path, { headers: flow.headers })).status, 502);
  }
});
test('two developers see only their own grants and a lost access record clears the cookie', async (t) => {
  const network = t.mock.method(globalThis, 'fetch', () => {
    throw Error('unexpected network access');
  });
  const f = setup(),
    first = await f.login();
  f.code = f.register(13, 'other', { 2: { account: 'studio', names: ['studio/other'] } });
  const second = await f.login(),
    count = f.calls.length;
  for (const [cookie, allowed, hidden] of [
    [first, 'studio/game', 'studio/other'],
    [second, 'studio/other', 'studio/game'],
  ]) {
    const html = await (await f.req('/projects', { headers: { cookie } })).text();
    assert.ok(html.includes(allowed));
    assert.ok(!html.includes(hidden));
    assert.ok(!html.includes(f.token));
    assert.ok(!cookie.includes(f.token));
  }
  assert.equal(f.calls.length, count);
  for (const { url, opts } of f.calls) {
    assert.equal(
      new URL(url).origin,
      opts.headers.Authorization ? 'https://api.github.com' : 'https://github.com',
    );
  }
  f.users.clear();
  const res = await f.req('/projects', { headers: { cookie: first } });
  assert.equal(res.headers.get('location'), '/');
  assert.match(res.headers.get('set-cookie'), /Max-Age=0/);
  assert.equal(network.mock.callCount(), 0);
});

test('only one of two callbacks can exchange a shared state', async () => {
  const f = setup();
  const { path, headers } = await f.start();
  const replies = await Promise.all([f.req(path, { headers }), f.req(path, { headers })]);
  assert.deepEqual(replies.map((r) => r.status).sort(), [302, 400]);
  assert.equal(f.calls.filter((c) => c.url.endsWith('/login/oauth/access_token')).length, 1);
});

test('a delivery signed by another key cannot revoke access', async () => {
  const f = setup(),
    cookie = await f.login();
  const installation = { id: 2, account: { login: 'studio' } };
  const reply = await f.deliver(
    'installation',
    { action: 'deleted', installation },
    { key: crypto.randomUUID() },
  );
  assert.equal(reply.status, 401);
  assert.match(await (await f.req('/projects', { headers: { cookie } })).text(), /studio\/game/);
});

test('configuration explains an unusable setting without showing its value', async () => {
  const f = setup(),
    value = crypto.randomUUID().slice(0, 9);
  f.env.EXPECTRAIL_HUB_COOKIE_KEY = value;
  f.env.EXPECTRAIL_HUB_ORIGIN = 'http://hub.example';
  const page = await (await f.req('/')).text();
  assert.match(page, /EXPECTRAIL_HUB_COOKIE_KEY: shorter than 32 bytes/);
  assert.match(page, /EXPECTRAIL_HUB_ORIGIN: must be https/);
  assert.ok(!page.includes(value));
  assert.ok(!page.includes(f.env.EXPECTRAIL_HUB_CLIENT_SECRET));
});
