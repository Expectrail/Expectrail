"""#257: actual capture placement, identity and completeness, without model calls."""
import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from expectrail import contracts, evaluator, observation_timeline as timeline
from expectrail.gate import verify
from agents.observations import from_trace_synthetic

ROOT = Path(__file__).resolve().parent.parent
SPEC = {"format": "expectrail.test-spec/v0", "id": "player-inside", "title": "Player stays inside",
        "objects": {"player": {"prompt": "player", "minScore": .5}},
        "assertion": {"type": "inside-region", "object": "player", "region": {"box": [0, 0, 100, 100]}}}


def png(width=128, height=96, shade=0):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    data = (b"\0" + bytes([shade % 255, 0, 0]) * width) * height
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(data)) + chunk(b"IEND", b"")


def trace_at(end_ticks=(1, 3, 5, 7, 9, 11), tps=120, fps=60, phase="post-physics-pre-draw"):
    rows = [{"tick": n, "frame": n // 2, "player": [15, 6.75], "body": [10, 10, 20, 20],
             "view": [1, 0, 0, 1, 0, 0], "onFloor": True, "playerVisible": True}
            for n in range(end_ticks[-1] + 1)]
    draws, previous = [], -1
    for n, tick in enumerate(end_ticks):
        draws.append({"frame": n, "tick": tick, "tickInterval": [min(previous + 1, tick), tick],
                      "phase": phase, "viewport": [128, 96], "transform": [1, 0, 0, 1, 0, 0]})
        previous = tick
    return {"format": "expectrail.trace/v0", "ticks": len(rows), "physicsTicksPerSecond": tps,
            "unknownActions": [], "rows": rows, "captureTimeline": {"fps": fps, "frames": draws}}


class TimelineTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.frames = self.root / "frames"; self.frames.mkdir()
        self.trace = trace_at()
        for n in range(6):
            (self.frames / f"f{n:08d}.png").write_bytes(png(shade=n))
        self.run = {"trace": self.trace, "framesDir": self.frames, "replaySha256": "a" * 64,
                    "timelineRequired": True,
                    "engineObservations": from_trace_synthetic(self.trace, "a" * 64)}
        old = {"format": "expectrail.observations/v0", "replay": {"sha256": "a" * 64},
               "model": {"name": "scripted-pixels"}, "frames": [{"frame": n, "objects": {
                   "player": [{"box": [10, 10, 20, 20], "score": .9}]}} for n in range(6)]}
        self.seen = timeline.emit(old, self.trace, self.frames)

    def judge(self, seen=None, spec=SPEC):
        document = self.seen if seen is None else seen
        class Observer:
            def look(self, *args, **kwargs): return document
        return verify.judge_run(spec, self.run, rule="both", visual=Observer(), ticks=12)

    def test_clean_pass_and_each_observation_names_its_provenance(self):
        contracts.validate(self.seen, "observations")
        self.assertEqual(self.judge()["result"], "pass")
        for n, frame in enumerate(self.seen["frames"]):
            detection = frame["objects"]["player"][0]
            self.assertEqual(detection["entityId"], "player:unique")
            self.assertEqual(detection["tick"], 2 * n + 1)
            self.assertEqual(detection["frame"], n)
            self.assertEqual(detection["source"], frame["source"])
            self.assertEqual(detection["sensor"], {"name": "scripted-pixels", "version": "1"})
            self.assertEqual(detection["coordinateSpace"], "screen-pixels")

    def test_one_frame_shift_cannot_pass(self):
        for field in ("tick", "source"):
            with self.subTest(field=field):
                seen = copy.deepcopy(self.seen)
                seen["frames"][2][field] = copy.deepcopy(seen["frames"][3][field])
                result = self.judge(seen)
                self.assertEqual(result["result"], "needs-review")
                self.assertIn("frame", result["reason"])

    def test_wrong_resolution_or_transform_cannot_pass(self):
        (self.frames / "f00000002.png").write_bytes(png(64, 48))
        result = self.judge()
        self.assertEqual(result["result"], "needs-review")
        self.assertIn("resolution", result["reason"])
        (self.frames / "f00000002.png").write_bytes(png(shade=2))
        seen = copy.deepcopy(self.seen)
        seen["timeline"]["frames"][2]["transform"][4] = 1
        self.assertEqual(self.judge(seen)["result"], "needs-review")

    def test_missing_image_or_observation_is_a_named_gap(self):
        seen = copy.deepcopy(self.seen); seen["frames"].pop(2)
        result = self.judge(seen)
        self.assertEqual(result["result"], "needs-review")
        self.assertIn("gap at frames [2]", result["reason"])
        (self.frames / "f00000002.png").unlink()
        result = self.judge()
        self.assertEqual(result["result"], "needs-review")
        self.assertIn("missing [2]", result["reason"])

    def test_two_same_class_targets_are_ambiguous_not_highest_score(self):
        seen = copy.deepcopy(self.seen)
        second = copy.deepcopy(seen["frames"][2]["objects"]["player"][0])
        second.update(score=.99, box=[200, 200, 210, 210], entityId="player:other")
        seen["frames"][2]["objects"]["player"].append(second)
        result = self.judge(seen)
        self.assertEqual(result["result"], "needs-review")
        self.assertIn("ambiguous identity", result["reason"])
        self.assertEqual(evaluator.evaluate(SPEC, seen)["result"], "needs-review")

    def test_outage_and_legacy_answer_on_new_capture_never_pass(self):
        class Down:
            def look(self, *args, **kwargs): raise verify.NoAnswer("observer unavailable")
        result = verify.judge_run(SPEC, self.run, rule="both", visual=Down(), ticks=12)
        self.assertEqual(result["result"], "needs-review")
        seen = copy.deepcopy(self.seen); seen["format"] = "expectrail.observations/v0"
        self.assertEqual(self.judge(seen)["result"], "needs-review")

    def test_screen_counterexample_is_not_replaced_by_engine_position(self):
        seen = copy.deepcopy(self.seen)
        seen["frames"][2]["objects"]["player"][0]["box"] = [200, 10, 210, 20]
        result = self.judge(seen)
        self.assertEqual(result["observed"]["engine"], "pass")
        self.assertEqual(result["observed"]["visual"], "fail")
        self.assertEqual(result["result"], "fail")
        self.assertEqual(result["frame"], 2)

    def test_real_visual_writer_preserves_disagreeing_and_multiple_answers(self):
        from agents.sam_observations import Cache
        from expectrail.observers import FramesObserver
        class Client:
            model, base, provider, engine_checked = "stand-in", "offline", "offline", True
            def segment(self, path, prompt):
                return copy.deepcopy(self.answers)
        client = Client()
        observer = FramesObserver(client=client, cache=Cache(None), workers=1, every=1)
        for answers, reason in (([{"box": [110, 10, 120, 20], "score": .99}], "disagrees"),
                                ([{"box": [10, 10, 20, 20], "score": .9},
                                  {"box": [11, 10, 21, 20], "score": .99}], "2 candidates")):
            with self.subTest(reason=reason):
                client.answers = answers
                seen = observer.look(SPEC, self.run, keep=False)
                self.assertEqual([d["box"] for d in seen["frames"][0]["objects"]["player"]],
                                 [a["box"] for a in answers])
                self.assertEqual(seen["format"], timeline.OBSERVATIONS)
                result = self.judge(seen)
                self.assertEqual(result["result"], "needs-review")
                self.assertIn(reason, result["reason"])

    def test_capture_is_validated_before_the_observer_is_called(self):
        from unittest import mock
        observer = mock.Mock()
        self.trace.pop("captureTimeline")
        result = verify.judge_run(SPEC, self.run, rule="both", visual=observer, ticks=12)
        self.assertEqual(result["result"], "needs-review")
        self.assertIn("did not record", result["reason"])
        observer.look.assert_not_called()

    def test_bound_entity_id_is_preserved_and_engine_evidence_is_not_pixels(self):
        for row in self.trace["rows"]:
            row["roleObjects"] = [{"id": "World/Player", "role": "player", "box": [10, 10, 20, 20]}]
        seen = timeline.emit(self.seen, self.trace, self.frames)
        self.assertEqual(seen["frames"][0]["objects"]["player"][0]["entityId"], "player:unique")
        # A raw writer has no provenance yet; bind its uniquely identified role to the engine id.
        for frame in seen["frames"]:
            frame["objects"]["player"][0].pop("entityId")
        seen = timeline.emit(seen, self.trace, self.frames)
        self.assertEqual(seen["frames"][0]["objects"]["player"][0]["entityId"], "World/Player")
        self.run["engineObservations"] = from_trace_synthetic(self.trace, "a" * 64)
        self.assertEqual(self.judge(seen)["result"], "pass")
        seen["frames"][0]["objects"]["player"][0]["source"] = {
            "kind": "trace", "sha256": seen["timeline"]["traceSha256"]}
        result = self.judge(seen)
        self.assertEqual(result["result"], "needs-review")
        self.assertIn("not pixel evidence", result["reason"])

    def test_visible_keeps_its_existing_class_presence_meaning(self):
        spec = copy.deepcopy(SPEC)
        spec["assertion"] = {"type": "visible", "object": "player"}
        seen = copy.deepcopy(self.seen)
        for frame in seen["frames"]:
            frame["objects"]["player"].append(copy.deepcopy(frame["objects"]["player"][0]))
        self.assertEqual(self.judge(seen, spec)["result"], "pass")

    def test_missing_event_is_not_interpolated_even_beside_a_witness(self):
        spec = copy.deepcopy(SPEC)
        spec["objects"]["goal"] = {"prompt": "goal"}
        spec["assertion"] = {"type": "reaches", "object": "player", "goal": "goal", "distancePx": 1}
        seen = copy.deepcopy(self.seen)
        for frame in seen["frames"]:
            frame["objects"]["goal"] = copy.deepcopy(frame["objects"]["player"])
            frame["objects"]["goal"][0]["entityId"] = "goal:unique"
        seen["frames"].pop(2)
        result = evaluator.evaluate(spec, seen, expected_frames=list(range(6)))
        self.assertEqual(result["result"], "needs-review")
        self.assertIn("no interpolation", result["reason"])

    def test_duplicate_missing_or_reversed_capture_records_are_refused(self):
        original = copy.deepcopy(self.trace["captureTimeline"]["frames"])
        for bad in ([original[0], *original], original[:2] + original[3:], list(reversed(original))):
            with self.subTest(bad=bad):
                self.trace["captureTimeline"]["frames"] = bad
                self.assertEqual(self.judge()["result"], "needs-review")
        self.trace["captureTimeline"]["frames"] = original
        (self.frames / "f0.png").write_bytes(png())
        self.assertEqual(self.judge()["result"], "needs-review")

    def test_null_identity_and_forged_intervals_are_named_gaps(self):
        seen = copy.deepcopy(self.seen)
        seen["frames"][2]["objects"]["player"][0]["entityId"] = None
        result = self.judge(seen)
        self.assertEqual(result["result"], "needs-review")
        self.assertIn("no entity id", result["reason"])
        seen = copy.deepcopy(self.seen)
        seen["timeline"]["frames"][2]["tickInterval"] = [0, 5]
        self.assertEqual(evaluator.evaluate(SPEC, seen)["result"], "needs-review")

    def test_both_schema_readers_require_v1_provenance(self):
        from expectrail.gate.record import errors
        schema = json.loads((ROOT / "contracts/observations.schema.json").read_text())
        self.assertEqual(errors(self.seen, schema), [])
        for field in ("tick", "source", "coordinateSpace", "sensor", "entityId"):
            with self.subTest(field=field):
                seen = copy.deepcopy(self.seen)
                seen["frames"][0]["objects"]["player"][0].pop(field)
                self.assertTrue(errors(seen, schema))
                with self.assertRaises(contracts.ContractError):
                    contracts.validate(seen, "observations")

    def test_negative_visual_evidence_matches_the_full_schema_reader(self):
        from jsonschema import Draft202012Validator
        from expectrail.gate import record

        def example(name):
            path = ROOT / f"contracts/examples/observations-{name}.json"
            return json.loads(path.read_text())["frames"][0]["notDrawn"]["player"]

        schema = timeline._schema()
        full = Draft202012Validator(schema)
        size = example("missing-player")
        place = example("clipped-player")
        empty = dict(size, reason="no-match", answer=None, observedSize=None)
        cases = [(size, True), (place, True), (empty, True),
                 (dict(empty, scale=[0, 1]), False), (dict(size, observedSize=[1, 0]), False),
                 (dict(size, expectedSize=[-1, 1]), False), (dict(empty, answer=size["answer"]), False),
                 (dict(empty, observedSize=[1, 2]), False), (dict(size, answer=None), False),
                 (dict(size, answer={"box": [1], "score": .8}), False),
                 ({k: v for k, v in place.items() if k != "expectedVisibleBox"}, False)]
        for negative, valid in cases:
            with self.subTest(negative=negative):
                seen = copy.deepcopy(self.seen)
                seen["frames"][0].update(objects={"player": []}, notDrawn={"player": negative})
                self.assertEqual(full.is_valid(seen), valid)
                self.assertEqual(not record.errors(seen, schema), valid)

    def test_gate_judges_v1_negative_answers_with_the_trusted_timeline(self):
        from expectrail import anchored
        from tests.test_anchored_observer import Blind

        calibration = json.loads((ROOT / "contracts/examples/vision-calibration.v1.json").read_text())
        observer = anchored.AnchoredObserver(Blind(self.run), anchored.check_calibration(calibration))
        result = verify.judge_run(SPEC, self.run, rule="both", visual=observer, ticks=12)
        self.assertEqual(result["observed"]["engine"], "pass")
        self.assertEqual(result["observed"]["visual"], "fail")
        self.assertEqual((result["result"], result["frame"]), ("fail", 0))

        seen = result["visualObservations"]
        self.assertEqual(seen["format"], timeline.OBSERVATIONS)
        negative = seen["frames"][0]["notDrawn"]["player"]
        self.assertEqual(negative["reason"], "no-match")
        negative["answer"] = {"box": [1, 2, 3, 4], "score": .9}
        self.assertEqual(self.judge(seen)["result"], "needs-review")

    def test_schema_references_must_name_an_existing_local_schema(self):
        from expectrail.gate import record
        for ref in ("https://invalid.example/schema", "#/missing", "#/properties/item", "#/type"):
            rule = {"type": "object", "properties": {"item": {"$ref": ref}}}
            with self.subTest(ref=ref), self.assertRaises(record.SchemaError):
                record.errors({"item": 1}, rule)

    def test_observation_order_is_not_silently_sorted(self):
        seen = copy.deepcopy(self.seen); seen["frames"].reverse()
        self.assertEqual(self.judge(seen)["result"], "needs-review")


