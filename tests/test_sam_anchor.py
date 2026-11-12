"""The anchored SAM probe, offline: a point at the engine's player position, not words (#330).

A scripted transport stands in for the Meta Model API, so nothing here is sent or paid for. What a
live reply to a point looks like is taken from the Model API's page (one record per prompted
object, under its id); what comes back when nothing is drawn there is not on that page, so both
an empty reply and a reply that cannot be read are held here: neither is ever a made-up box.
Standard library only.
"""
from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import agents.sam_observations as sam
from agents import sam_anchor as anchor
from agents.sam_observations import MetaSamClient, SamError, point_prompt
from tests.test_sam import box_token, png_bytes

W, H = 160, 96
REPO = Path(__file__).resolve().parent.parent


def reply(text: str):
    return json.dumps({"output_text": text}).encode(), "application/json"


def trace(ticks: int = 60, *, scale: float = 2.0, shift=(-100.0, -20.0), player=lambda t: (60.0 + 2 * t, 30.0)) -> dict:
    """A position log at 120 ticks a second (two ticks a frame). The player moves 2 px right a tick and
    the camera 1 px left, so the wrong tick's row or camera shows up as a point some pixels off."""
    rows = []
    for t in range(ticks):
        rows.append({"tick": t, "player": list(player(t)) if player(t) else None,
                     "view": [scale, 0.0, 0.0, scale, shift[0] - t, shift[1]]})
    return {"physicsTicksPerSecond": 120, "rows": rows}


class Run:
    """A run folder: frames/f*.png and trace.json. Every frame's bytes differ, so a request names its frame."""

    def __init__(self, root: Path, name: str = "clean", frames: int = 30, doc: dict | None = None):
        self.dir = root / name
        (self.dir / "frames").mkdir(parents=True)
        self.index = {}
        for i in range(frames):
            data = png_bytes(W, H, i)
            (self.dir / "frames" / f"f{i:08d}.png").write_bytes(data)
            self.index[base64.b64encode(data).decode()] = i
        if doc is not None:
            (self.dir / "trace.json").write_text(json.dumps(doc), encoding="utf-8")
        self.sent = []          # (frame, the text that was sent)

    def frame_of(self, body: dict) -> int:
        content = body["input"][0]["content"]
        frame = self.index[content[1]["image_url"].split(",", 1)[1]]
        self.sent.append((frame, content[0]["text"]))
        return frame


class TempCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        saved = dict(sam._usage)
        self.addCleanup(sam._usage.update, saved)
        sam._usage.update({"requests": 0, "images": 0, "videoFrames": 0, "reservedUsd": 0.0})
        env = mock.patch.dict(os.environ, {k: v for k, v in os.environ.items()
                                           if k not in (sam.CAP_ENV, sam.BACKEND_ENV, "GITHUB_ACTIONS")}, clear=True)
        env.start()
        self.addCleanup(env.stop)


class PointPromptTest(unittest.TestCase):
    def test_one_point_in_the_model_apis_grammar(self):
        self.assertEqual(point_prompt([(30, 40)], (W, H)), "<0f>1<|point;x=30;y=40;w=160;h=96|>")

    def test_each_point_is_its_own_object(self):
        self.assertEqual(point_prompt([(0, 0), (159, 95)], (W, H)),
                         "<0f>1<|point;x=0;y=0;w=160;h=96|>,2<|point;x=159;y=95;w=160;h=96|>")

    def test_a_point_outside_the_image_is_refused_before_anything_is_sent(self):
        for point in ((160, 10), (10, 96), (-1, 10), (10, -1)):
            with self.subTest(point=point), self.assertRaises(ValueError):
                point_prompt([point], (W, H))

    def test_a_point_is_whole_pixels_and_there_is_at_least_one(self):
        for points in ([], [(1.5, 2)], [("1", 2)], [(True, 2)]):
            with self.subTest(points=points), self.assertRaises(ValueError):
                point_prompt(points, (W, H))


