"""A count a ledger row quotes, tied to the notices its run published and counted again."""
from __future__ import annotations

import copy
import json
import unittest

from expectrail import capabilities as cap
from expectrail import capability_runs as runs
from tests.test_capability_runs import RUN, SAVED_NOTICES, LedgerRunsTest, _job, _run, saved_notices

BENCH = {"titled": "Held-out bench *", "not": ["Held-out bench clean"]}


def _count(says: str = "2 of 3", n: int = 2, of: int = 3, **more) -> dict:
    out = {"says": says, "n": n, "of": of, **BENCH, **more}
    if "reads" not in out:
        out.setdefault("count", "caught with SAM on: yes")
    return out


def _cite(*counts: dict, number: str = "1", shows: str = "2 of 3 held-out bugs caught") -> dict:
    return {"kind": "run", "ref": RUN + number, "conclusion": "success", "counts": list(counts), "shows": shows}


def _ledger(*evidence: dict) -> dict:
    return {"rows": [{"id": "mode", "status": "measured", "evidence": list(evidence)}], "timings": []}


def _notice(variant: str, message: str) -> dict:
    return {"title": f"Held-out bench {variant}", "message": message}


THREE = {
    "a": [_notice("sinking/v1", "caught with SAM on: yes; caught with SAM off: no; over 5 routes: engine 5 pass")],
    "b": [_notice("layering/v1", "caught with SAM on: yes; caught with SAM off: yes; over 5 routes: engine 5 fail"),
          {"title": "Bench time layering/v1", "message": "20 s"}],
    "c": [_notice("fall/v1", "caught with SAM on: no; caught with SAM off: no; over 5 routes: engine 5 pass")],
    "clean": [_notice("clean", "false alarm with SAM on: no; false alarm with SAM off: no; over 5 routes")],
}


class _Counted(unittest.TestCase):
    def check(self, *counts: dict, notices: dict | None = None, endings: dict | None = None,
              reader="default") -> list[str]:
        notices = THREE if notices is None else notices
        endings = endings or {}
        run = _run(*[_job(f"bench ({key})", endings.get(key, "success"), job_id=key) for key in notices])

        def read_notices(job_id: str) -> list:
            answer = notices[job_id]
            if isinstance(answer, Exception):
                raise answer
            return answer
        return runs.recheck(_ledger(_cite(*counts)), {"1": run}.__getitem__,
                            read_notices if reader == "default" else reader)[0]


