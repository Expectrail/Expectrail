"""Which live workflow steps may reach a capped model sender without that role's cap (#267).

Since #267 every model role's sender holds against its own cap before it sends:
``EXPECTRAIL_SAM_USD_CAP`` for vision, and ``EXPECTRAIL_{GLIMMER,MUSE,TRIAGE,SPEC}_USD_CAP`` for
the others (``expectrail.spend.CAP_ENV``). A sender with no cap sends nothing and says why. So a
live workflow step that reaches a sender without setting its cap spends runner time and measures
nothing. Builder two found this by ``grep`` on #267; this reads it from the code.

For every step of a job that runs in a protected environment (only those jobs get a key), it finds
the Python the step starts: ``python -m MODULE``, ``python path/to/file.py``, the ``expectrail``
command, and inline Python given with ``-c`` or as a here-document. It follows the repository's own
imports from there, every ``import`` in a file wherever it is written, ``importlib.import_module``
with a literal name, and any string that names one of the repository's modules (how a module
starts another with ``python -m``). A role whose sender is in that closure "may be reached".

This is a static over-approximation, and it says so: "may reach" is not "sends". Where it cannot
follow a start (``python -m "$module"``, a script it cannot read or parse) it reports "cannot tell"
for that step, never "no gap".

A cap counts as set only from outside the step's script: the workflow's, the job's or the step's
``env`` naming it with a value that is not literally empty (a value such as ``${{ inputs.cap }}`` is
known only at run time and counts; the sender stops on an empty cap anyway), or an earlier step of
the job surely writing it to ``$GITHUB_ENV`` (``caps_to_github_env``, read as shell commands).

The script itself never sets a cap here, because whether a start runs with a cap depends on the order
of the step's commands (an ``export`` after the start, an ``unset``, ``export -n``, ``env -u``), and
this audit does not follow that order. So a step whose script, or a shell script it runs, names a
cap the step needs is "cannot tell" for that cap, whether the cap also comes from ``env``. The same
for a start under ``sudo``, ``su``, ``doas``, ``runuser``, ``exec -c`` or ``env`` with an option
(``-i``, ``-u``), which change the environment the start sees. ``caps_set_in_script`` still reads
which caps a script surely exports, to say so in that reason.

Within what it reads, then, a step is listed whenever a start may run without a cap it needs. What it
does not read: a variable name built at run time (``unset "$NAME"``), and a program other than a shell
script or our Python that changes the environment before starting ours. Model keys are found by a
looser text search, which over-reports in the safe direction.

    python3 -m tools.spend_cap_audit            # report; exit 1 on any gap or cannot-tell
    python3 -m tools.spend_cap_audit --json
    python3 -m tools.spend_cap_audit --check    # exit 1 unless the gaps are exactly the recorded list

The recorded list, ``tools/spend_cap_gaps.json``, maps each step (``workflow::job::step name``) to the
caps it may miss, each with ``unreviewed``, or with what a reader found ("not sent: why", "open:
why"), and to the reasons it cannot be told. ``--check`` (and ``tests.test_spend_cap_audit``) fails on
a step that is not listed, so a new live step that may start a sender without its cap is caught when
it is written, and on a listed step the audit no longer lists, so the list only shrinks. It compares
steps, not caps (``compare``): which caps a listed step may miss moves with any new import on main,
and ``--check`` prints that drift as notes.

Nothing here runs a workflow, a game or a model.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The same table as expectrail.spend.CAP_ENV. A test holds the two equal, so this file does not
# import the package it audits.
CAP_ENV = {
    "vision": "EXPECTRAIL_SAM_USD_CAP",
    "glimmer": "EXPECTRAIL_GLIMMER_USD_CAP",
    "muse": "EXPECTRAIL_MUSE_USD_CAP",
    "triage": "EXPECTRAIL_TRIAGE_USD_CAP",
    "spec": "EXPECTRAIL_SPEC_USD_CAP",
}
# Vision is counted in agents.sam_observations itself, not through expectrail.spend.hold.
FIXED_SENDERS = {"agents.sam_observations": {"vision"}}
# The keys each role's sender can send with (read from the senders; tests hold them to the code).
# Vision reads MODEL_API_KEY only (agents.sam_observations.KEY_ENV); Glimmer its own key
# (agents.glimmer_client.KEY_ENVS); Muse, triage and spec drafting go through the provider layer,
# which takes any provider's key (expectrail.providers).
PROVIDER_KEYS = frozenset({
    "MODEL_API_KEY", "META_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
    "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "OLLAMA_API_KEY", "VLLM_API_KEY", "BASETEN_API_KEY",
    "EXPECTRAIL_OPEN_API_KEY", "FIREWORKS_API_KEY", "EXPECTRAIL_GLIMMER_API_KEY", "EXPECTRAIL_LLM_API_KEY",
})
ROLE_KEYS = {
    "vision": frozenset({"MODEL_API_KEY"}),
    "glimmer": frozenset({"EXPECTRAIL_GLIMMER_API_KEY", "FIREWORKS_API_KEY"}),
    "muse": PROVIDER_KEYS,
    "triage": PROVIDER_KEYS,
    "spec": PROVIDER_KEYS,
}
ROLE_KEY_PATTERN = re.compile(r"EXPECTRAIL_[A-Z]+_API_KEY")  # a role's own key, expectrail.providers
SPEND_MODULE = "expectrail.spend"
HOLD_NAMES = {"hold", "require_cap"}
CONSOLE_SCRIPTS = {"expectrail": "expectrail.cli"}

HEREDOC = re.compile(r"<<-?\s*(['\"]?)(?P<tag>[A-Za-z_][A-Za-z0-9_]*)\1")
# Loose text search, for model KEYS only: finding more keys than are set only audits more steps.
EXPORT = re.compile(r"(?:^|[\s;&|(])(?:export\s+)?(?P<name>[A-Z][A-Z0-9_]*)=(?P<value>\S*)")
GITHUB_ENV_WRITE = re.compile(r"(?P<name>[A-Z][A-Z0-9_]*)=[^\n]*>>\s*\"?\$\{?GITHUB_ENV")


# ---------------------------------------------------------------- the repository's modules

def module_files(root: Path) -> dict[str, Path]:
    """Dotted name -> file, for every .py under the repository's top-level packages."""
    out: dict[str, Path] = {}
    for top in sorted(p for p in root.iterdir() if p.is_dir() and (p / "__init__.py").is_file()):
        for path in sorted(top.rglob("*.py")):
            rel = path.relative_to(root).with_suffix("")
            parts = list(rel.parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if all(part.isidentifier() for part in parts):
                out[".".join(parts)] = path
    return out


def _parents(name: str) -> list[str]:
    parts = name.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts))]


