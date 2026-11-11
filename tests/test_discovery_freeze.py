"""The discovery freeze: any change to a file that decides a finding breaks it."""
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail.discovery import freeze
from tests import submission_commit

REPO = Path(__file__).resolve().parents[1]
FREEZE_TWO = "9af1f621c33ce4668eb8ad356a3220ea352d106595b0bc1b4cf877eead5e3053"


class FreezeTwoRecord(unittest.TestCase):
    """Freeze 2 was retired on November 9, 2026, after set 2's blind runs were recorded
    (docs/discovery.md, Set 2: blind runs 3 and 4). Discovery may change on main again; the record
    stays, and must still describe the code at commit c169a5e, the baseline, where those
    runs can be reproduced. A new blind claim needs a new freeze and a new fresh set first."""

    def test_the_record_is_kept(self):
        import json
        record = json.loads((REPO / freeze.FREEZE).read_text())
        self.assertEqual(record["sha256"], FREEZE_TWO)

    @unittest.skipUnless(submission_commit.available(), "the submission commit is not fetched (CI fetches it)")
    def test_the_record_holds_at_the_submission(self):
        root = submission_commit.extract([*freeze.FROZEN, freeze.GAME, freeze.FREEZE.as_posix()])
        ok, problems, digest = freeze.verify(root)
        self.assertTrue(ok, f"freeze 2 no longer describes the code at the submission commit: {problems}")
        self.assertEqual(digest, FREEZE_TWO)


class ReadersAreNotSentToAFailingCommand(unittest.TestCase):
    """Found by the nightly platform test (#288): the README's "Try it" block listed
    `python3 -m expectrail.discovery.freeze verify` as a step, and it exits 1 on main, because
    freeze 2 describes the baseline commit. While the working tree does not match the record, the
    pages a newcomer follows may name the command only with `--root`, pointed at a baseline checkout."""

    PAGES = ("README.md", "discovery/README.md")
    COMMAND = "expectrail.discovery.freeze verify"

    @classmethod
    def bare(cls, text: str) -> list[str]:
        """Each mention of the command that is not followed by `--root` before its code ends."""
        found = []
        for line in text.splitlines():
            start = 0
            while (at := line.find(cls.COMMAND, start)) != -1:
                start = at + len(cls.COMMAND)
                rest = line[start:].split("`", 1)[0].split("#", 1)[0]
                if not rest.strip().startswith("--root "):
                    found.append(line.strip())
        return found

    def test_a_bare_command_is_seen_and_one_with_a_root_is_not(self):
        self.assertEqual(self.bare("python3 -m expectrail.discovery.freeze verify   # frozen"),
                         ["python3 -m expectrail.discovery.freeze verify   # frozen"])
        self.assertEqual(len(self.bare("run `python -m expectrail.discovery.freeze verify`, then --root x")), 1)
        self.assertEqual(len(self.bare("python3 -m expectrail.discovery.freeze verify # --root runs/baseline")), 1)
        self.assertEqual(self.bare("python3 -m expectrail.discovery.freeze verify --root runs/baseline  # holds"), [])
        self.assertEqual(self.bare("`python -m expectrail.discovery.freeze verify --root runs/baseline`."), [])

    def test_the_pages_name_the_command(self):
        for page in self.PAGES:
            self.assertIn(self.COMMAND, (REPO / page).read_text(encoding="utf-8"), page)

    def test_no_page_presents_the_command_where_it_fails(self):
        ok, problems, _ = freeze.verify(REPO)
        if ok:
            self.skipTest("the working tree matches freeze 2, so the bare command passes here")
        for page in self.PAGES:
            lines = self.bare((REPO / page).read_text(encoding="utf-8"))
            if page == "discovery/README.md":   # it may say that the bare command exits 1 on main
                lines = [line for line in lines if "exits" not in line]
            self.assertEqual(lines, [], f"{page} names a command that exits 1 on this checkout: {problems}")

    @unittest.skipUnless(submission_commit.available(), "the submission commit is not fetched (CI fetches it)")
    def test_the_command_the_pages_give_holds_on_a_baseline_worktree(self):
        import subprocess
        parent = Path(tempfile.mkdtemp(prefix="expectrail-baseline-"))
        tree = parent / "baseline"
        subprocess.run(["git", "-C", str(REPO), "worktree", "add", "--detach", str(tree), submission_commit.COMMIT],
                       check=True, capture_output=True)
        try:
            self.assertEqual(freeze.main(["verify", "--root", str(tree)]), 0)
        finally:
            subprocess.run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(tree)],
                           check=True, capture_output=True)
            shutil.rmtree(parent, ignore_errors=True)


class FreezeOne(unittest.TestCase):
    def test_freeze_one_is_kept_and_differs_only_in_the_planner_request(self):
        import json
        one = json.loads((REPO / "discovery" / "freeze-1.json").read_text())
        two = json.loads((REPO / "discovery" / "freeze.json").read_text())
        self.assertEqual(one["sha256"], "6e9ca2bda1c0cf3d0d491ae411bbeb54e18c6701ebd1ed6274c742c02a644824")
        changed = sorted(f for f in one["files"] if one["files"][f] != two["files"].get(f))
        self.assertEqual(changed, ["expectrail/discovery/planner.py"])
        self.assertEqual(one["gameTree"], two["gameTree"])


class Freeze(unittest.TestCase):
    def copy(self):
        root = Path(tempfile.mkdtemp())
        for f in freeze.FROZEN:
            (root / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(REPO / f, root / f)
        (root / freeze.GAME / "player").mkdir(parents=True)
        (root / freeze.GAME / "player" / "player.gd").write_text("extends Node\n")
        (root / "discovery").mkdir(exist_ok=True)
        self.assertEqual(freeze.main(["write", "--root", str(root)]), 0)
        return root

    def test_an_untouched_checkout_verifies(self):
        ok, problems, digest = freeze.verify(self.copy())
        self.assertTrue(ok, problems)
        self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_a_changed_rule_or_game_breaks_it(self):
        root = self.copy()
        (root / "expectrail/discovery/templates.py").write_text("# tuned after the defects were written\n")
        (root / freeze.GAME / "player" / "player.gd").write_text("extends Node2D\n")
        ok, problems, _ = freeze.verify(root)
        self.assertFalse(ok)
        self.assertIn("expectrail/discovery/templates.py changed", problems)
        self.assertIn("game/platformer changed", problems)

    def test_the_digest_covers_its_own_record(self):
        root = self.copy()
        path = root / freeze.FREEZE
        path.write_text(path.read_text().replace('"command": "python', '"command": "python3'))
        ok, problems, _ = freeze.verify(root)
        self.assertFalse(ok)
        self.assertIn("the blind command changed", problems)


if __name__ == "__main__":
    unittest.main()
