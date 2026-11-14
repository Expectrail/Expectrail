"""The release gate's table and summary (#258), without starting anything.

What these tests hold:
- every row of the issue's table is in ``tests/release_gate/controls.py``, once, in its group;
- every row has tests or an ``open`` reason, and every test a row names exists; every test in the
  ``gate_*.py`` modules belongs to exactly one row or is a baseline;
- a probe (a row with tests and an ``open`` reason) is an expected failure, and a plain row's tests
  are not;
- the summary marks a row held only when its tests ran and passed with no open reason: a skipped test
  is "not run", a failure or an unexpected success is FAILED, and a failed positive control turns
  every held row into "not run";
- ``docs/release-gate.md`` was written by ``tools.release_gate`` and lists every row.

The real-process tests themselves run in CI's ``release-gate`` job (``python3 -m tools.release_gate
--require``), which has Godot.
"""
from __future__ import annotations

import importlib
import re
import unittest
from pathlib import Path

from tests.release_gate import controls
from tools import release_gate as rg

REPO = Path(__file__).resolve().parent.parent
SUMMARY = REPO / "docs" / "release-gate.md"

# The issue's table, row by row ("dropped, duplicated, out-of-order frames" is three rows here).
ISSUE = {
    "Identity and authority": ["wrong build or head", "unknown signer", "swapped policy", "expired receipt",
                               "changed head", "an approval added by the change"],
    "Candidate interference": ["writes to evidence or policy", "a forged trace", "a rewritten frame",
                               "a poisoned import cache", "reading a private path", "network egress"],
    "Observation": ["dropped frames", "duplicated frames", "out-of-order frames", "tick phase error",
                    "resolution change", "two same-class targets", "occlusion"],
    "Coverage": ["empty suite", "unreachable route", "zero evaluations", "skipped required observer",
                 "missing private suite"],
    "Intent": ["an approved intentional change passes as a contract change", "a weakened tolerance",
               "a misleading generated check stays advisory"],
    "Operations": ["timeout", "cancellation", "worker killed", "retry", "duplicate request", "disk quota",
                   "provider outage", "budget exhausted"],
}


def method(test_id: str):
    module, cls, name = test_id.rsplit(".", 2)
    return getattr(getattr(importlib.import_module(module), cls), name)


