"""The hub's configuration: every credential comes from the environment, none from a file.

With any sign-in setting absent or unusable, the service still starts, serves its pages and says that
GitHub sign-in is unconfigured, naming the missing settings (names only, never values).
"""
from dataclasses import dataclass, field
from urllib.parse import urlsplit

# Setting -> environment variable. Sean creates every value (docs/hub-design.md, "Before live sign-in").
ENV = {
    'client_id': 'EXPECTRAIL_HUB_CLIENT_ID',            # the GitHub App's client id
    'client_secret': 'EXPECTRAIL_HUB_CLIENT_SECRET',    # the GitHub App's client secret
    'app_slug': 'EXPECTRAIL_HUB_APP_SLUG',              # github.com/apps/<slug>, for the install link
    'cookie_key': 'EXPECTRAIL_HUB_COOKIE_KEY',          # signs session and sign-in state cookies
    'webhook_secret': 'EXPECTRAIL_HUB_WEBHOOK_SECRET',  # authenticates installation deliveries
    'origin': 'EXPECTRAIL_HUB_ORIGIN',                  # e.g. https://hub.expectrail.tech
}
# What sign-in needs. The webhook secret is checked on its own route; the App's private key is
# #713's (installation reads) and is not read here.
SIGN_IN = ('client_id', 'client_secret', 'app_slug', 'cookie_key', 'origin')
MIN_COOKIE_KEY_BYTES = 32
LOCAL_HOSTS = {'127.0.0.1', 'localhost', '::1'}


@dataclass(frozen=True)
class Config:
    values: dict = field(default_factory=dict)
    problems: tuple = ()          # plain reasons a present setting cannot be used

    @classmethod
    def from_env(cls, env):
        values, problems = {}, []
        for name, var in ENV.items():
            value = (env.get(var) or '').strip()
            if value:
                values[name] = value
        origin = values.get('origin')
        if origin is not None:
            reason = origin_problem(origin)
            if reason:
                problems.append(f'{ENV["origin"]}: {reason}')
                del values['origin']
            else:
                values['origin'] = origin.rstrip('/')
        key = values.get('cookie_key')
        if key is not None and len(key.encode()) < MIN_COOKIE_KEY_BYTES:
            problems.append(f'{ENV["cookie_key"]}: shorter than {MIN_COOKIE_KEY_BYTES} bytes')
            del values['cookie_key']
        slug = values.get('app_slug')
        if slug is not None and not all(c.isalnum() or c == '-' for c in slug):
            problems.append(f'{ENV["app_slug"]}: not a GitHub App slug')
            del values['app_slug']
        return cls(values, tuple(problems))

    def missing(self, names=SIGN_IN):
        return [ENV[n] for n in names if n not in self.values]

    @property
    def sign_in_ready(self):
        return not self.missing()

    @property
    def secure_cookies(self):
        origin = self.values.get('origin', '')
        return origin.startswith('https://')

    def __getitem__(self, name):
        return self.values[name]

    def __repr__(self):  # never print a value
        return f'Config(present={sorted(self.values)}, problems={list(self.problems)})'


def origin_problem(origin):
    try:
        parts = urlsplit(origin)
    except ValueError:
        return 'not a URL'
    if parts.path not in ('', '/') or parts.query or parts.fragment or parts.username or parts.password:
        return 'must be a bare origin, like https://hub.example'
    if not parts.hostname:
        return 'has no host'
    if parts.scheme == 'https':
        return None
    if parts.scheme == 'http' and parts.hostname in LOCAL_HOSTS:
        return None
    return 'must be https (http only for this machine)'
