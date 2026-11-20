"""The generator offers mirror-inputs metamorphic checks (#675, piece 3, slice 2), judged by the same rule as a
proposed check, in advisory rows that nothing counts."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from expectrail.contracts import validate_v1
from expectrail.jit import assess, cli, do_nothing, metamorphic
from expectrail.jit.probes import jit_library
from expectrail.jit.run import NO_CONTROL_GIVEN, gate_summary, generate
from tests.jit_fixtures import GOOD_CHECK, Case, model
from tests.test_jit_do_nothing import FrozenJitGame

REPO = Path(__file__).resolve().parents[1]
PROFILE = REPO / "discovery" / "platformer.profile.json"
PROF = json.loads(PROFILE.read_text())
GAME = REPO / "game" / "platformer"
REPORT = "The robot walks slower to the left than to the right."


class SlowLeftGame(FrozenJitGame):
    """FrozenJitGame, plus a defect ``slow-left`` (the player walks left at half speed), which ``fix-slowleft``
    removes and ``variant-slowleft`` puts back."""

    def __call__(self, route_path, run_dir, patches=()):
        stems = {Path(p).stem for p in patches}
        slow = ("slow-left" in stems and "fix-slowleft" not in stems) or "variant-slowleft" in stems
        out = super().__call__(route_path, run_dir, patches=patches)
        if slow:
            path = Path(run_dir) / "trace.json"
            trace = json.loads(path.read_text())
            prev_old = prev_new = None
            for row in trace["rows"]:
                x = row["player"][0]
                if prev_old is not None:
                    dx = x - prev_old
                    row["player"][0] = round(prev_new + (dx / 2 if dx < 0 else dx), 3)
                prev_old, prev_new = x, row["player"][0]
            path.write_text(json.dumps(trace))
        return out


class MirrorRefused(SlowLeftGame):
    """A replay of any mirrored route fails."""

    def __call__(self, route_path, run_dir, patches=()):
        if json.loads(Path(route_path).read_text())["name"].endswith("-mirror"):
            raise RuntimeError("godot exited with code 1")
        return super().__call__(route_path, run_dir, patches=patches)


def controls(classes):
    return do_nothing.controls(GAME, PROF, classes)


def run(candidate="fix-wrong", game=None, **kw):
    case = Case()
    game = game or SlowLeftGame()
    intent, _ = model({"candidates": [GOOD_CHECK]})
    doc = generate(PROFILE, REPORT, case.patch(candidate), [case.patch("slow-left")], case.dir / "out",
                   runner=game, intent=intent, variants_fn=case.variants("variant-slowleft"), **kw)
    validate_v1(doc, "jit-run")
    return doc, game


class Offer(unittest.TestCase):
    def setUp(self):
        self.probes = jit_library(PROF["actions"])

    def test_at_most_the_limit_in_library_order_and_one_of_each_twin_pair(self):
        got, skipped = metamorphic.offer(self.probes, PROF["actions"])
        self.assertEqual([d["probe"] for d in got], ["hold-right", "reverse", "jump-w40-x1", "jump-w40-x2"])
        why = {s["probe"]: s["reason"] for s in skipped}
        self.assertEqual(why["hold-left"], "the same two programs as a pair already offered")
        self.assertTrue(why["wait-long"].startswith("cannot tell:"))
        self.assertEqual(why["jump-w40-x8"], f"over the limit of {metamorphic.PAIR_LIMIT} pairs")
        self.assertEqual(sum(len(d["entries"]) for d in got), 4 * metamorphic.PAIR_LIMIT)

    def test_the_probes_the_proposed_checks_use_come_first(self):
        got, _ = metamorphic.offer(self.probes, PROF["actions"], first=["jump-w0-x2", "jump-w80-x8", "nope"])
        self.assertEqual([d["probe"] for d in got][:2], ["jump-w80-x8", "hold-right"])

    def test_a_probe_with_no_program_is_never_mirrored(self):
        report = {"id": "ingest-report", "source": "report", "route": {"events": []}}
        got, skipped = metamorphic.offer([report], PROF["actions"], first=["ingest-report"])
        self.assertEqual((got, skipped), ([], []))


class Pipeline(unittest.TestCase):
    def test_off_by_default_and_the_record_is_unchanged(self):
        doc, game = run()
        self.assertNotIn("metamorphic", doc)
        self.assertNotIn("metamorphic", doc["settings"])
        self.assertFalse(any("-mirror" in key for key in game.calls))

    def test_a_mirror_check_catches_a_fix_that_leaves_the_left_walk_slow(self):
        doc, _ = run(metamorphic=True, do_nothing=controls)
        self.assertEqual(doc["status"], "complete")
        self.assertIs(doc["settings"]["metamorphic"], True)
        rows = {r["spec"]["id"]: r for r in doc["metamorphic"]}
        self.assertEqual(len(rows), 16)
        dx = rows["mm-mirror-hold-right-player-dx-px"]
        self.assertEqual(dx["probeIds"], ["hold-right", "hold-right-mirror"])
        self.assertEqual(dx["reference"], ["pass"] * 3)
        self.assertEqual(dx["base"], ["fail"] * 3)
        # The near miss puts the slow walk back, exactly as the candidate left it: no kill (review of #231).
        self.assertEqual(dx["killed"], ["base"])
        self.assertEqual(dx["sameAsCandidate"], ["v-variant-slowleft"])
        self.assertTrue(dx["valid"])
        self.assertEqual(dx["candidate"], ["fail"] * 3)
        self.assertEqual(dx["outcome"], "catch")
        self.assertEqual(dx["exercised"]["reference"], [True] * 3)
        # A frozen player is not exercised by a mirror check: the control cannot pass it, so it is not dropped.
        self.assertEqual(dx["doNothing"]["runs"], ["not_exercised"])
        self.assertEqual(dx["doNothing"]["outcome"], "indeterminate")
        self.assertEqual([c["class"] for c in doc["doNothing"]], ["player"])
        # Walking alone is never in the air: the equal-height check is not exercised, never a pass.
        rise = rows["mm-mirror-hold-right-max-rise-px"]
        self.assertEqual(rise["reference"], ["not_exercised"])
        self.assertFalse(rise["valid"])
        self.assertEqual(rise["outcome"], "not-evaluated")
        self.assertEqual(rise["doNothing"]["outcome"], "not-run")
        # Height and airtime do not depend on the walking speed: valid nowhere, so nothing more is claimed.
        jump_rise = rows["mm-mirror-jump-w40-x1-max-rise-px"]
        self.assertEqual(jump_rise["reference"], ["pass"] * 3)
        self.assertEqual(jump_rise["reasons"], ["killed no near-miss variant"])

    def test_a_working_fix_passes_every_mirror_check(self):
        doc, _ = run("fix-slowleft", metamorphic=True)
        dx = next(r for r in doc["metamorphic"] if r["spec"]["id"] == "mm-mirror-hold-right-player-dx-px")
        self.assertTrue(dx["valid"])
        self.assertEqual(dx["candidate"], ["pass"] * 3)
        self.assertEqual(dx["outcome"], "no-catch")
        self.assertEqual(dx["killed"], ["base", "v-variant-slowleft"])
        self.assertEqual(dx["exercised"]["v-variant-slowleft"], [True] * 3)
        self.assertEqual(dx["doNothing"]["reason"], NO_CONTROL_GIVEN)

    def test_never_in_what_counts(self):
        plain, _ = run()
        doc, _ = run(metamorphic=True)
        self.assertTrue(any(r["outcome"] == "catch" for r in doc["metamorphic"]))
        for key in ("proposed", "validity", "catches", "counts", "variants"):
            self.assertEqual(doc[key], plain[key], key)
        ids = {r["spec"]["id"] for r in doc["metamorphic"]}
        self.assertFalse(ids & {row["specId"] for row in assess.counting(doc, REPORT, trusted=True)})
        self.assertNotIn("mm-mirror", json.dumps(gate_summary(doc)))

    def test_a_failure_in_this_stage_leaves_the_proposed_results_and_says_why(self):
        plain, _ = run()
        doc, _ = run(game=MirrorRefused(), metamorphic=True)
        self.assertEqual(doc["status"], "complete")
        self.assertEqual(doc["validity"], plain["validity"])
        self.assertTrue(doc["metamorphic"])
        for r in doc["metamorphic"]:
            self.assertEqual(r["outcome"], "not-evaluated")
            self.assertTrue(r["reasons"][-1].startswith("not evaluated: REPLAY_ERROR"), r["reasons"])
        self.assertTrue(any(d.startswith("metamorphic: stopped") for d in doc["diagnostics"]))

    def test_the_skips_are_one_diagnostic_line(self):
        doc, _ = run(metamorphic=True)
        lines = [d for d in doc["diagnostics"] if d.startswith("metamorphic:")]
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("metamorphic: 4 pairs offered (hold-right, reverse, jump-w40-x1, jump-w40-x2)"),
                        lines[0])
        self.assertIn("over the limit of 4 pairs", lines[0])

    def test_a_run_that_generated_nothing_writes_no_metamorphic_row(self):
        case = Case()
        doc = generate(PROFILE, REPORT, case.patch("fix-wrong"), [case.patch("slow-left")], case.dir / "out",
                       runner=SlowLeftGame(), intent=None, metamorphic=True)
        validate_v1(doc, "jit-run")
        self.assertEqual(doc["status"], "nothing-generated")
        self.assertEqual(doc["metamorphic"], [])

    def test_the_report_shows_the_rows_as_advisory(self):
        doc, _ = run(metamorphic=True)
        text = cli.render(doc)
        self.assertIn("Metamorphic checks (#675), advisory and never counted: 16 offered", text)
        self.assertIn("| `mm-mirror-hold-right-player-dx-px` | yes | pass, pass, pass |", text)


class TheExample(unittest.TestCase):
    def test_the_example_validates_and_each_row_is_a_metamorphic_trace_spec(self):
        from expectrail.contracts import load_strict

        doc = load_strict(REPO / "contracts" / "examples" / "jit-run-metamorphic.json", "jit-run")
        self.assertIs(doc["settings"]["metamorphic"], True)
        self.assertTrue(doc["metamorphic"])
        for r in doc["metamorphic"]:
            validate_v1(r["spec"], "trace-spec")
            self.assertEqual(r["spec"]["operation"]["type"], "metamorphic")
        self.assertEqual([r["outcome"] for r in doc["metamorphic"]][0], "catch")
        self.assertEqual(doc["catches"], [])
        self.assertIn("Metamorphic checks (#675)", cli.render(doc))

    def test_a_row_that_is_not_a_metamorphic_spec_is_refused(self):
        from expectrail.contracts import load_strict

        doc = load_strict(REPO / "contracts" / "examples" / "jit-run-metamorphic.json", "jit-run")
        doc["metamorphic"][0]["spec"]["operation"]["type"] = "relation"
        with self.assertRaises(Exception):
            validate_v1(doc, "jit-run")


class CommittedRuns(unittest.TestCase):
    """The two real-engine records under bench/jit/stand-in say what the measurement page says."""

    def _doc(self, which):
        from expectrail.contracts import load_strict

        return load_strict(REPO / "bench" / "jit" / "stand-in" / f"slow-left-metamorphic-{which}" / "jit-run.json",
                           "jit-run")

    def test_the_sideways_checks_catch_the_comment_only_candidate_and_pass_the_revert(self):
        for which, outcome, runs in (("comment-only", "catch", ["fail"] * 3), ("revert", "no-catch", ["pass"] * 3)):
            doc = self._doc(which)
            self.assertEqual((doc["status"], doc["settings"]["candidate"], doc["inputs"]["model"]),
                             ("complete", "withheld", "hand-written-stand-in"))
            valid = [r for r in doc["metamorphic"] if r["valid"]]
            self.assertEqual(sorted(r["spec"]["operation"]["signal"] for r in valid), ["player_dx_px"] * 4)
            for r in valid:
                self.assertEqual((r["reference"], r["base"], r["candidate"], r["outcome"]),
                                 (["pass"] * 3, ["fail"] * 3, runs, outcome))
            self.assertEqual(len(doc["metamorphic"]), 16)
            self.assertEqual(doc["catches"], [])
            self.assertEqual(doc["counts"]["valid"], 0)

    def test_the_candidate_files_are_the_ones_the_records_name(self):
        import hashlib

        for which in ("comment-only", "revert"):
            folder = REPO / "bench" / "jit" / "stand-in" / f"slow-left-metamorphic-{which}"
            self.assertEqual(hashlib.sha256((folder / "candidate.patch").read_bytes()).hexdigest(),
                             self._doc(which)["inputs"]["patchSha256"])


if __name__ == "__main__":
    unittest.main()
