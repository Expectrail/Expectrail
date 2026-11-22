import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { prepare } from '../prepare-assets.mjs';
test('stage exactly the public hub styles and fonts', async (t) => {
  const dir = await mkdtemp(join(tmpdir(), 'hub-assets-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const dest = join(dir, 'public');
  await prepare(dest);
  assert.deepEqual((await readdir(join(dest, 'assets'))).sort(), [
    'expectrail.css',
    'fonts',
    'hub-fonts.css',
    'hub.css',
  ]);
  assert.deepEqual((await readdir(join(dest, 'assets/fonts'))).sort(), [
    'texgyreadventor-bold.woff',
    'texgyreadventor-regular.woff',
  ]);
  assert.match(await readFile(join(dest, 'assets/hub-fonts.css'), 'utf8'), /font-family: Adventor/);
  const headers = await readFile(join(dest, '_headers'), 'utf8');
  assert.match(headers, /Referrer-Policy: same-origin/);
  assert.match(headers, /frame-ancestors 'none'/);
  await assert.rejects(prepare(dest), { code: 'EEXIST' });
});