class SegmentAtTest(TempCase):
    def setUp(self):
        super().setUp()
        self.png = self.tmp / "f.png"
        self.png.write_bytes(png_bytes(W, H, 1))
        self.bodies = []

    def client(self, text: str) -> MetaSamClient:
        def transport(body):
            self.bodies.append(body)
            return reply(text)
        return MetaSamClient(transport=transport, sleep=lambda s: None)

    def test_the_request_is_the_point_and_the_image_and_no_words(self):
        found = self.client("<0f>" + box_token(1, (20, 30, 44, 60), 0.93)).segment_at(self.png, [(30, 40)])
        self.assertEqual(found, [{"box": [20.0, 30.0, 44.0, 60.0], "score": 0.93}])
        content = self.bodies[0]["input"][0]["content"]
        self.assertEqual(content[0], {"type": "input_text", "text": "<0f>1<|point;x=30;y=40;w=160;h=96|>"})
        self.assertEqual(content[1]["type"], "input_image")
        self.assertEqual(self.bodies[0]["metadata"], sam.METADATA)       # confidence is asked for
        self.assertEqual(len(self.bodies), 1)

    def test_an_empty_reply_is_nothing_at_the_point(self):
        self.assertEqual(self.client("").segment_at(self.png, [(30, 40)]), [None])
        self.assertEqual(self.client("<0f>").segment_at(self.png, [(30, 40)]), [None])

    def test_a_box_without_a_confidence_keeps_its_box_and_has_no_score(self):
        found = self.client("<0f>" + box_token(1, (20, 30, 44, 60))).segment_at(self.png, [(30, 40)])
        self.assertEqual(found, [{"box": [20.0, 30.0, 44.0, 60.0], "score": None}])

    def test_answers_come_back_in_the_points_order(self):
        text = "<0f>" + box_token(2, (100, 10, 120, 30), 0.7) + "," + box_token(1, (20, 30, 44, 60), 0.9)
        found = self.client(text).segment_at(self.png, [(30, 40), (110, 20), (5, 5)])
        self.assertEqual([f and f["score"] for f in found], [0.9, 0.7, None])

    def test_a_reply_about_an_object_nobody_asked_for_is_an_error(self):
        for oid in (0, 2):
            with self.subTest(id=oid), self.assertRaises(SamError):
                self.client("<0f>" + box_token(oid, (20, 30, 44, 60), 0.9)).segment_at(self.png, [(30, 40)])

    def test_two_boxes_for_one_point_is_an_error_and_never_a_pick(self):
        text = "<0f>" + box_token(1, (20, 30, 44, 60), 0.9) + "," + box_token(1, (0, 0, 160, 96), 0.95)
        with self.assertRaises(SamError):
            self.client(text).segment_at(self.png, [(30, 40)])

    def test_words_in_the_reply_are_an_error_and_never_nothing_found(self):
        with self.assertRaises(SamError) as failed:
            self.client("I cannot segment a point.").segment_at(self.png, [(30, 40)])
        self.assertIn("cannot segment", str(failed.exception))
        self.assertEqual((failed.exception.kind, failed.exception.status), ("unknown", None))

    def test_it_is_counted_against_the_runs_cap_like_any_image(self):
        with mock.patch.dict(os.environ, {sam.CAP_ENV: "0.0025"}):
            client = self.client("<0f>" + box_token(1, (20, 30, 44, 60), 0.9))
            client.segment_at(self.png, [(30, 40)])
            with self.assertRaises(SamError) as stopped:
                client.segment_at(self.png, [(31, 40)])
        self.assertEqual((stopped.exception.kind, len(self.bodies)), ("budget", 1))

    def test_the_real_sender_sends_no_point_without_a_cap(self):
        with mock.patch.dict(os.environ, {sam.KEY_ENV: "not-a-real-key"}), \
                mock.patch("urllib.request.urlopen") as opened, self.assertRaises(SamError) as refused:
            MetaSamClient(sleep=lambda s: None).segment_at(self.png, [(30, 40)])
        self.assertEqual(refused.exception.kind, "budget")
        opened.assert_not_called()


