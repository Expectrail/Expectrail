"""The outside trial selects one check per project. No game or model runs here."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from expectrail.contracts import load
from expectrail.gate.verify import evaluate, observations, run_gate
from tests.test_ci_gate import FakeReplay
from tools.dodge_play_area import region
from tools import outside_trial as trial


def judge(spec, positions, ground=None, visible=True):
    rows = [{"tick": tick, "player": pos, "ground": ground, "view": [1, 0, 0, 1, 0, 0]}
            for tick, pos in enumerate(positions)]
    for i, row in enumerate(rows):
        state = visible[i] if isinstance(visible, list) else visible
        if state is not None:
            row['playerVisible'] = state
        if row['player'] is not None:
            x, y = row['player']
            row['body'] = [x-27, y-34, x+27, y+34]
    trace = {"physicsTicksPerSecond": 60, "rows": rows}
    return evaluate(spec, observations(trace, "0" * 64), trace=trace)


def clean_trace():
    return {'rows':[{'tick':0, 'player':[240,450], 'body':[213,416,267,484],
                     'playerVisible':True, 'view':[1,0,0,1,0,0]}]}


class DodgeCheckTest(unittest.TestCase):
    def setUp(self):
        projects = {p["name"]: p for p in trial.load_list()}
        self.kinematic = projects["kinematic-character"]
        self.dodge = projects["dodge-the-creeps"]

    def test_layout_selects_the_project_spec_and_keeps_the_default_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for project, expected in [(self.dodge, trial.REPO / "tests/outside/specs/dodge-play-area.json"),
                                      (self.kinematic, trial.SPEC)]:
                with self.subTest(project=project["name"]):
                    folder = root / "source" / project["path"]
                    folder.mkdir(parents=True)
                    (folder / "project.godot").touch()
                    checkout = trial.lay_out(project, root / "source", root / "work")
                    self.assertEqual([p.name for p in (checkout / "specs").iterdir()], [expected.name])
                    self.assertEqual((checkout / "specs" / expected.name).read_bytes(), expected.read_bytes())

    def test_change_expectations_and_the_kinematic_ground_check(self):
        for project, expected in [(self.dodge, {"broken": "reject", "harmless": "needs-review"}),
                                  (self.kinematic, {"broken": "reject", "harmless": "needs-review",
                                                    "invisible": "needs-review"})]:
            self.assertEqual({c["name"]: c["expect"] for c in project.get("changes", [])}, expected)
        spec = load(trial.SPEC, "test-spec")
        self.assertEqual(judge(spec, [[10, 50]] * 120, ground=70)["result"], "pass")
        self.assertEqual(judge(spec, [[10, 100]], ground=70)["result"], "fail")

    def test_kinematic_gate_verdicts_with_stand_in_replays_and_no_vision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "source" / self.kinematic["path"]
            src.mkdir(parents=True)
            (src / "project.godot").touch()
            base = trial.lay_out(self.kinematic, root / "source", root / "base")
            head = trial.lay_out(self.kinematic, root / "source", root / "head")
            for change in self.kinematic["changes"]:
                with self.subTest(change=change["name"]):
                    bug = head / "project/BUG"    # FakeReplay's fall-through switch
                    if change["name"] == "broken":
                        bug.touch()
                    else:
                        bug.unlink(missing_ok=True)
                    doc = run_gate(repo=head, base=base, game="project", routes=["routes/*.json"],
                                   specs="specs", work=root / "work" / change["name"],
                                   out=root / "out" / change["name"], replay=FakeReplay(), rule="both")
                    self.assertEqual(doc["decision"], change["expect"])
                    after = doc["checks"][0]["observed"]["after"]
                    self.assertEqual(after["engine"], "fail" if bug.exists() else "pass")

    def test_region_reads_native_viewport_size_and_refuses_a_scaled_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project.godot"
            display = "[display]\nwindow/size/viewport_width=100\nwindow/size/viewport_height=200\n"
            project.write_text(display + "[other]\nwindow/size/viewport_width=1000\n")
            left, top, right, bottom = region(project, clean_trace())
            project.write_text(display.replace("=100", "=110").replace("=200", "=250"))
            self.assertEqual(region(project, clean_trace()), [left, top, right + 10, bottom + 50])
            project.write_text(display + "window/size/window_width_override=50\n")
            with self.assertRaisesRegex(ValueError, "native size"):
                region(project, clean_trace())

    def test_dodge_origin_may_touch_each_edge_but_may_not_cross_it(self):
        spec = load(trial.REPO / self.dodge["spec"], "test-spec")
        # Native viewport of the pinned Dodge project. No ground in any row.
        w, h = 480, 720
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "project.godot"
            settings.write_text(f"[display]\nwindow/size/viewport_width={w}\nwindow/size/viewport_height={h}\n")
            self.assertEqual(spec["assertion"]["region"]["box"], region(settings, clean_trace()))
        inside = [[0, 0], [w, 0], [w, h], [0, h], [w - 1, h - 1]] * 24
        self.assertEqual(judge(spec, inside)["result"], "pass")
        for outside in ([-1, h / 2], [w + 1, h / 2], [w / 2, -1], [w / 2, h + 1]):
            with self.subTest(outside=outside):
                verdict = judge(spec, inside + [outside])
                self.assertEqual((verdict["result"], verdict["firstFrame"]), ("fail", len(inside)))
        self.assertEqual(judge(spec, [[0, 0], None])["result"], "needs-review")

    def test_spec_must_be_an_outside_spec_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "projects.json"
            for value in (None, "tests/outside/specs/../escape.json", "/tmp/spec.json",
                          "tests/outside/specs/missing.json"):
                with self.subTest(value=value):
                    doc = json.loads(trial.LIST.read_text())
                    next(p for p in doc["projects"] if p["name"] == self.dodge["name"])["spec"] = value
                    manifest.write_text(json.dumps(doc))
                    with self.assertRaises(trial.TrialError):
                        trial.load_list(manifest)

    def test_a_project_spec_cannot_follow_a_link(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(trial, "REPO", Path(tmp).resolve()):
            spec = trial.REPO / self.dodge["spec"]
            spec.parent.mkdir(parents=True)
            target = trial.REPO / "other.json"
            target.write_text("{}")
            spec.symlink_to(target)
            with self.assertRaisesRegex(trial.TrialError, "symbolic links"):
                trial.project_spec(self.dodge)

    def test_hidden_frames_are_not_exercised_and_no_round_cannot_pass(self):
        spec = load(trial.REPO / self.dodge['spec'], 'test-spec')
        hidden = judge(spec, [[-100, -100]] * 150, visible=False)
        self.assertEqual(hidden['result'], 'needs-review')
        self.assertEqual(hidden['coverage']['semanticResult'], 'not_exercised')
        self.assertEqual(hidden['framesJudged'], 0)
        self.assertEqual(hidden['coverage']['framesNotExercised'], list(range(150)))
        self.assertIn('not-exercised', hidden['reason'])
        mixed = judge(spec, [[0, 0]] * 10 + [[240, 450]] * 120 + [[1000, 1000]] * 10,
                      visible=[False] * 10 + [True] * 120 + [False] * 10)
        self.assertEqual(mixed['result'], 'pass')
        self.assertEqual(mixed['framesJudged'], 120)
        self.assertEqual(mixed['coverage']['framesNotExercised'], list(range(10)) + list(range(130, 140)))

    def test_unknown_visibility_does_not_pass_and_visible_escape_still_fails(self):
        spec = load(trial.REPO / self.dodge['spec'], 'test-spec')
        unknown = judge(spec, [[240, 450]] * 120, visible=None)
        self.assertEqual(unknown['result'], 'needs-review')
        self.assertEqual(unknown['coverage']['framesVisibilityUnknown'], list(range(120)))
        for flag in (True, None, False):
            with self.subTest(other_frames_visible=flag):
                verdict = judge(spec, [[240, 450]] * 120 + [[481, 450]], visible=[flag] * 120 + [True])
                self.assertEqual(verdict['result'], 'fail')
                self.assertEqual(verdict['firstFrame'], 120)
        short = judge(spec, [[240, 450]] * 119, visible=True)
        self.assertEqual(short['result'], 'needs-review')
        self.assertEqual(short['coverage']['semanticResult'], 'not_exercised')

    def test_filter_uses_last_tick_in_frame_at_the_capture_rate(self):
        spec = load(trial.REPO / self.dodge['spec'], 'test-spec')
        # This test is about frame mapping, not Dodge's 120-frame obligation.
        spec['coverage']['minFrames'] = 2
        rows = [{'tick': t, 'player': [240,450], 'playerVisible': t % 2 == 1,
                 'view':[1,0,0,1,0,0], 'body':[213,416,267,484]} for t in range(4)]
        trace = {'physicsTicksPerSecond':60,'rows':rows}
        from agents.observations import from_trace_synthetic
        obs = from_trace_synthetic(trace, fps=30)
        verdict = evaluate(spec, obs, trace=trace, capture_fps=30)
        self.assertEqual(verdict['result'], 'pass')
        self.assertEqual(verdict['framesJudged'], 2)
        self.assertEqual(verdict['coverage']['framesNotExercised'], [])
        from expectrail.contracts import digest
        self.assertEqual(verdict['observations']['sha256'], digest(obs))
        from expectrail.gate.verify import judge_run
        trace['unknownActions'] = []
        run = {'trace': trace, 'engineObservations': obs}
        self.assertEqual(judge_run(spec, run, ticks=4, capture_fps=30)['result'], 'pass')
        trace['rows'].append(dict(rows[-1]))
        self.assertEqual(evaluate(spec, obs, trace=trace, capture_fps=30)['result'], 'needs-review')

    def test_region_refuses_missing_measurements_instead_of_using_bundled_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / 'project.godot'
            project.write_text('[display]\nwindow/size/viewport_width=480\nwindow/size/viewport_height=720\n')
            for trace in ({}, {'rows':[{'player':[0,0]}]},
                          {'rows':[{'player':[0,0],'playerVisible':True,'view':[1,0,0,1,0,0]}]}):
                with self.subTest(trace=trace), self.assertRaises(ValueError):
                    region(project, trace)

    def test_changed_spec_is_unapproved_and_contract_examples_validate(self):
        from expectrail.contracts import validate
        spec = load(trial.REPO / self.dodge['spec'], 'test-spec')
        self.assertNotIn('approval', spec)
        for name, kind in [('trace-player-visibility.json','trace'),
                           ('test-spec-player-visibility.json','test-spec'),
                           ('verdict-player-visibility.json','verdict')]:
            doc = json.loads((trial.REPO/'contracts/examples'/name).read_text())
            self.assertEqual(validate(doc, kind), kind)
        code = (trial.REPO/'harness/godot/expectrail_harness.gd').read_text()
        self.assertIn('row["playerVisible"] = _player.is_visible_in_tree()', code)

    def test_gate_keeps_no_vision_uncertain_and_rejects_a_real_visible_escape(self):
        from expectrail.gate.verify import judge_run
        spec = load(trial.REPO / self.dodge['spec'], 'test-spec')
        for broken in (False, True):
            rows = [{'tick': t, 'player':[481 if broken and t == 125 else 240,450],
                     'body': [454 if broken and t == 125 else 213,416,
                              508 if broken and t == 125 else 267,484],
                     'view':[1,0,0,1,0,0], 'playerVisible': t >= 10} for t in range(140)]
            trace = {'physicsTicksPerSecond':60,'rows':rows,'unknownActions':[]}
            run = {'trace':trace,'engineObservations':observations(trace,'0'*64)}
            result = judge_run(spec, run, rule='both', ticks=140, capture_fps=60)
            self.assertEqual(result['result'], 'fail' if broken else 'needs-review')
            self.assertEqual(result['observed']['engine'], 'fail' if broken else 'pass')
            if broken:
                self.assertEqual(result['frame'], 125)

    def test_visibility_filter_is_opt_in_and_does_not_hide_gaps(self):
        spec = load(trial.REPO / self.dodge['spec'], 'test-spec')
        spec['coverage'].pop('whenPlayerVisible')
        self.assertEqual(judge(spec, [[481,450]], visible=False)['result'], 'fail')
        spec['coverage']['whenPlayerVisible'] = True
        rows = [{'tick':t, 'player':[240,450], 'playerVisible':True,
                 'view':[1,0,0,1,0,0]} for t in range(140)]
        trace = {'physicsTicksPerSecond':60,'rows':rows}
        obs = observations(trace,'0'*64)
        obs['frames'].pop(20)
        result = evaluate(spec,obs,trace=trace,expected_frames=list(range(140)))
        self.assertEqual(result['result'], 'needs-review')
        self.assertFalse(result['coverage']['completeWindow'])
