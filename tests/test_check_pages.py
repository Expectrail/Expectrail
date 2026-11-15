"""agents.check_pages: a page that is broken in a browser fails, and a working one passes.

Needs Playwright and Chromium (requirements-web.txt), as CI's web-capture job has; skipped elsewhere.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - the test job installs no browser
    sync_playwright = None

from agents.check_pages import check

GOOD = """<!DOCTYPE html><html><head><title>ok</title></head><body>
<select id="pick" onchange="show(this.value)"><option value="a">A</option><option value="b">B</option></select>
<p id="out"></p><a href="review/">review</a> <a href="https://example.com/">outside</a> <a href="#top">top</a>
<script>let shown = 0; function show(v) { shown += 1; document.getElementById('out').textContent = v; }</script>
</body></html>"""


def _site(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return root


class CheckPagesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.tool_requirements import require_tool
        require_tool('Playwright Chromium')
        cls.manager = sync_playwright().start()
        cls.addClassCleanup(cls.manager.stop)
        cls.browser = cls.manager.chromium.launch()
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def run_check(self, files: dict[str, str]) -> list[dict]:
        return check(_site(self.root, files), offline=True, browser=self.browser)

    def test_a_working_page_passes(self):
        self.assertEqual(self.run_check({"index.html": GOOD, "review/index.html": "<p>review</p>"}), [])

    def test_a_syntax_error_that_stops_the_script_fails(self):
        page = GOOD.replace("let shown = 0;", "let shown = 0; let shown = 1;")
        found = self.run_check({"index.html": page, "review/index.html": "<p>review</p>"})
        self.assertIn("script error", {f["what"] for f in found})
        self.assertTrue(any("already been declared" in f["detail"] for f in found))

    def test_an_error_raised_only_when_an_option_is_chosen_fails(self):
        page = GOOD.replace("shown += 1;", "if (v === 'b') { throw new Error('case b is broken'); } shown += 1;")
        found = self.run_check({"index.html": page, "review/index.html": "<p>review</p>"})
        self.assertEqual([(f["what"], "case b is broken" in f["detail"]) for f in found], [("script error", True)])

    def test_a_file_the_page_asks_for_that_is_not_there_fails(self):
        page = GOOD.replace("<p id=\"out\"></p>", "<p id=\"out\"></p><img src=\"assets/frame.png\">")
        found = self.run_check({"index.html": page, "review/index.html": "<p>review</p>"})
        self.assertEqual([(f["what"], f["detail"]) for f in found], [("missing file", "assets/frame.png")])

    def test_a_relative_link_to_nothing_fails_and_outside_links_are_not_followed(self):
        found = self.run_check({"index.html": GOOD})
        self.assertEqual([(f["what"], f["detail"]) for f in found], [("broken link", "review/")])

    def test_links_on_a_page_reached_by_redirect_resolve_from_where_it_lands(self):
        found = self.run_check({
            "index.html": '<meta http-equiv="refresh" content="0; url=demo/"><a href="demo/">demo</a>',
            "demo/index.html": GOOD.replace('href="review/"', 'href="../review/"'),
            "review/index.html": "<p>review</p>",
        })
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
