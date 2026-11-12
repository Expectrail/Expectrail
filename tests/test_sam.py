"""SAM 3.1 adapter and probe, offline: a scripted transport stands in for the Meta Model API."""
import base64
import io
import json
import os
import struct
import tempfile
import unittest
import urllib.error
import zlib
from pathlib import Path
from unittest import mock

import agents.sam_observations as sam
from agents.keys import MUSE_ENV_ALLOWLIST
from agents.observations import from_trace
from agents.sam_observations import (
    Cache, MetaSamClient, SamError, from_replay, output_text, parse_output, refine_targets,
    request_body, sample, sampling_plan,
)
from agents.sam_probe import boundary_gap, markdown, probe_run, tolerance_hint
from harness.run import REPO
from expectrail.contracts import load, validate
from expectrail.evaluator import evaluate

SPEC = load(REPO / "specs" / "player-stays-above-ground.json", "test-spec")
TOL = SPEC["assertion"]["boundary"]["tolerancePx"]
W, H = 160, 96
GROUND_TOP = 70


def png_bytes(width: int, height: int, seed: int) -> bytes:
    """A valid RGB PNG whose pixels encode ``seed`` so every frame hashes differently."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    row = bytes([seed % 256, (seed // 256) % 256, 7]) * width
    raw = b"".join(b"\x00" + row for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def box_token(oid, box, score=None, size=(W, H)):
    """Wire record for a half-open box: corners on the wire are inclusive."""
    x0, y0, x1, y1 = box
    c = f";c={score}" if score is not None else ""
    return (f"{oid}<|box;x1={x0};y1={y0};x2={x1 - 1};y2={y1 - 1};w={size[0]};h={size[1]}{c}|>"
            f"<|mask;x=0;y=0;data={y1 - y0},{x1 - x0},!Zq9+[x]'#$%^@`{{}}|>")


def player_bottom_falling(i: int) -> int:
    """Stands on the ground until frame 33, then sinks 5 px a frame (first past TOL at FIRST_FALL)."""
    return GROUND_TOP + max(0, i - 33) * 5


FIRST_FALL = 33 + int(TOL) // 5 + 1  # 38 with the approved 20 px tolerance


class Scene:
    """Frames on disk plus a fake sam-3.1 that answers from a script keyed by frame and prompt."""

    def __init__(self, root: Path, frames: int = 120, bottom=lambda i: GROUND_TOP, extra=None, missing=()):
        self.dir = root / "frames"
        self.dir.mkdir(parents=True)
        self.index = {}
        for i in range(frames):
            data = png_bytes(W, H, i)
            (self.dir / f"f{i:08d}.png").write_bytes(data)
            self.index[base64.b64encode(data).decode()] = i
        self.bottom = bottom
        self.extra = extra or {}
        self.missing = set(missing)
        self.bodies = []

    def answer(self, i: int, prompt: str) -> str:
        if prompt in self.extra:
            return self.extra[prompt](i)
        if prompt == SPEC["objects"]["player"]["prompt"]:
            if i in self.missing:
                return ""
            b = self.bottom(i)
            return box_token(0, (60, b - 20, 80, b), 0.91)
        if prompt == SPEC["objects"]["ground"]["prompt"]:
            return box_token(0, (0, GROUND_TOP, W, H), 0.88) + "," + box_token(1, (100, 30, 140, 40), 0.62)
        return self.extra.get(prompt, lambda i: "")(i)

    def transport(self, body: dict):
        self.bodies.append(body)
        content = body["input"][0]["content"]
        prompt = content[0]["text"]
        i = self.index[content[1]["image_url"].split(",", 1)[1]]
        text = self.answer(i, prompt)
        line = f"<0f>{text}" if text else ""
        doc = {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": line}]}]}
        return json.dumps(doc).encode(), "application/json"

    def client(self) -> MetaSamClient:
        return MetaSamClient(transport=self.transport, sleep=lambda s: None)


class WireFormatTest(unittest.TestCase):
    def test_records_are_half_open_with_scores_and_ids(self):
        text = "<0f>" + box_token(0, (251, 70, 924, 854), 0.93, size=(1280, 854)) + "," + \
            box_token(1, (10, 20, 30, 40), 0.5, size=(1280, 854))
        records = parse_output(text, frame_size=(1280, 854))
        self.assertEqual([r["id"] for r in records], [0, 1])
        self.assertEqual(records[0]["box"], [251, 70, 924, 854])
        self.assertEqual(records[0]["score"], 0.93)
        self.assertEqual(records[0]["frame"], 0)

    def test_boxes_scale_to_the_frame_when_the_service_reports_another_size(self):
        records = parse_output("<0f>" + box_token(0, (100, 50, 200, 100), 0.9, size=(800, 480)), frame_size=(1600, 960))
        self.assertEqual(records[0]["box"], [200, 100, 400, 200])

    def test_no_match_is_empty_and_video_lines_keep_their_frame(self):
        self.assertEqual(parse_output(""), [])
        text = "<0f>" + box_token(0, (1, 1, 5, 5), 0.8) + "\n<1f>" + box_token(0, (2, 2, 6, 6), 0.7)
        self.assertEqual([r["frame"] for r in parse_output(text)], [0, 1])

    def test_missing_confidence_is_none_and_bad_boxes_are_errors(self):
        self.assertIsNone(parse_output("<0f>" + box_token(0, (1, 1, 5, 5)))[0]["score"])
        with self.assertRaises(SamError):
            parse_output("<0f>0<|box;x1=1;y1=oops;x2=3;y2=4;w=9;h=9|>")

    def test_non_finite_numbers_and_out_of_range_confidences_are_errors(self):
        for token in ("0<|box;x1=1;y1=1;x2=5;y2=nan;w=9;h=9;c=0.9|>", "0<|box;x1=1;y1=1;x2=5;y2=5;w=9;h=9;c=nan|>",
                      "0<|box;x1=1;y1=1;x2=5;y2=5;w=;h=9;c=0.9|>", "0<|box;x1=1;y1=1;x2=5;y2=5;w=9;h=9;c=1.5|>",
                      "0<|box;x1=inf;y1=1;x2=5;y2=5;w=9;h=9;c=0.5|>"):
            with self.subTest(token=token), self.assertRaises(SamError):
                parse_output("<0f>" + token, frame_size=(9, 9))

    def test_unrecognised_output_is_an_error_not_nothing_found(self):
        for text in ("I can't help with that.", "0<|box;x1=1;y1=1;x2=5;y2=5;w=9;h=9;c=0.9|>",
                     "<0f>" + box_token(0, (1, 1, 5, 5), 0.8) + " trailing words"):
            with self.subTest(text=text), self.assertRaises(SamError):
                parse_output(text)
        for reply in (b"[1, 2]", b'"text"', b'{"id": "resp_1"}', b'{"output": "nope"}'):
            with self.subTest(reply=reply), self.assertRaises(SamError):
                output_text(reply, "application/json")
        self.assertEqual(output_text(b'{"status": "completed", "output": []}'), "")

    def test_json_and_streamed_replies(self):
        text = "<0f>" + box_token(0, (1, 1, 5, 5), 0.8)
        plain = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}
        self.assertEqual(output_text(json.dumps(plain).encode(), "application/json"), text)
        self.assertEqual(output_text(json.dumps({"output_text": text}).encode()), text)
        half = len(text) // 2
        events = [{"type": "response.output_text.delta", "delta": text[:half]},
                  {"type": "response.output_text.delta", "delta": text[half:]},
                  {"type": "response.completed"}]
        sse = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()
        self.assertEqual(output_text(sse, "text/event-stream"), text)

    def test_partial_or_failed_replies_are_errors(self):
        cut = f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': '<0f>0<|bo'})}\n\n".encode()
        with self.assertRaises(SamError):
            output_text(cut, "text/event-stream")
        with self.assertRaises(SamError):
            output_text(json.dumps({"status": "incomplete", "output": []}).encode())
        with self.assertRaises(SamError):
            output_text(json.dumps({"error": {"message": "model_not_found"}}).encode())

    def test_request_asks_for_confidence_and_sends_one_concept_and_one_image(self):
        body = request_body("small robot character", "data:image/png;base64,AAAA")
        self.assertEqual(body["model"], "sam-3.1")
        self.assertEqual(body["metadata"]["include_confidence"], "true")
        content = body["input"][0]["content"]
        self.assertEqual([c["type"] for c in content], ["input_text", "input_image"])
        self.assertEqual(content[0]["text"], "small robot character")


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.png = Path(self.tmp.name) / "f00000000.png"
        self.png.write_bytes(png_bytes(W, H, 1))

    def tearDown(self):
        self.tmp.cleanup()

    def test_retries_rate_limits_then_succeeds(self):
        calls = []

        def transport(body):
            calls.append(body)
            if len(calls) == 1:
                raise urllib.error.HTTPError("u", 429, "slow down", {}, io.BytesIO(b"rate limited"))
            return json.dumps({"output_text": "<0f>" + box_token(0, (1, 1, 5, 5), 0.8)}).encode(), "application/json"

        before = sam.sam_usage()
        client = MetaSamClient(transport=transport, sleep=lambda s: None)
        self.assertEqual(client.segment(self.png, "x"), [{"box": [1, 1, 5, 5], "score": 0.8}])
        self.assertEqual(client.calls, 2)
        # Two requests went out; one image was answered (and billed). The count is process-wide.
        after = sam.sam_usage()
        self.assertEqual((after["requests"] - before["requests"], sam.sam_images_since(before)), (2, 1))

    def test_a_failed_request_is_not_counted_as_an_image(self):
        def transport(body):
            raise urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b"bad"))
        before = sam.sam_usage()
        with self.assertRaises(SamError):
            MetaSamClient(transport=transport, sleep=lambda s: None).segment(self.png, "x")
        self.assertEqual(sam.sam_images_since(before), 0)
        self.assertEqual(sam.sam_usage()["requests"] - before["requests"], 1)

    def test_bad_requests_are_not_retried(self):
        def transport(body):
            raise urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b"mixing phrase and box prompts"))
        client = MetaSamClient(transport=transport, sleep=lambda s: None)
        with self.assertRaises(SamError) as cm:
            client.segment(self.png, "x")
        self.assertIn("400", str(cm.exception))
        self.assertEqual(client.calls, 1)

    def test_a_box_without_a_confidence_is_refused(self):
        client = MetaSamClient(transport=lambda b: (json.dumps({"output_text": "<0f>" + box_token(0, (1, 1, 5, 5))})
                                                   .encode(), ""), sleep=lambda s: None)
        with self.assertRaises(SamError):
            client.segment(self.png, "x")

    def test_the_key_comes_from_the_environment_only(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MODEL_API_KEY", None)
            with self.assertRaises(SamError) as cm:
                MetaSamClient().segment(self.png, "x")
        self.assertIn("MODEL_API_KEY", str(cm.exception))

    def test_the_fixer_never_gets_the_sam_key(self):
        self.assertNotIn("MODEL_API_KEY", MUSE_ENV_ALLOWLIST)

    def test_sam_and_the_fixer_must_not_share_a_key(self):
        from agents.keys import require_separate_sam_key
        cases = [({"EXPECTRAIL_OBS_PROVIDER": "sam", "MODEL_API_KEY": "LLM_a", "META_API_KEY": "LLM_a"}, True),
                 ({"EXPECTRAIL_OBS_PROVIDER": "sam", "MODEL_API_KEY": "", "META_API_KEY": "LLM_a"}, True),
                 ({"EXPECTRAIL_OBS_PROVIDER": "sam", "MODEL_API_KEY": "LLM_b", "META_API_KEY": "LLM_a"}, False),
                 ({"EXPECTRAIL_OBS_PROVIDER": "trace", "MODEL_API_KEY": "LLM_a", "META_API_KEY": "LLM_a"}, False)]
        for env, refused in cases:
            with self.subTest(env=env), mock.patch.dict(os.environ, env):
                if refused:
                    with self.assertRaises(SystemExit) as cm:
                        require_separate_sam_key()
                    self.assertNotIn("LLM_a", str(cm.exception))
                else:
                    require_separate_sam_key()

    def test_the_loop_will_not_run_muse_with_a_shared_sam_key(self):
        from agents import loop
        env = {"EXPECTRAIL_OBS_PROVIDER": "sam", "MODEL_API_KEY": "LLM_a", "META_API_KEY": "LLM_a"}
        muse = {"mode": "live", "offline_triage": True, "use_muse": True}
        with mock.patch.dict(os.environ, env), mock.patch.object(loop, "one_run") as one_run, \
                mock.patch.object(loop, "resolve_mode", return_value=muse), \
                mock.patch.object(loop, "seal_mode_flags", return_value=muse):
            with self.assertRaises(SystemExit) as cm:
                loop.main(["--out", str(Path(self.tmp.name) / "loop"), "--mode", "live"])
        self.assertIn("same key as META_API_KEY", str(cm.exception))
        one_run.assert_not_called()

    def test_dropped_connections_are_retried_then_reported(self):
        import http.client

        def transport(body):
            raise http.client.IncompleteRead(b"<0f>0<|bo", 500)
        client = MetaSamClient(transport=transport, sleep=lambda s: None)
        with self.assertRaises(SamError) as cm:
            client.segment(self.png, "x")
        self.assertIn("IncompleteRead", str(cm.exception))
        self.assertEqual(client.calls, 4)

    def test_sharing_the_fixers_key_is_warned_about(self):
        sam._warned_shared_key.clear()
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"MODEL_API_KEY": "LLM_same", "META_API_KEY": "LLM_same"}), \
                mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")), \
                mock.patch("sys.stderr", err):
            with self.assertRaises(SamError):
                MetaSamClient(retries=0).segment(self.png, "x")
        self.assertIn("same key as META_API_KEY", err.getvalue())
        self.assertNotIn("LLM_same", err.getvalue())


class SpendCapTest(unittest.TestCase):
    """EXPECTRAIL_SAM_USD_CAP: the most one run may spend on SAM. Every try is counted before it is
    sent, and a request that would pass the cap is not sent (#267; Sean's limit of November 12 is
    $200 a month and never more, which needs every run to have a worst case it cannot pass)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.png = Path(self.tmp.name) / "f.png"
        self.png.write_bytes(png_bytes(W, H, 1))
        self.sent = []
        patcher = mock.patch.dict(sam._usage, {"requests": 0, "images": 0, "videoFrames": 0, "reservedUsd": 0.0})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def answer(self, body):
        self.sent.append(body)
        return json.dumps({"output_text": "<0f>" + box_token(0, (1, 1, 5, 5), 0.8)}).encode(), "application/json"

    def client(self, transport=None):
        return MetaSamClient(transport=transport or self.answer, sleep=lambda s: None)

    def test_the_request_that_would_pass_the_cap_is_not_sent(self):
        with mock.patch.dict(os.environ, {sam.CAP_ENV: "0.0075"}):   # three images at $0.0025
            client = self.client()
            for _ in range(3):
                client.segment(self.png, "x")
            with self.assertRaises(sam.SamError) as stopped:
                client.segment(self.png, "x")
        self.assertEqual(stopped.exception.kind, "budget")
        self.assertIn("was not sent", str(stopped.exception))
        self.assertEqual(len(self.sent), 3)
        self.assertAlmostEqual(sam.sam_usage()["reservedUsd"], 0.0075)
        # Still refused after the stop: the count does not go back.
        with mock.patch.dict(os.environ, {sam.CAP_ENV: "0.0075"}), self.assertRaises(sam.SamError):
            self.client().segment(self.png, "y")
        self.assertEqual(len(self.sent), 3)

    def test_a_try_that_fails_is_counted_too(self):
        # Three tries of one image (two rate limits, then an answer) count as three: whether a
        # failed try is billed is not known, so the count can only err over.
        tries = []

        def transport(body):
            tries.append(body)
            if len(tries) < 3:
                raise urllib.error.HTTPError("u", 429, "slow down", {}, io.BytesIO(b"rate limited"))
            return self.answer(body)

        with mock.patch.dict(os.environ, {sam.CAP_ENV: "1"}):
            self.client(transport).segment(self.png, "x")
        self.assertAlmostEqual(sam.sam_usage()["reservedUsd"], 3 * sam.USD_PER_IMAGE)
        # And a retry stops at the cap like any other request: one try fits, the retry does not.
        sam._usage["reservedUsd"] = 0.0
        tries.clear()
        with mock.patch.dict(os.environ, {sam.CAP_ENV: "0.0025"}), self.assertRaises(sam.SamError) as stopped:
            self.client(transport).segment(self.png, "x")
        self.assertEqual((stopped.exception.kind, len(tries)), ("budget", 1))

    def test_a_cap_of_nothing_sends_nothing(self):
        with mock.patch.dict(os.environ, {sam.CAP_ENV: "0"}), self.assertRaises(sam.SamError) as stopped:
            self.client().segment(self.png, "x")
        self.assertEqual((stopped.exception.kind, self.sent), ("budget", []))

    def test_a_cap_that_is_not_an_amount_is_an_error_and_never_no_cap(self):
        for raw in ("lots", "-1", "nan", "inf", "1e999", "$5", "5 dollars"):
            with self.subTest(raw=raw), mock.patch.dict(os.environ, {sam.CAP_ENV: raw}):
                with self.assertRaises(sam.SamError) as refused:
                    self.client().segment(self.png, "x")
                self.assertEqual(refused.exception.kind, "budget")
        self.assertEqual(self.sent, [])

    def test_without_a_cap_nothing_leaves_this_machine(self):
        # The real sender refuses before it opens a connection; a stand-in sender (every test, every
        # recorded answer) is not held to a cap that was never set.
        env = {k: v for k, v in os.environ.items() if k != sam.CAP_ENV}
        env[sam.KEY_ENV] = "not-a-real-key"
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(sam.urllib.request, "urlopen", side_effect=AssertionError("a request was opened")):
            with self.assertRaises(sam.SamError) as refused:
                MetaSamClient(sleep=lambda s: None).segment(self.png, "x")
            self.assertEqual(refused.exception.kind, "budget")
            self.assertIn(sam.CAP_ENV, str(refused.exception))
            self.client().segment(self.png, "x")
        self.assertEqual(len(self.sent), 1)

    def test_a_budget_stop_is_written_where_the_judge_ladder_reads_it(self):
        # The ladder reads the kind from the observer's error file; tests/test_judge_ladder.py runs
        # the ladder on such a file and holds that it stops there.
        from agents import judge_ladder
        self.assertIn("budget", judge_ladder.STOP_KINDS)
        self.assertNotIn("budget", judge_ladder.NO_RETRY_KINDS)
        message = f"sam observations unavailable (kind={sam.SamError('x', kind='budget').kind}): x"
        self.assertEqual(judge_ladder._KIND.findall(message), ["budget"])

    def test_a_video_is_counted_by_its_frames(self):
        with mock.patch.dict(os.environ, {sam.CAP_ENV: "1"}):
            self.client()._call({"x": 1}, video_frames=10)     # billed as the least a video costs
            self.client()._call({"x": 1}, video_frames=120)
        self.assertAlmostEqual(sam.sam_usage()["reservedUsd"], (sam.MIN_VIDEO_FRAMES + 120) * sam.USD_PER_VIDEO_FRAME)


