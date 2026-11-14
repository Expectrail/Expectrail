"""The reproduction score counts pixel checks on their own, and the screen-only defects apart (#286).

Offline: hand-built jit-run records in the shape the replay writes (expectrail/jit/run.py, ``pixelChecks``)
and a small screen record. No engine, no model, no observer."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import unittest
from pathlib import Path

from expectrail.contracts import load_strict
from expectrail.jit import offer as offer_mod
from expectrail.jit import pixel
from expectrail.repro import score, screen
from expectrail.repro.__main__ import main
from tests.test_repro_score import FAIL3, PASS3, Fixture, check, jit_record, sha

PX = offer_mod.PIXEL
REPO = Path(__file__).resolve().parents[1]


def pixel_check(name="player-drawn", probe="jump-w0-x8") -> dict:
    [doc], errors = pixel.parse_answer([{"id": name, "statement": "The player is drawn.", "object": "player",
                                         "observer": "sam-3.1-anchor", "probe": probe,
                                         "predicate": {"type": "visible", "minScore": 0.8}}],
                                       pixel.BUNDLED_BINDINGS, [probe])
    assert not errors, errors
    return doc


SETTING = {"model": "sam-3.1", "box": "body", "pad": 4.0, "lift": 0.0}


def pixel_row(name="player-drawn", clean=PASS3, bug=FAIL3, candidate=FAIL3, status=None, outcome=None,
              setting=SETTING) -> dict:
    """One row of a record's ``pixelChecks``, with the status and outcome the replay would give its runs."""
    kept = setting is not None and list(clean) == PASS3 and list(bug) == FAIL3
    if status is None:
        status = "kept" if kept else "dropped"
    if outcome is None:
        outcome = ("catch" if list(candidate) == FAIL3 else "no-catch") if kept and candidate else "not-evaluated"
    return {"check": pixel_check(name), "status": status, "reason": None if kept else "test",
            "reservedUsd": 0.1, "setting": setting, "clean": list(clean), "bug": list(bug),
            "candidate": list(candidate) if kept else [], "outcome": outcome}


class PixelFixture(Fixture):
    def put_px(self, did, checks=(), pixel_rows=(), **kw):
        path = self.records / (score.CASE_PREFIX + did) / "jit-run.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = jit_record(self.tmp, self.by_id[did], checks, **kw)
        doc["settings"]["offer"] = PX
        doc["pixelChecks"] = list(pixel_rows)
        path.write_text(json.dumps(doc))
        load_strict(path, "jit-run")   # a record the pipeline could have written
        return path

    def score_px(self, **kw):
        return self.score(offer=PX, **kw)

    def row_px(self, did, **kw):
        return next(r for r in self.score_px(**kw)["rows"] if r["id"] == did)


class APixelCheckReproduces(PixelFixture):
    def test_kept_by_its_runs_and_failing_with_the_no_fix_candidate(self):
        self.put_px("unseen", [check("jit-a", killed=())], [pixel_row()])
        r = self.row_px("unseen")
        self.assertEqual(r["outcome"], "reproduced")
        self.assertEqual(r["reproducing"], ["jit-px-player-drawn"])
        self.assertEqual(r["pixel"], {"proposed": 1, "kept": 1, "reproducing": ["jit-px-player-drawn"]})
        self.assertEqual((r["proposed"], r["kept"]), (2, 1))   # both kinds in the row's own counts; jit-a is not kept

    def test_the_totals_say_what_a_pixel_check_did_and_what_only_a_pixel_check_did(self):
        self.put_px("unseen", [], [pixel_row()])
        self.put_px("sig-one", [check("jit-a")], [pixel_row()])
        self.put_px("sig-two", [check("jit-a")], [pixel_row(bug=["fail", "pass", "fail"])])
        t = self.score_px()["totals"]
        self.assertEqual(t["reproduced"], 3)
        self.assertEqual(t["pixel"], {"proposed": 3, "kept": 2, "reproducedBy": 2, "reproducedOnlyBy": 1})

    def test_two_of_three_on_the_bug_build_or_a_missing_setting_keeps_nothing(self):
        for row in (pixel_row(bug=["fail", "fail", "needs-review"]), pixel_row(clean=["pass", "pass", "needs-review"]),
                    pixel_row(setting=None)):
            with self.subTest(row=row["bug"] + row["clean"]):
                self.put_px("unseen", [], [row])
                r = self.row_px("unseen")
                self.assertEqual(r["outcome"], "not-reproduced")
                self.assertEqual(r["pixel"], {"proposed": 1, "kept": 0, "reproducing": []})

    def test_kept_and_then_not_failing_with_the_no_fix_candidate_is_flaky(self):
        self.put_px("unseen", [], [pixel_row(candidate=["fail", "pass", "fail"])])
        r = self.row_px("unseen")
        self.assertEqual((r["outcome"], r["missReason"]), ("not-reproduced", "flaky"))
        self.assertIn("jit-px-player-drawn failed 3 of 3 on the bug build", r["evidence"])

    def test_kept_and_never_judged_on_the_candidate_does_not_reproduce(self):
        self.put_px("unseen", [], [pixel_row(candidate=[])])
        r = self.row_px("unseen")
        self.assertEqual(r["outcome"], "not-reproduced")
        self.assertEqual(r["pixel"]["kept"], 1)
        self.assertEqual(r["pixel"]["reproducing"], [])

    def test_a_record_out_of_budget_has_no_pixel_checks_and_still_a_pixel_share(self):
        self.put_px("unseen", status="nothing-generated", reason="OUT_OF_BUDGET: test")
        r = self.row_px("unseen")
        self.assertEqual((r["outcome"], r["missReason"]), ("not-reproduced", "budget"))
        self.assertEqual(r["pixel"], {"proposed": 0, "kept": 0, "reproducing": []})


