"""Observable movement of a single recorded Godot drawing on an exact tick interval."""
import json
import unittest
from pathlib import Path

from expectrail import approval, contracts
from expectrail.coverage import checkpoint
from expectrail.evaluator import evaluate
from expectrail.gate import record
from expectrail.onboard_review import check_words
from tests.test_evaluator import det, obs, spec


ROOT = Path(__file__).resolve().parents[1]
WITNESS = dict(type='role-displacement', role='ball', fromTick=40, toTick=50,
               axis='y', minIncreasePx=40)


def movement_trace():
    rows = []
    for tick in range(40, 51):
        top = 100 + 4 * (tick - 40)
        ball = {'id': 'Level/Ball', 'role': 'ball', 'visible': True, 'boundsSource': 'drawing',
                'worldBox': [0, top, 8, top + 8], 'box': [3, 4, 11, 12]}
        rows.append({'tick': tick, 'roleObjects': [ball], 'player': [0, tick * 10]})
    return {'capabilities': {'roleBoxes': True}, 'bindings': {'ball': {'node': 'Ball'}}, 'rows': rows}


def movement_spec(witness):
    doc = spec({'type': 'visible', 'object': 'ball'}, objects=['ball'],
               window={'fromFrame': 40, 'toFrame': 50})
    doc['coverage'] = {'reached': [witness]}
    return doc


