"""Mutation bench: only a check that ran and failed is a catch. The verifier runs for real here, with
only Godot and the SAM wire stubbed, because a mock of verify is how the old scoring passed its tests
while every SAM-off survivor would have been reported as a vision-only win."""
from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

import agents.mutation_bench as mb
from agents import mutate_game
from agents.judge_bench import cases as judge_cases
from agents.sam_observations import MetaSamClient, SamError
from harness.run import REPO, apply_patches, tree_digest

GOOD_CLEAN = {"clean": {"source": "harness"}}
ROWS = [{"tick": t, "frame": t, "player": [90.0 + 2 * t, 452.0], "onFloor": True, "facing": 1,
         "ground": 465.25, "view": [1, 0, 0, 1, 0, 0]} for t in range(240)]
TRACE = {"format": "expectrail.trace/v0", "physicsTicksPerSecond": 120, "rows": ROWS,
         "levelSurfaces": [[[-4000.0, 465.25], [4000.0, 465.25], [4000.0, 900.0], [-4000.0, 900.0]]]}


STEPS = {"positionStep": 1, "offsetStep": 1, "scaleStep": 1, "zIndexStep": 1, "constantScale": 2, "collisionBits": 1}


def prereg(**wrong_fix) -> dict:
    return {"sha256": "ab" * 32, "wrongFix": {"commentOnlyLabel": "good", **wrong_fix},
            "oracle": {"traceThresholdPx": 1.0, "frameThreshold": 0},
            "agreement": {"seed": 7, "minimum": 2}}


def fake_harness(route, out, patch=None, patches=None, **kwargs):
    """A replay without Godot: one PNG per frame, and the trace the real harness would write."""
    out = Path(out)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    (out / "trace.json").write_text(json.dumps(TRACE))
    (out / "replay.json").write_text(json.dumps({"frameSha256": ["00"] * 120}))
    return {}


def verification(*checks, decision="accept", suite=None) -> dict:
    return {"decision": decision, "reasons": [], "suite": suite if suite is not None else GOOD_CLEAN,
            "checks": [{"kind": k, "spec": s, "route": "smoke", "result": r} for k, s, r in checks]}


CHEAP_PASS = verification(("regression", "ground", "pass"), ("gameplay", "motion", "pass"), ("clean", "ground", "pass"),
                          ("held-out", "ground", "pass"))
SAM_PASS = verification(("regression", "ground", "pass"), ("regression", "player-always-visible", "pass"),
                        ("gameplay", "motion", "pass"), ("clean", "ground", "pass"),
                        ("held-out", "player-always-visible", "needs-review"), decision="needs-review")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        os.environ.pop(mb.HELDOUT_ENV, None)
        patcher = mock.patch("agents.mutation_bench.sam_health.check", return_value=None)
        self.check = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop(mb.HELDOUT_ENV, None)

    def run_pair(self, *answers, operator="hide", case="dev/sinking/v2", force=False):
        left = list(answers)

        def fake_verify(request, candidate, out, **kwargs):
            out.mkdir(parents=True, exist_ok=True)
            answer = left.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            return answer

        with mock.patch.object(mb, "verify", side_effect=fake_verify):
            return mb.run_case(case, operator, self.out, prereg=prereg(), force_sam=force)


EXCLUDED = {"excludedBeforeDraw": {"pairs": [{"case": "dev/physics-fall-through/v1", "operator": "freeze"}]}}


class ExcludedPairTest(Base):
    def test_part_1_is_47_pairs_and_the_rehearsed_one_is_gone(self):
        study = mb.study_pairs(EXCLUDED)
        self.assertEqual(len(study), 47)
        self.assertNotIn(("dev/physics-fall-through/v1", "freeze"), study)

    def test_the_committed_registration_excludes_the_rehearsed_cases(self):
        doc = json.loads(mutate_game.PREREGISTRATION.read_text())
        self.assertEqual(len(mb.study_pairs(doc)), 47)
        self.assertEqual(mutate_game.excluded_mutants(doc), ["code:player/player.gd:7:sign.WALK_SPEED",
                                                             "resource-path:player/player.tscn:3:missing"])

    def test_a_pair_that_does_not_exist_is_refused(self):
        with self.assertRaises(mutate_game.PreregistrationError):
            mb.study_pairs({"excludedBeforeDraw": {"pairs": [{"case": "dev/x/v9", "operator": "freeze"}]}})

    def test_an_excluded_pair_is_refused_even_if_asked_for(self):
        with mock.patch.object(mb, "verify", side_effect=AssertionError("judged an excluded pair")), \
                self.assertRaises(SystemExit) as caught:
            mb.run_case("dev/physics-fall-through/v1", "freeze", self.out, prereg={**prereg(), **EXCLUDED})
        self.assertIn("excluded before registration", str(caught.exception))

    def test_the_workflow_plans_only_the_study(self):
        import yaml

        doc = yaml.safe_load((REPO / ".github" / "workflows" / "mutation-bench.yml").read_text(encoding="utf-8"))
        steps = str(doc["jobs"]["plan"]["steps"])
        self.assertIn("study_pairs(load_preregistration())", steps)
        self.assertIn("for c in cases for o in ops if (c, o) in study]", steps)


class OperatorFixturesTest(unittest.TestCase):
    def test_every_operator_applies_to_the_clean_game(self):
        for name in mb.OPERATORS:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp) / "game"
                shutil.copytree(REPO / "game" / "platformer", work, ignore=shutil.ignore_patterns(".godot"))
                apply_patches(work, [mb.operator_path(name)])

    def test_pairs_cover_eight_cases_times_six_operators(self):
        pairs = mb.pairs()
        self.assertEqual(len(pairs), 8 * 6)
        self.assertEqual(len({c for c, _ in pairs}), 8)


class PublicDecisionTest(unittest.TestCase):
    def test_a_held_out_arm_decides_nothing(self):
        self.assertEqual(mb.public_decision(SAM_PASS), "accept")
        self.assertEqual(mb.public_decision(CHEAP_PASS), "accept")

    def test_only_a_failed_check_is_a_rejection(self):
        self.assertEqual(mb.public_decision(verification(("regression", "a", "fail"), ("gameplay", "b", "needs-review"))),
                         "reject")
        self.assertEqual(mb.public_decision(verification(("regression", "a", "needs-review"), ("gameplay", "b", "pass"))),
                         "needs-review")

    def test_a_held_out_failure_cannot_reject(self):
        self.assertEqual(mb.public_decision(verification(("regression", "a", "pass"), ("held-out", "b", "fail"))), "accept")

    def test_a_clean_check_is_never_named_as_a_catch(self):
        doc = verification(("regression", "a", "fail"), ("clean", "b", "fail"), ("held-out", "c", "fail"))
        self.assertEqual(mb.failed_checks(doc), ["regression/a"])

    def test_the_door_gate_is_not_a_catch(self):
        gate = verification(("regression", "editable-globs", "fail"), decision="reject",
                            suite={"earlyReject": {"gate": "editable-globs"}})
        self.assertEqual(mb.public_decision(gate), "needs-review")

    def test_a_clean_control_from_a_fixture_is_not_to_be_trusted(self):
        fallback = verification(("regression", "a", "fail"), suite={"clean": {"source": "fixture-fallback"}})
        self.assertEqual(mb.public_decision(fallback), "needs-review")

    def test_a_clean_control_that_fails_is_never_a_catch(self):
        """The clean game says nothing about the case: SAM missing a clean frame is not a vision win."""
        for clean in ("fail", "needs-review"):
            with self.subTest(clean=clean):
                self.assertEqual(mb.public_decision(verification(("regression", "a", "pass"), ("clean", "b", clean))),
                                 "needs-review")
                self.assertEqual(mb.public_decision(verification(("regression", "a", "fail"), ("clean", "b", clean))),
                                 "needs-review")

    def test_no_checks_is_never_an_accept(self):
        self.assertEqual(mb.public_decision(verification()), "needs-review")
        self.assertEqual(mb.public_decision(verification(("held-out", "a", "pass"))), "needs-review")


