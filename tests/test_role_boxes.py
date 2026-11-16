"""Configured role geometry: offline contracts/readers and named real Godot integrations."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from agents import observations as obs
from agents.engine_check import check_for_trace
from expectrail.contracts import validate
from harness import adapters, run as hr

ROOT = Path(__file__).resolve().parent.parent


def record(role, box, *, visible=True, ident=None):
    return dict(id=ident or role, role=role, worldBox=box, box=box,
                visible=visible, boundsSource='drawing')


def trace():
    return {'format': 'expectrail.trace/v0', 'ticks': 2, 'physicsTicksPerSecond': 60,
            'bindings': {k: {'group': k, 'texture': 'res://square.svg'}
                         for k in ('player', 'coin', 'enemy', 'projectile', 'beacon')},
            'viewport': [360, 240], 'capabilities': {'roleBoxes': True},
            'rows': [{'tick': i, 'player': [80, 116], 'body': [78, 100, 82, 110],
                      'view': [1, 0, 0, 1, 0, 0], 'ground': 128,
                      'roleObjects': [record('player', [68, 104, 92, 128]),
                                      record('coin', [30, 20, 36, 30]),
                                      record('enemy', [100, 30, 130, 60]),
                                      record('projectile', [90, 80, 94, 82]),
                                      record('beacon', [5, 5, 10, 15], visible=False)]}
                     for i in range(2)]}


class RoleReaderTest(unittest.TestCase):
    def test_measured_art_not_collision_feet_or_coin_constants(self):
        t = trace()
        with mock.patch.object(obs, '_player_world_box', side_effect=AssertionError('legacy player')), \
             mock.patch.object(obs, '_floor_y', side_effect=AssertionError('legacy floor')):
            got = obs.from_trace_synthetic(t)
            refs = obs.engine_refs_by_frame(t, (360, 240), [0, 1])
        validate(got, 'observations')
        for frame in got['frames']:
            self.assertEqual(frame['objects']['player'][0]['box'], [68, 104, 92, 128])
            self.assertEqual(frame['objects']['coin'][0]['box'], [30, 20, 36, 30])
            self.assertEqual(frame['objects']['beacon'], [])
        self.assertEqual(refs[0]['projectile'], [[90, 80, 94, 82]])
        self.assertEqual(refs[0]['enemy'], [[100, 30, 130, 60]])

    def test_missing_records_are_unmeasured_not_invented_detections(self):
        for missing in ('roleObjects', 'capability'):
            t = trace()
            if missing == 'roleObjects':
                for r in t['rows']: r.pop('roleObjects')
            else: t['capabilities'].clear()
            document = obs.from_trace_synthetic(t)
            self.assertEqual(document['frames'], [])
            from expectrail.evaluator import evaluate
            spec = json.loads((ROOT/'agents/specs/player-stays-above-ground.json').read_text())
            verdict = evaluate(spec, document)
            self.assertEqual(verdict['result'], 'needs-review')
            self.assertIn('not-exercised', verdict['reason'])
            self.assertEqual(obs.engine_refs_by_frame(t, (360, 240), [0]), {})

    def test_hidden_and_offscreen_objects_are_not_observations(self):
        t = trace()
        t['rows'][0]['roleObjects'][0]['visible'] = False
        t['rows'][1]['roleObjects'][0]['box'] = [400, 10, 424, 34]
        got = obs.from_trace_synthetic(t)
        self.assertEqual([f['objects']['player'] for f in got['frames']], [[], []])

    def test_empty_role_and_unrecorded_role_are_different(self):
        t = trace()
        t['rows'][0]['roleObjects'] = []
        refs = obs.engine_refs_by_frame(t, (360, 240), [0])
        self.assertEqual(refs[0]['coin'], [])
        self.assertNotIn('unbound', refs[0])

    def test_engine_agreement_supports_every_bound_role(self):
        checked = check_for_trace(trace(), [0])
        hit = {'box': [100, 30, 130, 60], 'score': 1}
        miss = {'box': [200, 30, 230, 60], 'score': 1}
        self.assertEqual(checked({0: {'enemy': [hit, miss]}}), {0: {'enemy': [hit]}})

    def test_bound_ground_is_measured_and_reference_ground_stays_trusted(self):
        t = trace(); t['bindings']['ground'] = {'node': 'Floor', 'texture': 'res://square.svg'}
        for r in t['rows']: r['roleObjects'].append(record('ground', [0, 150, 360, 174]))
        self.assertEqual(obs.engine_ground_by_frame(t, (360, 240), [0])[0]['ground'][0]['box'],
                         [0, 150, 360, 174])
        surfaces = [[[0, 128], [360, 128], [360, 152], [0, 152]]]
        with mock.patch.object(obs, 'surface_under', side_effect=AssertionError('bundled constants')):
            trusted = obs.with_reference_ground(t, surfaces)
        self.assertEqual(trusted['rows'][0]['ground'], 128)
        self.assertEqual(obs.engine_ground_by_frame(trusted, (360, 240), [0])[0]['ground'][0]['box'][1], 128)

    def test_replay_state_includes_roles_but_preserves_the_legacy_comparison(self):
        a = trace()['rows'][0]; b = copy.deepcopy(a)
        b['roleObjects'][1]['visible'] = False
        self.assertNotEqual(adapters.GODOT.trace_state(a), adapters.GODOT.trace_state(b))
        self.assertEqual(adapters.GODOT.trace_state({'player': [3, 4]}), [3, 4])

    def test_schema_and_examples_and_incomplete_role_data(self):
        t = trace(); validate(t, 'trace')
        for name in ('trace.json', 'trace-godot.json', 'trace-role-boxes.json'):
            validate(json.loads((ROOT/'contracts/examples'/name).read_text()), 'trace')
        for field in ('box', 'worldBox', 'visible', 'role', 'boundsSource', 'id'):
            bad = copy.deepcopy(t); bad['rows'][0]['roleObjects'][0].pop(field)
            with self.subTest(field=field), self.assertRaises(Exception): validate(bad, 'trace')
        bad = copy.deepcopy(t); bad['rows'][0].pop('roleObjects')
        with self.assertRaises(Exception): validate(bad, 'trace')


class RealRoleBoxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.tool_requirements import godot_binary
        cls.engine = godot_binary()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='expectrail-role-boxes-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.game = self.root/'game'
        shutil.copytree(ROOT/'tests/projects/config-lane', self.game)

    def config(self, roles):
        path = self.game/'expectrail.project.json'
        doc = json.loads(path.read_text()); doc['bindings'].update(roles)
        path.write_text(json.dumps(doc))

    def replay(self, name='run', route=None, game=None):
        hr.run(route or self.game/'walk.json', self.root/name, game=game or self.game,
               godot=self.engine, capture_frames=False, sandbox='off', fps=None)
        got = json.loads((self.root/name/'trace.json').read_text()); validate(got, 'trace')
        return got

    def test_config_lane_measured_player_and_ground_follow_camera(self):
        self.config({'ground': {'node': 'Floor', 'texture': 'res://square.svg'},
                     'coin': {'node': 'Lookalike', 'texture': 'res://square.svg'}})
        t = self.replay()
        self.assertEqual(t['viewport'], [360, 240])
        self.assertIs(t['capabilities']['roleBoxes'], True)
        self.assertEqual(len(t['rows']), 120)
        for i, r in enumerate(t['rows']):
            by_role = {o['role']: o for o in r['roleObjects']}
            self.assertEqual(set(by_role), {'player', 'ground', 'coin'})
            p = by_role['player']; x, y = r['player']
            self.assertEqual(p['worldBox'], [round(v, 3) for v in (x-12, y-12, x+12, y+12)])
            self.assertTrue(p['visible']); self.assertEqual(p['boundsSource'], 'drawing')
            view = obs._view_at(t['rows'], i)
            expected = obs._frame_box(view, p['worldBox'])
            for a, b in zip(p['box'], expected): self.assertAlmostEqual(a, b, delta=.003)
            self.assertEqual(by_role['ground']['worldBox'], [-500, 128, 1500, 152])
            self.assertEqual(by_role['ground']['boundsSource'], 'collision')
        got = obs.from_trace_synthetic(t, fps=60)
        self.assertEqual(len(got['frames']), 120)
        self.assertTrue(any(f['objects']['coin'] for f in got['frames']))
        # It is allowed to leave the camera as the bound player walks away.
        self.assertTrue(all(f['objects']['player'] for f in got['frames']))

    def test_dynamic_group_members_visibility_and_identity_are_recorded_each_tick(self):
        self.config({'coin': {'group': 'loot', 'texture': 'res://square.svg'},
                     'projectile': {'group': 'shots', 'texture': 'res://square.svg'}})
        script = self.game/'avatar.gd'
        script.write_text(script.read_text() + '''

var role_tick := 0
var item: Sprite2D
func _process(_delta):
    pass
func role_step():
    if role_tick == 2 or role_tick == 6:
        item = Sprite2D.new()
        item.name = "Spawn#2"
        item.texture = preload("res://square.svg")
        item.scale = Vector2(0.5, 0.25)
        item.position = Vector2(170, 110)
        item.add_to_group("loot")
        item.add_to_group("shots")
        get_tree().current_scene.add_child(item)
    if role_tick == 3:
        item.visible = false
    if role_tick == 4:
        item.free()
    role_tick += 1
''')
        text = script.read_text().replace('func _physics_process(delta):', 'func _physics_process(delta):\n    role_step()')
        # Keep a failure explicit if the fixture's signature changes.
        if '    role_step()' not in text:
            text = text.replace('func _physics_process(delta: float) -> void:',
                                'func _physics_process(delta: float) -> void:\n    role_step()')
        self.assertIn('    role_step()', text)
        script.write_text(text.expandtabs(4))
        t = self.replay(); rows = t['rows']
        coins = lambda i: [o for o in rows[i]['roleObjects'] if o['role'] == 'coin']
        self.assertEqual(coins(0), []); self.assertEqual(coins(1), [])
        self.assertEqual(len(coins(2)), 1); self.assertTrue(coins(2)[0]['visible'])
        self.assertEqual(coins(2)[0]['worldBox'], [164, 107, 176, 113])
        self.assertFalse(coins(3)[0]['visible']); self.assertEqual(coins(4), [])
        self.assertEqual(coins(2)[0]['id'], 'Spawn##2')
        self.assertEqual(coins(6)[0]['id'], 'Spawn##2#2')
        self.assertTrue(any(o['role'] == 'projectile' for o in rows[2]['roleObjects']))
        self.assertEqual(t, self.replay('repeat'))

    def test_never_found_and_ambiguous_non_player_roles_refuse_without_a_trace(self):
        scene = self.game/'main.tscn'
        scene.write_text(scene.read_text()+'\n[node name="Lookalike" type="Sprite2D" parent="Actors"]\ntexture = ExtResource("art")\n')
        for name, binding, words in (
            ('missing', {'group': 'never-spawned'}, ('coin', 'never-spawned', 'not found')),
            ('ambiguous', {'node': 'Lookalike'}, ('coin', 'Lookalike', 'ambiguous')),
        ):
            self.config({'coin': {**binding, 'texture': 'res://square.svg'}})
            with self.subTest(name=name), self.assertRaisesRegex(SystemExit, 'bindings.coin'): self.replay(name)
            log = (self.root/name/'godot.log').read_text()
            for word in words: self.assertIn(word, log)
            self.assertFalse((self.root/name/'trace.json').exists())

    def test_group_measures_multiple_rotated_mirrored_and_hidden_drawings(self):
        self.config({'coin': {'group': 'loot', 'texture': 'res://square.svg'}})
        scene = self.game/'main.tscn'
        scene.write_text(scene.read_text() + '\n[node name="Mirrored" type="Sprite2D" parent="." groups=["loot"]]\n'
                         'position = Vector2(120,80)\nscale = Vector2(-2,0.5)\ntexture = ExtResource("art")\n'
                         '[node name="UnusedArt" type="Sprite2D" parent="Mirrored"]\n'
                         'visible = false\nscale = Vector2(10,10)\ntexture = ExtResource("art")\n'
                         '[node name="Rotated" type="Sprite2D" parent="." groups=["loot"]]\n'
                         'position = Vector2(150,80)\nrotation = 0.7853981633974483\ntexture = ExtResource("art")\n'
                         '[node name="Hidden" type="Node2D" parent="."]\nvisible = false\n'
                         '[node name="Loot" type="Sprite2D" parent="Hidden" groups=["loot"]]\n'
                         'position = Vector2(170,80)\ntexture = ExtResource("art")\n')
        t = self.replay()
        coins = {o['id']: o for o in t['rows'][0]['roleObjects'] if o['role'] == 'coin'}
        self.assertEqual(set(coins), {'Mirrored', 'Rotated', 'Hidden/Loot'})
        self.assertEqual(coins['Mirrored']['worldBox'], [96, 74, 144, 86])
        import math
        radius = 12*math.sqrt(2)
        for got, want in zip(coins['Rotated']['worldBox'], [150-radius, 80-radius, 150+radius, 80+radius]):
            self.assertAlmostEqual(got, want, delta=.001)
        self.assertFalse(coins['Hidden/Loot']['visible'])
        self.assertEqual(len(obs.from_trace_synthetic(t)['frames'][0]['objects']['coin']), 2)

    def test_a_present_but_unmeasurable_role_names_the_problem(self):
        self.config({'coin': {'node': 'Actors', 'texture': 'res://square.svg'}})
        # Actors must not borrow the separately bound player's drawing.
        with self.assertRaises(SystemExit): self.replay()
        log = (self.root/'run/godot.log').read_text()
        for word in ('bindings.coin', 'Actors', 'bounds'): self.assertIn(word, log)
        self.assertFalse((self.root/'run/trace.json').exists())

    def test_animated_sprite_measures_current_frame_without_mirroring_its_offset(self):
        self.config({'enemy': {'group': 'animated', 'texture': 'res://square.svg'}})
        script = self.game/'avatar.gd'
        source = script.read_text().replace('func _physics_process(delta: float) -> void:',
                                           'func _physics_process(delta: float) -> void:\n    animate_role()').expandtabs(4)
        script.write_text(source + """
