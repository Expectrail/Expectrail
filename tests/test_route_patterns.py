"""Route patterns: the gate's own matcher (``expectrail.gate.verify.pattern_matches``).

The files a pattern names decide which routes judge a change, so they may not depend on the Python
that runs the gate. ``Path.glob`` does: a pattern that ends in ``**`` gives the files below on
Python 3.13 and none of them on 3.12. This module imports the standard library only, so it runs on
every Python the package supports without the development requirements.
"""
from __future__ import annotations

import hashlib
import itertools
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from expectrail.gate import verify as gv
from expectrail.orchestrator import request as req

FILES = ("runs/jobs/abc/request.json", "runs/jobs/abc/status.json", "runs/jobs/keys/k.json",
         "runs/jobs/abc/output/findings.json", "runs/other.json", "routes/smoke.json", "routes/.hidden.json",
         "routes/Sub/deep/x.json", "top.json", "real/c.json", ".dot/d.json")
# test_every_python_finds_the_same_files: (patterns, patterns that find a file) and the digest.
GENERATED = (39526, 1556)
GENERATED_DIGEST = "03c5392e69ed8d6ea6b87d4372cba47a6c0c90f6abc3361f9df061256fbfa8ca"


class RoutePatternTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="expectrail-patterns-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "tree"
        for name in FILES:
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text("{}", encoding="utf-8")
        (self.tmp / "outside").mkdir()
        (self.tmp / "outside" / "o.json").write_text("{}", encoding="utf-8")
        os.symlink("../real", self.root / "routes" / "link")             # a link to a folder
        os.symlink("smoke.json", self.root / "routes" / "alias.json")    # a link to a file
        os.symlink("nowhere", self.root / "routes" / "dangling.json")    # a link to nothing
        os.symlink("..", self.root / "runs" / "up")                      # a loop
        os.symlink("../../outside", self.root / "routes" / "out")        # a link that leaves the checkout

    def files(self, pattern: str) -> list[str]:
        return sorted(p.relative_to(self.root).as_posix() for p in gv.pattern_matches(self.root, pattern) if p.is_file())

    def routes(self, *patterns: str) -> list[str]:
        return [p.relative_to(self.root).as_posix() for p in gv.find_routes(self.root, list(patterns))]

    def test_a_pattern_that_ends_in_two_stars_finds_the_files_below(self):
        # The case that differed: no route at all on Python 3.12, these on 3.13.
        self.assertEqual(self.routes("routes/**"), ["routes/.hidden.json", "routes/Sub/deep/x.json", "routes/smoke.json"])
        self.assertEqual(self.routes("routes/Sub/**"), ["routes/Sub/deep/x.json"])
        self.assertEqual(self.routes("**"), sorted(FILES))

    def test_what_each_pattern_finds(self):
        for pattern, expected in (
                ("routes/*.json", ["routes/.hidden.json", "routes/smoke.json"]),
                ("routes/**/*.json", ["routes/.hidden.json", "routes/Sub/deep/x.json", "routes/smoke.json"]),
                ("**/x.json", ["routes/Sub/deep/x.json"]),
                ("**/**/x.json", ["routes/Sub/deep/x.json"]),
                ("*.json", ["top.json"]),
                ("./routes//smoke.json", ["routes/smoke.json"]),
                ("r*/[st]*.json", ["routes/smoke.json"]),
                ("routes/?moke.json", ["routes/smoke.json"]),
                ("routes/[!s]*.json", ["routes/.hidden.json"]),
                (".*/*.json", [".dot/d.json"]),
                # The case of a name counts, on every file system.
                ("routes/sub/**", []), ("ROUTES/*.json", []), ("routes/Smoke.json", []),
                # A part that is not "**" may name a link to a folder and go on below it.
                ("routes/link/*.json", ["routes/link/c.json"]), ("routes/*/c.json", ["routes/link/c.json"]),
                # "**" never passes through one: real/c.json is found where it is, not through the link.
                ("**/c.json", ["real/c.json"]), ("routes/**/c.json", []),
                # Nothing to find.
                ("", []), (".", []), ("nothing/**", []), ("top.json/more", [])):
            with self.subTest(pattern=pattern):
                self.assertEqual(self.routes(pattern), expected)

    def test_a_route_is_a_regular_file_inside_the_checkout(self):
        # The matcher names a link to a file and a file through a link that leaves the checkout;
        # the routes are neither.
        self.assertEqual(self.files("routes/*.json"), ["routes/.hidden.json", "routes/alias.json", "routes/smoke.json"])
        self.assertEqual(self.routes("routes/*.json"), ["routes/.hidden.json", "routes/smoke.json"])
        self.assertEqual(self.files("routes/out/*.json"), ["routes/out/o.json"])
        self.assertEqual(self.routes("routes/out/*.json", "routes/dangling.json", "routes/alias.json"), [])
        self.assertEqual(self.routes("routes/link/*.json"), ["routes/link/c.json"])

    def test_a_loop_of_links_ends(self):
        # runs/up leads back to the checkout. A part that names it goes round once per part, and
        # "**" does not enter it.
        self.assertEqual(self.files("runs/up/runs/up/top.json"), ["runs/up/runs/up/top.json"])
        self.assertIn("runs/up/routes/smoke.json", self.files("*/*/*/*"))
        self.assertIn("runs/up/runs/up/runs/other.json", self.files("*/*/*/*/*/*"))
        everything = self.files("**/*.json")
        self.assertIn("runs/other.json", everything)
        self.assertEqual([name for name in everything if "up" in name.split("/")], [])

    def test_folders_nested_deeper_than_python_nests_calls(self):
        depth = sys.getrecursionlimit() + 200
        folders = [self.root / "deep"]
        for _ in range(depth):
            folders.append(folders[-1] / "d")
        for folder in folders:
            os.mkdir(folder)
        bottom = folders[-1] / "x.json"
        bottom.write_text("{}", encoding="utf-8")

        def remove():   # by hand: shutil.rmtree nests a call for every folder on some Pythons
            bottom.unlink(missing_ok=True)
            for folder in reversed(folders):
                os.rmdir(folder)
        self.addCleanup(remove)
        self.assertEqual(gv.find_routes(self.root, ["deep/**/x.json"]), [bottom])
        self.assertEqual(gv.find_routes(self.root, ["deep/**"]), [bottom])

    def generated(self):
        """(pattern, the files the matcher finds), over two generated sets: ordinary parts with the
        links of the tree above, and odd ones (brackets that do not close, stars inside a name)."""
        for name in ("a[b/x.json", "r]/y.json", "[]/z.json", "-/dash.json", "odd/a-b.json", "odd/!x.json", "odd/[x].json"):
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text("{}", encoding="utf-8")
        ordinary = ("**", "*", "r*", "*.json", "?obs", "[rj]*", "[S-s]uns", "[!R]uns", "runs", "jobs", "routes", "link",
                    "up", "out", "abc", "request.json", ".*", "Sub", "sub")
        odd = ("**", "*", "a[b", "[]", "[!]", "[!]]*", "[]r]*", "***", "r**", "**s", "[a-]*", "[!-]*", "[--r]*", "r]", "*[",
               "?", "x.json", "odd", "[x].json", "[[]x].json", "*.json", "o*", "[r", "[!r]*", "[^r]*", "[a-", "[z-a]*")
        for parts, lengths, step in ((ordinary, (1, 2, 3, 4), 11), (odd, (1, 2, 3), 1)):
            for length in lengths:
                combos = itertools.product(parts, repeat=length)
                if length == 4:
                    combos = itertools.islice(combos, 0, None, step)   # one in eleven of the longest
                for combo in combos:
                    pattern = "/".join(combo)
                    yield pattern, {p for p in gv.pattern_matches(self.root, pattern) if p.is_file()}

    def test_every_python_finds_the_same_files(self):
        # One digest of every generated pattern and what it finds, recorded on Python 3.13 and held
        # on every Python: no branch on the version, so a difference on any of them fails here.
        h = hashlib.sha256()
        patterns = finds = 0
        for pattern, found in self.generated():
            names = sorted(p.relative_to(self.root).as_posix() for p in found)
            h.update(pattern.encode() + b"\0" + "\0".join(names).encode() + b"\n")
            patterns += 1
            finds += bool(names)
        self.assertEqual((patterns, finds), GENERATED)
        self.assertEqual(h.hexdigest(), GENERATED_DIGEST)

    def test_the_same_as_path_glob_where_path_glob_can_be_asked(self):
        # The matcher against Path.glob, pattern by pattern. On Python 3.13, the Python every run so
        # far was made on, that is all of them. On 3.12 Path.glob refuses "**" inside a longer part
        # and gives a last "**" no file: those are counted and left out there, and the digest above
        # holds them to what 3.13 finds.
        current = sys.version_info >= (3, 13)
        compared = left_out = 0
        for pattern, found in self.generated():
            try:
                theirs = {p for p in self.root.glob(pattern) if p.is_file()}
            except ValueError:
                self.assertFalse(current, pattern)
                left_out += 1
                continue
            if not current and pattern.rsplit("/", 1)[-1] == "**":
                left_out += 1
                continue
            self.assertEqual(found, theirs, pattern)
            compared += 1
        self.assertEqual(compared + left_out, GENERATED[0])
        if current:
            self.assertEqual(left_out, 0)
        self.assertGreater(compared, 25000, (compared, left_out))

    def test_no_pattern_that_finds_a_file_below_a_folder_is_said_not_to_reach_it(self):
        # The orchestrator keeps its jobs folder out of where routes are looked for with
        # pattern_reaches, which errs towards yes. Held against the matcher that finds the routes.
        below = (self.root / "runs" / "jobs").resolve()
        parts = ("**", "*", "r*", "*.json", "?obs", "[rj]*", "[S-s]uns", "[Z-s]*", "[!R]uns", "[!A-Z]*", "runs", "jobs",
                 "abc", "request.json", "routes")
        matched = 0
        for length in (1, 2, 3):
            for combo in itertools.product(parts, repeat=length):
                pattern = "/".join(combo)
                if any(below in found.resolve().parents for found in gv.find_routes(self.root, [pattern])):
                    matched += 1
                    self.assertTrue(req.pattern_reaches(pattern, "runs/jobs"), pattern)
        self.assertGreater(matched, 100, matched)


if __name__ == "__main__":
    unittest.main()
