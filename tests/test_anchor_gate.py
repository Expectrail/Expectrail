"""The player's place on both sides, in the gate (#327, decision B of November 12, 2026).

Under the rule ``both`` with a base, the gate asks the vision model what is drawn inside the player's
own collision box in sampled frames of the base and the head, and compares each head frame with the
same base frame. A difference keeps the decision from accept (needs-review, with the two frames kept
side by side), and so does a frame with no answer. It never rejects and never makes an accept.

No live Godot and no live model. The replays are stand-ins that log the player's body box as the
harness does (#369) and write real PNG frames; the model is a scripted stand-in answering in SAM
3.1's wire format, as tests/test_two_observers.py does. These are not recordings of the live model:
the recorded live answers are in tests/data/sam-anchor/ and tests/test_anchor_rule.py.
"""
from __future__ import annotations

import base64
import contextlib
import io
import json
import shutil
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from agents.sam_observations import Cache, MetaSamClient
from expectrail.contracts import digest
from expectrail.gate import anchor as ga
from expectrail.gate import record as rec
from expectrail.gate import verify as gv
from expectrail.observers import FramesObserver
from tests.test_ci_gate import BASE, HEAD, make_repo
from tests.test_sam import GROUND_TOP, H, W, box_token, png_bytes
from tests.test_two_observers import FEET, PLAYER_PROMPT

# What a game folder's marker file makes its replay do. Every look keeps the engine's player on the
# ground and draws it where the engine says, so the check passes on both observers; they differ
# only in what is drawn inside the player's box.
#   HALF:  the player is drawn half hidden (half its height, and the model less sure)
#   QUIET: the model gives no answer for the player's box
#   MOVED: the engine has the player 10 px further on, so no frame is in the same place
#   NOBODY: the engine logs no body box (a harness from before #369)
#   LATE:  the engine has the player 10 px further on until frame 80, then in the same place and
#          drawn half hidden: many frames moved before the first difference
LOOKS = ("clean", "HALF", "QUIET", "MOVED", "NOBODY", "LATE")


def x_at(look: str, frame: int) -> int:
    return 80 if look == "MOVED" or (look == "LATE" and frame < 80) else 70
BODY = (-10.0, -20.75, 10.0, 13.25)   # left, top, right, bottom of the body box from the origin


def look_of(game: Path) -> str:
    return next((name for name in LOOKS[1:] if (game / name).exists()), "clean")