class APixelRowThatDisagreesWithItself(PixelFixture):
    def assert_no_result(self, rows, word):
        self.put_px("unseen", [], rows)
        r = self.row_px("unseen")
        self.assertEqual(r["outcome"], "no-result")
        self.assertIn(word, r["why"])
        self.assertNotIn("pixel", r)
        self.assertEqual(score.problems(self.score_px()), [])

    def test_kept_by_its_status_and_not_by_its_runs(self):
        self.assert_no_result([pixel_row(bug=["fail", "pass", "fail"], status="kept")], "marked kept")

    def test_dropped_by_its_status_and_kept_by_its_runs(self):
        self.assert_no_result([pixel_row(status="dropped")], "marked dropped")

    def test_a_catch_its_candidate_runs_contradict(self):
        self.assert_no_result([pixel_row(candidate=["fail", "pass", "fail"], outcome="catch")], "marked catch")

    def test_the_same_pixel_check_twice(self):
        self.assert_no_result([pixel_row(), pixel_row()], "named once")

    def test_more_runs_than_the_bench_counts(self):
        self.assert_no_result([pixel_row(clean=PASS3 + ["pass"], status="kept")], "marked kept")


class OnlyAPixelScoreHasPixelShares(PixelFixture):
    def test_a_pixel_record_is_no_result_in_a_score_of_another_setting_and_the_other_way_round(self):
        self.put_px("unseen", [], [pixel_row()])
        self.put("sig-one", [check("jit-a")])   # baseline
        base = self.score()
        self.assertEqual(next(r for r in base["rows"] if r["id"] == "unseen")["outcome"], "no-result")
        self.assertFalse(any("pixel" in r for r in base["rows"]))
        self.assertNotIn("pixel", base["totals"])
        px = self.score_px()
        self.assertEqual(next(r for r in px["rows"] if r["id"] == "sig-one")["outcome"], "no-result")

    def test_the_record_refuses_a_pixel_share_where_it_does_not_belong(self):
        self.put_px("unseen", [], [pixel_row()])
        record = self.score_px()
        self.assertEqual(score.problems(record), [])
        moved = copy.deepcopy(record)
        moved["offer"] = "baseline"
        self.assertTrue(any("pixel checks on a row" in p for p in score.problems(moved)))
        missing = copy.deepcopy(record)
        del next(r for r in missing["rows"] if r["id"] == "unseen")["pixel"]
        missing["totals"] = score.totals(missing["rows"])
        self.assertTrue(any("every scored row" in p for p in score.problems(missing)))
        swollen = copy.deepcopy(record)
        row = next(r for r in swollen["rows"] if r["id"] == "unseen")
        row["pixel"]["kept"] = 5
        swollen["totals"] = score.totals(swollen["rows"])
        self.assertTrue(any("do not fit" in p for p in score.problems(swollen)))
        renamed = copy.deepcopy(record)
        row = next(r for r in renamed["rows"] if r["id"] == "unseen")
        row["pixel"]["reproducing"] = row["reproducing"] = ["jit-player-drawn"]   # a trace check's name
        self.assertTrue(any("do not fit" in p for p in score.problems(renamed)))

    def test_it_is_written_and_read_back_and_the_page_names_the_pixel_share(self):
        self.put_px("unseen", [], [pixel_row()])
        record = self.score_px()
        path = score.write(record, self.tmp / "out")
        self.assertEqual(score.load(path), record)
        page = (self.tmp / "out" / score.PAGE).read_text(encoding="utf-8")
        self.assertIn("Pixel checks (#286): 1 proposed, 1 kept; defects a pixel check reproduced: 1, of which only a "
                      "pixel check: 1", page)
        self.assertIn("`jit-px-player-drawn` (pixel)", page)


