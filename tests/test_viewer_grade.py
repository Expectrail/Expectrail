"""The grade displayed beside a verdict comes only from its job record."""
import json
import tempfile
import unittest
from pathlib import Path

from expectrail import viewer
from expectrail.gate import record
from tests.test_viewer import banner_state

EXAMPLES = Path(__file__).resolve().parents[1] / "contracts" / "examples"


class ViewerGradeTest(unittest.TestCase):
    def setUp(self):
        self.findings = json.loads((EXAMPLES / "findings.json").read_text())
        self.job = json.loads((EXAMPLES / "verify-job.json").read_text())
        record.check_record(self.findings)

    def assert_header(self, page, grade):
        header = page.split("<h1>", 1)[1].split("<h2>Not tested</h2>", 1)[0]
        self.assertIn(f"<dt>Evidence grade</dt><dd>{grade}</dd>", header)
        self.assertIn(viewer.esc(record.observers_words(self.findings)), header)
        self.assertIn(viewer.esc(record.isolation_words(self.findings.get("isolation"))), header)
        self.assertEqual(banner_state(page), "behaviour-failure")

    def test_folder_and_export_show_grade_even_without_job_metadata(self):
        for grade in ("diagnostic", "isolated", None):
            with self.subTest(grade=grade), tempfile.TemporaryDirectory() as temp:
                job = dict(self.job, executionClass=grade, evidenceGrade=grade) if grade else None
                page = viewer.write(Path(temp), self.findings, status=job)
                for path in (page, page.parent / viewer.EXPORT_NAME):
                    self.assert_header(path.read_text(), grade or "Not recorded")

    def test_execution_class_and_receipt_verification_cannot_supply_a_missing_grade(self):
        job = dict(self.job, executionClass="isolated", evidenceGrade=None)
        with tempfile.TemporaryDirectory() as temp:
            page = viewer.write(Path(temp), self.findings, status=job)
            self.assert_header(page.read_text(), "Not recorded")
        self.assert_header(viewer.render_published(self.findings, "reject"), "Not recorded")
