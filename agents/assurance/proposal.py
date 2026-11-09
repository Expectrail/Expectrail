"""Turn a candidate fix into an OBAAF proposal bundle, and check it with OBAAF.

A candidate is a game-relative unified diff made against the seeded game (``player/player.tscn``),
applied with ``patch -p1`` inside ``game/platformer``. OBAAF's proposal checker wants a Git diff
relative to the repository root (``game/platformer/player/player.tscn``), and it is right to: the
path it checks is the path a pull request would change. Rewriting the patch's headers would be
guessing. Instead this materializes the base, a disposable repository cloned from this
repository's committed HEAD with the seeded defect committed on top, applies the candidate to a
second clone of that base, and asks Git for the diff (``git diff --no-renames``). Nothing here runs
game code: patches are applied to files, never replayed.

Two rule sets apply, and both must pass:

- OBAAF's (``obaaf proposal check --repo``): no workflow, instruction or OBAAF file, no symlink or
  submodule, no rename, at most 100 paths and 1,000,000 bytes, applied again to a temporary index of
  the base. ``PROTECT`` adds Expectrail's own trust boundary to its protected paths: the verifier,
  harness, evaluator, contracts, specs, tests, benchmarks and seeded bugs.
- Expectrail's (``editable``): every changed path must sit under the game root and match the
  request's editable globs. OBAAF's list says what may never change; this one says what may.

The bundle holds only ``patch.diff`` and ``meta.json`` (untrusted notes, never acted on). The
verification report, frames and records are separate artifacts: OBAAF refuses any other file in a
bundle, and evidence must not travel inside the thing it is evidence about.

    python3 -m agents.assurance.proposal --seed bugs/physics-fall-through/v1.patch \\
        --candidate agents/fixtures/fix-collision-mask.patch --out runs/proposal

needs ``obaaf`` on PATH (or ``OBAAF_BIN``), installed from the reviewed revision in ``OBAAF_REVISION``.

The game root and the default editable files come from an engine adapter (harness/adapters.py,
default ``godot``); the root must sit inside the repository, since the base is a clone of it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from agents.patchutil import apply_patches, path_allowed, sha256_file
from harness import adapters
from harness.adapters import Adapter
from harness.run import REPO


def game_root(adapter: str | Adapter = "godot") -> str:
    """The adapter's game root, relative to the repository (Godot: ``game/platformer``)."""
    root = adapters.resolve(adapter).game_root
    if not root.is_relative_to(REPO):
        raise ProposalError(f"the game root {root} is outside the repository, so no proposal can change it")
    return root.relative_to(REPO).as_posix()


# The OBAAF commit this integration was reviewed against (integration spec, section 10).
OBAAF_REVISION = "ef34304214923953cf7d67343b912385d4ce5906"
# Expectrail's trust boundary, added to OBAAF's protected paths: a fix may never change what judges it.
PROTECT = ["agents/**", "harness/**", "expectrail/**", "contracts/**", "specs/**", "tests/**", "bench/**",
           "bugs/**", "requirements*.txt"]
DEFAULT_EDITABLE = list(adapters.get("godot").editable)  # game-relative, as agents/matrix.py
# Fixed identity and dates, so the same inputs always give the same commits and trees.
_GIT_ENV = {"GIT_AUTHOR_NAME": "expectrail", "GIT_AUTHOR_EMAIL": "expectrail@invalid",
            "GIT_COMMITTER_NAME": "expectrail", "GIT_COMMITTER_EMAIL": "expectrail@invalid",
            "GIT_AUTHOR_DATE": "2026-10-30T00:00:00Z", "GIT_COMMITTER_DATE": "2026-10-30T00:00:00Z",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}


class ProposalError(Exception):
    """The candidate could not be turned into a proposal (it does not apply, or changes nothing)."""


GAME_ROOT = game_root("godot")


