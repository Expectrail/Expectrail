"""The Muse key gateway: Muse Code runs with a placeholder key, and never holds the real one.

Anything that steers Muse Code (a prompt injection in playtest feedback, a poisoned file in the
game) can make it run commands, so a key in its environment can be read and sent anywhere
(OBAAF-GHA-005). With the gateway on, ``muse exec`` gets a placeholder of the key's length and an
HTTPS proxy: mitmproxy (``mitmdump``) running ``agents/muse_gateway_addon.py``, which holds the real
key, swaps it in for Meta's API only (``*.meta.ai``), refuses every other host, and logs host, path,
status and header names, never values. Muse trusts the proxy's certificate authority and nothing
else.

Inside bubblewrap the sandbox also loses its network (``--unshare-net``): the only way out is
``agents/gateway_bridge.py``, which forwards 127.0.0.1:8899 in the sandbox to this process's Unix
socket and on to the proxy. So Muse cannot ignore the proxy and go elsewhere. On the host (the
screenshot judge's unsandboxed path, the live trust probe) the proxy and the placeholder apply, but
nothing stops a process from opening its own connections.

Measured Oct 30 (runs 41073919731 and 41074472926, agents/muse_gateway.py): Muse Code 1.4.14
answers through the proxy on the host and inside bubblewrap, every request going to api.meta.ai
with the key swapped into Authorization; with the placeholder alone and no proxy it is rejected.

``EXPECTRAIL_MUSE_GATEWAY=on`` turns it on (CI's live jobs set it); on and unavailable (no
mitmdump, no key) is an error, never a quiet fallback to giving Muse the key. ``EXPECTRAIL_MITMDUMP``
names the mitmdump binary (default: on PATH). The proxy runs in the same CI job as the fixer, so
OBAAF's static check still sees the key in that job; a gateway hosted elsewhere would clear it.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import string
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from harness.run import REPO

GATEWAY_ENV = "EXPECTRAIL_MUSE_GATEWAY"
MITMDUMP_ENV = "EXPECTRAIL_MITMDUMP"
HOSTS_ENV = "EXPECTRAIL_MUSE_GATEWAY_HOSTS"
DEFAULT_HOSTS = ".meta.ai"
# The same gateway for a bring-your-own coding agent, under its own switch so turning one on never
# changes the other. The allowlist is derived from the provider whose key the agent received
# (expectrail/providers.py), and BYO_HOSTS_ENV overrides it when a provider is served elsewhere.
BYO_GATEWAY_ENV = "EXPECTRAIL_BYO_GATEWAY"
BYO_HOSTS_ENV = "EXPECTRAIL_BYO_GATEWAY_HOSTS"
ADDON = REPO / "agents" / "muse_gateway_addon.py"
BRIDGE = REPO / "agents" / "gateway_bridge.py"
SANDBOX_DIR = "/gateway"          # where the gateway directory is bound inside bubblewrap
SANDBOX_PORT = 8899               # the bridge's port inside the sandbox's own network namespace
CA_VARS = ("SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
PROXY_VARS = ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy")
NO_PROXY_VARS = ("NO_PROXY", "no_proxy")


class GatewayError(SystemExit):
    """The gateway is on but cannot run. Never answered by handing Muse the real key instead."""


def _switch_on(value: str) -> bool:
    return value.strip().lower() in ("on", "1", "true", "yes")


def enabled(environ: Mapping[str, str] | None = None) -> bool:
    return _switch_on((environ if environ is not None else os.environ).get(GATEWAY_ENV, ""))


def byo_enabled(environ: Mapping[str, str] | None = None) -> bool:
    return _switch_on((environ if environ is not None else os.environ).get(BYO_GATEWAY_ENV, ""))


def provider_host(key_env: str) -> str | None:
    """The host the provider that owns ``key_env`` is reached at, or None when that is not one host.

    A vendor-named key belongs to exactly one provider, so the allowlist comes from the registry
    rather than a second list here. The shared overrides (EXPECTRAIL_LLM_API_KEY and the rest) belong
    to every provider at once, so they name no host and the caller has to be told instead of guessed
    at — an allowlist guessed wrong is either a broken run or a key sent somewhere it should not go.
    """
    from urllib.parse import urlparse

    from expectrail.providers import PROVIDER_DEFAULTS

    owners = {name for name, d in PROVIDER_DEFAULTS.items() if key_env in d["key_envs"]}
    if len(owners) != 1:
        return None
    host = urlparse(PROVIDER_DEFAULTS[owners.pop()]["api_base"]).hostname
    return host or None


def agent_key_env(agent: str, environ: Mapping[str, str] | None = None) -> str:
    """The one provider key env a BYO agent received, for the gateway to hold in its place.

    The gateway swaps a single placeholder for a single real key, so an agent carrying two provider
    keys (aider can) cannot be put behind it as it stands, and saying so is better than gatewaying
    one key and handing over the other.
    """
    from agents.keys import BYO_AGENT_KEY_ENVS

    env = environ if environ is not None else os.environ
    present = [name for name in BYO_AGENT_KEY_ENVS.get(agent, ()) if (env.get(name) or "").strip()]
    if not present:
        raise GatewayError(f"{BYO_GATEWAY_ENV}=on but {agent} has no provider key to hold: set one of "
                           f"{', '.join(BYO_AGENT_KEY_ENVS.get(agent, ())) or '(none known)'}")
    if len(present) > 1:
        raise GatewayError(f"{BYO_GATEWAY_ENV}=on but {agent} holds {len(present)} provider keys "
                           f"({', '.join(present)}); the gateway holds one key, so run it with one")
    return present[0]


def find_mitmdump(environ: Mapping[str, str] | None = None) -> str | None:
    env = environ if environ is not None else os.environ
    return env.get(MITMDUMP_ENV) or shutil.which("mitmdump")


def placeholder_for(real: str) -> str:
    """A fake key of the same length, keeping a short prefix (up to the first - or _ in 12 characters)
    so a client that checks a key's shape before sending it is not stopped by the shape alone."""
    cut = next((i + 1 for i, ch in enumerate(real[:12]) if ch in "-_"), 0)
    alphabet = string.ascii_letters + string.digits
    while True:
        fake = real[:cut] + "".join(secrets.choice(alphabet) for _ in range(max(len(real) - cut, 24)))
        if fake != real:
            return fake


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_mitmdump(mitmdump: str, conf: Path, log: Path, real: str, placeholder: str,
                   hosts: str) -> tuple[subprocess.Popen, str, Path]:
    """mitmdump with the gateway addon on a free local port: (process, proxy URL, CA certificate)."""
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if k not in ("META_API_KEY", "MODEL_API_KEY")}
    env.update(MUSE_GATEWAY_KEY=real, MUSE_GATEWAY_PLACEHOLDER=placeholder, MUSE_GATEWAY_LOG=str(log),
               MUSE_GATEWAY_HOSTS=hosts)
    with open(conf / "mitmdump.err", "w") as err:  # the child keeps its own copy of the descriptor
        proc = subprocess.Popen([mitmdump, "-q", "-s", str(ADDON), "--listen-host", "127.0.0.1",
                                 "--listen-port", str(port), "--set", f"confdir={conf}"],
                                env=env, stdout=subprocess.DEVNULL, stderr=err)
    ca = conf / "mitmproxy-ca-cert.pem"
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            raise GatewayError(f"the Muse key gateway's mitmdump exited ({proc.returncode}); see {conf / 'mitmdump.err'}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                if ca.is_file():
                    return proc, f"http://127.0.0.1:{port}", ca
        except OSError:
            pass
        time.sleep(0.2)
    proc.terminate()
    raise GatewayError("the Muse key gateway's mitmdump did not start listening within 60 s")


def read_log(log: Path, since: float = 0.0) -> list[dict]:
    if not log.is_file():
        return []
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if r.get("t", since) >= since]


