"""Merge guard check: the rules in AGENTS.md that a diff can break and a program can see.

    python3 -m tools.merge_guard --base SHA --head SHA [--body-file FILE] [--json]

It compares ``head`` with the commit where it left ``base`` and prints one line per reason, each
starting with the label the merge guard agent applies: ``needs-sean`` for what only a person may
do, ``changes-requested`` for what the builder must fix. Exit 0 with nothing to report, 1 with
reasons, 2 when the diff could not be read. The pull request's description comes from
``--body-file`` or the ``MERGE_GUARD_PR_BODY`` environment variable.

Standard library only, so the job that runs it installs nothing.

A workflow is read line by line, not parsed. What that reading cannot follow is reported rather than
passed: a job written as a flow mapping, a ``\\x``, ``\\u`` or ``\\U`` escape anywhere in the file, and
a quoted string that runs past the end of its line.

What it does not see: a test loosened without being skipped; a skip moved from one test to another
in the same file (skips are counted per file, added less removed); a skip whose name is not written
out (built with ``getattr`` or from pieces, or split over two lines); a ``load_tests`` that returns
no tests, or a test that returns before it asserts; a test method removed or renamed so that it no
longer runs; a file that is not Python deleted under ``tests/``; a new trigger (such as
``workflow_run``) on a workflow that already holds a secret; an ``approval`` in a JSON file outside
a ``specs`` or ``contracts`` folder; a new file that agents read as instructions (an ``AGENTS.md``
in a subfolder, a ``CLAUDE.md``) or the audit's own configuration; the private repository named
with no path after it, or a held-out name put together from pieces; whether a claim in the
description has a run behind it; and the contents of held-out files (it never reads them; the
private scan does that with the private set). On a ``pull_request`` run the workflow, this file
and its tests come from the pull request itself, so a change to any of them is reported as
``needs-sean`` and the merge guard agent should run main's copy.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

NEEDS_SEAN = "needs-sean"
CHANGES = "changes-requested"

GAME_DIRS = ("game/platformer/", "game/unity-platformer/")
BASELINE = ".github/obaaf-baseline.json"
RULE_FILES = ("AGENTS.md", ".github/CODEOWNERS")
GUARD_FILES = ("tools/merge_guard.py", "tools/__init__.py", ".github/workflows/merge-guard.yml",
               "tests/test_merge_guard.py")
NEW_WORK = "docs/new-work.md"
INTENDED = re.compile(r"^Guard: test change intended \(#\d+\)\s*$", re.M)
# An HTML comment in a description does not show on the page, so a line inside one is not a statement.
_HTML_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.S)
MAX_BYTES = 4 * 1024 * 1024

# Skips: unittest's decorators and calls, and pytest's, as they appear on a line of a test file.
_SKIP_NAMES = r"(?:skip|skipIf|skipUnless|skipif|expectedFailure|xfail|SkipTest|skipTest)"
_SKIP = re.compile(
    # any dotted name that ends in one: unittest.skip, an alias such as u.skip, pytest.mark.skipif, self.skipTest
    r"\.\s*" + _SKIP_NAMES + r"\b"
    # a bare decorator, a bare raise, and the import that makes either possible
    r"|@\s*" + _SKIP_NAMES + r"\b"
    r"|\braise\s+SkipTest\b"
    r"|^\s*from\s+(?:unittest|pytest)(?:\.\w+)*\s+import\b.*\b" + _SKIP_NAMES + r"\b"
    # one name of a parenthesised import, on a line of its own: "skip as later,"
    r"|^\s*" + _SKIP_NAMES + r"(?:\s+as\s+\w+)?\s*[,)]\s*$"
    r"|__unittest_skip__")
# A path under any fresh set, the third set by name, or a path inside the private repository.
_HELD_OUT = re.compile(r"\bfresh-[0-9]+/|\bfresh-[3]\b|Expectrail-heldout/[\w.]", re.I)
_APPROVAL_LINE = re.compile(r"""["']?approval["']?\s*[:=]""")
# Any use of the secrets context. The name is read where there is one (secrets.NAME, secrets['NAME']);
# every other use (secrets.*, toJSON(secrets), format('{0}', secrets), secrets[matrix.key],
# secrets: inherit) can reach all of them.
_SECRETS = re.compile(r"(?<![.\w-])secrets\b(?![\w-])", re.I)
_SECRET_NAME = re.compile(r"\s*(?:\.\s*([A-Za-z_][A-Za-z0-9_-]*)|\[\s*['\"]([^'\"]+)['\"]\s*\])")
_EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.S)
_IF_LINE = re.compile(r"^\s*(?:-\s*)?if\s*:.*$", re.M)


