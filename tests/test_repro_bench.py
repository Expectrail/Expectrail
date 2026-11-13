"""The public reproduction bench (issue #285): its defects, its strict reader, and the visibility
measurement, on a simulated game. Nothing here calls a model or starts the engine."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail.contracts import load_strict
from expectrail.jit.probes import jit_library
from expectrail.repro import bench, visibility
from expectrail.repro.__main__ import main
from tests.test_discovery import PROFILE, FakeGame

REPO = Path(__file__).resolve().parents[1]
PUBLIC = REPO / "bench" / "jit" / "public"
STUB = "--- a/player/player.gd\n+++ b/player/player.gd\n@@ -1,1 +1,1 @@\n-a\n+b\n"


def tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and ".godot" not in p.parts:
            h.update(p.relative_to(root).as_posix().encode() + b"\0" + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


class TheBench(unittest.TestCase):
    def setUp(self):
        self.doc = bench.load()

    def test_at_least_twenty_public_defects_across_the_families_each_with_a_patch_and_a_report(self):
        defects = self.doc["defects"]
        self.assertGreaterEqual(len(defects), 20)
        self.assertGreaterEqual(len(bench.families(self.doc)), 8)
        for d in defects:
            self.assertTrue((REPO / d["patch"]).is_file(), d["patch"])
            report = (REPO / d["report"]).read_text(encoding="utf-8").strip()
            self.assertTrue(report, d["report"])
            self.assertNotIn("\n", report, f"{d['id']}: a report is one paragraph in a player's words")

    def test_the_four_reported_bugs_are_in_it_from_their_own_files_and_marked_tuned_on(self):
        reported = {d["id"]: d for d in self.doc["defects"] if d["origin"] == "reported"}
        self.assertEqual(sorted(reported), ["air-jump", "body-flip", "enemy-ledge", "gun-cooldown"])
        for did, d in reported.items():
            self.assertEqual(d["patch"], f"bugs/reported/{did}.patch")
            self.assertEqual(d["report"], f"bench/jit/known/{did}/report.txt")
            self.assertTrue(d["tunedOn"])
        self.assertFalse(any(d["tunedOn"] for d in self.doc["defects"] if d["origin"] != "reported"))

    def test_no_defect_or_report_comes_from_held_out_material(self):
        for d in self.doc["defects"]:
            for path in (d["patch"], d["report"]):
                self.assertIsNone(bench.held_out_name(path), path)   # the reader's rule, the only copy of it
                self.assertFalse(any((REPO / part).is_symlink() for part in Path(path).parents), path)

    def test_the_written_defects_live_in_their_own_folder_and_nothing_else_is_there(self):
        written = {d["id"] for d in self.doc["defects"] if d["origin"] == "written-for-bench"}
        folders = {p.name for p in PUBLIC.iterdir() if p.is_dir()}
        self.assertEqual(folders, written)
        for did in written:
            self.assertEqual(sorted(p.name for p in (PUBLIC / did).iterdir()), ["defect.patch", "report.txt"])

    def test_every_patch_applies_to_a_copy_of_the_game_and_the_game_is_untouched(self):
        game = REPO / "game" / "platformer"
        before = tree_digest(game)
        for d in self.doc["defects"]:
            self.assertIsNone(bench.applies(d), d["id"])
        self.assertEqual(tree_digest(game), before)

    def test_a_patch_that_does_not_apply_is_reported_with_the_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "game" / "platformer" / "player").mkdir(parents=True)
            (root / "game" / "platformer" / "player" / "player.gd").write_text("something else\n")
            (root / "bench").mkdir()
            (root / "bench" / "x.patch").write_text(STUB)
            why = bench.applies({"patch": "bench/x.patch"}, root=root)
            self.assertIsInstance(why, str)
            self.assertIn("patch does not apply", why)

    def test_the_example_is_a_valid_bench(self):
        example = bench.load(REPO / "contracts" / "examples" / "repro-bench.json")
        self.assertEqual(example["format"], "expectrail.repro-bench/v1")

    def test_check_command_reads_the_bench_and_applies_every_patch(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["check"]), 0)
        self.assertEqual(json.loads(out.getvalue())["apply"], len(self.doc["defects"]))


class Refusals(unittest.TestCase):
    """A bench file is data: anything it names outside the public folders, or twice, is refused."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="repro-bench-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "game" / "platformer" / "player").mkdir(parents=True)
        (self.tmp / "game" / "platformer" / "player" / "player.gd").write_text("a\n")
        (self.tmp / "bench").mkdir()
        (self.tmp / "bugs" / "fresh").mkdir(parents=True)
        (self.tmp / "bench" / "one.patch").write_text(STUB)
        (self.tmp / "bench" / "two.patch").write_text(STUB.replace("+b", "+c"))
        (self.tmp / "bench" / "report.txt").write_text("The robot does a thing.\n")
        (self.tmp / "bugs" / "fresh" / "x.patch").write_text(STUB.replace("+b", "+d"))
        self.doc = {"format": "expectrail.repro-bench/v1", "description": "test", "game": "game/platformer",
                    "defects": [self.defect("one", "bench/one.patch"), self.defect("two", "bench/two.patch")]}

    @staticmethod
    def defect(did, patch, report="bench/report.txt", **kw):
        return {"id": did, "family": "movement-input", "patch": patch, "report": report, "origin": "written-for-bench",
                "authorExpects": "both", "tunedOn": False, **kw}

    def problems(self):
        return bench.problems(self.doc, self.tmp)

    def test_the_fixture_is_clean(self):
        self.assertEqual(self.problems(), [])

    def test_an_id_listed_twice(self):
        self.doc["defects"][1]["id"] = "one"
        self.assertIn("repro-bench: one: listed twice", self.problems())

    def test_the_same_patch_under_two_ids(self):
        self.doc["defects"][1]["patch"] = "bench/one.patch"
        self.assertIn("repro-bench: two: the same patch as one", self.problems())

    def test_paths_that_leave_the_public_folders(self):
        for path in ("../outside.patch", "bench/../../x.patch", "/etc/passwd", "game/platformer/player/player.gd",
                     "bench/./one.patch", "bench\\one.patch", "bugs/../bench/one.patch"):
            doc = copy.deepcopy(self.doc)
            doc["defects"][0]["patch"] = path
            found = bench.problems(doc, self.tmp)
            self.assertTrue(found and "defects/0/patch" in found[0], (path, found))

    def test_a_path_with_a_part_that_names_held_out_material_whatever_its_case(self):
        """Every one of these files exists, so only the name rule can refuse it."""
        for path in ("bugs/fresh/x.patch", "bench/freshly/x.patch", "bench/FRESH/x.patch", "bench/Fresh-set/x.patch",
                     "bench/x/fresh/x.patch", "bench/jit/blind-9/x.patch", "bench/Blind/x.patch",
                     "bench/heldout/x.patch", "bench/held-out/x.patch", "bench/HeldOut-set/x.patch",
                     "bench/fresh.patch"):
            target = self.tmp / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(STUB.replace("+b", "+" + path))
            for field in ("patch", "report"):
                doc = copy.deepcopy(self.doc)
                doc["defects"][0][field] = path
                found = bench.problems(doc, self.tmp)
                self.assertEqual(len(found), 1, (path, found))
                self.assertIn("names held-out material", found[0], path)

    def test_the_name_rule_is_the_readers_and_the_committed_bench_passes_it(self):
        self.assertIsNone(bench.held_out_name("bench/jit/known/air-jump/report.txt"))
        self.assertIsNone(bench.held_out_name("bugs/reported/refresh-rate.patch"))
        for d in bench.load()["defects"]:
            self.assertIsNone(bench.held_out_name(d["patch"]))
            self.assertIsNone(bench.held_out_name(d["report"]))

    def test_a_linked_folder_on_the_way_is_refused_wherever_it_leads(self):
        """The merge guard's cases on #306: the text of the path is innocent, the folder it goes through is a link."""
        fresh_set = self.tmp / "fresh-9"
        private = self.tmp / "Expectrail-heldout"
        plain = self.tmp / "elsewhere"
        outside = Path(tempfile.mkdtemp(prefix="repro-outside-"))
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        for folder in (fresh_set, private, plain, outside):
            folder.mkdir(exist_ok=True)
            (folder / "p.patch").write_text(STUB.replace("+b", "+" + folder.name))
            (folder / "r.txt").write_text("A report that must not be read.\n")
        (self.tmp / "bench" / "linked").symlink_to(fresh_set, target_is_directory=True)
        (self.tmp / "bench" / "notes").symlink_to(private, target_is_directory=True)
        (self.tmp / "bench" / "same-repo").symlink_to(plain, target_is_directory=True)
        (self.tmp / "bench" / "away").symlink_to(outside, target_is_directory=True)
        cases = (("patch", "bench/linked/p.patch", "leads to 'fresh-9', which names held-out material"),
                 ("report", "bench/notes/r.txt", "leads to 'Expectrail-heldout', which names held-out material"),
                 ("patch", "bench/same-repo/p.patch", "reached through a link"),
                 ("report", "bench/same-repo/r.txt", "reached through a link"),
                 ("patch", "bench/away/p.patch", "outside the repository"))
        for field, path, why in cases:
            doc = copy.deepcopy(self.doc)
            doc["defects"][0][field] = path
            found = bench.problems(doc, self.tmp)
            self.assertEqual(len(found), 1, (path, found))
            self.assertIn(why, found[0], path)

    def test_a_refused_file_is_never_opened(self):
        """Refusal comes before reading: a linked report that is far too large is refused for the link."""
        big = self.tmp / "elsewhere"
        big.mkdir()
        (big / "r.txt").write_text("x" * 10000)
        (self.tmp / "bench" / "via").symlink_to(big, target_is_directory=True)
        self.doc["defects"][0]["report"] = "bench/via/r.txt"
        found = self.problems()
        self.assertEqual(len(found), 1)
        self.assertNotIn("the report is empty or over", found[0])

    def test_a_link_out_of_the_repository(self):
        outside = Path(tempfile.mkdtemp(prefix="repro-outside-"))
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        (outside / "secret.patch").write_text(STUB.replace("+b", "+z"))
        (self.tmp / "bench" / "link.patch").symlink_to(outside / "secret.patch")
        self.doc["defects"][0]["patch"] = "bench/link.patch"
        self.assertIn("repro-bench: one: bench/link.patch: outside the repository", self.problems())

    def test_a_link_inside_the_repository_is_still_not_a_file(self):
        (self.tmp / "bench" / "link.patch").symlink_to(self.tmp / "bench" / "one.patch")
        self.doc["defects"][0]["patch"] = "bench/link.patch"
        self.assertIn("repro-bench: one: bench/link.patch: reached through a link, or not written as its own path",
                      self.problems())

    def test_a_missing_file(self):
        self.doc["defects"][0]["report"] = "bench/none.txt"
        self.assertIn("repro-bench: one: bench/none.txt: not a file in the repository", self.problems())

    def test_an_empty_report(self):
        (self.tmp / "bench" / "report.txt").write_text(" \n")
        self.assertTrue(any("the report is empty" in p for p in self.problems()))

    def test_a_patch_that_names_a_file_the_game_does_not_have_or_changes_nothing(self):
        (self.tmp / "bench" / "one.patch").write_text(STUB.replace("player/player.gd", "player/other.gd"))
        self.assertTrue(any("which is not a file of the game" in p for p in self.problems()))
        (self.tmp / "bench" / "one.patch").write_text("not a patch\n")
        self.assertTrue(any("repro-bench: one: the patch cannot be read" in p for p in self.problems()))
        (self.tmp / "bench" / "one.patch").write_text("--- a/player/player.gd\n+++ b/player/player.gd\n@@ -1,1 +1,1 @@\n a\n")
        self.assertIn("repro-bench: one: the patch changes nothing", self.problems())

    def test_unknown_family_extra_field_and_wrong_format(self):
        for change in ({"family": "other"}, {"approval": "sean"}, {"authorExpects": "nowhere"}):
            doc = copy.deepcopy(self.doc)
            doc["defects"][0].update(change)
            self.assertTrue(bench.problems(doc, self.tmp), change)
        self.doc["format"] = "expectrail.repro-bench/v0"
        self.assertTrue(self.problems())

    def test_load_refuses_duplicate_keys_and_reports_every_problem(self):
        path = self.tmp / "bench" / "defects.json"
        path.write_text('{"format": "expectrail.repro-bench/v1", "format": "expectrail.repro-bench/v1"}')
        with self.assertRaises(bench.BenchError):
            bench.load(path, self.tmp)
        self.doc["defects"][1]["id"] = "one"
        path.write_text(json.dumps(self.doc))
        with self.assertRaisesRegex(bench.BenchError, "listed twice"):
            bench.load(path, self.tmp)


