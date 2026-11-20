"""Fixture frames in a morning report are labelled as illustrative, never passed off as the run's own."""
from __future__ import annotations

import tempfile
import unittest
from unittest import mock
from pathlib import Path

from agents.loop import one_run
from agents.report import ILLUSTRATIVE_NOTE, build_report
from agents.verifier import verify
from harness.run import REPO
from tests.test_agents import AFTER_FRAME, BEFORE_FRAME, _request, _signing_key

FIX = REPO / "agents" / "fixtures" / "fix-collision-mask.patch"
OBS_FIXED = REPO / "agents" / "fixtures" / "obs-fixed.json"



# Historical trace fixtures: explicitly select the diagnostic benchmark control.
def setUpModule():
    global _trace_control
    _trace_control = mock.patch.dict("os.environ", {"EXPECTRAIL_OBS_PROVIDER": "trace"})
    _trace_control.start()


def tearDownModule():
    _trace_control.stop()


class IllustrativeFramesTest(unittest.TestCase):
    def _report(self, root: Path, **kwargs) -> tuple[dict, str]:
        verification = verify(_request(), FIX, root / "verify", observations_path=OBS_FIXED, skip_harness=True)
        summary = build_report(verification=verification, candidate=FIX, out=root / "morning",
                               before=[BEFORE_FRAME], after=[AFTER_FRAME], signing_key_path=_signing_key(root),
                               verification_path=root / "verify" / "verification.json", **kwargs)
        return summary, (root / "morning" / "morning-report.md").read_text(encoding="utf-8")

    def test_frames_passed_in_are_not_labelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary, report = self._report(Path(tmp))
        self.assertNotIn(ILLUSTRATIVE_NOTE, report)
        self.assertFalse(any("illustrative" in f for f in summary["frames"]))

    def test_illustrative_frames_are_flagged_and_explained(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary, report = self._report(Path(tmp), frames_illustrative=True)
        self.assertIn(ILLUSTRATIVE_NOTE, report)
        self.assertTrue(all(f["illustrative"] for f in summary["frames"]))
        self.assertLess(report.index(ILLUSTRATIVE_NOTE), report.index("![before]"))
        self.assertNotIn("—", ILLUSTRATIVE_NOTE)

    def test_the_loop_labels_its_fixture_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "loop"
            result = one_run(root, use_muse=False, offline_triage=True, observations=OBS_FIXED,
                             candidate_patch=FIX, skip_harness=True, run_trust=False)
            report = (root / "morning" / "morning-report.md").read_text(encoding="utf-8")
        self.assertEqual(result["decision"], "accept")
        self.assertIn(ILLUSTRATIVE_NOTE, report)
        self.assertTrue(all(f["illustrative"] for f in result["morning"]["frames"]))

    def test_the_loop_does_not_label_frames_it_was_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "loop"
            result = one_run(root, use_muse=False, offline_triage=True, observations=OBS_FIXED,
                             candidate_patch=FIX, skip_harness=True, run_trust=False,
                             before_frames=[BEFORE_FRAME], after_frames=[AFTER_FRAME])
            report = (root / "morning" / "morning-report.md").read_text(encoding="utf-8")
        self.assertNotIn(ILLUSTRATIVE_NOTE, report)
        self.assertFalse(any("illustrative" in f for f in result["morning"]["frames"]))


if __name__ == "__main__":
    unittest.main()
