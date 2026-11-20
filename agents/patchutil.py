"""Apply patches and enforce editable path globs for candidate fixes."""
from __future__ import annotations

import fnmatch
import hashlib
import re
from pathlib import Path

from harness import patching

DIFF_PATH = re.compile(r"^(?:---|\+\+\+) [ab]/(.+)$", re.MULTILINE)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_patch(work: Path, patch: Path) -> None:
    """Apply one unified diff to ``work`` and leave the tree it names (``harness.patching``, #659)."""
    patching.apply(work, patch)


def apply_patches(work: Path, patches: list[Path]) -> None:
    for patch in patches:
        apply_patch(work, patch)


def paths_touched(patch_text: str) -> list[str]:
    """Return unique game-relative paths named in a unified diff."""
    found: list[str] = []
    for match in DIFF_PATH.finditer(patch_text):
        rel = match.group(1).strip()
        if rel == "/dev/null":
            continue
        if rel not in found:
            found.append(rel)
    return found


def path_allowed(rel: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(rel, g.rstrip("/")) for g in globs)


def assert_editable(patch_text: str, editable: list[str]) -> list[str]:
    """Return paths that violate editable globs (empty if the patch is allowed)."""
    return [p for p in paths_touched(patch_text) if not path_allowed(p, editable)]


def write_unified_diff(before: Path, after: Path, relative: str) -> str:
    """Build a minimal unified diff for one file (a/relative → b/relative)."""
    import difflib

    a = before.read_text(encoding="utf-8").splitlines(keepends=True)
    b = after.read_text(encoding="utf-8").splitlines(keepends=True)
    return "".join(difflib.unified_diff(a, b, fromfile=f"a/{relative}", tofile=f"b/{relative}"))
