"""Fixer↔verifier isolation: shared deny-by-absence names (mount absence only).

These basenames must not appear under fixer-work. This does not claim the Muse
process cannot read the rest of the repo — only that verifier controls are not
mounted into the fixer workspace.
"""
from __future__ import annotations

from pathlib import Path

# Closed list for Gate 1 filmable trust. Basename match under fixer-work.
FIXER_FORBIDDEN_BASENAMES = frozenset({
    ".expectrail-signing-key",
    "obs-clean.json",
    "obs-held-out.json",
    "player-stays-above-ground.json",
    # Retired opaque reaches label — deny forever so it cannot remount as a test-spec.
    "player-reaches-end-of-route.json",
    # Current opaque motion id — deny so a fake SAM/spec file cannot mount either.
    "player-motion-on-smoke.json",
    # Verifier-side gameplay adjunct — must not mount into fixer-work.
    "verdict-gameplay.json",
    "evaluator.py",
})


# Generated checks (expectrail/jit, docs/jit.md) are never shown to the fixer, before or after a failed
# attempt: every file and folder the check generator writes is named with this prefix.
FIXER_FORBIDDEN_PREFIXES = ("jit-",)


def _forbidden(rel: Path) -> bool:
    return rel.name in FIXER_FORBIDDEN_BASENAMES or any(
        part.startswith(FIXER_FORBIDDEN_PREFIXES) for part in rel.parts)


def forbidden_paths_under(fixer: Path) -> list[Path]:
    """Return paths under fixer whose basename is on the deny list, or that sit in or are a generated-check
    output (a path component named ``jit-*``)."""
    if not fixer.is_dir():
        return []
    return sorted(
        p for p in fixer.rglob("*")
        if p.is_file() and _forbidden(p.relative_to(fixer))
    )


def arm(
    *,
    source: str,
    path: str | None = None,
    observations_sha256: str | None = None,
    detail: str | None = None,
) -> dict:
    """One suite provenance arm (candidate / clean / heldOut)."""
    out: dict = {"source": source}
    if path is not None:
        out["path"] = path
    if observations_sha256 is not None:
        out["observationsSha256"] = observations_sha256
    if detail is not None:
        out["detail"] = detail
    return out
