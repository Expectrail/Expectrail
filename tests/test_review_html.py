"""agents.review_html: the review as a page that cannot mislead, leak or break when it is moved."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents.review_html import render
from expectrail.contracts import ContractError
from harness.run import REPO

EXAMPLE = REPO / "contracts" / "examples" / "change-evidence.json"
PNG = (REPO / "agents" / "fixtures" / "frames" / "before-fall.png").read_bytes()


def _live_record(folder: Path, *, reasons: list[str] | None = None) -> Path:
    """The example, turned into a live review with a frame per arm in folder/assets."""
    doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    (folder / "assets").mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(PNG).hexdigest()
    for arm, replay in (("base", "1" * 64), ("candidate", "2" * 64)):
        (folder / "assets" / f"{arm}.png").write_bytes(PNG)
        doc["arms"][arm].update(provenance="harness", replaySha256=replay,
                                frame={"path": f"assets/{arm}.png", "frame": 30, "sha256": sha})
    doc.update(mode="live", evidenceLabel="FRESH LIVE")
    if reasons is not None:
        doc["reasons"] = reasons
    path = folder / "change-evidence.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


class ReviewPageTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def page(self, record: Path, out: Path | None = None) -> str:
        return render(record, out or record.parent).read_text(encoding="utf-8")

    def test_the_sample_review_renders_status_first_and_says_it_is_a_sample(self):
        text = self.page(EXAMPLE, self.tmp / "out")
        self.assertIn("REPAIR DEMONSTRATED", text)
        self.assertIn("SAMPLE", text)
        self.assertIn("Candidate from a fixture patch", text)
        self.assertIn("Verifier decision: accept", text)
        self.assertLess(text.index("REPAIR DEMONSTRATED"), text.index("<table"))
        self.assertIn("a sample review runs on recorded observations", text)
        self.assertNotIn("<img", text)  # no frames in a sample review, and none invented

    def test_self_contained_with_no_scripts_and_no_dashes_in_its_words(self):
        text = self.page(EXAMPLE, self.tmp / "out")
        self.assertNotIn("<script", text.lower())
        self.assertIsNone(re.search(r"(src|href)=\"(https?:)?//", text))
        self.assertNotIn("http://", text)
        self.assertNotIn("https://", text)
        for dash in ("—", "–"):
            self.assertNotIn(dash, text)

    def test_strings_from_the_record_are_escaped_and_keys_redacted(self):
        record = _live_record(self.tmp / "review", reasons=[
            '<script>alert("x")</script> failed', "provider said msk-" + "Z" * 40])
        text = self.page(record)
        self.assertNotIn("<script>alert", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertNotIn("Z" * 20, text)
        self.assertIn("[redacted]", text)

    def test_frames_show_side_by_side_with_their_run_arm_frame_and_replay(self):
        text = self.page(_live_record(self.tmp / "review"))
        self.assertEqual(len(re.findall(r'<img src="assets/(base|candidate)\.png"', text)), 2)
        self.assertIn("failing base, frame 30, replay 111111111111", text)
        self.assertIn("candidate, frame 30, replay 222222222222", text)

    def test_a_missing_frame_is_said_to_be_missing_never_replaced(self):
        record = _live_record(self.tmp / "review")
        (self.tmp / "review" / "assets" / "candidate.png").unlink()
        text = self.page(record)
        self.assertEqual(len(re.findall(r"<img ", text)), 1)
        self.assertIn("missing from the review folder", text)

    def test_a_frame_changed_after_recording_is_not_shown(self):
        record = _live_record(self.tmp / "review")
        (self.tmp / "review" / "assets" / "base.png").write_bytes(PNG + b"tampered")
        text = self.page(record)
        self.assertNotIn('src="assets/base.png"', text)
        self.assertIn("changed after it was recorded", text)
        self.assertIn("does not match its recorded SHA256", text)

    def test_a_copied_folder_still_renders_its_frames(self):
        self.page(_live_record(self.tmp / "review"))
        moved = self.tmp / "elsewhere" / "copy"
        shutil.copytree(self.tmp / "review", moved)
        text = (moved / "review.html").read_text(encoding="utf-8")
        for src in re.findall(r'<img src="([^"]+)"', text):
            self.assertTrue((moved / src).is_file(), src)

    def test_rendering_into_another_folder_brings_the_frames(self):
        record = _live_record(self.tmp / "review")
        text = self.page(record, self.tmp / "published")
        for src in re.findall(r'<img src="([^"]+)"', text):
            self.assertTrue((self.tmp / "published" / src).is_file(), src)

    def test_a_republished_live_review_says_it_is_recorded(self):
        record = _live_record(self.tmp / "review")
        page = render(record, self.tmp / "review", recorded="fix matrix run 1, demo run 1").read_text(encoding="utf-8")
        self.assertIn("RECORDED LIVE", page)
        self.assertIn("the run labelled it FRESH LIVE", page)
        self.assertIn("Recorded evidence: fix matrix run 1, demo run 1", page)
        self.assertNotIn("Evidence: FRESH LIVE", page)
        fresh = self.page(record)
        self.assertIn("Evidence: FRESH LIVE", fresh)
        self.assertNotIn("Recorded evidence", fresh)

    def test_private_routes_are_counts_only(self):
        text = self.page(EXAMPLE, self.tmp / "out")
        self.assertIn("1 check on the private routes: 1 passed, 0 failed, 0 need review", text)

    def test_a_record_that_is_not_valid_is_refused(self):
        doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        doc["status"] = "APPROVED"
        bad = self.tmp / "change-evidence.json"
        bad.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaises(ContractError):
            render(bad, self.tmp)

    def test_the_loop_writes_the_page_when_the_review_is_on(self):
        from agents.loop import one_run

        root = self.tmp / "loop"
        env = {"EXPECTRAIL_REVIEW": "on", "EXPECTRAIL_HELDOUT_DIR": "", "EXPECTRAIL_OBS_PROVIDER": "trace"}
        with mock.patch.dict(os.environ, env):
            result = one_run(root, use_muse=False, offline_triage=True,
                             observations=REPO / "agents" / "fixtures" / "obs-fixed.json",
                             candidate_patch=REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                             skip_harness=True, run_trust=False)
        self.assertEqual(result["review"]["html"], str(root / "review" / "review.html"))
        self.assertIn("REPAIR DEMONSTRATED", (root / "review" / "review.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
