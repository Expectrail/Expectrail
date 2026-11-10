"""Part 3 of the mutation bench (agents/mutation_fix.py, #156). Muse Code, Godot and SAM are stubbed;
the rehearsal job in mutation-fix.yml runs the same path on real Godot on every pull request that
touches it. Values here are test values, not proposals."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from agents import mutate_game as mg
from agents import mutation_bench as mb
from agents import mutation_fix as mf
from harness.run import REPO

SHA = "ab" * 32
PREREG = {"sha256": SHA, "reportTemplate": "A player says this no longer holds: {sentence}",
          "oracle": {"traceThresholdPx": 1.0, "frameThreshold": 0}}
CLEAN = {"rows": [{"tick": 0, "player": [10.0, 20.0], "facing": 1}]}
MOVED = {"rows": [{"tick": 0, "player": [15.0, 20.0], "facing": 1}]}
FRAMES = ["f0", "f1", "f2"]
REDRAWN = ["f0", "f1-drawn-wrong", "f2"]


def run(trace=CLEAN, frames=FRAMES):
    """One replay as the label code sees it: the engine record and the frame hashes."""
    return {"trace": trace, "frames": list(frames)}


CLEAN_RUN = run()


def caught(i, **fields) -> dict:
    return {"id": f"m{i}", "label": "bad", "outcome": "caught-cheap", "class": "numeric", "kind": "mutant",
            "arms": {"cheap": {"failedChecks": ["gameplay/player-motion-on-smoke"]}}, **fields}


def summary(n=15, **fields) -> dict:
    return {"preregistrationSha256": SHA, "missingCases": [], "awaiting-sam": 0, "rows": [caught(i) for i in range(n)], **fields}


class PickTest(unittest.TestCase):
    def test_ten_cases_seeded_with_reports_made_mechanically(self):
        doc = mf.pick(summary(), 5, PREREG)
        self.assertEqual((doc["sampled"], doc["caught"], doc["seed"]), (10, 15, 5))
        self.assertEqual(doc, mf.pick(summary(), 5, PREREG))
        self.assertNotEqual(doc["cases"], mf.pick(summary(), 6, PREREG)["cases"])
        self.assertEqual(doc["cases"][0]["report"], f"A player says this no longer holds: {mf.GAMEPLAY_SENTENCE}")

    def test_fewer_than_ten_gives_what_there_is(self):
        self.assertEqual(mf.pick(summary(3), 5, PREREG)["sampled"], 3)

    def test_only_bad_caught_mutants_are_drawn(self):
        rows = [caught(1), caught(2, outcome="survived"), caught(3, outcome="undecided"), caught(4, label="good")]
        self.assertEqual([c["id"] for c in mf.pick(summary(rows=rows), 5, PREREG)["cases"]], ["m1"])

    def test_it_reads_the_summary_the_bench_really_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(3):
                d = root / f"c{i}"
                d.mkdir()
                (d / "result.json").write_text(json.dumps({"format": mb.FORMAT, "preregistrationSha256": SHA, **caught(i)}))
            doc = mf.pick(json.loads(json.dumps(mb.summarize(root))), 5, PREREG)
        self.assertEqual(doc["sampled"], 3)

    def test_an_unfinished_part_2_is_refused(self):
        for fields in ({"missingCases": ["x"]}, {"unexpectedCases": ["x"]}, {"error": 1}, {"awaiting-sam": 2},
                       {"preregistrationSha256": "cd" * 32}):
            with self.subTest(fields=fields), self.assertRaises(SystemExit):
                mf.pick(summary(**fields), 5, PREREG)

    def test_a_template_without_its_slot_is_refused(self):
        with self.assertRaises(SystemExit):
            mf.pick(summary(), 5, {**PREREG, "reportTemplate": "A hand-written report."})

    def test_the_cli_needs_a_persons_seed(self):
        with mock.patch.object(mg, "load_preregistration", return_value=PREREG), self.assertRaises(SystemExit):
            mf.main(["--pick"])

    def test_a_committed_sample_is_never_redrawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "cases.json"
            existing.write_text("{}")
            with mock.patch.object(mg, "load_preregistration", return_value=PREREG), \
                    mock.patch.object(mf, "CASES", existing), self.assertRaises(SystemExit) as caught_:
                mf.main(["--pick", "--seed", "1"])
        self.assertIn("never redrawn", str(caught_.exception))


class CheckTest(unittest.TestCase):
    def test_every_check_has_a_sentence(self):
        for check in ("regression/player-stays-above-ground", "regression/player-always-visible",
                      "regression/coins-visible", "gameplay/player-motion-on-smoke", "engine-record/fire-rate"):
            self.assertTrue(mf.sentence_of(check), check)

    def test_the_failing_check_is_chosen_the_same_way_every_time(self):
        row = {"arms": {"cheap": {"failedChecks": ["z/z", "gameplay/a"]}, "sam": {"failedChecks": ["regression/x"]}},
               "engineRecord": {"fire-rate": "fail"}}
        self.assertEqual(mf.failing_check(row), "gameplay/a")
        self.assertEqual(mf.failing_check({"engineRecord": {"fire-rate": "fail"}}), "engine-record/fire-rate")
        self.assertEqual(mf.failing_check({"arms": {"sam": {"failedChecks": ["regression/x"]}}}), "regression/x")
        self.assertIsNone(mf.failing_check({}))

    GROUND = "regression/player-stays-above-ground"

    @staticmethod
    def arm(results, clean="harness"):
        return {"checkResults": results, "cleanSource": clean}

    def test_the_public_check_alone(self):
        arms = {"cheap": self.arm({"gameplay/m": "fail", self.GROUND: "pass"})}
        self.assertEqual(mf.public_result("gameplay/m", {"arms": arms}), "fail")
        self.assertEqual(mf.public_result(self.GROUND, {"arms": arms}), "pass")
        self.assertEqual(mf.public_result("engine-record/fire-rate", {"engineRecord": {"fire-rate": "pass"}}), "pass")

    def test_a_ground_failure_only_sam_saw_is_a_failure(self):
        """The cheap arm's pass must not hide it: that would be a natural catch that never happened."""
        arms = {"cheap": self.arm({self.GROUND: "pass"}), "sam": self.arm({self.GROUND: "fail"})}
        self.assertEqual(mf.public_result(self.GROUND, {"arms": arms}), "fail")

    def test_needs_review_is_no_answer_never_a_pass(self):
        arms = {"cheap": self.arm({self.GROUND: "pass"}), "sam": self.arm({self.GROUND: "needs-review"})}
        self.assertIsNone(mf.public_result(self.GROUND, {"arms": arms}))
        sam_only = {"sam": self.arm({"regression/coins-visible": "needs-review"})}
        self.assertIsNone(mf.public_result("regression/coins-visible", {"arms": sam_only}))
        self.assertIsNone(mf.public_result("engine-record/x", {"engineRecord": {"x": "needs-review"}}))

    def test_a_sam_check_needs_the_sam_arm(self):
        self.assertIsNone(mf.public_result("regression/coins-visible", {"arms": {"cheap": self.arm({})}}))

    def test_a_control_nobody_trusts_is_no_answer(self):
        arms = {"cheap": self.arm({self.GROUND: "fail"}, clean="fixture-fallback")}
        self.assertIsNone(mf.public_result(self.GROUND, {"arms": arms}))

    def test_the_bench_records_every_public_checks_result(self):
        doc = {"suite": {"clean": {"source": "harness"}}, "decision": "accept", "reasons": [],
               "checks": [{"kind": "regression", "spec": "a", "route": "s", "result": "pass"},
                          {"kind": "held-out", "spec": "b", "route": "s", "result": "fail"},
                          {"kind": "clean", "spec": "c", "route": "s", "result": "pass"}]}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(mb, "verify", return_value=doc):
            arm = mb._arm({}, Path("c"), Path(tmp), "sam-off", "trace")
        self.assertEqual(arm["checkResults"], {"regression/a": "pass"})


