"""A written explanation of one findings record, for the evidence viewer (#264).

    expectrail.explanation/v1   contracts/explanation.v1.schema.json

The Build line this serves: "Any model-written explanation links to evidence ids and can never
contradict the structured decision." So an explanation decides nothing, and the viewer shows one only
after ``check`` finds nothing wrong with it. ``check`` fails closed: what it cannot match to the
record is a reason to withhold the explanation, never a reason to show it.

- Expectrail, not the author, fills ``decision`` and ``recordSha256`` (``from_answer``). A model is
  told the decision; it is not asked for one.
- ``decision`` must be the verifier's, and the record's; ``recordSha256`` must be this record's.
- Every point cites evidence ids that are in the record: a finding's id, or ``check:<spec>@<route>``.
- ``says`` states the verdicts a point relies on, per cited id. Each must equal the record's.
- The text is printable ASCII (a look-alike letter cannot slip a word past the word lists below).
- Every number in a point must appear in the evidence it cites. Numbers are written as digits: a
  number word ("two", "half") is withheld, since it cannot be compared.
- A failing word ("fails", "broken", "regression") needs a stated ``fail`` in the same point, and a
  passing word ("passes", "fixed", "works") a stated ``pass``. A decision word ("accepted",
  "safe to merge", "rejected") must match the decision. A point with a verdict word and a negation
  ("not", "no longer", "doesn't") is withheld: what a negated verdict says cannot be told from words.
  Words of certainty beyond the evidence ("proves", "guaranteed", "all", "every", "always") are
  withheld: an accept is these checks on these routes, nothing more.

No model is called here. ``prompt`` is the question for one; ``from_answer`` turns its answer into a
v1 document. Asking a live model is a later slice with its own budget.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from expectrail import contracts

FORMAT = "expectrail.explanation/v1"
KIND = "explanation"
FILE_NAME = "explanation.json"
MAX_BYTES = 64 * 1024
VERDICTS = ("pass", "fail", "needs-review", "replay-error", "not-applicable")

FAIL_WORDS = frozenset("""fail fails failed failing failure failures broken break breaks broke breaking
regression regressions regressed regresses bug bugs buggy wrong worse incorrect incorrectly""".split())
PASS_WORDS = frozenset("""pass passes passed passing work works worked working fix fixes fixed fixing
repair repairs repaired correct correctly succeed succeeds succeeded success successful ok okay fine
good better resolved resolves""".split())
ACCEPT_WORDS = frozenset("accept accepts accepted acceptable approve approves approved safe merge merged "
                         "mergeable ship shippable".split())
REJECT_WORDS = frozenset("reject rejects rejected block blocks blocked".split())
NEGATIONS = frozenset("not no never nor neither without cannot cant longer none nothing".split())
CERTAINTY = frozenset("""prove proves proved proven proof guarantee guarantees guaranteed certain certainly
definitely always all every everything entire entirely whole completely totally fully""".split())
NUMBER_WORDS = frozenset("""zero one two three four five six seven eight nine ten eleven twelve thirteen
fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety
hundred hundreds thousand thousands million half twice double triple dozen""".split())
TOKEN = re.compile(r"[0-9]+(?:\.[0-9]+)?|[a-z]+(?:'[a-z]+)?")
NUMBER = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")


class ExplanationError(ValueError):
    pass


# --- the evidence an explanation may cite ---------------------------------------------------------

def evidence(record: dict) -> dict[str, dict]:
    """id -> {"before", "after", "text"} for every finding and every check in the record. ``text``
    is what a point citing it may take its numbers from."""
    out: dict[str, dict] = {}
    for c in record.get("checks") or []:
        out[f"check:{c['spec']}@{c['route']}"] = {
            "before": c.get("before"), "after": c.get("after"),
            "text": " ".join(str(c.get(k) or "") for k in ("spec", "route", "comparison"))}
    for f in record.get("findings") or []:
        out[f["id"]] = {
            "before": f.get("before"), "after": f.get("after"),
            "text": " ".join(str(f.get(k) if f.get(k) is not None else "")
                             for k in ("spec", "route", "comparison", "reason", "frame"))}
    return out


def _numbers(text: str) -> set[str]:
    return {_number(n) for n in NUMBER.findall(text)}


def _number(token: str) -> str:
    token = token.lstrip("-")
    if "." in token:
        token = token.rstrip("0").rstrip(".")
    return token.lstrip("0") or "0"


# --- the check ------------------------------------------------------------------------------------

def check(doc, record: dict | None, decision: str | None) -> list[str]:
    """Reasons to withhold this explanation; empty when it may be shown beside the evidence."""
    if isinstance(doc, dict) and set(doc) == {"unreadable"}:
        return [f"it could not be read: {doc['unreadable']}"]
    try:
        contracts.validate_v1(doc, KIND)
    except contracts.ContractError as exc:
        return [f"it is not a valid {FORMAT} document ({str(exc)[:200]})"]
    if record is None or decision is None:
        return ["there is no verifier decision for it to explain"]
    problems = []
    if doc["decision"] != decision or doc["decision"] != record.get("decision"):
        return [f"it explains a {doc['decision']} but the verifier decided {decision or 'nothing'}"]
    if doc["recordSha256"] != contracts.digest_v1(record):
        return ["it was written for other evidence than this run's"]
    known = evidence(record)
    for n, point in enumerate(doc["points"], 1):
        problems += [f"point {n}: {p}" for p in _point(point, known, decision)]
    return problems


def _point(point: dict, known: dict[str, dict], decision: str) -> list[str]:
    text = point["text"]
    if not all(" " <= ch <= "~" for ch in text):
        return ["its text has characters other than printable ASCII, so its words cannot be checked"]
    unknown = [c for c in point["cites"] if c not in known]
    if unknown:
        return [f"it cites {', '.join(unknown)}, which is not in this run's evidence"]
    problems = []
    stated = set()
    for cid, sides in point["says"].items():
        if cid not in point["cites"]:
            problems.append(f"it states a verdict for {cid} without citing it")
            continue
        for side, verdict in sides.items():
            actual = known[cid][side]
            if verdict != actual:
                problems.append(f"it says {cid} was {verdict} {side} the change; the record says "
                                f"{actual or 'not run'}")
            stated.add(verdict)
    allowed = set()
    for cid in point["cites"]:
        allowed |= _numbers(known[cid]["text"])
    tokens = TOKEN.findall(text.lower())
    words = set()
    for t in tokens:
        if t[0].isdigit():
            if _number(t) not in allowed:
                problems.append(f"the number {t} is not in the evidence it cites")
        else:
            words.add(t)
            if t.endswith("n't"):
                words.add("not")
    if words & NUMBER_WORDS:
        problems.append(f"it writes a number in words ({', '.join(sorted(words & NUMBER_WORDS))}); "
                        "numbers are compared as digits")
    verdict_words = words & (FAIL_WORDS | PASS_WORDS | ACCEPT_WORDS | REJECT_WORDS)
    if verdict_words and words & NEGATIONS:
        problems.append("it negates a verdict word, and what that says cannot be told from its words")
    if words & FAIL_WORDS and "fail" not in stated:
        problems.append(f"it says {', '.join(sorted(words & FAIL_WORDS))} without stating a failing verdict")
    if words & PASS_WORDS and "pass" not in stated:
        problems.append(f"it says {', '.join(sorted(words & PASS_WORDS))} without stating a passing verdict")
    if words & ACCEPT_WORDS and decision != "accept":
        problems.append(f"it says {', '.join(sorted(words & ACCEPT_WORDS))}, but the decision is {decision}")
    if words & REJECT_WORDS and decision != "reject":
        problems.append(f"it says {', '.join(sorted(words & REJECT_WORDS))}, but the decision is {decision}")
    if words & CERTAINTY:
        problems.append(f"it says {', '.join(sorted(words & CERTAINTY))}, which claims more than these "
                        "checks on these routes")
    return problems


def shown(doc, record: dict | None, decision: str | None) -> dict:
    """What the viewer embeds: the points when the check passes, otherwise only why it was withheld."""
    problems = check(doc, record, decision)
    author = doc.get("author") if isinstance(doc, dict) and isinstance(doc.get("author"), dict) else {}
    out = {"model": str(author.get("model") or "unknown")[:80], "recorded": author.get("recorded") is True}
    if problems:
        return dict(out, shown=False, withheld=problems[:10])
    return dict(out, shown=True, points=[{"text": p["text"], "cites": list(p["cites"])} for p in doc["points"]])


# --- the writer -----------------------------------------------------------------------------------

def prompt(record: dict) -> str:
    """The question for a model. It states the decision and the evidence; it asks for no decision."""
    lines = [
        "Explain this Expectrail verification result to someone who has not seen it.",
        f"The verifier's decision is: {record['decision']}. Do not decide anything; do not restate the decision.",
        "Answer with JSON only: {\"points\": [{\"text\": ..., \"cites\": [ids], \"says\": {id: {\"before\": v, "
        "\"after\": v}}}]}, 1 to 8 points, each text at most 400 printable ASCII characters.",
        "Every point cites the evidence ids it is about. In says, state the verdicts the point relies on, "
        "exactly as listed below. Write numbers as digits, and only numbers that appear in the cited "
        "evidence. Do not negate verdict words, and do not say all, every, always or proves.",
        "",
        "Evidence:",
    ]
    for cid, e in evidence(record).items():
        lines.append(f"- {cid}: before {e['before'] or 'not run'}, after {e['after']}; {e['text']}")
    return "\n".join(lines) + "\n"


def from_answer(answer: str, record: dict, *, model: str, recorded: bool) -> dict:
    """A v1 document from a model's answer. Raises ExplanationError when the answer is not the shape
    asked for. It does not decide whether the explanation is shown: ``check`` does, when it is read."""
    try:
        parsed = contracts.strict_loads(answer)
    except ValueError as exc:
        raise ExplanationError(f"the answer is not JSON ({type(exc).__name__})") from None
    if not isinstance(parsed, dict) or set(parsed) != {"points"}:
        raise ExplanationError("the answer must be an object with points only")
    doc = {"format": FORMAT, "decision": record["decision"], "recordSha256": contracts.digest_v1(record),
           "author": {"kind": "model", "model": model, "recorded": bool(recorded),
                      "promptSha256": hashlib.sha256(prompt(record).encode("utf-8")).hexdigest()},
           "points": parsed["points"]}
    try:
        contracts.validate_v1(doc, KIND)
    except contracts.ContractError as exc:
        raise ExplanationError(f"the answer does not fit {FORMAT}: {str(exc)[:200]}") from None
    return doc


# --- the reader -----------------------------------------------------------------------------------

def read(path: Path) -> dict:
    """An explanation file: a regular file (not a link), at most MAX_BYTES, strict JSON, schema-valid."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ExplanationError(f"{path.name} is not a regular file")
    if path.stat().st_size > MAX_BYTES:
        raise ExplanationError(f"{path.name} is larger than {MAX_BYTES} bytes")
    try:
        doc = contracts.strict_loads(path.read_text(encoding="utf-8"))
        contracts.validate_v1(doc, KIND)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ExplanationError(f"{path.name} is not a valid {FORMAT} document ({str(exc)[:200]})") from None
    return doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m expectrail.explanation",
                                     description="Write or check an explanation of a findings record.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prompt", help="print the question for a model")
    p.add_argument("findings", type=Path)
    a = sub.add_parser("from-answer", help="turn a model's answer into an explanation file")
    a.add_argument("findings", type=Path)
    a.add_argument("answer", type=Path)
    a.add_argument("--model", required=True)
    a.add_argument("--recorded", action="store_true", help="the answer was replayed from a recording")
    a.add_argument("--out", required=True, type=Path)
    c = sub.add_parser("check", help="exit 0 if the viewer would show it, 1 if it would be withheld")
    c.add_argument("findings", type=Path)
    c.add_argument("explanation", type=Path)
    args = parser.parse_args(argv)
    from expectrail.gate import record as rec
    try:
        record = rec.read_record(args.findings)
        if args.command == "prompt":
            sys.stdout.write(prompt(record))
            return 0
        if args.command == "from-answer":
            doc = from_answer(args.answer.read_text(encoding="utf-8"), record, model=args.model,
                              recorded=args.recorded)
            args.out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
            problems = check(doc, record, record["decision"])
            print(f"wrote {args.out}" + ("; the viewer would show it" if not problems else
                                         "; the viewer would withhold it: " + "; ".join(problems)))
            return 0
        problems = check(read(args.explanation), record, record["decision"])
    except (rec.RecordError, ExplanationError, OSError) as exc:
        print(f"explanation: {exc}", file=sys.stderr)
        return 2
    if problems:
        print("withheld: " + "; ".join(problems))
        return 1
    print("shown: it cites only this run's evidence and agrees with its decision")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
