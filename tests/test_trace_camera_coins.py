"""Coins and the camera in the episode, the three signals that read them, and the rule that the
generator is not offered those signals until the reproduction baseline is recorded (issue #285)."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from expectrail.contracts import ContractError, validate_v1
from expectrail.jit import intent
from expectrail.trace import signals
from expectrail.trace.evaluator import evaluate
from expectrail.trace.normalize import EpisodeError, normalize
from tests.jit_fixtures import PROFILE
from tests.test_trace_evaluator import episode, rows, spec

REPO = Path(__file__).resolve().parents[1]
NEW = ("coins_collected", "player_screen_x_range_px", "player_screen_y_range_px")
COINS = [[200.0, 590.0], [300.0, 590.0], [400.0, 590.0]]


def with_fields(n, *, coins=None, view=None, player=lambda t: [100.0, 600.0]):
    """Rows with the recorder's optional fields: ``coins(t)`` (a list; the key is left out when it is
    empty, as the recorder does, or when the function gives None) and ``view(t)``."""
    out = rows(n, player=player)
    for r in out:
        if coins is not None and coins(r["tick"]):
            r["coins"] = coins(r["tick"])
        if view is not None and view(r["tick"]) is not None:
            r["view"] = view(r["tick"])
    return out


def follow(player, lag=1, start=2, stop_at=None):
    """A camera that keeps the player at (400, 300) on screen. A row holds the camera of the frame
    drawn before its tick, so the view on row t is built from the player at t - lag. Before ``start``
    the view is the identity, as on the real engine. From ``stop_at`` the camera stays where it was."""
    def view(t):
        if t < start:
            return [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        at = max(t - lag, 0)
        if stop_at is not None:
            at = min(at, stop_at)
        x, y = player(at)
        return [1.0, 0.0, 0.0, 1.0, 400.0 - x, 300.0 - y]
    return view


def walk(t):
    return [100.0 + 2.0 * t, 600.0]


def hop(t):
    return [100.0, 600.0 - (40.0 if 20 <= t < 40 else 0.0)]


class TheEpisodeKeepsCoinsAndTheCamera(unittest.TestCase):
    def test_a_trace_with_both_gives_an_episode_with_both_and_it_validates(self):
        ep = episode(with_fields(10, coins=lambda t: COINS[: 3 - (t >= 5)], view=follow(walk)))
        validate_v1(ep, "episode")
        self.assertEqual(ep["capabilities"]["coins"], "initial-instances")
        self.assertIs(ep["capabilities"]["view"], True)
        self.assertEqual([len(s["coins"]) for s in ep["samples"]], [3] * 5 + [2] * 5)
        self.assertEqual(ep["samples"][3]["view"], [1.0, 0.0, 0.0, 1.0, 400.0 - 104.0, -300.0])

    def test_a_row_without_coins_has_none_left_once_any_row_had_some(self):
        ep = episode(with_fields(6, coins=lambda t: COINS[:1] if t < 3 else []))
        self.assertEqual([s["coins"] for s in ep["samples"]], [COINS[:1]] * 3 + [[]] * 3)

    def test_a_trace_that_never_names_coins_cannot_say_there_are_none(self):
        ep = episode(with_fields(6))
        validate_v1(ep, "episode")
        self.assertEqual(ep["capabilities"]["coins"], "unknown")
        self.assertIs(ep["capabilities"]["view"], False)
        self.assertTrue(all(s["coins"] is None and s["view"] is None for s in ep["samples"]))

    def test_a_malformed_coin_or_view_is_refused(self):
        for name, bad in (("coins", [[1.0]]), ("coins", [[1.0, "2"]]), ("coins", [[1.0, float("nan")]]),
                          ("coins", [[1.0, 2.0, 3.0]]), ("coins", ["x"]), ("view", [1.0, 0.0, 0.0, 1.0, 0.0]),
                          ("view", [1.0, 0.0, 0.0, 1.0, 0.0, float("inf")]), ("view", "identity"),
                          ("view", [1.0, 0.0, 0.0, 1.0, 0.0, "0"])):
            with self.subTest(name=name, bad=bad):
                data = with_fields(4, coins=lambda t: COINS, view=follow(walk))
                data[2][name] = bad
                with self.assertRaises(EpisodeError):
                    episode(data)

    def test_an_episode_written_before_these_fields_still_validates_and_reads_as_no_reading(self):
        ep = episode(with_fields(6, coins=lambda t: COINS, view=follow(walk)))
        del ep["capabilities"]["coins"], ep["capabilities"]["view"]
        for s in ep["samples"]:
            del s["coins"], s["view"]
        validate_v1(ep, "episode")
        for name in NEW:
            self.assertIsNone(signals.SIGNALS[name](ep), name)

    def test_the_schema_still_refuses_a_field_it_does_not_know_and_a_wrong_shape(self):
        ep = episode(with_fields(4, coins=lambda t: COINS, view=follow(walk)))
        for change in (lambda e: e["samples"][0].update(camera=[0]),
                       lambda e: e["samples"][0].update(view=[1.0, 0.0, 0.0, 1.0, 0.0]),
                       lambda e: e["samples"][0].update(view=[1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]),
                       lambda e: e["samples"][0].update(coins=[[1.0, 2.0, 3.0]]),
                       lambda e: e["capabilities"].update(coins="complete"),
                       lambda e: e["capabilities"].update(view="yes")):
            bad = copy.deepcopy(ep)
            change(bad)
            with self.assertRaises(ContractError):
                validate_v1(bad, "episode")

    def test_the_example_trace_carries_both_into_its_episode(self):
        trace = json.loads((REPO / "contracts" / "examples" / "trace.json").read_text(encoding="utf-8"))
        ep = normalize(trace, {"name": "example", "events": []}, episode_id="example")
        validate_v1(ep, "episode")
        self.assertEqual(ep["capabilities"]["coins"], "initial-instances")
        self.assertEqual(len(ep["samples"][0]["view"]), 6)
        self.assertEqual(ep["samples"][0]["coins"], [[float(x), float(y)] for x, y in trace["rows"][0]["coins"]])


class CoinsCollected(unittest.TestCase):
    def test_it_counts_the_coins_that_went(self):
        self.assertEqual(signals.coins_collected(episode(with_fields(10, coins=lambda t: COINS[: 3 - (t >= 4) - (t >= 7)]))), 2)

    def test_none_collected_is_zero_and_all_collected_is_all(self):
        self.assertEqual(signals.coins_collected(episode(with_fields(10, coins=lambda t: COINS))), 0)
        self.assertEqual(signals.coins_collected(episode(with_fields(10, coins=lambda t: COINS if t < 5 else []))), 3)

    def test_no_reading_when_the_trace_never_names_coins(self):
        self.assertIsNone(signals.coins_collected(episode(with_fields(10))))

    def test_a_relation_on_it_passes_where_coins_go_and_fails_where_they_stay(self):
        op = {"type": "relation", "signal": "coins_collected", "comparator": "gt", "toleranceAbs": 0,
              "left": "stand", "right": "walk"}
        stand = episode(with_fields(10, coins=lambda t: COINS), eid="stand")
        clean = episode(with_fields(10, coins=lambda t: COINS[: 3 - (t >= 4)]), eid="walk")
        stays = episode(with_fields(10, coins=lambda t: COINS), eid="walk")
        self.assertEqual(evaluate(spec(op), stand, clean)["result"], "pass")
        self.assertEqual(evaluate(spec(op), stand, stays)["result"], "fail")
        unknown = episode(with_fields(10), eid="walk")
        self.assertNotIn(evaluate(spec(op), stand, unknown)["result"], ("pass", "fail"))


class PlayerOnScreen(unittest.TestCase):
    def test_a_camera_that_follows_keeps_the_player_in_place(self):
        ep = episode(with_fields(60, view=follow(walk), player=walk))
        self.assertEqual(signals.player_screen_x_range_px(ep), 0.0)
        self.assertEqual(signals.player_screen_y_range_px(ep), 0.0)

    def test_a_camera_that_stops_lets_the_player_walk_across_the_screen(self):
        ep = episode(with_fields(60, view=follow(walk, stop_at=30), player=walk))
        self.assertEqual(signals.player_screen_x_range_px(ep), 2.0 * (58 - 30))   # the last tick has no later row
        self.assertEqual(signals.player_screen_y_range_px(ep), 0.0)

    def test_a_camera_that_does_not_go_up_shows_in_the_vertical_range_only(self):
        ep = episode(with_fields(60, view=follow(hop, stop_at=10), player=hop))
        self.assertEqual(signals.player_screen_x_range_px(ep), 0.0)
        self.assertEqual(signals.player_screen_y_range_px(ep), 40.0)

    def test_the_view_on_the_next_row_is_the_camera_of_this_ticks_frame(self):
        # With the view of the same row instead, a camera one tick behind would read as a 2 px lag.
        ep = episode(with_fields(60, view=follow(walk, lag=0), player=walk))
        # Here each row's view centres that row's own player. Read with the next row's view, the
        # player of tick t sits one step (2 px) left of centre: the pairing is t with t + 1.
        self.assertEqual({sx for _t, sx, _sy in signals.player_on_screen(ep)}, {398.0})
        self.assertEqual({sx for _t, sx, _sy in signals.player_on_screen(
            episode(with_fields(60, view=follow(walk), player=walk)))}, {400.0})

    def test_the_ticks_before_the_camera_is_applied_are_left_out(self):
        ep = episode(with_fields(60, view=follow(walk, start=5), player=walk))
        self.assertEqual(signals.player_on_screen(ep)[0][0], 4)   # the view of row 5 is the first real one
        self.assertEqual(signals.player_screen_x_range_px(ep), 0.0)

    def test_a_trace_whose_view_never_leaves_the_identity_has_no_camera_and_is_all_kept(self):
        ep = episode(with_fields(60, view=lambda t: [1.0, 0.0, 0.0, 1.0, 0.0, 0.0], player=walk))
        self.assertEqual(len(signals.player_on_screen(ep)), 59)
        self.assertEqual(signals.player_screen_x_range_px(ep), 2.0 * 58)

    def test_a_scaled_view_is_measured_in_frame_pixels(self):
        still = lambda t: [2.0, 0.0, 0.0, 2.0, 0.0, 0.0] if t >= 2 else [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]  # noqa: E731
        self.assertEqual(signals.player_screen_x_range_px(episode(with_fields(12, view=still, player=walk))),
                         2 * 2.0 * (10 - 1))

    def test_no_reading_without_a_camera_or_a_player(self):
        self.assertIsNone(signals.player_screen_x_range_px(episode(with_fields(20, player=walk))))
        self.assertIsNone(signals.player_screen_y_range_px(episode(with_fields(20, player=walk))))
        gone = with_fields(20, view=follow(walk), player=walk)
        for r in gone:
            r["player"] = None
        self.assertIsNone(signals.player_screen_x_range_px(episode(gone)))
        one = with_fields(20, player=walk)
        one[7]["view"] = [1.0, 0.0, 0.0, 1.0, 5.0, 5.0]
        self.assertIsNone(signals.player_screen_x_range_px(episode(one)))   # one point is not a range

    def test_a_tick_across_a_gap_is_not_paired_with_a_later_camera(self):
        data = with_fields(40, view=follow(walk), player=walk)
        del data[20:30]
        ep = episode(data)
        self.assertNotIn(19, [t for t, _x, _y in signals.player_on_screen(ep)])
        self.assertEqual(signals.player_screen_x_range_px(ep), 0.0)

    def test_a_relation_on_it_passes_where_the_camera_follows_and_fails_where_it_stops(self):
        op = {"type": "relation", "signal": "player_screen_x_range_px", "comparator": "lte", "toleranceAbs": 5,
              "left": "stand", "right": "walk"}
        stand = episode(with_fields(60, view=follow(lambda t: [100.0, 600.0])), eid="stand")
        follows = episode(with_fields(60, view=follow(walk), player=walk), eid="walk")
        stops = episode(with_fields(60, view=follow(walk, stop_at=30), player=walk), eid="walk")
        self.assertEqual(evaluate(spec(op), stand, follows)["result"], "pass")
        self.assertEqual(evaluate(spec(op), stand, stops)["result"], "fail")


class TheLanguageHasThem(unittest.TestCase):
    def test_every_signal_is_in_the_schema_and_every_schema_signal_is_a_signal(self):
        schema = json.loads((REPO / "contracts" / "trace-spec.v1.schema.json").read_text(encoding="utf-8"))
        relation = next(o for o in schema["properties"]["operation"]["oneOf"]
                        if o["properties"]["type"].get("const") == "relation")
        self.assertEqual(set(relation["properties"]["signal"]["enum"]), set(signals.SIGNALS))
        self.assertLessEqual(set(NEW), set(signals.SIGNALS))

    def test_the_summary_gives_each_of_them(self):
        ep = episode(with_fields(30, coins=lambda t: COINS[: 3 - (t >= 9)], view=follow(walk, stop_at=20), player=walk))
        got = signals.summary(ep)
        self.assertEqual((got["coins_collected"], got["player_screen_x_range_px"], got["player_screen_y_range_px"]),
                         (1, 16.0, 0.0))


class TheGeneratorIsNotOfferedThemBeforeTheBaseline(unittest.TestCase):
    """Issue #285 asks for the baseline rate before anything changes. Until that run is recorded the
    model must be given exactly what it was given before these signals existed."""

    def test_the_held_signals_are_these_three_and_the_rest_are_offered(self):
        self.assertEqual(set(intent.NOT_YET_OFFERED), set(NEW))
        self.assertEqual(set(intent.OFFERED), set(signals.SIGNALS) - set(NEW))
        self.assertEqual(len(intent.OFFERED), 11)

    def test_the_system_prompt_names_every_offered_signal_and_none_of_the_held(self):
        for system in (intent.SYSTEM, intent.SYSTEM + intent.REVISE_SYSTEM):
            for name in intent.OFFERED:
                self.assertIn(f"- {name}: ", system)
            for name in NEW:
                self.assertNotIn(name, system)
            self.assertIn("The SIGNAL names are: " + ", ".join(intent.OFFERED) + ".", system)

    def test_a_measured_value_of_a_held_signal_does_not_reach_the_prompt(self):
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))

        measured = {"clean": {"air_jumps": 1, "coins_collected": 5, "player_screen_x_range_px": 5.0,
                              "player_screen_y_range_px": 0.13},
                    "bugBuild": {"air_jumps": 7, "coins_collected": 0, "player_screen_x_range_px": 191.69,
                                 "player_screen_y_range_px": 0.13}}
        probe = {"id": "hold-right", "description": "Hold right.", "measured": measured}
        dmap = {"files": [], "claims": [], "probeIds": ["hold-right"]}
        text = intent.prompt("report", "patch", dmap, profile, [probe])
        for name in NEW:
            self.assertNotIn(name, text)
        sent = json.loads(text)["probesAvailable"][0]["measured"]
        self.assertEqual(sent, {"clean": {"air_jumps": 1}, "bugBuild": {"air_jumps": 7}})

    def answer(self, *signals_used):
        return json.dumps({"candidates": [
            {"id": f"check-{i}", "statement": "A rule.", "claimId": "player.jump", "class": "player",
             "operation": {"type": "relation", "signal": name, "comparator": "lte", "toleranceAbs": 0,
                           "left": "jump-w0-x2", "right": "jump-w0-x8"}} for i, name in enumerate(signals_used)]})

    def test_a_check_the_model_proposes_on_a_held_signal_is_dropped_and_said(self):
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))

        ids = {"jump-w0-x2", "jump-w0-x8"}
        _probes, entries, notes = intent.parse_answer(self.answer("air_jumps", "coins_collected"), profile, ids)
        self.assertEqual([e["spec"]["operation"]["signal"] for e in entries], ["air_jumps"])
        self.assertTrue(any("coins_collected is not offered yet" in n for n in notes), notes)
        with self.assertRaises(intent.IntentUnavailable):
            intent.parse_answer(self.answer(*NEW), profile, ids)

    def test_a_saved_proposal_with_a_check_on_a_held_signal_is_refused(self):
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))

        ids = {"jump-w0-x2", "jump-w0-x8"}
        _p, entries, _n = intent.parse_answer(self.answer("air_jumps"), profile, ids)
        patch = "--- a/x\n+++ b/x\n"
        for name, refused in (("air_jumps", False), ("player_screen_y_range_px", True)):
            cand = copy.deepcopy(entries[0])
            cand["spec"]["operation"]["signal"] = name
            validate_v1(cand["spec"], "trace-spec")   # the language has it; the generator may not use it yet
            doc = {"format": intent.PROPOSAL_FORMAT, "patchSha256": intent._sha(patch), "model": "m", "error": None,
                   "probes": [], "candidates": [cand], "diagnostics": [], "usage": {}, "promptSha256": None}
            path = Path(tempfile.mkdtemp(prefix="jit-held-")) / intent.PROPOSAL_NAME
            path.write_text(json.dumps(doc), encoding="utf-8")
            propose = intent.from_proposal(path)
            if refused:
                with self.assertRaisesRegex(intent.IntentUnavailable, "not offered yet"):
                    propose("report", patch, {}, profile, [])
            else:
                self.assertEqual(len(propose("report", patch, {}, profile, [])["candidates"]), 1)


if __name__ == "__main__":
    unittest.main()
