"""Detect whether live Muse Wonder / Muse Code can run in this environment.

Also loads a gitignored repo-root `.env` at CLI entry (never from readiness helpers),
so local Meta keys work without exporting them every shell. Process env always wins.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Mapping, TypedDict

from harness.run import REPO

# Keys we will adopt from a local `.env` (setdefault only).
DOTENV_KEYS = frozenset({
    "META_API_KEY",
    "MODEL_API_KEY",
    "META_API_BASE",
    "EXPECTRAIL_MODEL_API_BASE",
    "EXPECTRAIL_SPEC_MODEL",
    # Open weights (Muse Spark Open on a partner endpoint) for agents.feedback --sorter open
    "BASETEN_API_KEY",
    "EXPECTRAIL_OPEN_API_KEY",
    "EXPECTRAIL_OPEN_API_BASE",
    "EXPECTRAIL_OPEN_MODEL",
    # Open weights: Muse Glimmer as the vision backend (agents.glimmer_client)
    "EXPECTRAIL_VISION_BACKEND",
    "FIREWORKS_API_KEY",
    "EXPECTRAIL_GLIMMER_API_KEY",
    "EXPECTRAIL_GLIMMER_API_BASE",
    "EXPECTRAIL_GLIMMER_MODEL",
    "EXPECTRAIL_GLIMMER_COORDS",
    # Bring your own model, coding agent and vision backend (expectrail.providers, agents.byo_*)
    "EXPECTRAIL_LLM_PROVIDER",
    "EXPECTRAIL_LLM_MODEL",
    "EXPECTRAIL_LLM_API_BASE",
    "EXPECTRAIL_LLM_API_KEY",
    "EXPECTRAIL_SPEC_PROVIDER",
    "EXPECTRAIL_TRIAGE_PROVIDER",
    "EXPECTRAIL_TRIAGE_MODEL",
    "EXPECTRAIL_FIXER_PROVIDER",
    "EXPECTRAIL_FIXER_MODEL",
    "EXPECTRAIL_FIXER_AGENT",
    "EXPECTRAIL_FIXER_CMD",
    "EXPECTRAIL_FIXER_RO_BINDS",
    "EXPECTRAIL_VLM_PROVIDER",
    "EXPECTRAIL_VLM_MODEL",
    "EXPECTRAIL_VLM_API_BASE",
    "EXPECTRAIL_VLM_API_KEY",
    "EXPECTRAIL_VLM_COORDS",
    "EXPECTRAIL_LOCAL_VISION_URL",
    "EXPECTRAIL_KEYFRAMES_ONLY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENROUTER_API_KEY",
    "OLLAMA_HOST",
})

# Keys a BYO coding agent may receive inside its sandbox, by agent. Only its own provider's key:
# never MODEL_API_KEY, the vision key, or anything else the verifier holds.
BYO_AGENT_KEY_ENVS = {
    "claude-code": ("ANTHROPIC_API_KEY",),
    "codex": ("OPENAI_API_KEY",),
    "aider": ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"),
    "custom-cmd": ("EXPECTRAIL_FIXER_API_KEY",),
    "llm-patch": (),  # runs in Expectrail's own process; nothing enters a sandbox
    "muse-code": ("META_API_KEY",),
}
BYO_AGENT_BINARIES = {"claude-code": "claude", "codex": "codex", "aider": "aider", "muse-code": "muse"}

# Muse Code subprocess: model key + runtime/TLS/temp/proxy hygiene — not a sandbox.
MUSE_ENV_ALLOWLIST = frozenset({
    "META_API_KEY",
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "TMPDIR",
    "TMP",
    "TEMP",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_RUNTIME_DIR",
})

PROMPT_POLICY = "clean-v1"


class ModeResolution(TypedDict, total=False):
    mode: str
    offline_triage: bool
    use_muse: bool
    wonder_key_present: bool
    muse_ready: bool
    verification_default: str  # fixture | harness — informational; loop may override


def load_dotenv(path: Path | None = None) -> dict[str, str]:
    """Load KEY=VAL from a `.env` file into os.environ via setdefault.

    - Missing file: no-op.
    - Never overrides keys already present in the process environment (including empty
      string — CI/tests that clear or set META_API_KEY win).
    - Only adopts keys in DOTENV_KEYS.
    - Supports optional `export ` prefix, optional quotes, spaces around `=`.
    Returns the key→value pairs that were newly set (for tests).
    """
    env_path = path if path is not None else REPO / ".env"
    if not env_path.is_file():
        return {}
    adopted: dict[str, str] = {}
    text = env_path.read_text(encoding="utf-8-sig")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            raise SystemExit(f"malformed .env line (no '='): {raw!r} in {env_path}")
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key not in DOTENV_KEYS:
            continue
        if value == "":
            continue
        if key in os.environ:
            continue
        os.environ[key] = value
        adopted[key] = value
    return adopted


def muse_subprocess_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Allowlisted env for `muse exec` — leak hygiene, not OS isolation."""
    src = dict(base) if base is not None else dict(os.environ)
    out = {k: v for k, v in src.items() if k in MUSE_ENV_ALLOWLIST and v != ""}
    return out


