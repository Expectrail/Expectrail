"""Survival under the do-nothing control and the form histogram, read from a live run's own records
(expectrail/repro/control_survival.py, #285).

No engine, no model. The baseline recording predates the control, so its records carry no do-nothing rows
and the reader must say it cannot tell. The live-run cases are made from those records by adding the rows
a run of today's generator writes (expectrail/jit/run.py, ``_do_nothing_stage``), with the score's record
digests updated to the edited files."""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from expectrail.repro import __main__ as cli
from expectrail.repro import bench, control_form, control_survival

REPO = Path(__file__).resolve().parents[1]
RECORDING = REPO / "bench" / "jit" / "recordings" / "public-43465090517"
RECORDS = RECORDING / "repro"
SCORE = RECORDING / "repro-score" / "repro-score.json"
AUDIT = REPO / "docs" / "repro-audit.md"
PASSES = ["pass", "pass", "pass"]
FAILS = ["fail", "fail", "fail"]


def dn(runs: list[str], outcome: str, reason=None) -> dict:
    return {"control": "do-nothing:player", "runs": runs, "outcome": outcome, "reason": reason}


class LiveRun:
    """A copy of the baseline recording, edited into the records a run with the control would write."""

    def __init__(self, tmp: Path, name: str = "run"):
        self.dir = tmp / name
        shutil.copytree(RECORDING, self.dir)
        self.records = self.dir / "repro"
        self.score = self.dir / "repro-score" / "repro-score.json"
        self.doc = json.loads(self.score.read_text())

    def path(self, defect: str) -> Path:
        return self.records / f"repro-{defect}" / "jit-run.json"

    def record(self, defect: str) -> dict:
        return json.loads(self.path(defect).read_text())

    def put(self, defect: str, record: dict) -> None:
        self.path(defect).write_text(json.dumps(record, indent=1) + "\n")
        for row in self.doc["rows"]:
            if row["id"] == defect and row.get("recordSha256"):
                row["recordSha256"] = bench.sha256(self.path(defect))
        self.score.write_text(json.dumps(self.doc, indent=1) + "\n")

    def controlled(self, outcome_of=None) -> "LiveRun":
        """Every validity row given a do-nothing row: ``fails`` for a check that passed its reference,
        ``not-run`` (with the writer's reason) for one that did not, unless ``outcome_of`` says otherwise."""
        for row in self.doc["rows"]:
            if not row.get("recordSha256"):
                continue
            record = self.record(row["id"])
            for v in record["validity"]:
                if not (len(v["reference"]) >= 3 and all(r == "pass" for r in v["reference"][:3])):
                    v["doNothing"] = {"control": None, "runs": [], "outcome": "not-run",
                                      "reason": "did not pass on the reference, so the control was not run"}
                    continue
                v["doNothing"] = dn(FAILS, "fails")
                if outcome_of:
                    got = outcome_of(row["id"], v)
                    if got is not None:
                        v["doNothing"] = got
                        if got["outcome"] == "passes":
                            v["valid"] = False
            self.put(row["id"], record)
        return self


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)


class TheBaseline(unittest.TestCase):
    """The committed baseline predates the control: survival cannot be told from it."""

    @classmethod
    def setUpClass(cls):
        cls.result = control_survival.read(SCORE, RECORDS)

    def test_every_proposed_check_is_read_once_and_none_has_a_row(self):
        proposed = sum(len(json.loads((RECORDS / f"repro-{r['id']}" / "jit-run.json").read_text())["proposed"])
                       for r in json.loads(SCORE.read_text())["rows"] if r.get("recordSha256"))
        self.assertEqual(self.result["proposed"], proposed)
        self.assertEqual(self.result["outcomes"]["absent"], proposed)

    def test_survival_is_cannot_tell_not_a_number(self):
        self.assertIsNone(self.result["survival"]["stated"])
        self.assertIsNone(self.result["survival"]["judged"])
        self.assertIn("cannot tell", control_survival.render([self.result]))

    def test_the_form_histogram_is_still_read_and_agrees_with_control_form(self):
        forms = self.result["forms"]
        self.assertEqual(sum(sum(c.values()) for c in forms.values()), self.result["proposed"])
        for name in control_form.FORMS:
            self.assertIn(name, forms)
        self.assertEqual(sum(self.result["operations"].values()), self.result["proposed"])

    def test_valid_catches_are_the_scores_own(self):
        doc = json.loads(SCORE.read_text())
        self.assertEqual(self.result["catches"]["defects"], doc["totals"]["reproduced"])
        self.assertEqual(self.result["catches"]["checks"], sum(len(r["reproducing"]) for r in doc["rows"]))
        self.assertEqual(self.result["offer"], "baseline")
        self.assertTrue(self.result["label"].startswith("baseline, "))


