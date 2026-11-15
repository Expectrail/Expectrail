"""Run it played by a visitor in Chromium (tools/runit_smoke.py, #265).

The comparison rules run everywhere. The browser tests need Playwright's Chromium: they skip without it
locally and fail in CI's web-capture job, which sets EXPECTRAIL_WEB_TESTS=required."""
import contextlib
import copy
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.tool_requirements import require_tool
from tools import runit_smoke

REPO = Path(__file__).resolve().parent.parent

STATUS = {
    "format": "expectrail.run-it-result/v1", "requestId": "r-1", "sample": {"id": "clean", "expected": "accept"},
    "phase": "completed", "decision": "accept", "asExpected": True,
    "vision": {"recorded": True, "recordedAt": "2026-11-13", "answered": 120, "asked": 120, "notRecorded": 0},
    "receipt": {"why": "not signed yet (#255)"}, "diagnostics": [],
}
PAGE = {
    "resultShown": True, "when": "Your run", "verdict": "Accepted", "tone": "pass", "message": "Finished.",
    "facts": {"Vision": "Vision answers recorded on 2026-11-13 (sam-3.1, recording run 1): 120 of 120 questions "
                        "answered from the recording.",
              "This sample": "A working install decides accept. This run ended as this sample is expected to end today.",
              "Receipt": "not signed yet (#255)", "Request": "r-1"},
    "viewerShown": True, "evidenceHeadline": "Accepted", "evidenceNote": None,
}


def problems(status=None, page=None, earlier=False, evidence=True):
    return runit_smoke.compare(status or STATUS, page or PAGE, label="clean", earlier=earlier, evidence=evidence)


class Verdicts(unittest.TestCase):
    def test_only_an_accept_with_every_question_answered_from_the_recording_is_green(self):
        self.assertEqual(runit_smoke.expected_verdict(STATUS), ("Accepted", "pass"))
        for change in ({"notRecorded": 1}, {"answered": 119}, {"recorded": False}, {"answered": 0, "asked": 0}):
            status = copy.deepcopy(STATUS)
            status["vision"].update(change)
            self.assertEqual(runit_smoke.expected_verdict(status), ("Needs review", "review"), change)

    def test_a_run_without_a_decision_is_never_a_verdict(self):
        for change, title in (({"phase": "failed", "decision": None}, "The run failed: no verdict"),
                              ({"phase": "cancelled", "decision": None}, "Cancelled: no verdict"),
                              ({"decision": "maybe"}, "Cannot tell")):
            status = dict(STATUS, **change)
            self.assertEqual(runit_smoke.expected_verdict(status), (title, "review"))
        self.assertEqual(runit_smoke.expected_verdict(dict(STATUS, decision="reject")), ("Rejected", "fail"))


