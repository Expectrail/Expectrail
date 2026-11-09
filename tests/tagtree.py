"""Extract files from the tag the published results were recorded against.

The discovery freeze and the mutation bench's registration describe the code at the tag `submission`
(c169a5e). Main moves on, so their tests check the records against an extract of that tag instead of
the working tree. A checkout without the tag (a shallow clone) skips those tests; CI fetches it.
"""
from __future__ import annotations

import io
import subprocess
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TAG = "submission"


def tag_available(tag: str = TAG) -> bool:
    return subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", f"{tag}^{{commit}}"],
                          capture_output=True).returncode == 0


def extract(paths: list[str], tag: str = TAG) -> Path:
    """A temporary directory holding `paths` (files or directories) exactly as they are at `tag`."""
    archive = subprocess.run(["git", "-C", str(REPO), "archive", "--format=tar", tag, "--", *paths],
                             capture_output=True, check=True).stdout
    root = Path(tempfile.mkdtemp(prefix="expectrail-tag-"))
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(root, filter="data")
    return root