def png(salt: bytes) -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1600, 960, 8, 0, 0, 0, 0))
            + chunk(b"IEND", b"") + salt)


def harness_with_frames(route, out, patch=None, patches=None, **kwargs):
    fake_harness(route, out)
    for i in range(120):
        Path(out, "frames", f"f{i:08d}.png").write_bytes(png(i.to_bytes(4, "big") + (b"c" if patches else b"k")))


class RealVerifierTest(Base):
    """The Block: verify, the SAM adapter, the sampling and the scoring all real. Only Godot and the
    HTTP call are stubbed. SAM on, no private set."""

    def sam(self, *, robot=True, coins=True):
        def http(client, body):
            prompt = body["input"][0]["content"][0]["text"]
            seen = {"blue robot": robot, "gold coin": coins}.get(prompt)
            box = {"blue robot": "x1=80;y1=410;x2=120;y2=470", "gold coin": "x1=300;y1=300;x2=320;y2=320"}.get(prompt)
            text = f"<0f>0<|box;{box};w=1600;h=960;c=0.9|>" if seen else "<0f>"
            return json.dumps({"output_text": text}).encode(), "application/json"

        return http

    def run_real(self, operator="hide", **sam):
        env = {"MODEL_API_KEY": "dummy-sam", "EXPECTRAIL_SAM_CACHE": "off", "META_API_KEY": ""}
        with mock.patch.dict(os.environ, env), mock.patch("agents.verifier.harness_run", harness_with_frames), \
                mock.patch("agents.verifier.reference_surfaces", lambda out: TRACE["levelSurfaces"]), \
                mock.patch.object(MetaSamClient, "_http", self.sam(**sam)):
            return mb.run_case("dev/sinking/v2", operator, self.out, prereg=prereg())

    def test_a_survivor_is_a_finding_with_no_private_set(self):
        row = self.run_real()
        self.assertEqual(row["arms"]["sam"]["verifierDecision"], "needs-review")  # the verifier is unchanged
        self.assertEqual(row["arms"]["sam"]["decision"], "accept")
        self.assertEqual((row["outcome"], row["finding"], row["caught"]), ("survived", True, None))
        self.assertGreater(row["samImages"], 0)

    def test_a_sam_that_cannot_see_the_clean_game_either_decides_nothing(self):
        row = self.run_real(robot=False)
        self.assertEqual(row["arms"]["sam"]["ownResults"]["player-always-visible"], "fail")
        self.assertEqual((row["outcome"], row["caught"]), ("undecided", None))  # the control failed too

    def test_own_results_are_sams_alone(self):
        row = self.run_real(coins=False)
        self.assertEqual(row["arms"]["sam"]["ownResults"]["coins-visible"], "fail")
        self.assertNotIn("player-stays-above-ground", row["arms"]["sam"]["ownResults"])

    def test_a_sam_outage_is_undecided_not_a_win(self):
        def down(client, body):
            raise SamError("sam-3.1 HTTP 503: down", kind="server", status=503)

        env = {"MODEL_API_KEY": "dummy-sam", "EXPECTRAIL_SAM_CACHE": "off", "META_API_KEY": ""}
        with mock.patch.dict(os.environ, env), mock.patch("agents.verifier.harness_run", harness_with_frames), \
                mock.patch("agents.verifier.reference_surfaces", lambda out: TRACE["levelSurfaces"]), \
                mock.patch.object(MetaSamClient, "_http", down):
            row = mb.run_case("dev/sinking/v2", "hide", self.out, prereg=prereg())
        self.assertEqual((row["outcome"], row["caught"], row["finding"]), ("undecided", None, False))


