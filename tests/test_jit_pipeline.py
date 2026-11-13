"""Generated checks (docs/jit.md): the diff map, the assessor, the near-miss generator and one whole run
on a simulated game. Offline: no Godot, no model key."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail.contracts import load_strict, validate_v1
from expectrail.jit.probes import jit_library
from expectrail.jit import assess, cli
from expectrail.jit.diff_map import PatchError, diff_map, parse
from expectrail.jit.intent import IntentUnavailable, from_proposal, parse_answer, propose_to_file
from expectrail.jit.run import gate_summary, generate
from tests.jit_fixtures import ANSWER, PROFILE, STUB, Case, JitGame, model

REPO = Path(__file__).resolve().parents[1]
PROF = json.loads(PROFILE.read_text())
PROBES = jit_library(PROF["actions"])


def run_case(fix: str, *, base=("air-jump",), variants=("variant-airjump", "variant-noop"), answer=ANSWER,
             runner=None, **kw):
    case = Case()
    intent, transport = model(answer)
    doc = generate(PROFILE, "Infinite jump while in the air.", case.patch(fix), [case.patch(b) for b in base],
                   case.dir / "out", runner=runner or JitGame(), intent=kw.pop("intent", intent),
                   variants_fn=case.variants(*variants), **kw)
    return doc, transport, case


class DiffMap(unittest.TestCase):
    def test_reads_files_lines_and_the_claims_the_profile_ties_to_them(self):
        text = (REPO / "bugs" / "reported" / "air-jump.patch").read_text()
        m = diff_map(text, PROF, PROBES)
        self.assertEqual([f["path"] for f in m["files"]], ["player/player.gd"])
        self.assertIn("player.jump", m["claims"])
        self.assertIn("player.facing", m["claims"])  # player.gd is evidence for both
        self.assertTrue(m["files"][0]["addedLines"] and m["files"][0]["removedLines"])
        self.assertIn("jump-w0-x8", m["probeIds"])

    def test_a_file_no_claim_names_keeps_every_probe(self):
        m = diff_map("--- a/level/level.tscn\n+++ b/level/level.tscn\n@@ -1 +1 @@\n-a\n+b\n", PROF, PROBES)
        self.assertEqual(m["claims"], [])
        self.assertTrue(m["allProbes"])
        self.assertEqual(len(m["probeIds"]), len(PROBES))

    def test_refuses_what_is_not_a_patch_or_escapes_the_game(self):
        for bad in ("", "hello", "--- a/../x\n+++ b/../x\n@@ -1 +1 @@\n-a\n+b\n",
                    "--- /etc/passwd\n+++ /etc/passwd\n@@ -1 +1 @@\n-a\n+b\n"):
            with self.assertRaises(PatchError):
                parse(bad)

    def test_line_numbers_follow_the_hunks(self):
        files = parse("--- a/x.gd\n+++ b/x.gd\n@@ -10,3 +10,3 @@\n keep\n-old\n+new\n keep\n")
        self.assertEqual(files[0]["added"], [(11, "new")])
        self.assertEqual(files[0]["removed"], [(11, "old")])


class Assessor(unittest.TestCase):
    def test_validity_needs_the_reference_three_of_three_and_a_kill(self):
        self.assertTrue(assess.validity(["pass"] * 3, {"v": ["fail"] * 3})["valid"])
        self.assertFalse(assess.validity(["pass"] * 3, {"v": ["fail", "fail", "pass"]})["valid"])
        self.assertFalse(assess.validity(["pass"] * 3, {})["valid"])
        for ref in (["pass", "pass"], ["pass", "not_exercised", "pass"], ["fail"], ["pass", "pass", "execution_error"]):
            self.assertFalse(assess.validity(ref, {"v": ["fail"] * 3})["valid"], ref)

    def test_a_catch_is_three_failures_of_three_and_mixed_is_flaky(self):
        self.assertEqual(assess.catch(True, ["fail"] * 3), "catch")
        self.assertEqual(assess.catch(True, ["fail", "pass", "fail"]), "flaky")
        self.assertEqual(assess.catch(True, ["pass"] * 3), "no-catch")
        self.assertEqual(assess.catch(False, ["fail"] * 3), "not-evaluated")
        self.assertEqual(assess.catch(True, ["fail"] * 2), "not-evaluated")

    def test_strength(self):
        self.assertEqual(assess.strength(["fail"] * 3, "player.jump"), "strong")
        self.assertEqual(assess.strength(["pass"], "player.jump"), "weak")
        self.assertEqual(assess.strength(None, "player.jump"), "weak")
        self.assertEqual(assess.strength(None, "player.jump", frozenset({"player.jump"})), "strong")


class Pipeline(unittest.TestCase):
    def test_a_correct_fix_has_no_catch_and_only_the_useful_check_is_valid(self):
        doc, _t, _c = run_case("fix-good")
        validate_v1(doc, "jit-run")
        self.assertEqual(doc["status"], "complete")
        rows = {v["specId"]: v for v in doc["validity"]}
        self.assertTrue(rows["jit-no-extra-air-jumps"]["valid"])
        self.assertEqual(rows["jit-no-extra-air-jumps"]["outcome"], "no-catch")
        self.assertIn("killed no near-miss variant", rows["jit-always-passes"]["reasons"])
        self.assertFalse(rows["jit-miscalibrated"]["valid"])
        self.assertEqual(doc["catches"], [])

    def test_a_fix_that_leaves_the_bug_is_a_strong_catch(self):
        doc, _t, _c = run_case("fix-wrong")
        self.assertEqual([(c["specId"], c["strength"]) for c in doc["catches"]], [("jit-no-extra-air-jumps", "strong")])
        catch = doc["catches"][0]
        self.assertEqual(catch["candidate"], ["fail"] * 3)
        self.assertEqual(catch["base"], ["fail"] * 3)
        self.assertIn("base", catch["killed"])

    def test_without_a_base_a_catch_is_weak(self):
        # The near miss brings the air jump back with the player 1 px to the right, so it differs from
        # the candidate (which still air-jumps) while still failing the check.
        doc, _t, _c = run_case("fix-wrong-no-base", base=(), variants=("variant-airjump-moved",),
                               runner=_AlwaysAirJump())
        # The reference is the clean game; the candidate still has unlimited air jumps.
        self.assertEqual([c["strength"] for c in doc["catches"]], ["weak"])
        self.assertIsNone(doc["catches"][0]["base"])

    def test_a_near_miss_that_behaves_like_the_candidate_kills_nothing(self):
        # Review of #231: "variant-airjump" on a candidate that already air-jumps gives the candidate's
        # own trace, so the check "killing" it would prove nothing; it is not counted, and with no
        # other near miss the check is not valid and nothing is caught.
        doc, _t, _c = run_case("fix-wrong-no-base", base=(), variants=("variant-airjump",),
                               runner=_AlwaysAirJump())
        self.assertEqual(doc["catches"], [])
        variant = next(v for v in doc["variants"] if v["kind"] != "base")
        self.assertIn("jit-no-extra-air-jumps", variant["sameAsCandidateFor"])
        row = next(v for v in doc["validity"] if v["specId"] == "jit-no-extra-air-jumps")
        self.assertFalse(row["valid"])

    def test_the_base_build_counts_even_when_the_candidate_behaves_like_it(self):
        # A comment-only "fix" behaves like the bug: the base build is still a near miss, so the
        # check that fails on the bug is valid and catches the candidate, strongly.
        doc, _t, _c = run_case("fix-comment")
        self.assertEqual([(c["specId"], c["strength"]) for c in doc["catches"]], [("jit-no-extra-air-jumps", "strong")])
        self.assertNotIn("sameAsCandidateFor", next(v for v in doc["variants"] if v["kind"] == "base"))

    def test_every_generated_check_is_advisory_model_prior_and_auto_diff(self):
        doc, _t, _c = run_case("fix-wrong")
        for p in doc["proposed"]:
            self.assertEqual(p["spec"]["origin"], "AUTO_DIFF")
            self.assertEqual(p["spec"]["expectationRef"]["authority"], "model_prior")
            self.assertTrue(p["spec"]["id"].startswith("jit-"))
        self.assertIs(doc["advisory"], True)
        self.assertNotIn("decision", doc)

    def test_the_record_round_trips_and_the_gate_block_follows_its_rows(self):
        doc, _t, case = run_case("fix-wrong")
        again = load_strict(case.dir / "out" / "jit-run.json", "jit-run")
        self.assertEqual(again, doc)
        block = gate_summary(doc)
        self.assertEqual((block["status"], block["strong"], block["weak"], block["valid"]), ("ran", 1, 0, 1))
        self.assertEqual(block["catches"][0]["specId"], "jit-no-extra-air-jumps")
        self.assertEqual(gate_summary(None)["status"], "not-run")

    def test_same_change_ten_times_gives_the_same_catches(self):
        seen = set()
        for _ in range(10):
            doc, _t, _c = run_case("fix-wrong")
            seen.add(json.dumps([(v["specId"], v["valid"], v["outcome"], v["killed"]) for v in doc["validity"]]
                                + [(c["specId"], c["strength"]) for c in doc["catches"]]))
        self.assertEqual(len(seen), 1)

    def test_a_flaky_kill_does_not_make_a_check_valid(self):
        doc, _t, _c = run_case("fix-good", base=(), variants=("flaky-air-jump",))
        rows = {v["specId"]: v for v in doc["validity"]}
        self.assertFalse(rows["jit-no-extra-air-jumps"]["valid"])

    def test_the_report_and_gate_summary_commands(self):
        doc, _t, case = run_case("fix-wrong")
        record = case.dir / "out" / "jit-run.json"
        self.assertIn("strong", cli.render(doc))
        out = case.dir / "block.json"
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["gate-summary", str(record), "--out", str(out)]), 0)
        self.assertEqual(json.loads(out.read_text())["strong"], 1)


class _AlwaysAirJump(JitGame):
    def __call__(self, route_path, run_dir, patches=()):
        stems = {Path(p).stem for p in patches}
        if "fix-wrong-no-base" in stems:
            patches = [*patches, Path("air-jump.patch")]
        return super().__call__(route_path, run_dir, patches=patches)


class Proposal(unittest.TestCase):
    def test_propose_then_replay_gives_the_same_record_as_one_step(self):
        case = Case()
        cand, base = case.patch("fix-wrong"), case.patch("air-jump")
        intent, _t = model()
        one = generate(PROFILE, "r", cand, [base], case.dir / "one", runner=JitGame(), intent=intent,
                       variants_fn=case.variants("variant-airjump"))
        intent2, _t2 = model()
        propose_to_file(intent2, "r", cand.read_text(), PROF, PROBES, case.dir / "p")
        two = generate(PROFILE, "r", cand, [base], case.dir / "two", runner=JitGame(),
                       intent=from_proposal(case.dir / "p" / "jit-proposal.json"),
                       variants_fn=case.variants("variant-airjump"))
        strip = lambda d: {k: v for k, v in d.items() if k not in ("runId", "spend")}  # noqa: E731
        self.assertEqual(strip(one), strip(two))

    def test_a_proposal_for_another_patch_is_refused(self):
        case = Case()
        intent, _t = model()
        propose_to_file(intent, "r", "--- a/x.gd\n+++ b/x.gd\n@@ -1 +1 @@\n-a\n+c\n", PROF, PROBES, case.dir / "p")
        doc = generate(PROFILE, "r", case.patch("fix-wrong"), [case.patch("air-jump")], case.dir / "out",
                       runner=JitGame(), intent=from_proposal(case.dir / "p" / "jit-proposal.json"),
                       variants_fn=case.variants("variant-airjump"))
        self.assertEqual(doc["status"], "nothing-generated")
        self.assertIn("PROPOSAL_MISMATCH", doc["reason"])

    def test_a_tampered_proposal_is_refused(self):
        case = Case()
        intent, _t = model()
        propose_to_file(intent, "r", STUB, PROF, PROBES, case.dir / "p")
        path = case.dir / "p" / "jit-proposal.json"
        doc = json.loads(path.read_text())
        doc["candidates"][0]["spec"]["expectationRef"]["authority"] = "approved_intent"
        path.write_text(json.dumps(doc))
        with self.assertRaises(IntentUnavailable):
            from_proposal(path)("r", STUB, {}, PROF, PROBES)

    def test_the_model_answer_parser_drops_what_does_not_validate(self):
        bad = {"candidates": [{"id": "code", "statement": "x", "claimId": "player.jump", "class": "player",
                               "operation": {"type": "python", "src": "import os"}}]}
        with self.assertRaises(IntentUnavailable):
            parse_answer(json.dumps(bad), PROF, {p["id"] for p in PROBES})
        probes, entries, _n = parse_answer(json.dumps(ANSWER), PROF, {p["id"] for p in PROBES})
        self.assertEqual(len(entries), 3)


class DiffGames(unittest.TestCase):
    def test_two_folders_give_the_patch_that_turns_one_into_the_other(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "a" / "player").mkdir(parents=True)
        (tmp / "a" / "player" / "p.gd").write_text("one\ntwo\n")
        shutil.copytree(tmp / "a", tmp / "b")
        (tmp / "b" / "player" / "p.gd").write_text("one\nthree\n")
        (tmp / "b" / "new.gd").write_text("x")
        text = cli.diff_games(tmp / "a", tmp / "b")
        self.assertEqual([f["path"] for f in parse(text)], ["new.gd", "player/p.gd"])
        self.assertEqual(cli.diff_games(tmp / "a", tmp / "b"), text)
        self.assertEqual(cli.diff_games(tmp / "a", tmp / "a"), "")


class Dodgy(unittest.TestCase):
    """The near-miss generator on the real game and a real fix (needs the `patch` tool, not Godot)."""

    @classmethod
    def setUpClass(cls):
        if shutil.which("patch") is None:
            raise unittest.SkipTest("the patch tool is not installed")

    def test_variants_of_the_exact_undo_are_near_misses_that_apply(self):
        from expectrail.jit.dodgy import registered_steps, variants
        from harness.run import apply_patches

        game = REPO / "game" / "platformer"
        base = [REPO / "bugs" / "reported" / "air-jump.patch"]
        cand = REPO / "bench" / "jit" / "rehearsal" / "air-jump-undo.patch"
        vs = variants(game, base, cand, steps=registered_steps())
        self.assertTrue(vs)
        self.assertEqual(vs, variants(game, base, cand, steps=registered_steps()))  # deterministic
        kinds = {v["kind"] for v in vs}
        self.assertIn("partial-revert", kinds)
        self.assertIn("jit-operator", kinds)
        for v in vs:
            tmp = Path(tempfile.mkdtemp())
            self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
            shutil.copytree(game, tmp / "g", ignore=shutil.ignore_patterns(".godot"))
            vp = tmp / "v.patch"
            vp.write_text(v["patchText"])
            apply_patches(tmp / "g", [*base, cand, vp])  # raises if a variant does not apply

    def test_the_limit_is_kept_with_a_seed_from_the_candidate(self):
        from expectrail.jit.dodgy import variants

        game = REPO / "game" / "platformer"
        base = [REPO / "bugs" / "reported" / "air-jump.patch"]
        cand = REPO / "bench" / "jit" / "rehearsal" / "air-jump-undo.patch"
        two = variants(game, base, cand, limit=2)
        self.assertEqual(len(two), 2)
        self.assertEqual(two, variants(game, base, cand, limit=2))


if __name__ == "__main__":
    unittest.main()


class ProposeCommandTest(unittest.TestCase):
    """`python -m expectrail.jit.cli propose`, as jit.yml's live propose job calls it. The first live
    dispatch failed before any model call: the subcommand read a --budget-usd it never defined."""

    def test_propose_parses_its_arguments_and_records_an_unavailable_model(self):
        import contextlib
        import io
        import tempfile
        from pathlib import Path
        from unittest import mock

        from expectrail.jit import cli, intent

        def unavailable(offer="baseline"):
            def propose(*_a, **_k):
                raise intent.IntentUnavailable("no model in tests")
            propose.model, propose.system = "test", ""
            return propose

        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(intent, "spark_intent", unavailable), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            code = cli.main(["propose", "--report-file", str(repo / "bench/jit/rehearsal/air-jump.report.txt"),
                             "--candidate", str(repo / "bench/jit/rehearsal/air-jump-comment-only.patch"),
                             "--out", tmp, "--budget-usd", "2"])
            self.assertEqual(code, 0)
            printed = json.loads(out.getvalue())
            self.assertTrue(printed["error"])
            self.assertEqual(printed["candidates"], 0)
            self.assertTrue((Path(tmp) / "jit-proposal.json").is_file())

    def test_live_propose_job_passes_the_budget(self):
        from pathlib import Path

        text = (Path(__file__).resolve().parents[1] / ".github/workflows/jit.yml").read_text(encoding="utf-8")
        job = text[text.index("  propose:"):text.index("  replay:")]
        self.assertIn('--budget-usd "$BUDGET"', job)
        self.assertIn("environment: main-only", job)


class SparkTimeoutTest(unittest.TestCase):
    def test_the_live_call_waits_longer_than_the_spec_writers_default(self):
        from unittest import mock

        from expectrail import spec_writer
        from expectrail.jit import intent

        seen = {}

        def fake(body, timeout=120):
            seen["timeout"] = timeout
            raise TimeoutError("test")

        with mock.patch.object(spec_writer, "http_transport", fake):
            propose = intent.spark_intent()
            profile = load_strict(PROFILE, "mechanics-profile") if isinstance(PROFILE, Path) else PROFILE
            dmap = {"files": [], "claims": []}
            with self.assertRaises(intent.IntentUnavailable):
                propose("report", "", dmap, profile, [])
        self.assertEqual(seen["timeout"], intent.SPARK_TIMEOUT_S)
        self.assertGreaterEqual(intent.SPARK_TIMEOUT_S, 300)
