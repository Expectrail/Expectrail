"""The reproduction scorer (issue #285): the no-fix candidate, the cases of a live run, and the rate read
from that run's records. Offline: a simulated game and a fake model, no engine and no key."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail.contracts import load_strict
from expectrail.jit.diff_map import diff_map
from expectrail.jit.probes import jit_library
from expectrail.jit.run import generate
from expectrail.repro import bench, score, visibility
from expectrail.repro.__main__ import main
from tests.jit_fixtures import ANSWER, PROFILE, JitGame, model
from tests.test_repro_bench import STUB, Refusals

REPO = Path(__file__).resolve().parents[1]
NO_FIX_TEXT = "--- a/README.md\n+++ b/README.md\n@@ -1,2 +1,3 @@\n # A game\n+<!-- No fix. -->\n It has a robot.\n"
PASS3, FAIL3 = ["pass"] * 3, ["fail"] * 3


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(spec_id, reference=PASS3, killed=("base",), candidate=FAIL3, valid=None):
    """One proposed check and its runs, as the pipeline would record them."""
    kept = reference == PASS3 and bool(killed)
    return {"specId": spec_id, "valid": kept if valid is None else valid, "reference": list(reference),
            "killed": list(killed), "reasons": [] if kept else ["test"], "candidate": list(candidate) if kept else [],
            "outcome": "not-evaluated" if not kept else ("catch" if list(candidate) == FAIL3 else "flaky"
                                                         if "fail" in candidate else "no-catch")}


def jit_record(root: Path, defect: dict, checks=(), *, status="complete", reason=None, spend=0.1, reps=3,
               candidate=None, report=None, base=None) -> dict:
    report_text = (root / (report or defect["report"])).read_text(encoding="utf-8")
    rows = list(checks) if status == "complete" else []
    return {"format": "expectrail.jit-run/v1", "runId": "test-" + defect["id"], "advisory": True, "status": status,
            "reason": reason,
            "inputs": {"patchSha256": sha(root / (candidate or score.NO_FIX)),
                       "reportSha256": hashlib.sha256(report_text.encode("utf-8")).hexdigest(),
                       "basePatchSha256": [sha(root / (base or defect["patch"]))], "profileSha256": "0" * 64,
                       "model": "m", "promptSha256": None},
            "settings": {"reps": reps, "variantLimit": 8, "budgetUsd": 2.0}, "diffMap": None,
            "proposed": [{"spec": {"format": "expectrail.trace-spec/v1", "id": c["specId"], "origin": "AUTO_DIFF",
                                   "expectationRef": {"authority": "model_prior"}},
                          "applies": {}, "probeIds": ["jump-w0-x8"]} for c in rows],
            "probes": [], "variants": [], "validity": rows, "catches": [],
            "counts": {"proposed": len(rows), "valid": sum(c["valid"] for c in rows), "strong": 0, "weak": 0},
            "spend": {"usd": spend, "capUsd": 2.0, "sparkUsd": 0.0, "replayUsd": 0.0, "samUsd": 0.0, "samImages": 0,
                      "replays": 10, "promptTokens": 1, "completionTokens": 1,
                      "prices": {"sparkUsdPerMTokIn": 1.0, "sparkUsdPerMTokOut": 4.0, "runnerUsdPerMinute": 0.008,
                                 "samUsdPerImage": 0.0025, "source": "assumed"}},
            "diagnostics": []}


class TheNoFixCandidate(unittest.TestCase):
    """bench/jit/public/no-fix.patch stands in for a candidate in every case. It must tell the model
    nothing about any defect and change nothing in the game."""

    def setUp(self):
        self.doc = bench.load()

    def test_it_is_one_comment_line_in_the_games_readme_and_fits_the_bench(self):
        self.assertEqual(score.no_fix_problems(self.doc), [])
        text = (REPO / score.NO_FIX).read_text(encoding="utf-8")
        added = [line for line in text.splitlines() if line.startswith("+") and not line.startswith("+++")]
        self.assertEqual(len(added), 1)
        self.assertRegex(added[0], r"^\+<!-- [^<>]+ -->$")
        self.assertEqual(score.NO_FIX_FILE, "README.md")
        self.assertTrue((REPO / "game" / "platformer" / score.NO_FIX_FILE).is_file())
        self.assertFalse([line for line in text.splitlines() if line.startswith("-") and not line.startswith("---")])

    def test_it_applies_to_a_copy_of_the_clean_game(self):
        self.assertIsNone(bench.applies({"patch": score.NO_FIX}))

    @unittest.skipUnless(shutil.which("patch"), "patch is not installed")
    def test_it_applies_after_every_defect_the_way_a_replay_applies_it_and_only_the_readme_changes(self):
        from harness.run import apply_patches

        game = REPO / "game" / "platformer"
        for d in self.doc["defects"]:
            with self.subTest(defect=d["id"]), tempfile.TemporaryDirectory() as tmp:
                bug, both = Path(tmp) / "bug", Path(tmp) / "both"
                for work in (bug, both):
                    shutil.copytree(game, work, ignore=shutil.ignore_patterns(".godot"))
                apply_patches(bug, [REPO / d["patch"]])
                apply_patches(both, [REPO / d["patch"], REPO / score.NO_FIX])
                differ = [p.relative_to(bug).as_posix() for p in sorted(bug.rglob("*"))
                          if p.is_file() and p.read_bytes() != (both / p.relative_to(bug)).read_bytes()]
                self.assertEqual(differ, [score.NO_FIX_FILE])
                self.assertEqual(sorted(p.relative_to(bug).as_posix() for p in bug.rglob("*")),
                                 sorted(p.relative_to(both).as_posix() for p in both.rglob("*")))

    def test_no_claim_names_its_file_so_the_diff_map_keeps_every_probe(self):
        profile = load_strict(PROFILE, "mechanics-profile")
        probes = jit_library(profile["actions"])
        m = diff_map((REPO / score.NO_FIX).read_text(encoding="utf-8"), profile, probes)
        self.assertEqual(m["claims"], [])
        self.assertTrue(m["allProbes"])
        self.assertEqual(len(m["probeIds"]), len(probes))

    @unittest.skipUnless(shutil.which("patch"), "patch is not installed")
    def test_it_has_no_near_miss_of_its_own_so_the_bug_build_is_the_only_one(self):
        from expectrail.jit import dodgy

        found = dodgy.variants(REPO / "game" / "platformer", [REPO / "bugs" / "reported" / "air-jump.patch"],
                               REPO / score.NO_FIX)
        self.assertEqual(found, [])


class Fixture(unittest.TestCase):
    """A small bench in a temporary folder: two defects a signal shows, one the record shows, one nothing shows."""

    IDS = ("sig-one", "sig-two", "cam", "unseen")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="repro-score-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "game" / "platformer" / "player").mkdir(parents=True)
        (self.tmp / "game" / "platformer" / "player" / "player.gd").write_text("a\n")
        (self.tmp / "game" / "platformer" / "README.md").write_text("# A game\nIt has a robot.\n")
        (self.tmp / "bench" / "jit" / "public").mkdir(parents=True)
        (self.tmp / score.NO_FIX).write_text(NO_FIX_TEXT)
        (self.tmp / "bench" / "report.txt").write_text("It is broken.\n")
        (self.tmp / "bench" / "other.txt").write_text("Something else is broken.\n")
        for i, name in enumerate(self.IDS):
            (self.tmp / "bench" / f"{name}.patch").write_text(STUB.replace("+b", f"+b{i}"))
        self.doc = {"format": "expectrail.repro-bench/v1", "description": "test", "game": "game/platformer",
                    "defects": [Refusals.defect(n, f"bench/{n}.patch") for n in self.IDS]}
        self.doc["defects"][0]["tunedOn"] = True
        self.bench_path = self.tmp / "bench" / "defects.json"
        self.bench_path.write_text(json.dumps(self.doc))
        self.assertEqual(bench.problems(self.doc, self.tmp), [])
        self.by_id = {d["id"]: d for d in self.doc["defects"]}
        self.records = self.tmp / "records"
        moved = {"air_jumps": {"probes": 1, "probe": "jump-w0-x8", "clean": 1, "defect": 7}}
        rows = [{"id": "sig-one", "visibility": "signal", "signals": moved, "traceFields": ["player"], "probesChanged": 1},
                {"id": "sig-two", "visibility": "signal", "signals": moved, "traceFields": [], "probesChanged": 1},
                {"id": "cam", "visibility": "trace-only", "signals": {}, "traceFields": ["view"], "probesChanged": 1},
                {"id": "unseen", "visibility": "none", "signals": {}, "traceFields": [], "probesChanged": 0}]
        for r in rows:
            r["patchSha256"] = sha(self.tmp / self.by_id[r["id"]]["patch"])
        seen = {"format": visibility.FORMAT, "benchSha256": sha(self.bench_path), "engine": "simulated",
                "probes": ["jump-w0-x8"], "replaysPerBuild": {"clean": 2, "defect": 1}, "engineRetries": 0,
                "unstable": [], "defects": rows, "totals": visibility.totals(rows)}
        self.assertEqual(visibility.problems(seen), [])
        self.visibility_path = self.tmp / "visibility.json"
        self.visibility_path.write_text(json.dumps(seen))

    def put(self, did: str, checks=(), **kw) -> Path:
        path = self.records / (score.CASE_PREFIX + did) / "jit-run.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(jit_record(self.tmp, self.by_id[did], checks, **kw)))
        load_strict(path, "jit-run")   # the fixture is a record the pipeline could have written
        return path

    def score(self, **kw) -> dict:
        kw.setdefault("visibility_path", self.visibility_path)
        return score.score(self.doc, self.records, root=self.tmp, bench_path=self.bench_path, **kw)

    def row(self, did: str, **kw) -> dict:
        return next(r for r in self.score(**kw)["rows"] if r["id"] == did)


class Reproduced(Fixture):
    def test_a_check_that_passes_clean_and_fails_the_bug_build_three_of_three_twice_over(self):
        self.put("sig-one", [check("jit-a"), check("jit-b", killed=()), check("jit-c", reference=["fail"])])
        r = self.row("sig-one")
        self.assertEqual((r["outcome"], r["reproducing"], r["proposed"], r["kept"]), ("reproduced", ["jit-a"], 3, 1))
        self.assertIsNone(r["missReason"])
        self.assertEqual(r["spendUsd"], 0.1)

    def test_a_check_that_only_fails_on_some_other_near_miss_is_kept_and_reproduces_nothing(self):
        self.put("sig-one", [check("jit-a", killed=("jit:player/player.gd:3:negate",), candidate=PASS3)])
        r = self.row("sig-one")
        self.assertEqual((r["outcome"], r["kept"], r["reproducing"]), ("not-reproduced", 1, []))

    def test_two_of_three_on_the_bug_build_is_not_a_reproduction(self):
        # The pipeline lists "base" under killed only at 3 of 3, so 2 of 3 arrives as a check that killed nothing.
        self.put("sig-one", [check("jit-a", killed=())])
        self.assertEqual(self.row("sig-one")["outcome"], "not-reproduced")

    def test_the_rate_counts_every_defect_of_the_bench_and_the_subsets(self):
        self.put("sig-one", [check("jit-a")], spend=0.25)
        self.put("sig-two", [check("jit-a"), check("jit-b")], spend=2.5)
        self.put("cam", [check("jit-a", killed=())])
        t = self.score()["totals"]
        self.assertEqual((t["defects"], t["reproduced"], t["notReproduced"], t["noResult"]), (4, 2, 1, 1))
        self.assertEqual((t["untuned"], t["reproducedUntuned"]), (3, 1))
        self.assertEqual((t["traceVisible"], t["reproducedTraceVisible"]), (3, 2))
        self.assertEqual(t["keptChecks"], 3)
        self.assertEqual((t["spendUsd"], t["maxSpendUsd"], t["overCap"]), (2.85, 2.5, 1))
        self.assertEqual(t["misses"], {"no-signal": 1})


class Misses(Fixture):
    def test_out_of_budget_is_a_miss_with_that_reason(self):
        self.put("sig-one", status="nothing-generated", reason="OUT_OF_BUDGET: replay base/x#2 needs up to $0.0040")
        r = self.row("sig-one")
        self.assertEqual((r["outcome"], r["missReason"]), ("not-reproduced", "budget"))
        self.assertIn("OUT_OF_BUDGET", r["evidence"])

    def test_a_check_that_fails_the_bug_build_and_then_not_on_the_same_build_is_flaky(self):
        self.put("sig-one", [check("jit-a", candidate=["fail", "pass", "fail"])])
        r = self.row("sig-one")
        self.assertEqual((r["outcome"], r["missReason"], r["reproducing"]), ("not-reproduced", "flaky", []))
        self.assertIn("jit-a", r["evidence"])

    def test_a_check_that_passes_and_then_fails_on_the_clean_game_is_flaky(self):
        self.put("sig-one", [check("jit-a", reference=["pass", "fail"])])
        self.assertEqual(self.row("sig-one")["missReason"], "flaky")

    def test_a_check_that_simply_fails_on_the_clean_game_is_not_called_flaky(self):
        self.put("sig-one", [check("jit-a", reference=["fail"])])
        self.assertEqual(self.row("sig-one")["missReason"], "wrong-predicate")

    def test_the_reason_follows_what_the_library_probes_see(self):
        for did, reason in (("sig-two", "wrong-predicate"), ("cam", "no-signal"), ("unseen", "undetermined")):
            self.put(did, [check("jit-a", killed=()), check("jit-b", reference=["not_exercised"])])
            r = self.row(did)
            self.assertEqual((r["outcome"], r["missReason"]), ("not-reproduced", reason), did)
            self.assertTrue(r["evidence"])

    def test_without_a_visibility_record_a_plain_miss_is_undetermined(self):
        self.put("sig-two", [check("jit-a", killed=())])
        r = self.row("sig-two", visibility_path=None)
        self.assertEqual((r["missReason"], r["visibility"]), ("undetermined", None))
        self.assertIsNone(self.score(visibility_path=None)["visibilitySha256"])

    def test_the_two_reasons_no_record_can_show_are_never_assigned(self):
        for did in self.IDS:
            self.put(did, [check("jit-a", killed=())])
        reasons = {r["missReason"] for r in self.score()["rows"]}
        self.assertFalse(reasons & {"route-never-reaches", "probe-language"})
        self.assertLessEqual(reasons, set(score.ASSIGNED_HERE))


class NoResult(Fixture):
    def assert_no_result(self, did, word):
        r = self.row(did)
        self.assertEqual((r["outcome"], r["reproducing"], r["missReason"]), ("no-result", [], None))
        self.assertIn(word, r["why"])
        return r

    def test_no_record(self):
        self.assert_no_result("sig-one", "no readable record")

    def test_a_record_that_is_not_a_jit_run_record(self):
        path = self.put("sig-one", [check("jit-a")])
        doc = json.loads(path.read_text())
        doc["decision"] = "reproduced"
        path.write_text(json.dumps(doc))
        self.assert_no_result("sig-one", "no readable record")

    def test_a_run_that_generated_nothing_for_another_reason_than_budget(self):
        self.put("sig-one", status="nothing-generated", reason="MODEL_UNAVAILABLE: test")
        r = self.assert_no_result("sig-one", "MODEL_UNAVAILABLE")
        self.assertEqual(r["spendUsd"], 0.1)   # what it spent is still counted

    def test_a_record_for_another_candidate_defect_or_report(self):
        (self.tmp / "bench" / "fix.patch").write_text(STUB.replace("+b", "+fixed"))
        for kw, word in (({"candidate": "bench/fix.patch"}, "another candidate"),
                         ({"base": "bench/sig-two.patch"}, "another defect"),
                         ({"report": "bench/other.txt"}, "another report")):
            self.put("sig-one", [check("jit-a")], **kw)
            self.assert_no_result("sig-one", word)

    def test_a_record_that_ran_each_check_fewer_or_more_times(self):
        for reps in (1, 2, 5):
            self.put("sig-one", [check("jit-a", reference=["pass"] * reps, candidate=["fail"] * reps)], reps=reps)
            self.assert_no_result("sig-one", "3 of 3")

    def test_a_record_whose_valid_flag_its_own_runs_contradict(self):
        for lie in (check("jit-a", reference=["fail"], valid=True), check("jit-a", killed=(), valid=True),
                    check("jit-a", reference=["pass", "pass"], valid=True), check("jit-a", valid=False)):
            self.put("sig-one", [lie])
            r = self.assert_no_result("sig-one", "disagrees with itself")
            self.assertIsNone(r["spendUsd"])

    def test_a_record_with_runs_for_a_check_it_never_proposed_or_the_same_check_twice(self):
        path = self.put("sig-one", [check("jit-a"), check("jit-b")])
        doc = json.loads(path.read_text())
        doc["proposed"] = doc["proposed"][:1]
        path.write_text(json.dumps(doc))
        self.assert_no_result("sig-one", "disagrees with itself")
        self.put("sig-one", [check("jit-a"), check("jit-a")])
        self.assert_no_result("sig-one", "disagrees with itself")

    def test_a_missing_defect_never_raises_the_rate(self):
        self.put("sig-one", [check("jit-a")])
        t = self.score()["totals"]
        self.assertEqual((t["reproduced"], t["defects"], t["noResult"]), (1, 4, 3))


class TheScoreRecord(Fixture):
    def setUp(self):
        super().setUp()
        self.put("sig-one", [check("jit-a")])
        self.put("sig-two", [check("jit-a", killed=())])
        self.put("cam", status="nothing-generated", reason="OUT_OF_BUDGET: x")
        self.record = self.score(source="  run 123\n456 ")

    def test_it_is_written_and_read_back_the_same(self):
        path = score.write(self.record, self.tmp / "out")
        self.assertEqual(score.load(path), self.record)
        self.assertEqual(self.record["source"], "run 123 456")
        self.assertEqual(self.record["visibilitySha256"], sha(self.visibility_path))
        self.assertEqual((self.tmp / "out" / score.PAGE).read_text(), score.render(self.record))

    def test_the_same_records_give_the_same_score(self):
        self.assertEqual(self.score(source="run 123 456"), self.record)

    def test_a_record_that_disagrees_with_itself_is_refused(self):
        def tamper(change):
            doc = copy.deepcopy(self.record)
            change(doc)
            return score.problems(doc)

        self.assertEqual(score.problems(self.record), [])
        rows = {r["id"]: i for i, r in enumerate(self.record["rows"])}
        changes = {
            "a higher rate than the rows": lambda d: d["totals"].update(reproduced=4),
            "reproduced with no check": lambda d: d["rows"][rows["sig-two"]].update(outcome="reproduced", missReason=None,
                                                                                   evidence=None),
            "reproduced with no record": lambda d: d["rows"][rows["unseen"]].update(outcome="reproduced", why=None,
                                                                                    reproducing=["jit-a"], kept=1,
                                                                                    proposed=1),
            "a miss with no reason": lambda d: d["rows"][rows["sig-two"]].update(missReason=None),
            "a reason no record can show": lambda d: d["rows"][rows["sig-two"]].update(missReason="route-never-reaches"),
            "a reason outside the vocabulary": lambda d: d["rows"][rows["sig-two"]].update(missReason="bad-luck"),
            "more reproducing than kept": lambda d: d["rows"][rows["sig-one"]].update(kept=0),
            "a defect twice": lambda d: d["rows"].append(copy.deepcopy(d["rows"][0])),
            "a decision field": lambda d: d.update(decision="accept"),
            "another number of runs": lambda d: d.update(reps=1),
        }
        for name, change in changes.items():
            self.assertTrue(tamper(change), name)
        path = self.tmp / "tampered.json"
        doc = copy.deepcopy(self.record)
        doc["totals"]["reproduced"] = 4
        path.write_text(json.dumps(doc))
        with self.assertRaises(score.ScoreError):
            score.load(path)
        path.write_text('{"format": "expectrail.repro-score/v1", "format": "x"}')
        with self.assertRaises(score.ScoreError):
            score.load(path)

    def test_stale_says_when_the_score_no_longer_describes_the_bench(self):
        self.assertEqual(score.stale(self.record, self.doc, self.tmp, self.bench_path), [])
        (self.tmp / "bench" / "cam.patch").write_text(STUB.replace("+b", "+changed"))
        self.assertEqual(score.stale(self.record, self.doc, self.tmp, self.bench_path),
                         ["cam: the patch changed after it was scored"])
        (self.tmp / score.NO_FIX).write_text(NO_FIX_TEXT.replace("No fix.", "Another line."))
        self.assertIn("the no-fix candidate changed after it was scored",
                      score.stale(self.record, self.doc, self.tmp, self.bench_path))

    def test_the_page_gives_the_rate_the_subsets_and_a_row_per_defect(self):
        text = score.render(self.record)
        self.assertTrue(text.startswith("# Reproduction on the public bench: 1 of 4 (25%)\n"))
        self.assertIn("From run 123 456.", text)
        self.assertIn("no result: 1", text)
        self.assertIn("1 of 3 (33%)", text)              # of the defects the engine's record shows
        self.assertIn("Misses by reason: wrong-predicate 1, budget 1", text)
        for did in self.IDS:
            self.assertIn(f"| `{did}` |", text)
        self.assertEqual(len([line for line in text.splitlines() if line.startswith("| `")]), 4)

    def test_a_visibility_record_for_another_bench_is_refused(self):
        (self.tmp / "bench" / "cam.patch").write_text(STUB.replace("+b", "+changed"))
        with self.assertRaises(score.ScoreError) as caught:
            self.score()
        self.assertIn("visibility record does not describe this bench", str(caught.exception))
        self.visibility_path.write_text("{}")
        with self.assertRaises(score.ScoreError):
            self.score()


class NoFixRefusals(Fixture):
    def test_a_defect_that_changes_the_readme(self):
        (self.tmp / "bench" / "cam.patch").write_text(NO_FIX_TEXT.replace("No fix.", "A defect."))
        found = score.no_fix_problems(self.doc, self.tmp)
        self.assertEqual(len(found), 1)
        self.assertIn("cam: changes the game's README.md", found[0])
        with self.assertRaises(score.ScoreError):
            score.cases(self.doc, self.tmp)
        with self.assertRaises(score.ScoreError):
            self.score()

    def test_a_no_fix_patch_that_is_not_one_comment_line_in_the_readme(self):
        line = "+<!-- No fix. -->"
        for text in (STUB,                                                             # a script, and a real change
                     NO_FIX_TEXT.replace("README.md", "project.godot"),                 # a file the engine loads
                     NO_FIX_TEXT.replace(line, "+Some words."),                         # not a comment
                     NO_FIX_TEXT.replace(line, "+<!-- one --> words <!-- two -->"),     # more than a comment
                     NO_FIX_TEXT.replace(line, line + "\n+<!-- And more. -->"),          # two lines
                     NO_FIX_TEXT.replace(" It has a robot.", "-It has a robot."),        # removes a line
                     NO_FIX_TEXT + STUB,                                                # a second file
                     "not a patch\n"):
            (self.tmp / score.NO_FIX).write_text(text)
            self.assertTrue(score.no_fix_problems(self.doc, self.tmp), text)

    def test_a_missing_or_linked_no_fix_patch(self):
        (self.tmp / score.NO_FIX).unlink()
        self.assertTrue(score.no_fix_problems(self.doc, self.tmp))
        (self.tmp / "elsewhere.patch").write_text(NO_FIX_TEXT)
        (self.tmp / score.NO_FIX).symlink_to(self.tmp / "elsewhere.patch")
        self.assertTrue(score.no_fix_problems(self.doc, self.tmp))


class Cases(unittest.TestCase):
    def setUp(self):
        self.doc = bench.load()
        self.cases = score.cases(self.doc)

    def test_one_case_per_defect_with_the_defect_as_the_bug_and_no_fix_as_the_candidate(self):
        self.assertEqual([c["case"] for c in self.cases], ["repro-" + d["id"] for d in self.doc["defects"]])
        for c, d in zip(self.cases, self.doc["defects"]):
            self.assertEqual(c, {"case": "repro-" + d["id"], "base": d["patch"], "candidate": score.NO_FIX,
                                 "report": d["report"]})
            for k in ("base", "candidate", "report"):
                self.assertTrue((REPO / c[k]).is_file(), c[k])

    def test_case_names_fit_an_artifact_name_and_cannot_be_taken_for_a_first_round(self):
        for c in self.cases:
            self.assertRegex(c["case"], r"^[a-z0-9][a-z0-9-]{0,60}$")
            self.assertFalse(c["case"].endswith("-round1"), c["case"])
            self.assertFalse(c["case"].startswith("known-"))

    def test_the_command_prints_them_and_the_cap_for_a_workflow_step(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["cases", "--github-output"]), 0)
        lines = out.getvalue().splitlines()
        self.assertEqual(json.loads(lines[0].removeprefix("cases=")), self.cases)
        self.assertEqual(lines[1], "budget=2")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["cases"]), 0)
        self.assertEqual(json.loads(out.getvalue()), self.cases)


class OneWholeRun(unittest.TestCase):
    """The pipeline itself, on the simulated game with a fake model, given a case exactly as a live run
    would get it; then the scorer on the record it wrote."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="repro-run-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        doc = bench.load()
        self.doc = dict(doc, defects=[d for d in doc["defects"] if d["id"] in ("air-jump", "slow-left")])
        self.case = next(c for c in score.cases(doc) if c["case"] == "repro-air-jump")

    def run_case(self, answer=ANSWER, runner=None):
        intent, _transport = model(answer)
        out = self.tmp / "records" / self.case["case"]
        report = (REPO / self.case["report"]).read_text(encoding="utf-8", errors="replace")   # as the CLI reads it
        return generate(PROFILE, report, REPO / self.case["candidate"], [REPO / self.case["base"]], out,
                        runner=runner or JitGame(), intent=intent, variants_fn=lambda candidate, base: [])

    def test_the_air_jump_bug_is_reproduced_by_the_check_that_sees_it(self):
        doc = self.run_case()
        self.assertEqual(doc["status"], "complete", doc["reason"])
        self.assertTrue(doc["diffMap"]["allProbes"])
        self.assertEqual([v["kind"] for v in doc["variants"]], ["base"])
        record = score.score(self.doc, self.tmp / "records")
        rows = {r["id"]: r for r in record["rows"]}
        self.assertEqual((rows["air-jump"]["outcome"], rows["air-jump"]["reproducing"]),
                         ("reproduced", ["jit-no-extra-air-jumps"]))
        self.assertEqual((rows["air-jump"]["proposed"], rows["air-jump"]["kept"]), (3, 1))
        self.assertEqual(rows["slow-left"]["outcome"], "no-result")
        self.assertEqual((record["totals"]["reproduced"], record["totals"]["defects"]), (1, 2))

    def test_checks_that_see_nothing_reproduce_nothing(self):
        answer = {"candidates": [c for c in ANSWER["candidates"] if c["id"] != "no-extra-air-jumps"]}
        self.run_case(answer)
        row = score.score(self.doc, self.tmp / "records")["rows"][0]
        self.assertEqual((row["outcome"], row["kept"], row["reproducing"]), ("not-reproduced", 0, []))

    def test_the_score_command_writes_the_record_and_the_page_and_score_render_reads_it_back(self):
        self.run_case()
        bench_path = self.tmp / "defects.json"
        bench_path.write_text(json.dumps(self.doc))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["score", "--bench", str(bench_path), "--records", str(self.tmp / "records"),
                         "--out", str(self.tmp / "score"), "--no-visibility", "--source", "a test"])
        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(json.loads(out.getvalue())["reproduced"], 1)
        record = score.load(self.tmp / "score" / score.NAME)
        self.assertEqual(record["source"], "a test")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["score-render", str(self.tmp / "score" / score.NAME), "--bench", str(bench_path)]), 0)
        self.assertEqual(out.getvalue(), score.render(record))
        self.assertEqual(out.getvalue(), (self.tmp / "score" / score.PAGE).read_text())

    def test_the_committed_visibility_record_is_refused_for_a_bench_it_was_not_made_for(self):
        bench_path = self.tmp / "defects.json"
        bench_path.write_text(json.dumps(self.doc))
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = main(["score", "--bench", str(bench_path), "--records", str(self.tmp / "records"),
                         "--out", str(self.tmp / "score")])
        self.assertEqual(code, 1)
        self.assertIn("does not describe this bench", err.getvalue())
        self.assertFalse((self.tmp / "score").exists())


