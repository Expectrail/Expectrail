"""The work log's entries (docs/new-work/): one file per change, so pull requests never conflict over it."""
from __future__ import annotations

import unittest
from pathlib import Path

from tools import merge_guard as mg

FOLDER = Path(__file__).resolve().parent.parent / "docs" / "new-work"


class EntriesTest(unittest.TestCase):
    def test_every_file_is_an_entry_the_guard_would_accept(self):
        entries = sorted(p for p in FOLDER.iterdir() if p.name != "README.md")
        self.assertTrue(entries, "the folder holds at least the entry that introduced it")
        for path in entries:
            with self.subTest(entry=path.name):
                self.assertTrue(mg.is_entry(f"docs/new-work/{path.name}"), "name it YYYY-MM-DD-short-name.md")
                text = path.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("# "), "the first line says what changed")
                for section in ("## What changed", "## What was run", "## Files"):
                    self.assertIn(section, text)

    def test_the_readme_shows_the_layout_the_guard_asks_for(self):
        text = (FOLDER / "README.md").read_text(encoding="utf-8")
        for needed in ("YYYY-MM-DD-short-name.md", "## What was run", "tools.merge_guard"):
            self.assertIn(needed, text)


if __name__ == "__main__":
    unittest.main()
