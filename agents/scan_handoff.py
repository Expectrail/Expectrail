"""The private scan's hand-off: a pull request's files arrive as data and are proved to be that commit's.

    python3 -I agents/scan_handoff.py unpack --archive files.tar --repo OWNER/NAME --sha SHA --out scanned
    python3 -I agents/scan_handoff.py report --repo OWNER/NAME --sha SHA --status success --run-url URL

`private-scan.yml` runs from main after `private-scan-collect.yml` finishes on a pull request
(workflow_run). The collector runs the pull request's own copy of its workflow, so nothing it
uploads is trusted. `unpack` therefore asks GitHub for the commit's tree and writes a file only
when its bytes hash to the blob the tree names. It fails, writing nothing it keeps, when:

- a file in the archive is not in the commit under the scanned paths, or differs from it;
- a file in the commit under the scanned paths is missing from the archive (so nothing can be held
  back from the scan);
- the archive holds a link, a device or a path that leaves the folder;
- the tree is truncated, or the archive is over the size limits.

Nothing from the pull request is imported or run: the archive is read with `tarfile` as bytes, and
this file needs only the standard library, so the workflow runs it in Python's isolated mode.
`report` posts the scan's result as a check run on the pull request's head commit. It says passed
or failed and links to the run; it never carries what the scan found.

Not covered: Git LFS (the pointer file is what is hashed and scanned) and submodules (not scanned;
the old checkout did not scan them either).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath

# The paths the scan reads (the arguments of agents.export_scan in private-scan.yml and ci.yml).
ROOTS = ("bench", "docs", "apps", "README.md")
MAX_FILES = 20_000
MAX_BYTES = 256 * 1024 * 1024
CHECK_NAME = "private-export-scan"
_SHA = re.compile(r"[0-9a-f]{40}")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_FILE_MODES = {"100644", "100755"}
_CONCLUSIONS = {"success": "success", "failure": "failure", "cancelled": "cancelled"}


class HandoffError(Exception):
    """The archive is not the commit's files, or cannot be read safely."""


