"""Issue #560: a declared fix whose check failed before the change but could not be decided after it.

The decision stays needs-review. The words must match the record: the check did fail before the
change, so "none of the checks failed before the change" and "no check reproduced the bug" are wrong.
Offline: the gate tests' stand-in replays and stand-in vision; no engine, no model.
"""
from __future__ import annotations

import unittest

from expectrail.gate import comment as gc
from expectrail.gate import record as rec
from expectrail.orchestrator import cli
from tests.test_ci_gate import GateCase, ctx, make_repo
from tests.test_gate_intent import FAIL3, PASS3, ZERO, block
from tests.test_two_observers import Case, repo

UNDECIDED = dict(checks=1, passed=0, failed=0, needsReview=1)
WRONG = ("none of the", "no check reproduced")


class TheReason(unittest.TestCase):
    def test_a_base_failure_with_an_undecided_head_is_named(self):
        decision, reasons = rec.decide(UNDECIDED, ZERO, intent="fix", repair=block(), undecided_after_failure=1)
        self.assertEqual(decision, "needs-review")
        first = reasons[0]
        self.assertTrue(first.startswith("repair-not-demonstrated: this change is declared as a fix, and "), first)
        self.assertIn("1 check failed before the change but could not be decided after the change", first)
        for wrong in WRONG:
            self.assertNotIn(wrong, first.lower())
        self.assertIn("1 of 1 public checks could not be decided", reasons)

    def test_the_count_is_plural_and_joins_rows_that_did_not_count(self):
        two = dict(UNDECIDED, checks=2, needsReview=2)
        self.assertIn("2 checks failed before the change but could not be decided",
                      rec.decide(two, ZERO, intent="fix", repair=block(), undecided_after_failure=2)[1][0])
        mixed = rec.decide(dict(two, passed=1, needsReview=1), ZERO, intent="fix",
                           repair=block((["fail", "pass", "pass"], PASS3)), undecided_after_failure=1)[1][0]
        self.assertIn("1 check failed before the change and passed after it once, but not 3 times of 3", mixed)
        self.assertIn("; 1 other check failed before the change and could not be decided after the change", mixed)

    def test_it_only_words_the_reason_and_never_changes_a_decision(self):
        cases = [UNDECIDED, dict(UNDECIDED, checks=2, failed=1), dict(UNDECIDED, checks=2, passed=1),
                 {"checks": 0, "passed": 0, "failed": 0, "needsReview": 0}]
        for counts in cases:
            for intent in rec.INTENTS:
                for repair in (block(), block((FAIL3, PASS3)), None):
                    plain = rec.decide(counts, ZERO, intent=intent, repair=repair)[0]
                    worded = rec.decide(counts, ZERO, intent=intent, repair=repair, undecided_after_failure=3)[0]
                    self.assertEqual(plain, worded, (counts, intent, repair))

    def test_what_counts_as_undecided_after_a_failure(self):
        rows = [dict(before=b, after=a) for b, a in (
            ("fail", "needs-review"), ("fail", "replay-error"),            # these two
            ("fail", "pass"), ("fail", "fail"), ("fail", "not-applicable"),
            ("pass", "needs-review"), (None, "needs-review"), ("needs-review", "needs-review"))]
        self.assertEqual(rec.undecided_after_failure(rows), 2)

    def test_the_headline_follows_the_record_and_falls_back_to_the_reason(self):
        self.assertEqual(rec.unverified_fix_headline({"checks": [dict(before="fail", after="needs-review")]}),
                         rec.UNDECIDED_FIX)
        self.assertEqual(rec.unverified_fix_headline({"checks": [dict(before="pass", after="pass")]}),
                         rec.UNVERIFIED_FIX)
        said = rec.decide(UNDECIDED, ZERO, intent="fix", repair=block(), undecided_after_failure=1)[1]
        self.assertEqual(rec.unverified_fix_headline({"reasons": said}), rec.UNDECIDED_FIX)
        none = rec.decide(dict(UNDECIDED, passed=1, needsReview=0), ZERO, intent="fix", repair=block())[1]
        self.assertEqual(rec.unverified_fix_headline({"reasons": none}), rec.UNVERIFIED_FIX)
        # A reason that only mentions the words but is not the repair reason does not count.
        self.assertEqual(rec.unverified_fix_headline({"reasons": ["x " + rec.UNDECIDED_AFTER]}), rec.UNVERIFIED_FIX)


