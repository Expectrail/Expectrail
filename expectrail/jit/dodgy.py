"""Near-miss versions of a candidate patch ("dodgy diffs"): plausible wrong variants of the same change.

A generated check is only worth keeping if it tells the candidate apart from something close to it
that is wrong. Two kinds of variant, both deterministic and both built from the candidate's own lines:

- **operator**: the mutation bench's operators (agents/mutate_game.py: a constant's sign or scale, a
  comparison flipped, a negation dropped, a scene number moved, a collision bit flipped, a resource
  path broken), applied only to lines the candidate added. The steps are the ones the mutation
  bench registered (bench/mutation/preregistration.json, read and never written).
- **jit-operator**: three more, for code lines the bench's operators do not reach: a boolean literal
  flipped, an ``if``/``elif``/``while`` condition negated, a simple statement replaced by ``pass``.
  They are only used here; the mutation bench's generator is a registered record and is not changed.
- **partial-revert**: when the candidate changes more than one place, each place undone on its own
  while the others stay, the shape of a fix that is only half done.

Each variant is a unified diff to apply after the base patches and the candidate, so a replay of it
is ``patches=[*base, candidate, variant]``. Nothing in a patch is run here; the game copy is only read.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import random
import re
import shutil
import tempfile
from pathlib import Path

from expectrail.jit.diff_map import parse

DEFAULT_LIMIT = 8
SCENE_SUFFIXES = (".tscn",)
CODE_SUFFIXES = (".gd",)


def registered_steps(path: Path | None = None) -> dict:
    """The mutation bench's registered steps. Read only: that registration is a record (rule 6)."""
    from agents.mutate_game import PREREGISTRATION, STEPS

    doc = json.loads(Path(path or PREREGISTRATION).read_text(encoding="utf-8"))
    return {k: doc["generator"][k] for k in STEPS}


def _copy_game(game: Path, dest: Path) -> None:
    shutil.copytree(game, dest, ignore=shutil.ignore_patterns(".godot"))


def _apply(work: Path, patches: list[Path]) -> None:
    from harness.run import apply_patches

    apply_patches(work, patches)


def _diff(rel: str, before: list[str], after: list[str]) -> str:
    return "".join(difflib.unified_diff(before, after, fromfile=f"a/{rel}", tofile=f"b/{rel}"))


_BOOL = re.compile(r"\b(true|false)\b")
_COND = re.compile(r"^(\s*)(if|elif|while) (.+):\s*$")
_CONTROL = re.compile(r"^\s*(if|elif|else|while|for|func|match|class|static|@|const|var|signal|extends|#)\b|^\s*$")


def _jit_mutants(rel: str, n: int, line: str) -> list[dict]:
    """The code operators this generator adds for lines the bench's operators do not reach."""
    if not rel.endswith(CODE_SUFFIXES) or line.lstrip().startswith("#"):
        return []
    out = []

    def add(tag, after):
        out.append({"id": f"jit:{rel}:{n}:{tag}", "file": rel, "line": n, "before": line, "after": after})

    for i, m in enumerate(_BOOL.finditer(line)):
        add(f"bool.{i}", line[:m.start()] + ("false" if m.group(1) == "true" else "true") + line[m.end():])
    if m := _COND.match(line):
        add("negate", f"{m.group(1)}{m.group(2)} not ({m.group(3)}):")
    elif not _CONTROL.match(line):
        indent = line[: len(line) - len(line.lstrip())]
        add("delete", f"{indent}pass")
    return out


def _operator_mutants(rel: str, n: int, line: str, steps: dict) -> list[dict]:
    from agents import mutate_game as mg

    if rel.endswith(CODE_SUFFIXES):
        return mg._code_mutants(rel, n, line, steps)
    if rel.endswith(SCENE_SUFFIXES):
        return mg._scene_mutants(rel, n, line, steps)
    return []


def variants(game: Path, base_patches: list[Path], candidate: Path, *, steps: dict | None = None,
             limit: int = DEFAULT_LIMIT) -> list[dict]:
    """[{id, kind, file, line, patchText}], at most ``limit``, chosen by a seed taken from the candidate's
    own bytes so the same candidate always gives the same variants."""
    steps = steps if steps is not None else registered_steps()
    cand_bytes = Path(candidate).read_bytes()
    files = parse(cand_bytes.decode("utf-8", errors="replace"))
    found: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="jit-dodgy-") as tmp:
        pre, post = Path(tmp) / "pre", Path(tmp) / "post"
        _copy_game(game, pre)
        _apply(pre, list(base_patches))
        _copy_game(pre, post)
        _apply(post, [Path(candidate)])
        changed_places = []
        for f in files:
            rel = f["path"]
            post_file = post / rel
            if not post_file.is_file():
                continue
            post_lines = post_file.read_text(encoding="utf-8").splitlines(keepends=True)
            for n, _text in f["added"]:
                if not 1 <= n <= len(post_lines):
                    continue
                line = post_lines[n - 1].rstrip("\n")
                for kind, mutants in (("operator", _operator_mutants(rel, n, line, steps)),
                                      ("jit-operator", _jit_mutants(rel, n, line))):
                    for m in mutants:
                        if m["after"] == m["before"]:
                            continue
                        after = list(post_lines)
                        after[n - 1] = m["after"] + "\n"
                        found.append({"id": f"op:{m['id']}" if kind == "operator" else m["id"], "kind": kind,
                                      "file": rel, "line": n, "patchText": _diff(rel, post_lines, after)})
            pre_file = pre / rel
            pre_lines = pre_file.read_text(encoding="utf-8").splitlines(keepends=True) if pre_file.is_file() else []
            ops = [op for op in difflib.SequenceMatcher(a=pre_lines, b=post_lines, autojunk=False).get_opcodes()
                   if op[0] != "equal"]
            changed_places += [(rel, pre_lines, post_lines, op) for op in ops]
        if len(changed_places) > 1:
            for rel, pre_lines, post_lines, (_tag, i1, i2, j1, j2) in changed_places:
                after = post_lines[:j1] + pre_lines[i1:i2] + post_lines[j2:]
                found.append({"id": f"revert:{rel}:{j1 + 1}", "kind": "partial-revert", "file": rel,
                              "line": j1 + 1, "patchText": _diff(rel, post_lines, after)})
    seen, unique = set(), []
    for v in found:
        if v["patchText"] and v["patchText"] not in seen:
            seen.add(v["patchText"])
            unique.append(v)
    if len(unique) <= limit:
        return unique
    seed = int(hashlib.sha256(cand_bytes).hexdigest()[:16], 16)
    keep = sorted(random.Random(seed).sample(range(len(unique)), limit))
    return [unique[i] for i in keep]
