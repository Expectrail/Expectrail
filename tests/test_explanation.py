"""A written explanation in the evidence viewer (#264, expectrail/explanation.py): it is shown only
when it cites this run's evidence and cannot contradict the verifier's decision, and it is withheld,
with the reason on the page, whenever that cannot be told. No model is called: the answers are
stand-ins checked in under tests/fixtures/explanation/."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail import contracts, viewer
from expectrail import explanation as xpl
from expectrail.gate import record as rec
from expectrail.orchestrator import engines, runner
from expectrail.orchestrator import store as st
from tests.test_ci_gate import FakeReplay, make_repo
from tests.test_viewer import JobViewerTest, banner_state, embedded
from tests.test_viewer import Base as ViewerBase

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "contracts" / "examples"
ANSWER = REPO / "tests" / "fixtures" / "explanation" / "reject-answer.json"
FINDING = "35745b6a03ca"


def record() -> dict:
    return rec.read_record(EXAMPLES / "findings.json")


def example() -> dict:
    return json.loads((EXAMPLES / "explanation.v1.json").read_text(encoding="utf-8"))


def one_point(text: str, says=None, cites=(FINDING,)) -> dict:
    doc = example()
    doc["points"] = [{"text": text, "cites": list(cites),
                      "says": {FINDING: {"after": "fail"}} if says is None else says}]
    return doc


class ContractTest(unittest.TestCase):
    def test_the_example_is_valid_and_registered(self):
        self.assertIn(xpl.FORMAT, contracts.V1_FORMATS)
        self.assertEqual(contracts.validate_v1(example()), "explanation")

    def test_the_writer_makes_the_example_from_the_stand_in_answer(self):
        doc = xpl.from_answer(ANSWER.read_text(encoding="utf-8"), record(), model="stand-in", recorded=True)
        self.assertEqual(doc, example())
        # The decision and the record it explains are Expectrail's, not the answer's.
        self.assertEqual(doc["decision"], "reject")
        self.assertEqual(doc["recordSha256"], contracts.digest_v1(record()))

    def test_an_answer_cannot_bring_its_own_decision(self):
        answer = json.loads(ANSWER.read_text(encoding="utf-8"))
        answer["decision"] = "accept"
        with self.assertRaises(xpl.ExplanationError):
            xpl.from_answer(json.dumps(answer), record(), model="m", recorded=False)
        for bad in ("not json", '{"points": []}', '{"points": [{"text": "x", "cites": ["nope"], "says": {}}]}',
                    '{"points": 1, "points": 2}'):
            with self.subTest(answer=bad), self.assertRaises(xpl.ExplanationError):
                xpl.from_answer(bad, record(), model="m", recorded=False)

    def test_the_prompt_states_the_decision_and_every_id(self):
        text = xpl.prompt(record())
        self.assertIn("The verifier's decision is: reject.", text)
        for cid in xpl.evidence(record()):
            self.assertIn(f"- {cid}:", text)


class CheckTest(unittest.TestCase):
    def withheld(self, doc, decision="reject", rec_=None) -> list[str]:
        return xpl.check(doc, record() if rec_ is None else rec_, decision)

    def test_the_example_is_shown(self):
        self.assertEqual(self.withheld(example()), [])

    def test_a_different_decision_or_record_is_withheld(self):
        self.assertTrue(self.withheld(example(), "accept"))
        self.assertTrue(self.withheld(example(), "needs-review"))
        self.assertTrue(self.withheld(example(), None))
        self.assertTrue(xpl.check(example(), None, "reject"))
        doc = example()
        doc["decision"] = "accept"
        self.assertTrue(self.withheld(doc, "accept"))     # the record still says reject
        other = record()
        other["findings"][0]["reason"] = other["findings"][0]["reason"].replace("22.25", "22.5")
        self.assertEqual(self.withheld(example(), rec_=other), ["it was written for other evidence than this run's"])

    def test_an_id_that_is_not_in_the_evidence_is_withheld(self):
        doc = one_point("It fails.", cites=["aaaaaaaaaaaa"], says={})
        self.assertIn("not in this run's evidence", self.withheld(doc)[0])
        doc = one_point("It fails.", cites=["check:player-stays-above-ground@nowhere"], says={})
        self.assertTrue(self.withheld(doc))

    def test_a_stated_verdict_must_be_the_records(self):
        self.assertTrue(self.withheld(one_point("It passes after.", says={FINDING: {"after": "pass"}})))
        self.assertTrue(self.withheld(one_point("It fails before.", says={FINDING: {"before": "fail"}})))
        # A verdict for an id the point does not cite.
        self.assertTrue(self.withheld(one_point("It fails.", says={"d53dfb482f64": {"after": "fail"}})))

    def test_a_number_not_in_the_cited_evidence_is_withheld(self):
        self.assertEqual(self.withheld(one_point("It fails from frame 5 by 22.25px.")), [])
        self.assertEqual(self.withheld(one_point("It fails from frame 05 by 22.250px.")), [])
        for text in ("It fails from frame 6.", "It fails by 23px.", "It fails on 3 routes.", "It fails 100% of the time."):
            with self.subTest(text=text):
                self.assertIn("is not in the evidence", " ".join(self.withheld(one_point(text))))
        # Numbers in words cannot be compared, so they are withheld too.
        for text in ("It fails on two routes.", "It fails by half a tile.", "It fails twice."):
            with self.subTest(text=text):
                self.assertIn("number in words", " ".join(self.withheld(one_point(text))))

    def test_a_verdict_word_needs_a_stated_verdict(self):
        self.assertTrue(self.withheld(one_point("It is broken.", says={})))
        self.assertTrue(self.withheld(one_point("The change fixed the fall.", says={FINDING: {"after": "fail"}})))
        self.assertEqual(self.withheld(one_point("It passed before and fails after.",
                                                 says={FINDING: {"before": "pass", "after": "fail"}})), [])

    def test_a_decision_word_must_match_the_decision(self):
        for text in ("This change is safe to merge.", "Accepted.", "It can be approved."):
            with self.subTest(text=text):
                self.assertTrue(self.withheld(one_point(text)))
        self.assertEqual(self.withheld(one_point("Rejected: it fails from frame 5.")), [])

    def test_a_negated_verdict_is_withheld(self):
        for text in ("It no longer fails.", "It does not fail.", "It doesn't fail.", "It never fails.",
                     "Nothing is broken.", "It fails, not passes."):
            with self.subTest(text=text):
                self.assertIn("negates", " ".join(self.withheld(one_point(text))))

    def test_words_of_certainty_are_withheld(self):
        for text in ("This proves the bug.", "It always fails.", "All routes fail.", "Every check fails.",
                     "The game is entirely broken."):
            with self.subTest(text=text):
                self.assertIn("claims more", " ".join(self.withheld(one_point(text))))

    def test_text_that_is_not_plain_ascii_is_withheld(self):
        # A Cyrillic a in "pаsses" would get past a word list; it never gets past this.
        for text in ("It pаsses.", "It fails​.", "It fails\nfrom frame 5."):
            with self.subTest(text=repr(text)):
                self.assertIn("printable ASCII", self.withheld(one_point(text))[0])

    def test_an_invalid_or_unreadable_document_is_withheld(self):
        doc = example()
        doc["points"][0]["extra"] = True
        self.assertIn("not a valid", self.withheld(doc)[0])
        self.assertIn("could not be read", self.withheld({"unreadable": "too big"})[0])
        self.assertTrue(self.withheld("a string"))

    def test_an_accept_can_be_explained(self):
        accept = record()
        accept.update(decision="accept", findings=[])
        for c in accept["checks"]:
            c.update(after="pass", comparison="UNCHANGED", findingId=None)
        doc = example()
        doc.update(decision="accept", recordSha256=contracts.digest_v1(accept))
        cid = "check:player-stays-above-ground@combat"
        doc["points"] = [{"text": "The player stays above the ground on the combat route after the change: "
                                  "this check passes, before and after.",
                          "cites": [cid], "says": {cid: {"before": "pass", "after": "pass"}}}]
        self.assertEqual(xpl.check(doc, accept, "accept"), [])
        doc["points"][0]["text"] += " The game works."   # "works" is still a passing word with a pass stated
        self.assertEqual(xpl.check(doc, accept, "accept"), [])
        doc["points"][0]["text"] += " Nothing else can break."
        self.assertTrue(xpl.check(doc, accept, "accept"))


class CommandTest(unittest.TestCase):
    def run_main(self, *argv) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = xpl.main(list(argv))
        return code, out.getvalue()

    def test_check_exits_0_shown_1_withheld_2_unreadable(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        findings = str(EXAMPLES / "findings.json")
        self.assertEqual(self.run_main("check", findings, str(EXAMPLES / "explanation.v1.json"))[0], 0)
        bad = tmp / "bad.json"
        bad.write_text(json.dumps(one_point("It always fails.")), encoding="utf-8")
        code, out = self.run_main("check", findings, str(bad))
        self.assertEqual((code, out.startswith("withheld: ")), (1, True))
        (tmp / "link.json").symlink_to(EXAMPLES / "explanation.v1.json")
        self.assertEqual(self.run_main("check", findings, str(tmp / "link.json"))[0], 2)
        big = tmp / "big.json"
        big.write_text(" " * (xpl.MAX_BYTES + 1), encoding="utf-8")
        self.assertEqual(self.run_main("check", findings, str(big))[0], 2)
        out_file = tmp / "made.json"
        code, out = self.run_main("from-answer", findings, str(ANSWER), "--model", "stand-in", "--recorded",
                                  "--out", str(out_file))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out_file.read_text(encoding="utf-8")), example())


class ViewerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def page(self, doc) -> tuple[str, dict]:
        folder = self.tmp / "viewer"
        viewer.write(folder, record(), explanation=doc)
        page = (folder / "index.html").read_text(encoding="utf-8")
        return page, embedded(page)

    def test_a_shown_explanation_links_its_findings_and_decides_nothing(self):
        page, payload = self.page(example())
        plain = viewer.write(self.tmp / "plain", record()).read_text(encoding="utf-8")
        self.assertEqual(banner_state(page), banner_state(plain))
        self.assertEqual(banner_state(page), "behaviour-failure")
        self.assertEqual(payload["decision"], "reject")
        self.assertTrue(payload["explanation"]["shown"])
        self.assertIn('<section id="explanation"><h2>Explanation</h2>', page)
        self.assertIn("It decides nothing", page)
        self.assertIn(f'data-finding="{FINDING}"><code>{FINDING}</code></button>', page)
        self.assertIn("replayed from a recording", page)
        # The offline copy carries the same explanation.
        single = embedded((self.tmp / "viewer" / viewer.EXPORT_NAME).read_text(encoding="utf-8"))
        self.assertEqual(single["explanation"], payload["explanation"])

    def test_a_withheld_explanation_shows_why_and_none_of_its_text(self):
        doc = one_point("This change is safe to merge.")
        page, payload = self.page(doc)
        self.assertFalse(payload["explanation"]["shown"])
        self.assertNotIn("points", payload["explanation"])
        self.assertIn("<strong>Withheld.</strong>", page)
        self.assertNotIn("This change is safe to merge.", page)
        self.assertEqual(banner_state(page), "behaviour-failure")

    def test_without_an_explanation_the_page_has_no_section(self):
        page, payload = self.page(None)
        self.assertIsNone(payload["explanation"])
        self.assertNotIn('id="explanation"', page)


class JobExplanationTest(ViewerBase):
    """`expectrail report` reads <job>/explanation.json when there is one."""

    def setUp(self):
        super().setUp()
        self.store = st.JobStore(self.tmp / "jobs", lease_seconds=0.6)

    job = JobViewerTest.job
    report = JobViewerTest.report

    def rejected(self) -> str:
        job = self.job(make_repo(self.tmp / "h", bug=True), make_repo(self.tmp / "b"))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            runner.work(self.store, job, engines={"godot": engines.GodotGate(rule="engine-only", replay=FakeReplay())})
        return job

    def test_report_shows_a_matching_explanation_and_withholds_others(self):
        job = self.rejected()
        root = self.store.paths(job).root
        findings = rec.read_record(self.store.paths(job).output / "findings.json")
        fid = findings["findings"][0]["id"]
        answer = {"points": [{"text": "After the change this check fails.", "cites": [fid],
                              "says": {fid: {"after": "fail"}}}]}
        doc = xpl.from_answer(json.dumps(answer), findings, model="stand-in", recorded=True)
        (root / xpl.FILE_NAME).write_text(json.dumps(doc), encoding="utf-8")
        code, _ = self.report(job)
        self.assertEqual(code, 1)
        payload = embedded((root / "viewer" / "index.html").read_text(encoding="utf-8"))
        self.assertTrue(payload["explanation"]["shown"], payload["explanation"])
        # The same text for the example's record is for other evidence: withheld.
        (root / xpl.FILE_NAME).write_text(json.dumps(example()), encoding="utf-8")
        self.assertEqual(self.report(job)[0], 1)
        payload = embedded((root / "viewer" / "index.html").read_text(encoding="utf-8"))
        self.assertFalse(payload["explanation"]["shown"])
        # Not JSON: withheld and said; the report's exit code is unchanged.
        (root / xpl.FILE_NAME).write_text("{", encoding="utf-8")
        self.assertEqual(self.report(job)[0], 1)
        payload = embedded((root / "viewer" / "index.html").read_text(encoding="utf-8"))
        self.assertIn("could not be read", payload["explanation"]["withheld"][0])
        self.assertEqual(payload["decision"], "reject")

if __name__ == "__main__":
    unittest.main()
