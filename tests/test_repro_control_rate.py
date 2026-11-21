"""The public reproduction rate under the do-nothing validity rule (expectrail/repro/control_rate.py, #285).

The rows here are written from the committed baseline records' own digests, so they bind the way a row of
``tools/do_nothing_public.py`` does. No engine, no model."""
from __future__ import annotations

import copy
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from expectrail.contracts import digest_v1
from expectrail.repro import __main__ as cli
from expectrail.repro import control_rate

REPO = Path(__file__).resolve().parents[1]
RECORDING = REPO / "bench" / "jit" / "recordings" / "public-43465090517"
RECORDS = RECORDING / "repro"
SCORE = RECORDING / "repro-score" / "repro-score.json"


def _run(defect: str) -> dict:
    return json.loads((RECORDS / f"repro-{defect}" / "jit-run.json").read_text())


def _rows(outcomes: dict | None = None, default: str = "fails") -> dict:
    """A rows.json document: every check of every record bound, with ``default`` as its outcome unless
    ``outcomes[(defect, check)]`` names another."""
    outcomes = outcomes or {}
    score = json.loads(SCORE.read_text())
    rows = []
    for r in score["rows"]:
        run = _run(r["id"])
        for entry in run["proposed"]:
            spec = entry["spec"]
            rows.append({"defect": r["id"], "check": spec["id"], "specSha256": digest_v1(spec),
                         "sourceRun": digest_v1(run), "outcome": outcomes.get((r["id"], spec["id"]), default)})
    return {"rows": rows}


def _reproducing(defect: str) -> list[str]:
    return next(r["reproducing"] for r in json.loads(SCORE.read_text())["rows"] if r["id"] == defect)


