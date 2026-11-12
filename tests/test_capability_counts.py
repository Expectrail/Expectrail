"""A count a ledger row quotes, tied to the notices its run published and counted again."""
from __future__ import annotations

import copy
import json
import random
import unittest

from expectrail import capabilities as cap
from expectrail import capability_runs as runs
from tests.test_capability_runs import RUN, SAVED_NOTICES, LedgerRunsTest, _job, _run, saved_notices

BENCH = {"titled": "Held-out bench *", "not": ["Held-out bench clean"]}


def _count(says: str = "2 of 3", n: int = 2, of: int = 3, **more) -> dict:
    out = {"says": says, "n": n, "of": of, **BENCH, **more}
    if "reads" not in out:
        out.setdefault("count", "caught with SAM on: yes")
        if out["count"].endswith(": yes"):
            out.setdefault("otherwise", out["count"][:-len("yes")] + "no")
    return {key: value for key, value in out.items() if value is not None}


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
        # The clean game's notice says nothing about "caught", so it is not a fourth "no".
        found = self.check({"says": "2 of 3", "n": 2, "of": 3, "titled": "Held-out bench *",
                            "count": "caught with SAM on: yes", "otherwise": "caught with SAM on: no"})
        self.assertEqual(found, ["mode: run 1: '2 of 3': cannot tell: the notice 'Held-out bench clean' has neither "
                                 "the field 'caught with SAM on: yes' nor the field 'caught with SAM on: no'"])
        found = self.check({"says": "2 of 3", "n": 2, "of": 3, "titled": "Held-out bench *",
                            "count": "over 5 routes: engine 5 pass", "otherwise": "over 5 routes: engine 5 fail"},
                           notices={key: THREE[key] for key in "abc"})
        self.assertEqual(found, [])
        found = self.check({"says": "2 of 3", "n": 2, "of": 3, "titled": "*", "not": ["Bench time *", "* clean"],
                            "count": "over 5 routes: engine 5 pass", "otherwise": "over 5 routes: engine 5 fail"})
        self.assertEqual(found, [])

    def test_a_field_is_matched_whole_never_as_part_of_another(self):
        notices = {"a": [_notice("x", "not caught with SAM on: yes; caught with SAM on: yes!")],
                   "b": [_notice("y", "caught with SAM on: yes, twice")],
                   "c": [_notice("z", "  caught with SAM on: yes  ;other")]}
        self.assertEqual(runs.fields(notices["c"][0]["message"]), ["caught with SAM on: yes", "other"])
        self.assertEqual([runs._stated([item[0]], "caught with SAM on: yes", "caught with SAM on: no")[0]
                          for item in notices.values()], [0, 0, 1])
        # Two of the three have neither field: that is "cannot tell", not one of three.
        found = self.check(_count("1 of 3", 1, 3), notices=notices)
        self.assertEqual(found, ["mode: run 1: '1 of 3': cannot tell: the notice 'Held-out bench x' has neither the "
                                 "field 'caught with SAM on: yes' nor the field 'caught with SAM on: no' (and 1 more)"])

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


