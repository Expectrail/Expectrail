"""A stranger can reach Run it from the front door: the home page and the README link it (#265)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = ROOT / "docs" / "index.html"
README = ROOT / "README.md"
PAGE = ROOT / "docs" / "run-it" / "index.html"


class RunItLinksTest(unittest.TestCase):
    def test_the_page_and_its_script_are_there(self):
        self.assertTrue(PAGE.is_file())
        self.assertIn('<script src="run-it.js"></script>', PAGE.read_text(encoding="utf-8"))
        self.assertTrue((PAGE.parent / "run-it.js").is_file())

    def test_the_home_page_links_run_it_from_the_hero_the_nav_and_the_footer(self):
        html = HOME.read_text(encoding="utf-8")
        hero = html[html.index('<div class="actions">'):html.index('<div class="evidence"')]
        nav = html[html.index('<nav aria-label="Sections">'):html.index("</nav>")]
        footer = html[html.index("<footer>"):]
        for part in (hero, nav, footer):
            self.assertRegex(part, r'<a [^>]*href="run-it/"')

    def test_the_home_page_promises_no_verdict_and_says_where_the_state_is(self):
        html = HOME.read_text(encoding="utf-8")
        note = re.search(r'<p class="try-note">(.*?)</p>', html, re.S).group(1)
        self.assertIn("says whether it can start a run right now", note)
        for word in ("accepted", "accepts", "passes", "works"):
            self.assertNotIn(word, note.lower())

    def test_the_page_does_not_say_answers_were_recorded_before_they_are(self):
        # No sample had a recording when the page was linked from the home page; the intro describes the
        # rule and says what a sample without one gets, and the result of each run says which it was.
        text = PAGE.read_text(encoding="utf-8")
        self.assertNotIn("answers were recorded", text)
        self.assertIn("whose answers are not recorded yet cannot be accepted", text)

    def test_the_readme_links_the_live_page(self):
        self.assertIn("(https://expectrail.tech/run-it/)", README.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
