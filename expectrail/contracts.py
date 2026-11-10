"""Loading, hashing and validating the lane contracts in contracts/*.schema.json."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from expectrail.legacy import format_ids

SCHEMAS = Path(__file__).resolve().parent.parent / "contracts"
KINDS = (
    "route",
    "replay",
    "test-spec",
    "observations",
    "verdict",
    "repair-request",
    "verification",
    "gameplay-verdict",
    "release-candidate",
    "overnight-summary",
    "feedback-intake",
    "change-evidence",
)


class ContractError(ValueError):
    pass


def canonical(doc) -> bytes:
    """The bytes a contract's sha256 is taken over: sorted keys, no spaces."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(doc) -> str:
    return hashlib.sha256(canonical(doc)).hexdigest()


def kind_of(doc) -> str:
    """The document kind, from its format ID."""
    fmt = doc.get("format", "") if isinstance(doc, dict) else ""
    for kind in KINDS:
        if fmt in format_ids(kind):
            return kind
    raise ContractError(f"unknown or missing format: {fmt!r}")


def schema(kind: str) -> dict:
    return json.loads((SCHEMAS / f"{kind}.schema.json").read_text(encoding="utf-8"))


def validate(doc, kind: str | None = None) -> str:
    """Check doc against its schema; returns its kind. Needs the jsonschema package."""
    import jsonschema

    kind = kind or kind_of(doc)
    errors = sorted(jsonschema.Draft202012Validator(schema(kind)).iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.path) or "(root)"
        raise ContractError(f"{kind}: {where}: {first.message}")
    if kind == "overnight-summary":
        runs = doc["runs"]
        accepted = doc["accepted"]
        results = doc.get("results") or []
        if accepted > runs:
            raise ContractError(f"overnight-summary: accepted ({accepted}) > runs ({runs})")
        if len(results) != runs:
            raise ContractError(
                f"overnight-summary: len(results) ({len(results)}) != runs ({runs})"
            )
        cost = doc.get("cost") or {}
        if cost.get("costProvenance") == "metered" and cost.get("costUsd") is None:
            raise ContractError("overnight-summary: metered cost requires costUsd")
    if kind == "feedback-intake":
        turns = doc["turns"]
        for n, item in enumerate(doc["items"]):
            if item["turn"] >= len(turns):
                raise ContractError(f"feedback-intake: items/{n}: turn {item['turn']} is past the last turn")
        counts = {c: sum(1 for i in doc["items"] if i["category"] == c) for c in doc["counts"]}
        if counts != doc["counts"]:
            raise ContractError(f"feedback-intake: counts {doc['counts']} do not match items {counts}")
    return kind


def load(path: Path, kind: str | None = None) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if kind and kind_of(doc) != kind:
        raise ContractError(f"{path}: expected expectrail.{kind}/v0")
    return doc


# --- v1 records (docs/discovery.md) --------------------------------------------------------------
# An exact format registry: each v1 format ID maps to its kind and schema file. The v0 helpers above
# (kind_of, schema, validate, load) are unchanged.
V1_FORMATS = {
    "expectrail.episode/v1": ("episode", "episode.v1.schema.json"),
    "expectrail.trace-spec/v1": ("trace-spec", "trace-spec.v1.schema.json"),
    "expectrail.trace-verdict/v1": ("trace-verdict", "trace-verdict.v1.schema.json"),
    "expectrail.mechanics-profile/v1": ("mechanics-profile", "mechanics-profile.v1.schema.json"),
    "expectrail.discovery-run/v1": ("discovery-run", "discovery-run.v1.schema.json"),
    "expectrail.jit-run/v1": ("jit-run", "jit-run.v1.schema.json"),
}


def _no_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ContractError(f"duplicate key {key!r}")
        out[key] = value
    return out


def _no_constants(name):
    raise ContractError(f"non-finite number {name} is not allowed")


def strict_loads(text: str):
    """JSON with duplicate keys, NaN and Infinity refused."""
    return json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_no_constants)


def canonical_v1(doc) -> bytes:
    """canonical() with non-finite numbers refused (the project's v1 serialization rule)."""
    try:
        return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except ValueError as exc:
        raise ContractError(f"cannot serialize: {exc}") from None


def digest_v1(doc) -> str:
    return hashlib.sha256(canonical_v1(doc)).hexdigest()


def v1_kind(doc) -> str:
    fmt = doc.get("format", "") if isinstance(doc, dict) else ""
    if fmt not in V1_FORMATS:
        raise ContractError(f"unknown v1 format: {fmt!r}")
    return V1_FORMATS[fmt][0]


def schema_v1(kind: str) -> dict:
    for k, filename in V1_FORMATS.values():
        if k == kind:
            return json.loads((SCHEMAS / filename).read_text(encoding="utf-8"))
    raise ContractError(f"no v1 schema for {kind!r}")


def validate_v1(doc, kind: str | None = None) -> str:
    """Check a v1 record against its exact schema (and the expected kind, when given); returns its kind."""
    import jsonschema

    found = v1_kind(doc)
    if kind is not None and found != kind:
        raise ContractError(f"expected a {kind} record, got {found}")
    canonical_v1(doc)  # refuses NaN and Infinity anywhere
    errors = sorted(jsonschema.Draft202012Validator(schema_v1(found)).iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.path) or "(root)"
        raise ContractError(f"{found}: {where}: {first.message}")
    return found


def load_strict(path: Path, kind: str | None = None) -> dict:
    """Load and validate a v1 record: duplicate keys, non-finite numbers and unknown formats refused."""
    doc = strict_loads(Path(path).read_text(encoding="utf-8"))
    validate_v1(doc, kind)
    return doc
