"""An approval binds to the spec's content (issue #420).

A person's approval of a test spec is ``{"by", "at", "specSha256"}``. ``specSha256`` is the SHA-256
of the spec's canonical JSON with ``approval`` removed: keys sorted at every level, separators
``,`` and ``:``, no ASCII escaping, encoded as UTF-8, and non-finite numbers refused. Whitespace and
key order in the file therefore do not change it; any change to a value does (the assertion, the
window, a tolerance, the coverage block, the instruction, the id).

The digest is computed by ``expectrail.spec_writer approve``, which a person runs. It is never typed
by hand, and an agent never writes one.

Every reader of ``approval`` asks ``state`` (or ``approved``):

- ``bound``: the approval carries a digest and it matches the body. Approved.
- ``legacy``: the approval has no digest (every approval written before this). It still counts, and
  readers name it "approved before content binding" so a person knows to approve it again.
- ``mismatch``: the approval carries a digest that does not match the body (the spec was edited
  after it was approved, or the approval was copied from another spec), or the digest cannot be
  computed. Not approved: the spec is counted with the drafts and never judges a change.
- ``none``: no approval. A draft.
"""
from __future__ import annotations

import hashlib
import hmac
import json

DIGEST_FIELD = "specSha256"

NONE = "none"
BOUND = "bound"
LEGACY = "legacy"
MISMATCH = "mismatch"

MISMATCH_REASON = "approval does not match the spec's content; a person must approve it again"
LEGACY_NOTE = "approved before content binding"


def canonical(doc: dict) -> bytes:
    """The bytes the digest is taken over: the spec without ``approval``, canonical JSON in UTF-8.
    Raises ValueError for a value JSON cannot hold exactly (NaN, an infinity)."""
    if not isinstance(doc, dict):
        raise ValueError("a spec is a JSON object")
    body = {key: value for key, value in doc.items() if key != "approval"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return text.encode("utf-8")


def spec_sha256(doc: dict) -> str:
    return hashlib.sha256(canonical(doc)).hexdigest()


def state(doc) -> str:
    """``none``, ``bound``, ``legacy`` or ``mismatch`` for a parsed spec (see the module's notes).
    Anything that cannot be read as a matching digest is ``mismatch``: never approved."""
    if not isinstance(doc, dict):
        return NONE
    approval = doc.get("approval")
    if not approval:
        return NONE
    if not isinstance(approval, dict):
        return MISMATCH
    if DIGEST_FIELD not in approval:
        return LEGACY
    claimed = approval[DIGEST_FIELD]
    if not isinstance(claimed, str):
        return MISMATCH
    try:
        actual = spec_sha256(doc)
    except (ValueError, TypeError):
        return MISMATCH
    return BOUND if hmac.compare_digest(claimed.encode("ascii", "replace"), actual.encode("ascii")) else MISMATCH


def approved(doc) -> bool:
    """Whether a spec may judge a change: its approval matches its content, or it predates binding."""
    return state(doc) in (BOUND, LEGACY)


def note(spec_id: str, which: str) -> str | None:
    """The line a record or a report gives for a spec in state ``which``; None when there is nothing
    to say (a bound approval, or no approval at all)."""
    if which == MISMATCH:
        return f"spec {spec_id}: {MISMATCH_REASON}"
    if which == LEGACY:
        return f"spec {spec_id}: {LEGACY_NOTE}"
    return None


def is_note(line: str) -> bool:
    """Whether a record's reason is one of ``note``'s lines (the comment shows those on any decision)."""
    return isinstance(line, str) and line.startswith("spec ") and (
        line.endswith(": " + MISMATCH_REASON) or line.endswith(": " + LEGACY_NOTE))


# Shared by the model-side writer and the installed offline onboarding review.
import re
from datetime import datetime, timezone
from pathlib import Path

POSITIONAL = re.compile(r"\b(left|right|above|below|under|over|top|bottom|behind|in front|near|beside|"
                        r"next to|inside|outside|on top|underneath|between)\b", re.I)

class ApprovalError(ValueError):
    pass


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


def approve(path: Path, by: str, at: str | None = None, *, expected_sha256: str | None = None) -> dict:
    """A person signs off on a draft: it must be valid and lint-clean first."""
    from expectrail.contracts import validate
    if not isinstance(by, str) or not by.strip() or "\n" in by or "\r" in by:
        raise ApprovalError("A person's name is required; no approval was written.")
    by = by.strip()
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    doc.pop("approval", None)
    validate(doc, "test-spec")
    problems = lint(doc)
    if problems:
        raise ApprovalError("; ".join(problems))
    # The approval binds to what was approved (#420): the digest of the spec without its approval,
    # computed here and never typed. Editing the spec afterwards makes the approval not count.
    try:
        content = spec_sha256(doc)
    except ValueError as err:   # a value canonical JSON cannot hold (NaN, an infinity)
        raise ApprovalError(f"the spec cannot be approved: {err}") from err
    if expected_sha256 is not None and not hmac.compare_digest(content, expected_sha256):
        raise ApprovalError("the spec changed since review; no approval was written")
    doc["approval"] = {"by": by, "at": at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       DIGEST_FIELD: content}
    validate(doc, "test-spec")
    if state(doc) != BOUND:  # never write an approval that its own readers refuse
        raise ApprovalError("the approval written does not match the spec it was written for")
    Path(path).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc
