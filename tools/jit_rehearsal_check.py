"""What the generated-checks rehearsal in .github/workflows/jit.yml expects of each case (#675).

    python3 -m tools.jit_rehearsal_check CASE runs/jit/CASE/jit-run.json

Before the do-nothing control (#675, piece 1) the rehearsal proved two things: the plumbing runs end to
end, and the comment-only "fix" of air-jump is caught strongly. The stand-in's only catching check, "eight
presses give no more air jumps than two", passes a frozen player, so the control now drops it and the
comment-only case keeps no valid check and no catch. Sean accepted that reach cost on November 20.

So the rehearsal now proves the plumbing and that the control fires on a real run. It no longer covers
"a strong catch is produced": that is lost reach, disclosed here and in the work log, not a repair. A
rehearsal whose checks survive the control would bring it back (tracked as its own issue).
"""
from __future__ import annotations

import json
import sys

from expectrail.jit.assess import DO_NOTHING_PASSED

CASES = ("air-jump-undo", "air-jump-comment-only")
FROZEN_PLAYER_CHECK = "jit-no-extra-air-jumps"


def check(case: str, run: dict) -> list[str]:
    """The problems with one rehearsal run; empty when it reached what it rehearses."""
    if case not in CASES:
        return [f"unknown rehearsal case {case!r}: expected one of {', '.join(CASES)}"]
    problems: list[str] = []
    if run.get("status") != "complete":
        problems.append(f"the run did not complete: {run.get('status')!r}, {run.get('reason')!r}")
    rows = {r.get("specId"): r for r in run.get("validity") or []}
    frozen = rows.get(FROZEN_PLAYER_CHECK)
    dropped = (frozen is not None and frozen.get("valid") is False
               and DO_NOTHING_PASSED in (frozen.get("reasons") or [])
               and (frozen.get("doNothing") or {}).get("outcome") == "passes")
    if not dropped:
        problems.append(f"the do-nothing control did not drop {FROZEN_PLAYER_CHECK}, which passes a frozen "
                        "player: the control did not run on the real engine, or the rule moved")
    valid = (run.get("counts") or {}).get("valid", 0)
    catches = run.get("catches") or []
    if case == "air-jump-undo":
        if valid < 1:
            problems.append("no generated check was valid")
        if catches:
            problems.append("the exact undo was caught")
    else:
        if valid != 0 or catches:
            problems.append(f"the comment-only case now has {valid} valid check(s) and {len(catches)} catch(es); "
                            "since the do-nothing control it was expected to keep none. Revisit this expectation "
                            "and the lost-reach disclosure in the work log (#675)")
    return problems


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: python3 -m tools.jit_rehearsal_check CASE JIT_RUN_JSON", file=sys.stderr)
        return 2
    case, path = argv
    with open(path, encoding="utf-8") as f:
        run = json.load(f)
    problems = check(case, run)
    for p in problems:
        print(f"rehearsal {case}: {p}", file=sys.stderr)
    if not problems:
        print(f"rehearsal {case}: reached what it rehearses (valid {run['counts'].get('valid')}, "
              f"catches {len(run.get('catches') or [])}, {FROZEN_PLAYER_CHECK} dropped by the do-nothing control)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
