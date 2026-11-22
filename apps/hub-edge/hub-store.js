// The hub's three durable record types, with the same lifetimes as hub/store.py.
const STATE = "state:";
const ACCESS = "access:";
const INSTALLATION = "installation:";
const STATE_SECONDS = 600;
const ACCESS_SECONDS = 3600;
const LOGIN = /^[a-z\d](?:[a-z\d-]{0,38})$/i;
const REPOSITORY = /^[a-z\d][a-z\d-]{0,38}\/[a-z\d_.-]{1,100}$/i;
const clockSeconds = () => Math.floor(Date.now() / 1000);

function id(value) {
  const number = Number(value);
  if (!Number.isSafeInteger(number) || number < 1 || String(number) !== String(value)) {
    throw new TypeError("Expected a GitHub numeric ID");
  }
  return String(number);
}

function login(value) {
  if (typeof value !== "string" || !LOGIN.test(value)) throw new TypeError("Invalid GitHub login");
  return value;
}

function names(values) {
  if (!Array.isArray(values) || values.some((value) => typeof value !== "string" || !REPOSITORY.test(value))) {
    throw new TypeError("Invalid GitHub repository names");
  }
  return [...new Set(values)];
}

function expiryAllowed(expires, now, duration) {
  return Number.isSafeInteger(now) && Number.isSafeInteger(expires) && expires > now && expires - now <= duration;
}

async function stateKey(state) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(state));
  return STATE + Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

// RunIt-style adapter. Each operation gets its own transaction, including the
// read and write of a state consume and all changes from a removal delivery.
function transaction(storage, operation) {
  return storage.transaction((txn) => operation({
    get: (key) => txn.get(key),
    put: (key, value) => txn.put(key, value),
    putMany: (entries) => txn.put(entries),
    delete: (key) => txn.delete(key),
    list: (prefix) => txn.list({ prefix }),
    getAlarm: () => txn.getAlarm(),
    setAlarm: (time) => txn.setAlarm(time),
    deleteAlarm: () => txn.deleteAlarm(),
  }));
}

async function schedule(txn, expires) {
  const time = expires * 1000;
  const current = await txn.getAlarm();
  if (current === null || time < current) await txn.setAlarm(time);
}

function projectAccess(value) {
  const repositories = {};
  const accounts = {};
  for (const [installation, repos] of Object.entries(value.repositories)) {
    const key = id(installation);
    repositories[key] = names(repos);
    accounts[key] = login(value.accounts[key]);
  }
  return { expires: value.expires, repositories, accounts };
}

async function revoke(txn, installation, removed) {
  let batch = [];
  for (const [key, row] of await txn.list(ACCESS)) {
    if (!Object.hasOwn(row.repositories, installation)) continue;
    if (removed) {
      row.repositories[installation] = row.repositories[installation].filter((repo) => !removed.has(repo.toLowerCase()));
    } else {
      delete row.repositories[installation];
      delete row.accounts[installation];
    }
    batch.push([key, row]);
    if (batch.length === 128) {
      await txn.putMany(Object.fromEntries(batch));
      batch = [];
    }
  }
  if (batch.length) await txn.putMany(Object.fromEntries(batch));
}

export function createHubStore(storage, { clock = clockSeconds } = {}) {
  const atomic = (operation) => transaction(storage, operation);
  return {
    async consumeState(state, expires, now) {
      if (!Number.isSafeInteger(now) || typeof state !== "string" || !state || state.length > 256) return false;
      const key = await stateKey(state);
      return atomic(async (txn) => {
        const prior = await txn.get(key);
        if (prior && prior.expires > now) return false;
        if (!expiryAllowed(expires, now, STATE_SECONDS)) {
          if (prior) await txn.delete(key);
          return false;
        }
        await txn.put(key, { expires });
        await schedule(txn, expires);
        return true;
      });
    },

    setAccess(uid, value, now = clock()) {
      const key = ACCESS + id(uid);
      if (!expiryAllowed(value.expires, now, ACCESS_SECONDS)) throw new TypeError("Invalid access expiry");
      const row = projectAccess(value);
      return atomic(async (txn) => {
        await txn.put(key, row);
        await schedule(txn, row.expires);
      });
    },

    access(uid, now) {
      if (!Number.isSafeInteger(now)) throw new TypeError("Invalid access time");
      const key = ACCESS + id(uid);
      return atomic(async (txn) => {
        const row = await txn.get(key);
        if (!row) return null;
        if (row.expires > now) return row;
        await txn.delete(key);
        return null;
      });
    },

    forgetUser: (uid) => atomic((txn) => txn.delete(ACCESS + id(uid))),

    installed(installation, account, repositories) {
      const row = { account: login(account), repositories: names(repositories) };
      return atomic((txn) => txn.put(INSTALLATION + id(installation), row));
    },

    uninstalled: (installation) => atomic(async (txn) => {
      const key = id(installation);
      await txn.delete(INSTALLATION + key);
      await revoke(txn, key);
    }),

    suspended: (installation) => atomic(async (txn) => {
      const key = id(installation);
      const row = await txn.get(INSTALLATION + key);
      if (row) await txn.put(INSTALLATION + key, { ...row, repositories: [] });
      await revoke(txn, key);
    }),

    repositoriesAdded(installation, account, repositories) {
      const key = INSTALLATION + id(installation);
      const next = { account: login(account), repositories: names(repositories) };
      return atomic(async (txn) => {
        const prior = await txn.get(key);
        const row = prior ?? next;
        row.repositories = [...new Set([...row.repositories, ...next.repositories])];
        await txn.put(key, row);
      });
    },

    repositoriesRemoved(installation, repositories) {
      const key = id(installation);
      const removed = new Set(names(repositories).map((repo) => repo.toLowerCase()));
      return atomic(async (txn) => {
        const row = await txn.get(INSTALLATION + key);
        if (row) {
          row.repositories = row.repositories.filter((repo) => !removed.has(repo.toLowerCase()));
          await txn.put(INSTALLATION + key, row);
        }
        await revoke(txn, key, removed);
      });
    },
  };
}

async function expire(storage, now) {
  await transaction(storage, async (txn) => {
    let next = Infinity;
    for (const prefix of [STATE, ACCESS]) {
      for (const [key, row] of await txn.list(prefix)) {
        if (row.expires <= now) await txn.delete(key);
        else next = Math.min(next, row.expires);
      }
    }
    if (Number.isFinite(next)) await txn.setAlarm(next * 1000);
    else await txn.deleteAlarm();
  });
}

// worker.js (#785) exports this class as HubSessions and forwards every
// request through env.HUB.idFromName("hub"), like the RunIt wrapper.
export function createHubSessions(createService, { clock = clockSeconds } = {}) {
  return class HubSessions {
    constructor(state, env) {
      this.storage = state.storage;
      const store = createHubStore(this.storage, { clock });
      this.service = createService({ env, store, clock, waitUntil: (promise) => state.waitUntil(promise) });
    }

    fetch(request) {
      return this.service.handle(request);
    }

    alarm() {
      return expire(this.storage, clock());
    }
  };
}