class UnixBridge:
    """Host side of the sandbox's way out: a Unix socket whose connections go to the proxy's port."""

    def __init__(self, path: Path, port: int):
        self.path, self.port = path, port
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(path))
        self.listener.listen(64)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        from agents.gateway_bridge import _pump

        while True:
            try:
                client, _ = self.listener.accept()
            except OSError:
                return
            try:
                upstream = socket.create_connection(("127.0.0.1", self.port), timeout=10)
                upstream.settimeout(None)
            except OSError:
                client.close()
                continue
            for a, b in ((client, upstream), (upstream, client)):
                threading.Thread(target=_pump, args=(a, b), daemon=True).start()

    def close(self) -> None:
        try:
            self.listener.close()
        finally:
            self.path.unlink(missing_ok=True)


@dataclass
class Gateway:
    proxy: str
    ca: Path
    placeholder: str
    real: str = field(repr=False)
    dir: Path = field(default_factory=Path)
    log: Path = field(default_factory=Path)
    started: float = field(default_factory=time.time)

    @property
    def socket(self) -> Path:
        return self.dir / "gw.sock"

    def agent_env(self, base: Mapping[str, str], key_envs: tuple[str, ...], *, in_sandbox: bool) -> dict:
        """An agent's environment: the placeholder in place of each key, the proxy and its
        certificate, and nothing left that would bypass them."""
        env = {k: v for k, v in base.items() if k not in PROXY_VARS + NO_PROXY_VARS + CA_VARS}
        for name in key_envs:
            env[name] = self.placeholder
        proxy = f"http://127.0.0.1:{SANDBOX_PORT}" if in_sandbox else self.proxy
        ca = f"{SANDBOX_DIR}/ca.pem" if in_sandbox else str(self.ca)
        env.update({v: proxy for v in PROXY_VARS})
        env.update({v: ca for v in CA_VARS})
        if self.real and self.real in json.dumps(env):
            raise GatewayError("the real key reached the agent's environment; stopping")
        return env

    def muse_env(self, base: Mapping[str, str], *, in_sandbox: bool) -> dict:
        """Muse Code's environment: the placeholder, the proxy and its certificate, nothing to bypass them."""
        return self.agent_env(base, ("META_API_KEY",), in_sandbox=in_sandbox)

    def bridge_argv(self, argv: list[str]) -> list[str]:
        """``argv`` wrapped so it runs behind the in-sandbox bridge."""
        # The system Python: /usr is bound into the sandbox; a toolcache Python on PATH is not.
        return ["/usr/bin/python3", f"{SANDBOX_DIR}/bridge.py", "--port", str(SANDBOX_PORT), "--socket",
                f"{SANDBOX_DIR}/gw.sock", "--", *argv]

    def summary(self) -> dict:
        flows = read_log(self.log, self.started)
        return {
            "mode": "on",
            "requests": len(flows),
            "hosts": sorted({f["host"] for f in flows if f.get("host")}),
            "blockedHosts": sorted({f["host"] for f in flows if f.get("blocked")}),
            "swappedHeaders": sorted({n for f in flows for n in f.get("swapped") or []}),
            "errors": sorted({f["error"] for f in flows if f.get("error")})[:3],
        }


