// The Run it edge function on a Workers-style runtime (#265, slice 3; docs/run-it.md, "The edge
// function"). Every request goes to one Durable Object named "run-it", so the quotas, the busy check
// and the circuit breaker are held in one place with strongly consistent storage, and service.js
// serializes the requests inside it.
//
// Bindings (Sean sets them; none is in this repository):
//   RUN_IT          the Durable Object namespace for the class RunIt
//   GITHUB_TOKEN    secret: a fine-grained token on Expectrail/Expectrail with "Actions: read and write"
//   VISITOR_SALT    secret: 32 random characters or more; visitors are counted by a hash of it and the address
//   RUN_IT_OPEN     "true" to start runs; anything else and every run is refused as switched off
//   BREAKER_EPOCH   change it to any new value to close an open circuit breaker
//   PER_VISITOR, DAILY_CAP, BREAKER, ALLOWED_ORIGINS, VISITOR_HEADER: optional, see service.js
import { createService } from "./service.js";

export class RunIt {
  constructor(state, env) {
    const storage = state.storage;
    this.service = createService({
      env,
      store: {
        get: (key) => storage.get(key),
        put: (key, value) => storage.put(key, value),
        delete: (key) => storage.delete(key),
      },
      log: (message) => console.log(`run-it: ${message}`),
    });
  }

  fetch(request) {
    return this.service.handle(request);
  }
}

export default {
  fetch(request, env) {
    const stub = env.RUN_IT.get(env.RUN_IT.idFromName("run-it"));
    return stub.fetch(request);
  },
};