class TableTest(unittest.TestCase):
    def test_every_row_of_the_issue_is_there_once_in_its_group_and_order(self):
        self.assertEqual(list(ISSUE), list(controls.GROUPS))
        for group, names in ISSUE.items():
            self.assertEqual([c["control"] for c in controls.CONTROLS if c["group"] == group], names, group)
        ids = [c["id"] for c in controls.CONTROLS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_row_has_tests_or_a_reason_and_every_named_test_exists(self):
        for c in controls.CONTROLS:
            with self.subTest(c["id"]):
                self.assertTrue(c["tests"] or c["open"], "a row with no test needs an open reason")
                for t in c["tests"]:
                    self.assertTrue(callable(method(t)), t)
        for t in controls.BASELINES:
            self.assertTrue(callable(method(t)), t)

    def test_every_gate_test_belongs_to_one_row_or_is_a_baseline(self):
        named = controls.all_tests()
        self.assertEqual(len(named), len(set(named)), "a test is named by two rows")
        self.assertEqual(sorted(named), rg.gate_tests())

    def test_a_probe_is_an_expected_failure_and_a_plain_test_is_not(self):
        for c in controls.CONTROLS:
            for t in c["tests"]:
                expected = getattr(method(t), "__unittest_expecting_failure__", False)
                with self.subTest(t):
                    if expected:
                        self.assertTrue(c["open"], "an expected failure belongs to an open row")
                    elif c["open"]:
                        # An open row may hold plain tests beside its probe, but needs a probe.
                        self.assertTrue(any(getattr(method(x), "__unittest_expecting_failure__", False)
                                            for x in c["tests"]), f"{c['id']}: tests and an open reason, no probe")

    def test_the_gate_modules_are_not_collected_by_the_main_suite(self):
        self.assertTrue(rg.gate_modules())
        for name in rg.gate_modules():
            self.assertFalse(name.rsplit(".", 1)[1].startswith("test"), name)


def outcomes(default: str = rg.PASSED, **over) -> dict:
    found = {t: {"outcome": default, "seconds": 1.0, "detail": ""} for t in controls.all_tests()}
    for c in controls.CONTROLS:   # probes fail as expected unless told otherwise
        for t in c["tests"]:
            if getattr(method(t), "__unittest_expecting_failure__", False):
                found[t]["outcome"] = rg.EXPECTED
    for t, outcome in over.items():
        found[t]["outcome"] = outcome
    return found


def summary(found: dict) -> dict:
    return rg.summarise(found, commit="0" * 40, where="a test", when="now")


class SummaryTest(unittest.TestCase):
    def row(self, s: dict, cid: str) -> dict:
        return next(r for r in s["rows"] if r["id"] == cid)

    def test_a_row_is_held_only_when_its_tests_passed_and_it_has_no_open_reason(self):
        s = summary(outcomes())
        for r in s["rows"]:
            with self.subTest(r["id"]):
                self.assertEqual(r["status"] == rg.HELD, bool(r["tests"]) and not r["open"])
        self.assertFalse(rg.failed(s, require=True))

    def test_a_skipped_test_is_not_run_and_fails_a_required_run(self):
        t = controls.by_id()["timeout"]["tests"][0]
        s = summary(outcomes(**{t: rg.SKIPPED}))
        self.assertEqual(self.row(s, "timeout")["status"], rg.NOT_RUN)
        self.assertFalse(rg.failed(s, require=False))
        self.assertTrue(rg.failed(s, require=True))

    def test_a_failure_or_an_error_is_failed(self):
        t = controls.by_id()["cancellation"]["tests"][0]
        for outcome in (rg.FAILURE, rg.ERROR):
            with self.subTest(outcome):
                s = summary(outcomes(**{t: outcome}))
                self.assertEqual(self.row(s, "cancellation")["status"], rg.FAILED)
                self.assertTrue(rg.failed(s, require=False))

    def test_a_test_that_never_reported_is_not_held(self):
        found = outcomes()
        del found[controls.by_id()["retry"]["tests"][0]]
        self.assertEqual(self.row(summary(found), "retry")["status"], rg.FAILED)

    def test_an_open_row_stays_open_and_a_probe_that_passes_fails_the_run(self):
        probe = controls.by_id()["unreachable-route"]["tests"][1]
        s = summary(outcomes())
        self.assertEqual(self.row(s, "unreachable-route")["status"], rg.OPEN)
        self.assertIn("still fails", self.row(s, "unreachable-route")["note"])
        s = summary(outcomes(**{probe: rg.UNEXPECTED}))
        self.assertEqual(self.row(s, "unreachable-route")["status"], rg.FAILED)
        self.assertTrue(rg.failed(s, require=False))

    def test_without_the_positive_control_no_row_is_held(self):
        s = summary(outcomes(**{controls.BASELINES[0]: rg.FAILURE}))
        self.assertEqual(s["counts"][rg.HELD], 0)
        self.assertNotIn(rg.HELD, {r["status"] for r in s["rows"]})
        self.assertIn("NOT passed", rg.render(s))


class PublishedSummaryTest(unittest.TestCase):
    def test_it_was_written_by_the_tool_and_lists_every_row(self):
        text = SUMMARY.read_text(encoding="utf-8")
        self.assertIn("written by `python3 -m tools.release_gate`", text)
        for c in controls.CONTROLS:
            self.assertRegex(text, re.escape(f"| {c['control']} |"))
        held = [line for line in text.splitlines() if re.match(r"\| .+ \| held \|", line)]
        counted = int(re.search(r"Held (\d+)", text).group(1))
        self.assertEqual(len(held), counted)


if __name__ == "__main__":
    unittest.main()
