"""Draft a test spec from a plain-English check with Muse Spark, then have a person approve it.

    export MODEL_API_KEY=...              # your Meta Model API key; never commit it
    python3 -m expectrail.spec_writer draft "The player never falls through the ground" \
        --id player-stays-above-ground --out specs/player-stays-above-ground.json
    python3 -m expectrail.spec_writer approve specs/player-stays-above-ground.json --by sean

    # Any other model (expectrail.providers): anthropic, openai, gemini, openrouter, ollama, vllm, ...
    export ANTHROPIC_API_KEY=...
    python3 -m expectrail.spec_writer draft "The player never falls through the ground" --provider anthropic

Muse Spark only drafts. A draft is checked against contracts/test-spec.schema.json, and against
Meta's advice to keep positions out of SAM prompts, and it has no approval until a person adds one.
The evaluator, not the model, decides pass or fail later.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from expectrail import approval
from expectrail.contracts import ContractError, schema, validate

API_BASE = os.environ.get("EXPECTRAIL_MODEL_API_BASE", "https://api.meta.ai/v1")
DEFAULT_MODEL = os.environ.get("EXPECTRAIL_SPEC_MODEL", "muse-spark-1.3")
# Open weights: Muse Spark Open on a partner's OpenAI-compatible endpoint (draft --endpoint open).
# Baseten by default, with the model id Baseten lists (the id an earlier guide gave,
# meta-models/muse-spark-open-1026, is not listed; bench/spark-open/README.md).
OPEN_API_BASE = os.environ.get("EXPECTRAIL_OPEN_API_BASE", "https://inference.baseten.co/v1")
OPEN_MODEL = os.environ.get("EXPECTRAIL_OPEN_MODEL", "meta-models/muse-spark-open")
OPEN_KEY_ENVS = ("EXPECTRAIL_OPEN_API_KEY", "BASETEN_API_KEY")
# Words that describe position. SAM 3.1 finds things; where they are is the evaluator's job.
POSITIONAL = re.compile(r"\b(left|right|above|below|under|over|top|bottom|behind|in front|near|beside|"
                        r"next to|inside|outside|on top|underneath|between)\b", re.I)

SYSTEM_PROMPT = """You write test specs for Expectrail, a system that checks what players see in a game.
Turn the user's plain-English check into one JSON object in the expectrail.test-spec/v0 format.

Rules:
- "objects" names each thing the check is about. Each "prompt" is a short noun phrase a segmentation
  model can find in a frame, such as "blue robot" or "gold coin". Never put a position,
  direction or relation in a prompt ("left", "above", "on the ground" are not allowed there).
- "assertion" is exactly one of these four types, and nothing else:
  1. {"type": "visible", "object": O, "minFraction": 0..1}: O is found in at least that share of frames.
  2. {"type": "inside-region", "object": O, "region": {"relativeTo": R, "marginPx": n} or {"box": [x0,y0,x1,y1]},
     "tolerancePx": n}: O stays inside R's box (or a fixed box).
  3. {"type": "never-crosses", "object": O, "boundary": {"relativeTo": R, "edge": "top|bottom|left|right",
     "side": "above|below|left-of|right-of", "tolerancePx": n}}: O stays on "side" of that edge of R and
     never crosses it. "side" is where O stays, not where it must not go: "the ball never rises through
     the ceiling" is {"relativeTo": "ceiling", "edge": "bottom", "side": "below"}.
  4. {"type": "reaches", "object": O, "goal": G, "distancePx": n}: O touches or comes within n px of G at some point.
