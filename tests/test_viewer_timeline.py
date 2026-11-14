"""Viewer-only additions: recorded visual timelines, gaps, honest words and public reproduction."""
import copy
import base64
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import unittest

from expectrail import evaluator, viewer
from expectrail.contracts import digest
from tests.test_two_observers import Case, SPEC, repo
from tests.test_viewer import embedded, banner_state, obs, spec
from tests.test_runit import Case as RunItCase


class VisualTimelineTest(Case):
    def test_visual_failure_keeps_both_observers_and_the_recorded_first_frame(self):
        doc = self.gate(repo(self.tmp / 'h', 'DRAWN'), repo(self.tmp / 'b'))
        views = viewer.read_views(self.out / 'viewer')
        v = views[0]
        first = doc['findings'][0]['frame']
        self.assertEqual(doc['decision'], 'reject')
        self.assertEqual(v['firstFrame'], first)
        self.assertFalse([p for p in v['series']['after']['points'] if p['state'] == 'over'])
        self.assertEqual(next(p['frame'] for p in v['visualSeries']['after']['points'] if p['state'] == 'over'), first)
        for side in ('before', 'after'):
            self.assertEqual(v['visualSeries'][side]['source'], "the visual observer's record")
        exported = embedded((self.out / 'viewer/evidence.html').read_text())
        self.assertEqual(exported['views'][0]['visualSeries'], v['visualSeries'])

    def test_visual_data_must_match_the_record_and_verdict_and_not_be_a_link(self):
        doc = self.gate(repo(self.tmp / 'h'))
        check = doc['checks'][0]
        def read():
            return viewer.visual_series(self.out, SPEC, check, 'after', doc['specs'][0]['sha256'])
        self.assertIsNotNone(read()['series'])
        path = self.out / 'observations/head/smoke/player-stays-above-ground.visual.json'
        original = path.read_bytes()
        data = json.loads(original)
        data['frames'][0]['objects'] = {}
        path.write_text(json.dumps(data))
        self.assertIsNone(read()['series'])
        path.write_bytes(original)
        verdict_path = self.out / 'verdicts/head/smoke/player-stays-above-ground.visual.json'
        verdict = json.loads(verdict_path.read_text())
        verdict_path.write_text(json.dumps(dict(verdict, spec=dict(verdict['spec'], sha256='0' * 64))))
        self.assertIsNone(read()['series'])
        verdict_path.write_text(json.dumps(verdict))
        saved = path.with_suffix('.saved')
        path.rename(saved)
        path.symlink_to(saved)
        self.assertIsNone(read()['series'])
        path.unlink()
        path.write_bytes(original)
        self.assertIsNone(viewer.visual_series(self.out, SPEC, check, 'after', '0' * 64)['series'])
        bad = dict(check, route='../smoke')
        self.assertIsNone(viewer.visual_series(self.out, SPEC, bad, 'after', digest(SPEC))['series'])
        path.unlink()
        self.assertIsNone(read()['series'])
        path.write_bytes(original)
        directory = path.parent
        moved = directory.with_name('saved-smoke')
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
        self.assertIsNone(read()['series'])

    def test_provider_failure_says_vision_did_not_run_without_replacing_reject(self):
        for look, expected in [('BUG', 'behaviour-failure'), ('clean', 'observation-failure')]:
            with self.subTest(look=look):
                doc = self.gate(repo(self.tmp / look, look), visual=None)
                for setting in ('MODEL_API_KEY', 'EXPECTRAIL_SAM_USD_CAP'):
                    status = {'id': 'offline-test', 'phase': 'completed', 'decision': doc['decision'],
                              'reasons': doc['reasons'], 'inputs': {}, 'diagnostics': [
                                  {'code': 'PROVIDER_FAILED', 'stage': 'observing',
                                   'detail': setting + ' is missing', 'fix': 'Set ' + setting}]}
                    page = viewer.write(self.tmp / ('words-' + look), doc, status=status).read_text()
                    self.assertIn('Vision did not run (PROVIDER_FAILED)', page)
                    self.assertIn(setting, page)
                    self.assertEqual(banner_state(page), expected)
                    self.assertEqual(embedded(page)['decision'], doc['decision'])

    def test_engine_failure_says_vision_was_not_asked_not_that_the_provider_failed(self):
        self.gate(repo(self.tmp / 'h', 'BUG'))
        page = (self.out / 'viewer/index.html').read_text()
        self.assertIn('Vision was not asked about 1 after-change check', page)
        self.assertIn('already fails it, and a failure from either observer rejects', page)
        self.assertNotIn('Vision did not run (PROVIDER_FAILED)', page)

    def test_a_provider_that_was_called_is_not_reported_as_never_run(self):
        self.game.down = True
        doc = self.gate(repo(self.tmp / 'h'))
        self.assertEqual(doc['checks'][0]['observed']['after']['visual'], 'no-answer')
        words = viewer.vision_words(doc, {'diagnostics': [{'code': 'PROVIDER_FAILED'}]})
        self.assertIn('returned no usable answer', words)
        self.assertNotIn('did not run', words)


