"""Format IDs for the v0 contracts, kept as a module of its own because ``expectrail.contracts``,
which the discovery freeze covers byte for byte (discovery/freeze.json), imports it from here."""
from __future__ import annotations

PREFIX = "expectrail"


def format_ids(name: str, version: str = "v0") -> tuple[str, ...]:
    """The format IDs a document of this kind may carry: only the current one."""
    return (f"{PREFIX}.{name}/{version}",)
