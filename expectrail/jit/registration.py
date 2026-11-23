"""Read and write the public registration for the release verifier measurement."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path, PurePosixPath

import jsonschema

from expectrail.contracts import ContractError, SCHEMAS, canonical_v1, strict_loads


FORMAT = "expectrail.blind-registration/v2"
SCHEMA = SCHEMAS / "blind-registration.v2.schema.json"


def _timestamp(value: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(value.upper().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("registration timestamps must include a valid date and time") from exc
    if stamp.utcoffset() is None:
        raise ContractError("registration timestamps must include a time zone")
    return stamp


def _verify_pin_paths(files: dict) -> None:
    by_path = {}
    for group in files.values():
        for name, digest in group.items():
            path = PurePosixPath(name)
            if (not path.parts or path.is_absolute() or ".." in path.parts or path.as_posix() != name
                    or ":" in name or "\\" in name or any(ord(char) < 32 for char in name)):
                raise ContractError("pin paths must be canonical repo-relative paths")
            if by_path.setdefault(name, digest) != digest:
                raise ContractError("a file has conflicting registration pins")


def validate(doc: dict, *, require_registered: bool = False) -> None:
    """Check shape and consistency without opening the set or checking pinned files."""
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ContractError(f"registration is out of format. Expected {FORMAT}")
    canonical_v1(doc)
    schema = strict_loads(SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    error = next(validator.iter_errors(doc), None)
    if error is not None:
        field = "/".join(map(str, error.absolute_path)) or "registration"
        raise ContractError(f"{field} does not satisfy the registration schema ({error.validator})")
    if any(name != name.strip() for name in doc["strata"]["projects"]):
        raise ContractError("project ids must match the manifest's project names without whitespace")
    pins, budget = doc["pins"], doc["budget"]
    _verify_pin_paths(pins["files"])
    sam, total = budget["samUsd"], budget["totalUsd"]
    if sam is not None and total is not None and sam > total:
        raise ContractError("SAM budget exceeds the total budget")
    window = doc["runWindow"]
    if window and _timestamp(window["start"]) >= _timestamp(window["end"]):
        raise ContractError("run window must end after it starts")
    if doc["status"] == "draft":
        if doc["signOff"] is not None:
            raise ContractError("a draft cannot carry a recorded sign-off")
        if require_registered:
            raise ContractError("this operation requires a registered record")
        return
    sign_off = doc["signOff"]
    if not sign_off or not sign_off["by"].strip():
        raise ContractError("a registered record requires a recorded sign-off")
    if not window or _timestamp(sign_off["at"]) >= _timestamp(window["start"]):
        raise ContractError("sign-off must be recorded before the run window")
    if any(value is None for value in doc["thresholds"].values()):
        raise ContractError("a registered record requires all thresholds")
    if sam is None or total is None:
        raise ContractError("a registered record requires the budget caps")
    if not pins["commit"] or not pins["setManifestSha256"] or not all(pins["files"].values()):
        raise ContractError("a registered record requires the commit, set digest and all groups of file pins")


def read(path: Path, *, require_registered: bool = False) -> dict:
    doc = strict_loads(path.read_text(encoding="utf-8"))
    validate(doc, require_registered=require_registered)
    return doc


def write(path: Path, doc: dict) -> None:
    """Write canonical JSON to a new path, preserving the caller's decisions."""
    validate(doc)
    data = canonical_v1(doc)
    with path.open("xb") as output:
        output.write(data)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="validate the public registration")
    check.add_argument("registration", type=Path)
    check.add_argument("--require-registered", action="store_true")
    save = commands.add_parser("write", help="write a validated canonical copy to a new file")
    save.add_argument("registration", type=Path)
    save.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        doc = read(args.registration, require_registered=getattr(args, "require_registered", False))
        if args.command == "write":
            write(args.output, doc)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"{exc}\n")
    print(f"Registration format valid ({doc['status']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
