"""The patch controls from #378 on this machine (#659): which `patch`, its version, and the tree it leaves.

    python3 -m tools.patch_controls [SUMMARY_FILE]

Three controls are applied to a fresh copy each time:

- ``delete``: a patch that deletes ``BUG`` (``+++ /dev/null``);
- ``empty-by-edit``: an edit that removes the last line of ``keep.txt``, which must stay as an empty file;
- ``both``: one patch that does both and creates ``new.txt``.

Each control is applied twice: with the raw ``patch -p1 --forward --batch`` command, to record what
this machine's program leaves, and through ``harness.patching.apply``, the rule every candidate goes
through. The record says the file state after each, and whether ``apply`` left the tree the patch
names. It is appended to SUMMARY_FILE (the job summary) when one is given, and printed.

It always exits 0: the macOS job reports and does not gate. A tree that does not match, or a missing
``patch`` program, is written as such, never as a pass.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from harness import patching

DELETE = "--- a/BUG\n+++ /dev/null\n@@ -1 +0,0 @@\n-1\n"
EMPTY = "--- a/keep.txt\n+++ b/keep.txt\n@@ -1 +0,0 @@\n-only line\n"
CREATE = "--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1 @@\n+hello\n"

CONTROLS = [
    {"name": "delete", "patch": DELETE, "expect": {"BUG": "absent"}},
    {"name": "empty-by-edit", "patch": EMPTY, "expect": {"keep.txt": "file, 0 bytes"}},
    {"name": "both", "patch": DELETE + EMPTY + CREATE,
     "expect": {"BUG": "absent", "keep.txt": "file, 0 bytes", "new.txt": "file, 6 bytes"}},
]


def state(path: Path) -> str:
    """What is at ``path``: ``absent``, ``file, N bytes`` or ``not a file``."""
    if path.is_symlink() or (path.exists() and not path.is_file()):
        return "not a file"
    if not path.exists():
        return "absent"
    return f"file, {path.stat().st_size} bytes"


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def program() -> dict:
    """The ``patch`` on PATH and the first line its version flag prints (``--version``, then ``-v``)."""
    path = shutil.which("patch")
    if not path:
        return {"path": None, "version": None}
    for flag in ("--version", "-v"):
        try:
            done = subprocess.run(["patch", flag], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        line = _first_line(done.stdout) or _first_line(done.stderr)
        if done.returncode == 0 and line:
            return {"path": path, "version": line}
    return {"path": path, "version": "the program printed no version"}


def _game(root: Path) -> Path:
    work = root / "game"
    work.mkdir()
    (work / "BUG").write_text("1\n")
    (work / "keep.txt").write_text("only line\n")
    return work


def _run(control: dict) -> dict:
    row = {"name": control["name"], "expect": dict(control["expect"]), "raw": None, "raw_exit": None,
           "applied": None, "error": None}
    with tempfile.TemporaryDirectory(prefix="expectrail-patch-controls-") as tmp:
        root = Path(tmp)
        patch = root / "control.patch"
        patch.write_text(control["patch"])
        (root / "raw").mkdir()
        raw = _game(root / "raw")
        # The same command `apply` runs, without its check: what this machine's program leaves.
        done = subprocess.run(patching.command(raw, patch), capture_output=True, text=True)
        row["raw_exit"] = done.returncode
        row["raw"] = {rel: state(raw / rel) for rel in control["expect"]}
        (root / "applied").mkdir()
        applied = _game(root / "applied")
        try:
            patching.apply(applied, patch)
        except patching.PatchNotApplied as exc:
            row["error"] = exc.message
        except subprocess.CalledProcessError as exc:
            said = _first_line("\n".join(reversed((f"{exc.stdout or ''}\n{exc.stderr or ''}").splitlines())))
            row["error"] = f"`patch` failed with exit {exc.returncode}" + (f": {said}" if said else "")
        row["applied"] = {rel: state(applied / rel) for rel in control["expect"]}
    row["matches"] = row["error"] is None and row["applied"] == row["expect"]
    return row


def run_all() -> dict:
    found = {"program": program(), "controls": []}
    if found["program"]["path"]:
        found["controls"] = [_run(control) for control in CONTROLS]
    found["all_match"] = bool(found["controls"]) and all(row["matches"] for row in found["controls"])
    return found


def _states(states: dict | None) -> str:
    return "; ".join(f"`{rel}` {s}" for rel, s in (states or {}).items()) or "not recorded"


def render(found: dict) -> str:
    lines = ["## Patch controls on this machine (#659)", ""]
    prog = found["program"]
    if not prog["path"]:
        lines.append("- There is no `patch` program on PATH, so no control was applied.")
        return "\n".join(lines) + "\n"
    lines.append(f"- `patch`: `{prog['path']}`")
    lines.append(f"- Version: `{prog['version']}`")
    lines.append("")
    for row in found["controls"]:
        verdict = "matches the patch" if row["matches"] else "does not match the patch"
        lines.append(f"- `{row['name']}`: {verdict}")
        lines.append(f"  - raw `patch` (exit {row['raw_exit']}): {_states(row['raw'])}")
        lines.append(f"  - through `harness.patching.apply`: {_states(row['applied'])}")
        if row["error"]:
            lines.append(f"  - stopped: {row['error']}")
        lines.append(f"  - the patch names: {_states(row['expect'])}")
    lines.append("")
    lines.append("- Every control left the named tree." if found["all_match"]
                 else "- At least one control does not match the patch.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    text = render(run_all())
    print(text, end="")
    if argv:
        with open(argv[0], "a", encoding="utf-8") as out:
            out.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
