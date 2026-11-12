"""Issue #284: a change declared a fix is accepted only when a check demonstrates the repair.
Offline: the gate tests' fake replay (fixture traces judged by the real evaluator); no engine, no model."""
from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path

import jsonschema

from expectrail.gate import comment as gc
from expectrail.gate import record as rec
from expectrail.gate import verify as gv
from tests.test_ci_gate import BASE, HEAD, REPO, FakeReplay, GateCase, ctx, make_repo

EXAMPLE = REPO / "contracts" / "examples" / "findings-fix-not-demonstrated.json"
ZERO = {"status": "not-used", "routes": 0, "checks": 0, "passed": 0, "failed": 0, "needsReview": 0}
OK = {"checks": 2, "passed": 2, "failed": 0, "needsReview": 0}
FAIL3, PASS3 = ["fail"] * 3, ["pass"] * 3


def block(*rows):
    return rec.repair_block([{"spec": "s", "route": f"r{n}", "base": b, "head": h} for n, (b, h) in enumerate(rows)])


class FlakyBase(FakeReplay):
    """The base game (it holds BUG) shows the bug only on its first replay of each route."""

    def __call__(self, route: Path, game: Path, out: Path, frames: bool) -> dict:
        seen = sum(1 for name, g, _f in self.calls if name == route.name and g == str(game))
        if (game / "BUG").exists() and seen >= 1:
            (game / "BUG").rename(game / "BUG.off")
            try:
                return super().__call__(route, game, out, frames)
            finally:
                (game / "BUG.off").rename(game / "BUG")
        return super().__call__(route, game, out, frames)


class TheRule(GateCase):
    def test_a_fix_with_no_demonstration_is_needs_review_never_accept(self):
        for repair in (block(), None, block((["fail", "pass", "fail"], PASS3)), block((FAIL3, ["pass", "pass", "fail"]))):
            decision, reasons = rec.decide(OK, ZERO, intent="fix", repair=repair)
            self.assertEqual(decision, "needs-review")
            self.assertTrue(reasons[0].startswith("repair-not-demonstrated: "), reasons)

    def test_a_fix_with_a_demonstration_is_accepted_and_says_so(self):
        decision, reasons = rec.decide(OK, ZERO, intent="fix", repair=block((FAIL3, PASS3)))
        self.assertEqual(decision, "accept")
        self.assertIn("the repair is demonstrated", reasons[0])

    def test_one_demonstration_is_enough_beside_rows_that_do_not_count(self):
        repair = block((["fail", "pass", "pass"], PASS3), (FAIL3, PASS3))
        self.assertEqual([r["counts"] for r in repair["rows"]], [False, True])
        self.assertEqual(rec.decide(OK, ZERO, intent="fix", repair=repair)[0], "accept")

    def test_a_check_still_failing_after_the_change_rejects_whatever_else_was_repaired(self):
        failing = dict(OK, passed=1, failed=1)
        for repair in (block(), block((FAIL3, PASS3))):
            self.assertEqual(rec.decide(failing, ZERO, intent="fix", repair=repair)[0], "reject")

    def test_what_counts_as_a_demonstration(self):
        for base, head, counts in ((FAIL3, PASS3, True), (["fail", "fail", "pass"], PASS3, False),
                                   (["fail", "fail", "needs-review"], PASS3, False),
                                   (["fail", "fail", "replay-error"], PASS3, False),
                                   (FAIL3, ["pass", "pass", "needs-review"], False), (FAIL3, ["pass", "fail", "pass"], False),
                                   (["fail"], ["pass"], False), (["fail", "fail"], ["pass", "pass"], False),
                                   (PASS3, PASS3, False), (FAIL3, FAIL3, False), (PASS3, FAIL3, False)):
            self.assertEqual(rec.row_counts({"base": base, "head": head}), counts, (base, head))

    def test_none_and_change_are_judged_exactly_as_before(self):
        cases = [(OK, ZERO), ({"checks": 0, "passed": 0, "failed": 0, "needsReview": 0}, ZERO),
                 (dict(OK, passed=1, needsReview=1), ZERO), (dict(OK, passed=1, failed=1), ZERO),
                 (OK, dict(ZERO, status="unavailable")), (OK, dict(ZERO, status="judged", routes=1, checks=1, failed=1))]
        for counts, held in cases:
            plain = rec.decide(counts, held)
            for intent in ("none", "change"):
                self.assertEqual(rec.decide(counts, held, intent=intent), plain, (intent, counts))
                self.assertEqual(rec.decide(counts, held, intent=intent, repair=block((FAIL3, PASS3))), plain)

    def test_fix_never_makes_a_decision_easier(self):
        order = {"accept": 0, "needs-review": 1, "reject": 2}
        counts_list = [OK, dict(OK, passed=1, needsReview=1), dict(OK, passed=1, failed=1),
                       {"checks": 0, "passed": 0, "failed": 0, "needsReview": 0}]
        helds = [ZERO, dict(ZERO, status="unavailable"), dict(ZERO, status="judged", routes=1, checks=1, failed=1)]
        for counts in counts_list:
            for held in helds:
                for problems in (0, 2):
                    plain = rec.decide(counts, held, None, problems)[0]
                    for repair in (block(), block((FAIL3, PASS3)), block((["fail", "pass", "pass"], PASS3))):
                        fix = rec.decide(counts, held, None, problems, intent="fix", repair=repair)[0]
                        self.assertGreaterEqual(order[fix], order[plain], (counts, held, problems))

    def test_the_reason_says_why_nothing_was_shown(self):
        said = lambda **kw: rec.decide(kw.pop("counts", OK), ZERO, intent="fix", **kw)[1]  # noqa: E731
        self.assertIn("none of the 2 checks that ran failed before the change", said(repair=block())[0])
        self.assertIn("the build before the change was not judged", said(repair=block(), base_judged=False)[0])
        self.assertIn("1 check failed before the change and passed after it once, but not 3 times of 3",
                      said(repair=block((["fail", "pass", "pass"], PASS3)))[0])
        none_ran = said(counts={"checks": 0, "passed": 0, "failed": 0, "needsReview": 0}, repair=block())
        self.assertEqual(none_ran[0], "no checks ran")
        self.assertIn("repair-not-demonstrated: ", none_ran[1])

    def test_an_intent_that_is_not_one_of_the_three_is_refused(self):
        for bad in ("Fix", "", "bugfix", None):
            with self.assertRaises(ValueError):
                rec.decide(OK, ZERO, intent=bad)