@dataclass
class Graph:
    root: Path
    files: dict[str, Path]
    edges: dict[str, set[str]] = field(default_factory=dict)
    senders: dict[str, set[str]] = field(default_factory=dict)
    unreadable: set[str] = field(default_factory=set)

    @classmethod
    def build(cls, root: Path) -> "Graph":
        graph = cls(root, module_files(root))
        for name, path in graph.files.items():
            graph._scan(name, path)
        for name, roles in FIXED_SENDERS.items():
            if name in graph.files:
                graph.senders.setdefault(name, set()).update(roles)
        return graph

    def _scan(self, name: str, path: Path) -> None:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            self.unreadable.add(name)
            self.edges[name] = set()
            return
        is_pkg = path.name == "__init__.py"
        self.edges[name] = self.imports_of(tree, name, is_pkg)
        roles = set() if name.split(".")[0] == "tests" else self._held_roles(tree, name, is_pkg)
        if roles:
            self.senders.setdefault(name, set()).update(roles)

    def resolve(self, target: str) -> set[str]:
        """The repository modules an import of ``target`` loads: it and its packages."""
        found = {t for t in [*_parents(target), target] if t in self.files}
        return found

    def imports_of(self, tree: ast.AST, name: str, is_pkg: bool) -> set[str]:
        package = name if is_pkg else name.rpartition(".")[0]
        out: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    out |= self.resolve(alias.name)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    anchor = package.split(".") if package else []
                    up = node.level - 1
                    if up > len(anchor):
                        continue
                    anchor = anchor[: len(anchor) - up] if up else anchor
                    base = ".".join([*anchor, *([base] if base else [])])
                out |= self.resolve(base)
                for alias in node.names:
                    out |= self.resolve(f"{base}.{alias.name}" if base else alias.name)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # importlib.import_module("x.y"), or ["python", "-m", "x.y"] for a child process.
                text = node.value.strip()
                if text in self.files:
                    out |= self.resolve(text)
        out.discard(name)
        return out

    def _held_roles(self, tree: ast.AST, name: str, is_pkg: bool) -> set[str]:
        if name == SPEND_MODULE:
            return set()
        imports = self.imports_of(tree, name, is_pkg)
        if SPEND_MODULE not in imports:
            return set()
        roles: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
            first = node.args[0]
            if called in HOLD_NAMES and isinstance(first, ast.Constant) and first.value in CAP_ENV:
                roles.add(first.value)
        return roles

    def closure(self, starts: set[str]) -> set[str]:
        seen: set[str] = set()
        todo = [s for s in starts if s in self.files]
        while todo:
            mod = todo.pop()
            if mod in seen:
                continue
            seen.add(mod)
            todo.extend(self.edges.get(mod, ()))
        return seen

    def roles_reached(self, starts: set[str]) -> tuple[set[str], set[str]]:
        """(roles whose sender is reachable, unreadable modules on the way)."""
        reach = self.closure(starts)
        roles: set[str] = set()
        for mod in reach:
            roles |= self.senders.get(mod, set())
        return roles, reach & self.unreadable


