"""A candidate is applied to the tree it names, whichever `patch` the machine has (#659).

macOS's `patch` leaves a zero-byte file behind where a patch deletes it (`+++ /dev/null`); GNU `patch`
does the same under POSIXLY_CORRECT. The verifier then judged a tree in which the deleted file was
still there. `harness.patching.apply` reads the patch's own headers and hunks and makes the tree match
them after `patch` exits 0, or stops.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness import patching

DELETE = "--- a/BUG\n+++ /dev/null\n@@ -1 +0,0 @@\n-1\n"
EMPTY = "--- a/keep.txt\n+++ b/keep.txt\n@@ -1 +0,0 @@\n-only line\n"
CREATE = "--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1 @@\n+hello\n"


def _gnu() -> bool:
    try:
        out = subprocess.run(["patch", "--version"], capture_output=True, text=True).stdout
    except OSError:
        return False
    return out.startswith("GNU patch")


def _posix_for_deletions(real):
    """Run `patch` the way macOS does for a deletion: GNU patch under POSIXLY_CORRECT, for patches that
    delete a file only (POSIX mode also changes how files are created, which macOS does not)."""
    def run(cmd, *args, **kwargs):
        if cmd and cmd[0] == "patch" and "-i" in cmd:
            text = Path(cmd[cmd.index("-i") + 1]).read_text(encoding="utf-8")
            if "\n+++ /dev/null" in "\n" + text:
                kwargs["env"] = {**os.environ, "POSIXLY_CORRECT": "1"}
        return real(cmd, *args, **kwargs)
    return run


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="expectrail-patching-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.work = self.tmp / "game"
        self.work.mkdir()
        (self.work / "BUG").write_text("1\n")
        (self.work / "keep.txt").write_text("only line\n")

    def patch_file(self, text: str, name: str = "candidate.patch") -> Path:
        path = self.tmp / name
        path.write_text(text)
        return path


@unittest.skipUnless(shutil.which("patch"), "needs the patch program")
class RealPatch(Case):
    """The three controls from #378, with the machine's own `patch`."""

    def test_delete_to_dev_null_removes_the_file(self):
        patching.apply(self.work, self.patch_file(DELETE))
        self.assertFalse((self.work / "BUG").exists())

    def test_edit_removing_the_last_line_keeps_an_empty_file(self):
        patching.apply(self.work, self.patch_file(EMPTY))
        self.assertTrue((self.work / "keep.txt").is_file())
        self.assertEqual((self.work / "keep.txt").read_bytes(), b"")

    def test_one_patch_deletes_one_file_and_empties_another(self):
        patching.apply(self.work, self.patch_file(DELETE + EMPTY + CREATE))
        self.assertFalse((self.work / "BUG").exists())
        self.assertEqual((self.work / "keep.txt").read_bytes(), b"")
        self.assertEqual((self.work / "new.txt").read_text(), "hello\n")

    def test_git_style_deletion(self):
        text = "diff --git a/BUG b/BUG\ndeleted file mode 100644\nindex d00491f..0000000\n" + DELETE
        patching.apply(self.work, self.patch_file(text))
        self.assertFalse((self.work / "BUG").exists())

    def test_a_game_copy_inside_another_git_checkout(self):
        outer = self.tmp / "checkout"
        game = outer / "game" / "platformer"
        shutil.copytree(self.work, game)
        subprocess.run(["git", "init", "-q", str(outer)], check=True)
        patching.apply(game, self.patch_file(DELETE + EMPTY))
        self.assertFalse((game / "BUG").exists())
        self.assertEqual((game / "keep.txt").read_bytes(), b"")

    def test_a_patch_that_does_not_apply_still_fails(self):
        with self.assertRaises(subprocess.CalledProcessError):
            patching.apply(self.work, self.patch_file("--- a/keep.txt\n+++ b/keep.txt\n@@ -1 +1 @@\n-other\n+x\n"))


@unittest.skipUnless(_gnu(), "needs GNU patch, which can be put in POSIX mode")
class MacStyleDeletion(Case):
    """GNU patch in POSIX mode leaves a deleted file empty, as macOS's patch does (#378)."""

    def test_the_raw_program_leaves_an_empty_file(self):
        # The control: without the rule below, the tree keeps BUG.
        subprocess.run(["patch", "-p1", "--forward", "--batch", "-d", str(self.work), "-i",
                        str(self.patch_file(DELETE))], check=True, capture_output=True,
                       env={**os.environ, "POSIXLY_CORRECT": "1"})
        self.assertTrue((self.work / "BUG").is_file())
        self.assertEqual((self.work / "BUG").stat().st_size, 0)

    def test_apply_removes_what_the_patch_deletes(self):
        with mock.patch.object(patching.subprocess, "run", _posix_for_deletions(subprocess.run)):
            patching.apply(self.work, self.patch_file(DELETE + EMPTY))
        self.assertFalse((self.work / "BUG").exists())
        self.assertEqual((self.work / "keep.txt").read_bytes(), b"")