class AnchorsTest(unittest.TestCase):
    def test_the_point_is_the_players_place_in_that_frames_own_pixels(self):
        # Frame 5 shows tick 11 (the last tick before it was drawn), with the camera logged on tick 12.
        # Player at tick 11: (82, 30). Camera at tick 12: x shift -112. 2 * 82 - 112 = 52; 2 * 30 - 20 = 40.
        # (Tick 10's row would give 48, tick 11's camera 53.)
        where = anchor.anchors(trace(), (W, H), [5])
        self.assertEqual(where[5], {"world": [82.0, 30.0], "point": [52, 40], "scale": [2.0, 2.0]})

    def test_a_lift_moves_the_point_up_in_game_pixels(self):
        self.assertEqual(anchor.anchors(trace(), (W, H), [5], lift=10.0)[5]["point"], [52, 20])

    def test_a_player_outside_the_picture_is_not_asked_about(self):
        off = anchor.anchors(trace(player=lambda t: (200.0, 30.0)), (W, H), [5])[5]
        self.assertEqual(off["why"], "the player is outside the picture")
        self.assertEqual(off["point"], [288, 40])
        above = anchor.anchors(trace(player=lambda t: (71.0, 5.0)), (W, H), [5])[5]
        self.assertEqual((above["why"], above["point"]), ("the player is outside the picture", [30, -10]))

    def test_a_player_exactly_on_the_right_or_bottom_edge_is_asked_about_at_the_last_pixel_inside(self):
        # Camera at tick 12: x shift -112, y shift -20, scale 2. x = 136 lands on 160, the picture's
        # width; y = 58 lands on 96, its height. One game pixel further is outside.
        self.assertEqual(anchor.anchors(trace(player=lambda t: (136.0, 30.0)), (W, H), [5])[5]["point"], [159, 40])
        self.assertEqual(anchor.anchors(trace(player=lambda t: (82.0, 58.0)), (W, H), [5])[5]["point"], [52, 95])
        corner = anchor.anchors(trace(player=lambda t: (136.0, 58.0)), (W, H), [5])[5]
        self.assertEqual((corner["point"], "why" in corner), ([159, 95], False))
        for player in ((136.5, 30.0), (82.0, 58.5)):
            with self.subTest(player=player):
                self.assertEqual(anchor.anchors(trace(player=lambda t: player), (W, H), [5])[5]["why"],
                                 "the player is outside the picture")

    def test_no_player_no_camera_or_no_row_is_said_and_never_guessed(self):
        self.assertEqual(anchor.anchors(trace(player=lambda t: None), (W, H), [5])[5],
                         {"why": "the engine logged no player"})
        blind = trace()
        for row in blind["rows"]:
            row["view"] = None
        self.assertEqual(anchor.anchors(blind, (W, H), [5])[5], {"why": "the engine logged no camera"})
        self.assertEqual(anchor.anchors(trace(ticks=10), (W, H), [5])[5],
                         {"why": "the position log ends before this frame"})


class MeasureTest(unittest.TestCase):
    WHERE = {"world": [71.0, 30.0], "point": [30, 40], "scale": [2.0, 2.0]}

    def test_a_box_is_measured_against_the_point_in_game_pixels(self):
        row = anchor.measure(self.WHERE, {"box": [20.0, 10.0, 44.0, 60.0], "score": 0.93}, (W, H))
        self.assertEqual(row["holdsPoint"], True)
        self.assertEqual((row["size"], row["worldSize"]), ([24.0, 50.0], [12.0, 25.0]))
        self.assertEqual((row["aboveOrigin"], row["belowOrigin"]), (15.0, 10.0))
        self.assertEqual(row["frameShare"], round(24 * 50 / (W * H), 4))
        self.assertEqual(row["score"], 0.93)

    def test_a_box_beside_the_point_does_not_hold_it(self):
        for box in ([31.0, 10.0, 44.0, 60.0], [20.0, 10.0, 30.0, 60.0], [20.0, 41.0, 44.0, 60.0], [20.0, 10.0, 44.0, 40.0]):
            with self.subTest(box=box):
                self.assertEqual(anchor.measure(self.WHERE, {"box": box, "score": 0.9}, (W, H))["holdsPoint"], False)

    def test_a_box_the_size_of_the_frame_shows_as_the_whole_frame(self):
        row = anchor.measure(self.WHERE, {"box": [0.0, 0.0, 160.0, 96.0], "score": 0.8}, (W, H))
        self.assertEqual((row["frameShare"], row["holdsPoint"]), (1.0, True))

    def test_nothing_back_is_a_row_with_no_box(self):
        row = anchor.measure(self.WHERE, None, (W, H))
        self.assertEqual((row["box"], row["score"], row["note"]), (None, None, "nothing came back for the point"))
        self.assertNotIn("holdsPoint", row)


