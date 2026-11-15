"""Keep the browser visitor smoke and deployed HTTP smoke as separate commands (#265)."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SmokeNames(unittest.TestCase):
    def help(self, module):
        result = subprocess.run([sys.executable, '-m', module, '--help'], cwd=ROOT,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_browser_smoke_keeps_its_existing_module_and_cli(self):
        text = self.help('tools.runit_smoke')
        for option in ('--stand-in', '--require-sandbox', '--screenshots'):
            self.assertIn(option, text)
        self.assertNotIn('--expect-open', text)
        # Main's browser test module must still exercise the page, not the HTTP client.
        source = (ROOT / 'tests/test_runit_smoke.py').read_text()
        self.assertIn('EXPECTRAIL_WEB_TESTS', source)
        self.assertIn('runit_smoke.expected_verdict', source)

    def test_api_smoke_has_its_own_module_cli_tests_and_allowlist_entry(self):
        text = self.help('tools.runit_api_smoke')
        self.assertIn('api_url', text)
        self.assertIn('--expect-open', text)
        self.assertNotIn('--screenshots', text)
        self.assertTrue((ROOT / 'tests/test_runit_api_smoke.py').is_file())
        self.assertIn('!/tools/runit_api_smoke.py', (ROOT / '.gitignore').read_text().splitlines())

    def test_documented_commands_distinguish_the_two_roles(self):
        deploy = (ROOT / 'docs/run-it-deploy.md').read_text()
        commands = re.findall(r'`([^`\n]+)`', deploy)
        api = [c for c in commands if '--expect-open' in c]
        self.assertEqual(len(api), 2)
        for command in api:
            self.assertIn('tools/runit_api_smoke.py', command)
            self.assertNotIn('tools/runit_smoke.py', command)
        guide = (ROOT / 'docs/run-it.md').read_text()
        self.assertIn('tools.runit_smoke', guide)
        self.assertIn('tools/runit_api_smoke.py', guide)
        self.assertIn('Chromium', guide)
        self.assertIn('HTTP', guide)
        log = (ROOT / 'docs/new-work/2026-11-15-runit-deploy-ready.md').read_text()
        self.assertIn('tools/runit_api_smoke.py', log)
        self.assertNotIn('tools/runit_smoke.py', log)


if __name__ == '__main__':
    unittest.main()
