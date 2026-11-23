import test from 'node:test';
import assert from 'node:assert/strict';
import { githubAccess } from '../github.js';
import { fixture } from '../fixtures/stub.mjs';

function exchange(f, code = f.code) {
  const {
    EXPECTRAIL_HUB_CLIENT_ID: client_id,
    EXPECTRAIL_HUB_CLIENT_SECRET: client_secret,
    EXPECTRAIL_HUB_ORIGIN: origin,
  } = f.env;
  return githubAccess({ client_id, client_secret, origin }, code, f.transport);
}

test('OAuth identity and installation names come only from the authorizing developer', async (t) => {
  const network = t.mock.method(globalThis, 'fetch', () => {
    throw Error('unexpected network');
  });
  const f = fixture();
  const secondCode = f.register(17, 'second', { 2: { account: 'studio', names: ['studio/other'] } });
  assert.deepEqual(await exchange(f), {
    login: 'dev',
    uid: 9,
    repositories: { 2: ['studio/game'] },
    accounts: { 2: 'studio' },
  });
  assert.deepEqual(await exchange(f, secondCode), {
    login: 'second',
    uid: 17,
    repositories: { 2: ['studio/other'] },
    accounts: { 2: 'studio' },
  });
  for (const { url, opts } of f.calls) {
    assert.equal(opts.redirect, 'error');
    assert.equal(
      new URL(url).origin,
      opts.headers.Authorization ? 'https://api.github.com' : 'https://github.com',
    );
  }
  assert.equal(network.mock.callCount(), 0);
});

test('incomplete or oversized answers fail the whole exchange', async () => {
  for (const response of [
    () => Response.json({ total_count: 1, repositories: [] }),
    () => new Response('x'.repeat(1024 * 1024 + 1)),
    () => Response.json({ total_count: 1, repositories: [{ full_name: 'bad name' }] }),
  ]) {
    const f = fixture();
    f.override = (path) => (path.endsWith('/repositories') ? response() : null);
    await assert.rejects(exchange(f));
  }
});