class BoundRoleMovementTest(unittest.TestCase):
    def test_moving_player_cannot_witness_a_stationary_ball(self):
        trace = movement_trace()
        doc = movement_spec(WITNESS)
        observed = obs(*[(row['tick'], {'ball': det((1, 2, 9, 10))}) for row in trace['rows']])
        self.assertEqual(evaluate(doc, observed, trace=trace)['result'], 'pass')
        for row in trace['rows']:
            row['roleObjects'][0]['worldBox'] = [0, 100, 8, 108]
        result = evaluate(doc, observed, trace=trace)
        self.assertEqual((result['result'], result['coverage']['status']), ('needs-review', 'not-reached'))
        self.assertIn('ball moved 0 world pixels down between ticks 40 and 50', result['reason'])
        self.assertIn('requires 40', result['reason'])
        del trace['rows'][5]
        result = evaluate(doc, observed, trace=trace)
        self.assertEqual((result['result'], result['coverage']['status']),
                         ('needs-review', 'insufficient-observation'))
        self.assertIn('check the visible ball drawing at each tick from 40 to 50', result['reason'])

    def test_the_signed_inclusive_threshold_uses_world_coordinates(self):
        trace = movement_trace()
        self.assertIs(checkpoint(WITNESS, trace), True)
        self.assertIs(checkpoint(dict(WITNESS, minIncreasePx=40.001), trace), False)
        self.assertIs(checkpoint(dict(WITNESS, axis='x'), trace), False)
        for row in trace['rows']:
            # Y moves up. X increases by exactly 0.2 at the endpoints; the camera box stays put.
            left = 0.1 if row['tick'] == 40 else 0.3
            row['roleObjects'][0]['worldBox'] = [left, -row['tick'], left + 8, 8 - row['tick']]
        self.assertIs(checkpoint(dict(WITNESS, axis='x', minIncreasePx=0.2), trace), True)
        self.assertIs(checkpoint(dict(WITNESS, minIncreasePx=1), trace), False)

    def test_missing_ambiguous_hidden_or_replaced_drawing_at_any_tick_is_unknown(self):
        for change in ({'id': 'Level/Ball#2'}, {'id': None}, {'id': ''}, {'role': 'other'},
                       {'visible': False}, {'visible': 1}, {'boundsSource': 'collision'},
                       {'worldBox': None}, {'worldBox': [0, 1, 2, 0]}, {'worldBox': [0, 1, 0, 2]},
                       {'worldBox': [0, False, 2, 2]}, {'worldBox': [float('inf'), 1, 2, 2]},
                       {'worldBox': [float('nan'), 1, 2, 2]}):
            with self.subTest(change=change):
                trace = movement_trace()
                trace['rows'][5]['roleObjects'][0].update(change)
                self.assertIsNone(checkpoint(WITNESS, trace))
        for objects in (None, [], [None], [{'role': 'ball', 'id': 'other'}]):
            with self.subTest(objects=objects):
                trace = movement_trace()
                row = trace['rows'][4]
                if objects:
                    row['roleObjects'] += objects
                else:
                    row['roleObjects'] = objects
                self.assertIsNone(checkpoint(WITNESS, trace))

    def test_two_roles_may_bind_the_same_node_but_the_target_role_must_be_unique(self):
        trace = movement_trace()
        roles = trace['rows'][0]['roleObjects']
        roles.append(dict(roles[0], role='enemy'))
        trace['bindings']['enemy'] = {'node': 'Ball'}
        self.assertIs(checkpoint(WITNESS, trace), True)
        roles.append(roles[0])
        self.assertIsNone(checkpoint(WITNESS, trace))

    def test_a_resized_endpoint_cannot_claim_translation(self):
        trace = movement_trace()
        trace['rows'][-1]['roleObjects'][0]['worldBox'] = [0, 100, 8, 188]
        self.assertIsNone(checkpoint(WITNESS, trace))

    def test_requires_unambiguous_contiguous_ordered_ticks_and_measured_bindings(self):
        for field, value in (('rows', None), ('rows', [None]), ('capabilities', {'roleBoxes': False}),
                             ('bindings', {}), ('bindings', {'ball': {}}),
                             ('bindings', {'ball': {'group': 'Balls', 'node': 'Ball'}})):
            with self.subTest(field=field, value=value):
                trace = movement_trace()
                trace[field] = value
                self.assertIsNone(checkpoint(WITNESS, trace))
        for tick in (44, 46, True, 45.5):
            with self.subTest(tick=tick):
                trace = movement_trace()
                trace['rows'][5]['tick'] = tick
                self.assertIsNone(checkpoint(WITNESS, trace))
        trace = movement_trace()
        trace['rows'].reverse()
        self.assertIsNone(checkpoint(WITNESS, trace))
        for invalid in ({'toTick': 40}, {'fromTick': 55}, {'toTick': 10**100}, {'minIncreasePx': 0},
                        {'minIncreasePx': float('inf')}, {'minIncreasePx': True}, {'axis': 'z'}):
            with self.subTest(invalid=invalid):
                self.assertIsNone(checkpoint(dict(WITNESS, **invalid), movement_trace()))

    def test_both_schema_readers_and_the_review_page_describe_the_draft_witness(self):
        doc = movement_spec(WITNESS)
        schema = contracts.schema('test-spec')
        self.assertEqual(contracts.validate(doc), 'test-spec')
        self.assertEqual(record.errors(doc, schema), [])
        window = check_words(doc)['window']
        for word in ('40', '50', 'ball', 'world pixels down', 'visible drawing'):
            self.assertIn(word, window)
        for invalid in ({'role': ''}, {'role': '1'}, {'axis': 'z'}, {'minIncreasePx': 0},
                        {'fromTick': -1}, {'toTick': 1.5}, {'unexpected': 1}):
            with self.subTest(invalid=invalid):
                doc = movement_spec(dict(WITNESS, **invalid))
                self.assertTrue(record.errors(doc, schema))
                with self.assertRaises(contracts.ContractError):
                    contracts.validate(doc)

    def test_existing_legacy_approval_cannot_cover_a_new_checkpoint(self):
        doc = json.loads((ROOT / 'contracts/examples/test-spec.json').read_text())
        self.assertIn('approval', doc)
        schema = contracts.schema('test-spec')
        self.assertEqual(record.errors(doc, schema), [])
        self.assertEqual(contracts.validate(doc), 'test-spec')
        doc['coverage'] = {'reached': [WITNESS]}
        self.assertTrue(record.errors(doc, schema))
        with self.assertRaises(contracts.ContractError):
            contracts.validate(doc)


    def test_changing_coverage_invalidates_an_existing_content_bound_approval(self):
        doc = json.loads((ROOT / 'agents/specs/player-stays-above-ground.json').read_text())
        self.assertEqual(approval.state(doc), approval.BOUND)
        doc['coverage'] = {'reached': [WITNESS]}
        self.assertEqual(contracts.validate(doc), 'test-spec')
        self.assertEqual(record.errors(doc, contracts.schema('test-spec')), [])
        self.assertEqual(approval.state(doc), approval.MISMATCH)