- Every object named in the assertion must appear in "objects".
- If the check cannot be expressed with these four types, return {"unsupported": "<why>"} instead.
- Frames are 1600 by 960 pixels, y down. Use small tolerances (8 to 16 px) unless the check says otherwise.
Return only the JSON object."""

EXAMPLE_IN = "The dialog text always fits inside the dialog box."
EXAMPLE_OUT = {
    "format": "expectrail.test-spec/v0", "id": "dialog-text-fits-box", "instruction": EXAMPLE_IN,
    "objects": {"text": {"prompt": "dialog text"}, "box": {"prompt": "dialog box"}},
    "assertion": {"type": "inside-region", "object": "text", "region": {"relativeTo": "box"}, "tolerancePx": 4},
}


class SpecDraftError(RuntimeError):
    pass


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "spec"


def request_body(instruction: str, model: str, structured: bool = True, problems: list[str] | None = None) -> dict:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": EXAMPLE_IN},
        {"role": "assistant", "content": json.dumps(EXAMPLE_OUT)},
        {"role": "user", "content": instruction},
    ]
    if problems:
        messages.append({"role": "user", "content": "Your last answer was not a valid spec: "
                         + "; ".join(problems) + ". Return a corrected JSON object only."})
    body = {"model": model, "messages": messages, "temperature": 0}
    if structured:
        spec_schema = {k: v for k, v in schema("test-spec").items() if not k.startswith("$")}
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "expectrail_test_spec", "schema": spec_schema}}
    else:
        body["response_format"] = {"type": "json_object"}
    return body


def http_transport(body: dict, timeout: float = 120) -> dict:
    """POST to the Meta Model API's OpenAI-compatible chat completions endpoint."""
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        raise SpecDraftError("set MODEL_API_KEY to your Meta Model API key")
    req = urllib.request.Request(f"{API_BASE}/chat/completions", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")[:500]
        raise SpecDraftError(f"HTTP {err.code}: {detail}") from err


def open_transport(base: str | None = None, key: str | None = None):
    """POST to an OpenAI-compatible /chat/completions serving Muse Spark Open (open weights)."""
    base = (base or OPEN_API_BASE).rstrip("/")
    key = key or next((os.environ[n] for n in OPEN_KEY_ENVS if os.environ.get(n)), None)
    if not key:
        raise SpecDraftError(f"set one of {', '.join(OPEN_KEY_ENVS)} for {base}")

    def transport(body: dict) -> dict:
        req = urllib.request.Request(f"{base}/chat/completions", data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as err:
            detail = err.read().decode(errors="replace")[:500]
            raise SpecDraftError(f"HTTP {err.code}: {detail}") from err

    return transport


def provider_transport(provider: str | None = None, model: str | None = None):
    """Draft through expectrail.providers: any provider it knows, chosen by ``provider`` or
    EXPECTRAIL_SPEC_PROVIDER / EXPECTRAIL_LLM_PROVIDER. Returns (transport, resolved config).

    The transport takes the same request body as http_transport, so draft() and its fallback from
    schema-constrained output to plain JSON work unchanged.
    """
    from expectrail.providers import chat_completion, resolve_provider

    try:
        cfg = resolve_provider("SPEC", provider=provider, model=model, legacy_default_model=DEFAULT_MODEL,
                               legacy_key_envs=("MODEL_API_KEY",))
    except RuntimeError as err:
        raise SpecDraftError(str(err)) from err

    def transport(body: dict) -> dict:
        fmt = body.get("response_format") or {}
        schema_doc = (fmt.get("json_schema") or {}).get("schema") if fmt.get("type") == "json_schema" else None
        messages = list(body["messages"])
        if schema_doc is None and fmt.get("type") == "json_object":
            messages[0] = {**messages[0], "content": messages[0]["content"] + "\nAnswer with one JSON object."}
        try:
            return chat_completion(messages, role="SPEC", config=cfg, max_tokens=4096,
                                   temperature=body.get("temperature", 0), json_schema=schema_doc,
                                   schema_name="expectrail_test_spec", strict=False)
        except RuntimeError as err:
            raise SpecDraftError(str(err)) from err

    return transport, cfg


def lint(spec: dict) -> list[str]:
    """Problems the schema cannot see."""
    problems = []
    objects = spec.get("objects", {})
    for name, obj in objects.items():
        if POSITIONAL.search(obj.get("prompt", "")):
            problems.append(f"object {name!r} prompt {obj['prompt']!r} describes a position; positions belong "
                            "in the assertion")
    assertion = spec.get("assertion", {})
    named = [assertion.get("object"), assertion.get("goal"),
             (assertion.get("region") or {}).get("relativeTo"), (assertion.get("boundary") or {}).get("relativeTo")]
    for name in filter(None, named):
        if name not in objects:
            problems.append(f"assertion names {name!r}, which is not in objects")
    if "approval" in spec:
        problems.append("a draft must not carry an approval; a person adds it")
    return problems


def _parse(response: dict) -> dict:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as err:
        raise SpecDraftError(f"unexpected response shape: {str(response)[:200]}") from err
    if isinstance(content, list):  # some APIs return content parts
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    try:
        return json.loads(content)
    except json.JSONDecodeError as err:
        raise SpecDraftError(f"the model did not return JSON: {content[:200]}") from err


def draft(instruction: str, spec_id: str | None = None, model: str = DEFAULT_MODEL, transport=http_transport,
          allow_training: bool = False, attempts: int = 2) -> tuple[dict | None, list[str]]:
    """Returns (spec, problems). spec is None when the check is unsupported or no valid draft came back."""
    if model.endswith("-contributor") and not allow_training:
        raise SpecDraftError(f"{model} lets Meta train on prompts; use it only for public material "
                             "(pass allow_training=True)")
    structured, problems = True, []
    for _ in range(attempts):
        try:
            response = transport(request_body(instruction, model, structured, problems or None))
        except SpecDraftError as err:
            text = str(err)
            if structured and (text.startswith("HTTP 400") or "response_format" in text or "json_schema" in text):
                structured = False  # the endpoint rejected schema-constrained output; ask for plain JSON
                response = transport(request_body(instruction, model, structured, problems or None))
            else:
                raise
        doc = _parse(response)
        if "unsupported" in doc:
            return None, [f"unsupported: {doc['unsupported']}"]
        doc["format"] = "expectrail.test-spec/v0"
        doc["instruction"] = instruction
        doc["id"] = spec_id or doc.get("id") or slug(instruction)
        doc.pop("approval", None)
        problems = []
        try:
            validate(doc, "test-spec")
        except ContractError as err:
            problems.append(str(err))
        problems += lint(doc)
        if not problems:
            return doc, []
    return None, problems


def approve(path: Path, by: str, at: str | None = None) -> dict:
    """A person signs off on a draft: it must be valid and lint-clean first."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    doc.pop("approval", None)
    validate(doc, "test-spec")
    problems = lint(doc)
    if problems:
        raise SpecDraftError("; ".join(problems))
    # The approval binds to what was approved (#420): the digest of the spec without its approval,
    # computed here and never typed. Editing the spec afterwards makes the approval not count.
    try:
        content = approval.spec_sha256(doc)
    except ValueError as err:   # a value canonical JSON cannot hold (NaN, an infinity)
        raise SpecDraftError(f"the spec cannot be approved: {err}") from err
    doc["approval"] = {"by": by, "at": at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       approval.DIGEST_FIELD: content}
    validate(doc, "test-spec")
    if approval.state(doc) != approval.BOUND:  # never write an approval that its own readers refuse
        raise SpecDraftError("the approval written does not match the spec it was written for")
    Path(path).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Draft and approve Expectrail test specs.")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft", help="ask Muse Spark for a draft spec")
    d.add_argument("instruction")
    d.add_argument("--id")
    d.add_argument("--out", type=Path)
    d.add_argument("--endpoint", choices=("meta", "open"), default="meta",
                   help="meta: Muse Spark on Meta's Model API; open: Muse Spark Open (open weights) on "
                        "EXPECTRAIL_OPEN_API_BASE (default Baseten) with BASETEN_API_KEY")
    d.add_argument("--model", help=f"default {DEFAULT_MODEL}, or {OPEN_MODEL} with --endpoint open, or the "
                                   "provider's default with --provider")
    d.add_argument("--provider", help="any expectrail.providers provider (anthropic, openai, gemini, openrouter, "
                                      "ollama, vllm, meta, baseten, fireworks); overrides --endpoint. Default: "
                                      "EXPECTRAIL_SPEC_PROVIDER / EXPECTRAIL_LLM_PROVIDER when set")
    d.add_argument("--allow-training", action="store_true", help="allow a contributor-tier model")
    a = sub.add_parser("approve", help="a person approves a draft")
    a.add_argument("path", type=Path)
    a.add_argument("--by", required=True)
    args = p.parse_args(argv)
    try:
        if args.cmd == "draft":
            from expectrail.providers import byo_requested

            if args.provider or (args.endpoint == "meta" and byo_requested("SPEC")):
                transport, cfg = provider_transport(args.provider, args.model)
                model, where = cfg.model, f"{cfg.provider}, {cfg.api_base}"
            elif args.endpoint == "open":
                model, transport = args.model or OPEN_MODEL, open_transport()
                where = "open weights, " + OPEN_API_BASE
            else:
                model, transport = args.model or DEFAULT_MODEL, http_transport
                where = API_BASE
            spec, problems = draft(args.instruction, args.id, model, transport=transport,
                                   allow_training=args.allow_training)
            print(f"drafted by {model} ({where})", file=sys.stderr)
            if spec is None:
                print("needs review: " + "; ".join(problems), file=sys.stderr)
                return 2
            text = json.dumps(spec, indent=2) + "\n"
            if args.out:
                args.out.write_text(text, encoding="utf-8")
                print(f"draft written to {args.out}; review it, then run: python3 -m expectrail.spec_writer "
                      f"approve {args.out} --by <you>")
            else:
                print(text, end="")
            return 0
        doc = approve(args.path, args.by)
        print(f"approved {doc['id']} by {doc['approval']['by']} at {doc['approval']['at']} "
              f"(content sha256 {doc['approval'][approval.DIGEST_FIELD]})")
        return 0
    except (SpecDraftError, ContractError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