class TheJobStatus(unittest.TestCase):
    def status(self, reasons):
        return {"id": "j1", "phase": "completed", "decision": "needs-review", "reasons": reasons,
                "diagnostics": [], "evidenceGrade": None}

    def test_the_command_line_leads_with_what_the_record_shows(self):
        undecided = rec.decide(UNDECIDED, ZERO, intent="fix", repair=block(), undecided_after_failure=1)[1]
        text = cli.describe(self.status(undecided))
        self.assertTrue(text.startswith(rec.UNDECIDED_FIX), text)
        self.assertNotIn("No check reproduced", text)
        nothing = rec.decide(dict(UNDECIDED, passed=1, needsReview=0), ZERO, intent="fix", repair=block())[1]
        self.assertTrue(cli.describe(self.status(nothing)).startswith(rec.UNVERIFIED_FIX))


class WithoutVision(Case):
    """The tester's run: the bug on the base, the repair on the head, and no vision key. The engine's
    record fails the base and passes the head, so the base is a failure and the head needs review."""

    def test_the_record_the_comment_and_the_page_say_the_check_failed_before(self):
        doc = self.gate(repo(self.tmp / "head"), base=repo(self.tmp / "base", "BUG"), intent="fix", visual=None)
        self.assertEqual(doc["decision"], "needs-review")
        row = self.row(doc)
        self.assertEqual((row["before"], row["after"]), ("fail", "needs-review"))
        first = doc["reasons"][0]
        self.assertIn("1 check failed before the change but could not be decided after the change", first)
        for wrong in WRONG:
            self.assertNotIn(wrong, first.lower())
        rec.read_record(self.out / "findings.json")           # the reader recomputes the same decision
        lead = gc.render(doc, ctx()).split("\n")[3]
        self.assertTrue(lead.startswith(f"**{rec.UNDECIDED_FIX}.**"), lead)
        self.assertIn("1 check failed before the change and could not be decided after it", lead)
        page = (self.out / "review" / "index.html").read_text(encoding="utf-8")
        self.assertIn(rec.UNDECIDED_FIX, page)
        self.assertNotIn(rec.UNVERIFIED_FIX, page)


class HeadDoesNotFinish(GateCase):
    def test_a_head_replay_that_does_not_finish_is_named_the_same_way(self):
        doc = self.gate(make_repo(self.tmp / "head", crash=True), make_repo(self.tmp / "base", bug=True), intent="fix")
        self.assertEqual(doc["decision"], "needs-review")
        self.assertEqual({(c["before"], c["after"]) for c in doc["checks"]}, {("fail", "replay-error")})
        self.assertIn("2 checks failed before the change but could not be decided after the change", doc["reasons"][0])
        lead = gc.render(doc, ctx()).split("\n")[3]
        self.assertTrue(lead.startswith(f"**{rec.UNDECIDED_FIX}.**"), lead)

    def test_a_fix_whose_base_passes_keeps_the_old_words(self):
        doc = self.gate(make_repo(self.tmp / "head"), make_repo(self.tmp / "base"), intent="fix")
        self.assertIn("none of the 2 checks that ran failed before the change", doc["reasons"][0])
        self.assertTrue(gc.render(doc, ctx()).split("\n")[3].startswith(f"**{rec.UNVERIFIED_FIX}.**"))


if __name__ == "__main__":
    unittest.main()
