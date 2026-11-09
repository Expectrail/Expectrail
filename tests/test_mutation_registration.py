"""The mutation bench's registration stays checkable after main moves on.

Its pins are the sha256 of the code that judged the runs (bench/mutation/preregistration.json). The
bench is recorded, so main may change those files; the registration is now held at the tag
`submission` (c169a5e), where judged runs check out the code. These tests make sure the record
itself is untouched and still matches the code at that tag, and that main refuses with a message
naming the tag rather than judging anything with changed code.
"""
from __future__ import annotations

import hashlib
import unittest

from agents import mutate_game as mg
from tests import tagtree

# The registration as merged before any judged run (#145). It never changes.
REGISTRATION_SHA256 = "719eb1e2c049b374aa0b9161e0a3c96f159a964b5be2c28a0731c9cc753061ab"


class RegistrationRecordTest(unittest.TestCase):
    def test_the_registration_file_is_unchanged(self):
        self.assertEqual(hashlib.sha256(mg.PREREGISTRATION.read_bytes()).hexdigest(), REGISTRATION_SHA256,
                         "bench/mutation/preregistration.json is the record of the judged runs: never edit it")

    def test_it_names_the_tag_it_describes(self):
        self.assertEqual(mg.REGISTERED_TAG, tagtree.TAG)
        self.assertTrue(mg.REGISTERED_COMMIT.startswith("c169a5e"))


@unittest.skipUnless(tagtree.tag_available(), "the submission tag is not fetched (CI fetches it)")
class RegistrationHoldsAtTheTagTest(unittest.TestCase):
    def test_the_registration_loads_against_the_code_at_the_tag(self):
        paths = [*mg.PINNED, *mg.PINNED_TREES, mg.GAME.relative_to(mg.REPO).as_posix(),
                 mg.PREREGISTRATION.relative_to(mg.REPO).as_posix()]
        root = tagtree.extract(paths)
        doc = mg.load_preregistration(root / mg.PREREGISTRATION.relative_to(mg.REPO), root=root)
        self.assertEqual(doc["sha256"], REGISTRATION_SHA256)

    def test_a_moved_pin_is_refused_with_the_tag_named(self):
        paths = [*mg.PINNED, *mg.PINNED_TREES, mg.GAME.relative_to(mg.REPO).as_posix(),
                 mg.PREREGISTRATION.relative_to(mg.REPO).as_posix()]
        root = tagtree.extract(paths)
        (root / "agents" / "verifier.py").write_text("# changed after registration\n")
        with self.assertRaises(mg.PreregistrationError) as caught:
            mg.load_preregistration(root / mg.PREREGISTRATION.relative_to(mg.REPO), root=root)
        self.assertIn("agents/verifier.py", str(caught.exception))
        self.assertIn(mg.REGISTERED_TAG, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