class TreeMustMatch(Case):
    """When `patch` exits 0 but the tree is not what the patch names, the application stops."""

    def ok(self, effect=None):
        def run(cmd, *args, **kwargs):
            if effect:
                effect()
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return mock.patch.object(patching.subprocess, "run", run)

    def test_a_deleted_file_left_with_content_stops(self):
        with self.ok(), self.assertRaisesRegex(patching.PatchNotApplied, "BUG.*still there"):
            patching.apply(self.work, self.patch_file(DELETE))
        self.assertTrue((self.work / "BUG").exists())

    def test_a_deleted_name_left_as_a_folder_stops(self):
        (self.work / "BUG").unlink()
        (self.work / "BUG").mkdir()
        with self.ok(), self.assertRaisesRegex(patching.PatchNotApplied, "BUG"):
            patching.apply(self.work, self.patch_file(DELETE))

    def test_an_edited_file_that_is_gone_stops(self):
        with self.ok(lambda: (self.work / "keep.txt").unlink()), \
                self.assertRaisesRegex(patching.PatchNotApplied, "keep.txt.*missing"):
            patching.apply(self.work, self.patch_file(EMPTY))

    def test_a_created_file_that_is_not_there_stops(self):
        with self.ok(), self.assertRaisesRegex(patching.PatchNotApplied, "new.txt.*missing"):
            patching.apply(self.work, self.patch_file(CREATE))

    def test_the_error_is_a_failed_patch_to_existing_callers(self):
        # runit, repair and the proposal writer already stop on CalledProcessError and OSError.
        self.assertTrue(issubclass(patching.PatchNotApplied, subprocess.CalledProcessError))
        with self.ok():
            try:
                patching.apply(self.work, self.patch_file(DELETE))
            except subprocess.CalledProcessError as exc:
                self.assertNotIn("non-zero exit status", str(exc))
                self.assertIn("BUG", str(exc))
            else:
                self.fail("no error")


class Reading(unittest.TestCase):
    def test_lines_inside_a_hunk_are_not_headers(self):
        # A removed line "-- x" reads "--- x" and an added "++ y" reads "+++ y"; neither names a file.
        text = ("--- a/notes.txt\n+++ b/notes.txt\n@@ -1,2 +1,2 @@\n--- x\n+++ y\n keep\n"
                "--- a/BUG\n+++ /dev/null\n@@ -1 +0,0 @@\n-1\n")
        self.assertEqual(patching.files(text), {"notes.txt": "edit", "BUG": "delete"})

    def test_timestamps_and_quoted_names(self):
        text = ('--- "a/two words.txt"\t2026-11-19 10:00:00\n+++ "b/two words.txt"\t2026-11-19 10:01:00\n'
                "@@ -1 +1 @@\n-a\n+b\n")
        self.assertEqual(patching.files(text), {"two words.txt": "edit"})

    def test_creation_and_counts_without_a_length(self):
        self.assertEqual(patching.files(CREATE), {"new.txt": "create"})
        self.assertEqual(patching.files(DELETE + EMPTY), {"BUG": "delete", "keep.txt": "edit"})

    def test_a_hunk_cut_short_is_read_as_patch_reads_it(self):
        # GNU patch accepts trailing context that ends early (agents/fixtures/out-of-glob.patch does).
        self.assertEqual(patching.files("--- a/x\n+++ b/x\n@@ -1,4 +1,5 @@\n a\n+b\n c\n"), {"x": "edit"})
        # Cut short and followed by the next file: the next header is still read.
        text = "--- a/x\n+++ b/x\n@@ -1,4 +1,4 @@\n a\n-b\n+c\n" + DELETE
        self.assertEqual(patching.files(text), {"x": "edit", "BUG": "delete"})

    def test_a_hunk_longer_than_its_header_is_refused(self):
        with self.assertRaisesRegex(patching.PatchNotApplied, "more lines"):
            patching.files("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n-b\n+c\n")

    def test_what_cannot_be_checked_is_refused_before_patch_runs(self):
        cases = {
            "outside": "--- a/../x\n+++ b/../x\n@@ -1 +1 @@\n-a\n+b\n",
            "absolute": "--- /etc/x\n+++ /etc/x\n@@ -1 +1 @@\n-a\n+b\n",
            "rename": "diff --git a/x b/y\nsimilarity index 100%\nrename from x\nrename to y\n",
            "copy": "diff --git a/x b/y\nsimilarity index 100%\ncopy from x\ncopy to y\n",
            "binary": "diff --git a/x.png b/x.png\nGIT binary patch\nliteral 1\nIc${4\n",
            "binary-diff": "diff --git a/x.png b/x.png\nBinary files a/x.png and b/x.png differ\n",
            "nothing": "--- /dev/null\n+++ /dev/null\n",
            "no-files": "just words\n",
        }
        for name, text in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "p.patch"
                path.write_text(text)
                with mock.patch.object(patching.subprocess, "run",
                                       side_effect=AssertionError("patch ran")), \
                        self.assertRaises(patching.PatchNotApplied):
                    patching.apply(Path(tmp), path)


