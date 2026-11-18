"""Public-menu trace gap (#285): engine Label state, never a pixel verdict."""
import json
import tempfile
import unittest
from pathlib import Path

from expectrail.contracts import validate_v1
from expectrail.jit import offer, intent
from expectrail.trace import signals
from expectrail.trace.evaluator import evaluate
from expectrail.trace.normalize import EpisodeError, from_run_dir
from tests.test_trace_evaluator import episode, rows, spec

REPO = Path(__file__).resolve().parents[1]


def ui_episode(values):
    data = rows(len(values))
    for row, value in zip(data, values):
        row['uiIntegers'] = value
    return episode(data)


class UiIntegerTest(unittest.TestCase):
    def test_reader_preserves_optional_label_state_and_contract(self):
        ep = ui_episode([[], [0], [5]])
        self.assertEqual([s.get('uiIntegers') for s in ep['samples']], [[], [0], [5]])
        validate_v1(ep, 'episode')

    def test_single_value_at_end_including_zero_and_negative(self):
        for value in (0, 5, 10, -3):
            self.assertEqual(signals.SIGNALS['ui_integer_at_end'](ui_episode([[], [value]])), value)

    def test_ambiguous_empty_absent_overflow_and_stale_are_unknown(self):
        for ep in (episode(rows(2)), ui_episode([[]]), ui_episode([[5, 5]]),
                   ui_episode([None]), ui_episode([[5], []]), ui_episode([[5], None])):
            self.assertIsNone(signals.SIGNALS['ui_integer_at_end'](ep))

    def test_reader_refuses_malformed_values_instead_of_inventing_a_reading(self):
        for value in ([True], [1.0], ['5'], [10**9 + 1], [0] * 33, {}, '5'):
            with self.subTest(value=value), self.assertRaisesRegex(EpisodeError, 'uiIntegers'):
                ui_episode([value])

    def test_cross_signal_check_catches_both_counter_defects_without_a_magic_count(self):
        rule = spec({'type': 'signal_compare', 'leftSignal': 'coins_collected',
                     'rightSignal': 'ui_integer_at_end', 'comparator': 'eq', 'toleranceAbs': 0})
        for value, expected in (([5], 'pass'), ([0], 'fail'), ([10], 'fail'),
                                ([], 'insufficient_observation')):
            data = rows(2)
            data[0].update(coins=[[i, 0] for i in range(5)], uiIntegers=[])
            data[1].update(coins=[], uiIntegers=value)
            self.assertEqual(evaluate(rule, episode(data))['result'], expected)

    def test_only_evidence_offers_expose_the_new_signal(self):
        for setting in offer.ALL:
            meanings = offer.meanings(setting)
            self.assertEqual('ui_integer_at_end' in meanings, setting in (offer.EVIDENCE, offer.MENU, offer.PIXEL))
            self.assertEqual(intent._offered(setting), meanings)

    def test_unknown_trace_is_not_reconstructed_from_a_counter_value(self):
        rule = spec({'type': 'signal_compare', 'leftSignal': 'coins_collected',
                     'rightSignal': 'ui_integer_at_end', 'comparator': 'eq', 'toleranceAbs': 0})
        self.assertEqual(evaluate(rule, ui_episode([[5]]))['result'], 'insufficient_observation')

    def test_comparison_honors_the_window_and_tolerance(self):
        data = rows(4)
        for i, row in enumerate(data):
            row['uiIntegers'] = [i]
        rule = spec({'type': 'signal_compare', 'leftSignal': 'ui_integer_at_end',
                     'rightSignal': 'player_dx_px', 'comparator': 'eq', 'toleranceAbs': 1},
                    window={'kind': 'ticks', 'fromTick': 0, 'toTick': 1})
        self.assertEqual(evaluate(rule, episode(data))['result'], 'pass')
        rule['operation']['toleranceAbs'] = 0
        self.assertEqual(evaluate(rule, episode(data))['result'], 'fail')
        rule['window'] = {'kind': 'ticks', 'fromTick': 10, 'toTick': 12}
        self.assertEqual(evaluate(rule, episode(data))['result'], 'not_exercised')

    def test_proposer_parser_restricts_new_language_to_evidence(self):
        from tests.jit_fixtures import PROFILE
        profile = json.loads(PROFILE.read_text())
        op = {'type': 'signal_compare', 'leftSignal': 'coins_collected',
              'rightSignal': 'ui_integer_at_end', 'comparator': 'eq', 'toleranceAbs': 0}
        answer = json.dumps({'candidates': [{'id': 'counter', 'class': 'player',
                    'statement': 'The reported counter agrees with collection.',
                    'claimId': 'model.unbound', 'operation': op, 'appliesTo': ['menu']} ]})
        for setting in offer.ALL:
            if not offer.shows_evidence(setting):
                with self.assertRaises(intent.IntentUnavailable):
                    intent.parse_answer(answer, profile, {'menu'}, offer=setting)
            else:
                probes, entries, notes = intent.parse_answer(answer, profile, {'menu'}, offer=setting)
                self.assertEqual(entries[0]['spec']['operation'], op)
                self.assertEqual(entries[0]['applies'], {'kind': 'probes', 'ids': ['menu']})
                self.assertEqual(entries[0]['spec']['expectationRef']['authority'], 'model_prior')
        # A relation using the new signal is also held out of the old two offers.
        relation = {'type': 'relation', 'signal': 'ui_integer_at_end', 'left': 'menu',
                    'right': 'menu', 'comparator': 'eq', 'toleranceAbs': 0}
        for setting in (offer.BASELINE, offer.SIGNALS_REACH):
            self.assertIsNotNone(intent._operation_unoffered(relation, setting))

    def test_saved_proposal_reader_rechecks_operation_offer(self):
        import hashlib
        from tests.jit_fixtures import PROFILE
        profile = json.loads(PROFILE.read_text())
        op = {'type': 'signal_compare', 'leftSignal': 'coins_collected',
              'rightSignal': 'ui_integer_at_end', 'comparator': 'eq', 'toleranceAbs': 0}
        rule = spec(op)
        rule.update(id='jit-ui', origin='AUTO_DIFF')
        rule['expectationRef']['authority'] = 'model_prior'
        doc = {'format': intent.PROPOSAL_FORMAT, 'offer': offer.EVIDENCE, 'candidate': intent.SHOWN,
               'patchSha256': hashlib.sha256(b'patch').hexdigest(), 'probes': [],
               'candidates': [{'spec': rule, 'applies': {'kind': 'all'}}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'proposal.json'
            for setting in (offer.EVIDENCE, offer.BASELINE, offer.SIGNALS_REACH):
                doc['offer'] = setting
                path.write_text(json.dumps(doc))
                reader = intent.from_proposal(path, offer=setting)
                if offer.shows_evidence(setting):
                    self.assertEqual(reader('report', 'patch', {}, profile, [])['candidates'][0]['spec']['operation'], op)
                else:
                    with self.assertRaisesRegex(intent.IntentUnavailable, 'not offered'):
                        reader('report', 'patch', {}, profile, [])

    def test_contract_examples_validate_as_handwritten_examples(self):
        from expectrail.contracts import validate
        for name, kind in (('trace-ui-integers', 'trace'),
                           ('episode-ui-integers.v1', 'episode'),
                           ('trace-spec-ui-integers.v1', 'trace-spec')):
            doc = json.loads((REPO / 'contracts/examples' / (name + '.json')).read_text())
            (validate if kind == 'trace' else validate_v1)(doc, kind)


class PublicCounterEngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.tool_requirements import godot_binary
        from expectrail.jit.probes import jit_library
        from expectrail.repro.menu import menu_probes, declared_actions
        from expectrail.discovery.route_compiler import compile_route
        from harness.run import run
        godot = godot_binary(switch='EXPECTRAIL_ENGINE_TESTS')
        cls.tmp = tempfile.TemporaryDirectory(prefix='expectrail-ui-counter-')
        cls.addClassCleanup(cls.tmp.cleanup)
        actions = json.loads((REPO / 'discovery/platformer.profile.json').read_text())['actions']
        probes = menu_probes(jit_library(actions), ['toggle_pause'], actions,
                            declared_actions(REPO / 'game/platformer/project.godot'))
        probe = next(p for p in probes if p['id'].startswith('hold-right-'))
        route = compile_route(probe['program'], name=probe['id'], description=probe['description'],
                              actions=[*actions, 'toggle_pause'])
        path = Path(cls.tmp.name) / 'route.json'
        path.write_text(json.dumps(route))
        cls.episodes = {}
        for name in ('clean-a', 'clean-b', 'coin-counter-stuck', 'coin-counts-twice'):
            out = Path(cls.tmp.name) / name
            patches = [] if name.startswith('clean-') else [REPO / 'bench/jit/public' / name / 'defect.patch']
            run(path, out, patches=patches, godot=godot, capture_frames=False,
                trace_specs=[json.loads((REPO / "contracts/examples/trace-spec-ui-integers.v1.json").read_text())])
            cls.episodes[name] = from_run_dir(out, route, episode_id=name)

    def test_public_menu_route_exposes_both_recorded_counter_misses(self):
        got = {name: signals.SIGNALS['ui_integer_at_end'](ep) for name, ep in self.episodes.items()}
        self.assertEqual(got, {'clean-a': 5, 'clean-b': 5, 'coin-counter-stuck': 0, 'coin-counts-twice': 10})
        for name in ('clean-a', 'clean-b'):
            self.assertTrue(all(s['uiIntegers'] == [] for s in self.episodes[name]['samples'][:100]),
                            'the initially hidden menu must not supply a counter reading')
        rule = json.loads((REPO / 'contracts/examples/trace-spec-ui-integers.v1.json').read_text())
        judged = {name: evaluate(rule, ep)['result'] for name, ep in self.episodes.items()}
        self.assertEqual(judged, {'clean-a': 'pass', 'clean-b': 'pass',
                                  'coin-counter-stuck': 'fail', 'coin-counts-twice': 'fail'})
        print('Public menu engine readings (not a reproduction rate):', got)