class Game(FakeGame):
    """FakeGame with a camera in its record, and four more patches recognised by file name:
    camera-shift (the view moves, no signal does), no-change, crash, and script-error (the engine log says so).
    ``jitter`` makes the view of one probe differ between the first clean replay and the rest."""

    def __init__(self, jitter: str | None = None):
        super().__init__()
        self.jitter, self.clean_calls = jitter, {}

    def __call__(self, route_path, run_dir, patches=()):
        stems = {Path(p).stem for p in patches}
        route = json.loads(Path(route_path).read_text())
        super().__call__(route_path, run_dir, patches=[p for p in patches if Path(p).stem not in
                                                        ("camera-shift", "no-change", "script-error")])
        run_dir = Path(run_dir)
        trace = json.loads((run_dir / "trace.json").read_text())
        n = self.clean_calls[route["name"]] = self.clean_calls.get(route["name"], 0) + (0 if stems else 1)
        for row in trace["rows"]:
            shift = 50.0 if "camera-shift" in stems else 0.0
            if not stems and route["name"] == self.jitter and n == 1:
                shift = 1.0
            row["view"] = [1.0, 0.0, 0.0, 1.0, shift, 0.0]
        (run_dir / "trace.json").write_text(json.dumps(trace))
        (run_dir / "godot.log").write_text("SCRIPT ERROR: Parse Error: nope\n" if "script-error" in stems else "ok\n")