class CountTest(_Counted):
    def test_a_count_the_notices_give_has_no_problem(self):
        self.assertEqual(self.check(_count()), [])
        self.assertEqual(self.check(_count("1 of 3", 1, 3, count="caught with SAM off: yes")), [])

    def test_a_count_the_notices_do_not_give_is_a_problem_that_says_both(self):
        self.assertEqual(self.check(_count("3 of 3", 3, 3)), [
            "mode: run 1: '3 of 3': 3 of 3 is recorded and the run's notices give 2 of 3 (titled 'Held-out bench *', "
            "with the field 'caught with SAM on: yes')"])
        self.assertEqual(len(self.check(_count("2 of 4", 2, 4))), 1)
        self.assertEqual(len(self.check(_count("0 of 3", 0, 3))), 1)

    def test_a_notice_left_out_by_not_is_not_counted(self):
        # With the clean game's notice counted there would be four.
        self.assertEqual(self.check(_count()), [])
        found = self.check({"says": "2 of 3", "n": 2, "of": 3, "titled": "Held-out bench *",
                            "count": "caught with SAM on: yes"})
        self.assertIn("give 2 of 4", found[0])

    def test_a_field_is_matched_whole_never_as_part_of_another(self):
        notices = {"a": [_notice("x", "not caught with SAM on: yes; caught with SAM on: yes!")],
                   "b": [_notice("y", "caught with SAM on: yes, twice")],
                   "c": [_notice("z", "  caught with SAM on: yes  ;other")]}
        found = self.check(_count("3 of 3", 3, 3), notices=notices)
        self.assertIn("give 1 of 3", found[0])

    def test_a_title_is_matched_whole_and_only_the_star_is_special(self):
        self.assertTrue(runs.matches("Demo run *", "Demo run 2"))
        self.assertTrue(runs.matches("Demo run *", "Demo run 2 review"))
        self.assertTrue(runs.matches("Demo run * *", "Demo run 2 review"))
        self.assertFalse(runs.matches("Demo run * *", "Demo run 2"))
        self.assertFalse(runs.matches("Demo run *", "A Demo run 2"))
        self.assertFalse(runs.matches("Demo run", "Demo run 2"))
        self.assertTrue(runs.matches("Glimmer+engine (no SAM)?", "Glimmer+engine (no SAM)?"))
        self.assertFalse(runs.matches("Glimmer+engine (no SAM)?", "Glimmer+engine (no SAM"))
        self.assertFalse(runs.matches("a.c", "abc"))
        self.assertFalse(runs.matches("[ab]", "a"))

    def test_no_notice_with_the_title_is_cannot_tell(self):
        found = self.check(_count(titled="Dev bench *"))
        self.assertEqual(found, ["mode: run 1: '2 of 3': cannot tell: the run published no notice titled 'Dev bench *'"])
        self.assertEqual(len(self.check(_count("0 of 3", 0, 3), notices={"a": []})), 1)

    def test_the_same_notice_twice_is_cannot_tell_not_counted_twice(self):
        notices = dict(THREE, d=THREE["a"])
        found = self.check(_count("3 of 4", 3, 4), notices=notices)
        self.assertEqual(found, ["mode: run 1: '3 of 4': cannot tell: the run published the notice "
                                 "'Held-out bench sinking/v1' 2 times, and a count takes each once"])

    def test_a_notice_from_a_job_that_did_not_end_in_success_is_a_problem(self):
        found = self.check(_count(), endings={"c": "failure"})
        self.assertEqual(found, ["mode: run 1: '2 of 3': rests on the notice 'Held-out bench fall/v1' from job "
                                 "'bench (c)', which ended in failure"])

    def test_a_skipped_job_is_not_asked_for_notices(self):
        notices = dict(THREE, publish=KeyError("a skipped job was asked about"))
        self.assertEqual(self.check(_count(), notices=notices, endings={"publish": "skipped"}), [])

    def test_notices_that_cannot_be_read_are_cannot_tell_for_every_count_of_the_run(self):
        for failure, text in ((runs.RunUnreadable("job c: gh api exited 1: HTTP 403"), "job c: gh api exited 1: HTTP 403"),
                              (KeyError("title"), "the notices reader failed: KeyError: 'title'")):
            found = self.check(_count(), _count("1 of 3", 1, 3, count="caught with SAM off: yes"),
                               notices=dict(THREE, c=failure))
            self.assertEqual(found, [f"mode: run 1: '2 of 3': cannot tell: {text}",
                                     f"mode: run 1: '1 of 3': cannot tell: {text}"])

    def test_without_a_notices_reader_a_count_is_cannot_tell(self):
        self.assertEqual(self.check(_count(), reader=None),
                         ["mode: run 1: '2 of 3': cannot tell: no reader for the run's notices was given"])

    def test_a_run_that_is_not_finished_has_its_counts_left_alone(self):
        doc = _ledger(_cite(_count()))
        found = runs.recheck(doc, {"1": _run(status="in_progress", conclusion=None)}.__getitem__, lambda job: [])[0]
        self.assertEqual(found, ["mode: run 1: cannot tell: the run is in_progress, not completed"])


