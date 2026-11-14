"""SAM 3.1 as the replay's observer for pixel checks (#286; expectrail/jit/sam_observer.py).

Offline. The SAM answers are the recorded ones of run 43337979278 (tests/data/sam-anchor/, the bundled
game's smoke route, asked with a box of 48 x 68 game px 17 px above the origin), given back by
``RecordedSamClient``, which answers only the question SAM was asked. The replays are synthetic run
folders: for each recorded frame, the trace puts the player and the camera where they make the observer
ask exactly the box SAM was asked about, and the frames are small generated PNGs of the recorded size. So
these tests show the observer plans the same frames, asks the same boxes, reads the same answers and is
judged the same way, and that it refuses a replay whose frames do not line up. They do not show SAM's
answers on a bench probe: none has been recorded."""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from agents.sam_observations import SamError
from expectrail.contracts import validate_v1
from expectrail.jit import intent as intent_mod
from expectrail.jit import offer as offer_mod
from expectrail.jit import pixel
from expectrail.jit.run import from_base_alone, generate
from expectrail.jit.sam_observer import NAME, RecordedSamClient, SamAnchorObserver
from tests.jit_fixtures import PROFILE, Case, JitGame, Transport, reply

REPO = Path(__file__).resolve().parents[1]
BOX = REPO / "tests" / "data" / "sam-anchor" / "bundled-box-48x68-smoke-and-clean-routes.json"
RECORDING = json.loads(BOX.read_text(encoding="utf-8"))
RUNS = {r["run"]: r for r in RECORDING["runs"]}
SIZE = (1600, 960)        # frame size: every recorded box fits, and the boxes are not cut by an edge
SCALE = 2.0               # the recorded worldSize is the frame size halved
LIFT = 17.0
PROBE = "hold-right"      # 340 ticks: 170 frames; the first 120, every 10, are the recorded frames
DRAWN = {"id": "player-drawn", "statement": "On hold-right the player is drawn where the engine puts it.",
         "object": "player", "observer": NAME, "probe": PROBE,
         "predicate": {"type": "visible", "minScore": 0.8}}


