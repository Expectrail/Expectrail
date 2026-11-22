// Test-only transport. Values that stand in for credentials exist only for this process.
export function fixture() {
  const env = {
    EXPECTRAIL_HUB_ORIGIN: 'https://hub.example',
    EXPECTRAIL_HUB_APP_SLUG: 'sample',
    ...Object.fromEntries(
      ['CLIENT_ID', 'CLIENT_SECRET', 'COOKIE_KEY', 'WEBHOOK_SECRET'].map((k) => [
        'EXPECTRAIL_HUB_' + k,
        crypto.randomUUID(),
      ]),
    ),
  };
  const token = crypto.randomUUID(),
    code = crypto.randomUUID(),
    calls = [],
    users = new Map(),
    used = new Set();
  const store = {
    consumeState(state) {
      if (used.has(state)) return false;
      used.add(state);
      return true;
    },
    setAccess(uid, value) {
      users.set(uid, value);
    },
    access(uid, now) {
      const v = users.get(uid);
      return v?.expires > now ? v : null;
    },
    forgetUser(uid) {
      users.delete(uid);
    },
    installed() {},
    repositoriesAdded() {},
    uninstalled(id) {
      for (const a of users.values()) delete a.repositories[id];
    },
    suspended(id) {
      this.uninstalled(id);
    },
    repositoriesRemoved(id, names) {
      for (const a of users.values())
        if (a.repositories[id])
          a.repositories[id] = a.repositories[id].filter((n) => !names.includes(n));
    },
  };
  const stub = { env, token, code, calls, store, users, now: 1000, override: null };
  const authorizations = new Map(),
    identities = new Map();
  function register(
    id,
    login,
    repositories,
    authCode = crypto.randomUUID(),
    userToken = crypto.randomUUID(),
  ) {
    authorizations.set(authCode, userToken);
    identities.set(userToken, { id, login, repositories });
    return authCode;
  }
  register(9, 'dev', { 2: { account: 'studio', names: ['studio/game'] } }, code, token);
  stub.register = register;
  stub.transport = async (url, opts) => {
    calls.push({ url, opts });
    const u = new URL(url),
      path = u.pathname;
    if (stub.override) {
      const answer = stub.override(path, u, opts);
      if (answer) return answer;
    }
    if (url === 'https://github.com/login/oauth/access_token' && opts.method === 'POST') {
      const f = opts.body;
      if (
        f.get('client_secret') === env.EXPECTRAIL_HUB_CLIENT_SECRET &&
        f.get('client_id') === env.EXPECTRAIL_HUB_CLIENT_ID &&
        authorizations.has(f.get('code')) &&
        f.get('redirect_uri') === env.EXPECTRAIL_HUB_ORIGIN + '/callback'
      )
        return Response.json({ access_token: authorizations.get(f.get('code')) });
    }
    const who = identities.get(opts.headers.Authorization?.replace(/^Bearer /, ''));
    if (u.origin === 'https://api.github.com' && who) {
      if (path === '/user') return Response.json({ id: who.id, login: who.login });
      if (path === '/user/installations') {
        const installations = Object.entries(who.repositories).map(([id, repo]) => ({
          id: Number(id),
          account: { login: repo.account },
        }));
        return Response.json({ total_count: installations.length, installations });
      }
      const installation = path.match(/^\/user\/installations\/(\d+)\/repositories$/)?.[1];
      if (who.repositories[installation]) {
        const repositories = who.repositories[installation].names.map((full_name) => ({ full_name }));
        return Response.json({ total_count: repositories.length, repositories });
      }
    }
    throw Error('Unrecognised stub request');
  };
  return stub;
}