def secret_names(text: str) -> set[str]:
    """The secrets a piece of a workflow can reach; ``(every secret)`` when a use names none."""
    spans = [m.span() for m in _EXPRESSION.finditer(text)] + [m.span() for m in _IF_LINE.finditer(text)]
    names: set[str] = set()
    for m in _SECRETS.finditer(text):
        rest = text[m.end():]
        named = _SECRET_NAME.match(rest)
        if named:
            names.add(named.group(1) or named.group(2))
        elif re.match(r"\s*[.\[]", rest) or re.match(r"\s*:\s*inherit\b", rest):
            names.add("(every secret)")
        elif any(a <= m.start() < b for a, b in spans):
            names.add("(every secret)")
    return {n for n in names if n.upper() != "GITHUB_TOKEN"}


_LEVEL = {"none": 0, "read": 1, "write": 2}


@dataclass(frozen=True)
class Change:
    """One file of the diff. ``old`` is None for an added file, ``new`` is None for a deleted one."""
    path: str
    old: str | None
    new: str | None

    @property
    def added(self) -> list[str]:
        return _lines(self, "+")

    @property
    def removed(self) -> list[str]:
        return _lines(self, "-")


@dataclass(frozen=True)
class Reason:
    label: str
    rule: str
    path: str
    message: str

    def line(self) -> str:
        return f"{self.label}: {self.rule}: {self.path}: {self.message}"


def _lines(change: Change, sign: str) -> list[str]:
    old = (change.old or "").splitlines()
    new = (change.new or "").splitlines()
    out = []
    for line in difflib.ndiff(old, new) if len(old) * len(new) < 4_000_000 else _plain(old, new):
        if line.startswith(sign + " "):
            out.append(line[2:])
    return out


def _plain(old: list[str], new: list[str]):
    """A cheap diff for very large files: lines only one side has."""
    olds, news = set(old), set(new)
    yield from ("- " + l for l in old if l not in news)
    yield from ("+ " + l for l in new if l not in olds)


# --- approvals -------------------------------------------------------------------------------

def _is_spec_or_contract(path: str) -> bool:
    return bool({"specs", "contracts"} & set(path.split("/")[:-1]))


