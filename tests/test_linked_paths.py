"""A project, checkout or temporary folder reached through a symbolic link is still that folder (#378).

On macOS every temporary folder is reached through one: ``/var`` is a link to ``/private/var``, so
``tempfile`` hands out ``/var/folders/...`` while ``Path.resolve()`` says ``/private/var/folders/...``.
Code that resolves one side of a comparison and not the other then reads its own project as outside
itself. These tests build that layout on any system with a link of their own, so the cases below
are held on Linux CI as well as on a Mac. They also hold that the containment rules still refuse
what they refused before: a link out of the project is not let in by resolving.

CI's ``test`` job also runs the whole suite with ``TMPDIR`` behind a link (``.github/workflows/ci.yml``),
which is how a new test that compares two spellings of one folder is caught before a Mac meets it.
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail import onboard, onboarding


def linked(test: unittest.TestCase) -> tuple[Path, Path]:
    """(real folder, a link to it), removed after the test."""
    tmp = tempfile.TemporaryDirectory(prefix="expectrail-linked-")
    test.addCleanup(tmp.cleanup)
    real = Path(tmp.name).resolve() / "private"
    real.mkdir()
    link = Path(tmp.name).resolve() / "var"
    link.symlink_to(real, target_is_directory=True)
    return real, link


class ProjectThroughALink(unittest.TestCase):
    def setUp(self):
        real, link = linked(self)
        self.project = link / "game"
        self.project.mkdir()
        (self.project / "art.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (self.project / "main.tscn").write_text('[gd_scene format=3 uid="uid://main"]\n', encoding="utf-8")
        self.outside = real / "outside.png"
        self.outside.write_bytes(b"\x89PNG\r\n\x1a\n")

    def test_a_resource_in_the_project_is_found(self):
        self.assertEqual(onboarding.resource(self.project, "res://art.png"), (self.project / "art.png").resolve())

    def test_the_entry_scene_is_found_by_its_uid(self):
        self.assertEqual(onboarding.entry_scene(self.project, "uid://main"), "res://main.tscn")

    def test_a_local_file_in_the_project_is_found(self):
        self.assertTrue(onboard.local_file(self.project, "art.png").is_file())

    def test_what_leaves_the_project_is_still_refused(self):
        (self.project / "away.png").symlink_to(self.outside)
        for uri in ("res://../outside.png", "res://away.png", "res://missing.png"):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                onboarding.resource(self.project, uri)
        for name in ("away.png", "../outside.png", "missing.png"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                onboard.local_file(self.project, name)


class SplitGateThroughALinkedTemporaryFolder(unittest.TestCase):
    """The two-job gate's judge with every folder it is given and makes behind a link: it decides as
    it does without one, instead of finding "no Godot project" in its own base checkout."""

    def setUp(self):
        _real, link = linked(self)
        patcher = mock.patch.object(tempfile, "tempdir", str(link))
        patcher.start()
        self.addCleanup(patcher.stop)
        from tests.test_ci_gate import SplitGateTest

        self.case = SplitGateTest("test_regression_rejects")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.assertNotEqual(self.case.root, self.case.root.resolve(), "the test's folders are behind a link")

    def test_a_correct_fix_is_accepted(self):
        case = self.case
        case.capture()
        head_data = shutil.copytree(case.head, case.root / "head-data")
        shutil.rmtree(case.head)
        doc = case.judge(head_checkout=head_data)
        self.assertEqual(doc["decision"], "accept", doc["reasons"])

    def test_a_regression_is_rejected(self):
        case = self.case
        (case.base / "game/platformer/BUG").unlink()
        (case.head / "game/platformer/BUG").touch()
        case.capture("none")
        self.assertEqual(case.judge("none")["decision"], "reject")


if __name__ == "__main__":
    unittest.main()