class TheGate(GateCase):
    def fix(self, head_bug=False, base_bug=False, base=True, **kw):
        head = make_repo(self.tmp / "head", bug=head_bug)
        return self.gate(head, make_repo(self.tmp / "base", bug=base_bug) if base else None, intent="fix", **kw)

    def replays(self, side):
        return [name for name, game, _f in self.replay.calls if f"/{side}/" in game + "/"]

    def test_a_fix_whose_base_passes_every_check_is_needs_review(self):
        doc = self.fix()
        self.assertEqual(doc["decision"], "needs-review")
        self.assertTrue(doc["reasons"][0].startswith("repair-not-demonstrated: "))
        self.assertEqual((doc["intent"], doc["repair"]), ("fix", {"runs": 3, "demonstrated": 0, "rows": []}))
        self.assertEqual({c["comparison"] for c in doc["checks"]}, {"PRESERVED"})
        self.assertEqual(len(self.replay.calls), 4)          # nothing was replayed again: no check claimed a repair
        rec.check_record(json.loads((self.tmp / "out" / "findings.json").read_text()))

    def test_the_same_change_with_nothing_declared_is_accepted_as_before(self):
        doc = self.gate(make_repo(self.tmp / "head"), make_repo(self.tmp / "base"))
        self.assertEqual((doc["decision"], rec.intent_of(doc)), ("accept", "none"))
        self.assertNotIn("repair", doc)
        self.assertNotIn("intent", doc)      # the record of an undeclared change has no new field: an older reader reads it
        again = self.gate(self.tmp / "head", self.tmp / "base", out_name="out2", intent="change")
        self.assertEqual((again["decision"], again["intent"]), ("accept", "change"))
        self.assertNotIn("repair", again)

    def test_a_fix_with_a_check_failing_on_the_base_and_passing_on_the_head_is_accepted(self):
        doc = self.fix(base_bug=True)
        self.assertEqual(doc["decision"], "accept")
        self.assertIn("the repair is demonstrated", doc["reasons"][0])
        self.assertEqual(doc["repair"]["demonstrated"], 2)
        for row in doc["repair"]["rows"]:
            self.assertEqual((row["base"], row["head"], row["counts"]), (FAIL3, PASS3, True))
        # each of the two routes: once to judge and twice more to confirm, on each side
        self.assertEqual(sorted(self.replays("base")), sorted(["smoke.json", "combat.json"] * 3))
        self.assertEqual(sorted(self.replays("head")), sorted(["smoke.json", "combat.json"] * 3))

    def test_a_fix_whose_check_still_fails_on_the_head_is_rejected(self):
        doc = self.fix(head_bug=True, base_bug=True)
        self.assertEqual(doc["decision"], "reject")
        self.assertEqual({c["comparison"] for c in doc["checks"]}, {"UNRESOLVED"})
        self.assertEqual(doc["repair"]["rows"], [])

    def test_a_flaky_base_failure_does_not_count_as_a_demonstration(self):
        self.replay = FlakyBase()
        doc = self.fix(base_bug=True)
        self.assertEqual(doc["decision"], "needs-review")
        self.assertEqual({c["comparison"] for c in doc["checks"]}, {"REPAIRED"})     # one run each would have said so
        self.assertEqual(doc["repair"]["demonstrated"], 0)
        for row in doc["repair"]["rows"]:
            self.assertEqual((row["base"], row["counts"]), (["fail", "pass", "pass"], False))
        self.assertIn("failed before the change and passed after it once, but not 3 times of 3", doc["reasons"][0])
        # and with nothing declared the same flaky run is accepted, as it was before this rule
        self.replay = FlakyBase()
        plain = self.gate(self.tmp / "head", self.tmp / "base", out_name="plain")
        self.assertEqual(plain["decision"], "accept")

    def test_a_fix_with_no_base_cannot_be_demonstrated(self):
        doc = self.fix(base=False)
        self.assertEqual(doc["decision"], "needs-review")
        self.assertIn("the build before the change was not judged", doc["reasons"][0])

    def test_a_confirming_replay_that_does_not_finish_does_not_count(self):
        class DiesLater(FakeReplay):
            def __call__(self, route, game, out, frames):
                if "run3" in str(out) and "base" in str(out):
                    raise SystemExit("godot failed (139)")
                return super().__call__(route, game, out, frames)

        self.replay = DiesLater()
        doc = self.fix(base_bug=True)
        self.assertEqual(doc["decision"], "needs-review")
        self.assertEqual(doc["repair"]["rows"][0]["base"], ["fail", "fail", "replay-error"])

    def test_only_the_routes_that_claim_a_repair_are_replayed_again(self):
        """One route shows the bug on the base and the other does not: only the first is confirmed."""
        class OneRoute(FakeReplay):
            def __call__(self, route, game, out, frames):
                if route.name == "combat.json" and (game / "BUG").exists():
                    (game / "BUG").rename(game / "BUG.off")
                    try:
                        return super().__call__(route, game, out, frames)
                    finally:
                        (game / "BUG.off").rename(game / "BUG")
                return super().__call__(route, game, out, frames)

        self.replay = OneRoute()
        doc = self.fix(base_bug=True)
        self.assertEqual(doc["decision"], "accept")
        self.assertEqual([(r["route"], r["counts"]) for r in doc["repair"]["rows"]], [("smoke", True)])
        self.assertEqual(self.replays("base").count("combat.json"), 1)
        self.assertEqual(self.replays("base").count("smoke.json"), 3)

    def test_an_unknown_intent_is_a_stopped_run_recorded_as_a_fix(self):
        with self.assertRaises(gv.ConfigError):
            self.gate(make_repo(self.tmp / "head"), intent="feature")
        stopped = gv.stopped_record("x", pr=None, game="game/platformer", checks_from="head",
                                    expectrail_commit=None, intent="feature")
        self.assertEqual((stopped["decision"], stopped["intent"], stopped["repair"]["demonstrated"]), ("needs-review", "fix", 0))
        plain = gv.stopped_record("x", pr=None, game="game/platformer", checks_from="head", expectrail_commit=None)
        self.assertNotIn("intent", plain)
        self.assertNotIn("repair", plain)

    def test_the_command_takes_the_intent_and_exits_as_needs_review(self):
        head, base = make_repo(self.tmp / "head"), make_repo(self.tmp / "base")
        args = ["--repo", str(head), "--game", "game/platformer", "--routes", "routes/*.json", "--specs", "specs",
                "--base", str(base), "--pr", "7", "--head-sha", HEAD, "--base-sha", BASE]
        real = gv.run_gate
        gv.run_gate = lambda **kw: real(replay=self.replay, **kw)      # the command itself, on the fake replay
        self.addCleanup(setattr, gv, "run_gate", real)
        codes = {}
        for intent in ("fix", "none", "nonsense"):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                codes[intent] = gv.main(args + ["--out", str(self.tmp / f"out-{intent}"), "--intent", intent])
        self.assertEqual(codes, {"fix": gv.EXIT["needs-review"], "none": gv.EXIT["accept"],
                                 "nonsense": gv.EXIT["needs-review"]})
        stopped = json.loads((self.tmp / "out-nonsense" / "findings.json").read_text())
        self.assertEqual(stopped["intent"], "fix")
        self.assertIn("the intent must be one of", stopped["reasons"][0])


