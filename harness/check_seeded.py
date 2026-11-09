"""Replay every seeded bug and fail if any of them leaves the picture unchanged.

    python3 -m harness.check_seeded [--route harness/routes/smoke.json] [--out runs/seeded-check]
                                    [--only physics-fall-through/v2 ...]
    python3 -m harness.check_seeded --adapter web --out runs/seeded-check-web

A seeded variant whose frames are identical to the clean game is not a bug anyone could see, not a
player and not SAM, so the benchmark would count it as a miss it can never catch. This renders the
clean route once, then each variant in <bugs>/<family>/v*.patch on the same route, and compares frame
hashes. Writes <out>/summary.json and exits 1 if any variant changes no frame.

The adapter (default godot) replays the route and says where its seeded bugs are and which route to
use when none is given: bugs/ and the smoke route for Godot, apps/checkout/bugs/ and the desktop
session for the web page.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness import adapters
from harness.adapters import Adapter, sha256_file
from harness.run import REPO


def seeded_patches(only: list[str] | None = None, bugs: Path | None = None) -> list[Path]:
    patches = sorted((bugs or REPO / "bugs").glob("*/v*.patch"))
    if only:
        wanted = {name.removesuffix(".patch") for name in only}
        patches = [p for p in patches if f"{p.parent.name}/{p.stem}" in wanted]
        missing = wanted - {f"{p.parent.name}/{p.stem}" for p in patches}
        if missing:
            raise SystemExit(f"no such seeded variant: {', '.join(sorted(missing))}")
    return patches


def fingerprint(adapter: Adapter, out: Path) -> dict:
    """What a replay in ``out`` showed: the sha256 of each frame, in order, and of its trace."""
    return {"frameSha256": [sha256_file(f) for f in adapter.frames(out)],
            "trace": {"sha256": sha256_file(out / "trace.json")}}


def compare(clean: dict, variant: dict) -> dict:
    a, b = clean["frameSha256"], variant["frameSha256"]
    differing = sum(1 for x, y in zip(a, b) if x != y) + abs(len(a) - len(b))
    return {
        "frames": len(b),
        "framesDifferingFromClean": differing,
        "traceDiffersFromClean": clean["trace"]["sha256"] != variant["trace"]["sha256"],
    }


def _shown(patch: Path) -> str:
    return patch.relative_to(REPO).as_posix() if patch.is_relative_to(REPO) else patch.as_posix()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--adapter", choices=adapters.names(), default="godot",
                   help="the engine whose seeded bugs to replay (default godot)")
    p.add_argument("--route", type=Path, help="default: the adapter's default route (Godot: harness/routes/smoke.json)")
    p.add_argument("--out", type=Path, default=REPO / "runs" / "seeded-check")
    p.add_argument("--only", nargs="*", help="limit to family/vN names")
    args = p.parse_args(argv)
    adapter = adapters.get(args.adapter)
    route = args.route or adapter.default_route

    patches = seeded_patches(args.only, adapter.bugs)
    adapter.run(route, args.out / "clean")
    clean = fingerprint(adapter, args.out / "clean")
    rows = []
    for patch in patches:
        name = f"{patch.parent.name}/{patch.stem}"
        out = args.out / name.replace("/", "_")
        adapter.run(route, out, [patch])
        row = {"variant": name, "patch": _shown(patch), **compare(clean, fingerprint(adapter, out))}
        row["visible"] = row["framesDifferingFromClean"] > 0
        rows.append(row)
        status = "ok" if row["visible"] else "INVISIBLE"
        print(f"{status:9} {name}: {row['framesDifferingFromClean']}/{row['frames']} frames differ from clean"
              f"{', trace differs' if row['traceDiffersFromClean'] else ''}")

    summary = {
        "format": "expectrail.seeded-check/v0",
        "route": route.name,
        "variants": rows,
        "ok": all(r["visible"] for r in rows),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if not summary["ok"]:
        bad = ", ".join(r["variant"] for r in rows if not r["visible"])
        print(f"seeded variants with no visible change: {bad}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