@contextmanager
def muse_gateway(environ: Mapping[str, str] | None = None) -> Iterator[Gateway | None]:
    """The gateway for one Muse Code run, or None when it is off. Stopped (proxy and bridge) on exit."""
    env = environ if environ is not None else os.environ
    if not enabled(env):
        yield None
        return
    real = env.get("META_API_KEY", "")
    if not real:
        raise GatewayError(f"{GATEWAY_ENV}=on needs META_API_KEY: the gateway holds it for Muse Code")
    with _running(real, env.get(HOSTS_ENV, DEFAULT_HOSTS), env) as gw:
        yield gw


@contextmanager
def byo_gateway(agent: str, environ: Mapping[str, str] | None = None) -> Iterator[Gateway | None]:
    """The same gateway for one BYO coding agent run, or None when it is off.

    The agent gets a placeholder of its provider key's length and this proxy, which holds the real
    key and swaps it in for the provider's host only. Off by default: with it off the agent runs with
    its own key and the host's network, which is what the README describes. On and unavailable is an
    error, never a quiet fallback to handing the agent the real key.
    """
    env = environ if environ is not None else os.environ
    if not byo_enabled(env):
        yield None
        return
    key_env = agent_key_env(agent, env)
    hosts = (env.get(BYO_HOSTS_ENV) or "").strip() or provider_host(key_env)
    if not hosts:
        raise GatewayError(
            f"{BYO_GATEWAY_ENV}=on but the host for {key_env} is not one provider's: set "
            f"{BYO_HOSTS_ENV} to the host the agent may reach. The gateway refuses every host off "
            "its allowlist, so it is never widened by guessing.")
    with _running(env[key_env], hosts, env) as gw:
        yield gw