class GapTest(unittest.TestCase):
    def test_absent_frames_missing_objects_and_not_exercised_are_distinct(self):
        s, o = spec(), obs('trace-fixed.json')
        s['window'] = {'fromFrame': 0, 'toFrame': 4}
        frame = copy.deepcopy(o['frames'][0])
        o['frames'] = [dict(frame, frame=0), dict(frame, frame=2, objects={}), dict(frame, frame=4)]
        got = viewer.series(s, o)
        points = {p['frame']: p for p in got['points']}
        self.assertEqual(list(points), [0, 1, 2, 3, 4])
        self.assertEqual(points[1]['state'], 'absent')
        self.assertEqual(points[2]['state'], 'missing')
        self.assertEqual(points[3]['state'], 'absent')
        self.assertIsNone(points[1]['value'])
        # A region which does not overlap the player is not an observed failure.
        s['assertion']['boundary'] = {'relativeTo': 'ground', 'edge': 'top', 'side': 'above'}
        frame['objects']['ground'] = [{'box': [9999, 780, 10000, 900], 'score': 1}]
        one = viewer.series(s, dict(o, frames=[dict(frame, frame=0)]))
        self.assertEqual(one['points'][0]['state'], 'not-applicable')

    def test_empty_bounded_windows_and_large_gaps_are_bounded(self):
        s, o = spec(), obs('trace-fixed.json')
        o['frames'] = []
        s['window'] = {'fromFrame': 2, 'toFrame': 4}
        self.assertEqual([p['state'] for p in viewer.series(s, o)['points']], ['absent'] * 3)
        s['window']['toFrame'] = 10**9
        got = viewer.series(s, o)
        self.assertEqual(len(got['points']), viewer.MAX_POINTS)
        self.assertTrue(got['truncated'])

    def test_coverage_is_reported_without_turning_not_exercised_into_a_pass(self):
        s, o = spec(), obs('trace-fixed.json')
        s['coverage'] = {'minFrames': 1000}
        verdict = evaluator.evaluate(s, o)
        self.assertEqual(verdict['result'], 'needs-review')
        got = viewer.check_series(s, {'engineObservations': o}, verdict)
        self.assertEqual(got['series']['coverage']['status'], 'not-exercised')
        self.assertIn('not-exercised', got['note'])


class PublicSampleTest(RunItCase):
    def test_run_it_uses_the_public_command_in_both_exports(self):
        self.record('clean')  # offline stand-in model, never a live provider
        status, out = self.run_sample('clean')
        self.assertEqual(status['decision'], 'accept')
        for name in ('index.html', 'evidence.html'):
            page = (out / 'viewer' / name).read_text()
            command = embedded(page)['reproduce']
            self.assertEqual(command, 'python3 -m expectrail.runit run --sample clean --out clean-run')
            self.assertNotIn('/tmp/', command)


class KeyboardTest(unittest.TestCase):
    def test_the_real_script_handles_keys_gaps_observers_and_empty_evidence(self):
        script = Path(__file__).with_name('viewer_keyboard.cjs')
        samples = Path(__file__).resolve().parent.parent / 'docs/viewer-samples'
        pages = [embedded((samples / (name + '.html')).read_text()) for name in ('clean', 'fall-through-bug')]
        run = subprocess.run(['node', str(script)], input=json.dumps({'script': viewer.SCRIPT, 'pages': pages}),
                             text=True, capture_output=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('keyboard navigation: OK', run.stdout)


class PublishedSamplesTest(unittest.TestCase):
    def test_image_encoding_preserves_bytes_without_disguising_text_keys(self):
        from agents.export_scan import SECRETS
        # A key-shaped sequence can occur randomly in a PNG's base64 alphabet.
        image = 'data:image/png;base64,AAAA/' + 'ghp' + 'Q' * 16 + '+AAAA'
        key = 'ghp_' + 'Q' * 16
        encoded = viewer._json_for_script({'image': image, 'text': key})
        self.assertEqual(json.loads(encoded), {'image': image, 'text': key})
        self.assertEqual(SECRETS.findall(encoded), [key])

    def test_supplied_decisions_records_and_frame_bytes_are_preserved_offline(self):
        root = Path(__file__).resolve().parent.parent / 'docs/viewer-samples'
        provenance = json.loads((root / 'provenance.json').read_text())
        class References(HTMLParser):
            def handle_starttag(self, tag, attrs):
                for name, value in attrs:
                    if name in ('src', 'href'):
                        raise AssertionError('an offline export references ' + value)
        for name, decision in [('clean', 'accept'), ('fall-through-bug', 'reject')]:
            with self.subTest(sample=name):
                text = (root / (name + '.html')).read_text()
                data, source = embedded(text), provenance['samples'][name]
                References().feed(text)
                self.assertIn(f'content="{viewer.CSP}"', text)
                self.assertEqual(text.count('</script>'), 2)
                self.assertEqual(data['decision'], decision)
                self.assertEqual(digest(data['record']), source['recordSha256'])
                self.assertEqual(digest(data['job']), source['jobSha256'])
                self.assertEqual(data['reproduce'], viewer.reproduce(None, sample=name))
                self.assertNotIn('/tmp/expectrail-runit-', text)
                frames = [f for v in data['views'] for fs in v['frames'].values() for f in fs]
                self.assertEqual(len(frames), source['framesEmbedded'])
                for f in frames:
                    raw = base64.b64decode(f['path'].split(',', 1)[1], validate=True)
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), f['sha256'])
                self.assertFalse(source['visualMeasurementsIncluded'])
                self.assertTrue(all(s is None for v in data['views'] for s in v['visualSeries'].values()))
                self.assertIn('visual measurements were not included', text)
