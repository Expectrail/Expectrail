"""What the generated-checks rehearsal in .github/workflows/jit.yml expects of each case (#675).

    python3 -m tools.jit_rehearsal_check CASE runs/jit/CASE/jit-run.json

Before the do-nothing control (#675, piece 1) the rehearsal proved two things: the plumbing runs end to
end, and the comment-only "fix" of air-jump is caught strongly. The stand-in's only catching check, "eight
presses give no more air jumps than two", passes a frozen player, so the control now drops it and the
comment-only case keeps no valid check and no catch. Sean accepted that reach cost on November 20.

So the rehearsal now proves the plumbing and that the control fires on a real run. It no longer covers
"a strong catch is produced": that is lost reach, disclosed here and in the work log, not a repair. A
rehearsal whose checks survive the control would bring it back (tracked as its own issue).

That coverage is back with a third case (#691), gun-cooldown-long-comment-only: the public bench defect whose
gun cooldown is five times too long, "fixed" with one comment line in player/gun.gd. Its stand-ins are the six
checks the hosted baseline record proposed for that defect (run 43465090517), copied unchanged: "the gun fires
at least twice (or three times) on these shooting routes". The do-nothing control (a gun that never makes a
projectile) fails each of them, so they state an obligation, and they fail 3 of 3 on the bug build and on the
comment-only fix: a strong catch. The case asserts exactly that, and fails closed on anything less.
"""
from __future__ import annotations

import json
import sys

from expectrail.jit.assess import DO_NOTHING_PASSED

AIR_JUMP_CASES = ("air-jump-undo", "air-jump-comment-only")
STRONG_CATCH_CASES = ("gun-cooldown-long-comment-only",)
CASES = AIR_JUMP_CASES + STRONG_CATCH_CASES
FROZEN_PLAYER_CHECK = "jit-no-extra-air-jumps"
THREE_FAILS = ["fail", "fail", "fail"]


def _strong_catch(run: dict) -> list[str]:
    """A strong catch by a check that states an obligation: valid, failed 3 of 3 by the do-nothing control,
    and failing 3 of 3 on the base build and on the candidate. Anything less is no strong catch."""
    problems: list[str] = []
    rows = {r.get("specId"): r for r in run.get("validity") or [] if isinstance(r, dict)}
    for spec, row in rows.items():
        if row.get("valid") is True and (row.get("doNothing") or {}).get("outcome") == "passes":
            problems.append(f"{spec} is counted valid but passes the do-nothing control: the control's rule moved")
    good, weak_control = [], []
    for c in run.get("catches") or []:
        if not isinstance(c, dict):
            continue
        row = rows.get(c.get("specId"))
        if (c.get("strength") != "strong" or list(c.get("candidate") or []) != THREE_FAILS
                or list(c.get("base") or []) != THREE_FAILS or row is None or row.get("valid") is not True):
            continue
        control = row.get("doNothing") or {}
        if control.get("outcome") == "fails" and list(control.get("runs") or []) == THREE_FAILS:
            good.append(c["specId"])
        else:
            weak_control.append(c["specId"])
    if not good:
        if weak_control:
            problems.append("no strong catch by a check the do-nothing control fails 3 of 3: "
                            f"{', '.join(weak_control)} caught, but the control did not fail them, so they do not "
                            "show an obligation the frozen actor misses")
        else:
            problems.append("no strong catch: no valid check failed 3 of 3 on both the bug build and the "
                            "comment-only fix")
    return problems


def check(case: str, run: dict) -> list[str]:
    """The problems with one rehearsal run; empty when it reached what it rehearses."""
    if case not in CASES:
        return [f"unknown rehearsal case {case!r}: expected one of {', '.join(CASES)}"]
    problems: list[str] = []
    if run.get("status") != "complete":
        problems.append(f"the run did not complete: {run.get('status')!r}, {run.get('reason')!r}")
    if case in STRONG_CATCH_CASES:
        return problems + _strong_catch(run)
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
    if not problems and case in STRONG_CATCH_CASES:
        strong = sum(1 for c in run.get("catches") or [] if c.get("strength") == "strong")
        print(f"rehearsal {case}: reached what it rehearses (valid {run['counts'].get('valid')}, strong catches "
              f"{strong}, each failed by the do-nothing control)")
    elif not problems:
        print(f"rehearsal {case}: reached what it rehearses (valid {run['counts'].get('valid')}, "
              f"catches {len(run.get('catches') or [])}, {FROZEN_PLAYER_CHECK} dropped by the do-nothing control)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