class ProbeRunTest(TempCase):
    def client(self, run: Run, answer):
        def transport(body):
            return answer(run.frame_of(body))
        return MetaSamClient(transport=transport, sleep=lambda s: None)

    def test_every_chosen_frame_is_asked_at_its_own_point(self):
        run = Run(self.tmp, doc=trace())
        result = anchor.probe_run(run.dir, None, 10, 120, 0.0,
                                  self.client(run, lambda n: reply("<0f>" + box_token(1, (20, 30, 44, 60), 0.9))), None)
        # Frames 0, 10, 20 and the last (29). A frame is two ticks: the player moves 4 px and the camera
        # 2 px, so the point moves 2 * 4 - 2 = 6 px a frame from frame 0's 2 * 62 - 102 = 22. At frame
        # 29 it is at x = 197, outside the 160 px picture, and nothing is sent for it.
        self.assertEqual(result["framesProbed"], [0, 10, 20, 29])
        self.assertEqual(run.sent, [(0, "<0f>1<|point;x=22;y=40;w=160;h=96|>"),
                                    (10, "<0f>1<|point;x=82;y=40;w=160;h=96|>"),
                                    (20, "<0f>1<|point;x=142;y=40;w=160;h=96|>")])
        last = result["frames"][-1]
        self.assertEqual((last["frame"], last["asked"], last["note"]), (29, False, "the player is outside the picture"))
        s = result["summary"]
        self.assertEqual((s["frames"], s["asked"], s["notAsked"], s["answered"], s["holdsPoint"]), (4, 3, 1, 3, 1))
        self.assertEqual(s["score"], {"min": 0.9, "median": 0.9, "max": 0.9})
        self.assertEqual(s["worldWidth"], {"min": 12.0, "median": 12.0, "max": 12.0})

    def test_a_reply_that_cannot_be_read_is_written_down_and_the_run_goes_on(self):
        run = Run(self.tmp, doc=trace())
        answers = {0: "<0f>" + box_token(1, (10, 30, 30, 60), 0.9), 10: "no object at that point", 20: ""}
        result = anchor.probe_run(run.dir, [0, 10, 20], 10, 120, 0.0, self.client(run, lambda n: reply(answers[n])), None)
        rows = {r["frame"]: r for r in result["frames"]}
        self.assertEqual(rows[0]["box"], [10.0, 30.0, 30.0, 60.0])
        self.assertIn("no object at that point", rows[10]["error"])
        self.assertEqual((rows[10]["box"], rows[20]["box"], rows[20]["note"]), (None, None, "nothing came back for the point"))
        s = result["summary"]
        self.assertEqual((s["asked"], s["answered"], s["unreadable"]), (3, 1, 1))

    def test_an_http_error_stops_the_run_and_keeps_the_rows_so_far(self):
        run = Run(self.tmp, doc=trace())

        def answer(n):
            if n == 10:
                raise urllib.error.HTTPError("u", 400, "bad request", {}, io.BytesIO(b"object prompts are not enabled"))
            return reply("<0f>" + box_token(1, (10, 30, 30, 60), 0.9))

        with self.assertRaises(SamError) as stopped:
            anchor.probe_run(run.dir, [0, 10, 20], 10, 120, 0.0, self.client(run, answer), None)
        self.assertEqual((stopped.exception.kind, stopped.exception.status), ("request", 400))
        self.assertEqual([r["frame"] for r in stopped.exception.partial["frames"]], [0])
        self.assertEqual([n for n, _ in run.sent], [0, 10])            # frame 20 was never sent

    def test_the_cap_stops_the_run_and_keeps_the_rows_so_far(self):
        run = Run(self.tmp, doc=trace())
        with mock.patch.dict(os.environ, {sam.CAP_ENV: "0.005"}), self.assertRaises(SamError) as stopped:
            anchor.probe_run(run.dir, [0, 10, 20], 10, 120, 0.0,
                             self.client(run, lambda n: reply("<0f>" + box_token(1, (10, 30, 30, 60), 0.9))), None)
        self.assertEqual(stopped.exception.kind, "budget")
        self.assertEqual([r["frame"] for r in stopped.exception.partial["frames"]], [0, 10])
        self.assertEqual(len(run.sent), 2)

    def test_a_run_without_its_position_log_is_refused(self):
        run = Run(self.tmp)
        with self.assertRaises(SamError) as refused:
            anchor.probe_run(run.dir, None, 10, 120, 0.0, self.client(run, lambda n: reply("")), None)
        self.assertIn("trace.json", str(refused.exception))
        self.assertEqual(run.sent, [])


