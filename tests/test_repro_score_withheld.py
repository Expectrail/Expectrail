"""The reproduction score counts one candidate setting at a time (issue #285, step 6): records made with the
candidate withheld from the model apart from those made with it shown. Offline: no engine, no model."""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail.contracts import load_strict
from expectrail.jit.run import from_base_alone, generate
from expectrail.repro import bench, score
from expectrail.repro.__main__ import main
from expectrail.jit.intent import spark_intent
from tests.jit_fixtures import ANSWER, PROFILE, JitGame, Transport, model, reply
from tests.test_repro_score import Fixture, check

REPO = Path(__file__).resolve().parents[1]


class WithheldFixture(Fixture):
    def put_made(self, did: str, candidate, checks=None) -> Path:
        """A record of ``did`` with one reproducing check, made with ``candidate`` (None: before the setting)."""
        path = self.put(did, [check("jit-a")] if checks is None else checks)
        doc = json.loads(path.read_text())
        if candidate is not None:
            doc["settings"]["candidate"] = candidate
        path.write_text(json.dumps(doc))
        load_strict(path, "jit-run")   # still a record the pipeline could have written
        return path

    def rows(self, **kw) -> dict:
        return {r["id"]: r for r in self.score(**kw)["rows"]}


class OneSettingPerScore(WithheldFixture):
    def test_by_default_a_withheld_record_gives_no_result_and_a_shown_one_counts(self):
        self.put_made("sig-one", "withheld")
        self.put_made("sig-two", "shown")
        self.put_made("cam", None)   # written before the setting existed: made with the candidate shown
        rows = self.rows()
        self.assertEqual(rows["sig-one"]["outcome"], "no-result")
        self.assertIn("made with the candidate withheld, and this score counts records made with it shown",
                      rows["sig-one"]["why"])
        self.assertEqual((rows["sig-two"]["outcome"], rows["cam"]["outcome"]), ("reproduced", "reproduced"))

    def test_a_withheld_score_counts_only_withheld_records(self):
        self.put_made("sig-one", "withheld")
        self.put_made("sig-two", "shown")
        self.put_made("cam", None)
        rows = self.rows(candidate="withheld")
        self.assertEqual((rows["sig-one"]["outcome"], rows["sig-one"]["reproducing"]), ("reproduced", ["jit-a"]))
        for did in ("sig-two", "cam"):
            self.assertEqual(rows[did]["outcome"], "no-result")
            self.assertIn("made with the candidate shown, and this score counts records made with it withheld",
                          rows[did]["why"])

    def test_a_record_of_the_other_setting_never_raises_the_rate(self):
        for did in self.IDS:
            self.put_made(did, "withheld")
        self.assertEqual(self.score()["totals"]["reproduced"], 0)
        self.assertEqual(self.score(candidate="withheld")["totals"]["reproduced"], len(self.IDS))

    def test_the_offer_and_the_candidate_must_both_match(self):
        path = self.put_made("sig-one", "withheld")
        doc = json.loads(path.read_text())
        doc["settings"]["offer"] = "signals-reach"
        path.write_text(json.dumps(doc))
        self.assertEqual(self.rows(candidate="withheld")["sig-one"]["outcome"], "no-result")
        self.assertEqual(self.rows(candidate="withheld", offer="signals-reach")["sig-one"]["outcome"], "reproduced")
        self.assertEqual(self.rows(offer="signals-reach")["sig-one"]["outcome"], "no-result")

    def test_any_other_setting_is_refused_before_anything_is_read(self):
        for bad in ("hidden", "", None, "Withheld"):
            with self.subTest(bad=bad), self.assertRaises(score.ScoreError):
                self.score(candidate=bad)


