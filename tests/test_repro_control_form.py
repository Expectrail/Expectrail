"""Why a check passes the do-nothing control, read from its form (expectrail/repro/control_form.py, #285).

No engine, no model: the forms come from the committed baseline records, the outcomes from the committed
control rows, both bound by digest the way expectrail/repro/control_rate.py binds them."""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from expectrail.contracts import digest_v1
from expectrail.repro import __main__ as cli
from expectrail.repro import control_form
from expectrail.trace.evaluator import COMPARATORS

REPO = Path(__file__).resolve().parents[1]
RECORDING = REPO / "bench" / "jit" / "recordings" / "public-43465090517"
RECORDS = RECORDING / "repro"
SCORE = RECORDING / "repro-score" / "repro-score.json"
ROWS = REPO / "bench" / "jit" / "public" / "do-nothing-rows.json"
AUDIT = REPO / "docs" / "repro-audit.md"


def relation(comparator: str, tol: float = 0) -> dict:
    return {"operation": {"type": "relation", "signal": "player_dx_px", "comparator": comparator,
                          "toleranceAbs": tol, "left": "a", "right": "b"}}


def op(kind: str) -> dict:
    return {"operation": {"type": kind}}


class TheForm(unittest.TestCase):
    def test_a_relation_is_judged_with_the_evaluators_own_comparator_at_two_equal_arms(self):
        for comparator in COMPARATORS:
            for tol in (0, 5, -1):
                expected = "holds-when-equal" if COMPARATORS[comparator](0.0, 0.0, tol) else "fails-when-equal"
                self.assertEqual(control_form.form(relation(comparator, tol)), expected, (comparator, tol))

    def test_the_usual_tolerances_give_the_expected_split(self):
        for c in ("eq", "lte", "gte"):
            self.assertEqual(control_form.form(relation(c, 15)), "holds-when-equal")
        for c in ("gt", "lt"):
            self.assertEqual(control_form.form(relation(c, 15)), "fails-when-equal")
        # a negative tolerance turns the rule around: it is read, not assumed
        self.assertEqual(control_form.form(relation("lte", -1)), "fails-when-equal")
        self.assertEqual(control_form.form(relation("gt", -1)), "holds-when-equal")

    def test_bounds_a_still_actor_cannot_break_and_demands_it_cannot_meet(self):
        for kind in ("max_entity_drop", "max_episode_rise", "entity_present", "min_event_interval"):
            self.assertEqual(control_form.form(op(kind)), "holds-when-still", kind)
        for kind in ("min_event_count", "min_motion_extent", "event_response"):
            self.assertEqual(control_form.form(op(kind)), "needs-activity", kind)

    def test_what_the_form_does_not_settle_is_other_never_guessed(self):
        for kind in ("direction_agreement", "signal_compare", "mirror", "something-new"):
            self.assertEqual(control_form.form(op(kind)), "other", kind)
        self.assertEqual(control_form.form(relation("approx")), "other")
        self.assertEqual(control_form.form({"operation": {"type": "relation", "comparator": "eq",
                                                          "toleranceAbs": "5"}}), "other")
        self.assertEqual(control_form.form({}), "other")

    def test_every_form_is_named(self):
        self.assertEqual(control_form.FORMS, ("holds-when-equal", "holds-when-still", "fails-when-equal",
                                              "needs-activity", "other"))