class MainTest(TempCase):
    def run_main(self, argv, transport=None):
        out, err = io.StringIO(), io.StringIO()
        made = []

        def client(*args, **kwargs):
            made.append(1)
            return MetaSamClient(transport=transport, sleep=lambda s: None)

        with mock.patch.object(anchor, "MetaSamClient", client), mock.patch("agents.keys.load_dotenv", lambda: None), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = anchor.main([str(a) for a in argv])
        return code, out.getvalue(), err.getvalue(), made

    def test_a_dry_run_prints_the_points_and_makes_no_client(self):
        run = Run(self.tmp, doc=trace())
        code, out, _, made = self.run_main(["--runs", run.dir, "--out", self.tmp / "out", "--dry-run"])
        self.assertEqual((code, made), (0, []))
        self.assertIn("clean: f0@22,40 f10@82,40 f20@142,40 f29(not asked: the player is outside the picture)", out)
        self.assertIn("3 requests at most", out)
        self.assertFalse((self.tmp / "out").exists())

    def test_a_live_run_leaves_the_table_and_the_numbers(self):
        run = Run(self.tmp, doc=trace())
        transport = lambda body: (run.frame_of(body), reply("<0f>" + box_token(1, (10, 30, 150, 60), 0.9)))[1]  # noqa: E731
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            code, out, _, _ = self.run_main(["--runs", run.dir, "--out", self.tmp / "out"], transport)
        self.assertEqual(code, 0)
        report = json.loads((self.tmp / "out" / "anchor.json").read_text(encoding="utf-8"))
        self.assertEqual((report["stats"]["calls"], report["stats"]["reservedUsd"], report["stopped"]), (3, 0.0075, None))
        self.assertEqual(report["runs"][0]["summary"]["holdsPoint"], 3)
        page = (self.tmp / "out" / "anchor.md").read_text(encoding="utf-8")
        self.assertIn("| clean | 3 of 4 | 3 | 3 | 0.9 / 0.9 / 0.9 | 70 / 70 / 70 | 15 / 15 / 15 | 10 / 10 / 10 | 27.3% |", page)
        self.assertIn("| 29 | 178, 30 | 197, 40 | none |  |  |  |  | the player is outside the picture |", page)
        self.assertIn("::notice title=SAM anchor clean::asked 3 of 4; answered 3; holds the point 3", out)
        self.assertIn("f0 pt 22,40 box 10,30,150,60 c 0.9", out)
        self.assertIn("::notice title=SAM anchor summary::calls 3; counted $0.0075", out)

    def test_a_stop_still_leaves_what_was_measured_and_fails_the_step(self):
        run = Run(self.tmp, doc=trace())
        transport = lambda body: (run.frame_of(body), reply("<0f>" + box_token(1, (10, 30, 150, 60), 0.9)))[1]  # noqa: E731
        with mock.patch.dict(os.environ, {sam.CAP_ENV: "0.005", "GITHUB_ACTIONS": "true"}):
            code, out, err, _ = self.run_main(["--runs", run.dir, "--out", self.tmp / "out"], transport)
        self.assertEqual(code, 2)
        report = json.loads((self.tmp / "out" / "anchor.json").read_text(encoding="utf-8"))
        self.assertIn("spend cap is reached", report["stopped"])
        self.assertEqual([r["frame"] for r in report["runs"][0]["frames"]], [0, 10])
        self.assertIn("**Stopped early:** clean:", (self.tmp / "out" / "anchor.md").read_text(encoding="utf-8"))
        self.assertIn("::error title=SAM anchor probe stopped::", out)

    def test_another_vision_backend_is_refused(self):
        run = Run(self.tmp, doc=trace())
        with mock.patch.dict(os.environ, {sam.BACKEND_ENV: "glimmer"}):
            code, _, err, made = self.run_main(["--runs", run.dir, "--out", self.tmp / "out"])
        self.assertEqual((code, made), (2, []))
        self.assertIn("SAM 3.1 only", err)

    def test_no_run_folder_with_frames_is_an_error(self):
        (self.tmp / "empty").mkdir()
        code, _, err, _ = self.run_main(["--runs", self.tmp / "empty", "--dry-run"])
        self.assertEqual(code, 2)
        self.assertIn("no run dirs with frames/", err)