class TheRecord(GateCase):
    def setUp(self):
        super().setUp()
        self.doc = self.gate(make_repo(self.tmp / "head"), make_repo(self.tmp / "base", bug=True), intent="fix")

    def refused(self, change, why):
        doc = copy.deepcopy(self.doc)
        change(doc)
        with self.assertRaises(rec.RecordError) as caught:
            rec.check_record(doc)
        self.assertIn(why, str(caught.exception))

    def test_the_written_record_reads_back_and_matches_the_full_schema(self):
        rec.check_record(self.doc)
        jsonschema.Draft202012Validator(rec.schema()).validate(self.doc)

    def test_a_record_cannot_call_a_repair_demonstrated_that_its_runs_do_not_show(self):
        self.refused(lambda d: d["repair"]["rows"][0].update(base=["fail", "pass", "fail"]), "does not follow from its runs")
        self.refused(lambda d: d["repair"]["rows"][0].update(base=["fail"], head=["pass"]), "does not follow from its runs")
        self.refused(lambda d: d["repair"].update(demonstrated=3), "does not match the repair rows")
        self.refused(lambda d: d["repair"]["rows"][0].update(base=["pass", "fail", "fail"]), "the check's own result")
        self.refused(lambda d: d["repair"]["rows"][0].update(head=["fail", "pass", "pass"]), "the check's own result")

    def test_the_rows_are_exactly_the_checks_that_claim_a_repair(self):
        self.refused(lambda d: d["repair"]["rows"].pop(), "not exactly the checks that failed before and pass after")
        self.refused(lambda d: d["repair"]["rows"].reverse(), "not exactly the checks that failed before and pass after")
        self.refused(lambda d: d["repair"]["rows"][0].update(route="elsewhere"), "not exactly the checks")

    def test_the_block_is_there_exactly_when_the_change_is_a_fix(self):
        self.refused(lambda d: d.pop("repair"), "exactly when the change is declared a fix")
        self.refused(lambda d: d.update(intent="none"), "exactly when the change is declared a fix")
        self.refused(lambda d: d.update(intent="change"), "exactly when the change is declared a fix")

    def test_a_fix_cannot_be_recorded_as_accepted_without_a_demonstration(self):
        def strip(d):
            for row in d["repair"]["rows"]:
                row.update(base=["fail", "pass", "pass"], counts=False)
            d["repair"]["demonstrated"] = 0

        self.refused(strip, "the decision should be needs-review")

    def test_the_decision_is_held_to_the_intent_the_record_states(self):
        """Dropping the intent changes what the decision must be, so the two cannot disagree. It does not
        stop a writer from stating another intent: the record's writer is the verify job (docs/ci-gate.md)."""
        doc = self.gate(make_repo(self.tmp / "h2"), make_repo(self.tmp / "b2"), out_name="o2", intent="fix")
        self.assertEqual(doc["decision"], "needs-review")
        doc.pop("repair")
        doc["intent"] = "none"
        with self.assertRaises(rec.RecordError) as caught:
            rec.check_record(doc)
        self.assertIn("the decision should be accept", str(caught.exception))

    def test_the_schema_is_closed(self):
        self.refused(lambda d: d.update(intent="Fix"), "findings schema")
        self.refused(lambda d: d["repair"].update(runs=1), "findings schema")
        self.refused(lambda d: d["repair"].update(note="x"), "findings schema")
        self.refused(lambda d: d["repair"]["rows"][0].update(base=["fail"] * 4), "findings schema")
        self.refused(lambda d: d["repair"]["rows"][0].update(base=["fail", "fail", "maybe"]), "findings schema")

    def test_an_undeclared_changes_record_has_exactly_the_keys_it_had_before(self):
        old = json.loads((REPO / "contracts" / "examples" / "findings.json").read_text(encoding="utf-8"))
        doc = self.gate(make_repo(self.tmp / "h3"), make_repo(self.tmp / "b3"), out_name="o3")
        self.assertEqual(set(doc) - set(old), set())

    def test_a_record_from_before_the_field_reads_as_nothing_declared(self):
        old = json.loads((REPO / "contracts" / "examples" / "findings.json").read_text(encoding="utf-8"))
        self.assertNotIn("intent", old)
        rec.check_record(old)
        self.assertEqual(rec.intent_of(old), "none")
        self.assertFalse(rec.unverified_fix(old))

    def test_the_example_is_a_fix_that_was_not_demonstrated(self):
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        rec.check_record(example)
        jsonschema.Draft202012Validator(rec.schema()).validate(example)
        self.assertEqual((example["decision"], example["intent"], example["repair"]["demonstrated"]), ("needs-review", "fix", 0))
        self.assertTrue(example["reasons"][0].startswith("repair-not-demonstrated: "))