class SamplingTest(unittest.TestCase):
    def test_every_nth_frame_plus_the_last(self):
        self.assertEqual(sample(list(range(120)), 4)[:3], [0, 4, 8])
        self.assertEqual(sample(list(range(120)), 4)[-2:], [116, 119])
        self.assertEqual(sample(list(range(10, 50)), 10), [10, 20, 30, 40, 49])
        self.assertEqual(sample(list(range(5)), 1), [0, 1, 2, 3, 4])

    def test_counting_assertions_look_at_every_frame(self):
        visible = {"assertion": {"type": "visible", "object": "coin", "minFraction": 0.9}}
        self.assertEqual(sampling_plan(visible, 4), 1)
        self.assertEqual(sampling_plan({"assertion": {"type": "visible", "object": "coin"}}, 4), 4)
        self.assertEqual(sampling_plan(SPEC, 4), 4)

    def test_refine_fills_the_gap_back_to_the_last_passing_sample(self):
        looked = {0, 10, 20, 30, 40}
        fail40 = {"result": "fail", "firstFrame": 40}
        self.assertEqual(refine_targets(list(range(50)), looked, fail40, {0, 10, 20, 30}), list(range(31, 40)))
        # Sample 30 had no player: it is not a pass, so the stretch reaches back to 20.
        self.assertEqual(refine_targets(list(range(50)), looked, fail40, {0, 10, 20}),
                         [i for i in range(21, 40) if i != 30])
        self.assertEqual(refine_targets(list(range(50)), looked, {"result": "pass"}, looked), [])
        self.assertEqual(len(refine_targets(list(range(50)), looked, {"result": "fail", "firstFrame": None}, set())), 45)
        self.assertEqual(len(refine_targets(list(range(50)), looked, {"result": "needs-review"}, set(), "reaches")), 45)


class FromReplayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_scene(self, scene, every, spec=SPEC, cache=None, refine=True, confirm=False):
        stats = {}
        doc = from_replay(frames_dir=scene.dir, spec=spec, every=every, refine=refine, confirm=confirm,
                          client=scene.client(), cache=cache or Cache(None), workers=3, stats=stats)
        validate(doc, "observations")
        return doc, stats

    def test_sampled_and_refined_fall_through_matches_every_frame(self):
        scene = Scene(self.root, bottom=player_bottom_falling)
        full, _ = self.run_scene(scene, every=1)
        sampled, stats = self.run_scene(scene, every=10)
        v_full, v_sampled = evaluate(SPEC, full), evaluate(SPEC, sampled)
        self.assertEqual(v_full["result"], "fail")
        self.assertEqual(v_full["firstFrame"], FIRST_FALL)
        self.assertEqual(v_sampled["result"], "fail")
        self.assertEqual(v_sampled["firstFrame"], FIRST_FALL)
        self.assertEqual(stats["framesAnalyzed"], 13 + 9)
        self.assertEqual(sampled["analysis"]["refined"], {"frames": 9, "from": 31, "to": 39})
        self.assertEqual(sampled["model"]["prompts"]["player"], "blue robot")

    def test_without_refinement_the_first_frame_is_only_as_exact_as_the_sample(self):
        scene = Scene(self.root, bottom=player_bottom_falling)
        doc, stats = self.run_scene(scene, every=10, refine=False)
        self.assertEqual(evaluate(SPEC, doc)["firstFrame"], 40)
        self.assertEqual(stats["framesAnalyzed"], 13)

    def test_clean_run_passes_on_the_sample_and_absent_frames_were_not_looked_at(self):
        scene = Scene(self.root)
        doc, stats = self.run_scene(scene, every=4)
        self.assertEqual(evaluate(SPEC, doc)["result"], "pass")
        self.assertEqual(stats["framesAnalyzed"], 31)
        self.assertNotIn(1, {f["frame"] for f in doc["frames"]})
        self.assertEqual(len(scene.bodies), 31 * 2)

    def test_a_judged_frame_is_never_sent_twice(self):
        scene = Scene(self.root, bottom=player_bottom_falling)
        cache = Cache(self.root / "cache")
        first, stats1 = self.run_scene(scene, every=10, cache=cache)
        sent = len(scene.bodies)
        second, stats2 = self.run_scene(scene, every=10, cache=Cache(self.root / "cache"))
        self.assertEqual(len(scene.bodies), sent)
        self.assertEqual(stats2["calls"], 0)
        self.assertEqual(stats2["cacheHits"], 22 * 2)
        self.assertEqual(first, second)
        other = json.loads(json.dumps(SPEC))
        other["objects"]["player"]["prompt"] = "robot"
        from_replay(frames_dir=scene.dir, spec=other, every=10, client=scene.client(), cache=cache, workers=2)
        self.assertGreater(len(scene.bodies), sent)

    def test_a_sampled_pass_is_confirmed_on_every_frame(self):
        scene = Scene(self.root)
        doc, stats = self.run_scene(scene, every=4, confirm=True)
        self.assertEqual(evaluate(SPEC, doc)["result"], "pass")
        self.assertEqual(stats["framesAnalyzed"], 120)
        self.assertEqual(doc["analysis"]["confirmed"], 120 - 31)
        self.assertEqual(len(scene.bodies), 120 * 2)  # sampled frames are not sent twice

    def test_confirmation_catches_a_flicker_between_samples(self):
        # The robot sinks for frames 41-43 only: every 4th frame misses it, every frame does not.
        bottom = lambda i: GROUND_TOP + 30 if 41 <= i <= 43 else GROUND_TOP
        scene = Scene(self.root, bottom=bottom)
        sampled, _ = self.run_scene(scene, every=4)
        confirmed, _ = self.run_scene(scene, every=4, confirm=True)
        self.assertEqual(evaluate(SPEC, sampled)["result"], "pass")
        self.assertEqual(evaluate(SPEC, confirmed)["result"], "fail")
        self.assertEqual(evaluate(SPEC, confirmed)["firstFrame"], 41)

    def test_a_failure_is_not_confirmed_and_confirm_is_on_by_default(self):
        scene = Scene(self.root, bottom=player_bottom_falling)
        _, stats = self.run_scene(scene, every=10, confirm=True)
        self.assertEqual(stats["confirmed"], 0)
        self.assertEqual(stats["framesAnalyzed"], 22)
        clean = Scene(self.root / "c")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EXPECTRAIL_SAM_CONFIRM", None)
            doc = from_replay(frames_dir=clean.dir, spec=SPEC, every=10, client=clean.client(), cache=Cache(None))
        self.assertEqual(doc["analysis"]["framesAnalyzed"], 120)

    def test_window_is_respected(self):
        scene = Scene(self.root, frames=60)
        spec = json.loads(json.dumps(SPEC))
        spec["window"] = {"fromFrame": 10, "toFrame": 49}
        doc, _ = self.run_scene(scene, every=10, spec=spec)
        self.assertEqual([f["frame"] for f in doc["frames"]], [10, 20, 30, 40, 49])

    def test_reaches_rechecks_every_frame_when_the_sample_misses_the_moment(self):
        coin = lambda i: box_token(0, (62, 40, 70, 50), 0.8) if i == 57 else box_token(0, (140, 10, 150, 20), 0.8)
        scene = Scene(self.root, extra={"gold coin": coin})
        spec = {"format": "expectrail.test-spec/v0", "id": "reach-coin", "instruction": "x",
                "objects": {"player": {"prompt": "blue robot"}, "coin": {"prompt": "gold coin"}},
                "assertion": {"type": "reaches", "object": "player", "goal": "coin", "distancePx": 0}}
        doc, stats = self.run_scene(scene, every=10, spec=spec)
        self.assertEqual(evaluate(spec, doc)["result"], "pass")
        self.assertEqual(stats["framesAnalyzed"], 120)

    def test_a_sample_without_the_player_does_not_anchor_refinement(self):
        # Fails on frames 6-12, player undetected at sample 8: the first failing frame is still 6.
        bottom = lambda i: GROUND_TOP + TOL + 8 if 6 <= i <= 12 else GROUND_TOP
        scene = Scene(self.root, bottom=bottom, missing={8})
        full, _ = self.run_scene(scene, every=1)
        sampled, _ = self.run_scene(scene, every=4)
        self.assertEqual(evaluate(SPEC, full)["firstFrame"], 6)
        self.assertEqual(evaluate(SPEC, sampled)["firstFrame"], 6)

    def test_reaches_that_needs_review_on_the_sample_is_rechecked(self):
        coin = lambda i: box_token(0, (62, 40, 70, 50), 0.8) if i == 6 else box_token(0, (140, 10, 150, 20), 0.8)
        scene = Scene(self.root, extra={"gold coin": coin}, missing={4})
        spec = {"format": "expectrail.test-spec/v0", "id": "reach-coin", "instruction": "x",
                "objects": {"player": {"prompt": "blue robot"}, "coin": {"prompt": "gold coin"}},
                "assertion": {"type": "reaches", "object": "player", "goal": "coin", "distancePx": 0}}
        doc, _ = self.run_scene(scene, every=4, spec=spec)
        self.assertEqual(evaluate(spec, doc)["result"], "pass")

    def test_unexpected_errors_become_sam_errors(self):
        scene = Scene(self.root)

        def broken(body):
            raise AttributeError("'list' object has no attribute 'get'")
        with self.assertRaises(SamError) as cm:
            from_replay(frames_dir=scene.dir, spec=SPEC, client=MetaSamClient(transport=broken), cache=Cache(None))
        self.assertIn("AttributeError", str(cm.exception))
        with mock.patch.dict(os.environ, {"EXPECTRAIL_SAM_EVERY": "four"}), self.assertRaises(SamError):
            from_replay(frames_dir=scene.dir, spec=SPEC, client=scene.client(), cache=Cache(None))

    def test_the_cache_is_best_effort_and_checks_what_it_reads(self):
        scene = Scene(self.root)
        blocked = self.root / "not-a-dir"
        blocked.write_text("x")
        doc, stats = self.run_scene(scene, every=10, cache=Cache(blocked))
        self.assertEqual(evaluate(SPEC, doc)["result"], "pass")
        self.assertNotEqual(Cache.key("a" * 64, "p", "sam-3.1", "https://api.meta.ai/v1"),
                            Cache.key("a" * 64, "p", "sam-3.1", "http://localhost:9"))
        cache = Cache(self.root / "cache")
        key = Cache.key("a" * 64, "p", "sam-3.1")
        for bad in ([{"box": [1, 2, 3, float("nan")], "score": 0.9}], [{"box": [1, 2, 3, 4], "score": 7}], "x"):
            path = cache._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"detections": bad}))
            self.assertIsNone(cache.get(key))

    def test_missing_frames_fail_closed_through_the_seam(self):
        with self.assertRaises(SamError):
            from_replay(frames_dir=None, spec=SPEC, client=MetaSamClient(transport=lambda b: (b"", "")))
        with self.assertRaises(SystemExit):
            from_trace({"rows": []}, provider="sam", frames_dir=None, spec=SPEC)

    def test_the_seam_passes_frames_and_spec_to_sam(self):
        scene = Scene(self.root, bottom=player_bottom_falling)
        real = sam.MetaSamClient
        with mock.patch.object(sam, "MetaSamClient", side_effect=lambda: real(transport=scene.transport)), \
                mock.patch.dict(os.environ, {"EXPECTRAIL_SAM_CACHE": "off", "EXPECTRAIL_SAM_EVERY": "10"}):
            doc = from_trace({"rows": []}, replay_sha256="b" * 64, provider="sam", frames_dir=str(scene.dir), spec=SPEC)
        self.assertEqual(doc["model"]["name"], "sam-3.1")
        self.assertEqual(doc["replay"]["sha256"], "b" * 64)
        self.assertEqual(evaluate(SPEC, doc)["firstFrame"], FIRST_FALL)


class ProbeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def make_run(self, name, bottom):
        run = self.root / name
        scene = Scene(run, bottom=bottom)
        rows = [{"tick": t, "player": [0.0, 0.0], "onFloor": bottom(t // 2) == GROUND_TOP} for t in range(0, 240)]
        (run / "trace.json").write_text(json.dumps({"physicsTicksPerSecond": 120, "rows": rows}))
        return run, scene

    def test_gap_agrees_with_the_evaluator_frame_by_frame(self):
        tol = SPEC["assertion"]["boundary"]["tolerancePx"]
        scene = Scene(self.root, bottom=player_bottom_falling)
        doc = from_replay(frames_dir=scene.dir, spec=SPEC, every=1, client=scene.client(), cache=Cache(None))
        for frame in doc["frames"]:
            gap, _ = boundary_gap(SPEC, frame["objects"])
            single = dict(doc, frames=[frame])
            self.assertEqual(gap > tol, evaluate(SPEC, single)["result"] == "fail", frame["frame"])

    def test_probe_reports_clean_and_bug_gaps(self):
        clean, clean_scene = self.make_run("clean", lambda i: GROUND_TOP)
        bug, bug_scene = self.make_run("physics-fall-through_v1", player_bottom_falling)
        runs = []
        for run, scene in ((clean, clean_scene), (bug, bug_scene)):
            runs.append(probe_run(run, SPEC, None, 10, scene.client(), Cache(None), 2, None))
        self.assertEqual(runs[0]["verdict"]["result"], "pass")
        self.assertEqual(runs[1]["verdict"]["result"], "fail")
        self.assertEqual(runs[0]["objects"]["player"]["framesFound"], 13)
        self.assertTrue(all(g["onFloor"] for g in runs[0]["gaps"]))
        hint = tolerance_hint(SPEC, runs, {"clean"})
        self.assertEqual(hint["cleanWorstGap"], 0)
        self.assertGreater(hint["others"]["physics-fall-through_v1"], 12)
        md = markdown(SPEC, runs, hint, "sam-3.1", {"calls": 52, "cacheHits": 0})
        self.assertIn("| clean | 13 | pass |", md)
        self.assertIn("worst gap", md)

    def test_annotations_carry_the_numbers_on_one_line_each(self):
        from agents.sam_probe import annotations
        clean, clean_scene = self.make_run("clean", lambda i: GROUND_TOP)
        bug, bug_scene = self.make_run("physics-fall-through_v1", player_bottom_falling)
        runs = [probe_run(r, SPEC, None, 10, s.client(), Cache(None), 2, None)
                for r, s in ((clean, clean_scene), (bug, bug_scene))]
        report = {"spec": SPEC["id"], "model": "sam-3.1", "stats": {"calls": 52, "cacheHits": 0, "seconds": 26.0},
                  "runs": runs, "tolerance": tolerance_hint(SPEC, runs, {"clean"})}
        lines = annotations(report)
        self.assertEqual(len(lines), 3)
        self.assertTrue(all(line.startswith("::notice title=SAM probe ") and "\n" not in line for line in lines))
        self.assertIn("clean::pass; player 13/13 score min 0.91", lines[0])
        self.assertIn("gaps 0:0 10:0", lines[0])
        self.assertIn("seconds per call 0.50", lines[2])
        self.assertIn("physics-fall-through_v1:", lines[2])

    def test_sweep_tries_each_prompt_and_reuses_the_other_objects(self):
        from agents.sam_probe import _pairs, sweep, sweep_annotations, with_prompts
        floor = lambda i: box_token(0, (0, GROUND_TOP, W, H), 0.7)
        run = self.root / "clean"
        scene = Scene(run, extra={"floor": floor, "dirt": lambda i: ""})
        rows = [{"tick": t, "player": [0.0, 0.0], "onFloor": True} for t in range(240)]
        (run / "trace.json").write_text(json.dumps({"physicsTicksPerSecond": 120, "rows": rows}))
        client = scene.client()
        results = sweep([run], SPEC, "ground", ["floor", "dirt"], None, 10, client, Cache(self.root / "c"), 2,
                        None, {"clean"})
        self.assertEqual([r["runs"][0]["verdict"]["result"] for r in results], ["pass", "needs-review"])
        self.assertEqual(results[0]["runs"][0]["objects"]["ground"]["framesFound"], 13)
        self.assertEqual(client.calls, 13 * 3)  # player once, then from the cache; ground once per prompt
        lines = sweep_annotations(results)
        self.assertTrue(lines[0].startswith("::notice title=SAM sweep ground=floor::clean pass ground 13/13"))
        self.assertEqual(_pairs(["ground=dirt ground"], "--set"), {"ground": "dirt ground"})
        with self.assertRaises(SystemExit):
            _pairs(["ground"], "--set")
        with self.assertRaises(SystemExit):
            with_prompts(SPEC, {"coin": "gold coin"})
        self.assertEqual(SPEC["objects"]["ground"]["prompt"], "grass-topped ground")

    @unittest.skipUnless(__import__("importlib").util.find_spec("PIL"), "Pillow not installed")
    def test_overlays_and_contact_sheet(self):
        run, scene = self.make_run("clean", lambda i: GROUND_TOP)
        out = self.root / "probe"
        result = probe_run(run, SPEC, [0, 30, 60], 10, scene.client(), Cache(None), 2, out)
        self.assertEqual(len(result["images"]), 4)
        self.assertTrue((out / "clean-sheet.png").is_file())


class VerifierTest(unittest.TestCase):
    def verify_with(self, outcomes):
        from agents.verifier import verify
        from tests.test_agents import _request

        def harness(route, harness_out, patches=None, **_kw):
            harness_out.mkdir(parents=True, exist_ok=True)
            (harness_out / "trace.json").write_text(
                (REPO / "agents" / "fixtures" / "trace-fixed.json").read_text())
            (harness_out / "replay.json").write_text("{}\n")

        def observations(*_a, **_kw):
            item = outcomes.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch("agents.verifier.harness_run", side_effect=harness), \
                mock.patch("agents.verifier.from_trace", side_effect=observations):
            os.environ.pop("EXPECTRAIL_HELDOUT_DIR", None)
            out = Path(tmp.name)
            doc = verify(_request(), REPO / "agents" / "fixtures" / "fix-collision-mask.patch", out)
        validate(doc, "verification")
        return doc, out

    def test_observations_failure_on_the_candidate_is_needs_review_not_a_crash(self):
        clean = load(REPO / "agents" / "fixtures" / "obs-clean.json", "observations")
        doc, out = self.verify_with([SystemExit("observations unavailable: HTTP 503"), clean])
        regression = next(c for c in doc["checks"] if c["kind"] == "regression")
        self.assertEqual(regression["result"], "needs-review")
        self.assertEqual(doc["suite"]["candidate"]["source"], "unavailable")
        self.assertNotEqual(doc["decision"], "accept")
        self.assertIn("HTTP 503", (out / "observations-error.txt").read_text())

    def test_observations_failure_on_the_clean_replay_is_needs_review_not_a_fixture_pass(self):
        fixed = load(REPO / "agents" / "fixtures" / "obs-fixed.json", "observations")
        doc, out = self.verify_with([fixed, SystemExit("observations unavailable: HTTP 429")])
        clean = next(c for c in doc["checks"] if c["kind"] == "clean")
        self.assertEqual(clean["result"], "needs-review")
        self.assertEqual(doc["suite"]["clean"]["source"], "unavailable")
        self.assertNotEqual(doc["decision"], "accept")
        self.assertIn("HTTP 429", (out / "observations-clean-error.txt").read_text())


ROBOT = lambda i: box_token(0, (60, 40, 80, 70), 0.9)
COINS = lambda i: box_token(0, (100, 20, 108, 28), 0.85) + "," + box_token(1, (120, 20, 128, 28), 0.8)


class VerifierWithSamTest(unittest.TestCase):
    """EXPECTRAIL_OBS_PROVIDER=sam: the ground spec on the engine, the SAM specs on SAM's view."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.scene = Scene(self.root / "scene", extra={"blue robot": ROBOT, "gold coin": COINS})

    def harness(self, route, harness_out, patches=None, **_kw):
        harness_out.mkdir(parents=True, exist_ok=True)
        (harness_out / "trace.json").write_text((REPO / "agents" / "fixtures" / "trace-fixed.json").read_text())
        (harness_out / "replay.json").write_text("{}\n")
        (harness_out / "frames").mkdir(exist_ok=True)
        for i in range(120):
            (harness_out / "frames" / f"f{i:08d}.png").write_bytes(png_bytes(W, H, i))

    def verify(self, transport, **kw):
        from agents.verifier import verify
        from tests.test_agents import _request
        out = self.root / "verify"
        real = sam.MetaSamClient
        env = {"EXPECTRAIL_OBS_PROVIDER": "sam", "EXPECTRAIL_SAM_CACHE": "off"}
        with mock.patch.dict(os.environ, env), \
                mock.patch("agents.verifier.harness_run", side_effect=self.harness), \
                mock.patch.object(sam, "MetaSamClient", side_effect=lambda: real(transport=transport, retries=0)):
            os.environ.pop("EXPECTRAIL_HELDOUT_DIR", None)
            doc = verify(_request(), REPO / "agents" / "fixtures" / "fix-collision-mask.patch", out, **kw)
        validate(doc, "verification")
        return doc, out

    def by(self, doc, kind):
        return {c["spec"]: c["result"] for c in doc["checks"] if c["kind"] == kind}

    def test_sam_specs_join_the_engine_ground_check(self):
        doc, out = self.verify(self.scene.transport)
        self.assertEqual(self.by(doc, "regression"), {"player-stays-above-ground": "pass",
                                                      "player-always-visible": "pass", "coins-visible": "pass"})
        self.assertEqual(self.by(doc, "clean"), {"player-stays-above-ground": "pass",
                                                 "player-always-visible": "pass", "coins-visible": "pass"})
        self.assertTrue((out / "observations-player-always-visible.json").is_file())
        self.assertTrue((out / "verdict-clean-coins-visible.json").is_file())
        self.assertAlmostEqual(
            json.loads((out / "verdict-clean-coins-visible.json").read_text())["samMinScore"], 0.85)
        self.assertEqual(json.loads((out / "observations.json").read_text())["model"]["name"],
                         "expectrail.trace-synthetic")
        self.assertIn("position log against the clean level's ground line", doc["suite"]["candidate"]["detail"])
        self.assertIn("player-always-visible", doc["suite"]["clean"]["detail"])
        # No private held-out set here: SAM never saw a held-out route, so no accept.
        self.assertEqual({c["spec"]: c["result"] for c in doc["checks"]
                          if c["kind"] == "held-out" and c["route"] == "held-out-interim"},
                         {"player-stays-above-ground": "pass", "player-always-visible": "needs-review",
                          "coins-visible": "needs-review"})
        self.assertNotEqual(doc["decision"], "accept")
        # The only failing check is gameplay: the fixture trace is short of the harness threshold.
        self.assertEqual([c["kind"] for c in doc["checks"] if c["result"] == "fail"], ["gameplay"])

    def test_a_sam_failure_is_needs_review_and_the_ground_check_still_runs(self):
        def down(body):
            raise urllib.error.HTTPError("u", 503, "down", {}, io.BytesIO(b"maintenance"))
        doc, out = self.verify(down)
        self.assertEqual(self.by(doc, "regression"), {"player-stays-above-ground": "pass",
                                                      "player-always-visible": "needs-review",
                                                      "coins-visible": "needs-review"})
        self.assertNotEqual(doc["decision"], "accept")
        self.assertIn("503", (out / "observations-player-always-visible-error.txt").read_text())

    def test_a_clean_run_whose_score_margin_fell_below_the_floor_is_reported_not_passed(self):
        faint = lambda i: box_token(0, (60, 40, 80, 70), 0.55)  # still above the spec's minScore (0.5)
        self.scene = Scene(self.root / "scene-faint", extra={"blue robot": faint, "gold coin": COINS})
        doc, out = self.verify(self.scene.transport)
        self.assertEqual(self.by(doc, "clean")["player-always-visible"], "needs-review")
        verdict = json.loads((out / "verdict-clean-player-always-visible.json").read_text())
        self.assertAlmostEqual(verdict["samMinScore"], 0.55)
        self.assertIn("below the floor", verdict["reason"])
        # The floor watches the clean replay only: the candidate's margin is recorded, not gated.
        self.assertEqual(self.by(doc, "regression")["player-always-visible"], "pass")
        self.assertAlmostEqual(
            json.loads((out / "verdict-player-always-visible.json").read_text())["samMinScore"], 0.55)

    def test_a_missing_player_fails_the_candidate(self):
        gone = Scene(self.root / "gone", extra={"blue robot": lambda i: ROBOT(i) if i < 30 else "",
                                                 "gold coin": COINS})
        doc, _ = self.verify(gone.transport)
        self.assertEqual(self.by(doc, "regression")["player-always-visible"], "fail")
        self.assertEqual(doc["decision"], "reject")

    def test_offline_fixtures_cannot_be_judged_by_sam(self):
        doc, out = self.verify(self.scene.transport,
                               observations_path=REPO / "agents" / "fixtures" / "obs-fixed.json", skip_harness=True)
        self.assertEqual(self.by(doc, "regression")["player-always-visible"], "needs-review")
        self.assertEqual(self.by(doc, "clean")["coins-visible"], "needs-review")
        self.assertIn("no captured frames", (out / "observations-coins-visible-error.txt").read_text())

    def test_held_out_routes_need_every_visual_spec(self):
        from agents.verifier import _run_held_out_routes
        root = self.root / "held"
        root.mkdir()
        (root / "route.json").write_text((REPO / "harness" / "routes" / "smoke.json").read_text())
        manifest = {"routes": [{"name": "a", "file": "route.json", "minDeltaX": 0}]}
        ground = load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec")
        real = sam.MetaSamClient
        gone = Scene(self.root / "gone", extra={"blue robot": lambda i: "", "gold coin": COINS})
        for transport, expected in ((self.scene.transport, "pass"), (gone.transport, "fail")):
            out = self.root / f"out-{expected}"
            with mock.patch.dict(os.environ, {"EXPECTRAIL_SAM_CACHE": "off"}), \
                    mock.patch("agents.verifier.harness_run", side_effect=self.harness), \
                    mock.patch.object(sam, "MetaSamClient", side_effect=lambda: real(transport=transport, retries=0)):
                verdict, arm_doc = _run_held_out_routes(root, manifest, ground, [], out, use_sam=True)
            row = verdict["routes"][0]
            self.assertEqual(set(row["visuals"]), {"player-stays-above-ground", "player-always-visible",
                                                   "coins-visible"})
            self.assertEqual(row["visual"], expected)
            self.assertIn("SAM specs", arm_doc["detail"])

    def test_without_sam_held_out_evidence_is_unchanged(self):
        from agents.verifier import _run_held_out_routes
        root = self.root / "held"
        root.mkdir()
        (root / "route.json").write_text((REPO / "harness" / "routes" / "smoke.json").read_text())
        manifest = {"routes": [{"name": "a", "file": "route.json", "minDeltaX": 0}]}
        ground = load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec")
        with mock.patch("agents.verifier.harness_run", side_effect=self.harness):
            verdict, arm_doc = _run_held_out_routes(root, manifest, ground, [], self.root / "out")
        self.assertNotIn("visuals", verdict["routes"][0])
        self.assertNotIn("SAM", arm_doc["detail"])

    def test_sam_spec_ids_cannot_shadow_the_ground_spec(self):
        from agents.verifier import sam_specs
        with mock.patch.dict(os.environ, {"EXPECTRAIL_SAM_SPECS": "specs/player-stays-above-ground.json"}):
            with self.assertRaises(SystemExit):
                sam_specs("player-stays-above-ground")
        with mock.patch.dict(os.environ, {"EXPECTRAIL_SAM_SPECS":
                                          "specs/coins-visible.json,specs/coins-visible.json"}):
            with self.assertRaises(SystemExit):
                sam_specs("player-stays-above-ground")
        with mock.patch.dict(os.environ, {"EXPECTRAIL_SAM_SPECS": ""}):
            self.assertEqual([s["id"] for s in sam_specs("player-stays-above-ground")],
                             ["player-always-visible", "coins-visible"])

    def test_the_loop_rejects_a_mistyped_provider_before_the_fixer_runs(self):
        from agents import loop
        with mock.patch.dict(os.environ, {"EXPECTRAIL_OBS_PROVIDER": "sma"}), \
                mock.patch.object(loop, "one_run") as one_run:
            with self.assertRaises(SystemExit):
                loop.main(["--out", str(self.root / "loop")])
        one_run.assert_not_called()

    def test_the_hide_the_player_fixture_is_a_valid_candidate(self):
        from agents.patchutil import assert_editable, paths_touched
        text = (REPO / "agents" / "fixtures" / "fix-but-hide-player.patch").read_text()
        self.assertEqual(paths_touched(text), ["player/player.tscn"])
        self.assertEqual(assert_editable(text, ["player/**", "level/**"]), [])
        self.assertIn("+collision_mask = 30", text)   # the real fix
        self.assertIn("+z_index = -6", text)          # and the player sprite drawn behind the scenery

    def test_an_unknown_provider_stops_verify_before_any_work(self):
        from agents.verifier import verify
        from tests.test_agents import _request
        with mock.patch.dict(os.environ, {"EXPECTRAIL_OBS_PROVIDER": "nope"}), \
                mock.patch("agents.verifier.harness_run") as harness:
            with self.assertRaises(SystemExit):
                verify(_request(), REPO / "agents" / "fixtures" / "fix-collision-mask.patch", self.root / "v")
        harness.assert_not_called()


# The clean level for these synthetic traces: one solid floor whose top is at y 650.
LEVEL = [[[-2000.0, 650.0], [4000.0, 650.0], [4000.0, 714.0], [-2000.0, 714.0]]]


def ground_trace(sink: float = 0.0, ticks: int = 240, ground: float = 650.0, view=(2.0, 0.0, 0.0, 2.0, 600.0, -520.0)):
    """A harness-shaped trace with the engine's ground line and camera: the player stands on the
    ground (origin 13.25 above it, as in the clean game), sunk by ``sink`` world px."""
    rows = []
    for tick in range(ticks):
        v = [2.0, 0.0, 0.0, 2.0, 0.0, 0.0] if tick < 2 else list(view)  # camera settles after the first draw
        rows.append({"tick": tick, "frame": tick // 2, "player": [90.0 + tick, ground - 13.25 + sink],
                     "onFloor": True, "ground": ground, "view": v})
    return {"format": "expectrail.trace/v0", "ticks": ticks, "physicsTicksPerSecond": 120, "rows": rows}


class EngineGroundTest(unittest.TestCase):
    def test_ground_line_lands_in_frame_pixels_with_the_settled_camera(self):
        from agents.observations import engine_ground_by_frame, has_engine_ground
        trace = ground_trace()
        self.assertTrue(has_engine_ground(trace))
        by_frame = engine_ground_by_frame(trace, (1600, 960), [0, 1, 59])
        self.assertEqual({n: by_frame[n]["ground"][0]["box"][1] for n in (0, 1, 59)}, {0: 780.0, 1: 780.0, 59: 780.0})
        self.assertEqual(by_frame[0]["ground"][0]["source"], "engine")
        self.assertFalse(has_engine_ground({"rows": [{"tick": 0, "player": [0, 0]}]}))

    def test_the_position_log_now_sees_a_player_resting_too_low(self):
        from agents.observations import from_trace_synthetic
        ground_spec = load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec")
        self.assertEqual(evaluate(ground_spec, from_trace_synthetic(ground_trace()))["result"], "pass")
        self.assertEqual(evaluate(ground_spec, from_trace_synthetic(ground_trace(sink=26)))["result"], "fail")
        # An older trace has neither the ground line nor the camera: the floor then comes from the
        # player itself and a uniform sink is invisible. That is the gap the ground line closes.
        old = ground_trace(sink=26)
        for row in old["rows"]:
            row.pop("ground")
            row.pop("view")
        self.assertEqual(evaluate(ground_spec, from_trace_synthetic(old))["result"], "pass")

    def test_a_game_with_no_ground_to_measure_is_never_judged_against_a_guessed_one(self):
        # Today's harness logs the camera in every row and the ground line only where there is tile
        # collision under the player. Until November 12, 2026 a trace with no ground line anywhere
        # was taken for an older trace and given a floor guessed from the player; with no on-floor
        # row the guess was the player's first position or 0. Godot's Dodge the Creeps, unchanged,
        # was rejected that way: "player is 450px past the boundary (above 0, tolerance 20)" (#263).
        from agents.observations import from_trace_synthetic
        ground_spec = load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec")
        rows = [{"tick": t, "frame": t, "player": [240.0 + (t % 50), 450.0 if t >= 10 else 0.0], "onFloor": False,
                 "view": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]} for t in range(300)]
        top_down = {"format": "expectrail.trace/v0", "ticks": 300, "physicsTicksPerSecond": 60, "rows": rows}
        doc = from_trace_synthetic(top_down)
        self.assertEqual([f["objects"]["ground"] for f in doc["frames"]], [[]] * len(doc["frames"]))
        self.assertTrue(all(f["objects"]["player"] for f in doc["frames"]))
        self.assertIn("not measured", doc["model"]["ground"])
        verdict = evaluate(ground_spec, doc)
        self.assertEqual(verdict["result"], "needs-review")
        self.assertIn("a missing object is never a pass", verdict["reason"])
        # A level with ground in some places and none in others: judged where it is measured, and
        # the frames without it keep the result from a pass.
        partly = ground_trace()
        for row in partly["rows"][100:140]:
            row.pop("ground")
        self.assertEqual(evaluate(ground_spec, from_trace_synthetic(partly))["result"], "needs-review")
        sunk = ground_trace(sink=26)
        for row in sunk["rows"][100:140]:
            row.pop("ground")
        self.assertEqual(evaluate(ground_spec, from_trace_synthetic(sunk))["result"], "fail")   # a real fail still rejects

    def test_hybrid_asks_sam_for_the_robot_only_and_judges_it_against_the_engine_line(self):
        from agents.observations import engine_ground_by_frame
        ground_spec = load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec")
        root = Path(self.tmp.name)
        # In these 160x96 test frames the engine line sits at y 70; the robot's drawn feet at 72 or 100.
        line = {n: {"ground": [{"box": [0.0, 70.0, 160.0, 96.0], "score": 1.0, "source": "engine"}]}
                for n in range(120)}
        for name, feet, expected in (("ok", 72, "pass"), ("sunk", 100, "fail")):
            scene = Scene(root / name, extra={"blue robot": lambda i, f=feet: box_token(0, (60, f - 30, 80, f), 0.9)})
            doc = from_replay(frames_dir=scene.dir, spec=ground_spec, every=10, client=scene.client(),
                              cache=Cache(None), engine_objects=line)
            validate(doc, "observations")
            self.assertEqual(evaluate(ground_spec, doc)["result"], expected, name)
            self.assertEqual(doc["model"]["engineObjects"], ["ground"])
            self.assertEqual(set(doc["model"]["prompts"]), {"player"})
            self.assertTrue(all(b["input"][0]["content"][0]["text"] == "blue robot" for b in scene.bodies))
        self.assertTrue(engine_ground_by_frame(ground_trace(), (160, 96), [0]))

    def test_the_verifier_uses_the_hybrid_only_with_sam_and_a_ground_line(self):
        from agents.verifier import _ground_observations
        ground_spec = load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec")
        scene = Scene(Path(self.tmp.name) / "v", extra={"blue robot": lambda i: box_token(0, (60, 40, 80, 70), 0.9)})
        real = sam.MetaSamClient
        with mock.patch.dict(os.environ, {"EXPECTRAIL_SAM_CACHE": "off"}), \
                mock.patch.object(sam, "MetaSamClient", side_effect=lambda: real(transport=scene.transport, retries=0)):
            _, source = _ground_observations(ground_spec, ground_trace(), "0" * 64, scene.dir, True, LEVEL)
            self.assertEqual(source, "hybrid")
            _, source = _ground_observations(ground_spec, ground_trace(), "0" * 64, scene.dir, False, LEVEL)
            self.assertEqual(source, "engine")
            old = ground_trace()
            for row in old["rows"]:
                row.pop("ground")
                row.pop("view")
            _, source = _ground_observations(ground_spec, old, "0" * 64, scene.dir, True, None)
            self.assertEqual(source, "engine")
            # A current-harness trace without a trusted reference is needs-review, never its own yardstick.
            with self.assertRaises(SystemExit):
                _ground_observations(ground_spec, ground_trace(), "0" * 64, scene.dir, False, None)

    def test_the_sink_the_player_fixture_is_a_valid_candidate(self):
        from agents.patchutil import assert_editable, paths_touched
        text = (REPO / "agents" / "fixtures" / "fix-but-sink-player.patch").read_text()
        self.assertEqual(paths_touched(text), ["player/player.tscn"])
        self.assertEqual(assert_editable(text, ["player/**", "level/**"]), [])
        self.assertIn("+collision_mask = 30", text)          # the real fix
        self.assertIn("+position = Vector2(0, 12)", text)    # and the robot drawn 26 px into the ground

    def test_a_candidate_cannot_move_the_ground_it_is_judged_by(self):
        from agents.observations import from_trace_synthetic, with_reference_ground
        ground_spec = load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec")
        # The candidate buries the robot 26 px and lowers its own level by 26 px to match.
        cheat = ground_trace(sink=26, ground=650.0)
        for row in cheat["rows"]:
            row["ground"] = 676.0
        self.assertEqual(evaluate(ground_spec, from_trace_synthetic(cheat))["result"], "pass")
        judged = with_reference_ground(cheat, LEVEL)
        self.assertEqual(judged["groundReference"], "clean level")
        self.assertEqual(evaluate(ground_spec, from_trace_synthetic(judged))["result"], "fail")

    def test_the_ground_search_ignores_platforms_overhead_and_counts_a_sunk_surface(self):
        from agents.observations import surface_under
        platform = [[0.0, 400.0], [200.0, 400.0], [200.0, 464.0], [0.0, 464.0]]
        ramp = [[300.0, 650.0], [400.0, 600.0], [400.0, 714.0], [300.0, 714.0]]
        level = LEVEL + [platform, ramp]
        self.assertEqual(surface_under(level, 100.0, 636.75), 650.0)   # standing under a platform
        self.assertEqual(surface_under(level, 100.0, 662.75), 650.0)   # sunk 26 px: still that surface
        self.assertEqual(surface_under(level, 100.0, 396.75), 400.0)   # standing on the platform
        self.assertAlmostEqual(surface_under(level, 350.0, 600.0), 615.0)  # highest point under the body on the ramp
        self.assertIsNone(surface_under([], 0.0, 0.0))

    def test_a_frame_is_drawn_with_the_camera_logged_one_tick_later(self):
        from agents.observations import engine_ground_by_frame
        trace = ground_trace()
        for row in trace["rows"]:
            row["view"] = [2.0, 0.0, 0.0, 2.0, 0.0, -float(row["tick"])]  # the camera scrolls 1 px a tick
        by_frame = engine_ground_by_frame(trace, (1600, 960), [10, 119])
        self.assertEqual(by_frame[10]["ground"][0]["box"][1], 2 * 650.0 - 22)    # frame 10 shows tick 21, camera of tick 22
        self.assertEqual(by_frame[119]["ground"][0]["box"][1], 2 * 650.0 - 239)  # the last frame keeps its own

    def test_the_reference_level_comes_from_an_unpatched_replay_and_is_memoized(self):
        import agents.verifier as verifier
        calls = []

        def harness(route, out, patches=None, **_kw):
            calls.append(patches)
            out.mkdir(parents=True, exist_ok=True)
            (out / "trace.json").write_text(json.dumps({"rows": [], "levelSurfaces": LEVEL}))
        with mock.patch.object(verifier, "harness_run", side_effect=harness), \
                mock.patch.dict(verifier._REFERENCE_SURFACES, {}, clear=True):
            self.assertEqual(verifier.reference_surfaces(Path(self.tmp.name)), LEVEL)
            self.assertEqual(verifier.reference_surfaces(Path(self.tmp.name)), LEVEL)
        self.assertEqual(calls, [[]])  # one replay, with no patches at all

        def broken(route, out, patches=None, **_kw):
            raise OSError("godot aborted")
        with mock.patch.object(verifier, "harness_run", side_effect=broken), \
                mock.patch.dict(verifier._REFERENCE_SURFACES, {}, clear=True):
            self.assertIsNone(verifier.reference_surfaces(Path(self.tmp.name)))

    def test_the_lower_the_floor_fixture_moves_the_level_not_just_the_player(self):
        from agents.patchutil import assert_editable, paths_touched
        text = (REPO / "agents" / "fixtures" / "fix-and-lower-the-floor.patch").read_text()
        self.assertEqual(sorted(paths_touched(text)), ["level/tileset.tres", "player/player.tscn"])
        self.assertEqual(assert_editable(text, ["player/**", "level/**"]), [])
        self.assertIn("PackedVector2Array(-32, 4, 32, 4, 32, 32, -32, 32)", text)

    def test_the_sinking_bugs_are_valid_patches_on_the_player(self):
        from agents.patchutil import paths_touched
        for v, line in (("v1", "+position = Vector2(0, -40)"), ("v2", "+position = Vector2(0, 12)")):
            text = (REPO / "bugs" / "sinking" / f"{v}.patch").read_text()
            self.assertEqual(paths_touched(text), ["player/player.tscn"], v)
            self.assertIn(line, text)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
