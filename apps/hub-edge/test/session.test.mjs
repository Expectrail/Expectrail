import test from 'node:test';
import assert from 'node:assert/strict';
import { verify, sign } from '../session.js';
const key = crypto.randomUUID();
test('unsigned cookies are signed out, including non-ASCII, empty and oversized tokens', async () => {
  for (const value of [null, {}, '', '.', '..', 'é.abc', '"é.abc"', 'a'.repeat(2049), 'wrong.wrong']) {
    assert.equal(await verify(key, 'session', value, 1), null);
  }
});
test('wire format matches the independent HMAC implementation used by the Python reference', async () => {
  const { createHmac } = await import('node:crypto');
  const data = { uid: 7, exp: 200, login: 'dev' };
  const body = Buffer.from('{"exp":200,"login":"dev","uid":7}').toString('base64url');
  const expected =
    body +
    '.' +
    createHmac('sha256', key)
      .update('expectrail-hub/v1|session|' + body)
      .digest('base64url');
  assert.equal(await sign(key, 'session', data), expected);
  assert.deepEqual(await verify(key, 'session', expected, 199), data);
  for (const [k, p, t, n] of [
    [key, 'session', expected, 200],
    [key, 'state', expected, 0],
    [crypto.randomUUID(), 'session', expected, 0],
    [key, 'session', expected + '.', 0],
  ])
    assert.equal(await verify(k, p, t, n), null);
  for (const bad of [
    { ...data, uid: true },
    { ...data, exp: '2' },
    { ...data, uid: 0 },
    { ...data, login: 'bad/name' },
    { ...data, extra: 1 },
  ])
    await assert.rejects(sign(key, 'session', bad));
  for (const malformed of [Buffer.from('{'), Buffer.from([255])]) {
    const b = malformed.toString('base64url'),
      mac = createHmac('sha256', key)
        .update('expectrail-hub/v1|session|' + b)
        .digest('base64url');
    assert.equal(await verify(key, 'session', b + '.' + mac, 0), null);
  }
});
