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
