"""The outside vision judge consumes data from this capture, never an outside checkout."""
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from expectrail import anchored
from expectrail.gate import record
from harness.run import _replay_record
from tests.test_two_observers import Game
from tools import outside_trial as trial
from tools import outside_vision as vision


class Stand:
    """A stand-in model for the anchored observer: it reads where the player is drawn from the saved
    replay's own trace (the frame's run folder), as a model reads it from the pixels."""
    model, provider, base = 'sam-3.1', 'stand-in', ''

    def __init__(self):
        self.calls = 0

    @staticmethod
    def drawn(png):
        png = Path(png)
        rows = json.loads((png.parent.parent / 'trace.json').read_text())['rows']
        return [float(v) for v in rows[2 * int(png.stem[1:])]['body']]


class Sees(Stand):
    def segment_in(self, png, boxes):
        self.calls += 1
        return [{'box': self.drawn(png), 'score': 0.93} for _ in boxes]


class Echo(Stand):
    def segment_in(self, png, boxes):
        self.calls += 1
        return [{'box': [float(v) for v in b], 'score': 0.9} for b in boxes]


class CaptureJudgeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.data = self.root / 'incoming'
        # The two changes these stand-in replays make (the project's list may hold more, such as #330's
        # invisible player, which needs a real capture).
        projects = trial.load_list()
        listed = projects[0]
        self.project = {**listed, 'changes': [c for c in listed['changes'] if c['name'] in ('broken', 'harmless')]}
        patcher = mock.patch.object(trial, 'load_list', return_value=[self.project, *projects[1:]])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.route = next((trial.REPO / self.project['routes']).glob('*.json'))
        self.model = Game()
        self.trees = {}
        for variant in ('pinned', 'broken', 'harmless'):
            game = self.root / variant
            game.mkdir()
            if variant == 'broken':
                (game / 'BUG').touch()
            run_dir = self.data / variant / self.route.stem
            made = self.model.replay(self.route, game, run_dir, True)
            trace = made['trace']
            trace.update(format='expectrail.trace/v0', ticks=len(trace['rows']))
            for row in trace['rows']:
                # The player's collision box, as the harness logs it (#259), so the anchored observer
                # (#330) has a place to ask about.
                x, y = row['player']
                row['body'] = [x - 10.0, y - 20.75, x + 10.0, y + 13.25]
            (run_dir / 'trace.json').write_text(json.dumps(trace))
            isolation = json.loads((trial.REPO / 'contracts/examples/replay.json').read_text())['isolation']
            isolation['mode'] = 'require'
            tree = hashlib.sha256(variant.encode()).hexdigest()
            self.trees[variant] = tree
            _replay_record(self.route, run_dir, tree, 60, [], json.loads(self.route.read_text()),
                           '', run_dir / 'frames', isolation)
        self.receipt = vision.capture_id(self.project, self.data)
        self.out = self.root / 'findings'

    def judge(self):
        return vision.judge(self.project, self.data, self.receipt, self.out, self.model.observer())

    def test_saved_gate_runs_no_process_and_records_the_real_trees_and_both_observers(self):
        with mock.patch('subprocess.Popen', side_effect=AssertionError('judge launched a process')):
            rows = self.judge()
        self.assertTrue(self.model.asked)
        self.assertEqual([r['change'] for r in rows], [None, 'broken', 'harmless'])
        self.assertEqual(rows[0]['decision'], 'accept')
        self.assertEqual(rows[1]['decision'], 'reject')
        for variant in self.trees:
            doc = record.read_record(self.out / variant / 'findings.json')
            self.assertEqual(doc['game']['headTree'], self.trees[variant])
            self.assertEqual(doc['game']['baseTree'], None if variant == 'pinned' else self.trees['pinned'])
            self.assertEqual(doc['observers']['rule'], 'both')
            self.assertTrue(doc['isolation']['required'])
            self.assertEqual(doc['isolation']['sandboxed'], doc['isolation']['replays'])
        self.assertIn('| Project | Change |', (self.out / 'outside-trial.md').read_text())

    def test_corrupt_last_variant_is_refused_before_any_model_call(self):
        folder = self.data / 'harmless' / self.route.stem
        for name in ('trace.json', 'frames/f00000001.png', 'replay.json'):
            with self.subTest(file=name):
                file = folder / name
                original = file.read_bytes()
                file.write_bytes(original + b' ')
                with self.assertRaises(ValueError):
                    self.judge()
                self.assertFalse(self.model.asked)
                file.write_bytes(original)

    def test_a_symlink_a_missing_frame_and_an_extra_file_are_refused(self):
        folder = self.data / 'pinned' / self.route.stem
        frame = folder / 'frames/f00000001.png'
        saved = self.root / 'saved.png'
        frame.rename(saved)
        with self.assertRaises(ValueError):
            self.judge()
        frame.symlink_to(saved)
        with self.assertRaises(ValueError):
            self.judge()
        frame.unlink()
        saved.rename(frame)
        (folder / 'frames/extra.py').touch()
        with self.assertRaises(ValueError):
            self.judge()
        self.assertFalse(self.model.asked)

    def test_capture_pins_each_variant_and_requires_the_sandbox(self):
        destination = self.root / 'published'
        with mock.patch.object(trial, 'fetch', autospec=True) as fetch, \
                mock.patch.object(trial, 'lay_out', autospec=True) as layout, \
                mock.patch.object(trial, 'capture', autospec=True) as replay:
            def checkout(project, source, work, change):
                name = change['name'] if change else 'pinned'
                folder = work / name / 'project'
                folder.mkdir(parents=True)
                (folder / 'marker').write_text(name)
                return folder.parent

            def copy_run(project, checkout, stage, *, timeout, sandbox):
                self.assertEqual(sandbox, 'require')
                source = self.data / checkout.name
                folder = stage / project['name']
                shutil.copytree(source, folder)
                record_path = folder / self.route.stem / 'replay.json'
                doc = json.loads(record_path.read_text())
                doc['game']['tree'] = vision.verify.game_tree(checkout / 'project')
                record_path.write_text(json.dumps(doc))
                return [{'exit': 0, 'frames': doc['capture']['frames']}]

            layout.side_effect = checkout
            replay.side_effect = copy_run
            receipt = vision.capture(self.project, destination)
            self.assertEqual(fetch.call_args.args[0]['commit'], self.project['commit'])
            self.assertEqual(receipt, vision.capture_id(self.project, destination))
            self.assertEqual(set(self.trees), {p.name for p in destination.iterdir()})
            replay.side_effect = lambda *args, **kw: [{'exit': 1, 'frames': 0}]
            with self.assertRaisesRegex(ValueError, 'capture failed'):
                vision.capture(self.project, self.root / 'failed')
            self.assertFalse((self.root / 'failed').exists())

    def test_replay_must_name_the_trusted_route_required_isolation_and_frame_count(self):
        path = self.data / 'pinned' / self.route.stem / 'replay.json'
        original = path.read_bytes()
        for field, key, value in [('route', 'sha256', '0' * 64), ('isolation', 'mode', 'auto'),
                                  ('isolation', 'network', 'host'), ('capture', 'frames', 0)]:
            with self.subTest(field=field, key=key):
                doc = json.loads(original)
                doc[field][key] = value
                path.write_text(json.dumps(doc))
                self.receipt = vision.capture_id(self.project, self.data)
                with self.assertRaises(ValueError):
                    self.judge()
                self.assertFalse(self.model.asked)

    def test_cli_checks_cap_before_observer_and_writes_spend_even_on_failure(self):
        cli = ['judge', '--project', self.project['name'], '--data', str(self.data), '--digest', self.receipt,
               '--out', str(self.out)]
        caps = ('', '0', '-1', '2.01', 'NaN', 'inf')
        with mock.patch.dict(os.environ, {'MODEL_API_KEY': 'stand-in'}), \
                mock.patch('agents.sam_observations.MetaSamClient', return_value=Sees()) as factory:
            for cap in caps:
                with self.subTest(cap=cap), mock.patch.dict(os.environ, {'EXPECTRAIL_SAM_USD_CAP': cap}), \
                        self.assertRaises(SystemExit):
                    vision.main(cli)
            factory.assert_not_called()
            with mock.patch.dict(os.environ, {'EXPECTRAIL_SAM_USD_CAP': '2.00'}):
                with mock.patch.object(vision, 'judge', side_effect=ValueError('invalid capture')), \
                        self.assertRaisesRegex(ValueError, 'invalid capture'):
                    vision.main(cli)
            self.assertEqual(json.loads((self.out / 'spend.json').read_text())['requests'], 0)
            self.assertFalse((self.out / 'outside-trial.md').exists())

    def cli(self, out, *extra):
        return ['judge', '--project', self.project['name'], '--data', str(self.data),
                '--digest', self.receipt, '--out', str(out), *extra]

    def live(self, client, out):
        """The live path (#330): the CLI builds the model client, wraps it in a recorder, calibrates
        the anchored observer on the unchanged game, then judges. ``client`` stands in for the model."""
        with mock.patch.dict(os.environ, {'MODEL_API_KEY': 'stand-in', 'EXPECTRAIL_SAM_USD_CAP': '2'}), \
                mock.patch('agents.sam_observations.MetaSamClient', return_value=client):
            self.assertEqual(vision.main(self.cli(out)), 0)
        return json.loads((out / 'calibration.json').read_text())

    def decisions(self, out):
        return {v: record.read_record(out / v / 'findings.json')['decision'] for v in ('pinned', 'broken', 'harmless')}

    def test_a_model_that_sees_the_player_calibrates_and_judges_with_vision(self):
        client = Sees()
        calibration = self.live(client, self.out)
        anchored.check_calibration(calibration)
        self.assertTrue(calibration['enabled'], calibration['why'])
        self.assertGreater(client.calls, 0)
        self.assertEqual(self.decisions(self.out), {'pinned': 'accept', 'broken': 'reject', 'harmless': 'accept'})
        # The broken copy's reject has the visual observer's evidence, not the engine's alone.
        broken = record.read_record(self.out / 'broken' / 'findings.json')
        self.assertEqual(broken['observers']['visual']['name'], anchored.NAME)
        self.assertIn('reservedUsd', json.loads((self.out / 'spend.json').read_text()))
        self.assertIn('used', (self.out / 'calibration.md').read_text())
        self.assertIn('harmless', (self.out / 'outside-trial.md').read_text())

    def test_a_model_that_echoes_the_box_is_not_used(self):
        calibration = self.live(Echo(), self.out)
        self.assertFalse(calibration['enabled'])
        self.assertTrue(any('twice as large' in w for w in calibration['why']))
        decided = self.decisions(self.out)
        self.assertEqual(decided['broken'], 'reject')   # the engine's record alone rejects a fail
        self.assertEqual((decided['pinned'], decided['harmless']), ('needs-review', 'needs-review'))
        harmless = record.read_record(self.out / 'harmless' / 'findings.json')
        self.assertTrue(any('not calibrated' in r for r in harmless['reasons']), harmless['reasons'])

    def test_the_recording_replays_the_same_findings_without_a_model(self):
        self.live(Sees(), self.out)
        recording = self.out / 'vision-recording.json'
        again = self.root / 'replayed'
        with mock.patch('agents.sam_observations.MetaSamClient', side_effect=AssertionError('a client was built')), \
                mock.patch.dict(os.environ, {'MODEL_API_KEY': '', 'EXPECTRAIL_SAM_USD_CAP': ''}):
            self.assertEqual(vision.main(self.cli(again, '--recording', str(recording))), 0)
        self.assertEqual(self.decisions(again), self.decisions(self.out))
        for v in ('pinned', 'broken', 'harmless'):
            first, second = (record.read_record(o / v / 'findings.json') for o in (self.out, again))
            self.assertEqual(second['findings'], first['findings'])
            self.assertEqual(second['counts'], first['counts'])
        self.assertEqual(json.loads((again / 'calibration.json').read_text())['rates'],
                         json.loads((self.out / 'calibration.json').read_text())['rates'])

    def test_swapping_variant_folders_is_refused(self):
        a, b, tmp = (self.data / v for v in ('broken', 'harmless', 'tmp'))
        a.rename(tmp)
        b.rename(a)
        tmp.rename(b)
        with self.assertRaises(ValueError):
            self.judge()
        self.assertFalse(self.model.asked)


