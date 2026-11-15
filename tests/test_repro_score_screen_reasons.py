"""With the screen record, the scorer gives the two miss reasons only a hand finding gave before (#285, step 2).

A miss the engine's record does not show on any library probe is ``probe-language`` where the screen record
says the frames differ (``screen-only``) and the setting offers no check about the screen, and
``route-never-reaches`` where nothing differs in the record or the frames (``neither``). The reader
recomputes both. Offline: hand-built jit-run records and small screen records; no engine, no model."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from expectrail.jit import offer as offer_mod
from expectrail.repro import bench, breakdown, score, screen, visibility
from tests.test_repro_score import BaselineAsPublished, check, sha
from tests.test_repro_score_pixel import PixelFixture, pixel_row

REPO = Path(__file__).resolve().parents[1]


class ScreenFixture(PixelFixture):
    def screen_record(self, unseen: str) -> Path:
        """A screen record of the fixture's bench, in which ``unseen`` (visibility ``none``) sees ``unseen``."""
        sees = {"sig-one": "record-and-screen", "sig-two": "record-and-screen", "cam": "record-only",
                "unseen": unseen}
        box = {"atFrame": 10, "box": [0, 0, 10, 10], "examined": 1, "firstFrame": 5, "frames": 3, "of": 20,
               "pixels": 50, "probe": "jump-w0-x8"}
        rows = []
        for d, s in sees.items():
            record_moves = s in ("record-and-screen", "record-only")
            screen_moves = s in ("record-and-screen", "screen-only")
            rows.append({"id": d, "patchSha256": sha(self.tmp / self.by_id[d]["patch"]),
                         "recordFields": ["player"] if record_moves else [],
                         "probesRecordChanged": int(record_moves), "probesScreenChanged": int(screen_moves),
                         "screen": box if screen_moves else None, "sees": s})
        doc = {"format": screen.FORMAT, "benchSha256": sha(self.bench_path), "engine": "simulated",
               "engineRetries": 0, "frame": {"width": 100, "height": 100}, "maxFramesExamined": 8,
               "probes": ["jump-w0-x8"], "renderer": "none", "replaysPerBuild": {"clean": 2, "defect": 1},
               "unstable": [], "defects": rows, "totals": screen.totals(rows)}
        self.assertEqual(screen.problems(doc), [])
        path = self.tmp / f"screen-{unseen}.json"
        path.write_text(json.dumps(doc))
        return path

    def unseen_row(self, sees: str, **kw) -> dict:
        return next(r for r in self.score(screen_path=self.screen_record(sees), **kw)["rows"] if r["id"] == "unseen")


class TheScreenRecordGivesTheReason(ScreenFixture):
    def test_screen_only_is_probe_language(self):
        self.put("unseen", [check("jit-a", killed=())])
        r = self.unseen_row("screen-only")
        self.assertEqual((r["outcome"], r["missReason"], r["visibility"], r["screen"]),
                         ("not-reproduced", "probe-language", "none", "screen-only"))
        self.assertIn("the frames differ", r["evidence"])

    def test_neither_is_route_never_reaches(self):
        self.put("unseen", [check("jit-a", killed=())])
        r = self.unseen_row("neither")
        self.assertEqual((r["outcome"], r["missReason"]), ("not-reproduced", "route-never-reaches"))
        self.assertIn("nothing differs on any library probe", r["evidence"])

    def test_the_totals_and_the_page_count_them(self):
        self.put("unseen", [check("jit-a", killed=())])
        self.put("cam", [check("jit-a", killed=())])
        record = self.score(screen_path=self.screen_record("neither"))
        self.assertEqual(record["totals"]["misses"], {"route-never-reaches": 1, "no-signal": 1})
        self.assertIn("route-never-reaches: `nothing differs", score.render(record))
        self.assertEqual(score.problems(record), [])

    def test_without_a_screen_record_the_miss_stays_undetermined(self):
        self.put("unseen", [check("jit-a", killed=())])
        r = self.row("unseen")
        self.assertEqual(r["missReason"], "undetermined")
        self.assertNotIn("screen", r)

    def test_a_reason_read_from_the_runs_comes_first(self):
        # A flaky check or a spent budget is what the run shows; the screen record does not overrule it.
        self.put("unseen", [check("jit-a", reference=["pass", "fail", "pass"])])
        self.assertEqual(self.unseen_row("neither")["missReason"], "flaky")
        self.put("unseen", status="nothing-generated", reason="OUT_OF_BUDGET: test")
        self.assertEqual(self.unseen_row("screen-only")["missReason"], "budget")

    def test_a_defect_the_record_shows_keeps_its_reason(self):
        # The visibility record decides first: a signal that moves is a wrong predicate, whatever the screen.
        self.put("sig-two", [check("jit-a", killed=())])
        r = next(r for r in self.score(screen_path=self.screen_record("neither"))["rows"] if r["id"] == "sig-two")
        self.assertEqual(r["missReason"], "wrong-predicate")

    def test_a_reproduced_defect_stays_reproduced(self):
        self.put("unseen", [check("jit-a")])
        r = self.unseen_row("neither")
        self.assertEqual((r["outcome"], r["missReason"]), ("reproduced", None))


