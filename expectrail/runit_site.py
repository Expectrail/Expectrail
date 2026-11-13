"""What the Run it page reads besides a run's own folder (#265, slice 2).

- ``latest.json`` at the root of the ``run-it-results`` branch (``expectrail.run-it-latest/v1``): for
  each sample, the most recent published run. It is an index only. The page reads that run's own
  ``status.json`` for what the verifier decided, so this file never carries a verdict, and the page
  can show the latest run of each sample while the service that starts runs is switched off.
- The bodies the Run it service sends (``expectrail.run-it-api/v1``): the edge function (slice 3)
  and its local stand-in, ``tools/runit_stub.py``, speak the same contract.

    python3 -m expectrail.runit_site latest RESULTS REQUEST_ID

updates ``RESULTS/latest.json`` from ``RESULTS/REQUEST_ID/status.json``. The publish job runs it
after ``expectrail.runit check`` passed on the folder and before it commits.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from expectrail import runit
from expectrail.gate import record as rec

ROOT = Path(__file__).resolve().parent.parent
API_FORMAT = "expectrail.run-it-api/v1"
LATEST_FORMAT = "expectrail.run-it-latest/v1"
API_SCHEMA = "contracts/run-it-api.v1.schema.json"
LATEST_SCHEMA = "contracts/run-it-latest.v1.schema.json"
LATEST_NAME = "latest.json"
MAX_LATEST_BYTES = 64 * 1024


class SiteError(Exception):
    """A results folder or an index that cannot be used. Nothing was written."""


def _schema(name: str) -> dict:
    """Expectrail's own contract (never a copy beside the data being checked)."""
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def api_errors(doc) -> list[str]:
    """What is wrong with a body of the Run it service, by its contract (empty: nothing)."""
    return rec.errors(doc, _schema(API_SCHEMA))


def read_latest(results: Path) -> dict:
    """``results``/latest.json, checked against its schema; an empty index when there is none yet."""
    path = Path(results) / LATEST_NAME
    if not path.exists() and not path.is_symlink():
        return {"format": LATEST_FORMAT, "samples": {}}
    if path.is_symlink() or not path.is_file():
        raise SiteError(f"{LATEST_NAME} is not a regular file")
    try:
        doc = rec.read_json(path, MAX_LATEST_BYTES, LATEST_NAME)
    except rec.RecordError as exc:
        raise SiteError(str(exc)) from exc
    found = rec.errors(doc, _schema(LATEST_SCHEMA))
    if found:
        raise SiteError(f"{LATEST_NAME} does not match its schema: {found[0]}")
    return doc


def update_latest(results: Path, request_id: str, root: Path = ROOT) -> dict:
    """Make ``results``/``request_id`` the latest run of its sample in ``results``/latest.json.

    The folder's status.json must match its schema, name this request and a sample in the manifest
    under ``root`` (the repository; tests pass a copy).
    A run that finished before the one already listed for its sample leaves the index as it is.
    Returns the index as written (or as it stands)."""
    results = Path(results)
    if not runit.valid_id(request_id):
        raise SiteError("a request id is lower-case letters, digits and hyphens, at most 40")
    folder = results / request_id
    status_path = folder / "status.json"
    if folder.is_symlink() or not folder.is_dir() or status_path.is_symlink() or not status_path.is_file():
        raise SiteError(f"{request_id}/status.json is not there")
    try:
        status = rec.read_json(status_path, runit.MAX_STATUS_BYTES, "status.json")
    except rec.RecordError as exc:
        raise SiteError(str(exc)) from exc
    found = rec.errors(status, _schema(runit.RESULT_SCHEMA))
    if found:
        raise SiteError(f"status.json does not match its schema: {found[0]}")
    if status["requestId"] != request_id:
        raise SiteError("status.json names another request")
    try:
        runit.find_sample(runit.read_manifest(root), status["sample"]["id"])
    except runit.RunItError as exc:
        raise SiteError(str(exc)) from exc
    index = read_latest(results)
    sample = status["sample"]["id"]
    listed = index["samples"].get(sample)
    if listed is not None and listed["finishedAt"] > status["finishedAt"]:
        return index
    index["samples"][sample] = {"requestId": request_id, "finishedAt": status["finishedAt"]}
    found = rec.errors(index, _schema(LATEST_SCHEMA))
    if found:
        raise SiteError(f"the index would not match its schema: {found[0]}")
    tmp = results / f".{LATEST_NAME}.{os.getpid()}"
    tmp.write_text(json.dumps(index, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, results / LATEST_NAME)
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m expectrail.runit_site", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_latest = sub.add_parser("latest", help="list a published run as the latest of its sample")
    p_latest.add_argument("results", type=Path)
    p_latest.add_argument("request_id")
    args = parser.parse_args(argv)
    try:
        index = update_latest(args.results, args.request_id)
    except SiteError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(index, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