var animation_tick := 0
var animation_node: AnimatedSprite2D
func animate_role():
    if animation_tick == 0:
        var frames := SpriteFrames.new()
        frames.clear("default")
        for size in [Vector2i(10,6), Vector2i(20,8)]:
            var texture := GradientTexture2D.new()
            texture.width = size.x
            texture.height = size.y
            texture.gradient = Gradient.new()
            frames.add_frame("default", texture)
        animation_node = AnimatedSprite2D.new()
        animation_node.name = "Animated"
        animation_node.sprite_frames = frames
        animation_node.centered = false
        animation_node.offset = Vector2(3,4)
        animation_node.flip_h = true
        animation_node.position = Vector2(170,80)
        animation_node.scale = Vector2(2,1)
        animation_node.add_to_group("animated")
        get_tree().current_scene.add_child(animation_node)
    animation_node.frame = animation_tick % 2
    animation_tick += 1
""")
        t = self.replay()
        boxes = [next(o['worldBox'] for o in r['roleObjects'] if o['role'] == 'enemy')
                 for r in t['rows']]
        self.assertEqual(boxes[0], [176, 84, 196, 90])
        self.assertEqual(boxes[1], [176, 84, 216, 92])
        self.assertEqual(boxes[2], boxes[0])

    def test_crate_run_polygon_player_uses_its_own_measured_feet(self):
        base = ROOT/'tests/projects/crate-run'
        t = self.replay(game=base/'project', route=base/'routes/walk.json')
        self.assertTrue(t['rows'])
        for r in t['rows']:
            p = next(o for o in r['roleObjects'] if o['role'] == 'player')
            x, y = r['player']
            for a, b in zip(p['worldBox'], [x-16, y-16, x+16, y+16]):
                self.assertAlmostEqual(a, b, delta=.002)
            self.assertEqual(p['boundsSource'], 'drawing')
        got = obs.from_trace_synthetic(t, fps=60)
        self.assertTrue(all(f['objects']['player'] for f in got['frames']))


if __name__ == '__main__':
    unittest.main()