def wonder_key() -> str | None:
    key = os.environ.get("MODEL_API_KEY") or os.environ.get("META_API_KEY")
    return key if key else None


def muse_code_ready() -> bool:
    return shutil.which("muse") is not None and bool(os.environ.get("META_API_KEY"))


def triage_ready() -> bool:
    """A live triage model is available: the legacy Wonder key, or a BYO provider for TRIAGE."""
    if wonder_key() and not _byo("TRIAGE"):
        return True
    if _byo("TRIAGE"):
        from expectrail.providers import provider_ready

        return provider_ready("TRIAGE")
    return False


def _byo(role: str) -> bool:
    from expectrail.providers import byo_requested

    return byo_requested(role)


def byo_fixer_agent() -> str | None:
    """The coding agent named by EXPECTRAIL_FIXER_AGENT, when it is not Muse Code.

    Only an explicit choice counts: an installed `claude` or `codex` never silently replaces Muse.
    """
    agent = os.environ.get("EXPECTRAIL_FIXER_AGENT", "").strip().lower()
    return agent if agent and agent not in ("muse-code", "auto") else None


def byo_fixer_ready(agent: str | None = None) -> bool:
    agent = agent or byo_fixer_agent()
    if not agent:
        return False
    if agent == "llm-patch":
        from expectrail.providers import provider_ready

        return provider_ready("FIXER")
    if agent == "custom-cmd":
        return bool(os.environ.get("EXPECTRAIL_FIXER_CMD", "").strip())
    binary = BYO_AGENT_BINARIES.get(agent)
    return bool(binary and shutil.which(binary))


def fixer_ready() -> bool:
    """A live fixer is available: the BYO agent named by EXPECTRAIL_FIXER_AGENT, else Muse Code."""
    return byo_fixer_ready() if byo_fixer_agent() else muse_code_ready()