class TheScoreRecordNamesIt(WithheldFixture):
    def test_a_withheld_score_says_so_and_a_shown_one_is_as_before(self):
        self.put_made("sig-one", "withheld")
        withheld, shown = self.score(candidate="withheld"), self.score()
        self.assertEqual(withheld["candidate"], "withheld")
        self.assertNotIn("candidate", shown)
        self.assertEqual(score.problems(withheld), [])
        self.assertEqual(score.problems(shown), [])

    def test_it_is_written_and_read_back_the_same(self):
        self.put_made("sig-one", "withheld")
        record = self.score(candidate="withheld")
        path = score.write(record, self.tmp / "out")
        self.assertEqual(score.load(path), record)

    def test_the_reader_refuses_any_other_value_including_an_explicit_shown(self):
        self.put_made("sig-one", "withheld")
        record = self.score(candidate="withheld")
        for bad in ("shown", "hidden", None, True):
            with self.subTest(bad=bad):
                tampered = dict(record, candidate=bad)
                self.assertTrue(any("candidate" in p for p in score.problems(tampered)), score.problems(tampered))

    def test_the_page_says_withheld_and_what_that_means_and_a_shown_page_does_not(self):
        self.put_made("sig-one", "withheld")
        page = score.render(self.score(candidate="withheld"))
        self.assertIn("Candidate: **withheld**", page)
        self.assertIn("derived from the report and the bug build alone", page)
        self.assertNotIn("Candidate:", score.render(self.score()))

    def test_the_settings_are_spelled_as_the_pipeline_writes_them(self):
        from expectrail.jit import intent
        self.assertEqual(score.CANDIDATE_SETTINGS, (intent.SHOWN, intent.WITHHELD))
        schema = json.loads(score.SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["candidate"], {"const": intent.WITHHELD,
                                                             "description": schema["properties"]["candidate"]["description"]})

    def test_the_example_is_a_withheld_score_the_reader_accepts(self):
        example = score.load(REPO / "contracts" / "examples" / "repro-score-withheld.json")
        self.assertEqual(example["candidate"], "withheld")
        self.assertIn("Not a measured run", example["source"])


class OneWholeRunWithheld(unittest.TestCase):
    """The pipeline on the simulated game with a fake model, with the candidate withheld, exactly as a live
    run in repro mode would get a case; then the score command on the record it wrote."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="repro-withheld-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        doc = bench.load()
        self.doc = dict(doc, defects=[d for d in doc["defects"] if d["id"] == "air-jump"])
        self.bench_path = self.tmp / "defects.json"
        self.bench_path.write_text(json.dumps(self.doc))
        self.case = next(c for c in score.cases(doc) if c["case"] == "repro-air-jump")

    def run_case(self, candidate_to_model: str) -> dict:
        if candidate_to_model == "withheld":
            intent = spark_intent(transport=Transport(reply(ANSWER)), candidate="withheld")
        else:
            intent, _transport = model(ANSWER)
        out = self.tmp / "records" / self.case["case"]
        report = (REPO / self.case["report"]).read_text(encoding="utf-8", errors="replace")
        return generate(PROFILE, report, REPO / self.case["candidate"], [REPO / self.case["base"]], out,
                        runner=JitGame(), intent=intent, variants_fn=lambda candidate, base: [],
                        candidate_to_model=candidate_to_model)

    def run_score(self, *extra) -> tuple[int, str]:
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            try:
                code = main(["score", "--bench", str(self.bench_path), "--records", str(self.tmp / "records"),
                             "--out", str(self.tmp / "score"), "--no-visibility", *extra])
            except SystemExit as exc:
                code = exc.code
        return code, err.getvalue()

    def test_a_withheld_run_is_reproduced_under_withheld_and_is_no_result_by_default(self):
        doc = self.run_case("withheld")
        self.assertEqual(doc["status"], "complete", doc["reason"])
        self.assertEqual(doc["settings"]["candidate"], "withheld")
        code, err = self.run_score("--candidate", "withheld")
        self.assertEqual(code, 0, err)
        record = score.load(self.tmp / "score" / score.NAME)
        self.assertEqual(record["candidate"], "withheld")
        row = record["rows"][0]
        self.assertEqual((row["outcome"], row["reproducing"]), ("reproduced", ["jit-no-extra-air-jumps"]))
        # The scorer and the pipeline's own reading agree: every reproducing check came from the base alone.
        self.assertEqual(from_base_alone(doc)["fromBaseAlone"], row["reproducing"])
        self.assertIn("Candidate: **withheld**", (self.tmp / "score" / score.PAGE).read_text())
        shown = score.score(self.doc, self.tmp / "records", bench_path=self.bench_path)
        self.assertEqual(shown["rows"][0]["outcome"], "no-result")
        self.assertNotIn("candidate", shown)

    def test_a_shown_run_counts_by_default_and_is_no_result_under_withheld(self):
        doc = self.run_case("shown")
        self.assertEqual(doc["settings"]["candidate"], "shown")
        self.assertEqual(from_base_alone(doc)["fromBaseAlone"], [])
        self.assertEqual(score.score(self.doc, self.tmp / "records", bench_path=self.bench_path)["rows"][0]["outcome"],
                         "reproduced")
        withheld = score.score(self.doc, self.tmp / "records", bench_path=self.bench_path, candidate="withheld")
        self.assertEqual(withheld["rows"][0]["outcome"], "no-result")

    def test_any_other_value_exits_2_and_writes_nothing(self):
        code, err = self.run_score("--candidate", "hidden")
        self.assertEqual(code, 2)
        self.assertIn("--candidate", err)
        self.assertFalse((self.tmp / "score").exists())