class OutcomeTest(Base):
    def test_cheap_rejection_is_final_and_spends_no_sam(self):
        row = self.run_pair(verification(("gameplay", "motion", "fail"), ("clean", "g", "pass"), decision="reject"))
        self.assertEqual((row["outcome"], row["caught"]), ("caught-cheap", "sam-off"))
        self.assertNotIn("sam", row["arms"])
        self.check.assert_not_called()

    def test_cheap_needs_review_is_never_caught_and_never_reaches_sam(self):
        row = self.run_pair(verification(("regression", "g", "needs-review"), ("clean", "g", "pass"),
                                         decision="needs-review"))
        self.assertEqual((row["outcome"], row["caught"], row["finding"]), ("undecided", None, False))
        self.assertNotIn("sam", row["arms"])

    def test_a_dead_sam_at_the_check_is_undecided_and_spends_nothing(self):
        self.check.return_value = {"kind": "credit", "error": "HTTP 402"}
        row = self.run_pair(CHEAP_PASS)
        self.assertEqual(row["outcome"], "undecided")
        self.assertIn("credit", row["undecidedWhy"])
        self.assertEqual(row["samPreflight"]["kind"], "credit")

    def test_a_crash_twice_is_the_cases_own_and_does_not_fail_the_job(self):
        boom = SystemExit("godot failed (134); see runs/x/sam-off/replay/godot.log")
        row = self.run_pair(boom, boom)
        self.assertEqual((row["outcome"], row["caught"], row["finding"]), ("crash", None, False))

    def test_a_flake_is_retried_and_recorded(self):
        row = self.run_pair(SystemExit("godot failed (134); see runs/x/sam-off/replay/godot.log"),
                            verification(("gameplay", "m", "fail"), ("clean", "g", "pass"), decision="reject"))
        self.assertEqual(row["outcome"], "caught-cheap")
        self.assertTrue(row["arms"]["cheap"]["retried"])

    def test_the_clean_games_crash_is_tooling_not_the_case(self):
        row = self.run_pair(SystemExit("godot failed (134); see runs/x/level-reference/replay/godot.log"),
                            verification(("gameplay", "m", "fail"), ("clean", "g", "pass"), decision="reject"))
        self.assertEqual(row["outcome"], "error")  # not retried: the second answer is never asked for
        self.assertEqual(row["arms"], {})

    def test_a_game_that_will_not_import_is_the_cases_crash(self):
        fail = subprocess.CalledProcessError(1, ["godot", "--headless", "--path", "x/sam-off/replay/work", "--import"])
        self.assertEqual(self.run_pair(fail, fail)["outcome"], "crash")

    def test_the_clean_games_import_failure_is_tooling(self):
        fail = subprocess.CalledProcessError(1, ["godot", "--path", "x/level-reference/replay/work", "--import"])
        self.assertEqual(self.run_pair(fail)["outcome"], "error")

    def test_a_cheap_catch_survives_a_sam_arm_that_dies(self):
        rejected = verification(("gameplay", "m", "fail"), ("clean", "g", "pass"), decision="reject")
        boom = SystemExit("godot failed (134); see runs/x/sam-on/replay/godot.log")
        for answers in ((rejected, boom, boom), (rejected, RuntimeError("tool"))):
            with self.subTest(answers=len(answers)):
                row = self.run_pair(*answers, force=True)
                self.assertEqual((row["outcome"], row["caught"]), ("caught-cheap", "sam-off"))
                self.assertTrue(row["samArmFailed"])

    def test_a_sam_replay_that_dies_after_a_cheap_accept_is_not_the_cases_crash(self):
        boom = SystemExit("godot failed (134); see runs/x/sam-on/replay/godot.log")
        row = self.run_pair(CHEAP_PASS, boom, boom)
        self.assertEqual((row["outcome"], row["finding"]), ("undecided", False))

    def test_a_good_case_that_passes_is_no_finding(self):
        row = self.run_pair(CHEAP_PASS, SAM_PASS, operator="comment-only", case="dev/sinking/v1")
        self.assertEqual((row["outcome"], row["finding"]), ("survived", False))
        self.assertFalse((self.out / "dev_sinking_v1+comment-only" / "finding.json").exists())

    def test_a_patch_that_will_not_apply_is_tooling(self):
        row = self.run_pair(subprocess.CalledProcessError(1, ["patch"]),
                            verification(("gameplay", "m", "fail"), ("clean", "g", "pass"), decision="reject"))
        self.assertEqual((row["outcome"], row["arms"]), ("error", {}))  # not retried as a flake

    def test_a_tool_error_fails_the_job_and_a_crash_does_not(self):
        for outcome, code in (("error", 1), ("crash", 0), ("survived", 0), ("undecided", 0)):
            with self.subTest(outcome=outcome), mock.patch.object(mb, "run_case", return_value={"outcome": outcome}), \
                    mock.patch.object(mb.mutate_game, "load_preregistration", return_value=prereg()):
                self.assertEqual(mb.main(["--case", "dev/sinking/v1", "--operator", "hide", "--out", str(self.out)]), code)

    def test_every_case_ends_in_exactly_one_listed_outcome_and_writes_a_result(self):
        row = self.run_pair(CHEAP_PASS, SAM_PASS)
        self.assertIn(row["outcome"], mb.OUTCOMES)
        self.assertTrue((self.out / "dev_sinking_v2+hide" / "result.json").is_file())

    def test_a_survivor_gets_its_catch_spec(self):
        with mock.patch.object(mb, "verify", side_effect=lambda r, c, out, **k: (out.mkdir(parents=True, exist_ok=True),
                                                                                  CHEAP_PASS)[1]):
            mb.run_case("dev/sinking/v1", "comment-only", self.out, prereg=prereg(commentOnlyLabel="bad"))
        work = self.out / "dev_sinking_v1+comment-only"
        self.assertEqual(json.loads((work / "finding.json").read_text())["catchSpec"]["id"], "comment-only-delta")
        self.assertEqual(json.loads((work / "catch-spec.json").read_text())["id"], "comment-only-delta")

    def test_comment_only_takes_its_label_from_the_pre_registration(self):
        row = self.run_pair(CHEAP_PASS, SAM_PASS, operator="comment-only", case="dev/sinking/v1")
        self.assertEqual(row["label"], "good")
        self.assertEqual(self.run_pair(CHEAP_PASS, SAM_PASS, operator="hide", case="dev/sinking/v1")["label"], "bad")

    def test_refuses_when_heldout_dir_is_set(self):
        os.environ[mb.HELDOUT_ENV] = "/tmp/private"
        with self.assertRaises(SystemExit) as ctx:
            mb.run_case("dev/sinking/v2", "hide", self.out, prereg=prereg())
        self.assertIn("public checks only", str(ctx.exception))

    def test_nothing_is_judged_before_the_pre_registration_is_complete(self):
        draft = self.out / "draft.json"
        draft.write_text(json.dumps({"generator": {"seed": 1}}))
        with mock.patch.object(mutate_game, "PREREGISTRATION", draft), \
                mock.patch.object(mb, "verify", side_effect=AssertionError("judged too early")):
            self.assertEqual(mb.main(["--case", "dev/sinking/v1", "--operator", "hide", "--out", str(self.out)]), 2)

    def verify_says(self, *answers):
        left = list(answers)

        def fake(request, candidate, out, **kwargs):
            out.mkdir(parents=True, exist_ok=True)
            answer = left.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            return answer

        return mock.patch.object(mb, "verify", side_effect=fake)

    REJECTED = verification(("gameplay", "m", "fail"), ("clean", "g", "pass"), decision="reject")
    SAM_ON_REJECTION = verification(("regression", "player-always-visible", "pass"), ("gameplay", "m", "fail"),
                                    ("clean", "g", "pass"), decision="reject")

    def test_the_dry_run_needs_no_pre_registration_and_never_asks_sam(self):
        with self.verify_says(self.REJECTED):
            self.assertEqual(mb.main(["--dry-run", "--out", str(self.out)]), 0)
        self.check.assert_not_called()

    def test_a_dry_run_that_passes_the_cheap_tier_still_never_asks_sam(self):
        with self.verify_says(CHEAP_PASS):
            self.assertEqual(mb.main(["--dry-run", "--out", str(self.out)]), 0)
        self.check.assert_not_called()

    def test_the_sam_rehearsal_forces_sam_on_a_cheap_rejection(self):
        with self.verify_says(self.REJECTED, self.SAM_ON_REJECTION):
            self.assertEqual(mb.main(["--dry-run", "sam", "--out", str(self.out)]), 0)
        self.check.assert_called_once()
        row = json.loads((self.out / "rehearsal-pair" / "result.json").read_text())
        self.assertEqual((row["agreement"], row["preregistrationSha256"], row["rehearsal"]), ("disagree", None, True))

    def test_a_sam_rehearsal_that_never_reached_sam_fails_though_the_pair_was_caught(self):
        """The real path: the pair is a cheap catch, so a dead SAM would otherwise read as a pass."""
        self.check.return_value = {"kind": "credit", "error": "402"}
        with self.verify_says(self.REJECTED):
            self.assertEqual(mb.main(["--dry-run", "sam", "--out", str(self.out)]), 1)

    def test_a_sam_rehearsal_whose_sam_arm_died_fails(self):
        boom = SystemExit("godot failed (134); see runs/x/sam-on/replay/godot.log")
        with self.verify_says(self.REJECTED, boom, boom):
            self.assertEqual(mb.main(["--dry-run", "sam", "--out", str(self.out)]), 1)

    def game_tree(self, *patches):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "game"
            shutil.copytree(mb.GAME, work, ignore=shutil.ignore_patterns(".godot"))
            apply_patches(work, list(patches))
            return tree_digest(work)

    def test_the_rehearsal_pair_is_not_the_same_game_as_any_of_the_48(self):
        """By the game, not by the file: two patches can make one game."""
        case, fixture = mb.DRY_RUN
        rehearsed = self.game_tree(mb.dev_variants()[case], fixture)
        for pair_case, operator in mb.pairs():
            bug = mb.dev_variants()[pair_case]
            candidate = mb.build_candidate(bug, mb.operator_path(operator), self.out / "c.patch")
            with self.subTest(case=pair_case, operator=operator):
                self.assertNotEqual(rehearsed, self.game_tree(bug, candidate))

    def test_the_old_freeze_stand_in_really_was_one_of_the_48(self):
        """Why the check above compares games: this is the mistake it exists to catch."""
        bug = mb.dev_variants()[mb.DRY_RUN[0]]
        candidate = mb.build_candidate(bug, mb.operator_path("freeze"), self.out / "c.patch")
        self.assertEqual(self.game_tree(bug, mb.REPO / "agents" / "fixtures" / "freeze-player.patch"),
                         self.game_tree(bug, candidate))

    def test_the_rehearsal_pair_is_public_in_the_judge_benchmark(self):
        self.assertEqual(judge_cases()["bad/fall-through-comment-only"]["fixture"], mb.DRY_RUN[1].stem)

    def test_the_stand_ins_are_outside_the_population(self):
        """Against the files the generator really reads, so a change to what it reads breaks this."""
        with mock.patch.object(mutate_game, "source_files", wraps=mutate_game.source_files) as read:
            mutate_game.enumerate_mutants(STEPS)
        read.assert_called_once()
        files = set(mutate_game.source_files())
        for m in mb.dry_mutants():
            with self.subTest(id=m["id"]):
                self.assertNotIn(m["file"], files)
                self.assertTrue(mutate_game.patch_text(m))

    def test_the_stand_ins_cover_the_three_ends(self):
        self.assertEqual(sorted(mb.DRY_STAND_INS), ["rehearsal:cannot-start", "rehearsal:plays-differently",
                                                    "rehearsal:runs-with-a-load-failure"])

    def test_the_mutant_rehearsal_runs_every_stand_in_and_marks_them(self):
        def harness(route, out, patch=None, patches=None, **kwargs):
            fake_harness(route, out)
            if patches:
                Path(out, "replay.json").write_text(json.dumps({"frameSha256": ["11"] * 120}))

        with self.verify_says(CHEAP_PASS, CHEAP_PASS, CHEAP_PASS), mock.patch.object(mb, "harness_run", harness):
            rows = mb.rehearse("mutants", self.out)
        self.assertEqual([r["id"] for r in rows], list(mb.DRY_STAND_INS))
        self.assertTrue(all(r["rehearsal"] and r["preregistrationSha256"] is None for r in rows))
        self.assertTrue(all(r["outcome"] == "awaiting-sam" for r in rows))
        self.check.assert_not_called()

    def test_a_rehearsal_refuses_the_private_set(self):
        os.environ[mb.HELDOUT_ENV] = "/tmp/private"
        with self.assertRaises(SystemExit):
            mb.rehearse("pair", self.out)

    def test_a_rehearsal_never_counts_as_a_judged_result(self):
        """Its rows name no registration, so a summary refuses them beside a judged row."""
        for name, sha in (("a", "ab" * 32), ("b", None)):
            d = self.out / name
            d.mkdir()
            (d / "result.json").write_text(json.dumps({"format": mb.FORMAT, "label": "bad", "case": name, "operator": "x",
                                                       "outcome": "survived", "preregistrationSha256": sha}))
        with self.assertRaises(SystemExit):
            mb.summarize(self.out)