class WorkflowTest(unittest.TestCase):
    """Both probe workflows: the anchored mode runs under the same cap as the words."""

    def step(self, name: str) -> str:
        text = (REPO / ".github" / "workflows" / name).read_text(encoding="utf-8")
        return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))

    def test_the_outside_probe_asks_with_a_point_when_told_to_under_its_cap(self):
        code = self.step("outside-sam-probe.yml")
        probe = code.split("\n  probe:\n", 1)[1]
        self.assertIn("anchor:\n        description:", code)
        self.assertIn("type: boolean\n        default: false", code)
        self.assertIn('[[ "$ANCHOR" == "true" || "$ANCHOR" == "false" ]]', probe)
        self.assertIn('anchor=(--every "$EVERY" --lift "$LIFT" --out runs/sam-probe --runs "${runs[@]}")', probe)
        cap, dry, live = (probe.index(s) for s in (
            'export EXPECTRAIL_SAM_USD_CAP="$CAP"',
            'python -m agents.sam_anchor "${anchor[@]}" --dry-run',
            'python -m agents.sam_anchor "${anchor[@]}"\n'))
        self.assertLess(cap, dry)
        self.assertLess(dry, live)
        self.assertIn('[[ "$LIFT" =~ ^[0-9]{1,3}$ ]]', probe)

    def test_the_bundled_probe_has_a_cap_of_at_most_two_dollars_before_anything_is_asked(self):
        code = self.step("sam-probe.yml")
        job = code.split("\n  sam-probe:\n", 1)[1].split("\n  sam-video:\n", 1)[0]
        self.assertIn("if not 0 < float(sys.argv[1]) <= 2:", job)
        cap = job.index('export EXPECTRAIL_SAM_USD_CAP="$CAP"')
        for asked in ('python -m agents.sam_anchor "${anchor[@]}" --dry-run', 'python -m agents.sam_anchor "${anchor[@]}"\n',
                      'python -m agents.sam_probe "${args[@]}"'):
            self.assertLess(cap, job.index(asked), asked)
        self.assertIn('[[ "$ANCHOR" == "true" || "$ANCHOR" == "false" ]]', job)
        self.assertIn('[[ "$LIFT" =~ ^[0-9]{1,3}$ ]]', job)
        self.assertIn('anchor=(--every "$EVERY" --lift "$LIFT" --out runs/sam-probe --runs "${dirs[@]}")', job)


if __name__ == "__main__":
    unittest.main()