class ALiveRun(Fixture):
    def test_survival_counts_every_proposed_check_and_separates_those_the_control_judged(self):
        run = LiveRun(self.tmp).controlled(
            lambda d, v: dn(["fail", "pass"], "indeterminate") if d == "body-flip" else None)
        rec = run.record("bullet-behind-scenery")
        on_ref = [v for v in rec["validity"] if v["doNothing"]["outcome"] == "fails"
                  and v["specId"] not in next(r for r in run.doc["rows"]
                                              if r["id"] == "bullet-behind-scenery")["reproducing"]]
        self.assertTrue(on_ref, "the fixture needs a non-reproducing check that reached the control")
        on_ref[0]["doNothing"] = dn(PASSES, "passes", "passed")
        on_ref[0]["valid"] = False
        run.put("bullet-behind-scenery", rec)

        result = control_survival.read(run.score, run.records)
        o = result["outcomes"]
        self.assertEqual(o["absent"], 0)
        self.assertEqual(o["passes"], 1)
        self.assertEqual(sum(o.values()), result["proposed"])
        judged = o["passes"] + o["fails"] + o["indeterminate"]
        self.assertEqual(result["survival"]["judged"], (judged - 1, judged))
        self.assertEqual(result["survival"]["stated"], (result["proposed"] - 1, result["proposed"]))
        self.assertGreater(o["indeterminate"], 0)

    def test_a_check_with_no_validity_row_is_counted_apart(self):
        run = LiveRun(self.tmp).controlled()
        rec = run.record("bullet-behind-scenery")
        rec["validity"].pop()
        run.put("bullet-behind-scenery", rec)
        result = control_survival.read(run.score, run.records)
        self.assertEqual(result["outcomes"]["no-row"], 1)

    def test_a_check_that_failed_its_reference_is_not_counted_as_surviving_the_control(self):
        run = LiveRun(self.tmp).controlled()
        result = control_survival.read(run.score, run.records)
        off = result["outcomes"]["off-reference"]
        n, of = result["survival"]["judged"]
        self.assertEqual(of, result["outcomes"]["fails"] + result["outcomes"]["indeterminate"]
                         + result["outcomes"]["passes"])
        self.assertEqual(result["proposed"], of + off + result["outcomes"]["not-run"] + result["outcomes"]["no-row"])

    def test_a_run_given_no_control_says_not_run(self):
        run = LiveRun(self.tmp).controlled(lambda d, v: {"control": None, "runs": [], "outcome": "not-run",
                                                         "reason": "no do-nothing control was given to this run"})
        result = control_survival.read(run.score, run.records)
        self.assertEqual(result["outcomes"]["fails"] + result["outcomes"]["passes"], 0)
        self.assertIsNone(result["survival"]["judged"])
        self.assertIn("cannot tell", control_survival.render([result]))

    def test_two_runs_are_read_side_by_side(self):
        a = control_survival.read(*(lambda r: (r.score, r.records))(LiveRun(self.tmp, "a").controlled()))
        b = control_survival.read(*(lambda r: (r.score, r.records))(LiveRun(self.tmp, "b").controlled()))
        page = control_survival.render([a, b])
        self.assertIn(control_survival.HEADING, page)
        self.assertEqual(page.count("| Survival, as stated |"), 1)
        self.assertIn("relation", page)