class Compare(unittest.TestCase):
    def test_a_page_that_agrees_has_no_problem(self):
        self.assertEqual(problems(), [])

    def test_a_page_that_says_more_than_the_verifier_is_caught(self):
        status = dict(STATUS, decision="needs-review")
        found = problems(status, dict(PAGE, evidenceHeadline="Needs review"))
        self.assertTrue(any("allows 'Needs review'" in p for p in found), found)

    def test_a_page_that_shows_no_result_is_caught(self):
        self.assertIn("shows no result", problems(page=dict(PAGE, resultShown=False))[0])

    def test_earlier_runs_must_be_labelled_earlier_and_the_visitors_own_must_not(self):
        self.assertTrue(problems(earlier=True))
        earlier = dict(PAGE, when="Earlier run, from 2026-11-15 00:43 UTC")
        self.assertEqual(problems(page=earlier, earlier=True), [])
        self.assertTrue(problems(page=earlier, earlier=False))

    def test_the_vision_line_must_name_the_recording_and_its_counts_and_never_invent_one(self):
        facts = dict(PAGE["facts"], Vision="Vision answers recorded on 2026-11-14 (x): 120 of 120 questions answered "
                                           "from the recording.")
        self.assertTrue(problems(page=dict(PAGE, facts=facts)))
        facts = dict(PAGE["facts"], Vision="Vision answers recorded on 2026-11-13 (x): 12 of 120 questions answered "
                                           "from the recording.")
        self.assertTrue(problems(page=dict(PAGE, facts=facts)))
        status = copy.deepcopy(STATUS)
        status["vision"] = {"recorded": False, "why": "none"}
        status["decision"] = "needs-review"
        page = dict(PAGE, verdict="Needs review", tone="review", evidenceHeadline="Needs review")
        self.assertTrue(any("claims a recording" in p for p in problems(status, page)))

    def test_receipt_request_and_expected_end_must_match(self):
        self.assertTrue(problems(page=dict(PAGE, facts=dict(PAGE["facts"], Receipt="signed"))))
        self.assertTrue(problems(page=dict(PAGE, facts=dict(PAGE["facts"], Request="r-2"))))
        self.assertTrue(problems(dict(STATUS, asExpected=False)))

    def test_the_evidence_must_be_shown_and_its_headline_must_agree(self):
        self.assertTrue(problems(page=dict(PAGE, viewerShown=False)))
        self.assertTrue(problems(page=dict(PAGE, evidenceHeadline=None)))
        self.assertTrue(problems(page=dict(PAGE, evidenceHeadline="Rejected: a check fails after this change")))
        reject = dict(STATUS, decision="reject")
        page = dict(PAGE, verdict="Rejected", tone="fail", evidenceHeadline="Accepted")
        self.assertTrue(any("headline" in p for p in problems(reject, page)))
        self.assertEqual(problems(page=dict(PAGE, viewerShown=False), evidence=False), [])


class InChromium(unittest.TestCase):
    """The whole visitor path against the stub, with stand-in replays and stand-in recordings."""

    @classmethod
    def setUpClass(cls):
        require_tool("Playwright Chromium")

    def smoke(self, **kw):
        lines = []
        with contextlib.redirect_stderr(io.StringIO()):
            doc = runit_smoke.smoke(stand_in=True, log=lines.append, **kw)
        return doc, lines

    def test_every_offered_sample_and_every_state_holds(self):
        doc, lines = self.smoke()
        self.assertEqual(doc["problems"], [], "\n".join(lines))
        manifest = json.loads((REPO / "docs/run-it/samples.json").read_text(encoding="utf-8"))
        offered = [s["id"] for s in manifest["samples"] if s["head"] != "recorded-fix" or s.get("repairRecorded")]
        self.assertEqual([r["sample"] for r in doc["runs"]], offered)
        decisions = {r["sample"]: r["decision"] for r in doc["runs"]}
        self.assertEqual({k: decisions[k] for k in ("clean", "fall-through-bug", "fall-through-repair")},
                         {"clean": "accept", "fall-through-bug": "reject", "fall-through-repair": "accept"})
        names = [c["check"] for c in doc["checks"]]
        for expected in ("a second visitor is told Busy while a run is going",
                         "the quota refusal says when it resets and shows the earlier run, labelled earlier",
                         "each card names its latest run and its verdict",
                         "switched off, nothing starts and the latest run still opens, labelled earlier",
                         "the page logged no script errors"):
            self.assertIn(expected, names)
        self.assertTrue(all(c["held"] for c in doc["checks"]))

    def test_a_page_that_turns_a_reject_green_fails_the_smoke(self):
        tmp = Path(tempfile.mkdtemp(prefix="runit-smoke-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        shutil.copytree(REPO / "docs" / "run-it", tmp / "run-it")
        script = tmp / "run-it" / "run-it.js"
        source = script.read_text(encoding="utf-8")
        honest = 'return { tone: "fail", title: "Rejected", means: "A check fails with this change." };'
        self.assertIn(honest, source)
        script.write_text(source.replace(honest, 'return { tone: "pass", title: "Accepted", means: "" };'),
                          encoding="utf-8")
        doc, _ = self.smoke(docs=tmp, only=["fall-through-bug"])
        self.assertTrue(any("fall-through-bug: the page shows 'Accepted' (pass), status.json allows 'Rejected'" in p
                            for p in doc["problems"]), doc["problems"])


if __name__ == "__main__":
    unittest.main()
