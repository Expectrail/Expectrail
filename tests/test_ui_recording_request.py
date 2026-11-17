"""UI trace data is requested by evaluated specs, never by the game or offer alone (#285)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness import run as hr
from harness import sandbox as box
from tests import test_project_config as fixtures
from tests.test_trace_evaluator import spec

UI = spec({'type': 'signal_compare', 'leftSignal': 'coins_collected',
           'rightSignal': 'ui_integer_at_end', 'comparator': 'eq', 'toleranceAbs': 0})
RELATION = spec({'type': 'relation', 'signal': 'ui_integer_at_end', 'left': 'a',
                 'right': 'b', 'comparator': 'eq', 'toleranceAbs': 0})
PLAIN = spec({'type': 'relation', 'signal': 'coins_collected', 'left': 'a',
              'right': 'b', 'comparator': 'eq', 'toleranceAbs': 0})


class RecordingArgumentsTest(unittest.TestCase):
    def capture(self, requested):
        fixture = fixtures.SandboxValuesTest('test_the_sandbox_is_given_values_and_not_the_config_path')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        route = fixture.tmp / 'route.json'
        route.write_text(json.dumps({'format': 'expectrail.route/v0', 'name': 't', 'seed': 1,
                                      'ticks': 1, 'events': []}))
        engine = fixture.tmp / 'godot'; engine.write_bytes(b'not an engine')
        with mock.patch.object(box, 'probe', return_value=(fixtures.FAKE, None)), \
             mock.patch.object(box, 'run', side_effect=fixture.engine), \
             mock.patch.object(hr.subprocess, 'run', side_effect=AssertionError('started outside')):
            hr.run(route, fixture.tmp / 'out', game=fixtures.CRATE, godot=engine,
                   sandbox='require', capture_frames=False, trace_specs=requested)
        return fixture.calls[-1]

    def test_default_and_unrelated_specs_do_not_enable_ui_recording(self):
        for requested in ([], [PLAIN]):
            with self.subTest(requested=requested):
                self.assertFalse(any(a.startswith('--ui-integers=') for a in self.capture(requested)))

    def test_ui_signal_on_either_side_and_relation_use_existing_argument_path(self):
        swapped = spec({**UI['operation'], 'leftSignal': 'ui_integer_at_end', 'rightSignal': 'coins_collected'})
        for requested in ([UI], [swapped], [RELATION], [PLAIN, UI]):
            with self.subTest(requested=requested):
                argv = self.capture(requested)
                self.assertEqual([a for a in argv if a.startswith('--ui-integers=')], ['--ui-integers=true'])
                self.assertTrue(any(a.startswith('--bindings=') for a in argv))


class UnrequestedTraceEngineTest(unittest.TestCase):
    def test_trace_has_no_ui_key_when_no_spec_requested_it(self):
        from tests.tool_requirements import godot_binary
        engine = godot_binary(switch='EXPECTRAIL_ENGINE_TESTS')
        with tempfile.TemporaryDirectory(prefix='expectrail-ui-off-') as tmp:
            root = Path(tmp); route = root / 'route.json'
            route.write_text(json.dumps({'format': 'expectrail.route/v0', 'name': 'no-ui', 'seed': 1,
                                          'ticks': 4, 'events': []}))
            hr.run(route, root / 'out', godot=engine, capture_frames=False)
            trace = (root / 'out/trace.json').read_bytes()
            self.assertFalse(b'uiIntegers' in trace, 'an unrequested trace contains uiIntegers')
            self.assertTrue(json.loads(trace)['rows'])


class JitRecordingPlanTest(unittest.TestCase):
    def test_only_routes_with_a_ui_spec_request_it_in_every_judged_build(self):
        import shutil
        from expectrail.jit import offer
        from expectrail.jit.run import generate
        from tests.jit_fixtures import Case, JitGame, PROFILE, Transport, reply
        from expectrail.jit.intent import spark_intent
        case = Case(); self.addCleanup(shutil.rmtree, case.dir, True)
        calls = []
        game = JitGame()
        def runner(path, out, patches=(), *, trace_specs=()):
            calls.append((Path(out).parts[-2], json.loads(Path(path).read_text())['name'], list(trace_specs)))
            got = game(path, out, patches=patches)
            if trace_specs:
                trace_path = Path(out) / 'trace.json'; trace = json.loads(trace_path.read_text())
                trace['rows'][0]['coins'] = [[i, 0] for i in range(5)]
                bug = any(Path(p).stem == 'air-jump' for p in patches)
                for row in trace['rows']:
                    row['uiIntegers'] = [0 if bug else 5]
                trace_path.write_text(json.dumps(trace))
            return got
        check = {'id': 'counter', 'statement': 'The reported counter agrees with collection.',
                 'claimId': 'player.jump', 'class': 'player', 'operation': UI['operation'],
                 'appliesTo': ['jump-w0-x8']}
        plain = {'id': 'plain', 'statement': 'A separate route.', 'claimId': 'player.jump', 'class': 'player',
                 'operation': {'type': 'max_episode_rise', 'maxPx': 100000}, 'appliesTo': ['jump-w0-x2']}
        intent = spark_intent(transport=Transport(reply({'candidates': [check, plain]})), offer=offer.EVIDENCE)
        doc = generate(PROFILE, 'Counter is wrong.', case.patch('fix-comment'),
                       [case.patch('air-jump')], case.dir / 'out', runner=runner, intent=intent,
                       variants_fn=case.variants('variant-noop'), offer=offer.EVIDENCE)
        self.assertEqual(doc['status'], 'complete', doc['reason'])
        self.assertTrue(calls)
        for build, name, requested in calls:
            with self.subTest(build=build, route=name):
                self.assertEqual(bool(requested), name == 'jump-w0-x8')
                if requested:
                    self.assertEqual(requested[0]['operation'], UI['operation'])
        self.assertTrue({'reference', 'base', 'candidate-print', 'candidate'} <= {c[0] for c in calls})
        ui = next(v for v in doc['validity'] if v['specId'] == 'jit-counter')
        self.assertTrue(ui['valid'])
        self.assertEqual(ui['reference'], ['pass'] * 3)
        self.assertEqual(ui['outcome'], 'catch')
        # Optional fields must not manufacture a different candidate fingerprint.
        near = next(v for v in doc['variants'] if v['id'] == 'v-variant-noop')
        self.assertIn('jit-counter', near['sameAsCandidateFor'])


class DiscoveryRecordingPlanTest(unittest.TestCase):
    def test_a_planner_ui_spec_requests_old_or_new_routes_and_reproduction_replays(self):
        import shutil
        from expectrail.discovery.run import discover
        from tests.jit_fixtures import Case, JitGame, PROFILE
        for new_probe in (False, True):
            with self.subTest(new_probe=new_probe):
                case = Case(); self.addCleanup(shutil.rmtree, case.dir, True)
                requested = []
                game = JitGame()
                def runner(path, out, patches=(), *, trace_specs=()):
                    requested.append((Path(out).name, list(trace_specs)))
                    result = game(path, out, patches=patches)
                    if trace_specs:
                        trace_path = Path(out) / 'trace.json'; trace = json.loads(trace_path.read_text())
                        trace['rows'][0]['coins'] = [[i, 0] for i in range(5)]
                        for row in trace['rows']:
                            row['uiIntegers'] = [0 if patches else 5]
                        trace_path.write_text(json.dumps(trace))
                    return result
                target = 'plan-ui' if new_probe else 'hold-right'
                rule = spec(UI['operation'], sid='planned-counter')
                rule['expectationRef']['authority'] = 'model_prior'
                entry = {'spec': rule, 'applies': {'kind': 'probes', 'ids': [target]}, 'source': 'model'}
                extra = [{'id': target, 'family': 'planned', 'description': 'A short probe.', 'tags': [],
                          'program': {'op': 'wait', 'durationTicks': 4}}] if new_probe else []
                def planner(*args):
                    return {'probes': extra, 'candidates': [entry]}
                result = discover(PROFILE, [{'name': 'clean', 'role': 'reference'},
                         {'name': 'bug', 'role': 'base', 'patch': case.patch('air-jump')}],
                         case.dir / 'out', runner=runner, planner=planner, probe_ids=['hold-right'])
                finding = next((f for f in result['findings'] if f['specId'] == 'planned-counter'), None)
                self.assertIsNotNone(finding, result['diagnostics'])
                self.assertEqual(finding['reproduction'], {'runs': 3, 'failures': 3})
                self.assertFalse(any(specs for _, specs in requested[:2]))
                self.assertEqual(sum(bool(specs) for _, specs in requested), 4)
                self.assertTrue(all(specs and specs[0]['operation'] == UI['operation']
                                    for name, specs in requested if '-repro' in name))