@contextmanager
def _running(real: str, hosts: str, env: Mapping[str, str]) -> Iterator[Gateway]:
    """A started proxy and bridge holding ``real`` for ``hosts``; both stopped on exit."""
    mitmdump = find_mitmdump(env)
    if not mitmdump or not Path(mitmdump).exists() and not shutil.which(mitmdump):
        raise GatewayError(f"the key gateway is on but mitmdump was not found "
                           f"(install mitmproxy, or set {MITMDUMP_ENV})")
    workdir = Path(tempfile.mkdtemp(prefix="key-gateway-"))
    conf = workdir / "mitm"
    conf.mkdir()
    sandbox_dir = workdir / "sandbox"  # bound read-only at /gateway: the bridge, the CA, the socket
    sandbox_dir.mkdir()
    log = workdir / "gateway-log.jsonl"
    placeholder = placeholder_for(real)
    proc, proxy, ca = start_mitmdump(mitmdump, conf, log, real, placeholder, hosts)
    bridge = None
    try:
        shutil.copyfile(ca, sandbox_dir / "ca.pem")
        shutil.copyfile(BRIDGE, sandbox_dir / "bridge.py")
        gw = Gateway(proxy=proxy, ca=ca, placeholder=placeholder, real=real, dir=sandbox_dir, log=log)
        bridge = UnixBridge(gw.socket, int(proxy.rsplit(":", 1)[1]))
        yield gw
    finally:
        if bridge is not None:
            bridge.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(workdir, ignore_errors=True)


def evidence(root: Path) -> dict:
    """Every Muse run recorded under ``root`` (sandbox.json, judge.json): did it go through the gateway?"""
    runs = []
    for path in sorted(Path(root).rglob("*.json")):
        if path.name not in ("sandbox.json", "judge.json"):
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        g = doc.get("gateway") or (doc.get("sandbox") or {}).get("gateway") if isinstance(doc, dict) else None
        if isinstance(g, dict):
            runs.append(g)
        elif path.name == "sandbox.json":
            runs.append({"mode": "unrecorded"})  # a Muse run that left no gateway record still counts as a run
    on = [g for g in runs if g.get("mode") == "on"]
    stopped = 0  # runs the pre-run SAM check stopped before the fixer (agents/sam_health.py)
    for path in Path(root).rglob("result.json"):
        try:
            stopped += bool((json.loads(path.read_text(encoding="utf-8")) or {}).get("preflight"))
        except (OSError, ValueError, AttributeError):
            continue
    return {
        "stoppedBeforeFixer": stopped,
        "museRuns": len(runs),
        "throughGateway": len(on),
        "requests": sum(g.get("requests", 0) for g in on),
        "hosts": sorted({h for g in on for h in g.get("hosts", [])}),
        "blockedHosts": sorted({h for g in on for h in g.get("blockedHosts", [])}),
        "swappedHeaders": sorted({h for g in on for h in g.get("swappedHeaders", [])}),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--evidence", type=Path, required=True, help="a run directory: summarize its Muse runs")
    args = p.parse_args(argv)
    e = evidence(args.evidence)
    if not e["museRuns"] and e["stoppedBeforeFixer"]:
        # Nothing to check, and the reason is known: never a warning that evidence is missing.
        print(f"::notice title=Muse key gateway::no Muse run: the pre-run SAM check stopped "
              f"{e['stoppedBeforeFixer']} run(s) before the fixer, so nothing needed the gateway")
        return 0
    level = "notice" if e["museRuns"] and e["throughGateway"] == e["museRuns"] else "warning"
    print(f"::{level} title=Muse key gateway::{e['throughGateway']} of {e['museRuns']} Muse runs through the gateway; "
          f"{e['requests']} requests to {', '.join(e['hosts']) or 'nothing'}; key swapped in "
          f"{', '.join(e['swappedHeaders']) or 'no header'}; blocked {', '.join(e['blockedHosts']) or 'nothing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
