"""Extract files from the commit the published results were recorded against.

The discovery freeze and the mutation bench's registration describe the code at commit c169a5e, the
baseline commit. Main moves on, so their tests check the records against an extract of that
commit instead of the working tree. A checkout without the commit (a shallow clone) skips those tests;
CI fetches it.
"""
from __future__ import annotations

import atexit
import io
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMMIT = "c169a5e0da304773587304ed47bc8aabcec80da7"


def available(commit: str = COMMIT) -> bool:
    return subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", f"{commit}^{{commit}}"],
                          capture_output=True).returncode == 0


_EXTRACTED: list[Path] = []


@atexit.register
def _remove_extracted() -> None:
    """Remove what `extract` made. Its callers keep the folder for the length of a test and do not own
    a cleanup hook, and a suite run was leaving one behind per call."""
    while _EXTRACTED:
        shutil.rmtree(_EXTRACTED.pop(), ignore_errors=True)


def extract(paths: list[str], commit: str = COMMIT) -> Path:
    """A temporary directory holding `paths` (files or directories) exactly as they are at `commit`.

    The folder is removed at interpreter exit, so a suite run leaves nothing behind."""
    archive = subprocess.run(["git", "-C", str(REPO), "archive", "--format=tar", commit, "--", *paths],
                             capture_output=True, check=True).stdout
    root = Path(tempfile.mkdtemp(prefix="expectrail-submission-"))
    _EXTRACTED.append(root)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(root, filter="data")
    return root