class CountTest(unittest.TestCase):
    def test_the_three_counts(self):
        muse = {"source": "muse"}
        cases = [({**muse, "decision": "reject", "label": "bad", "publicCheck": "pass"}, (True, False, False)),
                 ({**muse, "decision": "reject", "label": "bad", "publicCheck": "fail", "museScreenshots": "accept"},
                  (True, False, False)),
                 ({**muse, "decision": "reject", "label": "bad", "publicCheck": "fail", "museScreenshots": "reject"},
                  (False, False, False)),
                 ({**muse, "decision": "accept", "label": "bad"}, (False, True, False)),
                 ({**muse, "decision": "reject", "label": "good", "publicCheck": "pass"}, (False, False, True)),
                 ({**muse, "decision": "accept", "label": "good"}, (False, False, False)),
                 ({**muse, "decision": "reject", "label": "unknown", "publicCheck": "pass"}, (False, False, False)),
                 ({**muse, "decision": "needs-review", "label": "bad"}, (False, False, False)),
                 ({"source": "fixture", "decision": "reject", "label": "bad", "publicCheck": "pass"}, (False, False, False))]
        for attempt, want in cases:
            with self.subTest(attempt=attempt):
                c = mf.counts(attempt)
                self.assertEqual((c["naturalCatch"], c["falseAccept"], c["falseReject"]), want)