def _git(args: list[str], cwd: Path) -> str:
    env = dict(os.environ, **_GIT_ENV, HOME=str(cwd))  # no user config, hooks or credentials
    proc = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args],
                          cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise ProposalError(f"git {' '.join(args[:2])} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def materialize_base(work: Path, seeds: list[Path], source: Path = REPO, adapter: str | Adapter = "godot") -> dict:
    """A disposable repository: ``source``'s committed HEAD, with the seeded defect committed on top.

    Benchmark lineage only: the base is a fixture, never the clean main branch, and nothing here is
    ever pushed. For a production task the base would be a real committed failing revision.
    """
    work = Path(work).resolve()  # git runs from inside it, so a relative path would not resolve
    base = work / "base"
    if base.exists():
        shutil.rmtree(base)
    _git(["clone", "--quiet", "--depth", "1", "--no-hardlinks", f"file://{source.resolve()}", str(base)], work)
    head = _git(["rev-parse", "HEAD"], base).strip()
    if seeds:
        apply_patches(base / game_root(adapter), seeds)
        _git(["add", "--all"], base)
        _git(["commit", "--quiet", "--no-verify", "-m", "seeded defect (benchmark fixture)"], base)
    return {"path": str(base), "sourceCommit": head, "commit": _git(["rev-parse", "HEAD"], base).strip(),
            "tree": _git(["rev-parse", "HEAD^{tree}"], base).strip(),
            "seedPatchSha256": [sha256_file(p) for p in seeds]}


def normalize(candidate: Path, seeds: list[Path], out: Path, source: Path = REPO,
              adapter: str | Adapter = "godot") -> dict:
    """Write ``out/proposal/`` (patch.diff, meta.json) for a game-relative candidate; return its record."""
    out = Path(out).resolve()
    candidate = Path(candidate).resolve()
    out.mkdir(parents=True, exist_ok=True)
    base = materialize_base(out, seeds, source, adapter)
    cand = out / "candidate-tree"
    if cand.exists():
        shutil.rmtree(cand)
    _git(["clone", "--quiet", "--no-hardlinks", base["path"], str(cand)], out)
    try:
        apply_patches(cand / game_root(adapter), [candidate])
    except (subprocess.CalledProcessError, OSError) as exc:
        raise ProposalError(f"the candidate does not apply to the seeded game: {exc}") from exc
    return bundle_from_tree(cand, base, out, {"candidatePatchSha256": sha256_file(candidate)}, adapter)


def bundle_from_tree(cand: Path, base: dict, out: Path, extra: dict | None = None,
                     adapter: str | Adapter = "godot") -> dict:
    """The proposal for whatever changed in ``cand`` (a clone of the base) since the base commit."""
    _git(["add", "--all"], cand)
    diff = _git(["diff", "--cached", "--no-renames", "--full-index", "--binary", base["commit"]], cand)
    if not diff.strip():
        raise ProposalError("the candidate changes nothing")
    tree = _git(["write-tree"], cand).strip()
    proposal = out / "proposal"
    if proposal.exists():
        shutil.rmtree(proposal)
    proposal.mkdir()
    (proposal / "patch.diff").write_text(diff, encoding="utf-8")
    # Untrusted notes: OBAAF never acts on meta.json, and neither does anything here.
    (proposal / "meta.json").write_text(json.dumps({"lineage": "benchmark", "note": "normalized from a "
                                                    "game-relative candidate; see the record beside the bundle"},
                                                   indent=2) + "\n", encoding="utf-8")
    record = {
        "format": "expectrail.proposal-normalization/v0",
        "mode": "audit",  # Phase A: reporting only, authorizes nothing
        "lineage": "benchmark",
        "gameRoot": game_root(adapter),
        "base": {k: v for k, v in base.items() if k != "path"},
        "candidateTree": tree,
        "patchFileSha256": sha256_file(proposal / "patch.diff"),
        "bundleDigest": bundle_digest(proposal),
        "changedPaths": changed_paths(diff),
        **(extra or {}),
    }
    (out / "normalization.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def bundle_digest(proposal: Path) -> str:
    """OBAAF's digest of a bundle: sha256 of the sorted [name, sha256] list as canonical JSON.

    The same definition as obaaf.attest.proposal.bundle_digest; check() passes it to OBAAF as
    --expect-digest, so a drift between the two is a refused proposal, not a silent mismatch.
    """
    listing = sorted([f.relative_to(proposal).as_posix(), sha256_file(f)]
                     for f in proposal.rglob("*") if f.is_file() and not f.is_symlink())
    data = json.dumps(listing, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def changed_paths(diff: str) -> list[str]:
    """Repository-relative paths in a ``git diff`` (both sides of each header), sorted, unique."""
    paths = set()
    for line in diff.splitlines():
        if line.startswith("diff --git a/") and " b/" in line:
            a, _, b = line[len("diff --git a/"):].partition(" b/")
            paths.update({a, b})
    return sorted(paths)


def editable_problems(paths: list[str], editable: list[str], root: str = GAME_ROOT) -> list[str]:
    """Expectrail's own rule: every changed path under the game root, matching an editable glob."""
    problems = []
    prefix = root + "/"
    for path in paths:
        if not path.startswith(prefix):
            problems.append(f"{path} is outside the game root {root}/")
        elif not path_allowed(path[len(prefix):], editable):
            problems.append(f"{path} is not in the editable files ({', '.join(editable)})")
    return problems


def obaaf_bin() -> str | None:
    return os.environ.get("OBAAF_BIN") or shutil.which("obaaf")


def obaaf_check(bundle: Path, base: Path, protect: list[str] | None = None, digest: str | None = None) -> dict:
    """``obaaf proposal check --repo base --json`` with Expectrail's protected paths; its JSON report."""
    exe = obaaf_bin()
    if not exe:
        raise ProposalError(f"obaaf is not installed (install OBAAF at {OBAAF_REVISION}, or set OBAAF_BIN)")
    cmd = [exe, "proposal", "check", str(bundle), "--repo", str(base), "--json"]
    if digest:
        cmd += ["--expect-digest", digest]
    for glob in PROTECT if protect is None else protect:
        cmd += ["--protect", glob]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    try:
        report = json.loads(proc.stdout)
    except ValueError as exc:
        raise ProposalError(f"obaaf proposal check gave no JSON (exit {proc.returncode}): "
                            f"{(proc.stderr or proc.stdout).strip()[:300]}") from exc
    report["exit"] = proc.returncode
    return report


def check(out: Path, record: dict, editable: list[str] | None = None, adapter: str | Adapter = "godot") -> dict:
    """Both rule sets over the bundle in ``out``; writes and returns ``out/proposal-check.json``.

    The game root is the one the record was normalized against; ``editable`` defaults to the
    adapter's default editable files."""
    out = Path(out).resolve()
    obaaf = obaaf_check(out / "proposal", out / "base", digest=record["bundleDigest"])
    own = editable_problems(record["changedPaths"], editable or list(adapters.resolve(adapter).editable),
                            record.get("gameRoot") or game_root(adapter))
    result = {
        "format": "expectrail.proposal-check/v0",
        "mode": "audit",
        "obaafRevision": OBAAF_REVISION,
        "obaaf": {"ok": bool(obaaf.get("ok")) and obaaf["exit"] == 0, "problems": obaaf.get("problems", [])},
        "editable": {"ok": not own, "problems": own},
        "ok": bool(obaaf.get("ok")) and obaaf["exit"] == 0 and not own,
        "patchFileSha256": record["patchFileSha256"],
        "bundleDigest": record["bundleDigest"],
    }
    (out / "proposal-check.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--candidate", type=Path, required=True, help="game-relative candidate patch")
    p.add_argument("--seed", type=Path, action="append", default=[], help="seeded defect patch (repeatable)")
    p.add_argument("--editable", action="append", help="game-relative editable glob (default: the matrix's)")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        record = normalize(args.candidate, args.seed, args.out)
        result = check(args.out, record, args.editable)
    except ProposalError as exc:
        print(f"proposal: {exc}", file=sys.stderr)
        return 2
    verdict = "passes" if result["ok"] else "is refused"
    print(f"proposal {verdict}: {len(record['changedPaths'])} path(s); "
          + "; ".join(result["obaaf"]["problems"] + result["editable"]["problems"])[:500])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
