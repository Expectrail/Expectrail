"""expectrail.gate.known_bench: the gate on the known-bugs bench, with no stated intent and declared a fix (#284)."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from expectrail.gate import known_bench as kb
from expectrail.gate import record as rec

REPO = kb.REPO
EXAMPLE = REPO / "contracts" / "examples" / "gate-known-bench.json"
MARKDOWN = REPO / "bench" / "jit" / "known" / "gate.md"


def fake_gate(before: dict[str, list[str]], after: dict[str, str]):
    """A stand-in for run_gate that decides with the gate's own ``decide``.

    ``before[case]`` is the base outcome on each of the three runs of the one check, ``after[case]``
    the head's. The case is read from the head tree's folder name, which run_case makes."""
    calls = []

    def run_gate(*, repo, game, routes, specs, out, work, base, intent):
        case = Path(repo).parent.name
        calls.append({"case": case, "intent": intent, "repo": Path(repo), "base": Path(base), "routes": routes,
                      "specs": specs, "game": game})
        b, a = before[case], after[case]
        checks = [{"spec": "player-stays-above-ground", "route": "smoke", "before": b[0], "after": a}]
        counts = {"checks": 1, "failed": int(a == "fail"), "needsReview": 0}
        held = {"checks": 0, "failed": 0, "needsReview": 0, "status": "none"}
        repair = None
        if intent == "fix":
            rows = []
            if b[0] == "fail" and a == "pass":
                rows = [{"spec": "player-stays-above-ground", "route": "smoke", "base": list(b), "head": [a] * 3}]
            repair = rec.repair_block(rows)
        decision, reasons = rec.decide(counts, held, intent=intent, repair=repair)
        doc = {"decision": decision, "reasons": reasons, "checks": checks}
        if repair is not None:
            doc["repair"] = repair
        return doc

    run_gate.calls = calls
    return run_gate


def run_all(before, after, cases=None):
    cases = cases if cases is not None else kb.load_cases()
    gate = fake_gate(before, after)
    with tempfile.TemporaryDirectory() as d:
        rows = [kb.run_case(c, Path(d) / c["case"], run_gate=gate) for c in cases]
    return rows, gate


class RunCase(unittest.TestCase):
    def test_trees_hold_the_bug_on_the_base_and_the_bug_plus_candidate_on_the_head(self):
        case = next(c for c in kb.load_cases() if c["case"] == "known-air-jump-undo")
        seen = {}

        def gate(*, repo, game, routes, specs, out, work, base, intent):
            game_dir = Path(repo) / game
            base_dir = Path(base) / game
            seen[intent] = {
                "head": (game_dir / "player" / "player.gd").read_text(encoding="utf-8"),
                "base": (base_dir / "player" / "player.gd").read_text(encoding="utf-8"),
                "clean": (REPO / game / "player" / "player.gd").read_text(encoding="utf-8"),
                "routes": all((Path(repo) / r).is_file() and (Path(base) / r).is_file() for r in routes),
                "specs": sorted(p.name for p in (Path(repo) / specs).glob("*.json")),
            }
            return {"decision": "accept", "reasons": ["all 2 checks pass"], "checks": []}

        with tempfile.TemporaryDirectory() as d:
            row = kb.run_case(case, Path(d) / case["case"], run_gate=gate)
        self.assertEqual(set(seen), set(kb.INTENTS))
        for s in seen.values():
            self.assertNotEqual(s["base"], s["clean"], "the base must carry the bug")
            self.assertEqual(s["head"], s["clean"], "the undo puts the clean game back")
            self.assertTrue(s["routes"])
            self.assertEqual(s["specs"], [Path(p).name for p in kb.spec_files()])
        self.assertEqual(row["baseSha256"], kb._sha(REPO / case["base"]))
        self.assertEqual(row["none"]["checks"], 0)

    def test_the_gate_is_run_with_each_intent_on_the_arm_a_routes_and_specs(self):
        names = [c["case"] for c in kb.load_cases()]
        rows, gate = run_all({n: ["pass"] * 3 for n in names}, {n: "pass" for n in names})
        self.assertEqual(len(gate.calls), 2 * len(names))
        self.assertEqual({c["intent"] for c in gate.calls}, set(kb.INTENTS))
        for c in gate.calls:
            self.assertEqual(c["routes"], ["harness/routes/smoke.json", "harness/routes/combat.json"])
            self.assertEqual((c["specs"], c["game"]), ("agents/specs", "game/platformer"))


class Rule(unittest.TestCase):
    """The rule's effect on the bench, with the gate's own decide behind a stand-in replay."""

    def test_nothing_reproduces_the_bug_every_accept_becomes_needs_review(self):
        names = [c["case"] for c in kb.load_cases()]
        rows, _ = run_all({n: ["pass"] * 3 for n in names}, {n: "pass" for n in names})
        t = kb.totals(rows)
        self.assertEqual(t["none"]["wrong"]["accept"], 4)
        self.assertEqual(t["fix"]["wrong"]["needs-review"], 4)
        self.assertEqual(t["fix"]["correct"]["needs-review"], 4)
        self.assertEqual((t["wrongAcceptToNeedsReview"], t["correctAcceptToNeedsReview"]), (4, 4))
        for r in rows:
            self.assertTrue(r["fix"]["firstReason"].startswith("repair-not-demonstrated"))
        self.assertEqual(kb.problems(kb.make_record(rows, engine="stand-in")), [])

    def test_a_check_failing_on_the_bug_accepts_the_undo_and_rejects_the_comment(self):
        names = [c["case"] for c in kb.load_cases()]
        before = {n: ["fail"] * 3 for n in names}
        after = {n: ("pass" if n.endswith("-undo") else "fail") for n in names}
        rows, _ = run_all(before, after)
        t = kb.totals(rows)
        self.assertEqual(t["fix"]["correct"]["accept"], 4)
        self.assertEqual(t["fix"]["wrong"]["reject"], 4)
        self.assertEqual(t["none"]["wrong"]["reject"], 4)
        self.assertEqual(kb.problems(kb.make_record(rows, engine="stand-in")), [])

    def test_a_flaky_base_failure_does_not_accept_a_fix(self):
        names = [c["case"] for c in kb.load_cases()]
        before = {n: ["fail", "pass", "fail"] for n in names}
        rows, _ = run_all(before, {n: "pass" for n in names})
        for r in rows:
            self.assertEqual(r["none"]["decision"], "accept")
            self.assertEqual(r["fix"]["decision"], "needs-review")
            self.assertEqual(r["fix"]["repairsDemonstrated"], 0)


class Reader(unittest.TestCase):
    def setUp(self):
        self.example = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def test_the_example_is_valid(self):
        self.assertEqual(kb.problems(self.example), [])

    def refused(self, change, words):
        doc = copy.deepcopy(self.example)
        change(doc)
        found = kb.problems(doc)
        self.assertTrue(any(words in p for p in found), found)

    def test_totals_that_do_not_follow_from_the_rows_are_refused(self):
        self.refused(lambda d: d["totals"]["fix"]["wrong"].update({"accept": 1}), "totals do not match")

    def test_a_fix_accepted_without_a_demonstrated_repair_is_refused(self):
        def change(d):
            r = d["rows"][0]
            r["none"]["decision"] = "accept"
            r["fix"].update(decision="accept", repairsDemonstrated=0)
            d["totals"] = kb.totals(d["rows"])
        self.refused(change, "accepted without a demonstrated repair")

    def test_a_fix_accepted_where_no_intent_was_not_is_refused(self):
        def change(d):
            r = d["rows"][0]
            r["none"]["decision"] = "needs-review"
            r["fix"].update(decision="accept", repairsDemonstrated=1, failedBefore=1)
            d["totals"] = kb.totals(d["rows"])
        self.refused(change, "accepted without a demonstrated repair")

    def test_an_unverified_fix_must_lead_with_the_reason(self):
        def change(d):
            r = next(r for r in d["rows"] if r["fix"]["decision"] == "needs-review")
            r["fix"]["firstReason"] = "no checks ran"
        self.refused(change, "does not lead with")

    def test_a_repair_under_no_intent_is_refused(self):
        self.refused(lambda d: d["rows"][0]["none"].update(repairsDemonstrated=1), "intent none records a repair")

    def test_counts_that_do_not_agree_and_duplicates_and_unknown_keys_are_refused(self):
        self.refused(lambda d: d["rows"][0]["fix"].update(failedBefore=99), "check counts do not agree")
        self.refused(lambda d: d["rows"].append(copy.deepcopy(d["rows"][0])), "listed twice")
        self.refused(lambda d: d.update(extra=1), "Additional properties")
        self.refused(lambda d: d.update(rule="both"), "rule")

    def test_load_refuses_duplicate_keys_and_oversize(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "gate.json"
            p.write_text('{"format": "a", "format": "b"}', encoding="utf-8")
            with self.assertRaises(kb.BenchError):
                kb.load(p)
            p.write_text(" " * (kb.MAX_BYTES + 1), encoding="utf-8")
            with self.assertRaises(kb.BenchError):
                kb.load(p)


class Stored(unittest.TestCase):
    """The record in bench/jit/known/gate.json: measured on the real engine, read back here."""

    def setUp(self):
        self.record = kb.load()

    def test_it_describes_the_bench_as_it_is(self):
        self.assertEqual(kb.stale(self.record), [])
        self.assertEqual({r["case"] for r in self.record["rows"]}, {c["case"] for c in kb.load_cases()})

    def test_the_page_is_the_record_rendered(self):
        self.assertEqual(MARKDOWN.read_text(encoding="utf-8"), kb.render(self.record))

    def test_declared_a_fix_no_wrong_fix_is_accepted(self):
        self.assertEqual(self.record["totals"]["fix"]["wrong"]["accept"], 0)

    def test_show_prints_the_page(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(kb.main(["show"]), 0)
        self.assertEqual(out.getvalue(), kb.render(self.record))

    def test_a_changed_patch_makes_it_stale(self):
        doc = copy.deepcopy(self.record)
        doc["rows"][0]["candidateSha256"] = "0" * 64
        self.assertTrue(any("a patch changed" in s for s in kb.stale(doc)))


if __name__ == "__main__":
    unittest.main()
