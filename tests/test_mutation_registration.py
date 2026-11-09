"""The mutation bench's registration stays checkable after main moves on.

Its pins are the sha256 of the code that judged the runs (bench/mutation/preregistration.json). The
bench is recorded, so main may change those files; the registration now describes commit c169a5e,
the hackathon submission, which judged runs check out. These tests make sure the record itself is
untouched and still matches the code at that commit, and that main refuses with a message naming the
commit rather than judging anything with changed code.
"""
from __future__ import annotations

import hashlib
import unittest

from agents import mutate_game as mg
from tests import submission_commit

# The registration as merged before any judged run (#145). It never changes.
REGISTRATION_SHA256 = "719eb1e2c049b374aa0b9161e0a3c96f159a964b5be2c28a0731c9cc753061ab"


class RegistrationRecordTest(unittest.TestCase):
    def test_the_registration_file_is_unchanged(self):
        self.assertEqual(hashlib.sha256(mg.PREREGISTRATION.read_bytes()).hexdigest(), REGISTRATION_SHA256,
                         "bench/mutation/preregistration.json is the record of the judged runs: never edit it")

    def test_it_names_the_commit_it_describes(self):
        self.assertEqual(mg.REGISTERED_COMMIT, submission_commit.COMMIT)


@unittest.skipUnless(submission_commit.available(), "the submission commit is not fetched (CI fetches it)")
class RegistrationHoldsAtTheSubmissionTest(unittest.TestCase):
    def test_the_registration_loads_against_the_code_at_the_submission(self):
        paths = [*mg.PINNED, *mg.PINNED_TREES, mg.GAME.relative_to(mg.REPO).as_posix(),
                 mg.PREREGISTRATION.relative_to(mg.REPO).as_posix()]
        root = submission_commit.extract(paths)
        doc = mg.load_preregistration(root / mg.PREREGISTRATION.relative_to(mg.REPO), root=root)
        self.assertEqual(doc["sha256"], REGISTRATION_SHA256)

    def test_a_moved_pin_is_refused_with_the_commit_named(self):
        paths = [*mg.PINNED, *mg.PINNED_TREES, mg.GAME.relative_to(mg.REPO).as_posix(),
                 mg.PREREGISTRATION.relative_to(mg.REPO).as_posix()]
        root = submission_commit.extract(paths)
        (root / "agents" / "verifier.py").write_text("# changed after registration\n")
        with self.assertRaises(mg.PreregistrationError) as caught:
            mg.load_preregistration(root / mg.PREREGISTRATION.relative_to(mg.REPO), root=root)
        self.assertIn("agents/verifier.py", str(caught.exception))
        self.assertIn(mg.REGISTERED_COMMIT, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