class RehearsalPassedTest(unittest.TestCase):
    PLAYS, LOADS, DEAD = list(mb.DRY_STAND_INS)
    GOOD = [{"id": PLAYS, "category": "visible", "outcome": "awaiting-sam"},
            {"id": LOADS, "category": "visible", "outcome": "caught-cheap", "loadFailures": 2},
            {"id": DEAD, "outcome": "crash"}]

    def changed(self, index, **change):
        rows = [dict(r) for r in self.GOOD]
        rows[index].update(change)
        return rows

    def test_mutants_pass_only_when_each_end_did_what_it_is_for(self):
        self.assertTrue(mb.rehearsal_passed("mutants", self.GOOD))
        for rows in (self.changed(0, outcome="crash"), self.changed(0, category="equivalent"),
                     self.changed(1, loadFailures=0), self.changed(1, category="equivalent"),
                     self.changed(2, outcome="caught-cheap"), self.changed(0, outcome="error"),
                     self.changed(2, outcome="error"), self.GOOD[:2]):
            with self.subTest(rows=rows):
                self.assertFalse(mb.rehearsal_passed("mutants", rows))

    def test_the_sam_rehearsal_needs_sam_to_have_answered(self):
        good = {"outcome": "caught-cheap", "arms": {"cheap": {}, "sam": {}}}
        self.assertTrue(mb.rehearsal_passed("sam", [good]))
        for row in ({"outcome": "caught-cheap", "arms": {"cheap": {}}}, {**good, "samPreflight": {"kind": "credit"}},
                    {**good, "samArmFailed": "x"}, {**good, "outcome": "crash"}, {**good, "outcome": "error"}):
            with self.subTest(row=row):
                self.assertFalse(mb.rehearsal_passed("sam", [row]))

    def test_the_pair_needs_a_cheap_answer(self):
        for outcome, passed in (("caught-cheap", True), ("awaiting-sam", True), ("undecided", False), ("crash", False),
                                ("error", False)):
            with self.subTest(outcome=outcome):
                self.assertEqual(mb.rehearsal_passed("pair", [{"outcome": outcome}]), passed)

    def test_a_stand_in_nobody_expects_fails_safely(self):
        self.assertFalse(mb.rehearsal_passed("mutants", [dict(self.GOOD[0], id="other"), *self.GOOD[1:]]))

    def test_a_rehearsal_with_no_rows_or_too_many_fails(self):
        self.assertFalse(mb.rehearsal_passed("pair", []))
        self.assertFalse(mb.rehearsal_passed("sam", [{"outcome": "caught-cheap"}] * 2))


class LoadFailureTest(Base):
    def log(self, name, *lines):
        path = self.out / name
        path.write_text("\n".join(lines))
        return path

    def test_only_lines_the_clean_game_does_not_have_count(self):
        clean = self.log("clean.log", "ERROR: Failed to load script x", "fine")
        log = self.log("m.log", "ERROR: Failed to load script x", "ERROR: Cannot open file 'res://a.missing'.",
                       "ERROR: Failed loading resource: res://a.missing.", "fine")
        self.assertEqual(mb.load_failures(clean, log), 2)

    def test_a_missing_log_is_unknown_not_zero(self):
        log = self.log("m.log", "ERROR: Failed to load script x")
        self.assertIsNone(mb.load_failures(self.out / "gone", log))
        self.assertIsNone(mb.load_failures(log, self.out / "gone"))

    def test_bytes_that_are_not_text_do_not_stop_it(self):
        clean = self.log("clean.log", "fine")
        log = self.out / "m.log"
        log.write_bytes(b"\xff\xfe ERROR: Failed to load script x\n")
        self.assertEqual(mb.load_failures(clean, log), 1)

    def test_a_game_that_runs_with_a_load_failure_is_judged_and_never_a_crash(self):
        """A missing texture is the bug a resource-path mutant makes: it must reach the checks."""
        manifest = {"mutants": [m for m in mb.dry_mutants() if "load-failure" in m["id"]]}

        def harness(route, out, patch=None, patches=None, **kwargs):
            fake_harness(route, out)
            Path(out, "godot.log").write_text("ERROR: Failed loading resource: x\n" if patches else "")
            if patches:
                Path(out, "replay.json").write_text(json.dumps({"frameSha256": ["11"] * 120}))

        rejected = verification(("regression", "g", "fail"), ("clean", "g", "pass"), decision="reject")
        with mock.patch.object(mb, "verify", side_effect=lambda r, c, out, **k: (out.mkdir(parents=True, exist_ok=True),
                                                                                  rejected)[1]), \
                mock.patch.object(mb, "harness_run", harness):
            row = mb.run_mutant(manifest["mutants"][0]["id"], "cheap", self.out, prereg=prereg(), manifest=manifest)
        self.assertEqual((row["outcome"], row["loadFailures"]), ("caught-cheap", 1))


class NoopTest(Base):
    def test_exactly_the_two_known_candidates_are_empty_and_every_pair_builds(self):
        empty = []
        for case, op in mb.pairs():
            cand = mb.build_candidate(mb.dev_variants()[case], mb.operator_path(op), self.out / "c.patch")
            if not cand.read_text().strip():
                empty.append((case, op))
        self.assertEqual(sorted(empty), [("dev/layering/v2", "behind-scenery"), ("dev/sinking/v2", "sink")])

    def test_an_empty_candidate_is_labelled(self):
        row = self.run_pair(verification(("regression", "g", "fail"), ("clean", "g", "pass"), decision="reject"),
                            operator="sink", case="dev/sinking/v2")
        self.assertTrue(row["noop"])

    def test_build_candidate_stacks_operator_on_undo(self):
        bug = mb.dev_variants()["dev/physics-fall-through/v1"]
        text = mb.build_candidate(bug, mb.operator_path("hide"), self.out / "c.patch").read_text()
        self.assertIn("player/", text)
        self.assertIn("visible = false", text)