class WorkflowTest(unittest.TestCase):
    def test_judge_never_fetches_or_starts_an_outside_project(self):
        wf = yaml.safe_load((trial.REPO / '.github/workflows/outside-vision.yml').read_text())
        self.assertEqual(set(wf.get('on', wf.get(True))), {'workflow_dispatch'})
        self.assertEqual(wf['permissions'], {'contents': 'read'})
        self.assertEqual(set(wf['jobs']), {'capture', 'judge'})
        capture, judge = (wf['jobs'][k] for k in ('capture', 'judge'))
        self.assertNotIn('secrets.', json.dumps(capture))
        self.assertNotIn('environment', capture)
        self.assertEqual(judge['environment'], 'main-only')
        self.assertEqual(judge['needs'], 'capture')
        self.assertIn("refs/heads/main", judge['if'])
        steps = json.dumps(judge['steps']).lower()
        for forbidden in ('git fetch', 'git clone', 'harness', 'godot', 'outside_trial', '--fetch',
                          'repository":', 'xvfb', 'bubblewrap', 'outside_vision capture'):
            self.assertNotIn(forbidden, steps)
        self.assertIn('tools.outside_vision judge', steps)
        self.assertIn('actions/download-artifact@', steps)
        holders = [s for s in judge['steps'] if 'secrets.MODEL_API_KEY' in json.dumps(s)]
        self.assertEqual(len(holders), 1)
        self.assertIn('tools.outside_vision judge', holders[0]['run'])