class ReadsTest(_Counted):
    SUMMARY = {"s": [{"title": "Judge summary glimmer", "message": "good fixes accepted 8 of 8; bad fixes accepted 0 of 7; undecided 0"}]}

    def reads(self, n: int = 0, of: int = 7, **more) -> dict:
        return {"says": f"{n} of {of}", "n": n, "of": of, "titled": "Judge summary glimmer",
                "reads": "bad fixes accepted {n} of {of}", **more}

    def test_a_count_one_notice_states_is_read_from_its_field(self):
        self.assertEqual(self.check(self.reads(), notices=self.SUMMARY), [])

    def test_a_count_the_notice_does_not_state_is_a_problem(self):
        self.assertEqual(self.check(self.reads(1, 7), notices=self.SUMMARY),
                         ["mode: run 1: '1 of 7': the notice 'Judge summary glimmer' has no field "
                          "'bad fixes accepted 1 of 7'"])
        # "8 of 8" is in the message, for the good fixes: another field does not count.
        self.assertEqual(len(self.check(self.reads(8, 8), notices=self.SUMMARY)), 1)

    def test_two_notices_with_the_title_is_cannot_tell(self):
        two = {"s": self.SUMMARY["s"], "t": [{"title": "Judge summary sam", "message": "bad fixes accepted 0 of 7"}]}
        found = self.check(self.reads(titled="Judge summary *"), notices=two)
        self.assertEqual(found, ["mode: run 1: '0 of 7': cannot tell: 2 notices are titled 'Judge summary *', and a "
                                 "count read from one notice takes exactly one"])


class ReadOnceTest(unittest.TestCase):
    def test_notices_are_read_once_a_run_and_only_for_a_run_with_counts(self):
        asked: list[str] = []

        def read_notices(job_id: str) -> list:
            asked.append(job_id)
            return THREE[job_id]
        answers = {"1": _run(*[_job(key, job_id=key) for key in THREE]), "2": _run(_job("other", job_id="other"))}
        doc = _ledger(_cite(_count()), _cite(_count()), {"kind": "run", "ref": RUN + "2", "conclusion": "success",
                                                         "shows": "it ran"})
        problems, checked = runs.recheck(doc, answers.__getitem__, read_notices)
        self.assertEqual((problems, asked), ([], list(THREE)))
        self.assertEqual(checked, ["run 1: completed, success, attempt 1, 4 jobs, 5 notices",
                                   "run 2: completed, success, attempt 1, 1 jobs"])


class GithubNoticesTest(unittest.TestCase):
    PAGE = [{"annotation_level": "notice", "title": "Held-out bench clean", "message": "false alarm with SAM on: no",
             "path": ".github", "start_line": 1},
            {"annotation_level": "warning", "title": "Held-out bench clean", "message": "deprecated"},
            {"annotation_level": "notice", "title": None, "message": "no title"}]

    def reader(self, pages: dict, asked: list | None = None):
        def call(path: str) -> str:
            if asked is not None:
                asked.append(path)
            answer = pages.get(int(path.rsplit("page=", 1)[1]), [])
            return answer if isinstance(answer, str) else json.dumps(answer)
        return runs.github_notices(call)

    def test_it_asks_for_the_jobs_annotations_and_keeps_the_notices(self):
        asked: list[str] = []
        found = self.reader({1: self.PAGE}, asked)("77")
        self.assertEqual(asked, ["repos/Expectrail/Expectrail/check-runs/77/annotations?per_page=100&page=1"])
        self.assertEqual(found, [{"title": "Held-out bench clean", "message": "false alarm with SAM on: no"},
                                 {"title": "", "message": "no title"}])

    def test_more_than_a_page_is_read_page_by_page(self):
        full = [dict(self.PAGE[0], title=f"n{i}") for i in range(100)]
        asked: list[str] = []
        self.assertEqual(len(self.reader({1: full, 2: full[:3]}, asked)("77")), 103)
        self.assertEqual(len(asked), 2)

    def test_pages_that_never_end_are_unreadable(self):
        full = [dict(self.PAGE[0], title=f"n{i}") for i in range(100)]
        with self.assertRaisesRegex(runs.RunUnreadable, "more than 500 annotations"):
            self.reader({page: full for page in range(1, 9)})("77")

    def test_an_answer_that_is_not_a_list_of_annotations_is_unreadable(self):
        for answer in ("<html>", {"message": "Not Found"}, [{"title": "x"}], [{"annotation_level": "notice"}],
                       [{"annotation_level": "notice", "title": "x", "message": None}], ["x"]):
            with self.assertRaises(runs.RunUnreadable, msg=answer):
                self.reader({1: answer})("77")