class AgreementTest(Base):
    def rejected(self):
        return verification(("gameplay", "motion", "fail"), ("clean", "g", "pass"), decision="reject")

    def test_force_sam_asks_about_a_rejection_and_it_stays_a_cheap_catch(self):
        sam = verification(("regression", "player-always-visible", "fail"), ("gameplay", "motion", "fail"),
                           ("clean", "g", "pass"), decision="reject")
        row = self.run_pair(self.rejected(), sam, force=True)
        self.assertEqual((row["outcome"], row["agreement"]), ("caught-cheap", "agree"))

    def test_gameplay_alone_is_not_agreement(self):
        """Both arms share the gameplay check, so counting it would make every row agree."""
        self.assertEqual(mb.own_results(verification(("regression", "player-stays-above-ground", "fail"),
                                                     ("regression", "coins-visible", "pass"), ("gameplay", "m", "fail"),
                                                     ("clean", "g", "fail"))), {"coins-visible": "pass"})
        sam = verification(("regression", "player-always-visible", "pass"), ("gameplay", "motion", "fail"),
                           ("clean", "g", "pass"), decision="reject")
        self.assertEqual(self.run_pair(self.rejected(), sam, force=True)["agreement"], "disagree")

    def test_undecided_vision_is_not_a_disagreement(self):
        sam = verification(("regression", "player-always-visible", "needs-review"), ("gameplay", "m", "fail"),
                           ("clean", "g", "pass"), decision="reject")
        self.assertEqual(self.run_pair(self.rejected(), sam, force=True)["agreement"], "undecided")

    def test_without_force_there_is_no_agreement_row(self):
        self.assertIsNone(self.run_pair(self.rejected()).get("agreement"))

    def test_a_dead_sam_keeps_the_cheap_catch_and_records_why(self):
        self.check.return_value = {"kind": "server", "error": "503"}
        row = self.run_pair(self.rejected(), force=True)
        self.assertEqual(row["outcome"], "caught-cheap")
        self.assertEqual(row["samPreflight"]["kind"], "server")
        self.assertIsNone(row.get("agreement"))


class MutantTest(Base):
    MANIFEST = {"mutants": [{"id": "code:enemy/enemy.gd:9:sign.WALK_SPEED", "class": "code", "file": "enemy/enemy.gd",
                             "line": 9, "before": "const WALK_SPEED = 22.0", "after": "const WALK_SPEED = -22.0"}]}
    ID = MANIFEST["mutants"][0]["id"]

    def run_mutant(self, frames=None, tier="cheap", answers=(), force=False, trace_extra=None):
        calls = []
        left = list(answers) or [CHEAP_PASS]

        def fake_verify(request, candidate, out, **kwargs):
            calls.append((request, candidate))
            out.mkdir(parents=True, exist_ok=True)
            return left.pop(0)

        def harness(route, out, patch=None, patches=None, **kwargs):
            fake_harness(route, out)
            if patches:
                Path(out, "replay.json").write_text(json.dumps({"frameSha256": frames or ["00"] * 120}))
                if trace_extra:
                    Path(out, "trace.json").write_text(json.dumps(trace_extra))

        with mock.patch.object(mb, "verify", side_effect=fake_verify), mock.patch.object(mb, "harness_run", harness):
            row = mb.run_mutant(self.ID, tier, self.out, prereg=prereg(), manifest=self.MANIFEST, force_sam=force)
        return row, calls

    def test_a_mutant_outside_the_editable_files_is_the_seed_never_the_candidate(self):
        row, calls = self.run_mutant(frames=["11"] * 120)
        request, candidate = calls[0]
        self.assertTrue(request["base"]["patch"].endswith("mutant.patch"))
        self.assertEqual(candidate.name, "empty.patch")  # the verifier's editable gate cannot judge it
        self.assertEqual(candidate.read_text(), "")
        self.assertEqual(row["outcome"], "awaiting-sam")

    def test_no_visible_difference_is_dropped_with_its_reason_and_never_judged(self):
        row, calls = self.run_mutant()
        self.assertEqual(calls, [])
        self.assertEqual(row["outcome"], "equivalent")
        self.assertIn("smoke route", row["dropReason"])

    def test_the_cheap_phase_never_spends_sam(self):
        self.run_mutant(frames=["11"] * 120)
        self.check.assert_not_called()

    def test_the_sam_phase_stands_alone_in_a_new_job(self):
        row, _ = self.run_mutant(frames=["11"] * 120, tier="sam", answers=[CHEAP_PASS, SAM_PASS])
        self.assertEqual(row["outcome"], "survived")

    def test_an_engine_record_failure_is_a_cheap_catch(self):
        bad = dict(TRACE, rows=[dict(r, enemies=[[1, 10.0, 100.0 + r["tick"]]]) for r in ROWS])
        row, _ = self.run_mutant(frames=["11"] * 120, trace_extra=bad)
        self.assertEqual(row["engineRecord"]["enemies-stay-up"], "fail")
        self.assertEqual(row["outcome"], "caught-cheap")

    def test_a_game_that_runs_but_never_loads_a_player_is_a_crash_not_a_catch(self):
        row, calls = self.run_mutant(frames=["11"] * 120, trace_extra=dict(TRACE, rows=[{"tick": 0}]))
        self.assertEqual(row["outcome"], "crash")
        self.assertEqual(calls, [])

    def test_a_mutant_that_will_not_import_twice_is_a_crash(self):
        def harness(route, out, patch=None, patches=None, **kwargs):
            if patches:
                raise subprocess.CalledProcessError(1, ["godot", "--headless", "--path", "x/mutant/work", "--import"])
            fake_harness(route, out)

        with mock.patch.object(mb, "harness_run", harness):
            row = mb.run_mutant(self.ID, "cheap", self.out, prereg=prereg(), manifest=self.MANIFEST)
        self.assertEqual(row["outcome"], "crash")

    def test_an_engine_record_catch_stands_in_the_sam_phase(self):
        bad = dict(TRACE, rows=[dict(r, enemies=[[1, 10.0, 100.0 + r["tick"]]]) for r in ROWS])
        row, _ = self.run_mutant(frames=["11"] * 120, tier="sam", answers=[CHEAP_PASS, SAM_PASS], trace_extra=bad)
        self.assertEqual(row["outcome"], "caught-cheap")

    def test_an_edited_manifest_is_refused(self):
        with mock.patch.object(mb.mutate_game, "load_manifest", side_effect=mutate_game.PreregistrationError("edited")), \
                self.assertRaises(mutate_game.PreregistrationError):
            mb.run_mutant(self.ID, "cheap", self.out, prereg=prereg())

    def test_a_mutant_that_crashes_twice_is_its_own_category(self):
        def harness(route, out, patch=None, patches=None, **kwargs):
            if patches:
                raise SystemExit("godot failed (134); see x/mutant/godot.log")
            fake_harness(route, out)

        with mock.patch.object(mb, "harness_run", harness):
            row = mb.run_mutant(self.ID, "cheap", self.out, prereg=prereg(), manifest=self.MANIFEST)
        self.assertEqual(row["outcome"], "crash")


