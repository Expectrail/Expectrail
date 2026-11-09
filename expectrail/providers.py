"""Vendor-agnostic LLM & Vision provider router for Expectrail (pure Python stdlib).

Decouples Expectrail's spec drafting (`expectrail.spec_writer`), failure triage
(`agents.triage`), direct patch generation (`agents.byo_fixer`), and VLM frame
fallback (`agents.glimmer_client` / `agents.byo_vision`) from hard-coded Meta API
endpoints while preserving 100% backward compatibility with legacy Meta env vars.

Supported providers out of the box (zero third-party SDK dependencies):
- `openai`: OpenAI Chat Completions (`https://api.openai.com/v1`)
- `anthropic`: Anthropic Messages API (`https://api.anthropic.com/v1/messages`)
- `gemini`: Google Gemini OpenAI-compatible endpoint (`https://generativelanguage.googleapis.com/v1beta/openai`)
- `openrouter`: OpenRouter unified gateway (`https://openrouter.ai/api/v1`)
- `ollama`: Local Ollama server (`http://localhost:11434/v1`, no API key required)
- `vllm`: Self-hosted vLLM / SGLang server (`http://localhost:8000/v1`)
- `baseten`: Baseten inference (`https://inference.baseten.co/v1`)
- `fireworks`: Fireworks AI inference (`https://api.fireworks.ai/inference/v1`)
- `meta`: Legacy Meta Model API (`https://api.meta.ai/v1`)
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

PROVIDER_DEFAULTS: dict[str, dict[str, Any]] = {
    "openai": {
        "api_base": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "key_envs": ("EXPECTRAIL_LLM_API_KEY", "OPENAI_API_KEY"),
        "requires_key": True,
        "protocol": "openai",
    },
    "anthropic": {
        "api_base": "https://api.anthropic.com/v1",
        "default_model": "claude-sonnet-5-5",
        "key_envs": ("EXPECTRAIL_LLM_API_KEY", "ANTHROPIC_API_KEY"),
        "requires_key": True,
        "protocol": "anthropic",
    },
    "gemini": {
        "api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-2.5-pro",
        "key_envs": ("EXPECTRAIL_LLM_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "requires_key": True,
        "protocol": "openai",
    },
    "openrouter": {
        "api_base": "https://openrouter.ai/api/v1",
        "default_model": "anthropic/claude-3.7-sonnet",
        "key_envs": ("EXPECTRAIL_LLM_API_KEY", "OPENROUTER_API_KEY"),
        "requires_key": True,
        "protocol": "openai",
    },
    "ollama": {
        "api_base": "http://localhost:11434/v1",
        "default_model": "qwen2.5-coder:32b",
        "key_envs": ("EXPECTRAIL_LLM_API_KEY", "OLLAMA_API_KEY"),
        "requires_key": False,
        "protocol": "openai",
    },
    "vllm": {
        "api_base": "http://localhost:8000/v1",
        "default_model": "local-model",
        "key_envs": ("EXPECTRAIL_LLM_API_KEY", "VLLM_API_KEY"),
        "requires_key": False,
        "protocol": "openai",
    },
    "baseten": {
        "api_base": "https://inference.baseten.co/v1",
        "default_model": "meta-models/muse-spark-open",
        "key_envs": ("EXPECTRAIL_OPEN_API_KEY", "BASETEN_API_KEY", "EXPECTRAIL_LLM_API_KEY"),
        "requires_key": True,
        "protocol": "openai",
    },
    "fireworks": {
        "api_base": "https://api.fireworks.ai/inference/v1",
        "default_model": "accounts/fireworks/models/muse-glimmer-30b",
        "key_envs": ("EXPECTRAIL_GLIMMER_API_KEY", "FIREWORKS_API_KEY", "EXPECTRAIL_LLM_API_KEY"),
        "requires_key": True,
        "protocol": "openai",
    },
    "meta": {
        "api_base": "https://api.meta.ai/v1",
        "default_model": "muse-spark-1.3",
        "key_envs": ("MODEL_API_KEY", "META_API_KEY", "EXPECTRAIL_LLM_API_KEY"),
        "requires_key": True,
        "protocol": "openai",
    },
}


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    protocol: str
    api_base: str
    model: str
    api_key: str
    timeout: float = 90.0


def _first_env(*names: str) -> str:
    for name in names:
        if not name:
            continue
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def detect_default_provider() -> str:
    """Auto-detect provider from environment when EXPECTRAIL_LLM_PROVIDER is unset.

    A legacy Meta key wins over any other provider's key, so a setup that worked before this module
    existed keeps calling the same model: having ANTHROPIC_API_KEY in the shell (say, for Claude
    Code) never silently reroutes Expectrail. Set EXPECTRAIL_LLM_PROVIDER to choose explicitly.
    """
    explicit = _first_env("EXPECTRAIL_LLM_PROVIDER").lower()
    if explicit:
        return explicit
    if _first_env("MODEL_API_KEY", "META_API_KEY"):
        return "meta"
    if _first_env("ANTHROPIC_API_KEY"):
        return "anthropic"
    if _first_env("OPENAI_API_KEY"):
        return "openai"
    if _first_env("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        return "gemini"
    if _first_env("OPENROUTER_API_KEY"):
        return "openrouter"
    if _first_env("OLLAMA_HOST", "EXPECTRAIL_OLLAMA_MODEL"):
        return "ollama"
    if _first_env("FIREWORKS_API_KEY", "EXPECTRAIL_GLIMMER_API_KEY"):
        return "fireworks"
    if _first_env("BASETEN_API_KEY", "EXPECTRAIL_OPEN_API_KEY"):
        return "baseten"
    return "meta"


def resolve_provider(
    role: str = "LLM",
    *,
    provider: str | None = None,
    model: str | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
    legacy_model_env: str = "",
    legacy_base_env: str = "",
    legacy_key_envs: tuple[str, ...] = (),
    legacy_default_model: str | None = None,
) -> ProviderConfig:
    """Resolve provider, model, base URL, and API key for a specific pipeline role.

    Role can be `"SPEC"`, `"TRIAGE"`, `"VLM"`, `"FIXER"`, or `"LLM"`.
    Role-specific variables (`EXPECTRAIL_<ROLE>_PROVIDER`, `EXPECTRAIL_<ROLE>_MODEL`,
    `EXPECTRAIL_<ROLE>_API_BASE`, `EXPECTRAIL_<ROLE>_API_KEY`) take precedence over
    global `EXPECTRAIL_LLM_*` variables, which in turn fall back to legacy Meta vars.
    """
    role_upper = role.upper()
    prov = (
        provider
        or _first_env(f"EXPECTRAIL_{role_upper}_PROVIDER", "EXPECTRAIL_LLM_PROVIDER")
        or detect_default_provider()
    ).lower()

    if prov not in PROVIDER_DEFAULTS:
        raise RuntimeError(f"unknown provider {prov!r} (want {'|'.join(PROVIDER_DEFAULTS)})")
    defaults = PROVIDER_DEFAULTS[prov]
    protocol = defaults["protocol"]

    resolved_base = (
        api_base
        or _first_env(
            f"EXPECTRAIL_{role_upper}_API_BASE",
            "EXPECTRAIL_LLM_API_BASE",
            legacy_base_env if prov in ("meta", "baseten", "fireworks") else "",
        )
        or defaults["api_base"]
    ).rstrip("/")

    resolved_model = (
        model
        or _first_env(
            f"EXPECTRAIL_{role_upper}_MODEL",
            "EXPECTRAIL_LLM_MODEL",
            legacy_model_env if prov in ("meta", "baseten", "fireworks") else "",
        )
        or (legacy_default_model if prov == "meta" and legacy_default_model else defaults["default_model"])
    )

    key_candidates = (
        f"EXPECTRAIL_{role_upper}_API_KEY",
        *defaults["key_envs"],
        *legacy_key_envs,
    )
    resolved_key = api_key if api_key is not None else _first_env(*key_candidates)
    if defaults["requires_key"] and not resolved_key:
        tried = ", ".join(dict.fromkeys(k for k in key_candidates if k))
        raise RuntimeError(
            f"Missing API key for provider '{prov}' (role={role_upper}). "
            f"Set one of: {tried}"
        )

    return ProviderConfig(
        provider=prov,
        protocol=protocol,
        api_base=resolved_base,
        model=resolved_model,
        api_key=resolved_key or "local-no-key",
    )


def _convert_openai_messages_to_anthropic(
    messages: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Translate OpenAI-style messages (including data:image/png;base64 blocks) to Anthropic format."""
    system_parts: list[str] = []
    anth_messages: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            if isinstance(content, str):
                system_parts.append(content)
            continue

        anth_role = "assistant" if role == "assistant" else "user"
        if isinstance(content, str):
            anth_messages.append({"role": anth_role, "content": content})
            continue

        blocks: list[dict[str, Any]] = []
        for part in content:
            ptype = part.get("type")
            if ptype == "text":
                blocks.append({"type": "text", "text": part.get("text", "")})
            elif ptype == "image_url":
                url = part.get("image_url", {}).get("url", "")
                if url.startswith("data:"):
                    header, b64_data = url.split(",", 1)
                    media_type = header.split(";")[0].replace("data:", "") or "image/png"
                    blocks.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64_data,
                            },
                        }
                    )
        anth_messages.append({"role": anth_role, "content": blocks})

    system_str = "\n\n".join(system_parts) if system_parts else None
    return system_str, anth_messages