class EveryNoticeSaysWhichTest(_Counted):
    """The merge guard's first reason on #315: a notice that lacks the field is not a "no"."""

    MISSED = {"count": "missed with SAM on: yes"}

    def test_a_zero_is_not_confirmed_by_a_field_no_notice_has(self):
        # The reviewer's case: no notice has a field about "missed", and "0 of 3" passed.
        found = self.check(_count("0 of 3", 0, 3, otherwise=None, **self.MISSED))
        self.assertEqual(found, ["mode: run 1: '0 of 3': cannot tell: the notice 'Held-out bench sinking/v1' has no "
                                 "field 'missed with SAM on: yes', and the count names no field ('otherwise') that a "
                                 "notice not counted must have (and 2 more)"])
        found = self.check(_count("0 of 3", 0, 3, otherwise="missed with SAM on: no", **self.MISSED))
        self.assertEqual(len(found), 1)
        self.assertIn("cannot tell: the notice 'Held-out bench sinking/v1' has neither the field", found[0])

    def test_a_misspelt_field_is_cannot_tell_whatever_the_number(self):
        for n in range(4):
            found = self.check(_count(f"{n} of 3", n, 3, count="caught with SAM on:yes"))
            self.assertEqual(len(found), 1, n)
            self.assertIn("cannot tell", found[0])

    def test_a_notice_with_both_fields_is_cannot_tell_not_a_yes(self):
        notices = dict(THREE, c=[_notice("fall/v1", "caught with SAM on: yes; caught with SAM on: no")])
        for n in (2, 3):
            found = self.check(_count(f"{n} of 3", n, 3), notices=notices)
            self.assertEqual(found, [f"mode: run 1: '{n} of 3': cannot tell: the notice 'Held-out bench fall/v1' has "
                                     "both the field 'caught with SAM on: yes' and the field 'caught with SAM on: no'"])

    def test_a_field_twice_in_one_notice_is_cannot_tell(self):
        notices = dict(THREE, c=[_notice("fall/v1", "caught with SAM on: yes; caught with SAM on: yes")])
        found = self.check(_count("3 of 3", 3, 3), notices=notices)
        self.assertEqual(found, ["mode: run 1: '3 of 3': cannot tell: the notice 'Held-out bench fall/v1' has the "
                                 "field 'caught with SAM on: yes' 2 times"])

    def test_a_notice_that_printed_nothing_for_the_field_is_not_a_no(self):
        notices = dict(THREE, c=[_notice("fall/v1", "over 5 routes: engine 5 pass")])
        found = self.check(_count(), notices=notices)
        self.assertEqual(len(found), 1)
        self.assertIn("cannot tell: the notice 'Held-out bench fall/v1' has neither", found[0])

    def test_without_otherwise_every_notice_must_have_the_field(self):
        self.assertEqual(self.check(_count("3 of 3", 3, 3, count="caught with SAM off: no", otherwise=None),
                                    notices={key: [_notice(key, "caught with SAM off: no")] for key in "abc"}), [])
        found = self.check(_count("2 of 3", 2, 3, otherwise=None))
        self.assertEqual(len(found), 1)
        self.assertIn("cannot tell: the notice 'Held-out bench fall/v1' has no field", found[0])

    def test_otherwise_that_is_the_counted_field_does_not_turn_a_missing_field_into_a_no(self):
        found = self.check(_count("2 of 3", 2, 3, otherwise="caught with SAM on: yes"))
        self.assertEqual(len(found), 1)
        self.assertIn("cannot tell: 'otherwise' is the same field as 'count'", found[0])

    FRAGMENTS = ("caught: yes", "caught: no", "caught: yse", "caught:yes", "Caught: yes", "not caught: yes",
                 "caught: yes!", "routes 5", "", " caught: yes ", "caught: no ", "missed: no")

    def test_generated_notices_a_count_that_passes_is_one_every_notice_states(self):
        """Whenever recheck passes an entry, every chosen notice states exactly one of its two fields and
        n is the number stating the first. The oracle below splits the message itself."""
        rng = random.Random(315)
        passed = refused = 0
        for _ in range(4000):
            messages = [";".join(rng.choice(self.FRAGMENTS) for _ in range(rng.randint(0, 3)))
                        for _ in range(rng.randint(1, 4))]
            notices = {f"j{i}": [_notice(f"v{i}", message)] for i, message in enumerate(messages)}
            otherwise = rng.choice(("caught: no", "caught: no", None, "missed: no", "caught: yes"))
            n, of = rng.randint(0, 4), rng.randint(1, 4)
            entry = _count(f"{n} of {of}", n, of, count="caught: yes", otherwise=otherwise)
            found = self.check(entry, notices=notices)
            if found:
                refused += 1
                continue
            passed += 1
            stated = [[part.strip() for part in message.split(";")] for message in messages]
            for got in stated:
                yes = got.count("caught: yes")
                no = got.count(otherwise) if otherwise not in (None, "caught: yes") else 0
                self.assertEqual(yes + no, 1, (entry, messages))
            self.assertEqual((n, of), (sum(got.count("caught: yes") for got in stated), len(messages)), (entry, messages))
        self.assertGreater(passed, 20)
        self.assertGreater(refused, 1000)


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


def _blind(name: str, kind: str = "defect", flagged=False, **more) -> dict:
    return {"title": f"Blind {name}", "message": json.dumps({"id": name, "kind": kind, "flagged": flagged, **more})}