class SummaryTest(Base):
    def write(self, name, **row):
        d = self.out / name
        d.mkdir()
        (d / "result.json").write_text(json.dumps({"format": mb.FORMAT, "label": "bad",
                                                   "preregistrationSha256": "ab", **row}))

    def test_denominators_reconcile_and_undecided_is_outside_the_score(self):
        for i, outcome in enumerate(("caught-cheap", "caught-sam", "survived", "undecided", "crash", "error")):
            self.write(f"r{i}", case=f"c{i}", operator="hide", outcome=outcome)
        doc = mb.summarize(self.out)
        self.assertEqual(sum(doc[o] for o in mb.OUTCOMES), doc["cases"])
        self.assertEqual((doc["badCaught"], doc["badSurvived"], doc["score"]), (2, 1, round(2 / 3, 4)))
        self.assertEqual(doc["byOperator"]["hide"]["cases"], 6)

    def test_a_good_fix_is_outside_the_score_and_a_rejection_of_it_is_a_false_reject(self):
        self.write("a", case="c", operator="comment-only", outcome="caught-cheap", label="good")
        doc = mb.summarize(self.out)
        self.assertIsNone(doc["score"])
        self.assertEqual(doc["falseRejects"], ["c comment-only"])

    def test_the_agreement_table_lists_every_disagreement(self):
        self.write("a", id="m1", outcome="caught-cheap", agreement="agree")
        self.write("b", id="m2", outcome="caught-cheap", agreement="disagree")
        self.write("c", id="m3", outcome="caught-cheap", agreement="undecided")
        a = mb.summarize(self.out)["agreement"]
        self.assertEqual((a["checked"], a["agree"], a["disagree"], a["undecided"]), (3, 1, 1, 1))
        self.assertEqual(a["disagreements"], ["m2"])

    def test_a_mutant_judged_in_both_phases_counts_once(self):
        self.write("a", kind="mutant", id="m", tier="cheap", outcome="awaiting-sam")
        self.write("b", kind="mutant", id="m", tier="sam", outcome="caught-sam")
        doc = mb.summarize(self.out)
        self.assertEqual((doc["cases"], doc["caught-sam"], doc["awaiting-sam"]), (1, 1, 0))

    def test_equivalents_are_listed_with_reasons_and_outside_the_cases(self):
        self.write("a", kind="mutant", id="m", outcome="equivalent", dropReason="no difference")
        doc = mb.summarize(self.out)
        self.assertEqual(doc["cases"], 0)
        self.assertEqual(doc["equivalentDropped"], [{"id": "m", "reason": "no difference"}])

    def test_sam_images_are_split_by_why_they_were_spent(self):
        self.write("a", id="m1", outcome="caught-sam", samImages=100, arms={"sam": {"samImages": 100}})
        self.write("b", id="m2", outcome="caught-cheap", agreement="agree", samImages=40, arms={"sam": {"samImages": 40}})
        (self.out / "sam-warm.json").write_text(json.dumps({"samImages": 233}))
        s = mb.summarize(self.out)["samImages"]
        self.assertEqual((s["spent"], s["tiered"], s["agreementOnly"], s["warm"]), (140, 100, 40, 233))
        self.assertEqual((s["fullRun"], s["fullRunCases"], s["ofCases"], s["probes"]), (140, 2, 2, 0))

    def test_results_from_two_registrations_are_refused(self):
        self.write("a", case="c", operator="hide", outcome="survived")
        self.write("b", case="d", operator="hide", outcome="survived", preregistrationSha256="cd")
        with self.assertRaises(SystemExit) as caught:
            mb.summarize(self.out)
        self.assertIn("2 different registrations", str(caught.exception))

    def test_a_dry_run_row_cannot_mix_in(self):
        self.write("a", case="c", operator="hide", outcome="survived")
        self.write("b", case="d", operator="hide", outcome="survived", preregistrationSha256=None)
        with self.assertRaises(SystemExit):
            mb.summarize(self.out)

    def test_the_summary_names_its_registration(self):
        self.write("a", case="c", operator="hide", outcome="survived")
        doc = mb.summarize(self.out)
        self.assertEqual(doc["preregistrationSha256"], "ab")
        self.assertIn("Registration `ab`", mb.markdown(doc))

    def test_the_cheap_tier_score_counts_only_cheap_catches(self):
        self.write("a", case="c", operator="hide", outcome="caught-cheap")
        self.write("b", case="d", operator="hide", outcome="caught-sam")
        doc = mb.summarize(self.out)
        self.assertEqual((doc["score"], doc["cheapTierScore"]), (1.0, 0.5))

    def test_each_operator_shows_tiered_and_full_run_images(self):
        self.write("a", case="c", operator="hide", outcome="caught-sam", arms={"sam": {"samImages": 100}})
        self.write("b", case="d", operator="hide", outcome="caught-cheap", agreement="agree",
                   arms={"sam": {"samImages": 40}})
        hide = mb.summarize(self.out)["byOperator"]["hide"]
        self.assertEqual((hide["samImagesTiered"], hide["samImagesFullRun"]), (100, 140))

    def test_a_probe_image_is_accounted_for(self):
        self.write("a", id="m1", outcome="caught-cheap", samImages=1)
        self.assertEqual(mb.summarize(self.out)["samImages"]["probes"], 1)

    def test_a_good_label_is_never_a_blind_spot_or_a_win(self):
        self.write("a", case="c", operator="comment-only", outcome="survived", label="good")
        self.write("b", case="d", operator="comment-only", outcome="caught-sam", label="good")
        doc = mb.summarize(self.out)
        self.assertEqual((doc["blindSpots"], doc["visionOnlyWins"], doc["goodAccepted"]), ([], [], 1))

    def test_each_operator_reports_its_images_and_each_check_its_catches(self):
        arms = {"cheap": {"failedChecks": ["gameplay/motion"]}, "sam": {"failedChecks": ["regression/coins-visible"]}}
        self.write("a", case="c", operator="hide", outcome="caught-cheap", samImages=9, arms=arms,
                   engineRecord={"fire-rate": "fail", "jump-height": "pass"})
        doc = mb.summarize(self.out)
        self.assertEqual(doc["byOperator"]["hide"]["samImages"], 9)
        self.assertEqual(doc["byCheck"], {"cheap gameplay/motion": 1, "engine-record fire-rate": 1,
                                          "sam regression/coins-visible": 1})
        self.assertEqual(doc["cheapTierScore"], 1.0)
        self.assertIn("## Which checks catch what", mb.markdown(doc))

    def test_outcomes_reconcile_in_a_partial_run(self):
        self.write("a", kind="mutant", id="m1", outcome="awaiting-sam")
        self.write("b", kind="mutant", id="m2", outcome="caught-cheap")
        doc = mb.summarize(self.out)
        self.assertEqual(sum(doc[o] for o in mb.OUTCOMES), doc["cases"])

    def test_the_sample_reconciles_against_the_manifest(self):
        manifest = self.out / "manifest.json"
        manifest.write_text(json.dumps({"mutants": [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]}))
        self.write("a", kind="mutant", id="m1", outcome="caught-cheap")
        self.write("b", kind="mutant", id="m2", outcome="equivalent", dropReason="x")
        with mock.patch.object(mb, "MANIFEST", manifest):
            r = mb.summarize(self.out)["reconciliation"]
        self.assertEqual(r, {"sampled": 3, "judged": 1, "equivalent": 1, "missing": ["m3"], "notInManifest": []})

    def test_an_empty_folder_has_nothing_to_summarize(self):
        with self.assertRaises(SystemExit) as caught:
            mb.summarize(self.out)
        self.assertIn("nothing to summarize", str(caught.exception))
        self.assertFalse((self.out / "mutation-summary.json").exists())

    def test_the_cli_exits_non_zero_on_an_empty_folder(self):
        result = subprocess.run([sys.executable, "-m", "agents.mutation_bench", "--summarize", str(self.out)],
                                capture_output=True, text=True, cwd=REPO)
        self.assertEqual(result.returncode, 1)
        self.assertIn("nothing to summarize", result.stderr)

    def test_a_folder_of_other_files_has_nothing_to_summarize(self):
        (self.out / "sam-warm.json").write_text(json.dumps({"samImages": 233}))
        (self.out / "result.json").write_text(json.dumps({"format": "something-else"}))
        with self.assertRaises(SystemExit):
            mb.summarize(self.out)

    def test_the_report_renders(self):
        self.write("a", case="c", operator="hide", outcome="survived")
        text = mb.markdown(mb.summarize(self.out))
        self.assertIn("Mutation score", text)
        self.assertIn("## Blind spots", text)

    def test_plan_sam_takes_every_survivor_and_a_seeded_sample_of_rejections(self):
        reg = dict(prereg(), sha256="ab")
        for i in range(5):
            self.write(f"c{i}", kind="mutant", id=f"caught{i}", outcome="caught-cheap")
        self.write("s", kind="mutant", id="left", outcome="awaiting-sam")
        first = mb.plan_sam(self.out, reg)
        self.assertEqual(first["survivors"], ["left"])
        self.assertEqual(len(first["agreement"]), 2)
        self.assertEqual(first, mb.plan_sam(self.out, reg))

    def test_plan_sam_refuses_results_from_elsewhere(self):
        self.write("a", kind="mutant", id="m", outcome="awaiting-sam", preregistrationSha256=None)
        with self.assertRaises(SystemExit) as caught:
            mb.plan_sam(self.out, dict(prereg(), sha256="ab"))
        self.assertIn("not from this registration", str(caught.exception))

    def test_a_rehearsal_summary_says_so_and_has_no_score(self):
        self.write("a", case="c", operator="rehearsal", outcome="caught-cheap", rehearsal=True,
                   preregistrationSha256=None)
        doc = mb.summarize(self.out)
        text = mb.markdown(doc)
        self.assertIn("never a result", text)
        self.assertNotIn("Mutation score", text)
        self.assertIsNone(doc["score"])
        self.assertIsNone(doc["byOperator"]["rehearsal"]["score"])
        self.assertIn("| rehearsal | - |", text)

    def stratified(self):
        """Numeric, the biggest class by far, all survive; every small class is caught."""
        for i in range(10):
            self.write(f"n{i}", kind="mutant", id=f"n{i}", outcome="survived", **{"class": "numeric"})
        for cls, n in (("collision-bit", 5), ("code", 8), ("resource-path", 6)):
            for i in range(n):
                self.write(f"{cls}{i}", kind="mutant", id=f"{cls}{i}", outcome="caught-cheap", **{"class": cls})
        manifest = self.out / "manifest.json"
        manifest.write_text(json.dumps({
            "sampling": {"method": "stratified"}, "shortByClass": {"boolean": 2}, "shortOfSample": 2,
            "enumeratedByClass": {"numeric": 2642, "boolean": 1, "collision-bit": 39, "code": 20, "resource-path": 66},
            "sampledByClass": {"numeric": 10, "boolean": 1, "collision-bit": 5, "code": 8, "resource-path": 6},
            "mutants": [{"id": f"n{i}"} for i in range(10)]}))
        with mock.patch.object(mb, "MANIFEST", manifest):
            return mb.summarize(self.out)

    def test_a_stratified_score_is_weighted_by_each_classs_real_size(self):
        doc = self.stratified()
        self.assertAlmostEqual(doc["score"], 19 / 29, places=3)  # what the allocation happens to give
        view = doc["sampling"]
        self.assertEqual(view["weightedScore"], round(125 / 2767, 4))
        self.assertEqual(view["classes"]["numeric"], {"enumerated": 2642, "sampled": 10, "equivalent": 0, "decided": 10,
                                                      "score": 0.0, "estimatedVisible": 2642.0,
                                                      "estimatedDecided": 2642.0})
        self.assertEqual(view["weightedCovers"], round(2767 / 2768, 4))
        self.assertEqual(view["classesWithNoScore"], ["boolean"])
        self.assertEqual(view["shortByClass"], {"boolean": 2})

    def test_the_report_leads_with_the_weighted_score_and_says_why(self):
        text = mb.markdown(self.stratified())
        self.assertIn("estimated decided mutants: **4.5%**", text)
        self.assertIn("not a score for the whole game", text)
        self.assertIn("| numeric | 2642 | 10 | 0 | 10 | 2642.0 | 0.0% |", text)
        self.assertIn("classes with no score: boolean", text)
        self.assertIn("Short of the plan by 2", text)
        self.assertNotIn("Mutation score: **", text)

    def view_of(self, enumerated, sampled, method="stratified"):
        manifest = self.out / "manifest.json"
        manifest.write_text(json.dumps({"sampling": {"method": method}, "enumeratedByClass": enumerated,
                                        "sampledByClass": sampled, "mutants": []}))
        with mock.patch.object(mb, "MANIFEST", manifest):
            return mb.summarize(self.out)

    def test_a_class_mostly_equivalent_weighs_what_it_can_show_not_its_size(self):
        """1,000 numeric, 90% equivalent, the rest caught; 100 code, all survive. The estimate is 50%."""
        for i in range(9):
            self.write(f"e{i}", kind="mutant", id=f"e{i}", outcome="equivalent", dropReason="x", **{"class": "numeric"})
        self.write("n", kind="mutant", id="n", outcome="caught-cheap", **{"class": "numeric"})
        for i in range(10):
            self.write(f"c{i}", kind="mutant", id=f"c{i}", outcome="survived", **{"class": "code"})
        view = self.view_of({"numeric": 1000, "code": 100}, {"numeric": 10, "code": 10})["sampling"]
        self.assertEqual(view["weightedScore"], 0.5)
        self.assertEqual(view["classes"]["numeric"]["estimatedVisible"], 100.0)
        self.assertEqual(view["classes"]["numeric"]["estimatedDecided"], 100.0)

    def test_a_class_weighs_its_decided_cases_not_only_its_visible_ones(self):
        """Half of numeric's visible cases are undecided, so it weighs half. Its score covers only the rest."""
        self.write("a", kind="mutant", id="a", outcome="caught-cheap", **{"class": "numeric"})
        self.write("b", kind="mutant", id="b", outcome="undecided", **{"class": "numeric"})
        self.write("c", kind="mutant", id="c", outcome="survived", **{"class": "code"})
        self.write("d", kind="mutant", id="d", outcome="survived", **{"class": "code"})
        view = self.view_of({"numeric": 100, "code": 50}, {"numeric": 2, "code": 2})["sampling"]
        self.assertEqual(view["classes"]["numeric"]["estimatedVisible"], 100.0)
        self.assertEqual(view["classes"]["numeric"]["estimatedDecided"], 50.0)
        self.assertEqual(view["weightedScore"], 0.5)  # 50 at 100%, 50 at 0%
        self.assertEqual(view["weightedCovers"], round(100 / 150, 4))

    def test_a_class_with_no_score_is_not_hidden_behind_the_rest(self):
        self.write("a", kind="mutant", id="a", outcome="caught-cheap", **{"class": "code"})
        self.write("b", kind="mutant", id="b", outcome="undecided", **{"class": "numeric"})
        doc = self.view_of({"numeric": 2642, "code": 20}, {"numeric": 1, "code": 1})
        self.assertEqual(doc["sampling"]["weightedCovers"], round(20 / 2662, 4))
        self.assertIn("covering 1% of the estimated visible mutants", mb.markdown(doc))

    def test_a_class_never_sampled_is_named_beside_the_coverage(self):
        self.write("a", kind="mutant", id="a", outcome="caught-cheap", **{"class": "code"})
        doc = self.view_of({"numeric": 1000, "code": 20}, {"numeric": 0, "code": 1})
        self.assertEqual(doc["sampling"]["classesNotSampled"], ["numeric"])
        self.assertIn("classes never sampled: numeric", mb.markdown(doc))

    def test_repeated_equivalents_never_give_a_negative_estimate(self):
        for i in range(3):
            self.write(f"e{i}", kind="mutant", id=f"e{i}", outcome="equivalent", dropReason="x", **{"class": "code"})
        view = self.view_of({"code": 20}, {"code": 1})["sampling"]
        self.assertEqual(view["classes"]["code"]["estimatedVisible"], 0.0)

    def test_a_rehearsal_survivor_is_not_a_blind_spot(self):
        self.write("a", case="c", operator="rehearsal", outcome="survived", rehearsal=True, preregistrationSha256=None)
        self.write("b", case="d", operator="rehearsal", outcome="caught-sam", rehearsal=True, preregistrationSha256=None)
        doc = mb.summarize(self.out)
        self.assertEqual((doc["blindSpots"], doc["visionOnlyWins"]), ([], []))

    def test_results_the_manifest_never_sampled_are_flagged(self):
        manifest = self.out / "manifest.json"
        manifest.write_text(json.dumps({"mutants": [{"id": "m1"}]}))
        self.write("a", kind="mutant", id="stray", outcome="caught-cheap")
        with mock.patch.object(mb, "MANIFEST", manifest):
            doc = mb.summarize(self.out)
        self.assertEqual(doc["reconciliation"]["notInManifest"], ["stray"])
        self.assertIn("1 not in the manifest", mb.markdown(doc))

    def test_cases_outside_the_score_are_counted_beside_it(self):
        self.write("a", kind="mutant", id="a", outcome="caught-cheap", **{"class": "code"})
        self.write("b", kind="mutant", id="b", outcome="awaiting-sam", **{"class": "code"})
        self.assertIn("Outside the score: 1 of 2 cases", mb.markdown(mb.summarize(self.out)))

    def test_a_manifest_that_does_not_know_a_class_says_so(self):
        self.write("a", kind="mutant", id="a", outcome="caught-cheap", **{"class": "new"})
        doc = self.view_of({"code": 20}, {"code": 1})
        self.assertIn("Classes the manifest does not know: new", mb.markdown(doc))

    def test_with_no_manifest_the_report_will_not_call_it_a_score_for_the_game(self):
        self.write("a", kind="mutant", id="a", outcome="caught-cheap", **{"class": "code"})
        with mock.patch.object(mb, "MANIFEST", self.out / "gone.json"):
            text = mb.markdown(mb.summarize(self.out))
        self.assertIn("not a score for the whole game", text)
        self.assertNotIn("Mutation score: **", text)

    def test_a_manifest_with_no_method_is_treated_the_same(self):
        self.write("a", kind="mutant", id="a", outcome="caught-cheap", **{"class": "code"})
        text = mb.markdown(self.view_of({"code": 20}, {"code": 1}, method=None))
        self.assertIn("not a score for the whole game", text)

    def test_a_uniform_sample_keeps_the_plain_score_and_its_table(self):
        self.write("a", kind="mutant", id="m1", outcome="caught-cheap", **{"class": "code"})
        manifest = self.out / "manifest.json"
        manifest.write_text(json.dumps({"sampling": {"method": "uniform"}, "enumeratedByClass": {"code": 20},
                                        "sampledByClass": {"code": 1}, "mutants": [{"id": "m1"}]}))
        with mock.patch.object(mb, "MANIFEST", manifest):
            text = mb.markdown(mb.summarize(self.out))
        self.assertIn("Mutation score: **100.0%**", text)
        self.assertIn("Method: uniform", text)

    def test_per_class_and_per_operator_tables_show_a_score(self):
        self.write("a", kind="mutant", id="m", outcome="caught-cheap", operator="hide", **{"class": "code"})
        text = mb.markdown(mb.summarize(self.out))
        self.assertIn("| code | 100.0% | 1 |", text)
        self.assertIn("| hide | 100.0% | 1 |", text)


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        import yaml

        self.doc = yaml.safe_load((REPO / ".github" / "workflows" / "mutation-bench.yml").read_text(encoding="utf-8"))

    def test_every_render_job_installs_a_display(self):
        for job in ("run", "sam-warm"):
            # Packages are installed through the apt-install action, so they are named in its inputs.
            steps = " ".join(str(s.get("run", "")) + " " + str((s.get("with") or {}).get("packages", ""))
                             for s in self.doc["jobs"][job]["steps"])
            with self.subTest(job=job):
                self.assertIn("xvfb", steps)
                self.assertIn("libgl1-mesa-dri", steps)

    def test_every_upload_is_scanned_first(self):
        """The Fix matrix's rule since #107. Walks every job, so a new upload cannot skip it."""
        uploads = 0
        for name, job in self.doc["jobs"].items():
            scanned = []
            for step in job["steps"]:
                run = str(step.get("run", ""))
                if "agents.export_scan" in run:
                    scanned.append(step)
                if "upload-artifact" not in str(step.get("uses", "")):
                    continue
                uploads += 1
                path = step["with"]["path"].strip().rstrip("/")
                with self.subTest(job=name, path=path):
                    scan = next((s for s in scanned if path in str(s["run"])), None)
                    self.assertIsNotNone(scan, f"{path} is uploaded unscanned")
                    if "always()" in str(step.get("if", "")):  # it runs even if the scan failed, unless gated
                        self.assertIn(f"steps.{scan['id']}.outcome == 'success'", step["if"])
        self.assertEqual(uploads, 4)

    def test_an_empty_summary_fails_its_step(self):
        step = next(s for s in self.doc["jobs"]["summarize"]["steps"] if s.get("name") == "Summarize")
        self.assertIn("set -o pipefail", step["run"])

    def test_the_private_set_is_never_checked_out(self):
        text = str(self.doc)
        self.assertNotIn("Expectrail-heldout", text)
        self.assertNotIn("HELDOUT_TOKEN", text)

    def test_the_plan_refuses_an_incomplete_pre_registration_and_any_branch(self):
        steps = str(self.doc["jobs"]["plan"]["steps"])
        self.assertIn("load_preregistration", steps)
        self.assertIn("load_manifest(prereg, MANIFEST)", steps)
        self.assertIn("refs/heads/main", steps)

    def test_only_the_dry_run_skips_that_gate(self):
        gate = next(s for s in self.doc["jobs"]["plan"]["steps"] if "load_preregistration" in str(s))
        self.assertEqual(gate["if"], "${{ !startsWith(inputs.mode, 'dry-run') }}")

    def judge_step(self):
        return next(s for s in self.doc["jobs"]["run"]["steps"] if s.get("name", "").startswith("Judge one case"))

    def test_every_mode_is_handled_by_the_judging_step(self):
        for mode in self.doc[True]["workflow_dispatch"]["inputs"]["mode"]["options"]:
            self.assertIn(f"{mode}) python", self.judge_step()["run"], mode)

    def test_each_rehearsal_runs_what_it_says(self):
        run = self.judge_step()["run"]
        self.assertIn("dry-run) python -m agents.mutation_bench --dry-run --out", run)
        self.assertIn("dry-run-sam) python -m agents.mutation_bench --dry-run sam --out", run)
        self.assertIn("dry-run-mutants) python -m agents.mutation_bench --dry-run mutants --out", run)

    def test_the_sam_rehearsal_gets_the_shared_answers_like_a_judged_run(self):
        steps = self.doc["jobs"]["run"]["steps"]
        guards = [self.doc["jobs"]["sam-warm"]["if"]] + [s["if"] for s in steps if "sam" in str(s.get("name", "")).lower()
                                                          and "if" in s]
        self.assertEqual(len(guards), 3)
        for guard in guards:
            with self.subTest(guard=guard):
                self.assertIn("inputs.mode == 'dry-run-sam'", guard)
                self.assertIn("inputs.mode == 'wrong-fix'", guard)
                self.assertIn("inputs.mode == 'generated-sam'", guard)

    def test_a_rehearsal_never_lands_with_judged_results(self):
        jobs = self.doc["jobs"]["summarize"]
        self.assertEqual(jobs["env"]["DEST"], "bench/mutation/${{ startsWith(inputs.mode, 'dry-run') && 'dry-run' || "
                                              "inputs.mode == 'wrong-fix' && 'wrong-fix' || 'generated' }}")
        upload = next(s for s in jobs["steps"] if "upload-artifact" in str(s.get("uses")))
        self.assertIn("mutation-rehearsal", upload["with"]["name"])

    def test_results_keep_godots_log(self):
        self.assertIn("godot.log", self.judge_step()["run"])

    def test_only_the_phases_that_ask_sam_hold_the_key(self):
        key = self.doc["jobs"]["run"]["env"]["MODEL_API_KEY"]
        for mode in ("wrong-fix", "generated-sam", "dry-run-sam"):
            self.assertIn(f"inputs.mode == '{mode}'", key)
        for mode in ("generated-cheap", "dry-run-mutants", "'dry-run'"):
            self.assertNotIn(mode, key)

    def test_results_keep_the_trace(self):
        self.assertIn("trace.json", str(self.doc["jobs"]["run"]["steps"]))


if __name__ == "__main__":
    unittest.main()