class Empty(Case):
    def test_an_empty_patch_changes_nothing(self):
        # agents.matrix gives an offline fixer an empty patch; `patch` accepts it and so does apply.
        for text in ("", "\n", "  \n\n"):
            with self.subTest(repr(text)):
                patching.apply(self.work, self.patch_file(text))
                self.assertEqual(sorted(p.name for p in self.work.iterdir()), ["BUG", "keep.txt"])


class Callers(unittest.TestCase):
    """Every helper that puts a candidate or a seed on a copy of the game goes through one rule."""

    def test_shared_helpers_use_apply(self):
        from agents import patchutil
        from harness import run
        from expectrail.gate import known_bench
        seen = []
        with mock.patch.object(patching, "apply", lambda work, patch: seen.append((work, patch))):
            patchutil.apply_patch(Path("w"), Path("a.patch"))
            patchutil.apply_patches(Path("w"), [Path("b.patch")])
            run.apply_patches(Path("w"), [Path("c.patch"), Path("d.patch")])
            known_bench._patch(Path("w"), Path("e.patch"))
        self.assertEqual([p.name for _, p in seen], ["a.patch", "b.patch", "c.patch", "d.patch", "e.patch"])

    def test_no_other_module_runs_patch_on_a_game_copy(self):
        # Left as they are, on purpose:
        # - expectrail/jit/blind.py is pinned by blind set 3's registration; a change would move the pin.
        # - harness/web/run.py patches the web app with the private web patches, which this change cannot
        #   test against; it is not a Godot game copy.
        allowed = {"expectrail/jit/blind.py", "harness/web/run.py"}
        repo = Path(__file__).resolve().parents[1]
        found = []
        for folder in ("expectrail", "agents", "harness", "tools"):
            for path in (repo / folder).rglob("*.py"):
                rel = path.relative_to(repo).as_posix()
                if rel == "harness/patching.py" or rel in allowed:
                    continue
                text = path.read_text(encoding="utf-8")
                for line in text.splitlines():
                    if '["patch", "-p1"' in line and "--dry-run" not in line:
                        found.append(f"{rel}: {line.strip()}")
        self.assertEqual(found, [])


@unittest.skipUnless(_gnu(), "needs GNU patch, which can be put in POSIX mode")
class MacStyleRepair(unittest.TestCase):
    """The three repair assertions macOS failed (#378), with deletions applied the macOS way."""

    def test_fresh_verdicts_hold(self):
        names = [
            "tests.test_visible_repair.RepairTest.test_fresh_verify_uses_patched_bug_and_recorded_answers",
            "tests.test_visible_repair.RepairTest.test_fresh_verdict_overrides_recorded_accept",
            "tests.test_433_remaining.ProviderOnlySample."
            "test_metered_provider_only_record_is_replayed_without_claiming_a_sandboxed_agent",
        ]
        suite = unittest.defaultTestLoader.loadTestsFromNames(names)
        with mock.patch.object(patching.subprocess, "run", _posix_for_deletions(subprocess.run)):
            result = unittest.TestResult()
            suite.run(result)
        self.assertEqual(result.testsRun, 3)
        self.assertEqual([str(t) for t, _ in result.failures + result.errors], [])
        self.assertEqual(result.skipped, [])


if __name__ == "__main__":
    unittest.main()