class LabelTest(unittest.TestCase):
    ROUTES = [Path("a.json"), Path("b.json")]
    ORACLE = {"traceThresholdPx": 1.0, "frameThreshold": 0}

    def label(self, runs, controls=None, thresholds=None):
        controls = controls if controls is not None else {"a": CLEAN_RUN, "b": CLEAN_RUN}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(mf, "_replay_with_frames", side_effect=runs):
            return mf.label_candidate(Path("m"), Path("c"), Path(tmp), thresholds or self.ORACLE, controls,
                                      routes=self.ROUTES)

    def test_good_only_when_every_route_matches(self):
        self.assertEqual(self.label([CLEAN_RUN, CLEAN_RUN])["label"], "good")
        self.assertEqual(self.label([CLEAN_RUN, run(MOVED)])["label"], "bad")

    def test_positions_that_match_with_frames_that_do_not_is_bad(self):
        """The case this oracle is for: the engine record is put back but the game is drawn wrong, as
        when the robot is drawn inside the floor. Vision catches it, so it must not score as a false
        reject."""
        out = self.label([CLEAN_RUN, run(CLEAN, REDRAWN)])
        self.assertEqual(out["label"], "bad")
        self.assertEqual(out["distances"], {"a": 0.0, "b": 0.0})
        self.assertEqual(out["framesDiffering"], {"a": 0, "b": 1})

    def test_a_missing_or_extra_frame_counts_as_differing(self):
        self.assertEqual(self.label([CLEAN_RUN, run(CLEAN, FRAMES[:2])])["label"], "bad")

    def test_both_registered_thresholds_are_used_and_inclusive_of_a_match(self):
        self.assertEqual(self.label([run(MOVED), run(MOVED)], thresholds={"traceThresholdPx": 5.0,
                                                                          "frameThreshold": 0})["label"], "good")
        self.assertEqual(self.label([run(CLEAN, REDRAWN)] * 2, thresholds={"traceThresholdPx": 0,
                                                                           "frameThreshold": 1})["label"], "good")

    def test_a_candidate_that_will_not_run_is_tried_again_then_bad(self):
        out = self.label([None, None, CLEAN_RUN])
        self.assertEqual((out["label"], out["notRun"]), ("bad", ["a"]))
        self.assertEqual(self.label([None, CLEAN_RUN, CLEAN_RUN])["label"], "good")  # a flake, on the second try

    def test_a_route_that_does_not_match_itself_leaves_it_unknown(self):
        self.assertEqual(self.label([CLEAN_RUN], controls={"a": None, "b": CLEAN_RUN})["label"], "unknown")

    def test_but_a_route_that_disagrees_still_decides_it(self):
        self.assertEqual(self.label([run(MOVED)], controls={"a": None, "b": CLEAN_RUN})["label"], "bad")
        self.assertEqual(self.label([run(CLEAN, REDRAWN)], controls={"a": None, "b": CLEAN_RUN})["label"], "bad")

    def test_the_seed_and_the_candidate_are_both_replayed(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(mf, "_replay_with_frames", return_value=CLEAN_RUN) as replay:
            mf.label_candidate(Path("m"), Path("c"), Path(tmp), self.ORACLE, {"a": CLEAN_RUN}, routes=[Path("a.json")])
        self.assertEqual([c.args[2] for c in replay.call_args_list], [[Path("m"), Path("c")]])

    def test_the_label_routes_are_not_only_the_judges(self):
        self.assertIn(mf.SMOKE, mf.LABEL_ROUTES)
        self.assertGreater(len(mf.LABEL_ROUTES), 1)

    def test_a_trace_that_differs_in_kind_stays_json_safe(self):
        out = self.label([CLEAN_RUN, run({"rows": []})])
        self.assertEqual(out["label"], "bad")
        json.dumps(out, allow_nan=False)


class ReplayWithFramesTest(unittest.TestCase):
    def replay(self, replay_json):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "r"

            def fake(route, out_dir, patches):
                out_dir.mkdir(parents=True, exist_ok=True)
                if replay_json is not None:
                    (out_dir / "replay.json").write_text(json.dumps(replay_json), encoding="utf-8")
                return CLEAN

            with mock.patch.object(mf.rt, "_replay", side_effect=fake):
                return mf._replay_with_frames(Path("a.json"), out, [])

    def test_it_reads_the_frame_hashes_the_harness_wrote(self):
        self.assertEqual(self.replay({"frameSha256": FRAMES}), CLEAN_RUN)

    def test_no_frame_hashes_is_no_replay(self):
        for doc in (None, {}, {"frameSha256": "f0"}):
            with self.subTest(doc=doc):
                self.assertIsNone(self.replay(doc))

    def test_a_replay_that_did_not_finish_is_no_replay(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(mf.rt, "_replay", return_value=None):
            self.assertIsNone(mf._replay_with_frames(Path("a.json"), Path(tmp) / "r", []))


class ControlTest(unittest.TestCase):
    def controls(self, runs):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(mf, "_replay_with_frames", side_effect=runs):
            return mf.route_controls(Path(tmp), routes=[Path("a.json")])

    def test_a_route_that_matches_itself_is_usable(self):
        self.assertEqual(self.controls([CLEAN_RUN, CLEAN_RUN]), {"a": CLEAN_RUN})

    def test_jitter_in_positions_or_frames_or_a_failed_replay_makes_a_route_unusable(self):
        for runs in ([CLEAN_RUN, run(MOVED)], [CLEAN_RUN, run(CLEAN, REDRAWN)], [None, CLEAN_RUN], [CLEAN_RUN, None]):
            with self.subTest(runs=runs):
                self.assertEqual(self.controls(runs), {"a": None})

    def test_a_route_that_rendered_no_frames_is_unusable(self):
        self.assertEqual(self.controls([run(CLEAN, []), run(CLEAN, [])]), {"a": None})


class RunCaseTest(unittest.TestCase):
    MUTANT = {"id": "code:enemy/enemy.gd:9:sign.WALK_SPEED", "class": "code", "file": "enemy/enemy.gd", "line": 9,
              "before": "const WALK_SPEED = 22.0", "after": "const WALK_SPEED = -22.0"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        patches = [mock.patch.object(mf.rt, "_replay", return_value=CLEAN),
                   mock.patch.object(mf.rt, "spaced_frames", return_value=[]),
                   mock.patch.object(mf, "route_controls", return_value={"smoke": CLEAN_RUN}),
                   mock.patch.object(mf, "label_candidate", return_value={"label": "bad", "distances": {},
                                                                          "framesDiffering": {}, "notRun": []})]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)

    def run_fixer(self, *patches, seen=None):
        left = list(patches)

        def fake(request, out, **kwargs):
            if seen is not None:
                seen.append((request, kwargs))
            out.mkdir(parents=True, exist_ok=True)
            text = left.pop(0)
            (out / "candidate.patch").write_text(text)
            return {"source": "muse", "empty": not text, "patchSha256": "x"}

        return mock.patch.object(mf, "run_fixer", side_effect=fake)

    def go(self, judged, patches, seen=None, **kwargs):
        with self.run_fixer(*patches, seen=seen), mock.patch.object(mf, "judge_candidate", side_effect=judged):
            return mf.run_case(self.MUTANT, "a report", "gameplay/m", self.out, prereg=PREREG, live=True,
                               judge=lambda *a, **k: {"decision": "reject"}, **kwargs)

    def test_the_loop_stops_at_an_accept_and_counts_every_candidate(self):
        row = self.go([{"outcome": "caught-cheap"}, {"outcome": "survived"}], ["a", "b", "c"])
        self.assertEqual(row["outcome"], "fixed")
        self.assertEqual([a["decision"] for a in row["attempts"]], ["reject", "accept"])
        self.assertTrue(row["attempts"][1]["falseAccept"])

    def test_labels_use_the_whole_registered_oracle(self):
        row = self.go([{"outcome": "caught-cheap"}] * 3, ["a", "b", "c"])
        label = self.mocks[3]
        self.assertEqual(label.call_args.args[3], PREREG["oracle"])
        self.assertLessEqual({"label", "distances", "framesDiffering", "notRun"}, set(row["attempts"][0]))

    def test_three_rejections_is_not_fixed(self):
        row = self.go([{"outcome": "caught-cheap"}] * 3, ["a", "b", "c"])
        self.assertEqual((row["outcome"], len(row["attempts"])), ("not-fixed", 3))

    def test_an_empty_attempt_is_no_candidate_and_the_loop_goes_on(self):
        row = self.go([{"outcome": "survived"}], ["", "b"])
        self.assertEqual([a["decision"] for a in row["attempts"]], ["empty", "accept"])

    def test_a_candidate_that_crashes_the_game_costs_one_attempt_not_the_case(self):
        row = self.go([mb.CaseCrashed("godot failed"), {"outcome": "survived"}], ["a", "b"])
        self.assertEqual([a["decision"] for a in row["attempts"]], ["needs-review", "accept"])
        self.assertEqual(row["outcome"], "fixed")

    def test_the_fixer_gets_the_report_and_no_check_and_the_same_globs_every_time(self):
        seen = []
        self.go([{"outcome": "caught-cheap"}] * 3, ["a", "b", "c"], seen=seen)
        request, kwargs = seen[0]
        self.assertIn("a report", kwargs["briefing"]["prompt"])
        self.assertFalse(kwargs["briefing"]["withRequest"])
        self.assertEqual(request["editable"], mf.EDITABLE)
        self.assertTrue(request["base"]["patch"].endswith("mutant.patch"))
        self.assertIn("gui/**", kwargs["briefing"]["prompt"])
        self.assertEqual(kwargs["prior_reject"], None)
        self.assertEqual(seen[1][1]["prior_reject"], {"attempt": 1, "decision": "reject"})

    def test_the_private_set_is_refused(self):
        with mock.patch.dict("os.environ", {mb.HELDOUT_ENV: "/tmp/x"}), self.assertRaises(SystemExit):
            mf.run_case(self.MUTANT, "r", "gameplay/m", self.out, prereg=PREREG, live=False)

    def test_a_game_that_will_not_replay_is_an_error_not_a_fix(self):
        with mock.patch.object(mf.rt, "_replay", return_value=None):
            row = mf.run_case(self.MUTANT, "r", "gameplay/m", self.out, prereg=PREREG, live=False)
        self.assertEqual(row["outcome"], "error")

    def test_judging_forces_sam_so_the_public_check_has_an_answer(self):
        row_seen = {}

        def tiers(request, candidate, work, row, **kwargs):
            row_seen.update(kwargs)
            row["outcome"] = "caught-cheap"

        with mock.patch.object(mf.mb, "_arm", return_value={"decision": "reject"}), mock.patch.object(mf, "_trace_of", return_value=None), \
                mock.patch.object(mf.mb, "judge_tiers", side_effect=tiers):
            mf.judge_candidate({}, Path("c"), self.out, sam=True)
        self.assertTrue(row_seen["force_sam"])
        self.assertFalse(row_seen["cheap_only"])


class ReplayWrapperTest(unittest.TestCase):
    def test_a_dead_game_is_no_trace_not_the_end_of_the_case(self):
        """SystemExit is how the harness reports a dead game, so the real label path must survive it."""
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(mf.rt, "harness_run", side_effect=SystemExit("godot failed")):
            self.assertIsNone(mf.rt._replay(Path("r.json"), Path(tmp) / "x", []))
            label = mf.label_candidate(Path("m"), Path("c"), Path(tmp), 1.0, {"a": CLEAN}, routes=[Path("a.json")])
        self.assertEqual(label["label"], "bad")


class RehearsalTest(unittest.TestCase):
    def test_it_uses_a_stand_in_and_its_exact_undo(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            seen = {}

            def fake(mutant, report, check, out_, **kwargs):
                seen.update(kwargs, mutant=mutant)
                return {}

            with mock.patch.object(mf, "run_case", side_effect=fake):
                mf.rehearse(out)
            self.assertNotIn(seen["mutant"]["file"], mg.source_files())
            self.assertIs(seen["sam"], False)
            self.assertIs(seen["live"], False)
            self.assertIsNone(seen["prereg"]["sha256"])
            self.assertIsNone(seen.get("routes"))  # every label route, so each one's frames are tried before any spend
            text = seen["fixture"].read_text()
            self.assertIn('+[ext_resource type="Texture2D" uid="uid://8bv0mysvxgle"', text)

    def test_its_undo_restores_the_clean_game(self):
        from harness.run import apply_patches, tree_digest

        mutant = next(m for m in mb.dry_mutants() if "load-failure" in m["id"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "game"
            shutil.copytree(mg.GAME, game, ignore=shutil.ignore_patterns(".godot"))
            seed, undo = root / "seed.patch", root / "undo.patch"
            seed.write_text(mg.patch_text(mutant))
            undo.write_text(mg.patch_text({**mutant, "before": mutant["after"], "after": mutant["before"]},
                                          game=mf._mutated(mutant, root)))
            apply_patches(game, [seed, undo])
            self.assertEqual(tree_digest(game), tree_digest(mg.GAME))

    def test_a_rehearsal_passes_only_on_an_accept_labelled_good(self):
        for attempt, code in (({"decision": "accept", "label": "good"}, 0), ({"decision": "reject", "label": "good"}, 1),
                              ({"decision": "accept", "label": "bad"}, 1)):
            with self.subTest(attempt=attempt), tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(mf, "rehearse", return_value={"outcome": "fixed", "attempts": [attempt]}):
                self.assertEqual(mf.main(["--rehearse", "--out", tmp]), code)


class RecordTest(unittest.TestCase):
    CASES = {"cases": [{"id": "a"}, {"id": "b"}]}

    def row(self, case, **fields):
        return {"format": mf.FORMAT, "case": case, "preregistrationSha256": SHA, "outcome": "fixed", "samImages": 400,
                "attempts": [{"attempt": 1, "source": "muse", "decision": "reject", "label": "bad", "naturalCatch": True}], **fields}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "ai-fixes"

    def record(self, *rows):
        def fetch(run, dest):
            for i, row in enumerate(rows):
                d = dest / f"c{i}"
                d.mkdir(parents=True)
                (d / "result.json").write_text(json.dumps(row))

        return mf.record([7], self.out, prereg=PREREG, fetch=fetch, cases=self.CASES)

    def test_accepted_is_not_called_fixed_and_says_how_many_were_good(self):
        rows = [self.row("a", attempts=[{"attempt": 1, "decision": "accept", "label": "bad"}]),
                self.row("b", attempts=[{"attempt": 1, "decision": "accept", "label": "good"}])]
        doc = self.record(*rows)
        self.assertEqual((doc["fixed"], doc["acceptedAndGood"]), (2, 1))
        text = (self.out / "README.md").read_text()
        self.assertIn("accepted a candidate on 2 of 2 generated bugs, 1 of them labelled good", text)
        self.assertNotIn("Muse Code fixed", text)

    def test_the_warm_job_is_in_the_spend(self):
        def fetch(run, dest):
            d = dest / "c"
            d.mkdir(parents=True)
            (d / "result.json").write_text(json.dumps(self.row("a")))
            (dest / "sam-warm.json").write_text(json.dumps({"samImages": 240}))

        doc = mf.record([7], self.out, prereg=PREREG, fetch=fetch, cases=self.CASES)
        self.assertEqual((doc["samImages"], doc["warmImages"]), (640, 240))

    def test_it_counts_and_reports_what_is_missing(self):
        doc = self.record(self.row("a"))
        self.assertEqual((doc["naturalCatches"], doc["missingCases"], doc["samImages"]), (1, ["b"], 400))
        self.assertIn("| Natural catches | 1 |", (self.out / "README.md").read_text())

    def test_it_refuses_a_rehearsal_another_registration_and_a_repeat(self):
        for rows in ((self.row("a", rehearsal=True),), (self.row("a", preregistrationSha256="cd" * 32),),
                     (self.row("a"), self.row("a")), ()):
            with self.subTest(rows=len(rows)), self.assertRaises(SystemExit):
                self.record(*rows)
        self.assertFalse(self.out.exists())


class EstimateTest(unittest.TestCase):
    def test_the_upper_bound(self):
        self.assertEqual(mf.estimate(10), {"cases": 10, "maxAttempts": 30, "maxSamImages": 14640, "maxSamUsd": 36.6})

    def test_it_works_before_the_case_list_exists(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(mg, "load_preregistration", return_value=PREREG), \
                mock.patch.object(mf, "CASES", Path(tmp) / "gone.json"):
            self.assertEqual(mf.main(["--estimate"]), 0)


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.text = (REPO / ".github" / "workflows" / "mutation-fix.yml").read_text(encoding="utf-8")
        self.doc = yaml.safe_load(self.text)

    def test_the_private_set_is_never_touched(self):
        self.assertNotIn("Expectrail-heldout", self.text)
        self.assertNotIn("HELDOUT_TOKEN", self.text)

    def test_the_rehearsal_job_holds_no_key(self):
        self.assertNotIn("secrets.", str(self.doc["jobs"]["rehearse"]))
        self.assertIn("--rehearse", str(self.doc["jobs"]["rehearse"]["steps"]))

    def test_a_pull_request_rehearses_and_nothing_else_runs_on_one(self):
        self.assertIn("pull_request", self.doc[True])
        self.assertEqual(self.doc["jobs"]["plan"]["if"],
                         "${{ github.event_name == 'workflow_dispatch' && inputs.mode == 'live' }}")
        self.assertIn("needs.plan.result == 'success'", self.doc["jobs"]["run"]["if"])
        self.assertIn("github.event_name == 'workflow_dispatch'", self.doc["jobs"]["run"]["if"])
        for job in ("sam-warm", "run"):
            self.assertEqual(self.doc["jobs"][job].get("environment"), "main-only")

    def test_a_live_run_starts_from_main_on_the_committed_list(self):
        steps = str(self.doc["jobs"]["plan"]["steps"])
        self.assertIn("refs/heads/main", steps)
        self.assertIn("load_cases(load_preregistration())", steps)

    def test_muse_runs_in_the_sandbox_through_the_gateway(self):
        steps = str(self.doc["jobs"]["run"]["steps"])
        self.assertIn("--live --require-sandbox", steps)
        self.assertIn("'EXPECTRAIL_MUSE_GATEWAY': 'on'", steps)

    def test_every_upload_is_scanned_first(self):
        for name, job in self.doc["jobs"].items():
            scanned = False
            for step in job["steps"]:
                scanned = scanned or "agents.export_scan" in str(step.get("run", ""))
                if "upload-artifact" in str(step.get("uses", "")):
                    with self.subTest(job=name):
                        self.assertTrue(scanned)
                        if "always()" in str(step.get("if", "")):
                            self.assertIn("steps.export-scan.outcome == 'success'", step["if"])

    def test_the_lane_is_declared(self):
        self.assertIn(".github/workflows/mutation-fix.yml#run", (REPO / ".github" / "obaaf.yml").read_text())


class NothingPinnedTest(unittest.TestCase):
    def test_part_3_can_change_after_registration(self):
        for rel in ("agents/mutation_fix.py", ".github/workflows/mutation-fix.yml", "agents/reported_trial.py"):
            self.assertNotIn(rel, mg.PINNED)


if __name__ == "__main__":
    unittest.main()
