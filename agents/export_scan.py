"""Scan what is about to leave a run, or the public repository, for material that must not.

    python3 -m agents.export_scan keep/ --private heldout-set       # a run's artifacts, before upload
    python3 -m agents.export_scan bench docs README.md apps         # the public repository

Errors (exit 1):
- key-like strings (Meta, OpenAI-style, GitHub, Slack, AWS keys) and private key blocks;
- a signing key file, or an image from the private routes;
- with the private set: a private route's name, a held-out variant's description, or a line a
  held-out patch (the game's, or the checkout page's under web/) adds that neither the clean game,
  the clean page nor any public patch in this repository contains
  (a line a public bug or fixture also adds is public already, so finding it leaks nothing).
Warnings: a machine's home path (/Users/<name>/, /home/<name>/), which says nothing private but has
no place in an export; --paths error makes them errors.

Findings name the file and count what was found. They never print the matched text: a scan that
printed a private route's name would leak it into the log it was meant to protect. Held-out ids
(``layering/v5``), counts and verdicts may leave, and are not flagged.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from harness import adapters
from harness.adapters import Adapter
from harness.run import REPO

SECRETS = re.compile(
    r"\b(?:msk|ghp|gho|ghs|github_pat|xox[abp])[-_A-Za-z0-9]{12,}"
    r"|\bsk-[A-Za-z0-9_-]{20,}"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----")
MACHINE_PATH = re.compile(r"(?:/Users/|/home/(?!runner/))[A-Za-z0-9._-]+/|[A-Z]:\\Users\\[^\\\s]+\\")
IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm"}
GAME_TEXT = set(adapters.get("godot").text_suffixes)  # .tscn .tres .gd .godot .cfg .import
MAX_BYTES = 8 * 1024 * 1024
MIN_LINE = 12  # shorter patch lines ("}", "z_index = 1") say little and match too much


def _clean_game_lines(adapter: str | Adapter = "godot") -> set[str]:
    """Every line of the adapter's clean project, read from the files with its text suffixes."""
    adapter = adapters.resolve(adapter)
    lines: set[str] = set()
    for path in adapter.game_root.rglob("*"):
        if path.suffix in adapter.text_suffixes and path.is_file():
            lines.update(l.strip() for l in path.read_text(encoding="utf-8", errors="replace").splitlines())
    return lines


def _clean_page_lines() -> set[str]:
    """The second domain's clean page (apps/checkout/site): its own lines are public."""
    return _clean_game_lines("web")


PUBLIC_PATCHES = ("bugs", "agents/fixtures", "apps/checkout/bugs", "apps/checkout/candidates")


def _public_patch_lines() -> set[str]:
    """Every line a patch published in this repository adds: the public bugs, fixes and fixtures."""
    lines: set[str] = set()
    for folder in PUBLIC_PATCHES:
        for path in (REPO / folder).rglob("*.patch"):
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    lines.add(line[1:].strip())
    return lines


def private_items(root: Path) -> dict[str, list[str]]:
    """What must not leave, read from the private set's manifest: route names, variant
    descriptions, and the lines each held-out patch adds that the clean game does not have."""
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    names: set[str] = set()
    for route in manifest.get("routes") or []:
        names.add(str(route.get("name") or Path(route["file"]).stem))
        names.add(Path(route["file"]).stem)
        names.add(str(route["file"]))
    descriptions: set[str] = set()
    for item in (manifest.get("variants") or []) + (manifest.get("routes") or []):
        text = " ".join(str(item.get("description") or "").split())
        if len(text) >= MIN_LINE:
            descriptions.add(text)
            descriptions.update(s.strip() for s in re.split(r"(?<=[.;:])\s+", text) if len(s.strip()) >= 24)
    clean = _clean_game_lines() | _clean_page_lines() | _public_patch_lines()
    added: set[str] = set()
    web = root / "web" / "manifest.json"
    web_variants = json.loads(web.read_text(encoding="utf-8")).get("variants") or [] if web.is_file() else []
    for variant, base in [(v, root) for v in manifest.get("variants") or []] + [(v, root / "web") for v in web_variants]:
        patch = base / str(variant.get("patch") or "")
        if not patch.is_file():
            continue
        for line in patch.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                body = line[1:].strip()
                if len(body) >= MIN_LINE and body not in clean:
                    added.add(body)
    return {"route names": sorted(n for n in names if n), "variant descriptions": sorted(descriptions),
            "patch lines": sorted(added)}


def _count(text: str, items: dict[str, list[str]]) -> dict[str, int]:
    counts = {}
    for kind, values in items.items():
        if kind == "route names":
            n = sum(1 for v in values if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(v)}(?![A-Za-z0-9_-])", text))
        else:
            n = sum(1 for v in values if v in text)
        if n:
            counts[kind] = n
    return counts


def _files(paths: list[Path]):
    for path in paths:
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from sorted(p for p in path.rglob("*") if p.is_file() and ".git" not in p.parts)


def scan(paths: list[Path], *, private: dict[str, list[str]] | None = None, paths_level: str = "warning",
         base: Path | None = None) -> list[dict]:
    """Findings: {level, file, what, count}. Never the matched text."""
    findings: list[dict] = []
    base = base or Path.cwd()

    def rel(p: Path) -> str:
        try:
            return str(p.resolve().relative_to(base.resolve()))
        except ValueError:
            return p.name

    for path in _files(paths):
        lowered = str(path).lower()
        if "signing-key" in path.name and not path.name.endswith(".pub"):
            findings.append({"level": "error", "file": rel(path), "what": "a signing key file", "count": 1})
            continue
        if path.suffix.lower() in IMAGES:
            if "held-out" in lowered or "heldout" in lowered:
                findings.append({"level": "error", "file": rel(path), "what": "an image from the private routes",
                                 "count": 1})
            continue
        if path.stat().st_size > MAX_BYTES:
            continue
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        text = data.decode("utf-8", errors="replace")
        secrets = len(SECRETS.findall(text))
        if secrets:
            findings.append({"level": "error", "file": rel(path), "what": "key-like strings", "count": secrets})
        if private:
            for kind, n in _count(text, private).items():
                findings.append({"level": "error", "file": rel(path), "what": f"private {kind}", "count": n})
        homes = len(MACHINE_PATH.findall(text))
        if homes:
            findings.append({"level": paths_level, "file": rel(path), "what": "machine home paths", "count": homes})
    return findings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("paths", type=Path, nargs="+")
    p.add_argument("--private", type=Path, help="a checkout of the private set (manifest.json, routes/, bugs/)")
    p.add_argument("--paths", dest="paths_level", choices=("warning", "error"), default="warning",
                   help="how to report machine home paths")
    args = p.parse_args(argv)
    private = None
    if args.private is not None:
        if (args.private / "manifest.json").is_file():
            private = private_items(args.private)
        else:
            print("::warning title=Export scan::no private set here, so only keys, files and paths were checked")
    findings = scan(args.paths, private=private, paths_level=args.paths_level)
    for f in findings:
        print(f"::{f['level']} title=Export scan::{f['file']}: {f['count']} {f['what']}")
    errors = sum(f["level"] == "error" for f in findings)
    files = sum(1 for _ in _files(args.paths))
    print(f"::notice title=Export scan::{files} files: {errors} error(s), {len(findings) - errors} warning(s)"
          + ("; compared with the private set" if private else ""))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