class WhereTheScreenRecordCannotSay(ScreenFixture):
    def test_measurements_that_disagree_are_undetermined_and_say_so(self):
        # The visibility record says the engine's record never differs; this screen record says it does.
        self.put("unseen", [check("jit-a", killed=())])
        for sees in ("record-and-screen", "record-only"):
            r = self.unseen_row(sees)
            self.assertEqual(r["missReason"], "undetermined", sees)
            self.assertIn("the two measurements disagree", r["evidence"], sees)

    def test_under_the_pixel_setting_a_screen_only_miss_is_undetermined(self):
        # Checks about the screen were on offer, so the language is not shown to be what failed.
        self.put_px("unseen", [check("jit-a", killed=())], [pixel_row(bug=["pass", "pass", "pass"])])
        r = next(r for r in self.score_px(screen_path=self.screen_record("screen-only"))["rows"]
                 if r["id"] == "unseen")
        self.assertEqual((r["outcome"], r["missReason"]), ("not-reproduced", "undetermined"))
        self.assertIn("checks about the screen were on offer", r["evidence"])

    def test_under_the_pixel_setting_neither_is_still_route_never_reaches(self):
        self.put_px("unseen", [check("jit-a", killed=())], [])
        r = next(r for r in self.score_px(screen_path=self.screen_record("neither"))["rows"] if r["id"] == "unseen")
        self.assertEqual(r["missReason"], "route-never-reaches")

    def test_a_screen_record_that_leaves_the_defect_out_is_refused_and_no_word_gives_no_reason(self):
        path = self.screen_record("neither")
        doc = json.loads(path.read_text())
        doc["defects"] = [r for r in doc["defects"] if r["id"] != "unseen"]
        doc["totals"] = screen.totals(doc["defects"])
        path.write_text(json.dumps(doc))
        self.put("unseen", [check("jit-a", killed=())])
        with self.assertRaisesRegex(score.ScoreError, "unseen: not measured"):
            self.score(screen_path=path)
        # A row the screen record could not measure ("error") reaches the scorer as no word at all.
        for pixel_offer in (False, True):
            self.assertIsNone(score.screen_reason("none", None, pixel_offer))
        self.assertIsNone(score.screen_reason(None, "neither", False))


class TheReaderRecomputesIt(ScreenFixture):
    def scored(self, sees: str) -> dict:
        self.put("unseen", [check("jit-a", killed=())])
        self.put("sig-two", [check("jit-a", killed=())])
        record = self.score(screen_path=self.screen_record(sees))
        self.assertEqual(score.problems(record), [])
        return record

    @staticmethod
    def at(record: dict, did: str) -> int:
        return next(i for i, r in enumerate(record["rows"]) if r["id"] == did)

    def test_each_edit_that_writes_a_reason_the_screen_record_does_not_show_is_refused(self):
        record = self.scored("neither")
        u, s = self.at(record, "unseen"), self.at(record, "sig-two")
        edits = {
            "the other screen reason": lambda d: d["rows"][u].update(missReason="probe-language"),
            "undetermined where the screen record gives one": lambda d: d["rows"][u].update(missReason="undetermined"),
            "a screen reason on a defect the record shows": lambda d: d["rows"][s].update(missReason="route-never-reaches"),
            "the screen word changed under the reason": lambda d: d["rows"][u].update(screen="screen-only"),
            "the visibility changed under the reason": lambda d: d["rows"][u].update(visibility="signal"),
        }
        for name, edit in edits.items():
            bad = copy.deepcopy(record)
            edit(bad)
            bad["totals"] = score.totals(bad["rows"])
            self.assertTrue(score.problems(bad), name)

    def test_probe_language_on_a_pixel_score_is_refused(self):
        record = self.scored("screen-only")
        self.assertEqual(record["rows"][self.at(record, "unseen")]["missReason"], "probe-language")
        bad = copy.deepcopy(record)
        bad["offer"] = offer_mod.PIXEL
        for r in bad["rows"]:
            if r["recordSha256"] is not None:
                r["pixel"] = {"proposed": 0, "kept": 0, "reproducing": []}
        bad["totals"] = score.totals(bad["rows"])
        self.assertTrue(any("only where the screen record shows it" in p for p in score.problems(bad)))

    def test_without_a_screen_record_neither_reason_may_be_written(self):
        self.put("unseen", [check("jit-a", killed=())])
        record = self.score()
        u = self.at(record, "unseen")
        for reason in score.SCREEN_REASONS:
            bad = copy.deepcopy(record)
            bad["rows"][u]["missReason"] = reason
            bad["totals"] = score.totals(bad["rows"])
            self.assertTrue(any("only where the screen record shows it" in p for p in score.problems(bad)), reason)

    def test_a_record_made_as_before_still_reads(self):
        self.put("unseen", [check("jit-a", killed=())])
        record = self.score()
        self.assertEqual(score.problems(record), [])
        self.assertEqual(record["rows"][self.at(record, "unseen")]["missReason"], "undetermined")


