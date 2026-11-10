"""One real call to each configured provider, and nothing else.

Expectrail's provider tests use recorded responses, so they pass whether or not a provider will
actually answer. That gap had a cost: the `anthropic` provider sent a `temperature` the Messages API
rejects outright, and every anthropic call — triage, the llm-patch fixer, spec drafting, byo-vlm —
failed from the day the provider layer landed until the first live run was attempted weeks later.
Recorded responses cannot catch that, and nothing else in CI talks to a provider.

So this probe sends one short prompt down the same path a real call takes
(``expectrail.providers.resolve_provider`` → ``build_http_payload`` → ``chat_completion``) and checks
only that the provider answered with text. It acts on nothing the model says, runs no fixer, replays
no game and writes no candidate: it is not an agent lane and not a verdict. A provider with no key
here is skipped and said so, never failed — the probe reports what it could reach.

    python3 -m agents.byo_smoke                  # every provider whose key is set
    python3 -m agents.byo_smoke --provider anthropic openai
    python3 -m agents.byo_smoke --list           # what would run, no calls

Exit 1 if a provider that had a key failed to answer, 0 otherwise (all skipped included: a repository
with no provider keys is a clean skip, not a broken build).
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Callable

from expectrail.providers import (
    PROVIDER_DEFAULTS,
    chat_completion,
    extract_message_text,
    resolve_provider,
)

# Hosted text providers only.
# - ollama and vllm default to a localhost server, so there is nothing for CI to reach and a failure
#   would say nothing about the provider layer.
# - fireworks is Muse Glimmer, a vision-language model Expectrail reaches through
#   agents/byo_vision.py with frames, never as a text chat completion. Probing it here says nothing
#   about the path that uses it: its first run answered HTTP 404 for a model id that the vision call
#   site overrides anyway (EXPECTRAIL_GLIMMER_MODEL). A vision probe needs a frame and a detector
#   comparison, which is a different job; until that exists, Glimmer is unprobed and not pretended
#   otherwise.
PROBED = ("anthropic", "openai", "gemini", "openrouter", "baseten", "meta")
# Short and answerable by any instruction-following model. The reply is not parsed: the probe asserts
# that text came back, not what it says, so a model's wording can never fail CI.
PROMPT = "Reply with the single word: ok"
# Generous on purpose. At 16 a model that spends tokens before it speaks returns no visible text and
# the probe calls a healthy provider broken; its first run did exactly that to Spark Open and Muse
# Spark. The cost of 256 is still a rounding error, and an empty answer now carries the stop reason
# so truncation is never mistaken for a provider that said nothing.
MAX_TOKENS = 256
# The probe never holds the verifier's SAM key (MODEL_API_KEY): for meta it reads META_API_KEY only,
# so a key the verifier owns is not spread into a job that does not need it.
KEY_ENVS: dict[str, tuple[str, ...]] = {
    name: tuple(e for e in PROVIDER_DEFAULTS[name]["key_envs"] if e != "MODEL_API_KEY")
    for name in PROBED
}


def key_envs(provider: str) -> tuple[str, ...]:
    """The env names whose presence lets this provider be probed."""
    return KEY_ENVS.get(provider, ())


def has_key(provider: str, env: dict[str, str] | None = None) -> bool:
    import os

    src = os.environ if env is None else env
    return any((src.get(name) or "").strip() for name in key_envs(provider))


def stop_reason(raw: dict[str, Any]) -> str:
    """Why the model stopped, as the provider reported it.

    An empty answer has two very different causes — the model said nothing, or it ran out of tokens
    before it said anything — and only the stop reason tells them apart. ``chat_completion``
    normalises an Anthropic reply into the OpenAI shape and keeps the original under ``raw``, so both
    spellings are looked for.
    """
    choices = raw.get("choices") or []
    if choices and choices[0].get("finish_reason"):
        return f"finish_reason={choices[0]['finish_reason']}"
    inner = raw.get("raw") if isinstance(raw.get("raw"), dict) else {}
    for source in (raw, inner):
        if source.get("stop_reason"):
            return f"stop_reason={source['stop_reason']}"
    return "no stop reason reported"


def probe(
    provider: str,
    *,
    transport: Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Call ``provider`` once. Returns a result row; never raises for a provider-side failure."""
    if not has_key(provider):
        return {"provider": provider, "model": None, "result": "skipped",
                "detail": f"no key: set one of {', '.join(key_envs(provider))}"}
    try:
        cfg = resolve_provider("LLM", provider=provider)
    except RuntimeError as exc:  # a key was present but the provider could not be configured
        return {"provider": provider, "model": None, "result": "fail", "detail": str(exc)}
    try:
        raw = chat_completion([{"role": "user", "content": PROMPT}], config=cfg,
                              max_tokens=MAX_TOKENS, transport=transport)
        text = extract_message_text(cfg, raw)
    except Exception as exc:  # noqa: BLE001 - any provider-side failure is a result, not a crash
        return {"provider": provider, "model": cfg.model, "result": "fail",
                "detail": f"{type(exc).__name__}: {' '.join(str(exc).split())[:400]}"}
    if not text.strip():
        return {"provider": provider, "model": cfg.model, "result": "fail",
                "detail": f"the provider answered with no text ({stop_reason(raw)})"}
    return {"provider": provider, "model": cfg.model, "result": "ok",
            "detail": f"answered {len(text.strip())} characters"}


def lines(rows: list[dict[str, Any]]) -> list[str]:
    """GitHub annotations: one per provider, then a summary."""
    out = []
    for row in rows:
        where = f"{row['provider']}" + (f"/{row['model']}" if row["model"] else "")
        if row["result"] == "ok":
            out.append(f"::notice title=BYO smoke {row['provider']}::{where} answered")
        elif row["result"] == "skipped":
            out.append(f"::notice title=BYO smoke {row['provider']} skipped::{row['detail']}")
        else:
            out.append(f"::error title=BYO smoke {row['provider']}::{where}: {row['detail']}")
    counts = {r: sum(1 for row in rows if row["result"] == r) for r in ("ok", "fail", "skipped")}
    out.append(f"::notice title=BYO smoke::{counts['ok']} answered, {counts['fail']} failed, "
               f"{counts['skipped']} skipped (no key)")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--provider", nargs="+", choices=PROBED, help="default: every provider with a key")
    p.add_argument("--list", action="store_true", help="print what would run and make no calls")
    args = p.parse_args(argv)
    wanted = args.provider or list(PROBED)
    if args.list:
        for name in wanted:
            print(f"{name}: {'would call' if has_key(name) else 'skipped (no key)'}")
        return 0
    rows = [probe(name) for name in wanted]
    for line in lines(rows):
        print(line)
    return 1 if any(row["result"] == "fail" for row in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