class FailsClosed(Fixture):
    """A record that disagrees with itself gives no number."""

    def refuse(self, run: LiveRun, pattern: str):
        with self.assertRaisesRegex(control_survival.ControlSurvivalError, pattern):
            control_survival.read(run.score, run.records)

    def test_an_outcome_its_own_runs_do_not_give(self):
        run = LiveRun(self.tmp).controlled()
        rec = run.record("body-flip")
        v = next(v for v in rec["validity"] if v["doNothing"]["outcome"] == "fails")
        v["doNothing"]["outcome"] = "indeterminate"
        run.put("body-flip", rec)
        self.refuse(run, "body-flip.*disagrees")

    def test_a_check_kept_as_valid_after_passing_the_control(self):
        run = LiveRun(self.tmp).controlled()
        rec = run.record("air-jump")
        v = rec["validity"][0]
        v["doNothing"] = dn(PASSES, "passes")
        run.put("air-jump", rec)
        self.refuse(run, "air-jump.*valid")

    def test_a_reproducing_check_that_passed_the_control(self):
        run = LiveRun(self.tmp).controlled()
        rec = run.record("air-jump")
        v = rec["validity"][0]
        v["doNothing"] = dn(PASSES, "passes")
        v["valid"] = False
        run.put("air-jump", rec)
        self.refuse(run, "air-jump")

    def test_a_control_run_for_a_check_that_failed_its_reference(self):
        run = LiveRun(self.tmp).controlled()
        for row in run.doc["rows"]:
            if not row.get("recordSha256"):
                continue
            rec = run.record(row["id"])
            off = [v for v in rec["validity"] if v["doNothing"]["outcome"] == "not-run"
                   and v["doNothing"]["reason"].startswith("did not pass")]
            if off:
                off[0]["doNothing"] = dn(FAILS, "fails")
                run.put(row["id"], rec)
                self.refuse(run, row["id"])
                return
        self.skipTest("no check in the baseline failed its reference")

    def test_a_reproducing_check_with_no_validity_row(self):
        run = LiveRun(self.tmp).controlled()
        rec = run.record("air-jump")
        rec["validity"] = [v for v in rec["validity"] if v["specId"] != "jit-c1"]
        run.put("air-jump", rec)
        self.refuse(run, "air-jump.*jit-c1")

    def test_an_unknown_outcome(self):
        run = LiveRun(self.tmp).controlled()
        rec = run.record("body-flip")
        rec["validity"][0]["doNothing"]["outcome"] = "sort-of"
        run.put("body-flip", rec)
        self.refuse(run, "body-flip")

    def test_a_validity_row_for_a_check_never_proposed_or_twice(self):
        run = LiveRun(self.tmp).controlled()
        rec = run.record("body-flip")
        rec["validity"].append(dict(rec["validity"][0], specId="jit-nobody"))
        run.put("body-flip", rec)
        self.refuse(run, "body-flip.*jit-nobody")
        run = LiveRun(self.tmp, "again").controlled()
        rec = run.record("body-flip")
        rec["validity"].append(dict(rec["validity"][0]))
        run.put("body-flip", rec)
        self.refuse(run, "body-flip.*twice")

    def test_some_records_with_rows_and_some_without(self):
        run = LiveRun(self.tmp).controlled()
        rec = run.record("body-flip")
        for v in rec["validity"]:
            del v["doNothing"]
        run.put("body-flip", rec)
        self.refuse(run, "some records")

    def test_a_record_that_is_not_the_one_the_score_names(self):
        run = LiveRun(self.tmp).controlled()
        path = run.path("air-jump")
        path.write_text(path.read_text() + " ")
        self.refuse(run, "air-jump.*score names")

    def test_a_record_made_with_another_setting(self):
        run = LiveRun(self.tmp).controlled()
        rec = run.record("air-jump")
        rec["settings"]["offer"] = "signals-reach-evidence-menu-control"
        run.put("air-jump", rec)
        self.refuse(run, "air-jump.*setting")


class Command(Fixture):
    def test_the_command_prints_the_counts_and_writes_the_page(self):
        run = LiveRun(self.tmp).controlled()
        out = self.tmp / "page.md"
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["control-survival", "--run", str(run.score), str(run.records),
                             "--run", str(SCORE), str(RECORDS), "--out", str(out)])
        self.assertEqual(code, 0)
        printed = [json.loads(line) for line in buf.getvalue().splitlines()]
        self.assertEqual(len(printed), 2)
        self.assertIsNone(printed[1]["survival"]["stated"])
        self.assertTrue(out.read_text().startswith(control_survival.HEADING))

    def test_the_command_refuses_a_record_that_disagrees(self):
        run = LiveRun(self.tmp).controlled()
        rec = run.record("body-flip")
        rec["validity"][0]["doNothing"]["outcome"] = "sort-of"
        run.put("body-flip", rec)
        with redirect_stdout(io.StringIO()):
            import contextlib
            with contextlib.redirect_stderr(io.StringIO()) as err:
                code = cli.main(["control-survival", "--run", str(run.score), str(run.records)])
        self.assertEqual(code, 1)
        self.assertIn("body-flip", err.getvalue())


class TheAudit(unittest.TestCase):
    def test_the_audit_names_the_reader_and_no_longer_says_it_is_not_built(self):
        text = AUDIT.read_text()
        self.assertIn("python3 -m expectrail.repro control-survival", text)
        self.assertNotIn("A reader of those rows is to be built on #285 before the run is published.", text)

    def test_the_baseline_numbers_the_audit_states_are_the_readers(self):
        text = " ".join(AUDIT.read_text().split())
        r = control_survival.read(SCORE, RECORDS)
        f = {k: sum(v.values()) for k, v in r["forms"].items()}
        self.assertIn(f"it reports {r['proposed']} proposed checks, all `absent`", text)
        self.assertIn(f"({f['holds-when-equal']} `holds-when-equal`, {f['holds-when-still']} `holds-when-still`, "
                      f"{f['fails-when-equal']} `fails-when-equal`, {f['needs-activity']} `needs-activity`, "
                      f"{f['other']} `other`)", text)
        self.assertIn(f"the score's {r['catches']['checks']} checks and {r['catches']['defects']} of "
                      f"{r['catches']['of']} defects", text)


if __name__ == "__main__":
    unittest.main()
