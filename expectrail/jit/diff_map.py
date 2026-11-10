"""Map a candidate patch to the behaviours it can affect: changed files and lines, profile claims, probes.

    diff_map(patch_text, profile, probes) -> {"files": [...], "claims": [...], "probeIds": [...]}

The patch is data. It is parsed as a unified diff (paths relative to the game, ``-p1``) and never
applied or run here. A claim is linked to a file when the profile's own ``evidenceRefs`` name that file,
so the map uses nothing but the game's profile; a file no claim names maps to no claim, and then every
probe is a candidate (nothing is skipped because the map did not know a file).

A probe is linked to a claim through the family that exercises the claim's mechanic. The families are
the probe library's (expectrail/discovery/probes.py); no probe is written for a particular change.
"""
from __future__ import annotations

import re

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
MAX_FILES = 50
MAX_LINES_PER_FILE = 400

# Which probe families exercise each claim's mechanic. Claims the table does not know get every probe.
CLAIM_FAMILIES = {
    "player.jump": ("jump-taps",),
    "weapon.cooldown": ("shoot-rate", "move-and-fire"),
    "player.facing": ("hold", "reverse", "move-and-fire", "shoot-rate"),
    "enemy.patrol": ("wait",),
}


class PatchError(ValueError):
    """The patch is not a unified diff this map can read."""


def _strip(path: str) -> str:
    path = path.split("\t", 1)[0].strip()
    if path == "/dev/null":
        return path
    if path.startswith(("a/", "b/")):
        path = path[2:]
    if path.startswith("/") or ".." in path.split("/"):
        raise PatchError(f"patch path {path[:80]!r} is not relative to the game")
    return path


def parse(patch_text: str) -> list[dict]:
    """[{path, added: [(line, text)], removed: [(line, text)]}], in patch order. Lines are 1-based:
    ``added`` in the new file, ``removed`` in the old one."""
    if not isinstance(patch_text, str):
        raise PatchError("the patch is not text")
    files: list[dict] = []
    current: dict | None = None
    old_n = new_n = 0
    in_hunk = False
    lines = patch_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            old, new = _strip(line[4:]), _strip(lines[i + 1][4:])
            path = new if new != "/dev/null" else old
            current = {"path": path, "added": [], "removed": []}
            files.append(current)
            in_hunk = False
            i += 2
            continue
        m = HUNK.match(line)
        if m:
            if current is None:
                raise PatchError("a hunk before any file header")
            old_n, new_n = int(m.group(1)), int(m.group(3))
            in_hunk = True
        elif in_hunk and current is not None:
            if line.startswith("+"):
                current["added"].append((new_n, line[1:]))
                new_n += 1
            elif line.startswith("-"):
                current["removed"].append((old_n, line[1:]))
                old_n += 1
            elif line.startswith(" ") or line == "":
                old_n += 1
                new_n += 1
            elif line.startswith("\\"):
                pass  # "\ No newline at end of file"
            else:
                in_hunk = False
        i += 1
    if not files:
        raise PatchError("no file in the patch")
    if len(files) > MAX_FILES:
        raise PatchError(f"the patch touches more than {MAX_FILES} files")
    for f in files:
        f["added"] = f["added"][:MAX_LINES_PER_FILE]
        f["removed"] = f["removed"][:MAX_LINES_PER_FILE]
    return files


def claims_for(path: str, profile: dict) -> list[str]:
    """The profile claims whose evidence names this file (``game/platformer/<path>: ...``)."""
    out = []
    for claim in profile["claims"]:
        for ref in claim.get("evidenceRefs") or []:
            named = ref.split(":", 1)[0].strip()
            if named.endswith("/" + path) or named == path:
                out.append(claim["claimId"])
                break
    return out


def diff_map(patch_text: str, profile: dict, probes: list[dict]) -> dict:
    files = parse(patch_text)
    claims: list[str] = []
    for f in files:
        f["claims"] = claims_for(f["path"], profile)
        claims += [c for c in f["claims"] if c not in claims]
    families: set[str] = set()
    unknown = not claims or any(c not in CLAIM_FAMILIES for c in claims)
    for c in claims:
        families.update(CLAIM_FAMILIES.get(c, ()))
    probe_ids = [p["id"] for p in probes if unknown or p["family"] in families]
    return {
        "files": [{"path": f["path"], "claims": f["claims"], "addedLines": [n for n, _ in f["added"]],
                   "removedLines": [n for n, _ in f["removed"]]} for f in files],
        "claims": claims,
        "probeIds": probe_ids,
        "allProbes": unknown,
        "_parsed": files,
    }