# ---------------------------------------------------------------- what a step starts

PY_NAME = re.compile(r"python(?:3(?:\.\d+)?)?")


@dataclass
class Starts:
    modules: set[str] = field(default_factory=set)
    cannot_tell: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)   # the shell scripts followed, as read


def _inline_imports(graph: Graph, code: str) -> set[str] | None:
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return None
    return graph.imports_of(tree, "__main__", False)


def _split_heredocs(script: str) -> tuple[list[str], dict[int, str]]:
    """Lines of the script with here-document bodies taken out; kept line index -> body."""
    lines = script.splitlines()
    kept: list[str] = []
    bodies: dict[int, str] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        m = HEREDOC.search(line)
        if m:
            tag, body = m.group("tag"), []
            i += 1
            while i < len(lines) and lines[i].strip() != tag:
                body.append(lines[i])
                i += 1
            bodies[len(kept) - 1] = "\n".join(body)
        i += 1
    return kept, bodies


def _join_continuations(lines: list[str]) -> list[tuple[int, str]]:
    """Logical lines: (index of the last physical line, text), so a here-document opened on the
    last line of a continued command is still found."""
    out: list[tuple[int, str]] = []
    buf = ""
    for i, line in enumerate(lines):
        if line.rstrip().endswith("\\"):
            buf += line.rstrip()[:-1] + " "
            continue
        out.append((i, buf + line))
        buf = ""
    if buf:
        out.append((len(lines) - 1, buf))
    return out


def _substitutions(text: str) -> list[str]:
    """The bodies of every ``$( ... )`` and back-quoted command in ``text``, nested ones too."""
    out: list[str] = []
    i = 0
    while i < len(text):
        if text.startswith("$(", i) and not text.startswith("$((", i):
            depth, j = 1, i + 2
            while j < len(text) and depth:
                depth += {"(": 1, ")": -1}.get(text[j], 0)
                j += 1
            body = text[i + 2:j - 1]
            out.append(body)
            out.extend(_substitutions(body))
            i = j
        elif text[i] == "`":
            j = text.find("`", i + 1)
            if j < 0:
                break
            out.append(text[i + 1:j])
            i = j + 1
        else:
            i += 1
    return out


def _blank_substitutions(text: str) -> str:
    """``text`` with each substitution replaced by a placeholder word, for the outer command."""
    for body in sorted(set(_substitutions(text)), key=len, reverse=True):
        text = text.replace(f"$({body})", "SUBST").replace(f"`{body}`", "SUBST")
    return text


