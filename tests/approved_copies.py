"""Approved copies of a check for tests that edit one (#644).

Since #642 the committed checks carry approvals bound to their content (#420), so a copy whose body a
test edits is no longer approved. A test that needs an edited check approved approves its own copy,
with the writer a person runs, in a temporary folder that the helper creates and deletes. A test that
needs an approval from before content binding builds one here instead of borrowing a committed check.

Nothing here writes into the repository: every approval is made on a copy in memory or in a temporary
folder, and no committed file is read for its approval.
"""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from expectrail.approval import approve

BY = "a test fixture"
AT = "2026-11-19T00:00:00Z"
LEGACY_AT = "2026-10-28T00:00:00Z"


def body(doc: dict) -> dict:
    """``doc`` without its approval: what a person would approve."""
    out = copy.deepcopy(doc)
    out.pop("approval", None)
    return out


def reapproved(doc: dict, by: str = BY, at: str = AT) -> dict:
    """``doc`` (its approval dropped) approved through ``approve`` in a temporary folder: bound to
    exactly this content."""
    with tempfile.TemporaryDirectory(prefix="approved-copy-") as tmp:
        path = Path(tmp) / "spec.json"
        path.write_text(json.dumps(body(doc)), encoding="utf-8")
        return approve(path, by, at=at)


def legacy(doc: dict, by: str = BY, at: str = LEGACY_AT) -> dict:
    """``doc`` with an approval from before content binding: a person and a time, no digest."""
    out = body(doc)
    out["approval"] = {"by": by, "at": at}
    return out
