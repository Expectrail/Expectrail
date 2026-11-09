"""Extract files from the commit the published results were recorded against.

The discovery freeze and the mutation bench's registration describe the code at commit c169a5e, the
baseline commit. Main moves on, so their tests check the records against an extract of that
commit instead of the working tree. A checkout without the commit (a shallow clone) skips those tests;
CI fetches it.
"""
from __future__ import annotations

import io
import subprocess
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMMIT = "c169a5e0da304773587304ed47bc8aabcec80da7"


def available(commit: str = COMMIT) -> bool:
    return subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", f"{commit}^{{commit}}"],
                          capture_output=True).returncode == 0


def extract(paths: list[str], commit: str = COMMIT) -> Path:
    """A temporary directory holding `paths` (files or directories) exactly as they are at `commit`."""
    archive = subprocess.run(["git", "-C", str(REPO), "archive", "--format=tar", commit, "--", *paths],
                             capture_output=True, check=True).stdout
    root = Path(tempfile.mkdtemp(prefix="expectrail-submission-"))
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(root, filter="data")
    return root
