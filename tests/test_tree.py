"""harness/tree.py: the one definition of what a game folder holds (#303).

Every digest of a game and the copy a replay runs are taken from the same walk, so the property
that matters is held here on real folders: the digest changes exactly when the copy changes.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail.gate import record as rec
from expectrail.gate import verify as gv
from harness import adapters
from harness import run as hr
from harness import sandbox as box
from harness import tree
from tests.test_ci_gate import FakeReplay, make_repo

REPO = Path(__file__).resolve().parent.parent


def old_digest(root: Path, skip: tuple[str, ...]) -> str:
    """The digest as every function computed it before November 12, for a folder with no links."""
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and not set(skip) & set(p.relative_to(root).parts)):
        h.update(path.relative_to(root).as_posix().encode() + b"\0" + hashlib.sha256(path.read_bytes()).hexdigest().encode() + b"\n")
    return h.hexdigest()


def held(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="expectrail-tree-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.checkout = self.tmp / "checkout"
        self.game = self.checkout / "game"
        self.game.mkdir(parents=True)
        (self.game / "project.godot").write_text("[application]\n", encoding="utf-8")
        (self.game / "player.gd").write_text("extends Node\n", encoding="utf-8")

    def write(self, name: str, text: str = "x\n", root: Path | None = None) -> Path:
        path = (self.game if root is None else root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class WalkTest(Case):
    def test_the_copy_holds_exactly_the_files_and_the_digest_of_the_copy_is_the_digest(self):
        self.write("levels/one.tscn")
        self.write("a/y.gd")
        self.write("a-b/x.gd")
        self.write(".godot/imported/cache.bin")
        self.write("addons/.godot/deep.bin")
        self.write(".git/HEAD")
        self.write("addons/tool/.git", "gitdir: elsewhere\n")   # a submodule's marker file
        self.write(".gitignore", ".godot/\n")
        self.write("shared/lvl.tscn", "[shared]\n", root=self.checkout)
        (self.game / "linked").symlink_to(Path("..") / "shared")
        (self.game / "alias.gd").symlink_to("player.gd")
        (self.game / "empty").mkdir()
        listed = tree.files(self.game, within=self.checkout, skip=tree.GODOT_SKIP)
        names = [name for name, _ in listed]
        self.assertEqual(names, [".gitignore", "a/y.gd", "a-b/x.gd", "alias.gd", "levels/one.tscn", "linked/lvl.tscn",
                                 "player.gd", "project.godot"])
        dest = self.tmp / "copy"
        written = tree.copy(self.game, dest, within=self.checkout, skip=tree.GODOT_SKIP)
        self.assertEqual(written, tree.digest(self.game, within=self.checkout, skip=tree.GODOT_SKIP))
        self.assertEqual(held(dest), {name: path.read_bytes() for name, path in listed})
        self.assertFalse(any(p.is_symlink() for p in dest.rglob("*")))   # plain files: nothing in the copy leads out
        self.assertEqual(tree.digest(dest), tree.digest(self.game, within=self.checkout, skip=tree.GODOT_SKIP))

    def test_the_digest_changes_exactly_when_the_copy_changes(self):
        self.write("shared/lvl.tscn", "[shared]\n", root=self.checkout)
        (self.game / "linked").symlink_to(Path("..") / "shared")
        places = {"player.gd": True, "levels/one.tscn": True, "__pycache__/x.pyc": True, ".expectrail/out.json": True,
                  "addons/tool/plugin.gd": True, ".godot/imported/x.bin": False, "deep/.godot/y.bin": False,
                  ".git/index": False, "deep/.git/config": False}

        def state() -> tuple[dict, str]:
            dest = self.tmp / "copy"
            shutil.rmtree(dest, ignore_errors=True)
            tree.copy(self.game, dest, within=self.checkout, skip=tree.GODOT_SKIP)
            return held(dest), tree.digest(self.game, within=self.checkout, skip=tree.GODOT_SKIP)

        for name in places:
            self.write(name, "one\n")
        for name, part_of_the_game in places.items():
            with self.subTest(changed=name):
                copy, digest = state()
                self.write(name, "two\n")
                new_copy, new_digest = state()
                self.assertEqual(new_copy != copy, part_of_the_game)
                self.assertEqual(new_digest != digest, new_copy != copy)
        with self.subTest(changed="a file behind the linked folder"):
            copy, digest = state()
            self.write("shared/lvl.tscn", "[changed]\n", root=self.checkout)
            new_copy, new_digest = state()
            self.assertTrue(new_copy != copy and new_digest != digest)
        with self.subTest(changed="a file added, then renamed"):
            copy, digest = state()
            self.write("new.gd")
            added = state()
            (self.game / "new.gd").rename(self.game / "renamed.gd")
            renamed = state()
            self.assertEqual(len({digest, added[1], renamed[1]}), 3)

    def test_what_cannot_be_described_is_a_problem_and_nothing_is_copied(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("not the game's", encoding="utf-8")

        def fifo(path):
            os.mkfifo(path)

        cases = (("a folder outside", lambda p: p.symlink_to(outside), "leaves the checkout"),
                 ("a file outside", lambda p: p.symlink_to(outside / "secret.txt"), "leaves the checkout"),
                 ("up and out", lambda p: p.symlink_to(Path("..") / ".." / ".." / "outside"), "leaves the checkout"),
                 ("a loop", lambda p: p.symlink_to("."), "loops back"),
                 ("nothing", lambda p: p.symlink_to(self.checkout / "absent"), "a link to nothing"),
                 ("a pipe", fifo, "not a file, a folder or a link"))
        for label, make, words in cases:
            with self.subTest(label):
                entry = self.game / "sub" / "entry"
                entry.parent.mkdir(exist_ok=True)
                make(entry)
                self.addCleanup(lambda e=entry: e.unlink() if e.is_symlink() or e.exists() else None)
                for use in (tree.files, tree.digest):
                    with self.assertRaisesRegex(tree.TreeProblem, f"sub/entry is .*{words}"):
                        use(self.game, within=self.checkout, skip=tree.GODOT_SKIP)
                dest = self.tmp / "copy"
                with self.assertRaises(tree.TreeProblem):
                    tree.copy(self.game, dest, within=self.checkout, skip=tree.GODOT_SKIP)
                self.assertFalse(dest.exists())
                entry.unlink()
        self.assertEqual((outside / "secret.txt").read_text(), "not the game's")

    def test_without_a_checkout_a_link_may_not_leave_the_game_folder(self):
        self.write("shared/lvl.tscn", root=self.checkout)
        (self.game / "linked").symlink_to(Path("..") / "shared")
        with self.assertRaisesRegex(tree.TreeProblem, "linked is a link that leaves the game folder"):
            tree.digest(self.game, skip=tree.GODOT_SKIP)
        self.assertIn("linked/lvl.tscn", [n for n, _ in tree.files(self.game, within=self.checkout)])

    def test_the_order_does_not_depend_on_how_the_folder_is_listed(self):
        for name in ("b/1.gd", "a/2.gd", "a-b/3.gd", "a.b/4.gd", "A/5.gd", "a/b/6.gd", "ab.gd"):
            self.write(name)
        names = [n for n, _ in tree.files(self.game)]
        self.assertEqual(names, sorted(names, key=lambda n: n.split("/")))
        real = os.scandir

        def backwards(folder):
            with real(folder) as entries:
                return _Listing(sorted(entries, key=lambda e: e.name, reverse=True))

        with mock.patch.object(tree.os, "scandir", side_effect=backwards):
            self.assertEqual([n for n, _ in tree.files(self.game)], names)


class _Listing(list):
    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class OneDefinitionTest(Case):
    """Every digest of a game is this walk, and the bundled games' digests are what they were."""

    def test_the_bundled_games_keep_the_digests_they_had(self):
        for adapter, skip in ((adapters.GODOT, (".godot",)), (adapters.UNITY, adapters.UNITY_IGNORE)):
            with self.subTest(adapter=adapter.name):
                root = adapter.game_root
                self.assertEqual([p for p in root.rglob("*") if p.is_symlink()], [])
                self.assertEqual(adapter.tree_digest(), old_digest(root, skip))
        game = REPO / "game" / "platformer"
        self.assertEqual(hr.tree_digest(game), old_digest(game, (".godot",)))
        self.assertEqual(gv.game_tree(game, REPO), old_digest(game, (".godot", ".git", ".expectrail")))

    def test_the_harness_the_gate_the_adapter_and_the_orchestrator_name_a_game_the_same_way(self):
        from expectrail.orchestrator import request as req

        self.write("levels/one.tscn")
        self.write("a-b/x.gd")
        self.write("a/y.gd")
        self.write("shared/lvl.tscn", root=self.checkout)
        (self.game / "linked").symlink_to(Path("..") / "shared")
        expected = tree.digest(self.game, within=self.checkout, skip=tree.GODOT_SKIP)
        self.assertEqual(hr.tree_digest(self.game, self.checkout), expected)
        self.assertEqual(gv.game_tree(self.game, self.checkout), expected)
        self.assertEqual(req.tree_digest(self.game, self.checkout), expected)
        (self.game / "linked").unlink()
        self.assertEqual(adapters.GODOT.tree_digest(self.game), hr.tree_digest(self.game))

    def test_the_work_copy_and_the_import_cache_are_made_from_the_same_files(self):
        self.write("levels/one.tscn")
        self.write(".git/HEAD")
        self.write(".godot/imported/stale.bin")
        self.write("shared/lvl.tscn", root=self.checkout)
        (self.game / "linked").symlink_to(Path("..") / "shared")
        work = self.tmp / "work"
        hr.prepare(self.game, work, within=self.checkout)
        mine = {"expectrail_harness.gd", "expectrail_recorder.gd"}
        copied = {name for name in held(work) if name not in mine}
        self.assertEqual(copied, {name for name, _ in tree.files(self.game, within=self.checkout, skip=tree.GODOT_SKIP)})
        self.assertFalse((work / ".git").exists() or (work / ".godot").exists())

    def test_the_copy_reports_the_bytes_it_wrote_not_a_later_reading(self):
        # The file changes after the copy read it: the digest the copy returns still describes the
        # copy, and no longer the folder.
        before = tree.digest(self.game, skip=tree.GODOT_SKIP)
        dest = self.tmp / "copy"
        written = tree.copy(self.game, dest, skip=tree.GODOT_SKIP)
        (self.game / "player.gd").write_text("extends Node\n# changed afterwards\n", encoding="utf-8")
        self.assertEqual(written, before)
        self.assertEqual(written, tree.digest(dest))
        self.assertNotEqual(written, tree.digest(self.game, skip=tree.GODOT_SKIP))

    def test_a_replay_stops_when_the_game_changes_between_its_first_read_and_its_copy(self):
        route = self.tmp / "route.json"
        route.write_text(json.dumps({"format": "expectrail.route/v0", "name": "t", "seed": 1, "steps": []}), encoding="utf-8")
        godot = self.tmp / "godot"
        godot.write_bytes(b"not an engine")

        def change_the_game(*args, **kwargs):
            (self.game / "player.gd").write_text("extends Node\n# swapped in after the digest\n", encoding="utf-8")
            return None   # no import cache

        with mock.patch.object(box, "probe", return_value=(None, "no sandbox in this test")), \
                mock.patch.object(hr, "ensure_import_cache", side_effect=change_the_game), \
                mock.patch.object(hr.subprocess, "run", side_effect=AssertionError("the game was started")), \
                self.assertRaisesRegex(SystemExit, "changed while the replay was being set up"):
            hr.run(route, self.tmp / "run", game=self.game, godot=godot, within=self.checkout)
        self.assertFalse((self.tmp / "run" / "work").exists())
        self.assertFalse((self.tmp / "run" / "replay.json").exists())

    def test_a_replay_stops_before_copying_a_game_with_a_link_that_leaves(self):
        (self.tmp / "outside").mkdir()
        (self.game / "out").symlink_to(self.tmp / "outside")
        route = self.tmp / "route.json"
        route.write_text(json.dumps({"format": "expectrail.route/v0", "name": "t", "seed": 1, "steps": []}), encoding="utf-8")
        godot = self.tmp / "godot"
        godot.write_bytes(b"not an engine")
        with mock.patch.object(box, "probe", return_value=(None, "no sandbox in this test")), \
                mock.patch.object(hr.subprocess, "run", side_effect=AssertionError("the game was started")), \
                self.assertRaisesRegex(SystemExit, "cannot be replayed as it stands: out is a link that leaves the checkout"):
            hr.run(route, self.tmp / "run", game=self.game, godot=godot, within=self.checkout)
        self.assertFalse((self.tmp / "run" / "work").exists())


class GateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="expectrail-tree-gate-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.replay = FakeReplay()

    def gate(self, repo: Path, **kwargs) -> dict:
        with contextlib.redirect_stdout(io.StringIO()):
            return gv.run_gate(repo=repo, game="game/platformer", routes=["routes/*.json"], specs="specs",
                               out=kwargs.pop("out", self.tmp / "out"), work=kwargs.pop("work", self.tmp / "work"),
                               replay=self.replay, **kwargs)

    def test_a_game_with_a_link_that_leaves_its_checkout_is_not_replayed(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        for side in ("head", "base"):
            with self.subTest(side=side):
                head, base = make_repo(self.tmp / side / "head"), make_repo(self.tmp / side / "base")
                ((head if side == "head" else base) / "game" / "platformer" / "assets").symlink_to(outside)
                self.replay = FakeReplay()
                with self.assertRaisesRegex(gv.ConfigError, f"the {side} game cannot be verified as it stands: assets is a link that leaves the checkout"):
                    self.gate(head, base=base)
                self.assertEqual(self.replay.calls, [])
        head = make_repo(self.tmp / "cli" / "head")
        (head / "game" / "platformer" / "assets").symlink_to(outside)
        with contextlib.redirect_stdout(io.StringIO()):
            code = gv.main(["--repo", str(head), "--game", "game/platformer", "--routes", "routes/*.json", "--specs", "specs",
                            "--out", str(self.tmp / "cli-out")])
        doc = rec.read_record(self.tmp / "cli-out" / "findings.json")
        self.assertEqual((code, doc["decision"], doc["checks"], doc["game"]["headTree"]), (2, "needs-review", [], None))
        self.assertIn("assets is a link that leaves the checkout", doc["reasons"][0])

    def test_a_replay_of_another_tree_than_the_record_names_is_not_used(self):
        class Honest(FakeReplay):
            """Says which tree it ran, as the harness does, and can change the game first."""

            def __init__(self, change=None):
                super().__init__()
                self.change = change

            def __call__(self, route, game, out, frames):
                if self.change is not None and not self.calls:
                    self.change(game)
                run = super().__call__(route, game, out, frames)
                return {**run, "tree": tree.digest(game, skip=tree.GODOT_SKIP)}

        # Unchanged: each replay names the record's tree and the gate decides as it did.
        self.replay = Honest()
        record = self.gate(make_repo(self.tmp / "still"))
        self.assertEqual((record["decision"], {c["after"] for c in record["checks"]}), ("accept", {"pass"}))
        # Changed after the gate read it: the game would pass, and no replay of it is used.
        self.replay = Honest(lambda game: (game / "swapped.gd").write_text("# after the gate's read\n", encoding="utf-8"))
        repo = make_repo(self.tmp / "moved")
        before = gv.game_tree(repo / "game" / "platformer", repo)
        record = self.gate(repo, out=self.tmp / "out2", work=self.tmp / "work2")
        self.assertEqual(record["game"]["headTree"], before)
        self.assertTrue(self.replay.calls)
        self.assertEqual({c["after"] for c in record["checks"]}, {"replay-error"})
        self.assertEqual({f["reason"] for f in record["findings"]}, {"the head game changed while it was being verified"})
        self.assertEqual(record["decision"], "needs-review")

    def test_the_harness_replay_reports_the_tree_its_copy_was_made_from(self):
        out = self.tmp / "run"
        out.mkdir()
        (out / "trace.json").write_text("{}", encoding="utf-8")
        (out / "replay.json").write_text("{}", encoding="utf-8")
        with mock.patch("harness.run.run", return_value={"game": {"tree": "ab" * 32}, "isolation": None}):
            run = gv.harness_replay(self.tmp / "route.json", self.tmp, out, False)
        self.assertEqual(run["tree"], "ab" * 32)

    def test_a_link_inside_the_checkout_is_part_of_the_tree_the_record_names(self):
        head = make_repo(self.tmp / "head")
        (head / "shared").mkdir()
        (head / "shared" / "lvl.tscn").write_text("[one]\n", encoding="utf-8")
        (head / "game" / "platformer" / "linked").symlink_to(Path("..") / ".." / "shared")
        first = self.gate(head)
        self.assertEqual(first["decision"], "accept")
        self.assertEqual(first["game"]["headTree"], hr.tree_digest(head / "game" / "platformer", head))
        (head / "shared" / "lvl.tscn").write_text("[two]\n", encoding="utf-8")
        second = self.gate(head, out=self.tmp / "out2", work=self.tmp / "work2")
        self.assertNotEqual(second["game"]["headTree"], first["game"]["headTree"])

    def test_the_gates_own_folders_may_not_be_inside_the_game(self):
        head = make_repo(self.tmp / "head")
        game = head / "game" / "platformer"
        for label, kwargs in (("output", dict(out=game / "expectrail-out")), ("work", dict(work=game / "w")),
                              ("output", dict(out=game))):
            with self.subTest(**{k: str(v.relative_to(head)) for k, v in kwargs.items()}), \
                    self.assertRaisesRegex(gv.ConfigError, f"the {label} folder is inside the head game folder"):
                self.gate(head, **kwargs)
        self.assertEqual(self.replay.calls, [])
        self.assertEqual(sorted(p.name for p in game.iterdir()), sorted(p.name for p in (make_repo(self.tmp / "ref") / "game" / "platformer").iterdir()))

    def test_version_control_inside_the_game_is_not_the_game(self):
        head = make_repo(self.tmp / "head")
        game = head / "game" / "platformer"
        before = self.gate(head)["game"]["headTree"]
        (game / ".git").mkdir()
        (game / ".git" / "index").write_text("changes on every command", encoding="utf-8")
        after = self.gate(head, out=self.tmp / "out2", work=self.tmp / "work2")["game"]["headTree"]
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