def build_http_payload(
    config: ProviderConfig,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int = 4096,
    temperature: float | None = 0.0,
    json_schema: dict[str, Any] | None = None,
    schema_name: str = "expectrail_response",
    strict: bool = True,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Construct (url, headers, payload_dict) for either OpenAI-compatible or Anthropic protocol."""
    if config.protocol == "anthropic":
        url = f"{config.api_base}/messages"
        headers = {
            "x-api-key": config.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        system_str, anth_msgs = _convert_openai_messages_to_anthropic(messages)
        if json_schema is not None:
            schema_instruction = (
                "\n\nYou MUST respond with valid JSON only (no markdown fences) "
                f"conforming to this JSON Schema:\n{json.dumps(json_schema)}"
            )
            system_str = (system_str or "") + schema_instruction
        payload: dict[str, Any] = {
            "model": config.model,
            "max_tokens": max_tokens,
            "messages": anth_msgs,
        }
        if system_str:
            payload["system"] = system_str
        if temperature is not None:
            payload["temperature"] = temperature
        return url, headers, payload

    # Default: OpenAI-compatible protocol (OpenAI, Gemini, OpenRouter, Ollama, vLLM, Meta, Fireworks, Baseten)
    url = f"{config.api_base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if json_schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": strict,
                "schema": json_schema,
            },
        }
    return url, headers, payload


def extract_message_text(config: ProviderConfig, raw_response: dict[str, Any]) -> str:
    """Extract assistant text content from OpenAI-compatible or Anthropic response JSON."""
    if config.protocol == "anthropic":
        content_blocks = raw_response.get("content", [])
        texts = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
        return "\n".join(texts).strip()
    choices = raw_response.get("choices", [])
    if not choices:
        raise RuntimeError(f"Empty choices in response from provider '{config.provider}': {raw_response}")
    msg = choices[0].get("message", {})
    return (msg.get("content") or "").strip()


def strip_json_fences(text: str) -> str:
    """Strip optional ```json ... ``` markdown fences if a model wraps its JSON output."""
    cleaned = text.strip()
    m = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return cleaned


def chat_completion(
    messages: list[dict[str, Any]],
    *,
    role: str = "LLM",
    config: ProviderConfig | None = None,
    max_tokens: int = 4096,
    temperature: float | None = 0.0,
    json_schema: dict[str, Any] | None = None,
    schema_name: str = "expectrail_response",
    strict: bool = True,
    transport: Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute a chat completion across any configured BYO-LLM provider and return raw response dict.

    Automatically falls back to unstructured JSON prompting if an OpenAI-compatible endpoint
    (such as an older local Ollama or vLLM model) rejects `response_format: json_schema`.
    """
    cfg = config or resolve_provider(role=role)
    url, headers, payload = build_http_payload(
        cfg,
        messages,
        max_tokens=max_tokens,
        temperature=temperature,
        json_schema=json_schema,
        schema_name=schema_name,
        strict=strict,
    )

    def _default_transport(u: str, h: dict[str, str], p: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(u, data=json.dumps(p).encode("utf-8"), headers=h, method="POST")
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=cfg.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                err_body = exc.read().decode("utf-8", errors="replace")
                if exc.code in RETRY_STATUS and attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                if (
                    exc.code == 400
                    and "response_format" in p
                    and any(tok in err_body.lower() for tok in ("response_format", "json_schema", "schema"))
                ):
                    p_fallback = dict(p)
                    p_fallback.pop("response_format", None)
                    return _default_transport(u, h, p_fallback)
                raise RuntimeError(f"HTTP {exc.code} from {cfg.provider} ({u}): {err_body}") from exc
        raise RuntimeError(f"Exhausted retries calling {cfg.provider} ({u})")

    caller = transport or _default_transport
    raw = caller(url, headers, payload)
    if cfg.protocol == "anthropic":
        text = extract_message_text(cfg, raw)
        return {
            "choices": [{"message": {"role": "assistant", "content": text}}],
            "model": raw.get("model", cfg.model),
            "provider": cfg.provider,
            "raw": raw,
        }
    return raw


LEGACY_PROVIDERS = frozenset({"meta", "baseten", "fireworks"})


def explicit_provider(role: str = "LLM") -> str:
    """The provider the user chose for ``role`` (EXPECTRAIL_<ROLE>_PROVIDER, then
    EXPECTRAIL_LLM_PROVIDER), or "" when none was chosen."""
    return _first_env(f"EXPECTRAIL_{role.upper()}_PROVIDER", "EXPECTRAIL_LLM_PROVIDER").lower()


def byo_requested(role: str = "LLM") -> bool:
    """True when ``role`` should go through this module instead of the legacy Meta path.

    Either the user named a non-Meta provider, or there is no Meta key at all but another
    provider's key (or a local server) is configured. A configured Meta key with no explicit
    choice keeps the legacy path, byte for byte.
    """
    chosen = explicit_provider(role)
    if chosen:
        return chosen != "meta"
    if _first_env("MODEL_API_KEY", "META_API_KEY"):
        return False
    return detect_default_provider() not in LEGACY_PROVIDERS


def provider_ready(role: str = "LLM", **kwargs: Any) -> bool:
    """True when resolve_provider(role) would succeed (a key, or a provider that needs none)."""
    try:
        resolve_provider(role, **kwargs)
    except RuntimeError:
        return False
    return True
