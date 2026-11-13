"""The miss breakdown (issue #285, step 2): the scorer's reasons, and hand findings only where the records
cannot say. Offline: no engine, no model."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from expectrail.repro import bench, breakdown, score, visibility
from expectrail.repro.__main__ import main

REPO = Path(__file__).resolve().parents[1]
EXAMPLE_SCORE = REPO / "contracts" / "examples" / "repro-score.json"


def hand(*rows):
    return {"format": breakdown.FORMAT, "written": "2026-11-12",
            "rows": [{"id": i, "reason": r, "basis": b} for i, r, b in rows]}


def scored(*rows):
    """A score's rows as the breakdown reads them: id, outcome and the scorer's reason."""
    out = [{"id": i, "outcome": o, "missReason": m} for i, o, m in rows]
    return {"rows": out, "totals": {"notReproduced": sum(r["outcome"] == "not-reproduced" for r in out),
                                    "noResult": sum(r["outcome"] == "no-result" for r in out)}}


class CommittedHandFindings(unittest.TestCase):
    def test_loads_and_names_only_bench_defects(self):
        record = breakdown.load()
        self.assertEqual(breakdown.unknown(record, bench.load()), [])

    def test_covers_exactly_the_defects_the_library_probes_leave_unchanged(self):
        # The scorer gives "undetermined" exactly where the visibility record says "none"; the hand file
        # is for those and no other.
        seen = visibility.load(visibility.RECORD)
        none = {r["id"] for r in seen["defects"] if r["visibility"] == "none"}
        self.assertEqual({r["id"] for r in breakdown.load()["rows"]}, none)


class HandFindingsReader(unittest.TestCase):
    def check_refused(self, record, fragment):
        self.assertTrue(any(fragment in p for p in breakdown.problems(record)), breakdown.problems(record))

    def test_only_the_two_reasons_no_record_separates(self):
        for reason in ("budget", "flaky", "wrong-predicate", "no-signal", "undetermined", "anything"):
            with self.subTest(reason=reason):
                self.check_refused(hand(("air-jump", reason, "seen")), "rows/0/reason")
        for reason in breakdown.HAND_REASONS:
            self.assertEqual(breakdown.problems(hand(("air-jump", reason, "seen"))), [])

    def test_a_defect_twice_is_refused(self):
        self.check_refused(hand(("air-jump", "probe-language", "a"), ("air-jump", "route-never-reaches", "b")),
                           "listed twice")

    def test_basis_must_be_one_line(self):
        for basis in ("two\nlines", "a  double space", " leading", "", "x" * 301, "tab\there"):
            with self.subTest(basis=basis):
                self.assertNotEqual(breakdown.problems(hand(("air-jump", "probe-language", basis))), [])

    def test_unknown_fields_and_formats_are_refused(self):
        record = hand(("air-jump", "probe-language", "seen"))
        record["rows"][0]["outcome"] = "reproduced"
        self.check_refused(record, "rows/0")
        record = hand(("air-jump", "probe-language", "seen"))
        record["format"] = "expectrail.repro-hand-reasons/v2"
        self.check_refused(record, "format")

    def test_load_refuses_duplicate_keys_and_oversize(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "h.json"
            p.write_text('{"format": "expectrail.repro-hand-reasons/v1", "format": "x", "written": "2026-11-12", '
                         '"rows": []}', encoding="utf-8")
            with self.assertRaises(breakdown.BreakdownError):
                breakdown.load(p)
            p.write_text(" " * (breakdown.MAX_BYTES + 1), encoding="utf-8")
            with self.assertRaises(breakdown.BreakdownError):
                breakdown.load(p)

    def test_unknown_names_defects_outside_the_bench(self):
        self.assertEqual(breakdown.unknown(hand(("not-a-defect", "probe-language", "seen")), bench.load()),
                         ["not-a-defect: a hand finding for a defect the bench does not have"])


class TheRule(unittest.TestCase):
    H = hand(("a", "route-never-reaches", "no route"), ("b", "probe-language", "screen only"),
             ("c", "probe-language", "screen only"), ("d", "route-never-reaches", "no route"))

    def test_hand_replaces_undetermined_only(self):
        rows = {r["id"]: r for r in breakdown.breakdown(
            scored(("a", "not-reproduced", "undetermined"), ("b", "not-reproduced", "wrong-predicate"),
                   ("c", "reproduced", None), ("d", "no-result", None), ("e", "not-reproduced", "undetermined"),
                   ("f", "not-reproduced", "flaky")), self.H)}
        self.assertEqual((rows["a"]["reason"], rows["a"]["source"]), ("route-never-reaches", "hand"))
        # A reason read from the records stands; the hand finding is carried, not counted.
        self.assertEqual((rows["b"]["reason"], rows["b"]["source"]), ("wrong-predicate", "scorer"))
        self.assertEqual(rows["b"]["hand"]["reason"], "probe-language")
        # A reproduced defect and a defect with no result get no reason, whatever the hand file says.
        self.assertEqual((rows["c"]["outcome"], rows["c"]["reason"], rows["c"]["source"]), ("reproduced", None, None))
        self.assertEqual((rows["d"]["outcome"], rows["d"]["reason"]), ("no-result", None))
        # No hand finding: undetermined stays undetermined.
        self.assertEqual((rows["e"]["reason"], rows["e"]["source"]), ("undetermined", "scorer"))
        self.assertEqual(rows["f"]["reason"], "flaky")

    def test_counts_follow_the_vocabulary_and_say_what_rests_on_hand(self):
        rows = breakdown.breakdown(
            scored(("a", "not-reproduced", "undetermined"), ("b", "not-reproduced", "wrong-predicate"),
                   ("e", "not-reproduced", "undetermined"), ("d", "not-reproduced", "undetermined")), self.H)
        c = breakdown.counts(rows)
        self.assertEqual(list(c), [k for k in score.MISS_REASONS if k in c])
        self.assertEqual(c, {"route-never-reaches": {"misses": 2, "byHand": 2},
                             "wrong-predicate": {"misses": 1, "byHand": 0},
                             "undetermined": {"misses": 1, "byHand": 0}})

    def test_the_hand_file_cannot_move_the_rate(self):
        s = scored(("a", "not-reproduced", "undetermined"), ("c", "reproduced", None))
        before = copy.deepcopy(s)
        rows = breakdown.breakdown(s, self.H)
        self.assertEqual(s, before)
        self.assertEqual([r["outcome"] for r in rows], ["not-reproduced", "reproduced"])


class Page(unittest.TestCase):
    def test_hand_text_is_one_code_span(self):
        h = hand(("a", "probe-language", "a [link](http://x) <b>|cell|</b> `tick` @someone"))
        page = breakdown.render(scored(("a", "not-reproduced", "undetermined")), h)
        row = [line for line in page.splitlines() if line.startswith("| `a` |")]
        self.assertEqual(len(row), 1)
        self.assertIn("`a [link](http://x) <b>/cell/</b> 'tick' @someone`", row[0])
        self.assertEqual(row[0].count("|"), 6)

    def test_no_miss_says_so(self):
        page = breakdown.render(scored(("a", "reproduced", None)), self.hand_empty())
        self.assertIn("No defect was missed.", page)

    @staticmethod
    def hand_empty():
        return hand()


class Command(unittest.TestCase):
    def test_breakdown_command_on_the_example_score(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["breakdown", "--score", str(EXAMPLE_SCORE)])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("| `wrong-predicate` | 1 | 0 |", out.getvalue())
        # The example's made-up rows do not describe the bench, and the command says so.
        self.assertIn("stale", err.getvalue())

    def test_a_bad_hand_file_is_an_error_not_a_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "h.json"
            p.write_text(json.dumps(hand(("a", "budget", "x"))), encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                code = main(["breakdown", "--score", str(EXAMPLE_SCORE), "--hand", str(p)])
        self.assertEqual(code, 1)
        self.assertIn("repro-hand-reasons", err.getvalue())


if __name__ == "__main__":
    unittest.main()