class TheWords(GateCase):
    def render(self, doc):
        return gc.render(doc, ctx())

    def test_an_unverified_fix_leads_with_it_and_says_how_to_get_a_check(self):
        doc = self.gate(make_repo(self.tmp / "head"), make_repo(self.tmp / "base"), intent="fix")
        body = self.render(doc)
        lead = body.split("\n")[3]
        self.assertTrue(lead.startswith("**No check reproduced the reported bug, so this fix is not verified.**"), lead)
        self.assertIn("add a check that fails on the bug", lead)
        self.assertIn("- repair\\-not\\-demonstrated: this change is declared as a fix", body)
        self.assertIn("**Declared as:** a fix, and no check demonstrated the repair.", body)
        page = (self.tmp / "out" / "review" / "index.html").read_text(encoding="utf-8")
        self.assertIn("No check reproduced the reported bug, so this fix is not verified.", page)

    def test_a_demonstrated_fix_says_which_check_showed_it(self):
        doc = self.gate(make_repo(self.tmp / "head"), make_repo(self.tmp / "base", bug=True), intent="fix")
        body = self.render(doc)
        self.assertIn("**The repair is demonstrated:** 2 of them failed before the change 3 times of 3.", body)
        self.assertIn("player\\-stays\\-above\\-ground on combat failed before the change 3 times of 3", body)
        self.assertNotIn("not verified", body)

    def test_with_nothing_declared_the_comment_says_so_and_leads_as_before(self):
        doc = self.gate(make_repo(self.tmp / "head"), make_repo(self.tmp / "base"))
        body = self.render(doc)
        self.assertIn("**Declared as:** nothing declared: judged as a change that should break no check.", body)
        self.assertNotIn("not verified", body)

    def test_a_rejected_fix_leads_with_the_failure(self):
        doc = self.gate(make_repo(self.tmp / "head", bug=True), make_repo(self.tmp / "base", bug=True), intent="fix")
        self.assertIn("fail after this change", self.render(doc).split("\n")[3])

    def test_the_docs_state_the_rule(self):
        text = (REPO / "docs" / "ci-gate.md").read_text(encoding="utf-8")
        self.assertTrue("repair-not-demonstrated" in text and "--intent" in text and "three times of three" in text)


if __name__ == "__main__":
    import unittest

    unittest.main()