class JsonNoticesTest(_Counted):
    """A count read from notices whose message is one JSON object (``has``, ``where``)."""

    SET = {
        "a": [_blind("a", flagged=True), {"title": "Blind time a", "message": "12 s"}],
        "b": [_blind("b"), {"title": "Blind time b", "message": "9 s"}],
        "c": [_blind("c", flagged=True, results={"fail": 4})],
        "d": [_blind("d", "intentional")],
        "clean": [_blind("clean", "clean")],
    }

    def entry(self, says: str = "2 of 3", n: int = 2, of: int = 3, **more) -> dict:
        out = {"says": says, "n": n, "of": of, "titled": "Blind *", "not": ["Blind time *"],
               "where": {"kind": "defect"}, "has": {"flagged": True}, **more}
        return {key: value for key, value in out.items() if value is not None}

    def one(self, *counts: dict, notices: dict | None = None) -> str:
        found = self.check(*counts, notices=self.SET if notices is None else notices)
        self.assertEqual(len(found), 1, found)
        return found[0]

    def swapped(self, key: str, *notices: dict) -> dict:
        return dict(self.SET, **{key: list(notices)})

    def test_a_count_the_json_notices_give_has_no_problem(self):
        healthy = self.entry("no healthy build flagged", 2, 2, where={"kind": ["clean", "intentional"]},
                             has={"flagged": False})
        self.assertEqual(self.check(self.entry(), healthy, self.entry("1 of 5", 1, 5, where=None, has={"id": "a"}),
                                    notices=self.SET), [])

    def test_a_count_the_notices_do_not_give_is_a_problem_that_says_both(self):
        self.assertEqual(self.one(self.entry("3 of 3", 3, 3)),
                         "mode: run 1: '3 of 3': 3 of 3 is recorded and the run's notices give 2 of 3 (titled "
                         "'Blind *', where \"kind\": \"defect\", with \"flagged\": true)")
        self.assertIn("give 2 of 3", self.one(self.entry("2 of 4", 2, 4)))
        self.assertIn("give 2 of 5 (titled 'Blind *', with", self.one(self.entry("2 of 3", where=None)))

    def test_a_message_that_is_not_one_json_object_is_cannot_tell(self):
        for message, said in (
            ("flagged: true", "is not JSON"), ("", "is not JSON"), ("[1, 2]", "is JSON and not an object"),
            ("true", "is JSON and not an object"), ('"x"', "is JSON and not an object"),
            ('{"id":"b","kind":"defect","flagged":false,"flagged":true}', "cannot be counted: the member 'flagged' is there twice"),
            ('{"kind":"defect","flagged":true,"results":{"a":1,"a":2}}', "cannot be counted: the member 'a' is there twice"),
            ('{"kind":"defect","flagged":true,"seconds":NaN}', "cannot be counted: NaN is not a JSON number"),
            ('{"kind":"defect","flagged":true} trailing', "is not JSON"),
            ("[" * 100000, "is not JSON"),
        ):
            found = self.one(self.entry(), notices=self.swapped("b", {"title": "Blind b", "message": message}))
            self.assertIn("'2 of 3': cannot tell: the message of the notice 'Blind b' " + said, found, message)

    def test_a_notice_left_in_by_the_title_must_be_json_too(self):
        # Without `not`, the "Blind time" notices have the title, and "12 s" is not an object: not a quiet 2 of 3.
        self.assertIn("cannot tell: the message of the notice 'Blind time a' is not JSON",
                      self.one(self.entry(**{"not": None})))

    def test_a_notice_without_the_member_is_not_a_no(self):
        bare = {"title": "Blind b", "message": json.dumps({"id": "b", "kind": "defect"})}
        self.assertIn("cannot tell: the notice 'Blind b' has no member 'flagged'",
                      self.one(self.entry(), notices=self.swapped("b", bare)))
        # A notice that does not say which set it is in is not left out of `of` quietly either.
        unsorted = {"title": "Blind d", "message": json.dumps({"id": "d", "flagged": False})}
        self.assertIn("cannot tell: the notice 'Blind d' has no member 'kind'",
                      self.one(self.entry(), notices=self.swapped("d", unsorted)))

    def test_a_member_of_another_kind_is_cannot_tell_never_equal_and_never_a_no(self):
        for flagged in ("true", 1, 0, None, [True], {"value": True}, 1.0):
            found = self.one(self.entry(), notices=self.swapped("b", _blind("b", flagged=flagged)))
            self.assertIn("has the member 'flagged' as", found, flagged)
            self.assertIn("which is not true or false", found, flagged)
        found = self.one(self.entry(), notices=self.swapped("d", _blind("d", kind=3)))
        self.assertIn("has the member 'kind' as 3, which is not text", found)
        # The other way round: the entry asks for a whole number and the notice has true.
        counted = self.entry("2 of 3", has={"reproduced": 1})
        found = self.one(counted, notices=self.swapped("b", _blind("b", reproduced=True)))
        self.assertIn("cannot tell", found)

    def test_no_notice_kept_by_where_is_cannot_tell(self):
        self.assertEqual(self.one(self.entry("0 of 1", 0, 1, where={"kind": "regression"})),
                         "mode: run 1: '0 of 1': cannot tell: the run published no notice titled 'Blind *', where "
                         "\"kind\": \"regression\"")

    def test_every_member_named_must_hold(self):
        both = self.entry("1 of 3", 1, 3, has={"flagged": True, "id": "a"})
        self.assertEqual(self.check(both, notices=self.SET), [])
        narrowed = self.entry("1 of 1", 1, 1, where={"kind": "defect", "id": "c"})
        self.assertEqual(self.check(narrowed, notices=self.SET), [])

    def test_the_same_notice_twice_and_a_failed_job_are_still_problems(self):
        twice = self.swapped("b", _blind("b"), _blind("b", flagged=True))
        self.assertIn("cannot tell: the run published the notice 'Blind b' 2 times", self.one(self.entry(), notices=twice))
        found = self.check(self.entry(), notices=self.SET, endings={"c": "failure"})
        self.assertEqual(len(found), 1)
        self.assertIn("from job 'bench (c)', which ended in failure", found[0])

    def test_generated_notices_a_count_passes_only_when_it_is_the_count(self):
        rng = random.Random(244)
        for _ in range(300):
            notices, defects, flagged = {}, 0, 0
            for index in range(rng.randint(1, 9)):
                kind = rng.choice(("defect", "defect", "intentional", "clean"))
                flag = rng.random() < 0.5
                defects += kind == "defect"
                flagged += kind == "defect" and flag
                notices[f"j{index}"] = [_blind(f"v{index}", kind, flag)]
            if not defects:
                continue
            self.assertEqual(self.check(self.entry(f"{flagged} of {defects}", flagged, defects), notices=notices), [])
            for n, of in ((flagged + 1, defects), (flagged, defects + 1), (flagged - 1, defects), (flagged, defects - 1)):
                if n < 0 or of < 1:
                    continue
                self.assertEqual(len(self.check(self.entry(f"{n} of {of}", n, of), notices=notices)), 1, (n, of))