def step_starts(graph: Graph, script: str, *, _depth: int = 0) -> Starts:
    found = Starts()
    lines, bodies = _split_heredocs(script)
    for index, line in _join_continuations(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for n, segment in enumerate([_blank_substitutions(line), *_substitutions(line)]):
            try:
                words = shlex.split(segment, comments=True)
            except ValueError:
                found.cannot_tell.append(f"cannot read the command {stripped[:80]!r}")
                continue
            # A here-document feeds the outer command, not a command substitution inside it.
            _scan_words(graph, words, stripped, bodies.get(index) if n == 0 else None, found, _depth)
    return found


# Commands that start what follows them with a changed environment.
ENV_CHANGERS = {"sudo", "su", "doas", "runuser", "pkexec"}


def _changes_environment(before: list[str]) -> bool:
    for j, word in enumerate(before):
        base = word.rsplit("/", 1)[-1]
        if base in ENV_CHANGERS:
            return True
        if base == "env" and any(w.startswith("-") for w in before[j + 1:]):
            return True
        if base == "exec" and any(w.startswith("-") for w in before[j + 1:]):
            return True
    return False


def _scan_words(graph: Graph, words: list[str], line: str, body: str | None, found: Starts, depth: int) -> None:
    for i, word in enumerate(words):
        base = word.rsplit("/", 1)[-1]
        if PY_NAME.fullmatch(base):
            had = set(found.modules)
            _python_start(graph, words[i + 1:], line, body, found)
            if found.modules - had and _changes_environment(words[:i]):
                found.cannot_tell.append(f"the start runs with a changed environment in {line[:80]!r}")
        elif base in CONSOLE_SCRIPTS and (i == 0 or words[i - 1] in {"&&", "||", ";", "|", "!", "then", "do",
                                                                        "time", "exec", "if", "else"}):
            found.modules |= graph.resolve(CONSOLE_SCRIPTS[base])
        elif word.endswith(".sh") and (i == 0 or words[i - 1] in {"bash", "sh", "source", ".", "&&", "||", ";",
                                                                     "then", "do", "if", "!"}):
            path = (graph.root / word).resolve()
            if "$" in word or not path.is_file() or depth >= 3:
                found.cannot_tell.append(f"cannot follow the shell script {word!r}")
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            inner = step_starts(graph, text, _depth=depth + 1)
            found.modules |= inner.modules
            found.cannot_tell.extend(inner.cannot_tell)
            found.texts.append(text)
            found.texts.extend(inner.texts)


def _python_start(graph: Graph, words: list[str], line: str, body: str | None, found: Starts) -> None:
    i = 0
    while i < len(words):
        word = words[i]
        if word == "-m":
            if i + 1 >= len(words):
                found.cannot_tell.append(f"no module after -m in {line[:80]!r}")
                return
            target = words[i + 1]
            if target in {"pip", "venv", "unittest", "json.tool", "http.server", "playwright"}:
                if target == "unittest":
                    found.cannot_tell.append(f"a test run in a live step: {line[:80]!r}")
                return
            if "$" in target or not all(p.isidentifier() for p in target.split(".")):
                found.cannot_tell.append(f"the module is chosen at run time in {line[:80]!r}")
                return
            if target in graph.files:
                found.modules |= graph.resolve(target)
            return  # a standard-library or installed module: nothing of ours
        if word == "-c":
            if i + 1 >= len(words):
                found.cannot_tell.append(f"no code after -c in {line[:80]!r}")
                return
            got = _inline_imports(graph, words[i + 1])
            if got is None:
                found.cannot_tell.append(f"cannot parse the inline Python in {line[:80]!r}")
            else:
                found.modules |= got
            return
        if word == "-":
            if body is None:
                found.cannot_tell.append(f"Python read from standard input in {line[:80]!r}")
                return
            got = _inline_imports(graph, body)
            if got is None:
                found.cannot_tell.append(f"cannot parse the here-document Python after {line[:80]!r}")
            else:
                found.modules |= got
            return
        if word.startswith("-"):
            i += 1
            continue
        # A script path.
        if word.endswith(".py"):
            path = (graph.root / word).resolve()
            if "$" in word or not path.is_file():
                found.cannot_tell.append(f"cannot read the script {word!r}")
                return
            try:
                rel = path.relative_to(graph.root.resolve()).with_suffix("")
            except ValueError:
                found.cannot_tell.append(f"the script {word!r} is outside the repository")
                return
            dotted = ".".join(p for p in rel.parts if p != "__init__")
            if dotted in graph.files:
                found.modules |= graph.resolve(dotted)
                return
            got = _inline_imports(graph, path.read_text(encoding="utf-8"))
            if got is None:
                found.cannot_tell.append(f"cannot parse the script {word!r}")
            else:
                found.modules |= got
            return
        return  # python followed by something that is not a start (e.g. a version check)


# ---------------------------------------------------------------- caps a step has

def _set(value) -> bool:
    return value is not None and str(value).strip() not in {"", "''", '""'}


def names_in_env(env) -> set[str]:
    """The variables an ``env:`` map sets to something that is not empty."""
    if not isinstance(env, dict):
        return set()
    return {str(k) for k, v in env.items() if _set(v)}


def names_in_script(script: str) -> set[str]:
    """Loose: every ``NAME=value`` with a value anywhere in the script. Used for model keys only,
    where finding too many is the safe direction; never for caps (``caps_set_in_script``)."""
    out = set()
    for m in EXPORT.finditer(script):
        if _set(m.group("value")):
            out.add(m.group("name"))
    return out


def names_to_github_env_loosely(script: str) -> set[str]:
    """Loose: for model keys only, as ``names_in_script``."""
    return {m.group("name") for m in GITHUB_ENV_WRITE.finditer(script)}


# ---------------------------------------------------------------- caps, read as shell commands

ASSIGN = re.compile(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)", re.S)
OPENERS = {"if", "case", "for", "while", "until", "select", "{", "function"}
CLOSERS = {"fi", "esac", "done", "}"}
LEADERS = {"then", "do", "else", "elif", "!", "time"}  # the next word is in command position
NL = "<end of line>"  # not a word shlex can make: it has spaces
SEPARATORS = {";", NL, ";;", ";&", ";;&"}
CONDITIONAL = {"&&", "||", "|", "|&", "&"}
GITHUB_ENV_TARGETS = {"$GITHUB_ENV", "${GITHUB_ENV}"}


@dataclass
class ShellNames:
    """What a step's script sets for the rest of the step, and what it writes to ``$GITHUB_ENV``
    for later steps. ``sure`` is False when the script could not be read as commands: then
    nothing it sets counts."""
    exported: set[str] = field(default_factory=set)
    to_github_env: set[str] = field(default_factory=set)
    sure: bool = True


OPERATORS = sorted([";;&", ";;", ";&", "&&", "||", "|&", ">>", "<<<", "<<-", "<<", ">&", "<&", "&>>", "&>",
                    ">|", ">", "<", "(", ")", ";", "&", "|"], key=len, reverse=True)
REDIRECTS_OUT = {">", ">>", ">|", "&>", "&>>"}


@dataclass(frozen=True)
class Token:
    text: str          # the word with its quoting removed, or the operator
    op: bool = False   # an unquoted shell operator
    plain: bool = True  # no quoting or escape in it, so it can be a keyword


def _closing(line: str, i: int, open_: str, close: str) -> int:
    """Index just past the ``close`` that balances the ``open_`` at ``i``, skipping quoted text; -1."""
    depth, j, n = 0, i, len(line)
    while j < n:
        c = line[j]
        if c == "\\":
            j += 2
            continue
        if c in "'\"":
            k = line.find(c, j + 1)
            if k < 0:
                return -1
            j = k + 1
            continue
        if line.startswith(open_, j):
            depth += 1
            j += len(open_)
            continue
        if line.startswith(close, j):
            depth -= 1
            j += len(close)
            if depth == 0:
                return j
            continue
        j += 1
    return -1


def _lex(line: str) -> list[Token] | None:
    """One logical line as shell words and operators, quoting kept apart from operators, so a quoted
    ``';'`` is a word. None when the line cannot be read (an unclosed quote or bracket)."""
    out: list[Token] = []
    buf: list[str] = []
    inword, plain, i, n = False, True, 0, len(line)

    def flush():
        nonlocal inword, plain
        if inword:
            out.append(Token("".join(buf), False, plain))
        buf.clear()
        inword, plain = False, True

    while i < n:
        c = line[i]
        if c in " \t\r":
            flush()
            i += 1
        elif c == "#" and not inword:
            break
        elif c == "\\":
            if i + 1 < n:
                buf.append(line[i + 1])
            inword, plain, i = True, False, i + 2
        elif c == "'":
            j = line.find("'", i + 1)
            if j < 0:
                return None
            buf.append(line[i + 1:j])
            inword, plain, i = True, False, j + 1
        elif c == '"':
            j, part = i + 1, []
            while j < n and line[j] != '"':
                if line[j] == "\\" and j + 1 < n and line[j + 1] in '$`"\\':
                    part.append(line[j + 1])
                    j += 2
                else:
                    part.append(line[j])
                    j += 1
            if j >= n:
                return None
            buf.append("".join(part))
            inword, plain, i = True, False, j + 1
        elif line.startswith("$((", i) or line.startswith("${", i):
            j = _closing(line, i + 1, "((", "))") if line.startswith("$((", i) else line.find("}", i) + 1
            if j <= 0:
                return None
            buf.append(line[i:j])
            inword, i = True, j
        elif c == "(" and inword and "".join(buf).endswith("="):   # an array: name=( ... )
            j = _closing(line, i, "(", ")")
            if j < 0:
                return None
            buf.append(line[i:j])
            i = j
        else:
            op = next((o for o in OPERATORS if line.startswith(o, i)), None)
            if op:
                flush()
                out.append(Token(op, True, False))
                i += len(op)
            else:
                buf.append(c)
                inword, i = True, i + 1
    flush()
    return out


Command = tuple[list[Token], bool, "str | None"]


def _commands(script: str) -> tuple[list[Command], bool]:
    """Simple commands of the script, each with whether it surely runs in the step's own shell
    (top level, not conditional, not in a pipeline, a subshell or the background) and the
    here-document body it reads. Returns (commands, sure); ``sure`` is False when a line cannot be
    read or the nesting does not balance, and then nothing the script sets counts."""
    lines, bodies = _split_heredocs(script)
    out: list[Command] = []
    depth = 0
    for index, line in _join_continuations(lines):
        tokens = _lex(_blank_substitutions(line))
        if tokens is None:
            return out, False
        tokens.append(Token(NL, True, False))
        current: list[Token] = []
        before = NL          # the operator before the current command
        in_test = False

        def end(after: str) -> None:
            if current:
                surely = depth == 0 and before in SEPARATORS and after not in CONDITIONAL
                out.append((list(current), surely, bodies.get(index)))
            current.clear()

        for tok in tokens:
            if in_test:
                current.append(tok)
                in_test = not (tok.plain and tok.text == "]]")
                continue
            if tok.op and (tok.text in SEPARATORS or tok.text in CONDITIONAL or tok.text in "()"):
                end(tok.text)
                if tok.text in "()":
                    depth += 1 if tok.text == "(" else -1
                    if depth < 0:
                        return out, False
                    before = NL if depth == 0 else "("
                    if depth == 0 and tok.text == ")":
                        before = ")"   # what follows a subshell is still part of its list
                else:
                    before = NL if (tok.text in SEPARATORS and depth == 0) else tok.text
                continue
            if not current and tok.plain:
                if tok.text == "[[":
                    in_test = True
                    current.append(tok)
                    continue
                if tok.text in OPENERS:
                    depth += 1
                    continue
                if tok.text in CLOSERS:
                    depth -= 1
                    if depth < 0:
                        return out, False
                    continue
                if tok.text in LEADERS:
                    continue
            current.append(tok)
    return out, depth == 0


def _redirect_target(tokens: list[Token]) -> tuple[int, str] | None:
    for i, tok in enumerate(tokens):
        if tok.op and tok.text in REDIRECTS_OUT and i + 1 < len(tokens) and not tokens[i + 1].op:
            return i, tokens[i + 1].text
    return None


def shell_names(script: str) -> ShellNames:
    commands, sure = _commands(script)
    found = ShellNames(sure=sure)
    if not sure:
        return found
    assigned: set[str] = set()   # shell variables surely set (not exported) earlier
    for tokens, surely_runs, body in commands:
        if not surely_runs:
            continue
        redirect = _redirect_target(tokens)
        words = [t.text for t in tokens if not t.op]
        if redirect is not None:
            at, target = redirect
            if target in GITHUB_ENV_TARGETS:
                # Reaches later steps only: ``echo NAME=value >> $GITHUB_ENV``, or a here-document.
                args = [t.text for t in tokens[:at] if not t.op]
                if args[:1] == ["echo"]:
                    rest = [a for a in args[1:] if not a.startswith("-")]
                    if len(rest) == 1 and (m := ASSIGN.fullmatch(rest[0])) and _set(m.group("value")):
                        found.to_github_env.add(m.group("name"))
                elif args == ["cat"] and body is not None:
                    for line in body.splitlines():
                        if (m := ASSIGN.fullmatch(line.strip())) and _set(m.group("value")):
                            found.to_github_env.add(m.group("name"))
            continue                 # a command that writes a file sets nothing in this shell
        if any(t.op for t in tokens):
            continue                 # other redirections or a here-document: not a plain export
        assigns = 0
        while assigns < len(words) and ASSIGN.fullmatch(words[assigns]):
            assigns += 1
        if assigns == len(words):    # bare assignments: shell variables, not passed to a child
            for w in words:
                m = ASSIGN.fullmatch(w)
                (assigned.add if _set(m.group("value")) else assigned.discard)(m.group("name"))
            continue
        if assigns:
            continue                 # a prefix covers its one command only
        if not tokens[0].plain:
            continue                 # a quoted command word is not the builtin by sight
        cmd, args = words[0], words[1:]
        if cmd == "export":
            if any(a.startswith("-") and a != "--" for a in args):
                continue             # export -n, -f, -p: not a plain export
        elif cmd in {"declare", "typeset"}:
            flags = "".join(a[1:] for a in args if a.startswith("-"))
            if "x" not in flags or any(a.startswith("+") for a in args):
                continue
        else:
            continue
        for a in args:
            if a.startswith("-"):
                continue
            m = ASSIGN.fullmatch(a)
            if m:
                (found.exported.add if _set(m.group("value")) else found.exported.discard)(m.group("name"))
            elif a in assigned:
                found.exported.add(a)
    return found


def caps_set_in_script(script: str) -> set[str]:
    """The caps a script surely exports for the rest of its step."""
    return shell_names(script).exported & set(CAP_ENV.values())


def caps_to_github_env(script: str) -> set[str]:
    """The caps a script surely writes to ``$GITHUB_ENV``, for later steps of the job."""
    return shell_names(script).to_github_env & set(CAP_ENV.values())


def caps_in_env(env) -> set[str]:
    return names_in_env(env) & set(CAP_ENV.values())


def keys_for(role: str, names: set[str]) -> set[str]:
    keys = {n for n in names if n.endswith("_API_KEY")}
    usable = keys & ROLE_KEYS[role]
    if role in {"muse", "triage", "spec"}:
        usable |= {k for k in keys if ROLE_KEY_PATTERN.fullmatch(k)}
    return usable


# ---------------------------------------------------------------- the audit

@dataclass(frozen=True)
class Row:
    workflow: str
    job: str
    step: str
    missing: tuple[str, ...]        # cap variable names
    cannot_tell: tuple[str, ...]

    def key(self) -> str:
        return f"{self.workflow}::{self.job}::{self.step}"


def _step_name(step: dict, index: int) -> str:
    return str(step.get("name") or step.get("id") or f"step {index + 1}")


def audit(root: Path = REPO, graph: Graph | None = None) -> list[Row]:
    import yaml  # requirements-dev.txt; only needed to audit, not to import this module

    graph = graph or Graph.build(root)
    rows: list[Row] = []
    for wf in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        try:
            doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            rows.append(Row(wf.name, "*", "*", (), (f"cannot read the workflow: {exc}"[:200],)))
            continue
        if not isinstance(doc, dict):
            continue
        wf_names = names_in_env(doc.get("env"))
        for job_name, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict) or not job.get("environment"):
                continue
            job_names = wf_names | names_in_env(job.get("env"))
            carried_keys: set[str] = set()   # loose, for keys
            carried_caps: set[str] = set()   # strict, for caps
            for index, step in enumerate(job.get("steps") or []):
                if not isinstance(step, dict):
                    continue
                script = step.get("run")
                if not isinstance(script, str):
                    continue
                step_env = names_in_env(step.get("env"))
                keys = job_names | carried_keys | step_env | names_in_script(script)
                caps = (job_names | carried_caps | step_env) & set(CAP_ENV.values())
                carried_keys |= names_to_github_env_loosely(script)
                carried_caps |= caps_to_github_env(script)
                if not keys_for("spec", keys) | keys_for("vision", keys) | keys_for("glimmer", keys):
                    continue  # no model key in this step: nothing it starts can send
                starts = step_starts(graph, script)
                roles, unreadable = graph.roles_reached(starts.modules)
                needed = sorted(CAP_ENV[r] for r in roles if keys_for(r, keys))
                text = "\n".join([script, *starts.texts])
                named = {cap for cap in needed if cap in text}
                missing = tuple(cap for cap in needed if cap not in caps and cap not in named)
                tell = list(starts.cannot_tell) + [f"cannot read the module {m}" for m in sorted(unreadable)]
                exported = caps_set_in_script(script)
                for cap in sorted(named):
                    how = "exports" if cap in exported else "names"
                    tell.append(f"the script {how} {cap} itself, and this audit does not follow the order of "
                                "a step's commands, so it cannot tell whether every start runs with it")
                if missing or tell:
                    rows.append(Row(wf.name, str(job_name), _step_name(step, index), missing, tuple(tell)))
    return rows