class ClockAndContractTest(unittest.TestCase):
    def test_godot_unity_and_fractional_clocks_use_the_recorded_intervals(self):
        from agents import unity_observations
        for tps, fps, ends, phase in (
                (120, 60, [1, 3, 5, 7, 9, 11], "post-physics-pre-draw"),
                (50, 50, list(range(50)), "post-draw"),
                (120, 50, [1, 3, 6, 8, 11], "post-physics-pre-draw"),
                (50, 60, [0, 0, 1, 2, 3, 4], "post-physics-pre-draw")):
            with self.subTest(tps=tps, fps=fps):
                trace = trace_at(ends, tps, fps, phase)
                doc = timeline.build(trace)
                self.assertEqual([f["tick"] for f in doc["frames"]], ends)
                self.assertEqual([timeline.tick_for(trace, n, fps) for n in range(len(ends))], ends)
                self.assertEqual(verify.window_frames(SPEC, len(trace["rows"]), trace, fps), list(range(len(ends))))
                if phase == "post-draw":
                    for row in trace["rows"]: row["frame"] = row["tick"]
                    observed = unity_observations.observations(trace, SPEC)
                    self.assertEqual([f["tick"] for f in observed["frames"]], ends)

    def test_legacy_fractional_clock_is_refused_instead_of_floor_division(self):
        trace = trace_at([0, 0, 1, 2, 3, 4], 50, 60); trace.pop("captureTimeline")
        with self.assertRaisesRegex(timeline.TimelineError, "no explicit mapping"):
            timeline.tick_for(trace, 2, 60)

    def test_template_reader_keeps_exact_evidence_checks_with_v1_provenance(self):
        from agents import template_observations as sensor
        old = json.loads((ROOT / 'contracts/examples/observations-template-foreground.json').read_text())
        trace = trace_at([1, 3, 5])
        seen = timeline.emit(old, trace)
        self.assertEqual(sensor.summarize(seen), sensor.summarize(old))
        seen['frames'][0]['objects']['player'][0]['box'][0] += 1
        with self.assertRaisesRegex(sensor.SensorError, 'detections disagree'):
            sensor.summarize(seen)

    def test_affine_box_uses_all_four_corners(self):
        from agents.observations import _frame_box
        self.assertEqual(_frame_box([1, 1, -1, 1, 0, 0], [0, 0, 10, 10]), [-10, 0, 10, 20])

    def test_new_contract_examples_and_old_reader(self):
        import jsonschema
        for name, kind in (("observations", "observations"), ("observations-v1", "observations"),
                           ("trace-capture-timeline", "trace"), ("replay-timeline", "replay")):
            path = ROOT / f"contracts/examples/{name}.json"
            doc = json.loads(path.read_text())
            if kind == "trace":
                jsonschema.validate(doc, json.loads((ROOT / "contracts/trace.schema.json").read_text()))
            else:
                self.assertEqual(contracts.validate(doc, kind), kind)
                self.assertEqual(contracts.load(path, kind), doc)
        jsonschema.validate(json.loads((ROOT / "contracts/examples/observation-timeline.json").read_text()),
                            json.loads((ROOT / "contracts/observation-timeline.v1.schema.json").read_text()))
        trace = json.loads((ROOT / "contracts/examples/trace-capture-timeline.json").read_text())
        recorded = json.loads((ROOT / "contracts/examples/observation-timeline.json").read_text())
        rebuilt = timeline.build(trace)
        self.assertEqual(rebuilt["traceSha256"], recorded["traceSha256"])
        self.assertEqual([f["tickInterval"] for f in rebuilt["frames"]],
                         [f["tickInterval"] for f in recorded["frames"]])