class ControlRate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def rate(self, doc: dict, score: Path = SCORE, records: Path = RECORDS) -> dict:
        path = self.tmp / "rows.json"
        path.write_text(json.dumps(doc))
        return control_rate.rate(score, records, path)

    def row(self, result: dict, defect: str) -> dict:
        return next(r for r in result["defects"] if r["id"] == defect)

    def test_every_reproducing_check_failing_the_control_leaves_the_baseline_as_it_was(self):
        result = self.rate(_rows())
        t = result["totals"]
        self.assertEqual((t["legacyReproduced"], t["reproduced"], t["cannotTell"], t["dropped"]), (17, 17, 0, 0))
        self.assertEqual((t["traceVisible"], t["legacyReproducedTraceVisible"], t["reproducedTraceVisible"]), (19, 16, 16))
        self.assertEqual((t["reproducedShown"], t["reproducedShownTraceVisible"]), (17, 16))

    def test_a_defect_whose_every_reproducing_check_passes_the_control_is_not_reproduced(self):
        result = self.rate(_rows({("air-jump", c): "passes" for c in _reproducing("air-jump")}))
        row = self.row(result, "air-jump")
        self.assertEqual(row["state"], "dropped")
        self.assertEqual(row["checks"]["passes"], sorted(_reproducing("air-jump")))
        t = result["totals"]
        self.assertEqual((t["reproduced"], t["dropped"], t["reproducedTraceVisible"]), (16, 1, 15))

    def test_one_reproducing_check_that_fails_the_control_keeps_the_defect(self):
        ids = _reproducing("air-jump")
        outcomes = {("air-jump", c): "passes" for c in ids[1:]}
        row = self.row(self.rate(_rows(outcomes)), "air-jump")
        self.assertEqual(row["state"], "reproduced")
        self.assertEqual(row["checks"]["fails"], [ids[0]])

    def test_a_defect_kept_only_by_indeterminate_checks_is_counted_and_shown_apart(self):
        # The generator keeps an indeterminate check (it drops only on a pass), so the rate counts it;
        # the row says the control did not show the check states an obligation.
        ids = _reproducing("gun-cooldown")
        outcomes = {("gun-cooldown", c): "passes" for c in ids[1:]} | {("gun-cooldown", ids[0]): "indeterminate"}
        result = self.rate(_rows(outcomes))
        self.assertEqual(self.row(result, "gun-cooldown")["state"], "reproduced-indeterminate")
        self.assertEqual(result["totals"]["reproducedOnlyIndeterminate"], 1)
        self.assertEqual(result["totals"]["reproduced"], 17)
        self.assertEqual(result["totals"]["reproducedShown"], 16)

    def test_a_check_not_run_on_the_control_leaves_its_defect_cannot_tell(self):
        ids = _reproducing("no-shooting-in-air")
        result = self.rate(_rows({("no-shooting-in-air", ids[0]): "not-run"}))
        self.assertEqual(self.row(result, "no-shooting-in-air")["state"], "cannot-tell")
        t = result["totals"]
        self.assertEqual((t["reproduced"], t["cannotTell"], t["dropped"]), (16, 1, 0))

    def test_a_row_for_another_version_of_the_check_or_record_does_not_bind(self):
        for field in ("specSha256", "sourceRun"):
            with self.subTest(field=field):
                doc = _rows({("no-shooting-in-air", "jit-c4"): "passes"})
                for r in doc["rows"]:
                    if (r["defect"], r["check"]) == ("no-shooting-in-air", "jit-c4"):
                        r[field] = "0" * 64
                row = self.row(self.rate(doc), "no-shooting-in-air")
                self.assertEqual(row["state"], "cannot-tell")
                self.assertEqual(row["checks"]["unbound"], ["jit-c4"])

    def test_a_missing_row_is_unbound_not_a_pass(self):
        doc = _rows()
        doc["rows"] = [r for r in doc["rows"] if r["defect"] != "double-jump-once"]
        row = self.row(self.rate(doc), "double-jump-once")
        self.assertEqual(row["state"], "cannot-tell")
        self.assertEqual(row["checks"]["unbound"], sorted(_reproducing("double-jump-once")))

    def test_a_check_that_does_not_reproduce_cannot_move_its_defect(self):
        run = _run("coin-stays")
        outcomes = {("coin-stays", e["spec"]["id"]): "passes" for e in run["proposed"]}
        result = self.rate(_rows(outcomes))
        self.assertEqual(self.row(result, "coin-stays")["state"], "not-reproduced")
        self.assertEqual(result["totals"]["dropped"], 0)
        # Nor can a passing non-reproducing check drop a reproduced defect: body-flip has 7 proposed, 7 reproducing,
        # so take a defect with a proposal outside its reproducing list.
        for r in json.loads(SCORE.read_text())["rows"]:
            extra = [e["spec"]["id"] for e in _run(r["id"])["proposed"] if e["spec"]["id"] not in r["reproducing"]]
            if r["outcome"] == "reproduced" and extra:
                result = self.rate(_rows({(r["id"], c): "passes" for c in extra}))
                self.assertEqual(self.row(result, r["id"])["state"], "reproduced")
                break
        else:
            self.fail("no reproduced defect has a proposal outside its reproducing checks")

    def test_a_score_that_does_not_name_the_record_on_disk_is_refused(self):
        records = self.tmp / "records"
        shutil.copytree(RECORDS, records)
        path = records / "repro-air-jump" / "jit-run.json"
        path.write_text(path.read_text() + "\n")
        with self.assertRaisesRegex(control_rate.ControlRateError, "air-jump"):
            self.rate(_rows(), records=records)

    def test_a_score_of_a_withheld_or_pixel_setting_is_refused_rather_than_misread(self):
        for key, value in (("candidate", "withheld"), ("offer", "signals-reach-evidence-pixel")):
            with self.subTest(key=key):
                doc = json.loads(SCORE.read_text())
                doc[key] = value
                path = self.tmp / f"score-{key}.json"
                path.write_text(json.dumps(doc))
                with self.assertRaises(control_rate.ControlRateError):
                    self.rate(_rows(), score=path)

    def test_the_rows_are_read_by_the_counting_audits_reader(self):
        doc = _rows()
        doc["rows"][0]["outcome"] = "maybe"
        with self.assertRaisesRegex(control_rate.ControlRateError, "unknown outcome"):
            self.rate(doc)

    def test_the_page_names_every_dropped_and_cannot_tell_defect_and_the_rates(self):
        outcomes = {("air-jump", c): "passes" for c in _reproducing("air-jump")}
        outcomes[("no-shooting-in-air", "jit-c4")] = "not-run"
        page = control_rate.render(self.rate(_rows(outcomes)))
        self.assertIn("**15/24** (62.50%)", page)
        self.assertIn("trace-visible **15/19** (78.95%)", page)
        self.assertIn("| air-jump | signal | dropped |", page)
        self.assertIn("| no-shooting-in-air | none | cannot-tell |", page)
        self.assertNotIn("| coin-stays |", page)

    def test_the_command_prints_the_totals_and_writes_the_page(self):
        path = self.tmp / "rows.json"
        path.write_text(json.dumps(_rows()))
        out = self.tmp / "page.md"
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["control-rate", "--score", str(SCORE), "--records", str(RECORDS),
                             "--do-nothing-rows", str(path), "--out", str(out)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buf.getvalue())["reproduced"], 17)
        self.assertIn("Reproduced under the do-nothing rule", out.read_text())


class PublishedFigures(unittest.TestCase):
    """The committed rows, read with the committed baseline, give the figures the audit page publishes."""

    ROWS = REPO / "bench" / "jit" / "public" / "do-nothing-rows.json"
    AUDIT = REPO / "docs" / "repro-audit.md"

    def test_the_audit_publishes_what_the_committed_rows_give(self):
        result = control_rate.rate(SCORE, RECORDS, self.ROWS)
        page = control_rate.render(result)
        audit = self.AUDIT.read_text()
        start = audit.index(control_rate.HEADING)
        self.assertIn(page.strip(), audit[start:])

    def test_the_committed_rows_are_the_public_records_and_name_their_engine(self):
        doc = json.loads(self.ROWS.read_text())
        self.assertEqual(doc["records"], "bench/jit/recordings/public-43465090517/repro")
        engines = {(r.get("engine") or {}).get("version") for runs in doc["evidence"].values() for r in runs}
        self.assertTrue(engines and all(e and e.startswith("4.7.2") for e in engines), engines)


if __name__ == "__main__":
    unittest.main()