class Visibility(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="repro-vis-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "game" / "platformer" / "player").mkdir(parents=True)
        (self.tmp / "game" / "platformer" / "player" / "player.gd").write_text("a\n")
        (self.tmp / "bench").mkdir()
        (self.tmp / "bench" / "report.txt").write_text("It is broken.\n")
        self.names = ["air-jump", "gun-cooldown", "camera-shift", "no-change", "crash", "script-error"]
        for i, name in enumerate(self.names):
            (self.tmp / "bench" / f"{name}.patch").write_text(STUB.replace("+b", f"+b{i}"))
        self.doc = {"format": "expectrail.repro-bench/v1", "description": "test", "game": "game/platformer",
                    "defects": [Refusals.defect(n, f"bench/{n}.patch") for n in self.names]}
        self.bench_path = self.tmp / "bench" / "defects.json"
        self.bench_path.write_text(json.dumps(self.doc))
        self.assertEqual(bench.problems(self.doc, self.tmp), [])
        self.profile = load_strict(PROFILE, "mechanics-profile")
        self.probes = [p for p in jit_library(self.profile["actions"])
                       if p["id"] in ("jump-w0-x8", "jump-w0-x2", "shoot-right-every12", "hold-right")]

    def measure(self, game=None, **kw):
        return visibility.measure(self.doc, self.profile, self.probes, self.tmp / "out", runner=game or Game(),
                                  root=self.tmp, bench_path=self.bench_path, **kw)

    def test_each_defect_is_sorted_by_what_it_changes_in_the_record(self):
        record = self.measure()
        rows = {r["id"]: r for r in record["defects"]}
        self.assertEqual({k: v["visibility"] for k, v in rows.items()},
                         {"air-jump": "signal", "gun-cooldown": "signal", "camera-shift": "trace-only",
                          "no-change": "none", "crash": "error", "script-error": "error"})
        self.assertEqual(record["totals"], {"defects": 6, "signal": 2, "trace-only": 1, "none": 1, "error": 2})
        air = rows["air-jump"]["signals"]["air_jumps"]
        self.assertEqual((air["probe"], air["clean"], air["probes"]), ("jump-w0-x8", 1, 1))
        self.assertGreater(air["defect"], 1)
        self.assertEqual(rows["gun-cooldown"]["signals"]["projectile_count"]["probe"], "shoot-right-every12")
        self.assertEqual(rows["camera-shift"]["traceFields"], ["view"])
        self.assertEqual(rows["camera-shift"]["probesChanged"], len(self.probes))
        self.assertEqual((rows["no-change"]["signals"], rows["no-change"]["traceFields"], rows["no-change"]["probesChanged"]),
                         ({}, [], 0))
        self.assertIn("could not be replayed in 3 attempts: godot exited", rows["crash"]["error"])
        self.assertEqual(record["engineRetries"], 0)   # counted only for builds that were measured in the end
        self.assertIn("script error", rows["script-error"]["error"])
        self.assertEqual(record["unstable"], [])
        self.assertEqual(visibility.load(self.tmp / "out" / visibility.NAME), record)

    def test_an_engine_that_fails_once_is_replayed_again_and_the_retry_is_counted(self):
        class CrashesOnce(Game):
            failed = False

            def __call__(self, route_path, run_dir, patches=()):
                if not patches and "hold-right" in str(route_path) and not self.failed:
                    self.failed = True
                    raise SystemExit("godot failed (-11); see godot.log")   # what harness.run does
                return super().__call__(route_path, run_dir, patches=patches)

        record = self.measure(CrashesOnce(), only=["no-change", "air-jump"])
        self.assertEqual(record["engineRetries"], 1)
        self.assertEqual([r["visibility"] for r in record["defects"]], ["signal", "none"])
        self.assertIn("Replays made again after the engine failed: 1.", visibility.render(record))

    def test_the_same_measurement_twice_gives_the_same_record(self):
        self.assertEqual(self.measure(), self.measure())

    def test_what_differs_between_two_clean_replays_is_unstable_and_counts_for_no_defect(self):
        record = self.measure(Game(jitter="hold-right"))
        self.assertEqual(record["unstable"], [{"probe": "hold-right", "fields": ["view"], "signals": []}])
        rows = {r["id"]: r for r in record["defects"]}
        self.assertEqual(rows["camera-shift"]["probesChanged"], len(self.probes) - 1)
        self.assertEqual(rows["no-change"]["visibility"], "none")

    def test_only_measures_the_named_defects(self):
        record = self.measure(only=["no-change"])
        self.assertEqual([r["id"] for r in record["defects"]], ["no-change"])

    def test_a_clean_game_that_cannot_be_replayed_gives_no_record(self):
        def broken(route_path, run_dir, patches=()):
            raise RuntimeError("no engine")
        with self.assertRaisesRegex(visibility.VisibilityError, "the clean game could not be replayed"):
            self.measure(broken)
        self.assertFalse((self.tmp / "out" / visibility.NAME).exists())

    def test_a_record_that_disagrees_with_itself_is_refused(self):
        record = self.measure()
        changes = {
            "totals": lambda r: r["totals"].update(signal=6),
            "visibility raised": lambda r: r["defects"][3].update(visibility="signal"),
            "visibility lowered": lambda r: r["defects"][0].update(visibility="none"),
            "error with no reason": lambda r: r["defects"][4].pop("error"),
            "reason on a measured row": lambda r: r["defects"][0].update(error="x"),
            "no probe changed": lambda r: r["defects"][0].update(probesChanged=0),
            "a signal that did not move": lambda r: r["defects"][0]["signals"]["air_jumps"].update(defect=1),
            "a signal the trace does not have": lambda r: r["defects"][3].update(
                visibility="signal", probesChanged=1,
                signals={"made_up_signal": {"probes": 1, "probe": "hold-right", "clean": 0, "defect": 1}}),
            "an unknown probe": lambda r: r["defects"][0]["signals"]["air_jumps"].update(probe="other"),
            "a defect twice": lambda r: r["defects"].append(copy.deepcopy(r["defects"][0])),
            "an extra field": lambda r: r.update(reproductionRate=1.0),
            "one clean replay": lambda r: r["replaysPerBuild"].update(clean=1),
        }
        for name, change in changes.items():
            doc = copy.deepcopy(record)
            change(doc)
            self.assertTrue(visibility.problems(doc), name)
            path = self.tmp / "tampered.json"
            path.write_text(json.dumps(doc))
            with self.assertRaises(visibility.VisibilityError, msg=name):
                visibility.load(path)

    def test_stale_says_when_the_record_no_longer_describes_the_bench(self):
        record = self.measure()
        self.assertEqual(visibility.stale(record, self.doc, self.tmp, self.bench_path), [])
        (self.tmp / "bench" / "no-change.patch").write_text(STUB.replace("+b", "+changed"))
        self.assertEqual(visibility.stale(record, self.doc, self.tmp, self.bench_path),
                         ["no-change: the patch changed after it was measured"])
        fewer = dict(self.doc, defects=self.doc["defects"][:-1] + [Refusals.defect("new-one", "bench/crash.patch")])
        found = visibility.stale(record, fewer, self.tmp, self.bench_path)
        self.assertIn("new-one: not measured", found)
        self.assertIn("script-error: measured, and no longer in the bench", found)

    def test_stale_when_only_the_bench_file_changed(self):
        record = self.measure()
        self.bench_path.write_text(json.dumps(self.doc, indent=2))
        self.assertEqual(visibility.stale(record, self.doc, self.tmp, self.bench_path),
                         ["the bench file changed after it was measured"])

    def test_render_has_a_row_per_defect_and_the_totals_and_claims_no_rate(self):
        text = visibility.render(self.measure(Game(jitter="hold-right")), self.doc)
        for name in self.names:
            self.assertIn(f"| `{name}` |", text)
        self.assertIn("A signal moves: 2.", text)
        self.assertIn("Could not be replayed: 2.", text)
        self.assertIn("Unstable between two replays of the clean game", text)
        self.assertNotIn("reproduc", text.lower())


class NoModelNoKey(unittest.TestCase):
    def test_the_package_never_imports_the_model_code_or_reads_a_key(self):
        for path in sorted((REPO / "expectrail" / "repro").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for word in ("intent", "MODEL_API_KEY", "os.environ", "urllib", "requests", "http"):
                self.assertNotIn(word, text.replace("https://", ""), f"{path.name}: {word}")


class TheRecordedMeasurement(unittest.TestCase):
    """bench/jit/public/visibility.json is a recorded run; these hold it to the bench and to the page."""

    def setUp(self):
        self.doc = bench.load()
        self.record = visibility.load()

    def test_it_covers_exactly_the_bench_as_it_is_now(self):
        self.assertEqual(visibility.stale(self.record, self.doc), [])
        self.assertEqual(self.record["totals"]["error"], 0)

    def test_it_used_every_probe_generated_checks_may_use(self):
        profile = load_strict(PROFILE, "mechanics-profile")
        self.assertEqual(self.record["probes"], [p["id"] for p in jit_library(profile["actions"])])

    def test_the_page_shows_the_record_as_rendered_and_nothing_else(self):
        page = (PUBLIC / "README.md").read_text(encoding="utf-8")
        start, end = "<!-- visibility:start -->\n", "<!-- visibility:end -->\n"
        self.assertIn(start, page)
        shown = page.split(start, 1)[1].split(end, 1)[0]
        self.assertEqual(shown, visibility.render(self.record, self.doc))

    def test_the_page_and_the_docs_say_this_is_not_a_reproduction_rate(self):
        page = (PUBLIC / "README.md").read_text(encoding="utf-8")
        # Since the baseline run of November 13 the page carries a rate; the visibility table still says
        # it is not one.
        self.assertIn("It is what the library probes can see, not a rate.", page)
        self.assertIn("bench/jit/public", (REPO / "docs" / "jit.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
