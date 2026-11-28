// Stage only the five public files also served by hub/server.py.
import { mkdir, copyFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { securityHeaders } from './service.js';

export async function prepare(target) {
  // Require a fresh directory: a leftover file must never enter the deployment.
  await mkdir(target);
  await mkdir(join(target, 'assets/fonts'), { recursive: true });
  for (const [name, source] of [
    ['expectrail.css', 'docs/assets/expectrail.css'],
    ['hub.css', 'docs/assets/hub.css'],
    ['hub-fonts.css', 'hub/fonts.css'],
    ...['regular', 'bold'].map((weight) => {
      const path = 'fonts/texgyreadventor-' + weight + '.woff';
      return [path, 'docs/assets/' + path];
    }),
  ]) {
    await copyFile(new URL('../../' + source, import.meta.url), join(target, 'assets', name));
  }
  await writeFile(
    join(target, '_headers'),
    [
      '/assets/*',
      ...Object.entries(securityHeaders).map(([name, value]) => '  ' + name + ': ' + value),
      '',
    ].join('\n'),
  );
}
if (process.argv[1] === fileURLToPath(import.meta.url))
  await prepare(fileURLToPath(new URL('./.public', import.meta.url)));
