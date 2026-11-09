"""Muse Wonder triage: turn failure evidence into a bug report, then a repair-request.

    python3 -m agents.triage --verdict ... --spec ... --route ... --out runs/triage \\
        [--log godot.log] [--frames-dir runs/fall/frames] [--offline]

With MODEL_API_KEY, calls muse-wonder-1.0 over Meta Model API. With a BYO provider
(EXPECTRAIL_TRIAGE_PROVIDER or EXPECTRAIL_LLM_PROVIDER and its key, or --provider), calls that model
through expectrail.providers instead. With --offline (or no key), writes a deterministic bug report
from the verdict reason and still emits a repair-request.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from agents.keys import load_dotenv, triage_ready, wonder_key
from agents.orchestrator import build_repair_request
from harness.run import REPO
from expectrail.contracts import load

WONDER_MODEL = "muse-wonder-1.0"


def _bug_report_offline(spec: dict, verdict: dict, route: dict, log_text: str) -> str:
    return "\n".join([
        f"# Bug report: {spec.get('id', 'unknown')}",
        "",
        f"Instruction: {spec.get('instruction', '')}",
        f"Assertion: {json.dumps(spec.get('assertion', {}), sort_keys=True)}",
        f"Verdict: {verdict.get('result')} — {verdict.get('reason')}",
        f"First fail frame: {verdict.get('firstFrame')}",
        f"Route: {route.get('name')} ({route.get('ticks')} ticks)",
        "",
        "## Evidence",
        json.dumps(verdict.get("evidence", [])[:3], indent=2),
        "",
        "## Log tail",
        "\n".join(log_text.strip().splitlines()[-40:]) or "(no log)",
        "",
        "Infer the smallest correct fix from the failing assertion and evidence above.",
        "Do not invent held-out checks or signing material.",
    ])


def call_wonder(prompt: str, api_key: str, *, api_base: str | None = None) -> str:
    base = api_base or os.environ.get("META_API_BASE", "https://api.meta.ai/v1")
    body = json.dumps({
        "model": WONDER_MODEL,
        "messages": [
            {"role": "system", "content": "You triage game bugs for Expectrail. Be concise."},
            {"role": "user", "content": prompt},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


TRIAGE_SYSTEM = "You triage game bugs for Expectrail. Be concise."


def call_byo(prompt: str, *, provider: str | None = None, model: str | None = None) -> tuple[str, str]:
    """Triage through any provider expectrail.providers knows. Returns (report, "provider/model")."""
    from expectrail.providers import chat_completion, extract_message_text, resolve_provider

    cfg = resolve_provider("TRIAGE", provider=provider, model=model,
                           legacy_default_model=WONDER_MODEL, legacy_key_envs=("MODEL_API_KEY", "META_API_KEY"))
    messages = [{"role": "system", "content": TRIAGE_SYSTEM}, {"role": "user", "content": prompt}]
    raw = chat_completion(messages, role="TRIAGE", config=cfg, max_tokens=2048, temperature=0.0)
    return extract_message_text(cfg, raw), f"{cfg.provider}/{cfg.model}"


def triage(
    *,
    spec: dict,
    verdict: dict,
    route: dict,
    out: Path,
    base_patch: str = "bugs/physics-fall-through/v1.patch",
    log_text: str = "",
    key_frames: list[str] | None = None,
    offline: bool = False,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    from expectrail.providers import byo_requested

    out.mkdir(parents=True, exist_ok=True)
    prompt = _bug_report_offline(spec, verdict, route, log_text)
    api_base = os.environ.get("META_API_BASE", "https://api.meta.ai/v1")
    api_key = wonder_key()
    if provider is not None:
        byo = provider != "meta"
    else:
        byo = byo_requested("TRIAGE")
    triage_model = WONDER_MODEL
    if offline or (not byo and not api_key) or (byo and provider is None and not triage_ready()):
        report = prompt
        source = "offline"
    elif byo:
        triage_model = f"byo:{provider or 'configured'}"  # what was attempted, if the call fails
        try:
            report, triage_model = call_byo(
                prompt + "\n\nWrite a short actionable bug report for the coding agent.",
                provider=provider, model=model,
            )
            source = triage_model
        except (RuntimeError, urllib.error.URLError, KeyError, TimeoutError) as exc:
            report = prompt + f"\n\n(BYO triage call failed: {exc}; using offline report.)"
            source = "offline-fallback"
    else:
        try:
            report = call_wonder(
                prompt + "\n\nWrite a short actionable bug report for Muse Code.",
                api_key,
                api_base=api_base,
            )
            source = WONDER_MODEL
        except (urllib.error.URLError, KeyError, TimeoutError) as exc:
            report = prompt + f"\n\n(Wonder call failed: {exc}; using offline report.)"
            source = "offline-fallback"

    (out / "bug-report.md").write_text(report + "\n", encoding="utf-8")
    triage_meta = {"source": source, "model": triage_model}
    request = build_repair_request(
        request_id=f"rr-triage-{spec.get('id', 'bug')}",
        spec=spec,
        verdict=verdict,
        route=route,
        base_patch=base_patch,
        key_frames=key_frames,
        notes=f"Triage source: {source}. See bug-report.md.",
        triage=triage_meta,
    )
    (out / "repair-request.json").write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
    (out / "triage.json").write_text(json.dumps(triage_meta, indent=2) + "\n", encoding="utf-8")
    return request


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--spec", type=Path, default=REPO / "agents" / "specs" / "player-stays-above-ground.json")
    p.add_argument("--verdict", type=Path, default=REPO / "contracts" / "examples" / "verdict.json")
    p.add_argument("--route", type=Path, default=REPO / "harness" / "routes" / "smoke.json")
    p.add_argument("--base-patch", default="bugs/physics-fall-through/v1.patch")
    p.add_argument("--log", type=Path)
    p.add_argument("--key-frame", action="append", default=[])
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--offline", action="store_true")
    p.add_argument("--provider", help="BYO triage provider (anthropic, openai, gemini, openrouter, ollama, "
                                      "vllm, meta, ...); default: EXPECTRAIL_TRIAGE_PROVIDER / LLM_PROVIDER")
    p.add_argument("--model", help="model id for --provider (default: the provider's default)")
    args = p.parse_args(argv)
    log_text = args.log.read_text(encoding="utf-8") if args.log and args.log.exists() else ""
    triage(
        spec=load(args.spec, "test-spec"),
        verdict=load(args.verdict, "verdict"),
        route=load(args.route, "route"),
        out=args.out,
        base_patch=args.base_patch,
        log_text=log_text,
        key_frames=args.key_frame or ["frames/f00000008.png", "frames/f00000016.png"],
        offline=args.offline,
        provider=args.provider,
        model=args.model,
    )
    print(f"wrote {args.out / 'repair-request.json'} and bug-report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