class TheContract(unittest.TestCase):
    def test_the_example_is_a_score_the_reader_accepts(self):
        example = score.load(REPO / "contracts" / "examples" / "repro-score.json")
        self.assertEqual(example["format"], score.FORMAT)
        self.assertEqual({r["outcome"] for r in example["rows"]}, set(score.OUTCOMES))
        self.assertIn("An example", example["source"])

    def test_the_schema_has_no_decision_and_fixes_three_runs_and_the_cap(self):
        schema = json.loads(score.SCHEMA.read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertNotIn("decision", schema["properties"])
        self.assertEqual(schema["properties"]["reps"], {"const": score.REPS})
        self.assertEqual(schema["properties"]["capUsd"], {"const": score.CAP_USD})
        self.assertEqual(tuple(schema["$defs"]["reason"]["enum"]), score.MISS_REASONS)


class NoRateYet(unittest.TestCase):
    """No live run has been made on the bench. Until one is, no page may carry a rate."""

    def test_no_score_record_is_committed_and_the_pages_say_none_was_measured(self):
        self.assertEqual(sorted(p.name for p in (REPO / "bench" / "jit" / "public").glob("*score*")), [])
        page = (REPO / "bench" / "jit" / "public" / "README.md").read_text(encoding="utf-8")
        self.assertIn("No reproduction rate has been measured", page)
        self.assertIn("No reproduction rate has been measured", (REPO / "docs" / "jit.md").read_text(encoding="utf-8"))
        self.assertIsNone(re.search(r"reproduc\w+ (rate )?(is|was|of) \d+ ?%", page))


class Workflow(unittest.TestCase):
    """jit.yml's repro mode: the bench's cases through the same jobs as any live change, then the scorer."""

    def setUp(self):
        import yaml

        self.text = (REPO / ".github/workflows/jit.yml").read_text(encoding="utf-8")
        self.jobs = yaml.safe_load(self.text)["jobs"]
        self.plan = self.text[self.text.index("  plan:"):self.text.index("  measure:")]

    def test_repro_mode_runs_only_from_main_and_takes_its_cases_from_the_bench(self):
        block = self.plan[self.plan.index('"$MODE" == "repro"'):]
        block = block[:block.index("exit 0")]
        self.assertIn('[[ "$GITHUB_REF" == "refs/heads/main" ]]', block)
        self.assertIn("python -m expectrail.repro check", block)
        self.assertIn('python -m expectrail.repro cases --github-output >> "$GITHUB_OUTPUT"', block)
        for name in ("CASE", "BASE", "CANDIDATE", "REPORT", "BUDGET"):   # nothing typed at dispatch reaches it
            self.assertNotIn(f"${name}", block)
        self.assertIn("repro", self.text[self.text.index("options:"):self.text.index("default: 'rehearsal'")])

    def test_the_score_job_reads_only_final_records_and_holds_no_secret(self):
        import yaml

        job = self.jobs["repro-score"]
        self.assertIn("inputs.mode == 'repro'", job["if"])
        self.assertNotIn("environment", job)
        dumped = yaml.safe_dump(job)
        self.assertNotIn("secrets.", dumped)
        self.assertIn("jit-repro-*", dumped)
        self.assertIn("-round1", dumped)
        self.assertIn("python -m expectrail.repro score --records runs/repro --out runs/repro-score", dumped)
        self.assertIn("inputs.mode == 'bench'", self.jobs["score"]["if"])   # the known-bugs score stays its own

    def test_adding_the_mode_added_no_secret_environment_or_permission(self):
        self.assertEqual(sorted(n for n, j in self.jobs.items() if "environment" in j), ["propose", "revise"])
        for name, job in self.jobs.items():
            self.assertNotIn("permissions", job, name)
        self.assertNotIn("pull_request_target", self.text)
        self.assertNotIn("id-token", self.text)
        self.assertEqual(self.text.count("permissions:"), 1)
        self.assertIn("permissions:\n  contents: read\n", self.text)


if __name__ == "__main__":
    unittest.main()