def _approvals(text: str | None) -> dict[str, str] | None:
    """Every ``approval`` in a JSON document, by where it is; None when the text is not JSON."""
    if text is None:
        return {}
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    found: dict[str, str] = {}

    def walk(node, where: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                here = f"{where}/{key}"
                if key == "approval":
                    found[here] = json.dumps(value, sort_keys=True)
                walk(value, here)
        elif isinstance(node, list):
            for n, value in enumerate(node):
                walk(value, f"{where}/{n}")

    walk(doc, "")
    return found


def check_approvals(changes: list[Change]) -> list[Reason]:
    out = []
    for c in changes:
        if not _is_spec_or_contract(c.path):
            continue
        old, new = _approvals(c.old), _approvals(c.new)
        if old is None or new is None:
            if any(_APPROVAL_LINE.search(l) for l in c.added + c.removed):
                out.append(Reason(NEEDS_SEAN, "approval", c.path, "a line that sets an approval was added or removed"))
            continue
        for where in sorted(set(old) | set(new)):
            if old.get(where) == new.get(where):
                continue
            what = "added" if where not in old else "removed" if where not in new else "changed"
            out.append(Reason(NEEDS_SEAN, "approval", c.path, f"approval {what} at {where or '/'}; only a person approves a check"))
    return out


# --- the game, the rules, the guard itself, the baseline ---------------------------------------

def check_paths(changes: list[Change]) -> list[Reason]:
    out = []
    for c in changes:
        if c.path.startswith(GAME_DIRS):
            out.append(Reason(CHANGES, "game", c.path, "the game is never edited; a seeded bug or a fix is a patch"))
        if c.path in RULE_FILES:
            out.append(Reason(NEEDS_SEAN, "rules", c.path, "only a person changes the rules"))
        if c.path in GUARD_FILES and c.old is not None:
            what = "deleted" if c.new is None else "changed"
            out.append(Reason(NEEDS_SEAN, "guard", c.path, f"the merge guard check was {what}; a person reviews that"))
    return out


def _fingerprints(text: str | None) -> set[str] | None:
    if text is None:
        return set()
    try:
        findings = json.loads(text)["findings"]
        return {json.dumps(f.get("fingerprint", f), sort_keys=True) if isinstance(f, dict) else json.dumps(f)
                for f in findings}
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def check_baseline(changes: list[Change]) -> list[Reason]:
    for c in changes:
        if c.path != BASELINE or c.new is None:
            continue
        old, new = _fingerprints(c.old), _fingerprints(c.new)
        if old is None or new is None:
            if [l for l in c.added if l.strip()]:
                return [Reason(NEEDS_SEAN, "baseline", c.path, "lines were added and the file could not be read as a baseline")]
        elif new - old:
            return [Reason(NEEDS_SEAN, "baseline", c.path, f"{len(new - old)} finding(s) added to the accepted baseline")]
    return []


# --- workflows -------------------------------------------------------------------------------

def _strip_comment(line: str) -> str:
    quote = ""
    for n, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (n == 0 or line[n - 1] in " \t"):
            return line[:n].rstrip()
    return line.rstrip()


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _key(line: str) -> str | None:
    m = re.match(r"""\s*["']?([A-Za-z0-9_.-]+)["']?\s*:(?:\s|$)""", line)
    return m.group(1) if m else None


def _blocks(lines: list[str]) -> dict[str, list[str]]:
    """Split lines into blocks by the keys at their smallest indent. Each block keeps its key line."""
    lines = [l for l in lines if l.strip()]
    if not lines:
        return {}
    base = min(_indent(l) for l in lines)
    out: dict[str, list[str]] = {}
    current = None
    for line in lines:
        if _indent(line) == base and not line.lstrip().startswith("- ") and _key(line):
            current = _key(line)
            out[current] = [line]
        elif current is not None:
            out[current].append(line)
    return out


def _permissions(block: list[str] | None) -> dict[str, int] | None:
    """A permissions block as scope -> level, ``*`` for every scope not named. None when absent."""
    if block is None:
        return None
    text = "\n".join(block)
    inline = block[0].split(":", 1)[1].strip().strip("'\"")
    if inline == "write-all":
        return {"*": 2}
    if inline == "read-all":
        return {"*": 1}
    perms = {"*": 0}
    for scope, level in re.findall(r"""([a-z-]+)["']?\s*:\s*["']?(read|write|none)\b""", text.split(":", 1)[1]):
        perms[scope] = _LEVEL[level]
    return perms


def _level(perms: dict[str, int] | None, scope: str) -> int:
    if perms is None:
        return 2  # no block: the token gets the repository's default, which may write
    return perms.get(scope, perms["*"])


@dataclass
class Job:
    text: str
    environment: str
    perms: dict[str, int] | None

    @property
    def secrets(self) -> set[str]:
        return secret_names(self.text)

    @property
    def id_token(self) -> bool:
        named = re.search(r"id-token[\"']?\s*:\s*[\"']?write\b", self.text)
        return bool(named) or (self.perms is not None and _level(self.perms, "id-token") == 2)


_ENVIRONMENT_KEY = re.compile(r"""(?<![\w.-])["']?environment["']?\s*:""")
_WRITE_VALUE = re.compile(r""":\s*["']?(?:write|write-all)\b""")
_ID_TOKEN = re.compile(r"""id-token["']?\s*:\s*["']?write\b""")


def unread_jobs(text: str | None) -> list[str]:
    """Jobs (or the whole ``jobs`` map) whose value starts on the key's own line, as a flow mapping does."""
    if text is None:
        return []
    lines = [_strip_comment(l).replace("\t", "    ") for l in text.splitlines()]
    block = _blocks(lines).get("jobs")
    if block is None:
        return []
    if block[0].split(":", 1)[1].strip():
        return ["the jobs map"]
    out = []
    for name, job in _blocks(block[1:]).items():
        if job[0].split(":", 1)[1].strip():
            out.append(f"job {name}")
    return out


# YAML decodes these inside a double-quoted string, so "env\x69ronment" is a key the patterns never see.
_ESCAPE = re.compile(r"\\(?:x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8})")
# The line that opens a block scalar: "run: |", "- >-", "script: |2+".
_BLOCK_HEADER = re.compile(r"""^(?P<lead>\s*(?:-\s+)*)(?:(?:[A-Za-z0-9_.-]+|"[^"\\]*"|'[^']*')\s*:\s+)?[|>][+-]?[1-9]?[+-]?\s*$""")


def escapes(text: str | None) -> int:
    """How many ``\\x``, ``\\u`` and ``\\U`` escapes the text holds, wherever they are."""
    return len(_ESCAPE.findall(text or ""))


def open_strings(text: str | None) -> int:
    """How many quoted strings, outside block scalars, are still open where their line ends.

    Such a string can hold a ``#`` line the reader takes for a comment, or join two halves of a word
    with a backslash at the line's end. The text of a block scalar (``run: |``) is not looked at: it
    is literal, and a shell script may quote as it likes.
    """
    count = 0
    block = None  # inside a block scalar: the column its text must be indented past
    quote = ""
    for raw in (text or "").splitlines():
        line = raw.replace("\t", "    ")
        if not quote:
            if block is not None:
                if not line.strip() or _indent(line) > block:
                    continue
                block = None
            header = _BLOCK_HEADER.match(_strip_comment(line))
            if header:
                block = len(header.group("lead"))
                continue
        n = 0
        while n < len(line):
            ch = line[n]
            if quote == '"':
                if ch == "\\":
                    n += 1
                elif ch == '"':
                    quote = ""
            elif quote == "'":
                if ch == "'":
                    if line[n + 1:n + 2] == "'":
                        n += 1
                    else:
                        quote = ""
            elif ch == "#" and (n == 0 or line[n - 1] == " "):
                break
            elif ch in "'\"" and (n == 0 or line[n - 1] in " {[,:"):
                quote = ch
            n += 1
        if quote:
            count += 1
    return count


def parse_workflow(text: str | None) -> tuple[dict[str, Job], str]:
    """The jobs of a workflow with what each can reach, and the file without comments.

    Anything outside ``jobs`` (workflow-level ``env``, ``permissions``) counts toward every job, and
    is also kept as the pseudo-job ``(workflow)`` so a secret added there is seen.
    """
    if text is None:
        return {}, ""
    lines = [_strip_comment(l).replace("\t", "    ") for l in text.splitlines()]
    plain = "\n".join(lines)
    top = _blocks(lines)
    workflow_perms = _permissions(top.get("permissions"))
    outside = "\n".join(l for key, block in top.items() if key not in ("jobs", "permissions") for l in block)
    jobs = {"(workflow)": Job(outside, "", None)}
    for name, block in _blocks(top.get("jobs", [])[1:]).items():
        keys = _blocks(block[1:])
        perms = _permissions(keys.get("permissions"))
        environment = " ".join(" ".join(l.split()) for l in keys.get("environment", []))
        jobs[name] = Job("\n".join(block), environment, perms if perms is not None else workflow_perms)
    return jobs, plain


def check_workflows(changes: list[Change]) -> list[Reason]:
    out = []
    for c in changes:
        if not re.match(r"\.github/workflows/[^/]+\.ya?ml$", c.path) or c.new is None:
            continue
        old_jobs, old_plain = parse_workflow(c.old)
        new_jobs, new_plain = parse_workflow(c.new)

        def reason(message: str) -> None:
            out.append(Reason(NEEDS_SEAN, "workflow", c.path, message))

        if new_plain.count("pull_request_target") > old_plain.count("pull_request_target"):
            reason("pull_request_target was added")
        # Fail closed: a job written as a flow mapping ({...}) is not split into its keys, so say so.
        for name in unread_jobs(c.new):
            reason(f"{name} is written as a flow mapping, which the guard does not read; a person reads it")
        # Fail closed again: an escape can spell any word the patterns look for, and a string that runs
        # over a line can hide one. Neither is read; both are counted against what the file had.
        if escapes(c.new) > escapes(c.old):
            reason("the file gains an escaped character (\\x, \\u or \\U), which the guard does not read; a person reads it")
        if open_strings(c.new) > open_strings(c.old):
            reason("the file gains a quoted string that runs over a line, which the guard does not read; a person reads it")
        before_reasons = len(out)
        for name, job in new_jobs.items():
            before = old_jobs.get(name)
            where = "the workflow" if name == "(workflow)" else f"job {name}"
            gained = job.secrets - (before.secrets if before else set())
            if gained:
                reason(f"{where} gains secrets: {', '.join(sorted(gained))}")
            if job.environment and job.environment != (before.environment if before else ""):
                reason(f"{where} gains or changes an environment")
            if job.id_token and not (before and before.id_token):
                reason(f"{where} gains id-token: write")
            if name == "(workflow)":
                continue  # its permissions are judged through each job's effective permissions
            if before is None:
                # A new job may read. Anything it may write, or a token left at the default, is wider.
                if job.perms is None:
                    reason(f"new {where} has no permissions block, so its token gets the repository default")
                else:
                    wide = sorted(s for s, level in job.perms.items() if level == 2)
                    if wide:
                        reason(f"new {where} may write: {', '.join('every scope' if s == '*' else s for s in wide)}")
                continue
            scopes = set(job.perms or {"*": 0}) | set(before.perms or {"*": 0})
            wider = sorted(s for s in scopes if _level(job.perms, s) > _level(before.perms, s))
            if job.perms is None and before.perms is not None:
                reason(f"{where} lost its permissions block, so its token gets the repository default")
            elif wider:
                reason(f"{where} gets wider permissions: {', '.join('every other scope' if s == '*' else s for s in wider)}")
        # Backstop: whatever the file as a whole gains must be accounted for by a reason above.
        said = " ".join(r.message for r in out[before_reasons:])
        gained = secret_names(new_plain) - secret_names(old_plain)
        unsaid = sorted(n for n in gained if n not in said)
        if unsaid:
            reason(f"the file gains secrets no job accounts for: {', '.join(unsaid)}")
        for pattern, words, what in ((_ENVIRONMENT_KEY, ("environment",), "an environment"),
                                     (_WRITE_VALUE, ("permissions", "may write", "id-token"), "a write permission"),
                                     (_ID_TOKEN, ("id-token",), "id-token: write")):
            if len(pattern.findall(new_plain)) > len(pattern.findall(old_plain)) and not any(w in said for w in words):
                reason(f"the file gains {what} that no job accounts for")
    return out


# --- tests -----------------------------------------------------------------------------------

def _is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return path.endswith(".py") and (path.startswith("tests/") or "/tests/" in path or name.startswith("test_"))


def check_tests(changes: list[Change], body: str) -> list[Reason]:
    if INTENDED.search(_HTML_COMMENT.sub("", body or "")):
        return []
    hint = "; if intended, the description needs the line \"Guard: test change intended (#issue)\""
    out = []
    for c in changes:
        if not _is_test(c.path):
            continue
        if c.new is None:
            out.append(Reason(CHANGES, "tests", c.path, "a test file was deleted" + hint))
            continue
        more = sum(1 for l in c.added if _SKIP.search(l)) - sum(1 for l in c.removed if _SKIP.search(l))
        if more > 0:
            out.append(Reason(CHANGES, "tests", c.path, f"{more} line(s) that skip a test or expect it to fail were added" + hint))
    return out


# --- held-out material -------------------------------------------------------------------------

def check_held_out(changes: list[Change]) -> list[Reason]:
    out = []
    for c in changes:
        if c.new is None:
            continue
        hits = sum(1 for l in c.added if _HELD_OUT.search(l))
        if not hits:
            continue
        if c.path.endswith(".md") and c.old is not None and _HELD_OUT.search(c.old):
            continue  # a doc that already names them
        # The count only: a guard that printed the line would repeat what it was meant to keep out.
        out.append(Reason(NEEDS_SEAN, "held-out", c.path, f"{hits} added line(s) name a fresh set or a path in the private repository"))
    return out


# --- the work log ------------------------------------------------------------------------------

def _is_code(path: str) -> bool:
    return not (path.endswith(".md") or path.startswith("docs/") or path.startswith(".github/ISSUE_TEMPLATE/"))


def check_new_work(changes: list[Change]) -> list[Reason]:
    code = sorted(c.path for c in changes if _is_code(c.path))
    if not code:
        return []
    for c in changes:
        if c.path == NEW_WORK and any(l.lstrip().startswith("|") and l.count("|") >= 4 for l in c.added):
            return []
    return [Reason(CHANGES, "new-work", NEW_WORK, f"{len(code)} file(s) outside the docs changed and no row was added (first: {code[0]})")]


def check(changes: list[Change], body: str = "") -> list[Reason]:
    """Every reason this diff may not merge as it stands, in a fixed order."""
    return (check_approvals(changes) + check_paths(changes) + check_baseline(changes) + check_workflows(changes)
            + check_tests(changes, body) + check_held_out(changes) + check_new_work(changes))


def labels(reasons: list[Reason]) -> list[str]:
    return sorted({r.label for r in reasons})


# --- git ---------------------------------------------------------------------------------------

class GuardError(RuntimeError):
    pass


def _git(repo: Path, *args: str) -> bytes:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if done.returncode:
        raise GuardError(f"git {' '.join(args)}: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout


def _show(repo: Path, rev: str, path: str) -> str:
    try:
        raw = _git(repo, "show", f"{rev}:{path}")
    except GuardError:
        return ""  # a submodule or a path git cannot show as a file
    return raw[:MAX_BYTES].decode("utf-8", "replace")


def read_changes(repo: Path, base: str, head: str) -> list[Change]:
    """The files that differ between ``head`` and the commit where it left ``base``."""
    fork = _git(repo, "merge-base", base, head).decode().strip()
    names = _git(repo, "diff", "--name-status", "--no-renames", "-z", fork, head).decode("utf-8", "replace").split("\0")
    out = []
    for status, path in zip(names[0::2], names[1::2]):
        old = None if status.startswith("A") else _show(repo, fork, path)
        new = None if status.startswith("D") else _show(repo, head, path)
        out.append(Change(path, old, new))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="the commit or branch the pull request targets")
    parser.add_argument("--head", required=True, help="the pull request's head commit")
    parser.add_argument("--body-file", help="a file holding the pull request's description")
    parser.add_argument("--repo", default=".", help="the repository (default: the current directory)")
    parser.add_argument("--json", action="store_true", help="print the reasons and the labels as JSON")
    args = parser.parse_args(argv)
    body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else os.environ.get("MERGE_GUARD_PR_BODY", "")
    try:
        changes = read_changes(Path(args.repo), args.base, args.head)
    except GuardError as err:
        print(f"merge guard: {err}", file=sys.stderr)
        return 2
    reasons = check(changes, body)
    if args.json:
        print(json.dumps({"files": len(changes), "labels": labels(reasons),
                          "reasons": [r.__dict__ for r in reasons]}, indent=2))
    else:
        for r in reasons:
            print(r.line())
        if reasons:
            print(f"merge guard: {len(reasons)} reason(s) in {len(changes)} file(s); labels: {', '.join(labels(reasons))}")
        else:
            print(f"merge guard: nothing to report in {len(changes)} file(s)")
    return 1 if reasons else 0


if __name__ == "__main__":
    sys.exit(main())
