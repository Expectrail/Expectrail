"""The native record #659 asks for: the machine's `patch`, its version, and the tree after each control.

`tools.patch_controls` applies the three controls from #378 (a deletion, an edit that empties a file,
and one patch doing both with a creation), first with the raw `patch` command and then through
`harness.patching.apply`, and writes what it found. The macOS job runs it, so the record comes from a
Mac and not from a guess.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from harness import patching
from tools import patch_controls

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "macos.yml"


def _gnu() -> bool:
    try:
        out = subprocess.run(["patch", "--version"], capture_output=True, text=True).stdout
    except OSError:
        return False
    return out.startswith("GNU patch")


def _posix(real):
    """GNU patch under POSIXLY_CORRECT for patches that delete, as macOS's patch behaves for those."""
    def run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "patch" and "-i" in cmd:
            text = Path(cmd[cmd.index("-i") + 1]).read_text(encoding="utf-8")
            if "\n+++ /dev/null" in "\n" + text:
                kwargs["env"] = {**os.environ, "POSIXLY_CORRECT": "1"}
        return real(cmd, *args, **kwargs)
    return run


class Controls(unittest.TestCase):
    def test_the_three_controls_are_the_ones_the_issue_names(self):
        self.assertEqual([c["name"] for c in patch_controls.CONTROLS], ["delete", "empty-by-edit", "both"])
        both = next(c for c in patch_controls.CONTROLS if c["name"] == "both")
        self.assertEqual(both["expect"], {"BUG": "absent", "keep.txt": "file, 0 bytes",
                                          "new.txt": "file, 6 bytes"})

    def test_each_control_names_its_files_as_the_patch_reader_does(self):
        for control in patch_controls.CONTROLS:
            self.assertEqual(set(patching.files(control["patch"])), set(control["expect"]), control["name"])

    def test_the_raw_run_is_the_command_apply_runs(self):
        seen = []

        def run(cmd, *args, **kwargs):
            seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        with mock.patch.object(patch_controls.subprocess, "run", run), \
                mock.patch.object(patch_controls.shutil, "which", return_value="/bin/patch"), \
                mock.patch.object(patch_controls.patching, "apply", lambda work, patch: None):
            patch_controls.run_all()
        raw = [c for c in seen if "-i" in c]
        self.assertEqual(len(raw), 3)
        for cmd in raw:
            work, patch = Path(cmd[cmd.index("-d") + 1]), Path(cmd[cmd.index("-i") + 1])
            self.assertEqual(cmd, patching.command(work, patch))

    def test_a_file_state_is_said_plainly(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "a").write_text("abc")
        (tmp / "e").write_text("")
        (tmp / "d").mkdir()
        self.assertEqual(patch_controls.state(tmp / "a"), "file, 3 bytes")
        self.assertEqual(patch_controls.state(tmp / "e"), "file, 0 bytes")
        self.assertEqual(patch_controls.state(tmp / "d"), "not a file")
        self.assertEqual(patch_controls.state(tmp / "x"), "absent")


@unittest.skipUnless(shutil.which("patch"), "needs the patch program")
class OnThisMachine(unittest.TestCase):
    def test_apply_gives_the_named_tree_for_every_control(self):
        found = patch_controls.run_all()
        self.assertTrue(found["program"]["path"])
        for row in found["controls"]:
            self.assertEqual(row["applied"], row["expect"], row["name"])
            self.assertIsNone(row["error"], row["name"])
            self.assertTrue(row["matches"], row["name"])
        self.assertTrue(found["all_match"])

    def test_the_version_line_is_recorded(self):
        found = patch_controls.run_all()
        self.assertTrue(found["program"]["version"])
        self.assertNotIn("\n", found["program"]["version"])

    @unittest.skipUnless(_gnu(), "needs GNU patch, which can be put in POSIX mode")
    def test_with_mac_style_deletion_the_raw_tree_keeps_an_empty_file_and_apply_does_not(self):
        with mock.patch.object(subprocess, "run", _posix(subprocess.run)):
            found = patch_controls.run_all()
        rows = {r["name"]: r for r in found["controls"]}
        self.assertEqual(rows["delete"]["raw"], {"BUG": "file, 0 bytes"})
        self.assertEqual(rows["delete"]["applied"], {"BUG": "absent"})
        self.assertTrue(rows["delete"]["matches"])
        self.assertTrue(rows["empty-by-edit"]["matches"])
        # POSIX mode also refuses to create a file from /dev/null, which macOS's patch does not, so this
        # emulation cannot stand in for `both`. The report says the run stopped; it never says it matched.
        self.assertFalse(rows["both"]["matches"])
        self.assertIn("exit 1", rows["both"]["error"])
        self.assertFalse(found["all_match"])

    def test_a_tree_that_does_not_match_is_reported_not_hidden(self):
        def leave_content(work, patch):
            raise patching.PatchNotApplied("BUG is deleted by the patch but is still there with content")
        with mock.patch.object(patch_controls.patching, "apply", leave_content):
            found = patch_controls.run_all()
        self.assertFalse(found["all_match"])
        text = patch_controls.render(found)
        self.assertIn("still there with content", text)
        self.assertIn("does not match", text)


class Report(unittest.TestCase):
    def test_no_patch_program_is_said_and_nothing_is_claimed(self):
        with mock.patch.object(patch_controls.shutil, "which", return_value=None):
            found = patch_controls.run_all()
        self.assertIsNone(found["program"]["path"])
        self.assertEqual(found["controls"], [])
        self.assertFalse(found["all_match"])
        self.assertIn("no `patch` program", patch_controls.render(found))

    @unittest.skipUnless(shutil.which("patch"), "needs the patch program")
    def test_the_command_appends_to_the_summary_and_exits_zero(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        summary = tmp / "summary.md"
        summary.write_text("before\n")
        code = patch_controls.main([str(summary)])
        self.assertEqual(code, 0)
        text = summary.read_text()
        self.assertTrue(text.startswith("before\n"))
        self.assertIn("## Patch controls on this machine (#659)", text)
        self.assertIn(shutil.which("patch"), text)
        for name in ("delete", "empty-by-edit", "both"):
            self.assertIn(f"`{name}`", text)


class Workflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    def test_the_macos_job_records_the_controls_whatever_the_suite_did(self):
        steps = self.doc["jobs"]["suite"]["steps"]
        rows = [s for s in steps if "tools.patch_controls" in s.get("run", "")]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("if"), "always()")
        self.assertIn("$GITHUB_STEP_SUMMARY", rows[0]["run"])

    def test_a_change_to_the_tool_runs_the_macos_job_on_its_pull_request(self):
        # yaml reads the bare key `on` as True.
        triggers = self.doc.get("on", self.doc.get(True))
        self.assertIn("tools/patch_controls.py", triggers["pull_request"]["paths"])
        self.assertIn("harness/patching.py", triggers["pull_request"]["paths"])


if __name__ == "__main__":
    unittest.main()