class Game:
    def __init__(self):
        self.index: dict[str, tuple[str, int]] = {}
        self.boxes: list[tuple[str, int]] = []   # (look, frame) of every box question

    def replay(self, route: Path, game: Path, out: Path, frames: bool) -> dict:
        look = look_of(game)
        ticks = json.loads(route.read_text(encoding="utf-8"))["ticks"]
        y = GROUND_TOP - FEET
        rows = []
        for t in range(ticks):
            x = float(x_at(look, t // 2))
            row = {"tick": t, "player": [x, y], "onFloor": True, "ground": float(GROUND_TOP),
                   "view": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]}
            if look != "NOBODY":
                row["body"] = [x + BODY[0], y + BODY[1], x + BODY[2], y + BODY[3]]
            rows.append(row)
        out.mkdir(parents=True, exist_ok=True)
        frames_dir = None
        if frames:
            frames_dir = out / "frames"
            frames_dir.mkdir(exist_ok=True)
            for i in range(ticks // 2):
                data = png_bytes(W, H, 5000 + LOOKS.index(look) * 1000 + i)
                (frames_dir / f"f{i:08d}.png").write_bytes(data)
                self.index[base64.b64encode(data).decode()] = (look, i)
        return {"trace": {"physicsTicksPerSecond": 120, "rows": rows, "unknownActions": []},
                "replaySha256": digest({"look": look, "route": route.name}), "framesDir": frames_dir}

    def transport(self, body: dict):
        content = body["input"][0]["content"]
        look, i = self.index[content[1]["image_url"].split(",", 1)[1]]
        text = content[0]["text"]
        x = x_at(look, i)
        if text == PLAYER_PROMPT:
            answer = box_token(0, (x - 10, GROUND_TOP - 20, x + 10, GROUND_TOP), 0.91)
        elif text.startswith("<0f>1<|box;"):
            self.boxes.append((look, i))
            top = int(GROUND_TOP - FEET + BODY[1])
            if look == "QUIET":
                answer = ""
            elif (look == "HALF" and i >= 20) or (look == "LATE" and i >= 80):
                answer = box_token(1, (x - 10, top + 17, x + 10, GROUND_TOP), 0.6)
            else:
                answer = box_token(1, (x - 10, top, x + 10, GROUND_TOP), 0.93)
        else:
            answer = ""
        doc = {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": f"<0f>{answer}" if answer else ""}]}]}
        return json.dumps(doc).encode(), "application/json"

    def observer(self) -> FramesObserver:
        client = MetaSamClient(transport=self.transport, retries=0, sleep=lambda s: None)
        return FramesObserver(client=client, cache=Cache(None), name="sam")


def repo(root: Path, look: str = "clean") -> Path:
    make_repo(root, routes=("smoke",))
    if look != "clean":
        (root / "game" / "platformer" / look).write_text("1", encoding="utf-8")
    return root


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="anchor-gate-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.game = Game()
        self.n = 0

    def gate(self, head_look: str, base_look: str | None = "clean", *, visual="sam", **kw) -> dict:
        self.n += 1
        self.out = self.tmp / f"out{self.n}"
        head = repo(self.tmp / f"head{self.n}", head_look)
        base = repo(self.tmp / f"base{self.n}", base_look) if base_look else None
        if visual == "sam":
            visual = self.game.observer()
        with contextlib.redirect_stdout(io.StringIO()):
            doc = gv.run_gate(repo=head, game="game/platformer", routes=["routes/*.json"], specs="specs",
                              out=self.out, work=self.tmp / f"work{self.n}", base=base,
                              pr={"number": 7, "headSha": HEAD, "baseSha": BASE if base else None},
                              replay=self.game.replay, rule=rec.BOTH, visual=visual, **kw)
        rec.read_record(self.out / "findings.json")   # the reader accepts what the writer wrote
        return doc


class DecisionBTest(Case):
    def test_the_same_game_on_both_sides_is_an_accept_and_the_block_says_they_agree(self):
        doc = self.gate("clean")
        self.assertEqual(doc["decision"], "accept")
        route = doc["anchor"]["routes"][0]
        # Every tenth of the 120 captured frames and the last: 13 frames, asked on each side.
        self.assertEqual((route["result"], route["in"], route["out"]), ("agree", 13, 0))
        self.assertEqual(len(self.game.boxes), 26)
        self.assertEqual((doc["anchor"]["status"], doc["anchor"]["box"]), ("asked", "body"))
        self.assertFalse((self.out / "anchor").exists())

    def test_a_player_drawn_half_hidden_is_needs_review_with_both_frames_kept(self):
        doc = self.gate("HALF")
        # Both observers pass the check itself: the player is where the engine says.
        self.assertEqual(doc["counts"], {"checks": 1, "passed": 1, "failed": 0, "needsReview": 0})
        self.assertEqual(doc["decision"], "needs-review")
        route = doc["anchor"]["routes"][0]
        self.assertEqual((route["result"], route["out"], route["in"]), ("differ", 11, 2))
        self.assertTrue(any("player's place" in r and "side by side" in r for r in doc["reasons"]))
        first = route["kept"][0]
        self.assertEqual(first, 20)
        for side in ("base", "head"):
            self.assertTrue((self.out / "anchor" / "smoke" / f"{side}-{first:06d}.png").is_file())
        self.assertNotEqual((self.out / "anchor" / "smoke" / f"base-{first:06d}.png").read_bytes(),
                            (self.out / "anchor" / "smoke" / f"head-{first:06d}.png").read_bytes())

    def test_many_frames_moved_before_the_first_difference_still_give_a_record_the_reader_accepts(self):
        # Every other frame: 40 moved frames (0 to 78) before the first difference at 80, more than
        # the 32 frames a route may list. The differing frames are listed first.
        doc = self.gate("LATE", anchor_every=2)
        route = doc["anchor"]["routes"][0]
        self.assertEqual((route["result"], route["moved"], route["out"]), ("differ", 40, 21))
        self.assertEqual(doc["decision"], "needs-review")
        self.assertEqual(route["kept"], [80, 82, 84, 86, 88, 90, 92, 94])
        self.assertEqual(len(route["frames"]), ga.MAX_LISTED)
        self.assertTrue(any("frame 80" in r for r in doc["reasons"]), doc["reasons"])
        self.assertTrue((self.out / "anchor" / "smoke" / "head-000080.png").is_file())

    def test_a_difference_never_rejects(self):
        self.assertNotEqual(self.gate("HALF")["decision"], "reject")

    def test_no_answer_for_the_players_box_is_never_an_accept(self):
        doc = self.gate("QUIET")
        self.assertEqual(doc["counts"]["passed"], 1)
        self.assertEqual(doc["decision"], "needs-review")
        self.assertEqual(doc["anchor"]["routes"][0]["result"], "no-answer")

    def test_a_player_the_engine_moved_is_not_compared_and_does_not_stand_in_the_way(self):
        doc = self.gate("MOVED")
        route = doc["anchor"]["routes"][0]
        self.assertEqual((route["result"], route["moved"], route["in"]), ("silent", 13, 0))
        self.assertEqual(doc["decision"], "accept")

    def test_a_harness_without_the_body_box_asks_nothing_and_changes_nothing(self):
        doc = self.gate("NOBODY", "NOBODY")
        route = doc["anchor"]["routes"][0]
        self.assertEqual((route["result"], route["notAsked"]), ("silent", 13))
        self.assertEqual(self.game.boxes, [])
        self.assertEqual(doc["decision"], "accept")

    def test_without_a_base_nothing_is_asked_and_the_record_has_no_block(self):
        doc = self.gate("HALF", None)
        self.assertNotIn("anchor", doc)
        self.assertEqual(self.game.boxes, [])

    def test_a_visual_observer_that_cannot_be_asked_about_a_box_leaves_the_block_not_asked(self):
        class NoBoxes:
            def __init__(self, inner):
                self.inner = inner

            def describe(self):
                return self.inner.describe()

            def look(self, *a, **kw):
                return self.inner.look(*a, **kw)

        doc = self.gate("HALF", visual=NoBoxes(self.game.observer()))
        self.assertEqual(doc["anchor"]["status"], "not-asked")
        self.assertEqual(doc["anchor"]["routes"], [])
        # Not asked says nothing: the decision is the checks' alone, as before this block.
        self.assertEqual(doc["decision"], "accept")

    def test_a_reject_stays_a_reject(self):
        differ = {"status": "asked", "stopped": None, "routes": [
            {"route": "smoke", "result": "differ", "frames": [{"frame": 20, "state": "out", "why": []}]}]}
        held = {"status": "not-used", **gv.HELD_ZERO}
        counts = {"checks": 2, "passed": 1, "failed": 1, "needsReview": 0}
        self.assertEqual(rec.decide(counts, held, anchor=differ)[0], "reject")
        counts = {"checks": 2, "passed": 2, "failed": 0, "needsReview": 0}
        self.assertEqual(rec.decide(counts, held, anchor=differ)[0], "needs-review")


class ReaderTest(Case):
    def written(self, look: str) -> dict:
        self.gate(look)
        return json.loads((self.out / "findings.json").read_text(encoding="utf-8"))

    def refused(self, doc: dict, words: str):
        with self.assertRaises(rec.RecordError) as caught:
            rec.check_record(doc)
        self.assertIn(words, str(caught.exception))

    def test_an_accept_beside_a_route_that_differs_is_refused(self):
        doc = self.written("HALF")
        doc["decision"], doc["reasons"] = "accept", ["all 1 checks pass"]
        self.refused(doc, "the decision should be needs-review")

    def test_a_route_cannot_say_agree_when_its_counts_say_differ(self):
        doc = self.written("HALF")
        doc["anchor"]["routes"][0]["result"] = "agree"
        self.refused(doc, "the result should be differ")

    def test_a_record_cannot_drop_its_differing_frames_and_keep_the_count(self):
        doc = self.written("HALF")
        doc["anchor"]["routes"][0]["frames"] = []
        doc["anchor"]["routes"][0]["kept"] = []
        self.refused(doc, "frames differ and none is listed")

    def test_the_block_is_refused_under_the_engine_only_rule(self):
        doc = self.written("clean")
        doc.pop("observers")
        for row in doc["checks"]:
            row.pop("observed")
        self.refused(doc, "the rule is not both")

    def test_a_record_with_no_block_reads_as_before(self):
        doc = self.written("clean")
        doc.pop("anchor")
        rec.check_record(doc)


class ExampleTest(unittest.TestCase):
    def test_the_contracts_example_is_a_record_the_reader_accepts(self):
        doc = rec.read_record(Path(__file__).resolve().parent.parent / "contracts" / "examples" / "findings-anchor-differs.json")
        self.assertEqual(doc["decision"], "needs-review")
        self.assertEqual(doc["anchor"]["routes"][0]["result"], "differ")


class BlockTest(unittest.TestCase):
    def test_no_client_is_not_asked(self):
        found = ga.block([("smoke", {}, {})], None, None)
        self.assertEqual((found["status"], found["routes"]), ("not-asked", []))
        self.assertIsNone(rec.anchor_effect(found))

    def test_asking_that_stops_is_not_an_accept(self):
        found = {"status": "stopped", "stopped": "the vision model stopped (budget)", "routes": []}
        self.assertIn("before every route", rec.anchor_effect(found))

    def test_an_absent_block_says_nothing(self):
        self.assertIsNone(rec.anchor_effect(None))

    def test_every_cap_the_writer_has_is_one_the_reader_accepts(self):
        # The writer's limits agree with the schema's, so a full block is never refused.
        props = rec.schema()["properties"]["anchor"]["properties"]
        row = props["routes"]["items"]["properties"]
        self.assertEqual(props["routes"]["maxItems"], ga.MAX_ROUTES)
        self.assertEqual(row["frames"]["maxItems"], ga.MAX_LISTED)
        self.assertEqual(row["kept"]["maxItems"], ga.MAX_KEPT)
        self.assertLessEqual(ga.MAX_KEPT, ga.MAX_LISTED)

    def test_more_routes_than_the_record_holds_stop_the_asking_and_are_not_an_accept(self):
        class Never:
            def segment_in(self, *a):
                raise AssertionError("not asked")

        found = ga.block([("r", {}, {})] * 3, Never(), None)   # no frames: each route is silent
        self.assertEqual((found["status"], len(found["routes"])), ("asked", 3))
        with unittest.mock.patch.object(ga, "MAX_ROUTES", 2):
            found = ga.block([("r", {}, {})] * 3, Never(), None)
        self.assertEqual((found["status"], len(found["routes"])), ("stopped", 2))
        self.assertIn("not an accept", rec.anchor_effect(found))

    def test_route_names_that_are_not_plain_file_names_get_no_folder(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        pic = tmp / "f.png"
        pic.write_bytes(png_bytes(4, 4, 1))
        row = {"route": "../escape", "result": "differ", "kept": [3], "_pictures": {3: (pic, pic)}}
        kept = ga.keep_pictures({"status": "asked", "routes": [row]}, tmp / "out")
        self.assertFalse((tmp / "out").exists())
        self.assertNotIn("_pictures", kept["routes"][0])


if __name__ == "__main__":
    unittest.main()
