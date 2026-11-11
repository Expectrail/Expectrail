"""The public reproduction bench: its defects and their reports, read strictly.

    python3 -m expectrail.repro check      # the bench reads strictly and every patch applies to a copy of the game

A defect is a patch against the clean game and a bug report in a player's words
(bench/jit/public/defects.json, ``expectrail.repro-bench/v1``). Everything here is public: reproduction
is developed on these defects only, never on a blind set. The file holds no result. What a defect
shows in the engine's record is measured by ``expectrail.repro.visibility``; whether the generator
reproduces it is measured by a live run, which this module does not start.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from expectrail.contracts import ContractError, strict_loads
from expectrail.jit.diff_map import PatchError, parse

REPO = Path(__file__).resolve().parents[2]
BENCH = REPO / "bench" / "jit" / "public" / "defects.json"
SCHEMA = REPO / "contracts" / "repro-bench.v1.schema.json"
FORMAT = "expectrail.repro-bench/v1"
MAX_BYTES = 256 * 1024
MAX_REPORT_BYTES = 4000


class BenchError(ValueError):
    """The bench file, or a file it names, cannot be used."""


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _inside(root: Path, rel: str) -> Path:
    """``root/rel``, refused when it is not a regular file inside ``root`` (a link out of it included)."""
    path = root / rel
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        raise BenchError(f"{rel}: outside the repository") from None
    if path.is_symlink() or not path.is_file():
        raise BenchError(f"{rel}: not a file in the repository")
    return path


def problems(doc, root: Path = REPO) -> list[str]:
    """What is wrong with a bench document, one line each: the schema first, then the files it names."""
    import jsonschema

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        return [f"repro-bench: {'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}"[:300] for e in errors[:10]]
    out: list[str] = []
    seen_ids: set[str] = set()
    seen_patches: dict[str, str] = {}
    game = root / doc["game"]
    for d in doc["defects"]:
        did = d["id"]
        if did in seen_ids:
            out.append(f"repro-bench: {did}: listed twice")
        seen_ids.add(did)
        try:
            patch = _inside(root, d["patch"])
            report = _inside(root, d["report"])
        except BenchError as exc:
            out.append(f"repro-bench: {did}: {exc}")
            continue
        digest = sha256(patch)
        if digest in seen_patches:
            out.append(f"repro-bench: {did}: the same patch as {seen_patches[digest]}")
        seen_patches[digest] = did
        raw = report.read_bytes()
        if not raw.strip() or len(raw) > MAX_REPORT_BYTES:
            out.append(f"repro-bench: {did}: the report is empty or over {MAX_REPORT_BYTES} bytes")
        try:
            files = parse(patch.read_text(encoding="utf-8"))
        except (PatchError, UnicodeDecodeError) as exc:
            out.append(f"repro-bench: {did}: the patch cannot be read ({exc})"[:300])
            continue
        if not files or not any(f["added"] or f["removed"] for f in files):
            out.append(f"repro-bench: {did}: the patch changes nothing")
        for f in files:
            if not (game / f["path"]).is_file():
                out.append(f"repro-bench: {did}: the patch names {f['path']!r}, which is not a file of the game")
    return out


def load(path: Path = BENCH, root: Path = REPO) -> dict:
    """The bench document, or BenchError with every problem found."""
    raw = Path(path).read_bytes()
    if len(raw) > MAX_BYTES:
        raise BenchError(f"repro-bench: over {MAX_BYTES} bytes")
    try:
        doc = strict_loads(raw.decode("utf-8"))
    except (ValueError, ContractError) as exc:
        raise BenchError(f"repro-bench: unreadable: {exc}"[:300]) from exc
    found = problems(doc, root)
    if found:
        raise BenchError("; ".join(found))
    return doc


def applies(defect: dict, root: Path = REPO, game: str = "game/platformer") -> str | None:
    """None when the defect's patch applies exactly to a copy of the game; otherwise why not.

    ``git apply --check`` on a copy outside any repository: nothing is written, the game itself is
    never touched, and no context line may be off (the harness's ``patch`` is more forgiving, so a
    patch that passes here applies there)."""
    with tempfile.TemporaryDirectory(prefix="expectrail-repro-") as tmp:
        work = Path(tmp) / "game"
        shutil.copytree(root / game, work, ignore=shutil.ignore_patterns(".godot"))
        git = shutil.which("git")
        if git is None:
            return "git is not installed, so the patch was not checked"
        # Its own small environment: git finds no repository above the copy and reads nobody's settings.
        env = {"PATH": os.defpath, "HOME": tmp, "GIT_CEILING_DIRECTORIES": str(Path(tmp).resolve()),
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        done = subprocess.run([git, "apply", "--check", "-p1", str((root / defect["patch"]).resolve())],
                              cwd=work, capture_output=True, text=True, env=env)
        if done.returncode != 0:
            return " ".join((done.stdout + done.stderr).split())[:300] or f"git apply exited {done.returncode}"
    return None


def families(doc: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in doc["defects"]:
        out[d["family"]] = out.get(d["family"], 0) + 1
    return dict(sorted(out.items()))