def as_json(rows: list[Row]) -> dict:
    return {row.key(): {"missing": list(row.missing), "cannotTell": list(row.cannot_tell)} for row in rows}


GAPS_FILE = REPO / "tools" / "spend_cap_gaps.json"


def read_recorded(path: Path = GAPS_FILE) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    for key, entry in doc.items():
        if not isinstance(entry, dict) or key.count("::") != 2:
            raise ValueError(f"{path.name}: {key!r} is not a step with its caps")
        for name, value in entry.items():
            if name == "cannotTell":
                if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
                    raise ValueError(f"{path.name}: {key!r} cannotTell is not a list of reasons")
            elif name not in CAP_ENV.values():
                raise ValueError(f"{path.name}: {key!r} names {name!r}, which is not a role's cap")
            elif not isinstance(value, str) or not value.strip():
                raise ValueError(f"{path.name}: {key!r} {name} needs 'unreviewed' or what was found")
    return doc


def compare(rows: list[Row], recorded: dict) -> list[str]:
    """Every step listed by the audit but not recorded, or recorded but no longer listed. Empty when
    they agree.

    The comparison is by step, not by cap: the import closure changes whenever main adds an import,
    so which caps a listed step may miss moves with unrelated changes (one merge, #602, added Muse to
    ten listed steps). A step that is listed stays under review as a whole; ``drift`` says what moved.
    """
    found = {row.key() for row in rows}
    problems = [f"new step: {key} may start a sender without its cap, or cannot be told. Set the cap "
                f"in that step's env (from the workflow's own budget input), or list it in {GAPS_FILE.name} "
                "with why" for key in sorted(found - set(recorded))]
    problems += [f"fixed: {key} is no longer listed by the audit. Remove it from {GAPS_FILE.name}"
                 for key in sorted(set(recorded) - found)]
    return problems