def png(path: Path, size, seed: int) -> None:
    """A real PNG of ``size``, its first pixel set from ``seed`` so every frame has its own digest."""
    w, h = size
    row = b"\x00" + bytes([seed % 256, (seed // 256) % 256, 7]) + b"\x00" * (3 * w - 3)
    raw = row + (b"\x00" + b"\x00" * 3 * w) * (h - 1)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def rows_from(run: dict, ticks: int, body: bool = False) -> list[dict]:
    """Trace rows that make the observer ask, on each recorded frame, the box SAM was asked about there.

    A frame shows tick 2n+1 and is drawn with the camera logged on tick 2n+2 (agents/observations.py).
    The point is the middle of the recorded box, the camera's offset is what puts the lifted player
    there, and a frame the recording did not ask about has the player far outside the picture."""
    rows = [{"player": [0.0, 0.0], "view": [SCALE, 0, 0, SCALE, 0.0, 0.0]} for _ in range(ticks)]
    for f in run["frames"]:
        n = f["frame"]
        if f.get("asked"):
            x0, y0, x1, y1 = f["promptBox"]
            fx, fy = (x0 + x1) / 2, (y0 + y1) / 2
            wx, wy = f["world"]
        else:
            fx, fy, wx, wy = -5000.0, -5000.0, 0.0, 0.0
        view = [SCALE, 0, 0, SCALE, fx - SCALE * wx, fy - SCALE * wy]
        rows[2 * n + 1] = {"player": [wx, wy + LIFT], "view": view}
        rows[2 * n + 2] = {"player": [wx, wy + LIFT], "view": view}
        if body:
            for t in (2 * n + 1, 2 * n + 2):
                rows[t]["body"] = [wx - 20, wy - 30, wx + 20, wy + 30]
    return rows


def make_run(run_dir: Path, route_name: str, rows: list[dict], frames: int = 170, size=SIZE,
             fps: int = 60, tps: int = 120, keep_trace: bool = False) -> Path:
    """A replay folder. With ``keep_trace``, the trace already there (the simulated game's) keeps its rows
    and other fields, and only gains the player, camera and body of ``rows``."""
    trace = {"physicsTicksPerSecond": tps, "rows": rows}
    if keep_trace:
        trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
        trace["rows"] = [{**old, **new} for old, new in zip(trace["rows"], rows)]
    if run_dir.exists():
        shutil.rmtree(run_dir)
    (run_dir / "frames").mkdir(parents=True)
    for n in range(frames):
        png(run_dir / "frames" / f"f{n:08d}.png", size, n)
    (run_dir / "trace.json").write_text(json.dumps(trace), encoding="utf-8")
    digests = [hashlib.sha256((run_dir / "frames" / f"f{n:08d}.png").read_bytes()).hexdigest() for n in range(frames)]
    (run_dir / "replay.json").write_text(json.dumps({
        "format": "expectrail.replay/v0", "route": {"name": route_name, "sha256": "0" * 64},
        "capture": {"fps": fps, "physicsTicksPerSecond": tps, "frames": frames, "pattern": "frames/f%08d.png"},
        "frameSha256": digests}), encoding="utf-8")
    return run_dir


ROUTE = {"format": "expectrail.route/v0", "name": PROBE, "ticks": 340, "seed": 0, "events": []}


def boxed(client) -> SamAnchorObserver:
    return SamAnchorObserver(client, box=(48, 68), lift=LIFT, first=120)


class Scratch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)


class TheFramesArePlannedFromTheRouteAlone(unittest.TestCase):
    def test_every_tenth_frame_and_the_last_the_route_fills(self):
        frames = SamAnchorObserver(object()).frames(ROUTE)
        self.assertEqual(frames, [*range(0, 170, 10), 169])

    def test_the_first_120_frames_are_the_recorded_frames(self):
        self.assertEqual(boxed(object()).frames(ROUTE), RUNS["clean"]["framesProbed"])

    def test_at_most_max_frames_with_the_first_and_the_last(self):
        long = {**ROUTE, "ticks": 1150}
        frames = SamAnchorObserver(object(), max_frames=30).frames(long)
        self.assertLessEqual(len(frames), 30)
        self.assertEqual((frames[0], frames[-1]), (0, 574))
        self.assertEqual(frames, sorted(set(frames)))

    def test_a_route_without_ticks_is_refused_and_a_very_short_one_asks_nothing(self):
        with self.assertRaises(pixel.PixelError):
            SamAnchorObserver(object()).frames({"name": PROBE})
        self.assertEqual(SamAnchorObserver(object()).frames({**ROUTE, "ticks": 1}), [])

    def test_bad_settings_are_refused(self):
        for kw in ({"lift": 3.0}, {"box": (0, 10)}, {"box": "big"}, {"every": 0}, {"max_frames": 1},
                   {"first": 0}, {"pad": -1}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                SamAnchorObserver(object(), **kw)


class TheRecordedAnswersReplayThroughTheRealObserver(Scratch):
    def ask(self, name: str):
        run_dir = make_run(self.tmp / name, PROBE, rows_from(RUNS[name], 340))
        client = RecordedSamClient(BOX, name)
        return boxed(client)(run_dir, ROUTE), client

    def test_the_same_boxes_are_asked_and_the_same_answers_read(self):
        for name in ("clean", "layering_v1", "layering_v2", "missing-texture_v1", "sinking_v2"):
            with self.subTest(run=name):
                answer, client = self.ask(name)
                recorded = {f["frame"]: f for f in RUNS[name]["frames"]}
                self.assertEqual(answer["run"]["framesProbed"], RUNS[name]["framesProbed"])
                for f in answer["run"]["frames"]:
                    r = recorded[f["frame"]]
                    self.assertEqual(f["asked"], r["asked"])
                    for key in ("promptBox", "box", "score", "holdsPoint"):
                        self.assertEqual(f.get(key), r.get(key), (name, f["frame"], key))
                asked = sum(1 for f in RUNS[name]["frames"] if f["asked"])
                self.assertEqual(answer["images"], asked)
                self.assertEqual(client.calls, asked)
                self.assertEqual(answer["setting"], pixel.setting_of(RECORDING))
                self.assertEqual(answer["run"]["route"]["name"], PROBE)

    def test_judged_as_the_recording_was(self):
        check, why = pixel.parse_candidate(DRAWN, pixel.BUNDLED_BINDINGS, [PROBE])
        self.assertIsNone(why)
        results = {name: pixel.judge(check, self.ask(name)[0]["run"])["result"]
                   for name in ("clean", "layering_v1", "layering_v2", "missing-texture_v1")}
        self.assertEqual(results, {"clean": "pass", "layering_v1": "fail", "layering_v2": "fail",
                                   "missing-texture_v1": "pass"})

    def test_a_player_outside_the_picture_is_a_gap(self):
        answer, _ = self.ask("physics-fall-through_v1")
        check, _ = pixel.parse_candidate(DRAWN, pixel.BUNDLED_BINDINGS, [PROBE])
        self.assertEqual(pixel.judge(check, answer["run"])["result"], "needs-review")

    def test_a_recording_asked_another_way_is_refused(self):
        run_dir = make_run(self.tmp / "clean", PROBE, rows_from(RUNS["clean"], 340, body=True))
        with self.assertRaisesRegex(pixel.PixelError, "recorded answers were asked with"):
            SamAnchorObserver(RecordedSamClient(BOX, "clean"), first=120)(run_dir, ROUTE)


class TheFramesMustLineUp(Scratch):
    def setUp(self):
        super().setUp()
        self.run_dir = make_run(self.tmp / "clean", PROBE, rows_from(RUNS["clean"], 340))
        self.client = RecordedSamClient(BOX, "clean")

    def refused(self, pattern):
        with self.assertRaisesRegex(pixel.PixelError, pattern) as ctx:
            boxed(self.client)(self.run_dir, ROUTE)
        return ctx.exception

    def edit_replay(self, **changes):
        path = self.run_dir / "replay.json"
        doc = json.loads(path.read_text())
        for key, value in changes.items():
            target = doc
            *parents, last = key.split(".")
            for p in parents:
                target = target[p]
            target[last] = value
        path.write_text(json.dumps(doc))

    def test_a_replay_of_another_route(self):
        self.edit_replay(**{"route.name": "hold-left"})
        self.refused("the replay is of 'hold-left'")

    def test_another_frame_rate(self):
        self.edit_replay(**{"capture.fps": 30})
        self.refused("planned at 60 fps")

    def test_another_physics_rate(self):
        self.edit_replay(**{"capture.physicsTicksPerSecond": 60})
        self.refused("120 ticks a second")

    def test_no_replay_record(self):
        (self.run_dir / "replay.json").unlink()
        self.refused("no readable replay.json")

    def test_a_hole_in_the_frames(self):
        (self.run_dir / "frames" / "f00000050.png").unlink()
        self.refused("not the replay's")

    def test_a_frame_that_is_not_the_replays_and_what_was_sent_rides_on_the_error(self):
        png(self.run_dir / "frames" / "f00000040.png", SIZE, 999)
        exc = self.refused("frame 40 on disk is not the frame the replay recorded")
        self.assertEqual(exc.images, 4)   # frames 0, 10, 20, 30 were asked first

    def test_frames_the_replay_did_not_capture_are_gaps(self):
        short = make_run(self.tmp / "short", PROBE, rows_from(RUNS["clean"], 340), frames=101)
        answer = boxed(self.client)(short, ROUTE)
        missing = [f["frame"] for f in answer["run"]["frames"] if not f["asked"]]
        self.assertEqual(missing, [110, 119])
        self.assertEqual(answer["images"], 11)
        check, _ = pixel.parse_candidate(DRAWN, pixel.BUNDLED_BINDINGS, [PROBE])
        verdict = pixel.judge(check, answer["run"])
        self.assertEqual(verdict["result"], "needs-review")
        self.assertIn("did not capture", verdict["reason"])

    def test_a_question_the_recording_was_not_asked_stops_the_run(self):
        rows = rows_from(RUNS["clean"], 340)
        rows[2 * 20 + 2]["view"][4] += 6.0   # frame 20 now asks a box 6 px to the right
        run_dir = make_run(self.tmp / "moved", PROBE, rows)
        with self.assertRaisesRegex(pixel.PixelError, "frame 20: asked about") as ctx:
            boxed(self.client)(run_dir, ROUTE)
        self.assertEqual(ctx.exception.images, 3)


class AskedWithTheBodyBox(Scratch):
    class Client:
        model = "sam-3.1"

        def __init__(self, fail_at=None, kind="auth"):
            self.calls, self.boxes, self.fail_at, self.kind = 0, [], fail_at, kind

        def segment_in(self, png_path, boxes):
            self.calls += 1
            self.boxes.append(list(boxes[0]))
            if self.fail_at is not None and self.calls == self.fail_at:
                raise SamError("no", kind=self.kind)
            x0, y0, x1, y1 = boxes[0]
            return [{"box": [x0 + 4, y0 + 4, x1 - 4, y1 - 4], "score": 0.9}]

    def test_the_box_is_the_logged_body_widened_by_pad(self):
        run_dir = make_run(self.tmp / "clean", PROBE, rows_from(RUNS["clean"], 340, body=True))
        client = self.Client()
        observer = SamAnchorObserver(client, first=120)
        answer = observer(run_dir, ROUTE)
        self.assertEqual(answer["setting"], {"model": "sam-3.1", "box": "body", "pad": 4.0, "lift": 0.0})
        f0 = next(f for f in RUNS["clean"]["frames"] if f["frame"] == 0)
        x0, y0, x1, y1 = f0["promptBox"]
        fx = (x0 + x1) / 2
        # body 40 x 60 game px plus 4 each way, at scale 2: 96 x 136 frame px, centred on the body's middle
        self.assertEqual(client.boxes[0][2] - client.boxes[0][0], 96)
        self.assertIn(client.boxes[0][3] - client.boxes[0][1], (136, 137))   # floor and ceil round a half pixel
        self.assertAlmostEqual((client.boxes[0][0] + client.boxes[0][2]) / 2, fx, delta=1)
        self.assertEqual(answer["images"], 13)
        check, _ = pixel.parse_candidate(DRAWN, pixel.BUNDLED_BINDINGS, [PROBE])
        self.assertEqual(pixel.judge(check, answer["run"])["result"], "pass")

    def test_a_tick_without_a_body_box_is_a_gap(self):
        run_dir = make_run(self.tmp / "clean", PROBE, rows_from(RUNS["clean"], 340))   # no body logged
        answer = SamAnchorObserver(self.Client(), first=120)(run_dir, ROUTE)
        self.assertTrue(all(not f["asked"] for f in answer["run"]["frames"]))
        self.assertEqual(answer["images"], 0)

    def test_a_stop_ends_the_run_and_carries_what_was_sent(self):
        run_dir = make_run(self.tmp / "clean", PROBE, rows_from(RUNS["clean"], 340, body=True))
        with self.assertRaisesRegex(pixel.PixelError, "SAM stopped at frame 40") as ctx:
            SamAnchorObserver(self.Client(fail_at=5), first=120)(run_dir, ROUTE)
        self.assertEqual(ctx.exception.images, 5)

    def test_an_unreadable_reply_is_written_down_and_the_run_goes_on(self):
        run_dir = make_run(self.tmp / "clean", PROBE, rows_from(RUNS["clean"], 340, body=True))
        answer = SamAnchorObserver(self.Client(fail_at=2, kind="unreadable"), first=120)(run_dir, ROUTE)
        f10 = next(f for f in answer["run"]["frames"] if f["frame"] == 10)
        self.assertIn("error", f10)
        self.assertEqual(answer["images"], 13)
        check, _ = pixel.parse_candidate(DRAWN, pixel.BUNDLED_BINDINGS, [PROBE])
        self.assertEqual(pixel.judge(check, answer["run"])["result"], "needs-review")


# --- end to end: run.generate with the real observer and recorded answers ----------------------------

BUILDS = {"pixel-reference": "clean", "pixel-base": "layering_v1"}


class FrameGame:
    """The simulated game for the trace, then the frames, trace rows and replay record of the recorded run
    for the build (the replay folder's parent is the build: expectrail/jit/run.py)."""

    def __init__(self, builds, body=False):
        self.game, self.builds, self.body = JitGame(), builds, body

    def __call__(self, route_path, run_dir, patches=()):
        self.game(route_path, run_dir, patches=patches)
        route = json.loads(Path(route_path).read_text())
        name = self.builds[Path(run_dir).parent.name]
        make_run(Path(run_dir), route["name"], rows_from(RUNS[name], route["ticks"], body=self.body), keep_trace=True)


def by_build(builds):
    return lambda png_path: builds[Path(png_path).parents[2].name]


def generate_with(case, fix, builds, client=None, observer=None, base=("air-jump",)):
    t = Transport(reply({"candidates": [], "pixelChecks": [DRAWN]}))
    observer = observer or boxed(client or RecordedSamClient(BOX, by_build(builds)))
    game = FrameGame(builds)
    return generate(PROFILE, "The player is drawn behind the scenery.", case.patch(fix),
                    [case.patch(b) for b in base], case.dir / f"out-{fix}", runner=JitGame(),
                    intent=intent_mod.spark_intent(transport=t, offer=offer_mod.PIXEL), variants_fn=case.variants(),
                    observer=observer, frame_runner=game, offer=offer_mod.PIXEL, clock=lambda: 0.0)


class EndToEnd(unittest.TestCase):
    def test_kept_on_the_layering_bug_and_a_wrong_fix_is_caught(self):
        builds = {**BUILDS, "pixel-candidate": "layering_v1"}
        doc = generate_with(Case(), "fix-wrong", builds)
        validate_v1(doc, "jit-run")
        self.assertEqual(doc["status"], "complete", doc["reason"])
        [row] = doc["pixelChecks"]
        self.assertEqual((row["status"], row["outcome"]), ("kept", "catch"), row["reason"])
        self.assertEqual((row["clean"], row["bug"], row["candidate"]), (["pass"] * 3, ["fail"] * 3, ["fail"] * 3))
        self.assertEqual(row["setting"], pixel.setting_of(RECORDING))
        self.assertEqual(from_base_alone(doc)["pixelReproducing"], ["jit-px-player-drawn"])
        # 13 images a run, on 3 runs of each of the clean game, the bug build and the candidate.
        self.assertEqual(doc["spend"]["samImages"], 13 * 9)

    def test_a_good_fix_is_not_caught(self):
        doc = generate_with(Case(), "fix-good", {**BUILDS, "pixel-candidate": "clean"})
        [row] = doc["pixelChecks"]
        self.assertEqual((row["status"], row["outcome"]), ("kept", "no-catch"))

    def test_an_observer_that_stops_part_way_is_charged_what_it_sent(self):
        class Stopping(RecordedSamClient):
            def segment_in(self, png_path, boxes):
                if self.calls == 13 * 3 + 5:   # the sixth image of the first bug-build run
                    self.calls += 1
                    raise SamError("credit gone", kind="credit")
                return super().segment_in(png_path, boxes)

        doc = generate_with(Case(), "fix-wrong", BUILDS, client=Stopping(BOX, by_build(BUILDS)))
        self.assertEqual(doc["status"], "complete", doc["reason"])
        [row] = doc["pixelChecks"]
        self.assertEqual(row["status"], "dropped")
        self.assertIn("SAM stopped", row["reason"])
        self.assertEqual(doc["spend"]["samImages"], 13 * 3 + 6)