class TheScreenOnlyDefectsApart(PixelFixture):
    def setUp(self):
        super().setUp()
        sees = {"sig-one": "record-and-screen", "sig-two": "record-and-screen", "cam": "record-only",
                "unseen": "screen-only"}
        box = {"atFrame": 10, "box": [0, 0, 10, 10], "examined": 1, "firstFrame": 5, "frames": 3, "of": 20,
               "pixels": 50, "probe": "jump-w0-x8"}
        rows = [{"id": d, "patchSha256": sha(self.tmp / self.by_id[d]["patch"]),
                 "recordFields": [] if s == "screen-only" else ["player"],
                 "probesRecordChanged": 0 if s == "screen-only" else 1,
                 "probesScreenChanged": 0 if s == "record-only" else 1,
                 "screen": None if s == "record-only" else box, "sees": s} for d, s in sees.items()]
        doc = {"format": screen.FORMAT, "benchSha256": sha(self.bench_path), "engine": "simulated",
               "engineRetries": 0, "frame": {"width": 100, "height": 100}, "maxFramesExamined": 8,
               "probes": ["jump-w0-x8"], "renderer": "none", "replaysPerBuild": {"clean": 2, "defect": 1},
               "unstable": [], "defects": rows, "totals": screen.totals(rows)}
        self.assertEqual(screen.problems(doc), [])
        self.screen_path = self.tmp / "screen.json"
        self.screen_path.write_text(json.dumps(doc))

    def test_the_rate_on_the_screen_only_defects_is_given_apart(self):
        self.put_px("unseen", [], [pixel_row()])
        self.put_px("sig-one", [check("jit-a")], [])
        record = self.score_px(screen_path=self.screen_path)
        self.assertEqual(record["screenSha256"], sha(self.screen_path))
        self.assertEqual({r["id"]: r["screen"] for r in record["rows"]},
                         {"sig-one": "record-and-screen", "sig-two": "record-and-screen", "cam": "record-only",
                          "unseen": "screen-only"})
        self.assertEqual((record["totals"]["screenOnly"], record["totals"]["reproducedScreenOnly"]), (1, 1))
        page = score.render(record)
        self.assertIn("Of the defects that change only the screen on a library probe (the screen record): 1 of 1", page)
        self.assertIn("none; screen record: screen-only", page)

    def test_it_works_for_any_setting_and_without_it_nothing_is_said(self):
        self.put("sig-one", [check("jit-a")])
        with_screen = self.score(screen_path=self.screen_path)
        self.assertEqual((with_screen["totals"]["screenOnly"], with_screen["totals"]["reproducedScreenOnly"]), (1, 0))
        plain = self.score()
        self.assertNotIn("screenSha256", plain)
        self.assertNotIn("screenOnly", plain["totals"])
        self.assertFalse(any("screen" in r for r in plain["rows"]))

    def test_a_screen_record_for_another_bench_is_refused(self):
        doc = json.loads(self.screen_path.read_text())
        doc["defects"][0]["patchSha256"] = "0" * 64
        self.screen_path.write_text(json.dumps(doc))
        with self.assertRaisesRegex(score.ScoreError, "screen record does not describe this bench"):
            self.score(screen_path=self.screen_path)

    def test_screen_on_some_rows_only_or_without_the_records_digest_is_refused(self):
        self.put("sig-one", [check("jit-a")])
        record = self.score(screen_path=self.screen_path)
        self.assertEqual(score.problems(record), [])
        partial = copy.deepcopy(record)
        del partial["rows"][0]["screen"]
        self.assertTrue(any("some rows" in p for p in score.problems(partial)))
        unnamed = copy.deepcopy(record)
        del unnamed["screenSha256"]
        self.assertTrue(any("only when the score names" in p for p in score.problems(unnamed)))



class TheCommandLine(unittest.TestCase):
    def test_score_takes_the_pixel_setting_and_the_committed_screen_record_of_the_real_bench(self):
        import shutil
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="repro-score-pixel-cli-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "records").mkdir()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["score", "--records", str(tmp / "records"), "--out", str(tmp / "score"), "--offer", PX,
                         "--screen", str(screen.RECORD), "--source", "no records: a test"])
        self.assertEqual(code, 0, err.getvalue())
        record = score.load(tmp / "score" / score.NAME)
        committed = screen.load(screen.RECORD)
        self.assertEqual(record["offer"], PX)
        self.assertEqual(record["totals"]["screenOnly"], committed["totals"]["screen-only"])
        self.assertEqual(record["totals"]["reproducedScreenOnly"], 0)
        self.assertEqual(record["totals"]["noResult"], record["totals"]["defects"])   # no record, no result
        self.assertNotIn("pixel", record["totals"])   # no row was scored, so no row has a pixel share
        self.assertEqual(record["screenSha256"], sha(screen.RECORD))


class TheExample(unittest.TestCase):
    def test_the_pixel_example_is_a_sound_score_record(self):
        doc = json.loads((REPO / "contracts" / "examples" / "repro-score-pixel.json").read_text(encoding="utf-8"))
        self.assertEqual(score.problems(doc), [])
        self.assertEqual(doc["offer"], PX)
        self.assertIn("pixel", doc["totals"])
        self.assertIn("screenOnly", doc["totals"])


if __name__ == "__main__":
    unittest.main()