def drift(rows: list[Row], recorded: dict) -> list[str]:
    """For steps in both: the caps and reasons that differ from the recorded list. Not a failure."""
    notes: list[str] = []
    for row in rows:
        entry = recorded.get(row.key())
        if entry is None:
            continue
        listed = {k for k in entry if k != "cannotTell"}
        for cap in sorted(set(row.missing) - listed):
            notes.append(f"note: {row.key()} may now also miss {cap}")
        for cap in sorted(listed - set(row.missing)):
            notes.append(f"note: {row.key()} no longer misses {cap}")
        if list(row.cannot_tell) != list(entry.get("cannotTell", [])):
            notes.append(f"note: {row.key()} cannot tell: found {list(row.cannot_tell)}, listed "
                         f"{list(entry.get('cannotTell', []))}")
    return notes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", action="store_true", help="print the gaps as JSON")
    ap.add_argument("--check", action="store_true", help=f"compare with {GAPS_FILE.name}")
    ap.add_argument("--root", type=Path, default=REPO)
    args = ap.parse_args(argv)
    rows = audit(args.root)
    if args.check:
        try:
            problems = compare(rows, read_recorded(args.root / "tools" / GAPS_FILE.name))
        except (OSError, ValueError) as exc:
            print(f"cannot tell: the recorded list cannot be read: {exc}")
            return 1
        for problem in problems:
            print(problem)
        for note in drift(rows, read_recorded(args.root / "tools" / GAPS_FILE.name)):
            print(note)
        print(f"{len(rows)} step(s) listed; {'they match the recorded list' if not problems else f'{len(problems)} difference(s)'}.")
        return 1 if problems else 0
    if args.json:
        print(json.dumps(as_json(rows), indent=2, sort_keys=True))
    else:
        for row in rows:
            if row.missing:
                print(f"GAP  {row.key()}: may reach a sender with no {', '.join(row.missing)}")
            for why in row.cannot_tell:
                print(f"CANNOT TELL  {row.key()}: {why}")
        gaps = sum(1 for r in rows if r.missing)
        unknown = sum(1 for r in rows if r.cannot_tell)
        print(f"{gaps} step(s) may reach a sender without its cap; {unknown} step(s) cannot be told.")
    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main())
