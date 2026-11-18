"""The hostile-feedback film: refusals, guard blocks, verifier accept, honest labels."""
from __future__ import annotations

import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from agents import film_feedback as film
from harness.run import REPO
from expectrail import spec_writer


# Historical trace fixtures: explicitly select the diagnostic benchmark control.
def setUpModule():
    global _trace_control
    _trace_control = mock.patch.dict("os.environ", {"EXPECTRAIL_OBS_PROVIDER": "trace"})
    _trace_control.start()


def tearDownModule():
    _trace_control.stop()


class FilmFeedbackTest(unittest.TestCase):
    def test_rehearsal_passes_and_labels_what_is_scripted(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "film"
            result = film.run(out)
            self.assertTrue(result["ok"], result["problems"])
            self.assertEqual((result["refused"], result["drafts"], result["decision"]), (2, 2, "accept"))
            self.assertEqual(result["guard"]["blocked"], 5)
            attempts = json.loads((out / "fix" / "hostile-attempts.json").read_text())
            self.assertTrue(all(a["decision"] == a["expected"] for a in attempts))
            guard = json.loads((out / "fix" / "guard.json").read_text())
            self.assertEqual(guard["source"], "scripted")
            md = (out / "morning" / "morning-report.md").read_text()
            self.assertIn("scripted for the film", md)
            film_md = (out / "film.md").read_text()
            self.assertIn("scripted attempts through the real hook; not model behavior", film_md)
            self.assertIn("saved transcript (fixture)", film_md)
            # the approve command the film tells you to run on camera works
            draft = next(out.joinpath("feedback", "drafts").glob("*.json"))
            doc = spec_writer.approve(draft, by="film-test")
            self.assertEqual(doc["approval"]["by"], "film-test")

    def test_relative_out_dir_works(self):
        import os

        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                result = film.run(Path("runs/film"))
            finally:
                os.chdir(cwd)
            self.assertTrue(result["ok"], result["problems"])

    def test_a_hook_that_does_not_answer_is_a_failure(self):
        from unittest import mock

        broken = mock.Mock(returncode=2, stdout="", stderr="python3: can't open file")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(film.subprocess, "run", return_value=broken):
            result = film.run(Path(tmp) / "film")
        self.assertFalse(result["ok"])
        self.assertTrue(any("said error" in p for p in result["problems"]))

    def test_fails_when_nothing_asks_to_weaken_a_check(self):
        example = json.loads((REPO / "contracts" / "examples" / "feedback-intake.json").read_text())
        example["items"] = [i for i in example["items"] if i["category"] != "weaken-check"]
        example["counts"]["weaken-check"] = 0
        with tempfile.TemporaryDirectory() as tmp:
            intake = Path(tmp) / "feedback-intake.json"
            intake.write_text(json.dumps(example))
            result = film.run(Path(tmp) / "film", intake=intake)
            self.assertFalse(result["ok"])
            self.assertTrue(any("weaken" in p for p in result["problems"]))
            self.assertEqual(film.main(["--out", str(Path(tmp) / "film2"), "--intake", str(intake)]), 1)

    def test_live_guard_file_replaces_the_scripted_attempts(self):
        live = {"installed": True, "loaded": True, "calls": 12, "source": "muse",
                "blocked": [{"tool": "web_fetch", "reason": "web_fetch is not available to the fixer"}]}
        with tempfile.TemporaryDirectory() as tmp:
            guard = Path(tmp) / "guard.json"
            guard.write_text(json.dumps(live))
            out = Path(tmp) / "film"
            result = film.run(out, live_guard=guard)
            self.assertTrue(result["ok"], result["problems"])
            self.assertFalse((out / "fix" / "hostile-attempts.json").exists())
            md = (out / "morning" / "morning-report.md").read_text()
            self.assertNotIn("scripted for the film", md)
            self.assertIn("Muse Code's own tool calls", (out / "film.md").read_text())


if __name__ == "__main__":
    unittest.main()
