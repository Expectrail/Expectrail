import assert from "node:assert/strict";
import { test } from "node:test";
import { createHubSessions, createHubStore } from "../hub-store.js";

// Only the backing storage survives a new object. Transactions commit a copy in order.
class Storage {
  data = new Map();
  alarm = null;
  pending = Promise.resolve();

  transaction(operation) {
    const next = this.pending.then(async () => {
      const rows = structuredClone(this.data);
      let alarm = this.alarm;
      const result = await operation({
        get: async (key) => structuredClone(rows.get(key)),
        put: async (key, value) => {
          if (typeof key === "string") rows.set(key, structuredClone(value));
          else for (const [name, row] of Object.entries(key)) rows.set(name, structuredClone(row));
        },
        delete: async (key) => rows.delete(key),
        list: async ({ prefix }) => new Map([...rows].filter(([key]) => key.startsWith(prefix))),
        getAlarm: async () => alarm,
        setAlarm: async (time) => { alarm = time; },
        deleteAlarm: async () => { alarm = null; },
      });
      this.data = rows;
      this.alarm = alarm;
      return result;
    });
    this.pending = next.catch(() => {});
    return next;
  }
}

const now = 1_800_000_000;
const state = "sample-nonce";
const snapshot = {
  expires: now + 3600,
  repositories: { 10: ["studio/one", "studio/two"], 20: ["other/three"] },
  accounts: { 10: "studio", 20: "other" },
};

// This is the callback replay boundary, including a fresh object over durable storage.
test("exactly one concurrent callback consumes a state, and a restarted object refuses it", async () => {
  const storage = new Storage();
  const HubSessions = createHubSessions(({ store }) => ({
    handle: async () => Response.json(await store.consumeState(state, now + 600, now)),
  }));
  const first = new HubSessions({ storage }, {});
  const other = new HubSessions({ storage }, {});
  const request = new Request("https://hub.test/callback");
  const answers = await Promise.all([first.fetch(request), other.fetch(request)]);
  const consumed = await Promise.all(answers.map((response) => response.json()));
  assert.deepEqual(consumed.sort(), [false, true]);
  const restarted = new HubSessions({ storage }, {});
  assert.equal(await (await restarted.fetch(request)).json(), false);
  assert.equal(storage.data.size, 1);
  assert.ok(!JSON.stringify([...storage.data]).includes(state));
});

test("state and user access expire on read before an alarm has run", async () => {
  const storage = new Storage();
  const store = createHubStore(storage);
  assert.equal(await store.consumeState(state, now + 600, now), true);
  assert.equal(await store.consumeState(state, now + 600, now + 599), false);
  assert.equal(await store.consumeState(state, now + 600, now + 601), false);
  assert.equal(storage.data.size, 0);
  assert.equal(await store.consumeState(state, now + 1200, now + 601), true);
  await store.setAccess(1, snapshot, now);
  const restarted = createHubStore(storage);
  assert.deepEqual(await restarted.access(1, now + 3599), snapshot);
  assert.equal(await restarted.access(1, now + 3660), null);
});

test("removal and suspension reach every user immediately and addition does not grant access", async () => {
  const storage = new Storage();
  const store = createHubStore(storage);
  await store.installed(10, "studio", ["studio/one", "studio/two"]);
  await store.installed(20, "other", ["other/three"]);
  await Promise.all([store.setAccess(1, snapshot, now), store.setAccess(2, snapshot, now)]);
  await store.repositoriesAdded(10, "studio", ["studio/new"]);
  assert.deepEqual(await store.access(1, now), snapshot);
  await store.repositoriesRemoved(10, ["Studio/One"]);
  const restarted = createHubStore(storage);
  assert.deepEqual(storage.data.get("installation:10").repositories, ["studio/two", "studio/new"]);
  for (const uid of [1, 2]) assert.deepEqual((await restarted.access(uid, now)).repositories[10], ["studio/two"]);
  await store.suspended(20);
  assert.deepEqual(storage.data.get("installation:20"), { account: "other", repositories: [] });
  for (const uid of [1, 2]) assert.deepEqual((await restarted.access(uid, now)).accounts, { 10: "studio" });
  await store.uninstalled(10);
  assert.equal(storage.data.has("installation:10"), false);
  for (const uid of [1, 2]) assert.deepEqual((await restarted.access(uid, now)).repositories, {});
  await restarted.forgetUser(1);
  assert.equal(await store.access(1, now), null);
  assert.deepEqual((await store.access(2, now)).repositories, {});
});

test("stored records are projected and caller changes cannot mutate durable access", async () => {
  const storage = new Storage();
  const store = createHubStore(storage);
  const input = structuredClone(snapshot);
  input.unrecognized = "do not retain";
  input.accounts[30] = "unseen";
  await store.setAccess(1, input, now);
  input.repositories[10].push("studio/late");
  const result = await store.access(1, now);
  assert.deepEqual(result, snapshot);
  result.repositories[10].pop();
  assert.deepEqual(await store.access(1, now), snapshot);
  assert.ok(!JSON.stringify([...storage.data]).includes("do not retain"));
});

test("alarms purge unread expired rows without touching installations", async () => {
  const storage = new Storage();
  let time = now;
  const HubSessions = createHubSessions(() => ({ handle: () => new Response() }), { clock: () => time });
  const object = new HubSessions({ storage }, {});
  const store = createHubStore(storage);
  await store.setAccess(1, snapshot, now);
  await store.consumeState(state, now + 600, now);
  await store.installed(10, "studio", ["studio/one"]);
  assert.equal(storage.alarm, (now + 600) * 1000);
  time += 600;
  await object.alarm();
  assert.equal(storage.data.size, 2);
  assert.equal(storage.alarm, (now + 3600) * 1000);
  time = now + 3600;
  await object.alarm();
  assert.equal(storage.data.size, 1);
  assert.equal(storage.alarm, null);
});
