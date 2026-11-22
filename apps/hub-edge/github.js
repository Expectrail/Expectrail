// GitHub replies are data. Only these fixed OAuth/user API endpoints receive credentials.
import { validLogin } from './session.js';
export class GitHubError extends Error {}
export const validRepo = (name) =>
  typeof name === 'string' && /^[a-z\d-]{1,39}\/[a-z\d._-]{1,100}$/i.test(name);
export async function boundedBytes(stream, limit) {
  if (!stream) throw Error('missing body');
  const reader = stream.getReader(),
    chunks = [];
  let length = 0;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    length += value.length;
    if (length > limit) {
      await reader.cancel();
      throw RangeError('body too large');
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  return bytes;
}
export async function githubAccess(config, code, transport) {
  async function call(url, options) {
    const res = await transport(url, {
      ...options,
      redirect: 'error',
      signal: AbortSignal.timeout(15000),
      headers: {
        Accept: 'application/json',
        'User-Agent': 'Expectrail-hub',
        'X-GitHub-Api-Version': '2022-11-28',
        ...options.headers,
      },
    });
    if (
      [403, 429].includes(res.status) &&
      (res.headers.get('x-ratelimit-remaining') === '0' || res.headers.has('retry-after'))
    )
      throw new GitHubError('GitHub rate limit reached. Try again later.');
    if (res.status === 401) throw new GitHubError('GitHub refused the credentials.');
    if (!res.ok) throw new GitHubError('GitHub answered ' + res.status + '.');
    return JSON.parse(new TextDecoder().decode(await boundedBytes(res.body, 1024 * 1024)));
  }
  const { access_token: token } = await call('https://github.com/login/oauth/access_token', {
    method: 'POST',
    body: new URLSearchParams({
      client_id: config.client_id,
      client_secret: config.client_secret,
      code,
      redirect_uri: config.origin + '/callback',
    }),
  });
  if (typeof token !== 'string' || !token) throw Error('GitHub did not complete sign-in');
  const get = (path) =>
    call('https://api.github.com' + path, { headers: { Authorization: 'Bearer ' + token } });
  const { id, login } = await get('/user');
  if (!Number.isSafeInteger(id) || id <= 0 || !validLogin(login)) throw Error('invalid GitHub user');
  async function pages(path, key) {
    const items = [];
    for (let page = 1; page <= 10; page++) {
      const data = await get(path + '?per_page=100&page=' + page);
      if (!Array.isArray(data[key]) || !Number.isSafeInteger(data.total_count))
        throw Error('invalid list');
      items.push(...data[key]);
      if (items.length === data.total_count) return items;
      if (!data[key].length || items.length > data.total_count) break;
    }
    throw Error('incomplete GitHub list');
  }
  const repositories = {},
    accounts = {};
  for (const item of await pages('/user/installations', 'installations')) {
    if (!Number.isSafeInteger(item.id) || item.id <= 0 || !validLogin(item.account?.login))
      throw Error('invalid installation');
    accounts[item.id] = item.account.login;
    const names = new Set();
    for (const repo of await pages('/user/installations/' + item.id + '/repositories', 'repositories')) {
      if (!validRepo(repo.full_name)) throw Error('invalid repository');
      names.add(repo.full_name);
    }
    repositories[item.id] = [...names].sort();
  }
  return { uid: id, login, repositories, accounts };
}
