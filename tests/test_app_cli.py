"""The app's screen mapping and --open-browser, without a browser or Godot (merge guard on #620)."""
from __future__ import annotations

import io
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from expectrail import app


class ScreenTest(unittest.TestCase):
    def test_every_job_state_maps_to_its_screen(self):
        out = {'evidence': 1}
        cases = [
            ('queued', None, None, ('running', 'queued')),
            ('running', None, None, ('running', 'running')),
            ('cancelled', None, None, ('cancelled', 'cancelled')),
            ('failed', None, None, ('failed', 'failed')),
            ('completed', 'needs-review', None, ('needs-review', 'could-not-be-carried-out')),
            ('completed', 'needs-review', out, ('needs-review', 'needs-review')),
            ('completed', 'accept', out, ('accept', 'accept')),
            ('completed', 'reject', out, ('reject', 'reject')),
        ]
        for phase, decision, output, want in cases:
            with self.subTest(phase=phase, decision=decision, output=bool(output)):
                self.assertEqual(app.job_screen(phase, decision, output), want)

    def test_needs_review_without_output_says_it_could_not_be_carried_out(self):
        self.assertEqual(app.job_screen('completed', 'needs-review', {})[1], 'could-not-be-carried-out')


class OpenBrowserTest(unittest.TestCase):
    def run_app(self, opened):
        seen, done = [], threading.Event()

        def fake_open(url):
            seen.append(url)
            done.set()
            return opened

        def serve(self_server):
            done.wait(5)
            raise KeyboardInterrupt

        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(app.webbrowser, 'open', fake_open), \
                mock.patch.object(app.Server, 'serve_forever', serve), redirect_stdout(out):
            code = app.main(['--open-browser', '--jobs-root', str(Path(tmp) / 'jobs')])
            # The opener runs on a thread: give its fallback line time to print.
            for _ in range(50):
                if opened or 'did not open' in out.getvalue():
                    break
                threading.Event().wait(0.02)
        return code, seen, out.getvalue()

    def test_the_browser_gets_the_printed_local_address(self):
        code, seen, out = self.run_app(True)
        self.assertEqual(code, 0)
        self.assertEqual(len(seen), 1)
        self.assertRegex(seen[0], r'^http://127\.0\.0\.1:\d+/\?token=.+$')
        self.assertIn(f'Open {seen[0]}', out)
        self.assertNotIn('did not open', out)

    def test_a_browser_that_does_not_open_prints_the_fallback(self):
        code, seen, out = self.run_app(False)
        self.assertEqual(code, 0)
        self.assertEqual(len(seen), 1)
        self.assertIn('Your browser did not open. Copy the local address above into your browser.', out)


if __name__ == '__main__':
    unittest.main()
