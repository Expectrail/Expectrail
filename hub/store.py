"""What the hub keeps, and nothing more (docs/hub-design.md, "Data and deletion").

- installations: installation id -> account login and selected repository names, kept while the App
  is installed and updated from authenticated installation deliveries;
- access: GitHub user id -> the installations and repositories GitHub said that user can see at their
  last sign-in, kept for the session's hour only and dropped at sign-out;
- consumed sign-in states, kept until they would have expired anyway.

Nothing from inside a game and no credential is ever stored. This store is in memory: a restart
forgets everything, which signs everyone out. A durable store is a later slice.
"""
from dataclasses import dataclass, field
import threading


@dataclass
class Access:
    expires: int
    repositories: dict = field(default_factory=dict)   # installation id -> set of "owner/name"
    accounts: dict = field(default_factory=dict)       # installation id -> account login


class MemoryStore:
    def __init__(self):
        self._lock = threading.Lock()
        self.installations = {}   # id -> {'account': str, 'repositories': set}
        self._access = {}         # uid -> Access
        self._states = {}         # state -> expiry

    # sign-in state
    def consume_state(self, state, expires, now):
        """True the first time a state is used; False on any reuse."""
        with self._lock:
            self._states = {s: e for s, e in self._states.items() if e > now}
            if state in self._states:
                return False
            self._states[state] = expires
            return True

    # per-user access, refreshed at every sign-in
    def set_access(self, uid, access):
        with self._lock:
            self._access[uid] = access

    def access(self, uid, now):
        with self._lock:
            found = self._access.get(uid)
            if found is None or found.expires <= now:
                self._access.pop(uid, None)
                return None
            return Access(found.expires, {i: set(r) for i, r in found.repositories.items()},
                          dict(found.accounts))

    def forget_user(self, uid):
        with self._lock:
            self._access.pop(uid, None)

    # installations, from authenticated deliveries
    def installed(self, installation_id, account, repositories):
        with self._lock:
            self.installations[installation_id] = {'account': account, 'repositories': set(repositories)}

    def uninstalled(self, installation_id):
        """The App was removed: drop the installation and every user's view of it at once."""
        with self._lock:
            self.installations.pop(installation_id, None)
            for access in self._access.values():
                access.repositories.pop(installation_id, None)
                access.accounts.pop(installation_id, None)

    def repositories_added(self, installation_id, account, names):
        with self._lock:
            entry = self.installations.setdefault(installation_id, {'account': account, 'repositories': set()})
            entry['repositories'].update(names)

    def repositories_removed(self, installation_id, names):
        with self._lock:
            entry = self.installations.get(installation_id)
            if entry:
                entry['repositories'].difference_update(names)
            for access in self._access.values():
                if installation_id in access.repositories:
                    access.repositories[installation_id].difference_update(names)
