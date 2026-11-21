"""The signed-out hub can load its brand fonts without leaving its origin."""
from pathlib import Path

from tests.test_hub_auth import HubCase


class HubFontTest(HubCase):
    def test_hub_links_its_font_stylesheet_under_the_same_origin_policy(self):
        page = self.client.get('/')
        self.assertIn('href="/assets/hub-fonts.css"', page.text)
        self.assertIn("font-src 'self'", page.header('Content-Security-Policy'))
        stylesheet = self.client.get('/assets/hub-fonts.css')
        self.assertEqual(stylesheet.header('Content-Type'), 'text/css; charset=utf-8')
        self.assertIn('font-family: Adventor', stylesheet.text)
        self.assertNotIn('http', stylesheet.text)

    def test_only_the_known_adventor_files_are_served(self):
        sources = Path(__file__).resolve().parents[1] / 'docs' / 'assets' / 'fonts'
        for filename in ('texgyreadventor-regular.woff', 'texgyreadventor-bold.woff'):
            with self.subTest(filename=filename):
                response = self.client.get('/assets/fonts/' + filename)
                self.assertEqual(response.status, 200)
                self.assertEqual(response.header('Content-Type'), 'font/woff')
                self.assertEqual(response.body, (sources / filename).read_bytes())
        for path in ('/assets/fonts/../front-door.css', '/assets/fonts/Lora-Variable.woff'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status, 404)