class NoticesThatAreNotTextTest(_Counted):
    """The merge guard's case on #315: whatever a notices reader returns, an unread notice is "cannot tell"."""

    def test_a_title_or_a_message_that_is_not_text_is_cannot_tell_for_every_way_of_counting(self):
        entries = (_count(), {"says": "2 of 3", "n": 2, "of": 3, "titled": "Held-out bench *", "reads": "{n} of {of}"},
                   {"says": "2 of 3", "n": 2, "of": 3, "titled": "Held-out bench *", "has": {"flagged": True}})
        for bad in ({"title": None, "message": "x"}, {"title": "Held-out bench a", "message": None},
                    {"title": 7, "message": "x"}, {"title": "Held-out bench a", "message": {"flagged": True}},
                    {"title": "Held-out bench a", "message": b"x"}, {"title": "Held-out bench a"}, {"message": "x"},
                    "Held-out bench a", None, ["Held-out bench a", "x"]):
            for entry in entries:
                found = self.check(entry, notices=dict(THREE, a=[bad]))
                self.assertEqual(len(found), 1, (bad, entry))
                self.assertIn("cannot tell: job 'bench (a)': a notice's title or message is not text", found[0])

    def test_notices_that_are_not_a_list_are_cannot_tell(self):
        for bad in (None, "x", {"title": "Held-out bench a", "message": "x"}, 7):
            found = self.check(_count(), notices=dict(THREE, a=bad))
            self.assertEqual(len(found), 1, bad)
            self.assertIn("cannot tell: job 'bench (a)': the notices are not a list", found[0])


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
        self.assertGreaterEqual(len(self.entries(self.doc)), 20)
        self.assertGreaterEqual(sum(1 for _, count in self.entries(self.doc) if "has" in count), 4)
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
        self.assertGreaterEqual(tied, 13)
        self.assertLessEqual(tied, quoted)
        self.assertIn(f"Of the {quoted} counts quoted beside a run link, "
                      f"{'every one' if tied == quoted else tied} are tied to notices", cap.render(self.doc))


