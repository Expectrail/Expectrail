"""A repair record's folder may be reached through a link; its proofs may not be links (#378).

On macOS every temporary folder is reached through a link (``/var`` -> ``/private/var``). The
provider-only check and CI's autofix bundle refused an invocation proof whenever any folder above
it was a link, so a record in a temporary folder on a Mac (or under CI's linked ``TMPDIR``) could
never be published. ``record.unlinked_below`` allows links above the record's folder and refuses
them inside it, with the resolved-path comparison kept as a fallback.
"""
import tempfile
import unittest
from pathlib import Path

from expectrail import repair_provenance
from expectrail.gate import record

PROOF = "attempt-1/fixer-invocation.json"


class LinkedRecordFolder(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="expectrail-proof-")
        self.addCleanup(tmp.cleanup)
        self.real = Path(tmp.name).resolve() / "private"
        (self.real / "attempt-1").mkdir(parents=True)
        (self.real / PROOF).write_bytes(b"{}\n")
        self.link = Path(tmp.name).resolve() / "var"
        self.link.symlink_to(self.real, target_is_directory=True)
        self.outside = Path(tmp.name).resolve() / "outside.json"
        self.outside.write_bytes(b"{}\n")

    def test_a_link_above_the_record_is_allowed(self):
        self.assertEqual(record.unlinked_below(self.link, PROOF), self.link / PROOF)
        self.assertEqual(record.unlinked_below(self.real, PROOF), self.real / PROOF)

    def test_a_linked_proof_file_is_refused(self):
        (self.real / PROOF).unlink()
        (self.real / PROOF).symlink_to(self.outside)
        for base in (self.real, self.link):
            with self.assertRaises(record.RecordError):
                record.unlinked_below(base, PROOF)

    def test_a_linked_attempt_folder_is_refused(self):
        other = self.real.parent / "elsewhere"
        (self.real / "attempt-1").rename(other)
        (self.real / "attempt-1").symlink_to(other, target_is_directory=True)
        with self.assertRaises(record.RecordError):
            record.unlinked_below(self.link, PROOF)

    def test_paths_that_leave_the_record_are_refused(self):
        for rel in ("../outside.json", str(self.outside), "attempt-1/../../outside.json", "", "."):
            with self.subTest(rel=rel), self.assertRaises(record.RecordError):
                record.unlinked_below(self.real, rel)

    def doc(self):
        return {"fixer": {"source": "llm-patch", "sandboxed": False, "providerOnly": True},
                "budget": {"usdCap": 6},
                "attempts": [{"n": 1, "fixerInvocation": PROOF, "fixerInvocationSha256": "0" * 64}]}

    def test_provider_only_reads_a_proof_through_a_linked_record_folder(self):
        # Past the link check: it reaches the digest comparison, which this stand-in proof fails.
        with self.assertRaisesRegex(ValueError, "digest differs"):
            repair_provenance.provider_only(self.link / "repair-run.json", self.doc())

    def test_provider_only_still_refuses_a_linked_proof(self):
        (self.real / PROOF).unlink()
        (self.real / PROOF).symlink_to(self.outside)
        with self.assertRaisesRegex(ValueError, "linked invocation proof"):
            repair_provenance.provider_only(self.link / "repair-run.json", self.doc())


if __name__ == "__main__":
    unittest.main()
