"""What a game folder holds: one definition, used by every digest of a game and by every copy a
replay runs.

A replay runs a copy of the game folder, and several records name the game by a digest of its
files: replay.json (``game.tree``), the gate's findings (``headTree``, ``baseTree``), the import
cache's key and a verification job's inputs. Until November 12, 2026 each of those walked the
folder its own way and the copy walked it a fifth way, so a file could be replayed without being in
the digest (behind a linked folder, or in a folder one of the lists skipped). Here there is one
walk. The digest is taken over ``files``; the copy holds exactly ``files``; so the digest changes
exactly when the copy does. ``copy`` also returns the digest of the bytes it wrote, so a replay can
name the copy it ran and stop when the folder changed after it was first read.

The rules, for every engine:

- Links are followed, and what they lead to is part of the game under the link's own path.
- A link may not leave ``within`` (the game folder itself unless a wider folder is given, such as
  the checkout). One that does, one that loops back into its own folder and one that leads nowhere
  are a ``TreeProblem``: never followed, never left out quietly.
- Anything that is not a file, a folder or a link (a pipe, a socket, a device) is a ``TreeProblem``.
- Names in ``skip`` are not part of the game at any depth, as files or as folders. For Godot they
  are ``.godot`` (the engine's own cache, rebuilt from the game) and ``.git`` (version control).
- An empty folder is not part of the game: no digest has ever covered one, so the copy does not
  hold one either.
- Order is by path, part by part, so it does not depend on the Python version or the file system.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

GODOT_SKIP = (".godot", ".git")


class TreeProblem(ValueError):
    """The game folder cannot be described or copied as it stands."""


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def files(root: Path, *, within: Path | None = None, skip: tuple[str, ...] = ()) -> list[tuple[str, Path]]:
    """Every file of the game at ``root`` as (path inside the game with ``/``, file to read), sorted.
    Nothing outside ``within`` is opened."""
    limit = os.path.realpath(root if within is None else within)
    left_out = set(skip)
    found: list[tuple[str, Path]] = []

    def walk(folder: str, inside: str, above: tuple[str, ...]) -> None:
        real = os.path.realpath(folder)
        if not _inside(real, limit):
            raise TreeProblem(f"{inside or '.'} is a link that leaves the {'game folder' if within is None else 'checkout'}")
        if real in above:
            raise TreeProblem(f"{inside or '.'} is a link that loops back into its own folder")
        with os.scandir(folder) as entries:
            for entry in sorted(entries, key=lambda e: e.name):
                if entry.name in left_out:
                    continue
                name = f"{inside}/{entry.name}" if inside else entry.name
                if entry.is_symlink() and not _inside(os.path.realpath(entry.path), limit):
                    raise TreeProblem(f"{name} is a link that leaves the {'game folder' if within is None else 'checkout'}")
                if entry.is_dir():
                    walk(entry.path, name, above + (real,))
                elif entry.is_file():
                    found.append((name, Path(entry.path)))
                elif entry.is_symlink():
                    raise TreeProblem(f"{name} is a link to nothing")
                else:
                    raise TreeProblem(f"{name} is not a file, a folder or a link")

    walk(str(root), "", ())
    return sorted(found, key=lambda item: item[0].split("/"))


def digest(root: Path, *, within: Path | None = None, skip: tuple[str, ...] = ()) -> str:
    """The digest of the game at ``root``: for each file in order, its path, a NUL, the sha256 of its
    bytes and a newline."""
    h = hashlib.sha256()
    for name, path in files(root, within=within, skip=skip):
        h.update(name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).hexdigest().encode() + b"\n")
    return h.hexdigest()


def copy(root: Path, dest: Path, *, within: Path | None = None, skip: tuple[str, ...] = ()) -> str:
    """Copy the game at ``root`` into the new folder ``dest``: exactly the files ``files`` lists, each
    as a plain file with its mode and times. ``dest`` must not exist.

    Returns the digest of the bytes it wrote, in ``digest``'s form: each file is read once, and what
    was hashed is what was written. So a caller that took ``digest`` earlier can tell whether the game
    changed in between, and a record can name the copy that ran and not a later reading of the folder."""
    listed = files(root, within=within, skip=skip)   # the whole walk first: a problem copies nothing
    dest = Path(dest)
    dest.mkdir(parents=True)
    h = hashlib.sha256()
    for name, path in listed:
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        target.write_bytes(data)
        shutil.copystat(path, target)
        h.update(name.encode() + b"\0" + hashlib.sha256(data).hexdigest().encode() + b"\n")
    return h.hexdigest()
