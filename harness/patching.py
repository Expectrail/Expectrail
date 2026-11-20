"""Put a unified diff on a copy of the game so the tree is the one the diff names (#659).

Every seed, candidate and repair reaches a game copy through ``apply``. It runs the machine's
``patch -p1 --forward --batch`` and then checks the result against the diff's own headers:

- A file the diff deletes (new name ``/dev/null``) must be gone. macOS's ``patch``, and GNU ``patch``
  under POSIXLY_CORRECT, leave it behind with zero bytes; that empty file is removed. If it is still
  there with content, or as anything but a file, the application stops.
- A file the diff edits or creates must be there afterwards, even when the edit leaves it empty. No
  global ``-E``: that would also delete a file a candidate meant to empty.

An empty patch changes nothing. What the check cannot read is refused before ``patch`` runs, never
passed: a non-empty diff with no file in it, a name that leaves the copy, a rename, copy or binary
change (``patch`` would move or skip bytes this reader does not follow), or a hunk with more lines
than its header says. A hunk cut short is left to ``patch``, which accepts trailing context that ends
early.

A refusal or a mismatch raises ``PatchNotApplied``, a ``CalledProcessError``, so callers that already
stop on a failed ``patch`` stop on it too.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath

NULL = "/dev/null"
HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
UNREADABLE = ("rename from ", "rename to ", "copy from ", "copy to ", "GIT binary patch", "Binary files ")


class PatchNotApplied(subprocess.CalledProcessError):
    """The patch could not be checked, or ``patch`` exited 0 and left a tree the patch does not name."""

    def __init__(self, message: str, cmd: list[str] | None = None):
        super().__init__(1, cmd or ["patch"], output="", stderr=message)
        self.message = message

    def __str__(self) -> str:
        return self.message


def _name(field: str) -> str:
    """The path in a ``---``/``+++`` line, without its timestamp; quoted names are unquoted."""
    field = field.rstrip("\n")
    if field.startswith('"'):
        end = field.find('"', 1)
        while end != -1 and field[end - 1] == "\\":
            end = field.find('"', end + 1)
        if end == -1:
            raise PatchNotApplied(f"an unterminated quoted file name: {field}")
        return field[1:end].encode("latin-1", "backslashreplace").decode("unicode_escape")
    return field.split("\t", 1)[0].rstrip()


def _strip(name: str) -> str:
    """``-p1``: drop the first part of the path. Refuse a name that would leave the copy."""
    if name == NULL:
        return NULL
    if name.startswith("/"):
        raise PatchNotApplied(f"the patch names an absolute path: {name}")
    parts = PurePosixPath(name).parts
    rel = PurePosixPath(*parts[1:]) if len(parts) > 1 else None
    if rel is None or ".." in rel.parts or str(rel) in ("", "."):
        raise PatchNotApplied(f"the patch names a path this check cannot place in the game: {name}")
    return rel.as_posix()


def _header_at(lines: list[str], i: int) -> bool:
    """A file header is ``---``, ``+++`` and ``@@``: no hunk line starts with ``@``, so inside a hunk
    those three lines can only be the next file."""
    return (lines[i].startswith("--- ") and i + 2 < len(lines) and lines[i + 1].startswith("+++ ")
            and lines[i + 2].startswith("@@ "))


def files(text: str) -> dict[str, str]:
    """Each game-relative path the patch touches, mapped to ``create``, ``edit`` or ``delete``.

    Headers are read only between hunks; a hunk's lines are counted from its ``@@`` header, so a
    removed line that reads ``--- x`` is not taken for a file. A later entry for a path wins.
    """
    lines = text.splitlines()
    found: dict[str, str] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(UNREADABLE):
            raise PatchNotApplied(f"the patch has a change this check cannot follow: {line.strip()}")
        if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            old, new = _strip(_name(line[4:])), _strip(_name(lines[i + 1][4:]))
            if old == NULL and new == NULL:
                raise PatchNotApplied("the patch has an entry from /dev/null to /dev/null")
            path, kind = (old, "delete") if new == NULL else (new, "create" if old == NULL else "edit")
            found[path] = kind
            i += 2
            while i < len(lines) and (match := HUNK.match(lines[i])):
                want_old = int(match.group(1)) if match.group(1) is not None else 1
                want_new = int(match.group(2)) if match.group(2) is not None else 1
                i += 1
                while (want_old > 0 or want_new > 0) and i < len(lines):
                    body = lines[i]
                    if _header_at(lines, i):
                        break  # a hunk shorter than its header, then the next file: as patch reads it
                    tag = body[:1]
                    if tag in (" ", ""):
                        want_old, want_new = want_old - 1, want_new - 1
                    elif tag == "-":
                        want_old -= 1
                    elif tag == "+":
                        want_new -= 1
                    elif tag != "\\":
                        break  # trailing context cut short; patch decides whether the hunk still applies
                    if want_old < 0 or want_new < 0:
                        raise PatchNotApplied(f"a hunk for {path} has more lines than its header says")
                    i += 1
                while i < len(lines) and lines[i].startswith("\\"):
                    i += 1
            continue
        i += 1
    if not found:
        raise PatchNotApplied("the patch names no file")
    return found


def command(work: Path, patch: Path) -> list[str]:
    """The ``patch`` command ``apply`` runs, before its own check of the tree. ``tools.patch_controls``
    runs it alone on a scratch copy to record what the machine's program leaves (#659)."""
    return ["patch", "-p1", "--forward", "--batch", "-d", str(work), "-i", str(patch)]


def apply(work: Path, patch: Path) -> None:
    """Apply ``patch`` to the folder ``work`` and leave exactly the tree it names, or raise."""
    patch = Path(patch).resolve()
    text = patch.read_text(encoding="utf-8", errors="surrogateescape")
    if not text.strip():
        return  # an empty patch changes nothing, as `patch` itself treats it (an offline fixer's no-op)
    expected = files(text)
    cmd = command(work, patch)
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    for rel, kind in expected.items():
        target = Path(work) / rel
        if kind == "delete":
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise PatchNotApplied(f"{rel} is deleted by the patch but is still there, not as a file", cmd)
            if target.is_file():
                if target.stat().st_size:
                    raise PatchNotApplied(f"{rel} is deleted by the patch but is still there with content", cmd)
                target.unlink()  # macOS and POSIX patch keep the emptied file; the patch deletes it.
        elif not target.is_file() or target.is_symlink():
            verb = {"create": "created", "edit": "edited"}[kind]
            raise PatchNotApplied(f"{rel} is {verb} by the patch but is missing afterwards", cmd)