class Tally(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def rows(self, doc: dict) -> Path:
        path = self.tmp / "rows.json"
        path.write_text(json.dumps(doc))
        return path

    def test_a_row_that_names_another_record_or_check_is_unbound(self):
        doc = json.loads(ROWS.read_text())
        doc["rows"][0]["specSha256"] = "0" * 64
        doc["rows"][1]["sourceRun"] = "0" * 64
        result = control_form.tally(SCORE, RECORDS, self.rows(doc))
        self.assertEqual(sum(f["unbound"] for f in result["forms"].values()), 2)
        base = control_form.tally(SCORE, RECORDS, ROWS)
        self.assertEqual(sum(f["unbound"] for f in base["forms"].values()), 0)
        self.assertEqual(result["checks"], base["checks"])

    def test_a_record_that_is_not_the_one_the_score_names_is_refused(self):
        bad = self.tmp / "records"
        shutil.copytree(RECORDS, bad)
        path = bad / "repro-air-jump" / "jit-run.json"
        path.write_text(path.read_text() + " ")
        with self.assertRaisesRegex(control_form.ControlFormError, "air-jump"):
            control_form.tally(SCORE, bad, ROWS)

    def test_a_check_with_no_row_is_counted_as_having_none(self):
        doc = json.loads(ROWS.read_text())
        dropped = doc["rows"].pop(0)
        result = control_form.tally(SCORE, RECORDS, self.rows(doc))
        base = control_form.tally(SCORE, RECORDS, ROWS)
        self.assertEqual(sum(f["unbound"] for f in result["forms"].values()), 1, dropped["check"])
        self.assertEqual(result["checks"], base["checks"])


class TheCommittedRows(unittest.TestCase):
    """What the published section says, recomputed from the committed rows and records."""

    @classmethod
    def setUpClass(cls):
        cls.result = control_form.tally(SCORE, RECORDS, ROWS)

    def test_every_check_of_every_record_is_read_once(self):
        records = sum(len(json.loads((RECORDS / f"repro-{r['id']}" / "jit-run.json").read_text())["proposed"])
                      for r in json.loads(SCORE.read_text())["rows"])
        self.assertEqual(self.result["checks"], records)
        self.assertEqual(sum(sum(f.values()) for f in self.result["forms"].values()), records)

    def test_no_check_a_still_actor_satisfies_by_its_form_ever_fails_the_control(self):
        for name in ("holds-when-equal", "holds-when-still"):
            self.assertEqual(self.result["forms"][name]["fails"], 0, name)
            self.assertGreater(self.result["forms"][name]["passes"], 0, name)

    def test_no_strict_relation_ever_passes_the_control(self):
        self.assertEqual(self.result["forms"]["fails-when-equal"]["passes"], 0)
        self.assertGreater(self.result["forms"]["fails-when-equal"]["fails"], 0)

    def test_every_dropped_defect_was_reproduced_only_by_checks_a_still_actor_satisfies(self):
        dropped = {d["id"]: d for d in self.result["dropped"]}
        self.assertEqual(set(dropped), {"air-jump", "enemy-ledge", "slow-left", "slides-after-stop",
                                        "enemy-fast-left"})
        for d in dropped.values():
            self.assertEqual(set(d["reproducing"]) - {"holds-when-equal", "holds-when-still"}, set(), d["id"])
            # and the proposer offered nothing of a form that can fail at rest
            self.assertEqual(d["demanding"], 0, d["id"])

    def test_every_defect_shown_to_state_an_obligation_has_a_demanding_reproducing_check(self):
        for d in self.result["shown"]:
            self.assertTrue(d["failingForms"], d["id"])
            self.assertTrue(set(d["failingForms"]) <= {"fails-when-equal", "needs-activity", "other"}, d)

    def test_the_audit_publishes_what_the_committed_rows_give(self):
        page = control_form.render(self.result)
        audit = AUDIT.read_text()
        start = audit.index(control_form.HEADING)
        self.assertIn(page.strip(), audit[start:])

    def test_the_command_prints_the_tally_and_writes_the_page(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        out = tmp / "page.md"
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["control-form", "--score", str(SCORE), "--records", str(RECORDS),
                             "--do-nothing-rows", str(ROWS), "--out", str(out)])
        self.assertEqual(code, 0)
        printed = json.loads(buf.getvalue())
        self.assertEqual(printed["holds-when-equal"]["fails"], 0)
        self.assertIn(control_form.HEADING, out.read_text())

    def test_the_rows_bind_to_these_records(self):
        doc = json.loads(ROWS.read_text())
        run = json.loads((RECORDS / "repro-air-jump" / "jit-run.json").read_text())
        row = next(r for r in doc["rows"] if r["defect"] == "air-jump")
        self.assertEqual(row["sourceRun"], digest_v1(run))


if __name__ == "__main__":
    unittest.main()
