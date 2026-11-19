"""A written explanation of one findings record, for the evidence viewer (#264).

    expectrail.explanation/v1   contracts/explanation.v1.schema.json

The Build line this serves: "Any model-written explanation links to evidence ids and can never
contradict the structured decision." So an explanation decides nothing, and the viewer shows one only
after ``check`` matches every word of it to the record. ``check`` fails closed: what it cannot match to the
record is a reason to withhold the explanation, never a reason to show it.

- Expectrail, not the author, fills ``decision`` and ``recordSha256`` (``from_answer``). A model is
  told the decision; it is not asked for one.
- ``decision`` must be the verifier's, and the record's; ``recordSha256`` must be this record's.
- Every point cites evidence ids that are in the record: a finding's id, or ``check:<spec>@<route>``.
- ``says`` states the verdicts a point relies on, per cited id. Each must equal the record's.
- The text is printable ASCII (a look-alike letter cannot pass for a word on the lists below).
- Every word comes from a fixed list Expectrail can match: neutral words (``NEUTRAL``: "the",
  "before", "after", "frame", "route", ...), the names of the evidence the point cites, and the
  verifier's own wording of that evidence (a finding's comparison and reason). Any other word
  withholds the point: a list of words to refuse can never be finished, so the check allows rather
  than refuses. A spec's name is allowed as a name, never split into a claim.
- Every number must appear in the evidence the point cites, written as digits.
- A comparison word ("same", "unchanged") needs every cited verdict to be equal before and after the
  change; "difference" or "changed" needs one that differs. Scope words ("only", "also", "other",
  "than") are never allowed: they have no verdict to match.
- A failing word ("fails", "regression") needs a stated ``after: fail`` in the same point; a passing
  word ("passes", "fixed") needs every stated ``after`` to be ``pass``. A ``before`` verdict never
  licenses a word: the verdict sentences the viewer writes from ``says`` cover before and after.
- A decision word ("accepted", "rejected") must be the decision. Negations ("not", "no longer",
  "doesn't") and words of certainty ("proves", "all", "always") are never allowed.

What the page says about each cited verdict, it writes itself from ``says`` (which must equal the
record); the author's text is shown beside it, never instead of it.

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

# Every word of a point must come from one of these places, or the point is withheld (``_point``).
# A list of words to refuse cannot be finished (English always has another way to say "fine"), so the
# check works the other way round: only words it can match to the evidence are allowed.
# Words that cannot carry a claim of their own: articles, pronouns, copulas, prepositions, "before",
# "after", and the nouns that name evidence. A word that compares (same, other, than, earlier), scopes
# (only, also, both) or counts never goes here: with it, a sentence made of allowed words alone could
# say "nothing changed" or "it is just the observer" (#632, second review). tests.test_explanation
# pins this list and checks it against those kinds of word.
FUNCTION_WORDS = frozenset("""a an the this that these those it its is are was were be been has have had
of in on at to from by for with as and or which during between before after""".split())
EVIDENCE_NOUNS = frozenset("""change check checks route routes frame frames tick ticks player object px pixel
pixels tolerance limit bound measured measurement measurements value values recorded observer observers
engine vision record evidence finding findings sample run replay replays result results reading readings
window""".split())
NEUTRAL = FUNCTION_WORDS | EVIDENCE_NOUNS
# Comparison words, allowed only where the cited evidence holds them: "same" where every cited id has
# a before and an after verdict and they are equal; "difference" where some cited id's differ.
SAME_WORDS = frozenset("same unchanged identical alike".split())
DIFFERENT_WORDS = frozenset("difference differences different differs differ changed".split())
# Never allowed: a word that limits or widens what the evidence covers has no verdict to match.
SCOPE = frozenset("""only just merely solely simply purely except also too even both either other others
another else than more most less least few many much some any several mostly mainly""".split())
# Verdict words: allowed only where the point states the matching verdict after the change.
FAIL_WORDS = frozenset("fail fails failed failing failure regression regressed".split())
PASS_WORDS = frozenset("pass passes passed passing fixed".split())
# Decision words: allowed only when they are the verifier's decision.
DECISION_WORDS = {"accept": frozenset("accept accepted".split()), "reject": frozenset("reject rejected".split())}
# Never allowed, even when the verifier's own wording of a finding has them: what a negated or
# over-certain sentence says cannot be matched to a verdict. Named so the page can say why.
NEGATIONS = frozenset("not no never nor neither without cannot cant longer none nothing".split())
CERTAINTY = frozenset("""prove proves proved proven proof guarantee guarantees guaranteed certain certainly
definitely always all every everything entire entirely whole completely totally fully""".split())
NUMBER_WORDS = frozenset("""zero one two three four five six seven eight nine ten eleven twelve thirteen
fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety
hundred hundreds thousand thousands million half twice double triple dozen""".split())
TOKEN = re.compile(r"check:[a-z0-9-]+@[a-z0-9-]+|[0-9a-f]{12}(?![0-9a-z])|[0-9]+(?:\.[0-9]+)?"
                   r"|[a-z0-9]+(?:['-][a-z0-9]+)*")
NUMBER = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")


class ExplanationError(ValueError):
    pass


# --- the evidence an explanation may cite ---------------------------------------------------------

def evidence(record: dict) -> dict[str, dict]:
    """id -> {"before", "after", "text"} for every finding and every check in the record. ``text``
    is what a point citing it may take its numbers from."""
    out: dict[str, dict] = {}
    for c in record.get("checks") or []:
        cid = f"check:{c['spec']}@{c['route']}"
        out[cid] = {
            "before": c.get("before"), "after": c.get("after"),
            "text": " ".join(str(c.get(k) or "") for k in ("spec", "route", "comparison")),
            "names": {cid, c["spec"], c["route"]}, "words": _words(str(c.get("comparison") or ""))}
    for f in record.get("findings") or []:
        out[f["id"]] = {
            "before": f.get("before"), "after": f.get("after"),
            "text": " ".join(str(f.get(k) if f.get(k) is not None else "")
                             for k in ("spec", "route", "comparison", "reason", "frame")),
            "names": {f["id"], f["spec"], f["route"]},
            "words": _words(f"{f.get('comparison') or ''} {f.get('reason') or ''}")}
    return out


def _words(text: str) -> set[str]:
    """The verifier's own words for a piece of evidence (its comparison and reason), which a point
    citing it may reuse. A spec's name is not split into words: "player-stays-above-ground" names the
    check; "the player stays above ground" would be a claim."""
    return ({t for t in TOKEN.findall(text.lower()) if not t[0].isdigit()}
            - NEGATIONS - CERTAINTY - SCOPE - SAME_WORDS - DIFFERENT_WORDS)


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
    stated_after = [sides["after"] for cid, sides in point["says"].items()
                    if cid in point["cites"] and "after" in sides]
    numbers, words_ok, names = set(), set(NEUTRAL), set()
    for cid in point["cites"]:
        numbers |= _numbers(known[cid]["text"])
        words_ok |= known[cid]["words"]
        names |= known[cid]["names"]
    words, unknown_words = set(), []
    for t in TOKEN.findall(text.lower()):
        if t in names:
            continue
        if t[0].isdigit() and NUMBER.fullmatch(t):
            if _number(t) not in numbers:
                problems.append(f"the number {t} is not in the evidence it cites")
            continue
        words.add(t)
    if words & NUMBER_WORDS:
        problems.append(f"it writes a number in words ({', '.join(sorted(words & NUMBER_WORDS))}); "
                        "numbers are compared as digits")
    if words & NEGATIONS or any(w.endswith("n't") for w in words):
        problems.append("it negates something, and what a negated sentence says cannot be matched to a verdict")
    if words & CERTAINTY:
        problems.append(f"it says {', '.join(sorted(words & CERTAINTY))}, which claims more than these "
                        "checks on these routes")
    fail_words, pass_words = words & FAIL_WORDS, words & PASS_WORDS
    if fail_words and "fail" not in stated_after:
        problems.append(f"it says {', '.join(sorted(fail_words))} without stating a failing verdict after the change")
    if pass_words and (not stated_after or any(v != "pass" for v in stated_after)):
        problems.append(f"it says {', '.join(sorted(pass_words))}, but not every verdict it states after the "
                        "change is pass")
    if words & SCOPE:
        problems.append(f"it says {', '.join(sorted(words & SCOPE))}, which limits or widens what the "
                        "evidence covers, and that cannot be matched to a verdict")
    sides = [(known[cid]["before"], known[cid]["after"]) for cid in point["cites"]]
    same_words, different_words = words & SAME_WORDS, words & DIFFERENT_WORDS
    if same_words and not (sides and all(b is not None and b == a for b, a in sides)):
        problems.append(f"it says {', '.join(sorted(same_words))}, but not every verdict it cites is the "
                        "same before and after the change")
    if different_words and not any(b is not None and a is not None and b != a for b, a in sides):
        problems.append(f"it says {', '.join(sorted(different_words))}, but no verdict it cites differs "
                        "before and after the change")
    decision_words = set().union(*DECISION_WORDS.values()) & words
    if decision_words - DECISION_WORDS.get(decision, frozenset()):
        problems.append(f"it says {', '.join(sorted(decision_words))}, but the decision is {decision}")
    named = (NUMBER_WORDS | NEGATIONS | CERTAINTY | SCOPE | SAME_WORDS | DIFFERENT_WORDS | FAIL_WORDS
             | PASS_WORDS | decision_words)
    unknown_words = sorted(w for w in words - words_ok - named if not w.endswith("n't"))
    if unknown_words:
        problems.append(f"it uses words Expectrail cannot match to the evidence ({', '.join(unknown_words[:8])}"
                        + (", ..." if len(unknown_words) > 8 else "") + ")")
    return problems


def shown(doc, record: dict | None, decision: str | None) -> dict:
    """What the viewer embeds: the points when the check passes, otherwise only why it was withheld."""
    problems = check(doc, record, decision)
    author = doc.get("author") if isinstance(doc, dict) and isinstance(doc.get("author"), dict) else {}
    out = {"model": str(author.get("model") or "unknown")[:80], "recorded": author.get("recorded") is True}
    if problems:
        return dict(out, shown=False, withheld=problems[:10])
    return dict(out, shown=True, points=[
        {"text": p["text"], "cites": list(p["cites"]),
         "verdicts": [[cid, sides.get("before"), sides.get("after")] for cid, sides in p["says"].items()]}
        for p in doc["points"]])


# --- the writer -----------------------------------------------------------------------------------

def prompt(record: dict) -> str:
    """The question for a model. It states the decision and the evidence; it asks for no decision."""
    lines = [
        "Explain this Expectrail verification result to someone who has not seen it.",
        f"The verifier's decision is: {record['decision']}. Do not decide anything; do not restate the decision.",
        "Answer with JSON only: {\"points\": [{\"text\": ..., \"cites\": [ids], \"says\": {id: {\"before\": v, "
        "\"after\": v}}}]}, 1 to 8 points, each text at most 400 printable ASCII characters.",
        "Every point cites the evidence ids it is about. In says, state the verdicts the point relies on, "
        "exactly as listed below. Use only these words: the ids and names of the evidence the point cites, "
        "the words of that evidence's own description below, the verdict words pass, passes, passed, fixed, "
        "fail, fails, failed, regression (only where the point states that verdict after the change), and: "
        + " ".join(sorted(NEUTRAL)) + ". Say same or unchanged only where every cited verdict is the same "
        "before and after the change, and difference or changed only where one differs. Any other word "
        "withholds the point. Write numbers as digits, and "
        "only numbers that appear in the cited evidence. Do not negate anything.",
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