class LedgerCountsTest(unittest.TestCase):
    """The committed ledger, counted against the notices GitHub gave (tests/capability_notices.json). No network."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = cap.load()
        helper = LedgerRunsTest()
        helper.doc = cls.doc
        cls.answers = helper.answers()

    def counted(self, doc: dict) -> list[str]:
        return runs.recheck(doc, copy.deepcopy(self.answers).__getitem__, saved_notices)[0]

    def entries(self, doc: dict) -> list[tuple[dict, dict]]:
        return [(ev, count) for row in doc["rows"] for ev in row["evidence"] for count in ev.get("counts", [])]

    def test_every_count_tied_to_notices_is_the_count_the_saved_notices_give(self):
        self.assertEqual(self.counted(self.doc), [])
        self.assertGreaterEqual(len(self.entries(self.doc)), 15)
        for ev, _ in self.entries(self.doc):
            self.assertIn(runs._split(ev["ref"])[0], SAVED_NOTICES)

    def test_each_count_fails_when_its_number_is_changed(self):
        for index, (_, count) in enumerate(self.entries(self.doc)):
            for key in ("n", "of"):
                doc = copy.deepcopy(self.doc)
                changed = self.entries(doc)[index][1]
                changed[key] += 1
                found = self.counted(doc)
                self.assertEqual(len(found), 1, (count, key, found))
                self.assertIn(repr(count["says"]), found[0])

    def test_the_ledger_has_no_offline_count_problem_and_says_how_many_counts_are_tied(self):
        self.assertEqual(cap.row_problems(self.doc), [])
        quoted, tied = cap.quoted_counts(self.doc)
        self.assertGreaterEqual(tied, 11)
        self.assertLessEqual(tied, quoted)
        self.assertIn(f"Of the {quoted} counts quoted beside a run link, "
                      f"{'every one' if tied == quoted else tied} are tied to notices", cap.render(self.doc))


class OfflineTest(unittest.TestCase):
    def problems(self, shows: str, *counts: dict) -> list[str]:
        return cap.count_problems("mode", _cite(*counts, shows=shows))

    def test_a_count_whose_words_and_numbers_agree_has_no_problem(self):
        self.assertEqual(self.problems("2 of 3 held-out bugs caught, no false alarm", _count(),
                                       _count("no false alarm", 1, 1, titled="Held-out bench clean")), [])

    def test_words_the_evidence_does_not_say_are_a_problem(self):
        self.assertEqual(self.problems("3 of 3 caught", _count()),
                         ["mode: run 1: the count '2 of 3' is tied to notices and the evidence does not say it"])

    def test_numbers_that_are_not_the_ones_in_the_words_are_a_problem(self):
        self.assertEqual(self.problems("2 of 3 caught", _count(n=3)),
                         ["mode: run 1: the count '2 of 3' is recorded as 3 of 3"])
        self.assertEqual(len(self.problems("2 of 3 caught", _count(of=4))), 1)

    def test_more_than_there_are_two_counts_in_one_entry_and_the_same_words_twice_are_problems(self):
        self.assertEqual(self.problems("4 of 3 caught", _count("4 of 3", 4, 3)),
                         ["mode: run 1: the count '4 of 3': 4 of 3 is more than there are"])
        self.assertEqual(self.problems("2 of 3 on, 1 of 3 off", _count("2 of 3 on, 1 of 3", 2, 3)),
                         ["mode: run 1: the count '2 of 3 on, 1 of 3' quotes 2 counts; tie each to notices on its own"])
        self.assertEqual(self.problems("2 of 3 caught", _count(), _count()),
                         ["mode: run 1: the count '2 of 3' is tied to notices twice"])

    def test_a_field_with_a_semicolon_can_never_match_and_is_a_problem(self):
        self.assertEqual(len(self.problems("2 of 3 caught", _count(count="a: yes; b: no"))), 1)
        entry = {"says": "2 of 3", "n": 2, "of": 3, "titled": "Summary", "reads": "{n} of {of}; undecided 0"}
        self.assertEqual(len(self.problems("2 of 3 caught", entry)), 1)

    def test_reads_needs_each_number_once(self):
        entry = {"says": "2 of 3", "n": 2, "of": 3, "titled": "Summary", "reads": "{n} of {of} of {of}"}
        self.assertEqual(self.problems("2 of 3 caught", entry),
                         ["mode: run 1: the count '2 of 3': 'reads' must have {n} and {of} once each"])

    def test_row_problems_reports_a_bad_count_in_the_ledger(self):
        doc = copy.deepcopy(cap.load())
        row = next(r for r in doc["rows"] if r["id"] == "sam-observer")
        row["evidence"][0]["counts"][1]["n"] = 5
        self.assertEqual(cap.row_problems(doc), ["sam-observer: run 41003749744: the count '4 of 8' is recorded as 5 of 8"])

    def test_what_counts_as_a_quoted_count(self):
        found = [m.group(0) for m in cap._QUOTED.finditer(
            "8 of 8 caught, 3 of 12 flagged; $3.67 for 34 candidates; 1 of 2.5; version 4 of 5x; 10 of 10")]
        self.assertEqual(found, ["8 of 8", "3 of 12", "10 of 10"])

    def test_the_same_words_twice_in_one_sentence_need_two_entries_to_be_tied_twice(self):
        row = {"id": "mode", "evidence": [_cite(_count("8 of 8", 8, 8), shows="8 of 8 on and 8 of 8 off")]}
        self.assertEqual(cap.quoted_counts({"rows": [row]}), (2, 1))

    def test_the_page_marks_evidence_whose_counts_are_tied(self):
        page = cap.render(cap.load())
        self.assertIn("Counted from the run's notices: 8 of 8, 4 of 8", page)
        self.assertIn('no false alarm (1 of 1 with "false alarm with SAM on: no")', page)


class SchemaTest(unittest.TestCase):
    def errors(self, change) -> list:
        import jsonschema

        doc = copy.deepcopy(cap.load())
        row = next(r for r in doc["rows"] if r["id"] == "godot-verify")
        run = next(e for e in row["evidence"] if e.get("counts"))
        test = next(e for e in row["evidence"] if e["kind"] == "test")
        change(run, test)
        validator = jsonschema.Draft202012Validator(json.loads(cap.SCHEMA.read_text(encoding="utf-8")))
        return list(validator.iter_errors(doc))

    def test_the_schema_takes_counts_on_a_run_only_and_one_way_of_counting(self):
        self.assertEqual(self.errors(lambda run, test: None), [])
        entry = {"says": "8 of 8", "n": 8, "of": 8, "titled": "Held-out bench *"}
        for change in (
            lambda run, test: test.update(counts=[dict(entry, count="x")]),
            lambda run, test: run.update(counts=[]),
            lambda run, test: run.update(counts=[entry]),
            lambda run, test: run.update(counts=[dict(entry, count="x", reads="{n} of {of}")]),
            lambda run, test: run.update(counts=[dict(entry, reads="8 of 8")]),
            lambda run, test: run.update(counts=[dict(entry, count="x", of=0)]),
            lambda run, test: run.update(counts=[dict(entry, count="x", n=-1)]),
            lambda run, test: run.update(counts=[dict(entry, count="x", n="8")]),
            lambda run, test: run.update(counts=[dict(entry, count="x", pattern=".*")]),
            lambda run, test: run.update(counts=[dict(entry, count="x", **{"not": []})]),
        ):
            self.assertTrue(self.errors(change))


if __name__ == "__main__":
    unittest.main()
