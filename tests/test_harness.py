import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness.run import (
    DEFAULT_CACHE_DIR,
    REPO,
    apply_patches,
    cache_key,
    ensure_import_cache,
    find_godot,
    get_cache_dir,
    godot_cmd,
    prepare,
    tree_digest,
)


class HarnessTest(unittest.TestCase):
    def test_tree_digest_deterministic_and_ignores_godot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("hello\n", encoding="utf-8")
            (root / "sub").mkdir()
            (root / "sub" / "b.txt").write_text("world\n", encoding="utf-8")
            digest1 = tree_digest(root)

            # Creating a .godot directory must not change the tree digest
            (root / ".godot").mkdir()
            (root / ".godot" / "cache.bin").write_bytes(b"\x00\x01\x02")
            (root / "sub" / ".godot").mkdir()
            (root / "sub" / ".godot" / "other.bin").write_bytes(b"\x99")
            digest2 = tree_digest(root)

            self.assertEqual(digest1, digest2)

    def test_get_cache_dir_default_and_env(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("EXPECTRAIL_GODOT_CACHE", None)  # a developer may have it set
            self.assertEqual(get_cache_dir(), DEFAULT_CACHE_DIR)
        with mock.patch.dict(os.environ, {"EXPECTRAIL_GODOT_CACHE": "/custom/path"}):
            self.assertEqual(get_cache_dir(), Path("/custom/path/.godot"))
        with mock.patch.dict(os.environ, {"EXPECTRAIL_GODOT_CACHE": "/custom/path/.godot"}):
            self.assertEqual(get_cache_dir(), Path("/custom/path/.godot"))

    def test_find_godot_env_override(self):
        with mock.patch.dict(os.environ, {"EXPECTRAIL_GODOT": "/custom/godot"}):
            self.assertEqual(find_godot(), Path("/custom/godot"))

    def test_godot_cmd_display_and_platform(self):
        fake_binary = Path("/bin/godot")
        self.assertEqual(godot_cmd(fake_binary, display=True), [str(fake_binary)])
        with mock.patch("sys.platform", "linux"):
            cmd = godot_cmd(fake_binary, display=False)
            self.assertEqual(cmd[0], "xvfb-run")
            self.assertIn(str(fake_binary), cmd)
        with mock.patch("sys.platform", "darwin"):
            cmd = godot_cmd(fake_binary, display=False)
            self.assertEqual(cmd, [str(fake_binary)])

    def test_prepare_with_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "game"
            work = root / "work"
            cache = root / "cache" / ".godot"

            game.mkdir(parents=True)
            (game / "project.godot").write_text("[application]\nname=\"Test\"\n", encoding="utf-8")

            cache_imported = cache / "imported"
            cache_imported.mkdir(parents=True)
            (cache_imported / "sample.ctex").write_bytes(b"dummy-ctex-data")

            prepare(game, work, cache=cache)

            self.assertTrue((work / "project.godot").is_file())
            self.assertTrue((work / "expectrail_harness.gd").is_file())
            self.assertTrue((work / "expectrail_recorder.gd").is_file())
            self.assertTrue((work / ".godot" / "imported" / "sample.ctex").is_file())
            self.assertIn("ExpectrailHarness", (work / "project.godot").read_text(encoding="utf-8"))

    def _fake_godot_import(self, calls):
        """subprocess.run stand-in: '--import' creates .godot/imported in the target project."""
        def fake(cmd, **kw):
            calls.append(cmd)
            if "--import" in cmd:
                project = Path(cmd[cmd.index("--path") + 1])
                (project / ".godot" / "imported").mkdir(parents=True, exist_ok=True)
                (project / ".godot" / "imported" / "x.ctex").write_bytes(b"ctex")
            return mock.Mock(returncode=0, stdout="", stderr="")
        return fake

    def _game(self, root: Path) -> Path:
        game = root / "game"
        game.mkdir()
        (game / "project.godot").write_text("[application]\nname=\"Test\"\n", encoding="utf-8")
        return game

    def test_import_cache_inside_the_clean_game_is_never_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = self._game(root)
            (game / ".godot" / "imported").mkdir(parents=True)  # e.g. left by the editor
            godot = root / "fake-godot"
            godot.touch()
            calls = []
            with mock.patch.dict(os.environ, {"EXPECTRAIL_GODOT_CACHE": str(root / "cache")}):
                with mock.patch("subprocess.run", side_effect=self._fake_godot_import(calls)):
                    found = ensure_import_cache(game, godot, {})
            self.assertEqual(found, root / "cache" / ".godot")
            self.assertNotEqual(found, game / ".godot")
            self.assertEqual(len([c for c in calls if "--import" in c]), 1)
            self.assertTrue((found / "imported" / "x.ctex").is_file())

    def test_a_cache_is_not_stored_under_a_key_its_copy_does_not_match(self):
        # The key is taken from one reading of the game and the cache is imported from a copy made
        # by a second. If the folder changed in between (and back), a cache built from game B used
        # to be stored under game A's key, and a later replay of A reused it (review of #318).
        from harness import run as hr
        from harness import tree

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = self._game(root)
            (game / "level.tscn").write_text("game A\n", encoding="utf-8")
            godot = root / "fake-godot"
            godot.touch()
            calls = []
            real_copy = tree.copy

            def game_b_for_a_moment(src, dest, **kwargs):
                (game / "level.tscn").write_text("game B\n", encoding="utf-8")
                try:
                    return real_copy(src, dest, **kwargs)
                finally:
                    (game / "level.tscn").write_text("game A\n", encoding="utf-8")

            cache = root / "cache" / ".godot"
            with mock.patch.dict(os.environ, {"EXPECTRAIL_GODOT_CACHE": str(root / "cache")}), \
                    mock.patch("subprocess.run", side_effect=self._fake_godot_import(calls)):
                with mock.patch.object(tree, "copy", side_effect=game_b_for_a_moment), \
                        contextlib.redirect_stderr(io.StringIO()) as said:
                    self.assertIsNone(ensure_import_cache(game, godot, {}))
                self.assertIn("changed while its import cache was being made", said.getvalue())
                self.assertFalse(cache.exists())
                self.assertFalse(hr._key_file(cache).exists())
                self.assertEqual([c for c in calls if "--import" in c], [])   # nothing was imported from game B
                # With the folder still, the same call stores a cache, under the key of what it copied.
                self.assertEqual(ensure_import_cache(game, godot, {}), cache)
                stored = hr._key_file(cache).read_text(encoding="utf-8")
                self.assertEqual(stored.strip(), hr.cache_key(game, godot))
                # A digest the caller took earlier is the one the copy is held to: the folder is
                # game C now, the caller read something else, and the stored cache is left as it was.
                (game / "level.tscn").write_text("game C\n", encoding="utf-8")
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertIsNone(ensure_import_cache(game, godot, {}, game_tree="0" * 64))
                self.assertEqual(hr._key_file(cache).read_text(encoding="utf-8"), stored)
                self.assertEqual(len([c for c in calls if "--import" in c]), 1)

    def test_matching_key_reuses_cache_and_a_changed_game_rewarms_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = self._game(root)
            godot = root / "fake-godot"
            godot.touch()
            calls = []
            with mock.patch.dict(os.environ, {"EXPECTRAIL_GODOT_CACHE": str(root / "cache")}):
                with mock.patch("subprocess.run", side_effect=self._fake_godot_import(calls)):
                    first = ensure_import_cache(game, godot, {})
                    again = ensure_import_cache(game, godot, {})
                    self.assertEqual(len([c for c in calls if "--import" in c]), 1,
                                     "same game + same Godot must reuse the cache")
                    (game / "level.tscn").write_text("changed\n", encoding="utf-8")
                    third = ensure_import_cache(game, godot, {})
                    self.assertEqual(len([c for c in calls if "--import" in c]), 2,
                                     "a changed game must rebuild the cache")
            self.assertEqual(first, again)
            self.assertEqual(third, first)
            self.assertEqual((root / "cache" / ".godot.key").read_text().strip(), cache_key(game, godot))
            leftovers = [p.name for p in (root / "cache").iterdir() if p.name.startswith("staging-")]
            self.assertEqual(leftovers, [], "staging folders must be cleaned up")

    def test_failed_warm_falls_back_to_a_normal_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = self._game(root)
            godot = root / "fake-godot"
            godot.touch()
            boom = subprocess.CalledProcessError(1, ["godot", "--import"])
            with mock.patch.dict(os.environ, {"EXPECTRAIL_GODOT_CACHE": str(root / "cache")}):
                with mock.patch("subprocess.run", side_effect=boom):
                    self.assertIsNone(ensure_import_cache(game, godot, {}))

    def test_run_skips_import_on_clean_cached_run(self):
        from harness.run import run

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = self._game(root)
            route = root / "route.json"
            route.write_text('{"name": "test", "ticks": 10}', encoding="utf-8")
            out = root / "out"
            godot_mock = root / "fake-godot"
            godot_mock.touch()

            calls = []
            fake_import = self._fake_godot_import(calls)

            def fake_subp(cmd, **kw):
                if "--write-movie" in cmd:
                    calls.append(cmd)
                    frames = out / "frames"
                    frames.mkdir(parents=True, exist_ok=True)
                    (frames / "f00000000.png").write_bytes(b"dummy")
                    (out / "trace.json").write_text('{"physicsTicksPerSecond": 60, "rows": []}', encoding="utf-8")
                    return mock.Mock(returncode=0, stdout="Godot Engine v4.7.2 Using Device: test", stderr="")
                return fake_import(cmd, **kw)

            with mock.patch.dict(os.environ, {"EXPECTRAIL_GODOT_CACHE": str(root / "cache")}):
                with mock.patch("subprocess.run", side_effect=fake_subp):
                    ensure_import_cache(game, godot_mock, {})  # warm once
                    calls.clear()
                    # 1. Clean run with a warm, matching cache: no --import
                    run(route, out, game=game, godot=godot_mock)
                    import_calls = [c for c in calls if "--import" in c]
                    self.assertEqual(len(import_calls), 0, "Clean cached run must skip --import")

                    # 2. Force import run: should call --import
                    calls.clear()
                    run(route, out, game=game, godot=godot_mock, force_import=True)
                    import_calls = [c for c in calls if "--import" in c]
                    self.assertEqual(len(import_calls), 1, "force_import must trigger --import")

                    # 3. Patched run: should call --import for incremental check
                    dummy_patch = root / "test.patch"
                    dummy_patch.write_text("", encoding="utf-8")
                    calls.clear()
                    with mock.patch("harness.run.apply_patches"):
                        run(route, out, game=game, godot=godot_mock, patches=[dummy_patch])
                    import_calls = [c for c in calls if "--import" in c]
                    self.assertEqual(len(import_calls), 1, "Patched run must call --import incrementally")

    def test_the_game_never_gets_the_verifiers_secrets(self):
        from harness.run import game_env
        source = {"PATH": "/usr/bin", "HOME": "/home/r", "DISPLAY": ":99", "LC_ALL": "C.UTF-8",
                  "XDG_RUNTIME_DIR": "/run/user/1", "MESA_GL_VERSION_OVERRIDE": "3.3",
                  "MODEL_API_KEY": "sam", "META_API_KEY": "muse", "GITHUB_TOKEN": "gh", "HELDOUT_TOKEN": "h",
                  "EXPECTRAIL_HELDOUT_DIR": "/private", "EXPECTRAIL_SAM_CACHE": "/cache", "AWS_SECRET_ACCESS_KEY": "a",
                  "ACTIONS_RUNTIME_TOKEN": "r", "GITHUB_ENV": "/env"}
        env = game_env(source)
        self.assertEqual(set(env), {"PATH", "HOME", "DISPLAY", "LC_ALL", "XDG_RUNTIME_DIR",
                                    "MESA_GL_VERSION_OVERRIDE", "LIBGL_ALWAYS_SOFTWARE"})
        self.assertEqual(env["LIBGL_ALWAYS_SOFTWARE"], "1")
        self.assertEqual(game_env(dict(source, LIBGL_ALWAYS_SOFTWARE="0"))["LIBGL_ALWAYS_SOFTWARE"], "0")

    def test_every_godot_process_of_a_run_gets_the_scrubbed_environment(self):
        from harness.run import run

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = self._game(root)
            route = root / "route.json"
            route.write_text('{"name": "test", "ticks": 10}', encoding="utf-8")
            out = root / "out"
            godot_mock = root / "fake-godot"
            godot_mock.touch()
            envs = []
            fake_import = self._fake_godot_import([])

            def fake_subp(cmd, **kw):
                envs.append(kw.get("env"))
                if "--write-movie" in cmd:
                    (out / "frames").mkdir(parents=True, exist_ok=True)
                    (out / "frames" / "f00000000.png").write_bytes(b"dummy")
                    (out / "trace.json").write_text('{"physicsTicksPerSecond": 60, "rows": []}', encoding="utf-8")
                    return mock.Mock(returncode=0, stdout="Godot Engine v4.7.2", stderr="")
                return fake_import(cmd, **kw)

            secrets = {"EXPECTRAIL_GODOT_CACHE": str(root / "cache"), "MODEL_API_KEY": "sam-key",
                       "META_API_KEY": "muse-key", "EXPECTRAIL_HELDOUT_DIR": "/private"}
            with mock.patch.dict(os.environ, secrets), mock.patch("subprocess.run", side_effect=fake_subp):
                run(route, out, game=game, godot=godot_mock, force_import=True)
            godot_envs = [e for e in envs if e is not None]
            self.assertGreaterEqual(len(godot_envs), 2)  # the import and the capture
            for env in godot_envs:
                self.assertFalse({"MODEL_API_KEY", "META_API_KEY", "EXPECTRAIL_HELDOUT_DIR"} & set(env), env)

    def test_all_seeded_bug_patches_apply_cleanly(self):
        patches = sorted((REPO / "bugs").glob("*/*.patch"))
        self.assertGreaterEqual(len(patches), 6)
        for patch in patches:
            with self.subTest(patch=patch.name):
                with tempfile.TemporaryDirectory() as tmp:
                    work = Path(tmp) / "game"
                    shutil.copytree(REPO / "game" / "platformer", work, ignore=shutil.ignore_patterns(".godot"))
                    apply_patches(work, [patch])

    def test_all_routes_valid_against_schema(self):
        try:
            import jsonschema  # noqa: F401
            import json
            from expectrail.contracts import validate
        except ImportError:
            self.skipTest("jsonschema not installed")
        routes = sorted((REPO / "harness" / "routes").glob("*.json"))
        self.assertGreaterEqual(len(routes), 1)
        for route_path in routes:
            with self.subTest(route=route_path.name):
                doc = json.loads(route_path.read_text(encoding="utf-8"))
                self.assertEqual(validate(doc), "route")


if __name__ == "__main__":
    unittest.main()

