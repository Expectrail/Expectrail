// Wire format and lifetimes match hub/session.py.
const utf8 = new TextEncoder();
const b64 = (bytes) =>
  btoa(String.fromCharCode(...bytes))
    .replaceAll('+', '-')
    .replaceAll('/', '_')
    .replace(/=+$/, '');
const decode = (text) =>
  Uint8Array.from(atob(text.replaceAll('-', '+').replaceAll('_', '/')), (c) => c.charCodeAt(0));
export const SESSION_SECONDS = 3600,
  STATE_SECONDS = 600;
export const validLogin = (value) =>
  typeof value === 'string' && /^[a-z0-9][a-z0-9-]{0,38}$/i.test(value);
export async function macKey(key) {
  return crypto.subtle.importKey('raw', utf8.encode(key), { name: 'HMAC', hash: 'SHA-256' }, false, [
    'sign',
    'verify',
  ]);
}
function shape(purpose, data) {
  if (!data || !Number.isSafeInteger(data.exp)) return false;
  const fields = Object.keys(data).sort().join(',');
  if (purpose === 'session')
    return (
      fields === 'exp,login,uid' &&
      Number.isSafeInteger(data.uid) &&
      data.uid > 0 &&
      validLogin(data.login)
    );
  return purpose === 'state' && fields === 'exp,state' && typeof data.state === 'string';
}
const message = (purpose, body) => utf8.encode('expectrail-hub/v1|' + purpose + '|' + body);
export async function sign(key, purpose, data) {
  if (!shape(purpose, data)) throw new TypeError('invalid cookie fields');
  const json = JSON.stringify(data, Object.keys(data).sort()).replace(
    /[\u007f-\uffff]/g,
    (c) => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'),
  );
  const body = b64(utf8.encode(json));
  const mac = await crypto.subtle.sign('HMAC', await macKey(key), message(purpose, body));
  return body + '.' + b64(new Uint8Array(mac));
}
export async function verify(key, purpose, token, now) {
  if (typeof token !== 'string' || token.length > 2048 || !/^[\w-]{1,2000}\.[\w-]{43}$/.test(token))
    return null;
  try {
    const [body, signature] = token.split('.');
    const bytes = decode(signature);
    if (
      b64(bytes) !== signature ||
      !(await crypto.subtle.verify('HMAC', await macKey(key), bytes, message(purpose, body)))
    )
      return null;
    const data = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(decode(body)));
    return shape(purpose, data) && data.exp > now ? data : null;
  } catch {
    return null;
  }
}