class TheBreakdownTakesTheScorersReason(ScreenFixture):
    def test_a_hand_finding_is_shown_beside_it_and_counts_for_nothing(self):
        self.put("unseen", [check("jit-a", killed=())])
        scored = self.score(screen_path=self.screen_record("neither"))
        hand = {"format": breakdown.FORMAT, "written": "2026-11-12",
                "rows": [{"id": "unseen", "reason": "probe-language", "basis": "Seen by hand."}]}
        self.assertEqual(breakdown.problems(hand), [])
        [row] = [r for r in breakdown.breakdown(scored, hand) if r["id"] == "unseen"]
        self.assertEqual((row["reason"], row["source"], row["hand"]["reason"]),
                         ("route-never-reaches", "scorer", "probe-language"))
        self.assertEqual(breakdown.counts(breakdown.breakdown(scored, hand)),
                         {"route-never-reaches": {"misses": 1, "byHand": 0}})


class TheContract(unittest.TestCase):
    def test_the_screen_example_is_a_score_the_reader_accepts_with_both_screen_reasons(self):
        example = score.load(REPO / "contracts" / "examples" / "repro-score-screen.json")
        self.assertIn("screenSha256", example)
        self.assertIn("An example", example["source"])
        given = {r["missReason"] for r in example["rows"]}
        self.assertLessEqual(set(score.SCREEN_REASONS), given)
        for reason in score.SCREEN_REASONS:
            bad = copy.deepcopy(example)
            row = next(r for r in bad["rows"] if r["missReason"] == reason)
            row["missReason"] = "undetermined"
            bad["totals"] = score.totals(bad["rows"])
            self.assertTrue(score.problems(bad), reason)

    def test_the_schema_says_when_the_two_reasons_are_given(self):
        schema = json.loads(score.SCHEMA.read_text(encoding="utf-8"))
        text = schema["$defs"]["reason"]["description"]
        self.assertIn("only with a screen record", text)
        self.assertEqual(tuple(schema["$defs"]["reason"]["enum"]), score.MISS_REASONS)


class TheCommittedRecordsAgreeWithTheHandFindings(unittest.TestCase):
    """On the bench as committed, the rule gives each baseline miss that the records could not classify the
    reason its November 12 hand finding gives. The hand findings were written before the screen record."""

    def test_every_unclassified_baseline_miss_gets_its_hand_reason(self):
        table = BaselineAsPublished("test_the_breakdown_on_the_page_is_the_rule_applied").table()
        seen = {r["id"]: r["visibility"] for r in visibility.load(visibility.RECORD)["defects"]}
        sees = {r["id"]: r["sees"] for r in screen.load(screen.RECORD)["defects"]}
        self.assertEqual(screen.stale(screen.load(screen.RECORD), bench.load(), REPO, bench.BENCH), [])
        hand = {r["id"]: r["reason"] for r in breakdown.load()["rows"]}
        unclassified = [r["id"] for r in table if not r["reproduced"] and seen[r["id"]] == "none"]
        self.assertEqual(len(unclassified), 4)
        given = {d: score.screen_reason(seen[d], sees.get(d), False) for d in unclassified}
        self.assertTrue(all(g is not None for g in given.values()), given)
        self.assertEqual({d: g[0] for d, g in given.items()}, {d: hand[d] for d in unclassified})


if __name__ == "__main__":
    unittest.main()