def blob_sha(data: bytes) -> str:
    """Git's name for a file with these bytes."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def scanned(path: str) -> bool:
    return any(path == root or path.startswith(root + "/") for root in ROOTS)


def expected(tree: dict) -> dict[str, str]:
    """Path to blob sha for every file the commit has under the scanned paths."""
    if tree.get("truncated"):
        raise HandoffError("GitHub truncated the commit's tree, so the archive cannot be checked against it")
    entries = tree.get("tree")
    if not isinstance(entries, list):
        raise HandoffError("the commit's tree could not be read")
    out: dict[str, str] = {}
    for entry in entries:
        path = str(entry.get("path") or "")
        if not scanned(path):
            continue
        if entry.get("type") == "blob" and entry.get("mode") in _FILE_MODES:
            out[path] = str(entry.get("sha"))
        elif entry.get("type") == "blob":
            raise HandoffError("the commit has a link under the scanned paths; a person reads it")
    return out


def _safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if name.startswith("/") or "\\" in name or "\0" in name or ".." in path.parts or not path.parts:
        raise HandoffError("the archive holds a path that leaves the folder")
    return path.as_posix()


def unpack(archive: Path, tree: dict, out: Path) -> int:
    """Write the archive's files under `out` if they are exactly the commit's; return how many."""
    want = expected(tree)
    out = Path(out)
    if out.exists():
        raise HandoffError(f"{out} already exists")
    seen: set[str] = set()
    total = 0
    try:
        with tarfile.open(archive, mode="r:") as tar:
            for member in tar:
                if member.isdir():
                    continue
                if not member.isreg():
                    raise HandoffError("the archive holds something that is not a plain file")
                name = _safe_name(member.name)
                if name in seen:
                    raise HandoffError("the archive holds a file twice")
                if name not in want:
                    raise HandoffError("the archive holds a file the commit does not have under the scanned paths")
                seen.add(name)
                total += member.size
                if len(seen) > MAX_FILES or total > MAX_BYTES:
                    raise HandoffError("the archive is over the size limits")
                data = tar.extractfile(member).read()
                if blob_sha(data) != want[name]:
                    raise HandoffError("a file in the archive differs from the commit's")
                target = out / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        missing = len(set(want) - seen)
        if missing:
            raise HandoffError(f"{missing} file(s) of the commit are missing from the archive")
    except (tarfile.TarError, OSError) as error:
        shutil.rmtree(out, ignore_errors=True)
        raise HandoffError(f"the archive could not be read ({type(error).__name__})") from None
    except HandoffError:
        shutil.rmtree(out, ignore_errors=True)
        raise
    out.mkdir(parents=True, exist_ok=True)
    return len(seen)


def _check_ids(repo: str, sha: str) -> None:
    if not _REPO.fullmatch(repo):
        raise HandoffError("not a repository name")
    if not _SHA.fullmatch(sha):
        raise HandoffError("not a full commit id")


def _call(url: str, token: str, body: dict | None = None, opener=urllib.request.urlopen) -> dict:
    request = urllib.request.Request(
        url, data=None if body is None else json.dumps(body).encode(), method="GET" if body is None else "POST",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "expectrail-private-scan"})
    with opener(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _api() -> str:
    return os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")


def fetch_tree(repo: str, sha: str, token: str, opener=urllib.request.urlopen) -> dict:
    _check_ids(repo, sha)
    return _call(f"{_api()}/repos/{repo}/git/trees/{sha}?recursive=1", token, opener=opener)


def check_run(sha: str, status: str, run_url: str) -> dict:
    """The check posted on the pull request's head. Anything but a clean success is not a pass."""
    conclusion = _CONCLUSIONS.get(status, "failure")
    passed = conclusion == "success"
    return {
        "name": CHECK_NAME, "head_sha": sha, "status": "completed", "conclusion": conclusion,
        "details_url": run_url,
        "output": {
            "title": "Nothing from the private set, and no key, in this commit's files" if passed
            else "The private scan did not pass",
            "summary": (f"Main's scanner read this commit's `bench`, `docs`, `apps` and `README.md` as data "
                        f"and compared them with the private set. Result: {conclusion}. "
                        f"File names and counts are in the run's log: {run_url}"),
        },
    }


def post_check(repo: str, sha: str, status: str, run_url: str, token: str, opener=urllib.request.urlopen) -> dict:
    _check_ids(repo, sha)
    return _call(f"{_api()}/repos/{repo}/check-runs", token, check_run(sha, status, run_url), opener=opener)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    u = sub.add_parser("unpack", help="check the archive against the commit and write its files")
    u.add_argument("--archive", type=Path, required=True)
    u.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("report", help="post the result as a check run on the commit")
    r.add_argument("--status", required=True, help="the job's status: success, failure or cancelled")
    r.add_argument("--run-url", required=True)
    for s in (u, r):
        s.add_argument("--repo", required=True)
        s.add_argument("--sha", required=True)
    args = p.parse_args(argv)
    token = os.environ.get("GH_TOKEN", "")
    try:
        if args.command == "unpack":
            if not args.archive.is_file():
                raise HandoffError("no archive arrived from the pull request's run")
            count = unpack(args.archive, fetch_tree(args.repo, args.sha, token), args.out)
            print(f"::notice title=Private scan::{count} file(s) match commit {args.sha}")
        else:
            post_check(args.repo, args.sha, args.status, args.run_url, token)
            print(f"::notice title=Private scan::reported {args.status} on {args.sha}")
    except HandoffError as error:
        print(f"::error title=Private scan::{error}")
        return 1
    except OSError as error:  # the API refused or could not be reached; never print a response body
        print(f"::error title=Private scan::GitHub's API call failed ({type(error).__name__})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
