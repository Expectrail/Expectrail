"""The section menu on the five front-door pages folds behind a labelled toggle on narrow screens.

The button ships hidden and nav.js reveals it, so without the script the links are always shown. Each page loads the
shared stylesheet and the menu script under a tag made from the file's SHA-256, so a browser holding an older copy
fetches the new one as soon as either file changes.
"""
import hashlib
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ["index.html", "guides.html", "concepts.html", "positioning.html", "quickstart.html"]


def digest(name):
    return hashlib.sha256((ROOT / "docs/assets" / name).read_bytes()).hexdigest()[:10]


class SiteNavTest(unittest.TestCase):
    def test_each_page_has_the_hidden_labelled_toggle_right_before_the_nav(self):
        for page in PAGES:
            html = (ROOT / "docs" / page).read_text(encoding="utf-8")
            with self.subTest(page=page):
                self.assertRegex(html, r'<button class="menu-toggle" type="button" aria-expanded="false" hidden>'
                                       r'.*?<span class="menu-label">Menu</span></button><nav aria-label="Sections">')

    def test_each_page_loads_the_current_stylesheet_and_menu_script(self):
        for page in PAGES:
            html = (ROOT / "docs" / page).read_text(encoding="utf-8")
            with self.subTest(page=page):
                self.assertIn('href="assets/front-door.css?v={}"'.format(digest("front-door.css")), html)
                self.assertIn('<script src="assets/nav.js?v={}" defer></script>'.format(digest("nav.js")), html)

    def test_the_menu_folds_only_after_the_script_runs_and_closes_with_escape(self):
        css = (ROOT / "docs/assets/front-door.css").read_text(encoding="utf-8")
        js = (ROOT / "docs/assets/nav.js").read_text(encoding="utf-8")
        self.assertIn(".top.has-toggle nav{display:none", css)
        self.assertNotRegex(css, r"(?<!has-toggle )nav\{display:none")
        self.assertIn("classList.add('has-toggle')", js)
        self.assertIn("'Escape'", js)
        self.assertIn("aria-expanded", js)


if __name__ == "__main__":
    unittest.main()
