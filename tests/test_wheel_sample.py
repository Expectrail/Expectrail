"""The explicit saved-answer sample profile cannot weaken ordinary verification (#249)."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from expectrail import cli, doctor, recorded


class RecordedSampleProfileTest(unittest.TestCase):
    def invoke(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = cli.main(list(args))
        return status, out.getvalue(), err.getvalue()

    def test_saved_sample_uses_the_existing_runner_and_no_network(self):
        from expectrail.orchestrator import sample
        rows = [dict(asExpected=True, status={'phase': 'completed', 'decision': decision})
                for decision in ('accept', 'reject', 'accept')]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict('os.environ', {cli.SAMPLE_RECORDINGS_ENV: '1'}), \
                mock.patch('urllib.request.urlopen', side_effect=AssertionError('no network')), \
                mock.patch.object(sample, 'run', return_value=rows) as run:
            status, text, err = self.invoke('sample', '--jobs-root', tmp, '--json')
        self.assertEqual((status, err), (0, ''))
        self.assertEqual(json.loads(text), rows)
        visual = run.call_args.kwargs['engines']['godot']._visual
        self.assertIsInstance(visual, recorded.RecordedBankObserver)
        self.assertEqual([d['sample'] for d in visual.recordings], ['clean', 'fall-through-bug', 'fall-through-repair'])
        self.assertEqual(visual.client.calls, 0)

    def test_json_keeps_replay_diagnostics_on_stderr(self):
        from expectrail.orchestrator import sample

        warning = '::warning title=Expectrail gate::route smoke: the head replay did not finish'
        rows = [{'asExpected': False, 'status': {'phase': 'completed', 'decision': 'needs-review'}}]

        def interrupted_replay(*args, **kwargs):
            print(warning)
            return rows

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict('os.environ', {cli.SAMPLE_RECORDINGS_ENV: '1'}), \
                mock.patch.object(sample, 'run', side_effect=interrupted_replay):
            status, text, err = self.invoke('sample', '--jobs-root', tmp, '--json')

        self.assertEqual(status, 3)
        self.assertEqual(json.loads(text), rows)
        self.assertIn(warning, err.splitlines())

    def test_a_missing_answer_remains_no_answer_without_live_fallback(self):
        visual = cli._sample_observer()
        with tempfile.TemporaryDirectory() as tmp, mock.patch('urllib.request.urlopen', side_effect=AssertionError('live fallback')):
            png = Path(tmp) / 'changed.png'; png.write_bytes(b'new image bytes')
            with self.assertRaises(recorded.MissingRecordedAnswer):
                visual.client.segment(png, 'player')
        self.assertEqual(visual.client.not_recorded, 1)

    def test_invalid_recordings_do_not_start_a_run(self):
        from expectrail.orchestrator import sample
        with mock.patch.dict('os.environ', {cli.SAMPLE_RECORDINGS_ENV: '1'}), \
                mock.patch.object(cli, '_sample_observer', side_effect=recorded.RecordingError('missing recording')), \
                mock.patch.object(sample, 'run', side_effect=AssertionError('must not start')):
            status, text, err = self.invoke('sample', '--json')
        self.assertEqual((status, text), (5, ''))
        self.assertIn('missing recording', err)

    def test_profile_is_opt_in_and_ordinary_doctor_keeps_its_rules(self):
        with mock.patch.dict('os.environ', {cli.SAMPLE_RECORDINGS_ENV: '0'}), mock.patch.object(doctor, 'main', return_value=3) as main:
            self.assertEqual(self.invoke('doctor')[0], 3)
            main.assert_called_once_with([])

    def test_sample_profile_never_substitutes_for_an_explicit_project(self):
        with mock.patch.dict('os.environ', {cli.SAMPLE_RECORDINGS_ENV: '1'}), mock.patch.object(doctor, 'main', return_value=3) as main:
            self.assertEqual(self.invoke('doctor', '--project', '/not-a-sample')[0], 3)
            main.assert_called_once_with(['--project', '/not-a-sample'])

    def test_doctor_requires_valid_recordings_and_reports_missing_live_settings_as_optional(self):
        for available in (False, True):
            found = doctor.vision_checks({})
            observer = cli._sample_observer() if available else None
            with self.subTest(available=available), mock.patch.dict('os.environ', {cli.SAMPLE_RECORDINGS_ENV: '1'}), \
                    mock.patch.object(doctor, 'checks', return_value=found), \
                    mock.patch.object(cli, '_sample_observer', return_value=observer,
                                      side_effect=None if available else recorded.RecordingError('missing')):
                status, text, err = self.invoke('doctor', '--json')
            self.assertEqual(status, 0 if available else 3, err)
            doc = json.loads(text)
            self.assertEqual(doctor.problems(doc), [])
            checks = {c['id']: c for c in doc['checks']}
            self.assertTrue(checks['sample-recordings']['required'])
            for name in ('vision-key', 'vision-cap'):
                self.assertEqual((checks[name]['required'], checks[name]['status']), (False, 'missing'))

    def test_usage_and_conflicting_jobs_roots_never_run(self):
        with mock.patch.dict('os.environ', {cli.SAMPLE_RECORDINGS_ENV: '1'}):
            for args in (('sample', '--unknown'), ('doctor', '--unknown'),
                         ('--jobs-root', 'a', 'sample', '--jobs-root', 'b')):
                with self.subTest(args=args):
                    status, out, err = self.invoke(*args)
                    self.assertEqual((status, out), (5, ''))
                    self.assertIn('Nothing was run', err)
