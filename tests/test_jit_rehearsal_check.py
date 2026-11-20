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


STRONG_CASE = "gun-cooldown-long-comment-only"


def _gun_run(control="fails", strength="strong", valid=True, candidate=("fail",) * 3, base=("fail",) * 3,
             status="complete", n=6):
    """The shape recorded on Godot 4.7.2 with the workflow's own command, 2026-11-20 (#691): six recorded
    checks, each failing the do-nothing control 3 of 3, valid, and a strong catch of the comment-only fix."""
    rows, catches = [], []
    for i in range(1, n + 1):
        spec = f"jit-c{i}"
        runs = {"fails": ["fail"] * 3, "passes": ["pass"] * 3, "indeterminate": ["not_exercised"] * 3}[control]
        reasons = [] if valid else [DO_NOTHING_PASSED if control == "passes" else "killed no near-miss variant"]
        rows.append({"specId": spec, "valid": valid, "reasons": reasons, "killed": ["base"] if valid else [],
                     "candidate": list(candidate),
                     "doNothing": {"control": "do-nothing:projectile", "runs": runs, "outcome": control,
                                   "reason": None}})
        if valid and list(candidate) == ["fail"] * 3:
            catches.append({"specId": spec, "strength": strength, "candidate": list(candidate), "base": list(base)})
    return {"status": status, "reason": None, "validity": rows, "catches": catches,
            "counts": {"proposed": n, "valid": sum(r["valid"] for r in rows),
                       "strong": sum(c["strength"] == "strong" for c in catches),
                       "weak": sum(c["strength"] == "weak" for c in catches)}}


class StrongCatchCase(unittest.TestCase):
    """#691: a case whose checks survive the do-nothing control and still catch a comment-only fix strongly."""

    def test_what_the_engine_gave_passes(self):
        self.assertEqual(rc.check(STRONG_CASE, _gun_run()), [])

    def test_no_catch_fails(self):
        problems = rc.check(STRONG_CASE, _gun_run(candidate=("pass",) * 3))
        self.assertTrue(any("no strong catch" in p for p in problems), problems)

    def test_a_weak_catch_is_not_enough(self):
        problems = rc.check(STRONG_CASE, _gun_run(strength="weak", base=("pass",) * 3))
        self.assertTrue(any("no strong catch" in p for p in problems), problems)

    def test_a_catch_the_control_did_not_fail_is_not_enough(self):
        # Indeterminate (a gap, not exercised) does not drop a check, but it does not show the check states an
        # obligation either: the case must show a catch by a check the frozen actor fails.
        problems = rc.check(STRONG_CASE, _gun_run(control="indeterminate"))
        self.assertTrue(any("do-nothing control" in p for p in problems), problems)

    def test_a_valid_check_that_passes_the_control_is_reported(self):
        run = _gun_run()
        run["validity"][0]["doNothing"].update(outcome="passes", runs=["pass"] * 3)
        problems = rc.check(STRONG_CASE, run)
        self.assertTrue(any("passes the do-nothing control" in p for p in problems), problems)

    def test_a_strong_label_without_three_failures_on_base_and_candidate_fails(self):
        problems = rc.check(STRONG_CASE, _gun_run(base=("fail", "fail", "pass")))
        self.assertTrue(any("no strong catch" in p for p in problems), problems)
        run = _gun_run()
        for c in run["catches"]:
            c["candidate"] = ["fail", "fail"]
        problems = rc.check(STRONG_CASE, run)
        self.assertTrue(any("no strong catch" in p for p in problems), problems)

    def test_only_a_catch_labelled_strong_counts(self):
        # Three failures on the base with a weak label: the assessor did not call it strong, so neither does this.
        problems = rc.check(STRONG_CASE, _gun_run(strength="weak"))
        self.assertTrue(any("no strong catch" in p for p in problems), problems)

    def test_a_catch_with_no_validity_row_fails(self):
        run = _gun_run()
        run["validity"] = []
        problems = rc.check(STRONG_CASE, run)
        self.assertTrue(any("no strong catch" in p for p in problems), problems)

    def test_an_incomplete_run_fails(self):
        self.assertTrue(rc.check(STRONG_CASE, _gun_run(status="failed")))

    def test_the_air_jump_frozen_player_check_is_not_asked_of_it(self):
        # Its checks are about the projectile; the air-jump stand-in's check id is not expected here.
        self.assertFalse(any(rc.FROZEN_PLAYER_CHECK in p for p in rc.check(STRONG_CASE, _gun_run())))


class WorkflowMatrixMatchesTheCheck(unittest.TestCase):
    """Every rehearsal case the workflow runs is one the check knows, with its committed files present."""

    def test_matrix(self):
        import yaml
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        wf = yaml.safe_load((root / ".github/workflows/jit.yml").read_text())
        include = wf["jobs"]["rehearsal"]["strategy"]["matrix"]["include"]
        self.assertEqual(sorted(c["case"] for c in include), sorted(rc.CASES))
        for c in include:
            for key in ("report", "base"):
                self.assertTrue((root / c[key]).is_file(), (c["case"], key, c[key]))
            self.assertTrue((root / "bench/jit/rehearsal" / f"{c['case']}.patch").is_file(), c["case"])
            self.assertTrue((root / "bench/jit/rehearsal" / c["case"] / "jit-proposal.json").is_file(), c["case"])
        step = next(s for s in wf["jobs"]["rehearsal"]["steps"] if s.get("name") == "Replay the stand-in proposal")
        self.assertIn('--report-file "$REPORT"', step["run"])
        self.assertIn('--base "$BASE"', step["run"])
        self.assertEqual(step["env"]["REPORT"], "${{ matrix.report }}")
        self.assertEqual(step["env"]["BASE"], "${{ matrix.base }}")

    def test_the_stand_in_is_the_recorded_checks_unchanged(self):
        # The gun-cooldown-long stand-ins are copied from the hosted record of run 43465090517, not written
        # for this rehearsal: the same specs and probes, nothing tuned.
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        rec = json.loads((root / "bench/jit/recordings/public-43465090517/repro/repro-gun-cooldown-long/"
                                  "jit-run.json").read_text())
        stand_in = json.loads((root / "bench/jit/rehearsal" / STRONG_CASE / "jit-proposal.json").read_text())
        self.assertEqual([(c["spec"], c["applies"]) for c in stand_in["candidates"]],
                         [(p["spec"], p["applies"]) for p in rec["proposed"]])


if __name__ == "__main__":
    unittest.main()
