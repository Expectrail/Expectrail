// Loading/discovering tests never installs a runtime. Missing means named skip, or required-mode fail.
import { createRequire } from 'node:module';
import { readFileSync, accessSync, constants } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

export const MINIFLARE_VERSION = '4.20260730.0';
export const WORKERD_VERSION = '1.20260730.1';
export const COMPATIBILITY_DATE = '2026-07-30';

export function runtime() {
  const require = createRequire(import.meta.url);
  let path;
  try { path = require.resolve('miniflare/package.json'); }
  catch (error) {
    if (error.code !== 'MODULE_NOT_FOUND') throw error;
    return {missing:`Miniflare ${MINIFLARE_VERSION} / workerd ${WORKERD_VERSION} is not installed; see docs/run-it-status-bound.md`};
  }
  const installed = JSON.parse(readFileSync(path,'utf8'));
  if (installed.version !== MINIFLARE_VERSION) throw new Error(`Miniflare ${installed.version} found; pinned ${MINIFLARE_VERSION} required`);
  const fromRuntime = createRequire(path);
  const workerd = fromRuntime('workerd');
  if (workerd.version !== WORKERD_VERSION) throw new Error(`workerd ${workerd.version} found; pinned ${WORKERD_VERSION} required`);
  let binary;
  try { binary=workerd.default; accessSync(binary,constants.X_OK); }
  catch (error) {
    if (!['ENOENT','MODULE_NOT_FOUND'].includes(error.code)) throw error;
    return {missing:`workerd ${WORKERD_VERSION} native executable is not installed for this platform`};
  }
  const nativeVersion = execFileSync(binary,['--version'],{encoding:'utf8',timeout:15000}).trim();
  if (nativeVersion !== 'workerd '+COMPATIBILITY_DATE) throw new Error(`Unexpected native runtime: ${nativeVersion}`);
  return {Miniflare:fromRuntime('miniflare').Miniflare,undici:fromRuntime('undici'),info:{miniflare:installed.version,workerd:workerd.version,
    nativeVersion,compatibilityDate:COMPATIBILITY_DATE}};
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const found=runtime();
  console.log(JSON.stringify(found.info || {missing:found.missing}));
  process.exitCode=found.missing ? 3 : 0;
}