def byo_agent_env(agent: str, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Allowlisted env for a BYO coding agent: runtime hygiene plus its own provider key only."""
    src = dict(base) if base is not None else dict(os.environ)
    names = (MUSE_ENV_ALLOWLIST - {"META_API_KEY"}) | set(BYO_AGENT_KEY_ENVS.get(agent, ()))
    return {k: v for k, v in src.items() if k in names and v != ""}


def resolve_mode(requested: str) -> ModeResolution:
    """Map auto|offline|live to concrete triage/fixer flags.

    auto: Wonder live if a key exists; Muse Code live if muse + META_API_KEY exist;
          otherwise fixtures. CI stays deterministic without secrets.
    live: requires Wonder key and Muse Code readiness; fails closed otherwise.
    """
    if requested not in ("auto", "offline", "live"):
        raise ValueError(f"unknown mode: {requested}")
    if requested == "offline":
        return {
            "mode": "offline",
            "offline_triage": True,
            "use_muse": False,
            "wonder_key_present": False,
            "muse_ready": False,
            "verification_default": "fixture",
        }
    if requested == "live":
        if not triage_ready():
            raise SystemExit(
                "live mode needs MODEL_API_KEY or META_API_KEY for Wonder triage "
                "(or a BYO triage provider: EXPECTRAIL_LLM_PROVIDER and its key)"
            ) from None
        if not fixer_ready():
            raise SystemExit(
                "live mode needs muse on PATH and META_API_KEY for Muse Code "
                "(or EXPECTRAIL_FIXER_AGENT set to an installed agent)"
            ) from None
        return {
            "mode": "live",
            "offline_triage": False,
            "use_muse": True,
            "wonder_key_present": True,
            "muse_ready": True,
            "verification_default": "fixture",
        }
    # auto
    return {
        "mode": "auto",
        "offline_triage": not triage_ready(),
        "use_muse": fixer_ready(),
        "wonder_key_present": triage_ready(),
        "muse_ready": fixer_ready(),
        "verification_default": "fixture",
    }


def seal_mode_flags(
    resolved: ModeResolution,
    *,
    force_offline_triage: bool,
    force_online_triage: bool,
    force_muse: bool,
) -> ModeResolution:
    """Apply CLI overrides only when they do not contradict the sealed mode.

    Raises SystemExit on contradictions so overnight policy cannot silently lie.
    """
    mode = resolved["mode"]
    offline_triage = resolved["offline_triage"]
    use_muse = resolved["use_muse"]

    if force_offline_triage and force_online_triage:
        raise SystemExit("conflicting flags: --offline-triage and --online-triage") from None

    if force_offline_triage:
        if mode == "live":
            raise SystemExit("--offline-triage conflicts with --mode live") from None
        offline_triage = True
    if force_online_triage:
        if mode == "offline":
            raise SystemExit("--online-triage conflicts with --mode offline") from None
        if not triage_ready():
            raise SystemExit("--online-triage needs MODEL_API_KEY or META_API_KEY "
                             "(or a BYO triage provider)") from None
        offline_triage = False
    if force_muse:
        if mode == "offline":
            raise SystemExit("--use-muse conflicts with --mode offline") from None
        if not fixer_ready():
            raise SystemExit("--use-muse needs muse on PATH and META_API_KEY "
                             "(or EXPECTRAIL_FIXER_AGENT set to an installed agent)") from None
        use_muse = True

    out: ModeResolution = {
        "mode": mode,
        "offline_triage": offline_triage,
        "use_muse": use_muse,
        "wonder_key_present": resolved.get("wonder_key_present", triage_ready()),
        "muse_ready": resolved.get("muse_ready", fixer_ready()),
        "verification_default": resolved.get("verification_default", "fixture"),
    }
    return out


def require_separate_sam_key() -> None:
    """With SAM on, refuse to run Muse Code (the fixer) unless SAM has its own key.

    The verifier reads MODEL_API_KEY; Muse Code receives META_API_KEY (MUSE_ENV_ALLOWLIST). If
    both hold the same key, the fixer holds the verifier's key, which breaks the promise that the
    fixer never sees verifier secrets. Called by entry points that run Muse; a no-op when the
    observations provider is not SAM.
    """
    from agents.observations import resolve_provider

    if resolve_provider() != "sam":
        return
    from agents.sam_observations import SamError, vision_backend

    muse_key = os.environ.get("META_API_KEY", "").strip()
    try:
        backend = vision_backend()
    except SamError as exc:
        raise SystemExit(str(exc)) from None
    if backend == "local-http":
        return  # a local detector holds no key
    if backend in ("byo-vlm", "byo-vlm-engine"):
        from expectrail.providers import provider_ready, resolve_provider

        if not provider_ready("VLM"):
            raise SystemExit(f"EXPECTRAIL_VISION_BACKEND={backend} needs a VLM provider and its key "
                             "(EXPECTRAIL_VLM_PROVIDER / EXPECTRAIL_VLM_API_KEY, or a provider key)")
        if muse_key and resolve_provider("VLM").api_key == muse_key:
            raise SystemExit("the vision model's key is the same as META_API_KEY, which Muse Code (the fixer) "
                             "receives; the verifier's vision key must be its own")
        return
    if backend in ("glimmer", "both", "glimmer-engine"):
        from agents.glimmer_client import KEY_ENVS, api_key

        glimmer = api_key()
        if not glimmer:
            raise SystemExit(f"EXPECTRAIL_VISION_BACKEND={backend} needs one of {', '.join(KEY_ENVS)}")
        if muse_key and glimmer == muse_key:
            raise SystemExit("the Glimmer key is the same as META_API_KEY, which Muse Code (the fixer) "
                             "receives; the verifier's vision key must be its own")
        if backend in ("glimmer", "glimmer-engine"):
            return
    sam_key = os.environ.get("MODEL_API_KEY", "").strip()
    if not sam_key:
        raise SystemExit("EXPECTRAIL_OBS_PROVIDER=sam needs MODEL_API_KEY (a Meta Model API key for SAM)")
    if muse_key and sam_key == muse_key:
        raise SystemExit("MODEL_API_KEY is the same key as META_API_KEY, which Muse Code (the fixer) "
                         "receives. Create a second key on dev.meta.ai for SAM and set it as "
                         "MODEL_API_KEY, so the fixer never holds the verifier's key.")


def require_separate_byo_keys(agent: str | None = None) -> None:
    """The BYO counterpart of require_separate_sam_key: the fixer never holds the verifier's key.

    Refuses when the key a BYO coding agent receives is also a key the verifier uses: SAM's
    (MODEL_API_KEY), Glimmer's, or a BYO vision model's (EXPECTRAIL_VISION_BACKEND=byo-vlm*). Same
    provider for both is fine; the same key is not. Create a second key for the verifier.
    """
    agent = agent or byo_fixer_agent()
    if not agent:
        return
    fixer_keys = {os.environ.get(n, "").strip() for n in BYO_AGENT_KEY_ENVS.get(agent, ())} - {""}
    if agent == "llm-patch":
        from expectrail.providers import provider_ready, resolve_provider

        if provider_ready("FIXER"):
            fixer_keys = {resolve_provider("FIXER").api_key} - {"local-no-key"}
    if not fixer_keys:
        return
    verifier: dict[str, str] = {}
    for name in ("MODEL_API_KEY", "FIREWORKS_API_KEY", "EXPECTRAIL_GLIMMER_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            verifier[name] = value
    backend = os.environ.get("EXPECTRAIL_VISION_BACKEND", "").strip().lower()
    if backend.startswith("byo-vlm"):
        from expectrail.providers import provider_ready, resolve_provider

        if provider_ready("VLM"):
            vlm = resolve_provider("VLM")
            if vlm.api_key != "local-no-key":
                verifier[f"the {vlm.provider} key the vision model (EXPECTRAIL_VLM_*) uses"] = vlm.api_key
    for name, value in verifier.items():
        if value in fixer_keys:
            raise SystemExit(f"{name} is the same key the {agent} fixer receives; the verifier's key must be "
                             "its own (set EXPECTRAIL_VLM_API_KEY or MODEL_API_KEY to a second key)")
