"""What the generated-checks rehearsal in jit.yml expects of each case (#675, piece 1).

Since the do-nothing control, the air-jump stand-in's only catching check ("eight presses give no more air
jumps than two") passes a frozen player and is dropped. The comment-only case therefore keeps no valid
check and no catch: that is lost reach, disclosed, not a repair. These tests pin the expectation so the
rehearsal still proves the plumbing and that the control fires on a real run.
"""
import unittest

from expectrail.jit.assess import DO_NOTHING_PASSED
from tools import jit_rehearsal_check as rc


def _row(spec, valid, reasons, outcome):
    return {"specId": spec, "valid": valid, "reasons": reasons,
            "doNothing": {"control": "do-nothing:player", "runs": ["pass"] * 3 if outcome == "passes" else [],
                          "outcome": outcome}}


def _run(valid_still_works=False, extra_dropped=True, catches=(), status="complete"):
    rows = []
    if extra_dropped:
        rows.append(_row("jit-no-extra-air-jumps", False, [DO_NOTHING_PASSED], "passes"))
    else:
        rows.append(_row("jit-no-extra-air-jumps", True, [], "fails"))
    rows.append(_row("jit-air-jump-still-works", valid_still_works,
                     [] if valid_still_works else ["killed no near-miss variant"], "fails"))
    rows.append(_row("jit-rise-bounded", False, ["killed no near-miss variant"], "indeterminate"))
    valid = sum(1 for r in rows if r["valid"])
    return {"status": status, "reason": None, "validity": rows, "catches": list(catches),
            "counts": {"proposed": 3, "valid": valid, "strong": 0, "weak": 0}}


class RehearsalExpectation(unittest.TestCase):
    def test_what_the_engine_gave_on_both_cases_passes(self):
        # The shapes recorded on Godot 4.7.2 with the workflow's own command, 2026-11-20.
        self.assertEqual(rc.check("air-jump-undo", _run(valid_still_works=True)), [])
        self.assertEqual(rc.check("air-jump-comment-only", _run()), [])

    def test_an_incomplete_run_fails(self):
        self.assertTrue(rc.check("air-jump-undo", _run(valid_still_works=True, status="failed")))

    def test_the_control_must_fire_on_a_real_run(self):
        # If the frozen-player check is no longer dropped, the control did not run or the rule moved.
        problems = rc.check("air-jump-comment-only", _run(extra_dropped=False))
        self.assertTrue(any("do-nothing control" in p for p in problems), problems)
        problems = rc.check("air-jump-undo", _run(valid_still_works=True, extra_dropped=False))
        self.assertTrue(any("do-nothing control" in p for p in problems), problems)

    def test_a_drop_must_carry_the_controls_reason_and_outcome(self):
        run = _run()
        run["validity"][0]["doNothing"]["outcome"] = "fails"
        self.assertTrue(rc.check("air-jump-comment-only", run))

    def test_the_exact_undo_must_not_be_caught(self):
        run = _run(valid_still_works=True, catches=[{"specId": "x", "strength": "strong"}])
        self.assertTrue(any("exact undo was caught" in p for p in rc.check("air-jump-undo", run)))

    def test_the_undo_still_needs_one_valid_check(self):
        self.assertTrue(any("no generated check was valid" in p
                            for p in rc.check("air-jump-undo", _run(valid_still_works=False))))

    def test_comment_only_reach_returning_is_reported_not_hidden(self):
        # A valid check or a catch on the comment-only case means the stand-ins changed or the control
        # stopped dropping: the expectation (and the disclosure in the work log) must be revisited.
        for run in (_run(valid_still_works=True),
                    _run(catches=[{"specId": "x", "strength": "strong"}])):
            problems = rc.check("air-jump-comment-only", run)
            self.assertTrue(any("revisit" in p.lower() for p in problems), problems)

    def test_an_unknown_case_fails_closed(self):
        self.assertTrue(rc.check("something-else", _run()))

    def test_main_returns_nonzero_on_a_problem(self):
        import contextlib, io, json, os, tempfile
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            p = os.path.join(d, "jit-run.json")
            with open(p, "w") as f:
                json.dump(_run(extra_dropped=False), f)
            self.assertEqual(rc.main(["air-jump-comment-only", p]), 1)
            with open(p, "w") as f:
                json.dump(_run(), f)
            self.assertEqual(rc.main(["air-jump-comment-only", p]), 0)


if __name__ == "__main__":
    unittest.main()
