// The SQLite-backed class factory is supplied by the independent store change (#786).
import { createHubSessions } from './hub-store.js';
import { createService } from './service.js';

export const HubSessions = createHubSessions(createService);

export default {
  fetch(request, env) {
    return env.HUB.get(env.HUB.idFromName('hub')).fetch(request);
  },
};
