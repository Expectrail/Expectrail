"""What a pull request declares itself to be for: ``fix``, ``change`` or ``none`` (issue #284).

    python3 -m expectrail.gate.intent --event "$GITHUB_EVENT_PATH"      # prints fix, change or none

A pull request declares its intent with a label or a line in its description:

- a label ``intent:fix``, ``intent:change`` or ``intent:none``;
- a line of the description that starts ``Expectrail-Intent:``, followed by ``fix``, ``change`` or
  ``none`` and nothing else (the key's case and the spaces around the value do not matter).

A closing-keyword link (Fixes/Closes/Resolves and their GitHub variants) is a fix,
even with a none/change declaration. Every such link is treated strictly; no label lookup is made.

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
MAX_LINKS = 10
# Deliberately conservative, including quoted/code text and cross-repository links.
# Without an issue-label lookup every closing reference imposes fix.
REFERENCE = r"(?:https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[0-9]+|[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\#[0-9]+|\#[0-9]+)"
CLOSING = re.compile(r"\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\b\s*:?\s*" + REFERENCE + r"\b", re.IGNORECASE)
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
    as a bug: it is then a fix, whatever else it says. Every closing-keyword
    reference is also a fix, because no issue-label permission/lookup is required."""
    found: list[tuple[str, str]] = [
        ('fix', f"closing-keyword line {link['line']}: {link['text']}") for link in closing_links(body)]
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


def closing_links(body) -> list[dict]:
    """Bounded matching phrases, never executable text or an issue-label lookup."""
    text = body if isinstance(body, str) else ''
    links = []
    for match in CLOSING.finditer(text[:MAX_BODY]):
        link = {'line': text.count('\n', 0, match.start()) + 1,
                'text': _clip(match.group(), 320)}
        if link not in links:
            links.append(link)
        if len(links) == MAX_LINKS:
            break
    return links


def pull_request_metadata(pr: dict) -> dict:
    """The existing PR identity, with the closing lines used by both CI halves."""
    result = {'number': pr['number'], 'headSha': pr['head']['sha'], 'baseSha': pr['base'].get('sha')}
    links = closing_links(pr.get('body'))
    if links:
        result['fixLinks'] = links
    return result


def _event_pr(path: Path):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_EVENT_BYTES + 1)
    if len(raw) > MAX_EVENT_BYTES:
        raise ValueError('the event file is too large to read')
    event = json.loads(raw.decode('utf-8'))
    return event.get('pull_request') if isinstance(event, dict) else None


def ci_context(metadata, selected: str, event_path=None):
    """Legacy action's event adds provenance and can only tighten explicit intent.

    No event is consulted for a local command without PR identity. An unreadable
    or mismatched CI context refuses the command, never supplies a weaker result.
    """
    if metadata is None or not event_path:
        return metadata, selected
    pr = _event_pr(Path(event_path))
    if not isinstance(pr, dict):
        raise ValueError('the event does not identify this pull request')
    try:
        actual = pull_request_metadata(pr)
    except (KeyError, TypeError) as exc:
        raise ValueError('the event has no usable pull request identity') from exc
    if (actual['number'] != metadata['number'] or actual['headSha'] != metadata['headSha']
            or (metadata['baseSha'] is not None and actual['baseSha'] != metadata['baseSha'])):
        raise ValueError('the event names a different pull request or commit')
    result = dict(metadata)
    if actual.get('fixLinks'):
        result['fixLinks'] = actual['fixLinks']
    declared = of_pull_request(pr).intent
    # Unknown CLI values keep the existing stopped-record path; do not turn an
    # invalid command into an accepted fix merely because it also has a link.
    if selected in INTENTS:
        selected = min((selected, declared), key=INTENTS.index)
    return result, selected


def of_pull_request(pr: dict | None) -> Declared:
    """The intent a pull request object (as the REST API and the event give it) declares."""
    pr = pr if isinstance(pr, dict) else {}
    labels = pr.get("labels")
    return declared(labels if isinstance(labels, list) else [], pr.get("body"))


def of_event(path: Path) -> Declared:
    """The intent the pull request in a ``pull_request`` event file declares; ``none`` for any other
    event. An event file that cannot be read stops the caller: it is never read as ``none``."""
    pr = _event_pr(path)
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
