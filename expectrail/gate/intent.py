"""What a pull request declares itself to be for: ``fix``, ``change`` or ``none`` (issue #284).

    python3 -m expectrail.gate.intent --event "$GITHUB_EVENT_PATH"      # prints fix, change or none

A pull request declares its intent with a label or a line in its description:

- a label ``intent:fix``, ``intent:change`` or ``intent:none``;
- a line of the description that starts ``Expectrail-Intent:``, followed by ``fix``, ``change`` or
  ``none`` and nothing else (the key's case and the spaces around the value do not matter).

Nothing declared is ``none``. When there are several declarations the strictest wins: ``fix`` over
``change`` over ``none``. A declaration whose value is not one of the three (a label ``intent:bugfix``,
a line ``Expectrail-Intent: maybe``) is read as ``fix``. So no label or line can make acceptance
easier than leaving it out: ``fix`` is the stricter path, and adding text can only move towards it.

Both halves of the CI gate call this. The untrusted verify job reads the declaration from the event
GitHub gave it and passes it to the gate. The trusted comment job reads it again from the pull
request it fetched itself, and refuses a record that was judged less strictly than the pull request
declares, so a pull request that edits its own copy of the verify action cannot declare ``none`` for
itself (docs/ci-gate.md). Standard library only: the comment job imports it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

INTENTS = ("fix", "change", "none")   # the same three as expectrail.gate.record.INTENTS, strictest first
LABEL_PREFIX = "intent:"
# A line that starts with the key is a declaration; its value is the whole rest of the line.
LINE = re.compile(r"[ \t]*expectrail-intent[ \t]*:(.*)", re.IGNORECASE)
MAX_BODY = 65536          # GitHub keeps at most this many characters of a description
MAX_LABELS = 100
MAX_EVENT_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True)
class Declared:
    """The intent a pull request declares and where it was read: ``sources`` lists each declaration
    as written (``label intent:fix``, ``line Expectrail-Intent: fix``), at most ten, each cut short."""
    intent: str
    sources: tuple[str, ...] = ()

    def words(self) -> str:
        """One line for a reason or a comment: what was declared, and where."""
        if not self.sources:
            return "nothing is declared, so it is read as none"
        return f"declared {self.intent} by " + ", ".join(self.sources)


def _value(raw: str) -> str:
    """One declared value: one of the three, or ``fix`` for anything else."""
    return raw if raw in INTENTS else "fix"


def declared(labels, body, *, links_bug: bool = False) -> Declared:
    """The intent from a pull request's labels (names, or label objects with a ``name``) and its
    description. ``links_bug`` is for a caller that knows the pull request links an issue labelled
    as a bug: it is then a fix, whatever else it says. Neither half of the CI gate knows that today
    (the description says "Closes #N", not whether #N is a bug), so both pass False."""
    found: list[tuple[str, str]] = []
    for label in list(labels or [])[:MAX_LABELS]:
        name = label.get("name") if isinstance(label, dict) else label
        if isinstance(name, str) and name.lower().startswith(LABEL_PREFIX):
            found.append((_value(name[len(LABEL_PREFIX):].strip().lower()), f"label {name}"))
    text = body if isinstance(body, str) else ""
    for line in text[:MAX_BODY].splitlines():
        match = LINE.fullmatch(line)
        if match:
            found.append((_value(match.group(1).strip().lower()), f"line {line.strip()}"))
    if links_bug:
        found.append(("fix", "a linked bug issue"))
    if not found:
        return Declared("none")
    intent = min((value for value, _ in found), key=INTENTS.index)
    sources = tuple(dict.fromkeys(_clip(source) for _, source in found))[:10]
    return Declared(intent, sources)


def of_pull_request(pr: dict | None) -> Declared:
    """The intent a pull request object (as the REST API and the event give it) declares."""
    pr = pr if isinstance(pr, dict) else {}
    labels = pr.get("labels")
    return declared(labels if isinstance(labels, list) else [], pr.get("body"))


def of_event(path: Path) -> Declared:
    """The intent the pull request in a ``pull_request`` event file declares; ``none`` for any other
    event. An event file that cannot be read stops the caller: it is never read as ``none``."""
    if path.stat().st_size > MAX_EVENT_BYTES:
        raise ValueError("the event file is too large to read")
    event = json.loads(path.read_text(encoding="utf-8"))
    pr = event.get("pull_request") if isinstance(event, dict) else None
    return of_pull_request(pr) if isinstance(pr, dict) else Declared("none")


def _clip(text: str, limit: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--event", type=Path, required=True, help="the event file GitHub wrote ($GITHUB_EVENT_PATH)")
    args = p.parse_args(argv)
    try:
        found = of_event(args.event)
    except (OSError, ValueError) as exc:
        # Unreadable is the stricter path, never "nothing declared".
        print(f"::warning title=Expectrail intent::the event could not be read ({_clip(str(exc))}), so the change is read as a fix",
              file=sys.stderr)
        print("fix")
        return 0
    print(f"Expectrail intent: {found.words()}", file=sys.stderr)
    print(found.intent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