class GodotCaptureTimelineTest(unittest.TestCase):
    def test_actual_draws_cover_integral_and_fractional_clocks(self):
        import shutil
        from unittest import mock
        from harness import run as harness
        from tests.tool_requirements import godot_binary, require_tool
        godot = godot_binary()
        require_tool('xvfb-run')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for tps, fps in ((120, 60), (120, 50), (50, 60)):
                with self.subTest(tps=tps, fps=fps):
                    project = root / f'project-{tps}-{fps}'
                    shutil.copytree(ROOT / 'tests/projects/capture-clock', project)
                    settings = project / 'project.godot'
                    settings.write_text(settings.read_text().replace('physics_ticks_per_second=120',
                                                                    f'physics_ticks_per_second={tps}'))
                    route = root / 'route.json'
                    route.write_text(json.dumps({'format': 'expectrail.route/v0', 'name': 'clock',
                                                 'seed': 1, 'ticks': 12, 'events': []}))
                    outputs = []
                    with mock.patch.object(harness, 'get_cache_dir', return_value=root / 'cache'):
                        for attempt in range(2):
                            out = root / f'run-{tps}-{fps}-{attempt}'
                            replay = harness.run(route, out, game=project, fps=fps, godot=godot, sandbox='off')
                            self.assertNotIn('timelineProblem', replay, replay.get('timelineProblem'))
                            trace = json.loads((out / 'trace.json').read_text())
                            expected = timeline.build(trace, out / 'frames', ticks=12)
                            self.assertEqual(replay['timeline'], expected)
                            self.assertEqual(expected['frames'][-1]['tick'], 11)
                            self.assertEqual(len(expected['frames']), len(replay['frameSha256']))
                            from harness.unity.png_pixels import read
                            for at in expected['frames']:
                                image = out / 'frames' / f"f{at['frame']:08d}.png"
                                width, height, channels, pixels = read(image)
                                white = [i % width for i in range(width * height)
                                         if pixels[i * channels:i * channels + 3] == b'\xff\xff\xff']
                                self.assertTrue(white, 'fixture player must be drawn')
                                self.assertEqual(min(white), trace['rows'][at['tick']]['player'][0],
                                                 f"pixels disagree with recorded tick on frame {at['frame']}")
                            print(f"capture tps={tps} fps={fps} attempt={attempt}: "
                                  f"ticks={[f['tick'] for f in expected['frames']]}; pixels agree")
                            outputs.append(((out / 'trace.json').read_bytes(), replay['frameSha256']))
                    self.assertEqual(outputs[0], outputs[1], 'same route must give identical trace and image bytes')