class OfflineTest(unittest.TestCase):
    def problems(self, shows: str, *counts: dict) -> list[str]:
        return cap.count_problems("mode", _cite(*counts, shows=shows))

    def test_a_count_whose_words_and_numbers_agree_has_no_problem(self):
        self.assertEqual(self.problems("2 of 3 held-out bugs caught, no false alarm", _count(),
                                       _count("no false alarm", 1, 1, titled="Held-out bench clean")), [])

    def test_words_found_only_inside_a_larger_number_are_a_problem(self):
        # The merge guard's second reason on #315: "8 of 8" was found in "8 of 80".
        inside = ("the count {!r} is tied to notices and the evidence says it only inside a larger number or word, "
                  "or across another count")
        for shows, says, n, of in (("8 of 80 held-out bugs caught", "8 of 8", 8, 8),
                                   ("12 of 30 caught", "2 of 3", 2, 3),
                                   ("2 of 3.5 caught", "2 of 3", 2, 3),
                                   ("2 of 3,000 caught", "2 of 3", 2, 3),
                                   ("version 2 of 3x", "2 of 3", 2, 3),
                                   ("$2 of 3 spent", "2 of 3", 2, 3),
                                   ("1.2 of 3 caught", "2 of 3", 2, 3)):
            self.assertEqual(self.problems(shows, _count(says, n, of)),
                             ["mode: run 1: " + inside.format(says)], shows)
            row = {"id": "mode", "evidence": [_cite(_count(says, n, of), shows=shows)]}
            self.assertEqual(cap.quoted_counts({"rows": [row]})[1], 0, shows)

    def test_the_reviewers_ledger_cases_are_problems(self):
        doc = copy.deepcopy(cap.load())
        ev = next(r for r in doc["rows"] if r["id"] == "sam-observer")["evidence"][0]
        before = cap.quoted_counts(doc)[1]
        ev["shows"] = "8 of 80 held-out bugs caught with SAM on; 4 of 8 without a vision model"
        found = cap.row_problems(doc)
        self.assertEqual(len(found), 1)
        self.assertIn("sam-observer: run 41003749744: the count '8 of 8' is tied to notices and the evidence says it "
                      "only inside a larger number", found[0])
        self.assertEqual(cap.quoted_counts(doc)[1], before - 1)
        doc = copy.deepcopy(cap.load())
        ev = next(r for r in doc["rows"] if r["id"] == "sam-observer")["evidence"][0]
        ev["shows"] = "8 of 8 held-out bugs caught with SAM on; 0 of 8 missed"
        ev["counts"][1] = {"says": "0 of 8", "n": 0, "of": 8, "titled": "Held-out bench *",
                           "not": ["Held-out bench clean"], "count": "missed with SAM on: yes"}
        self.assertEqual(cap.row_problems(doc), [
            "sam-observer: run 41003749744: the count '0 of 8': 0 of 8 leaves notices that are not counted, and no "
            "'otherwise' names the field they must have instead"])
        helper = LedgerRunsTest()
        helper.doc = doc
        found = runs.recheck(doc, helper.answers().__getitem__, saved_notices)[0]
        self.assertEqual(len(found), 1)
        self.assertIn("'0 of 8': cannot tell: the notice", found[0])
        self.assertIn("has no field 'missed with SAM on: yes'", found[0])

    def test_words_without_a_count_do_not_start_or_end_inside_a_word_or_touch_a_count(self):
        shows = "2 of 3 caught, no false alarm in 1.5 s"
        for says in ("c", "aught", "no false al", "of", "of 3 caught", "3 caught", "5 s", "in 1"):
            found = self.problems(shows, _count(says, 3, 3, otherwise=None))
            self.assertEqual(len(found), 1, says)
            self.assertIn("only inside a larger number or word", found[0])
        for says in ("caught", "no false alarm", "in 1.5 s"):
            self.assertEqual(self.problems(shows, _count(says, 1, 1, otherwise=None)), [], says)

    def test_two_wordings_cannot_tie_the_same_count(self):
        self.assertEqual(self.problems("2 of 3 caught", _count(), _count("2 of 3 caught")),
                         ["mode: run 1: the count '2 of 3 caught' is tied to words of the evidence that another count "
                          "is tied to already"])
        # The same words twice in the evidence are two counts, and two entries may tie them.
        self.assertEqual(self.problems("2 of 3 on, 2 of 3 off", _count(), _count()), [])
        row = {"id": "mode", "evidence": [_cite(_count(), _count(), shows="2 of 3 on, 2 of 3 off")]}
        self.assertEqual(cap.quoted_counts({"rows": [row]}), (2, 2))

    def test_fewer_than_all_needs_the_field_the_others_must_have(self):
        self.assertEqual(self.problems("2 of 3 caught", _count(otherwise=None)),
                         ["mode: run 1: the count '2 of 3': 2 of 3 leaves notices that are not counted, and no "
                          "'otherwise' names the field they must have instead"])
        self.assertEqual(self.problems("3 of 3 caught", _count("3 of 3", 3, 3, otherwise=None)), [])
        self.assertEqual(self.problems("2 of 3 caught", _count(otherwise="caught with SAM on: yes")),
                         ["mode: run 1: the count '2 of 3': 'otherwise' is the same field as 'count'"])
        entry = {"says": "2 of 3", "n": 2, "of": 3, "titled": "Summary", "reads": "{n} of {of}", "otherwise": "x"}
        self.assertEqual(self.problems("2 of 3 caught", entry),
                         ["mode: run 1: the count '2 of 3': 'otherwise' goes with 'count', not with 'reads'"])

    def test_a_field_with_a_line_break_or_a_space_at_an_end_is_a_problem(self):
        for key, value in (("count", "caught:\nyes"), ("count", " caught: yes"), ("otherwise", "caught: no ")):
            found = self.problems("2 of 3 caught", _count(**{"otherwise": "caught: no", key: value}))
            self.assertEqual(len(found), 1, value)
            self.assertIn(f"{key!r} is one field of a notice and has a line break in it or a space at an end", found[0])

    NUMBERS = ("8", "80", "2", "3", "12", "30", "3.5", "1,000", "0", "08")
    GLUE = (" ", " ", " ", "", ".", ",", ", ", "; ", "$", "x", " x", "-", "(", ") ", "\n")
    WORDS = ("caught", "bugs", "of", "of", "no", "version", "s")

    def test_generated_words_a_count_that_passes_is_one_the_page_would_count_at_that_place(self):
        """Whenever count_problems passes an entry whose words hold a count, _QUOTED finds that count in
        the evidence at that place, and quoted_counts calls a count tied exactly when the check passes."""
        rng = random.Random(3150)
        passed = refused = 0
        for _ in range(6000):
            parts = []
            for _ in range(rng.randint(1, 4)):
                parts += [rng.choice(self.NUMBERS), " of ", rng.choice(self.NUMBERS), rng.choice(self.GLUE),
                          rng.choice(self.WORDS), rng.choice(self.GLUE)]
            shows = "".join(parts)
            pick = rng.random()
            if pick < 0.4:
                at = 6 * rng.randrange(len(parts) // 6)
                says = "".join(parts[at:at + 3])
            elif pick < 0.7:
                start = rng.randrange(len(shows))
                says = shows[start:start + rng.randint(1, 12)]
            else:
                says = f"{rng.choice(self.NUMBERS)} of {rng.choice(self.NUMBERS)}"
            inner = list(cap._QUOTED.finditer(says))
            if len(inner) != 1:
                continue
            n, of = int(inner[0].group(1)), int(inner[0].group(2))
            if n > of or of < 1:
                continue
            entry = _count(says, n, of, otherwise="caught with SAM on: no")
            found = cap.count_problems("mode", _cite(entry, shows=shows))
            row = {"id": "mode", "evidence": [_cite(entry, shows=shows)]}
            tied = cap.quoted_counts({"rows": [row]})[1]
            self.assertEqual(tied, 0 if found else 1, (shows, says, found))
            if found:
                refused += 1
                continue
            passed += 1
            spans = {m.span(): m for m in cap._QUOTED.finditer(shows)}
            at = [p for p in range(len(shows)) if shows.startswith(says, p)
                  and (p + inner[0].start(), p + inner[0].end()) in spans]
            self.assertTrue(at, (shows, says))
            match = spans[(at[0] + inner[0].start(), at[0] + inner[0].end())]
            self.assertEqual((int(match.group(1)), int(match.group(2))), (n, of))
            # Read without the pattern: the count is not part of a longer number or word on either side.
            before, after = shows[:match.start()], shows[match.end():]
            self.assertFalse(before[-1:].isalnum() or before[-1:] in (".", ",", "$", "_"), (shows, says))
            self.assertFalse(after[:1].isalnum() or after[:1] == "_", (shows, says))
            self.assertFalse(after[:1] in (".", ",") and after[1:2].isdigit(), (shows, says))
        self.assertGreater(passed, 300)
        self.assertGreater(refused, 300)

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
        self.assertEqual(len(self.problems("2 of 3 caught", _count(count="a: yes; b: no", otherwise="a: no"))), 1)
        entry = {"says": "2 of 3", "n": 2, "of": 3, "titled": "Summary", "reads": "{n} of {of}; undecided 0"}
        self.assertEqual(len(self.problems("2 of 3 caught", entry)), 1)

    def test_reads_needs_each_number_once(self):
        entry = {"says": "2 of 3", "n": 2, "of": 3, "titled": "Summary", "reads": "{n} of {of} of {of}"}
        self.assertEqual(self.problems("2 of 3 caught", entry),
                         ["mode: run 1: the count '2 of 3': 'reads' must have {n} and {of} once each"])

    def test_words_that_hold_no_count_cannot_carry_numbers_nobody_reads(self):
        # The merge guard's case on #315: "8 of 8 caught", and an entry on the word "caught" recorded as 5 of 9.
        entry = {"says": "caught", "n": 5, "of": 9, "titled": "Held-out bench *", "count": "caught: yes",
                 "otherwise": "caught: no"}
        found = self.problems("8 of 8 caught", entry)
        self.assertEqual(len(found), 1)
        self.assertIn("words that hold no count say something of every notice counted, and 5 of 9 is recorded",
                      found[0])
        self.assertEqual(self.problems("8 of 8 caught", dict(entry, n=9)), [])
        for way in ({"reads": "{n} of {of} caught"}, {"has": {"caught": True}}):
            base = {"says": "caught", "of": 9, "titled": "Summary", **way}
            self.assertEqual(len(self.problems("8 of 8 caught", dict(base, n=0))), 1, way)
            self.assertEqual(self.problems("8 of 8 caught", dict(base, n=9)), [], way)

    def test_reads_that_two_different_counts_would_fill_the_same_is_a_problem(self):
        # The merge guard's case on #315: "{n}{of}" is "111" for 1 of 11 and for 11 of 1.
        for reads in ("{n}{of}", "{of}{n}", "caught {n}{of}", "{n}0 of {of}", "{n} of 1{of}", "x1{n} of {of}",
                      "{n} of {of}0", "{n} of {of}{", "}{n} of {of}"):
            entry = {"says": "2 of 3", "n": 2, "of": 3, "titled": "Summary", "reads": reads}
            found = self.problems("2 of 3 caught", entry)
            self.assertEqual(len(found), 1, reads)
            self.assertIn("so more than one count would fill it the same", found[0])
        for reads in ("{n} of {of}", "({n}/{of})", "caught {n} of {of} bugs", "{of} seen, {n} caught", "{n}-{of}"):
            entry = {"says": "2 of 3", "n": 2, "of": 3, "titled": "Summary", "reads": reads}
            self.assertEqual(self.problems("2 of 3 caught", entry), [], reads)

    def test_members_a_json_count_names_must_be_plain_values_and_named_once(self):
        def found(**more) -> list[str]:
            entry = {"says": "2 of 3", "n": 2, "of": 3, "titled": "Blind *", "has": {"flagged": True}, **more}
            return self.problems("2 of 3 caught", entry)
        self.assertEqual(found(), [])
        self.assertEqual(found(where={"kind": "defect"}), [])
        self.assertEqual(found(where={"kind": ["clean", "intentional"], "tries": [1, 2]}), [])
        for more, said in (
            ({"has": {"flagged": 1.0}}, "'has' gives 'flagged' values that are not all"),
            ({"has": {"flagged": None}}, "'has' gives 'flagged' values that are not all"),
            ({"has": {"flagged": {"a": 1}}}, "'has' gives 'flagged' values that are not all"),
            ({"has": {"flagged": [True, False]}}, "'has' gives 'flagged' a list"),
            ({"has": {"kind": ["a", "b"]}}, "'has' gives 'kind' a list"),
            ({"where": {"kind": ["a"]}}, "'where' gives 'kind' a list"),
            ({"where": {"kind": ["a", "a"]}}, "'where' gives 'kind' a list"),
            ({"where": {"kind": [True, False]}}, "'where' gives 'kind' a list"),
            ({"where": {"kind": ["a", 1]}}, "'where' gives 'kind' values that are not all"),
            ({"where": {"kind": [1, True]}}, "'where' gives 'kind' values that are not all"),
            ({"where": {"kind": []}}, "'where' gives 'kind' values that are not all"),
            ({"where": {"flagged": True}}, "'has' and 'where' both name the member 'flagged'"),
        ):
            got = found(**more)
            self.assertEqual(len(got), 1, more)
            self.assertIn(said, got[0])
        orphan = {"says": "2 of 3", "n": 2, "of": 3, "titled": "Blind *", "reads": "{n} of {of}", "where": {"a": "b"}}
        self.assertEqual(self.problems("2 of 3 caught", orphan), ["mode: run 1: the count '2 of 3': 'where' goes with 'has'"])

    def test_the_page_says_what_a_json_count_was_counted_by(self):
        row = {"kind": "run", "ref": RUN + "1", "shows": "no healthy build flagged", "counts": [
            {"says": "no healthy build flagged", "n": 3, "of": 3, "titled": "Blind *",
             "where": {"kind": ["clean", "intentional"]}, "has": {"flagged": False}}]}
        self.assertTrue(cap._evidence(row).endswith(
            'Counted from the run\'s notices: no healthy build flagged (3 of 3 with "flagged": false, of those '
            'with "kind": "clean" or "intentional")'))

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
        entry = {"says": "8 of 8", "n": 8, "of": 8, "titled": "Held-out bench *"}
        self.assertEqual(self.errors(lambda run, test: None), [])
        self.assertEqual(self.errors(lambda run, test: run.update(counts=[dict(
            entry, n=4, count="caught with SAM off: yes", otherwise="caught with SAM off: no")])), [])
        self.assertEqual(self.errors(lambda run, test: run.update(counts=[dict(entry, count="x")])), [])
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
            lambda run, test: run.update(counts=[dict(entry, count="a\nb")]),
            lambda run, test: run.update(counts=[dict(entry, count="a; b")]),
            lambda run, test: run.update(counts=[dict(entry, count=" a")]),
            lambda run, test: run.update(counts=[dict(entry, count="a", otherwise="b ")]),
            lambda run, test: run.update(counts=[dict(entry, count="a", otherwise="b;c")]),
            lambda run, test: run.update(counts=[dict(entry, reads="{n} of {of}", otherwise="b")]),
            lambda run, test: run.update(counts=[dict(entry, reads="{n} of {of}; x")]),
            lambda run, test: run.update(counts=[dict(entry, reads="{n} of\n{of}")]),
            lambda run, test: run.update(counts=[dict(entry, reads="{n}{of}")]),
            lambda run, test: run.update(counts=[dict(entry, reads="{of}{n}")]),
            lambda run, test: run.update(counts=[dict(entry, reads="{n}0 of {of}")]),
            lambda run, test: run.update(counts=[dict(entry, reads="{n} of {of}0")]),
            lambda run, test: run.update(counts=[dict(entry, reads="1{n} of {of}")]),
            lambda run, test: run.update(counts=[dict(entry, has={})]),
            lambda run, test: run.update(counts=[dict(entry, has={"flagged": True}, count="x")]),
            lambda run, test: run.update(counts=[dict(entry, has={"flagged": True}, reads="{n} of {of}")]),
            lambda run, test: run.update(counts=[dict(entry, has={"flagged": True}, otherwise="x")]),
            lambda run, test: run.update(counts=[dict(entry, has={"flagged": [True, False]})]),
            lambda run, test: run.update(counts=[dict(entry, has={"flagged": None})]),
            lambda run, test: run.update(counts=[dict(entry, has={"flagged": 0.5})]),
            lambda run, test: run.update(counts=[dict(entry, has={"flagged": {"is": True}})]),
            lambda run, test: run.update(counts=[dict(entry, count="x", where={"kind": "defect"})]),
            lambda run, test: run.update(counts=[dict(entry, has={"flagged": True}, where={})]),
            lambda run, test: run.update(counts=[dict(entry, has={"flagged": True}, where={"kind": ["defect"]})]),
            lambda run, test: run.update(counts=[dict(entry, has={"flagged": True}, where={"kind": ["a", "a"]})]),
            lambda run, test: run.update(counts=[dict(entry, has={"flagged": True}, where={"kind": [True, False]})]),
            lambda run, test: run.update(counts=[dict(entry, has={"flagged": True}, where={"kind": ["a", 1]})]),
        ):
            self.assertTrue(self.errors(change))
        for fine in (dict(entry, reads="{n} of {of}"), dict(entry, reads="caught ({n}/{of})"),
                     dict(entry, has={"flagged": True}), dict(entry, has={"flagged": True, "tries": 1, "id": "a"}),
                     dict(entry, has={"flagged": True}, where={"kind": "defect"}),
                     dict(entry, has={"flagged": True}, where={"kind": ["clean", "intentional"], "tries": [1, 2]})):
            self.assertEqual(self.errors(lambda run, test: run.update(counts=[fine])), [], fine)


if __name__ == "__main__":
    unittest.main()
