"""expectrail.blind_set: the blind-manifest/v1 reader, writer and validator (#742).

Every set here is synthetic, written by these tests: a valid set at the minimum counts of #282 section 3,
and copies of it that each break one rule. No real blind set is read."""
import difflib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from expectrail import blind_set, contracts

EXAMPLE = Path(__file__).resolve().parent.parent / "contracts" / "examples" / "blind-manifest.v1.json"
REGISTRATION_EXAMPLE = EXAMPLE.with_name("blind-registration.v2.json")
PROJECTS = ("alpha", "beta", "gamma")
SECRET = "THE-PLAYER-SINKS-SECRET-WORDS"


def _diff(path: str, old: str, new: str) -> str:
    lines = difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}")
    return "".join(lines)


def _text(name: str, value: str) -> str:
    return f"# {name}\nfirst = 0\nvalue = {value}\nlast = 9\n"


class SyntheticSet:
    """A set that meets every minimum: 15 defects (10 with two correct fixes), 30 wrong fixes,
    20 correct fixes and 10 changes that are not fixes, over three projects."""

    def __init__(self, root: Path):
        self.root = root
        self.set = root / "set"
        self.projects = {p: root / "projects" / p for p in PROJECTS}
        for folder in self.projects.values():
            folder.mkdir(parents=True)
        self.set.mkdir()
        entries = []
        kind = 0
        for n in range(15):
            eid, project = f"e{n:02d}", PROJECTS[n % 3]
            name = f"{eid}.txt"
            for folder in self.projects.values():
                (folder / name).write_text(_text(name, "1"), encoding="utf-8")
            self._write(f"{eid}/defect.patch", _diff(name, _text(name, "1"), _text(name, "2")))
            self._write(f"{eid}/defect.mp4", "recording")
            cands = []
            for w in range(2):
                cid = f"wrong-{w}"
                self._write(f"{eid}/{cid}.patch", _diff(name, _text(name, "2"), _text(name, f"2  # {cid}")))
                cands.append({"id": cid, "truth": "wrong", "wrongFixKind": blind_set.WRONG_FIX_KINDS[kind % 5],
                              "patch": f"{eid}/{cid}.patch"})
                kind += 1
            if n < 10:
                for c, style in enumerate(("minimal", "restructures")):
                    cid = f"correct-{c}"
                    self._write(f"{eid}/{cid}.patch", _diff(name, _text(name, "2"), _text(name, f"1{'0' * c}")))
                    cands.append({"id": cid, "truth": "correct", "style": style, "patch": f"{eid}/{cid}.patch",
                                  "confirmedBy": "second person"})
            entries.append({
                "id": eid, "project": project,
                "description": f"{SECRET} {n}", "howItShouldBehave": f"{SECRET} behaves {n}",
                "family": blind_set.FAMILIES[n % 10], "whereItShows": "screen-only" if n < 5 else "trace-only",
                "difficulty": "medium", "exercised": True, "defectPatch": f"{eid}/defect.patch",
                "reproduction": {"steps": ["play it"], "recording": f"{eid}/defect.mp4"}, "candidates": cands})
        for n in range(10):
            eid, project = f"n{n:02d}", PROJECTS[n % 3]
            name = f"{eid}.txt"
            for folder in self.projects.values():
                (folder / name).write_text(_text(name, "5"), encoding="utf-8")
            self._write(f"{eid}/change.patch", _diff(name, _text(name, "5"), _text(name, "5  # tidy")))
            kind_name = blind_set.NOT_A_FIX_KINDS[n % 6]
            expected = ("not-accept" if kind_name == "intentional-without-contract" else "accept")
            entries.append({"id": eid, "project": project, "description": f"{SECRET} change {n}",
                            "notAFixKind": kind_name, "expectedVerdict": expected, "exercised": True,
                            "patch": f"{eid}/change.patch", "whyHarmless": "only a comment"})
        self.doc = {"format": blind_set.FORMAT, "name": "synthetic",
                    "projects": {p: {"source": "synthetic", "commit": "0" * 40} for p in PROJECTS},
                    "entries": entries, "exclusions": [], "sealedAt": None, "sha256": None,
                    "declaredCounts": {}}
        self.doc["declaredCounts"] = blind_set.counts(self.doc)
        self.save()

    def _write(self, rel: str, text: str) -> None:
        path = self.set / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def save(self, doc=None) -> Path:
        path = self.set / "manifest.json"
        path.write_text(json.dumps(self.doc if doc is None else doc, indent=1), encoding="utf-8")
        return path

    def recount(self) -> None:
        self.doc["declaredCounts"] = blind_set.counts(self.doc)

    def entry(self, eid: str) -> dict:
        return next(e for e in self.doc["entries"] if e["id"] == eid)

    def validate(self, apply=True):
        return blind_set.validate(self.save(), self.projects, apply=apply)


class BlindSetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = SyntheticSet(Path(self.tmp.name))

    def run_validator(self, apply=True):
        # Commits cannot be checked on these folders; the commit check has its own test below.
        report = self.s.validate(apply)
        report["unmet"] = [u for u in report["unmet"] if "not a git checkout" not in u]
        report["passed"] = not report["unmet"] and apply
        return report

    def assertUnmet(self, fragment: str, report=None):
        report = report or self.run_validator()
        self.assertFalse(report["passed"])
        self.assertTrue(any(fragment in u for u in report["unmet"]), report["unmet"])

    def write_registration(self, *, projects=PROJECTS, digest=None):
        doc = json.loads(REGISTRATION_EXAMPLE.read_text(encoding="utf-8"))
        doc["strata"]["projects"] = list(projects)
        doc["pins"]["setManifestSha256"] = digest
        path = self.s.root / "registration.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def test_supplied_registration_drives_quotas(self):
        manifest = self.s.save()
        registration = self.write_registration()
        stricter = {"wrongFixes": {"minimum": 31}, "perFamily": 5}
        with patch.dict(blind_set.QUOTAS, stricter):
            default = blind_set.validate(manifest, apply=False)
            self.assertUnmet("the minimum is 31", default)
            self.assertUnmet("at least 5", default)
            actual = blind_set.validate(manifest, apply=False, registration_path=registration)
        self.assertEqual(actual["unmet"], [])
        self.assertFalse(actual["passed"])
        self.assertIn("quotas taken from the public registration", blind_set.render(actual))

    def test_invalid_registration_stops_before_manifest_or_patches(self):
        path = self.write_registration()
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["strata"]["minimums"]["wrongFixes"] = 29
        path.write_text(json.dumps(doc), encoding="utf-8")
        with patch.object(blind_set, "load", side_effect=AssertionError("manifest opened")):
            report = blind_set.validate(self.s.save(), registration_path=path)
        self.assertUnmet("public registration", report)
        self.assertIsNone(report["counts"])
        self.assertFalse(report["patchesChecked"])

    def test_manifest_projects_must_match_the_registration(self):
        path = self.write_registration(projects=("alpha", "beta", "delta"))
        report = blind_set.validate(self.s.save(), apply=False, registration_path=path)
        self.assertUnmet("project names differ from the public registration", report)
        self.assertNotIn(SECRET, blind_set.render(report))

    def test_pinned_manifest_digest_requires_a_matching_seal(self):
        sealed = dict(self.s.doc, sealedAt="2031-01-01T00:00:00Z")
        sealed["sha256"] = blind_set.manifest_sha256(sealed)
        path = self.write_registration(digest=sealed["sha256"])
        draft = blind_set.validate(self.s.save(), apply=False, registration_path=path)
        self.assertUnmet("sealed manifest digest differs", draft)
        matching = blind_set.validate(self.s.save(sealed), apply=False, registration_path=path)
        self.assertEqual(matching["unmet"], [])
        wrong_pin = self.write_registration(digest="a" * 64)
        wrong = blind_set.validate(self.s.save(sealed), apply=False, registration_path=wrong_pin)
        self.assertUnmet("sealed manifest digest differs", wrong)

    def test_registration_command_line(self):
        out = io.StringIO()
        path = self.write_registration()
        with redirect_stdout(out):
            code = blind_set.main(["validate", str(self.s.save()), "--registration", str(path), "--skip-apply"])
        self.assertEqual(code, 1)
        self.assertIn("Counts now: 30 wrong fixes", out.getvalue())
        self.assertIn("quotas taken from the public registration", out.getvalue())

    # --- the valid set ---------------------------------------------------------------------------
    def test_the_synthetic_set_meets_every_minimum_and_passes(self):
        report = self.run_validator()
        self.assertEqual(report["unmet"], [])
        self.assertTrue(report["passed"])
        self.assertEqual((report["counts"]["wrongFixes"], report["counts"]["correctFixes"],
                          report["counts"]["notAFix"]), (30, 20, 10))
        text = blind_set.render(report)
        self.assertIn("PASS: the set would be accepted and would run with 30 wrong fixes, 20 correct fixes, "
                      "10 changes that are not fixes", text)
        self.assertNotIn(SECRET, text)

    def test_the_commit_check_reports_folders_that_are_not_checkouts(self):
        report = blind_set.validate(self.s.save(), self.s.projects)
        self.assertFalse(report["passed"])
        self.assertTrue(all("not a git checkout" in u for u in report["unmet"]), report["unmet"])

    def test_skipping_the_patches_never_passes(self):
        report = self.run_validator(apply=False)
        self.assertEqual(report["unmet"], [])
        self.assertFalse(report["passed"])
        self.assertIn("cannot pass until they are", " ".join(report["notes"]))
        self.assertNotIn("PASS", blind_set.render(report))

    # --- size and strata -------------------------------------------------------------------------
    def test_too_few_wrong_fixes_says_how_many_more(self):
        self.s.entry("e14")["candidates"].pop()
        self.s.recount()
        self.assertUnmet("size: 29 wrong fixes, the minimum is 30: 1 more wrong fixes")

    def test_too_few_correct_fixes_and_not_a_fix(self):
        self.s.doc["entries"] = [e for e in self.s.doc["entries"] if e["id"] not in ("e09", "n09")]
        self.s.recount()
        report = self.run_validator()
        self.assertUnmet("size: 18 correct fixes, the minimum is 20: 2 more correct fixes", report)
        self.assertUnmet("size: 9 changes that are not fixes, the minimum is 10", report)

    def test_a_project_above_half_the_set(self):
        for e in self.s.doc["entries"]:
            if e["project"] == "gamma":
                e["project"] = "alpha"
        self.s.recount()
        report = self.run_validator()
        self.assertUnmet("project alpha:", report)
        self.assertUnmet("is above half the set", report)
        self.assertUnmet("project gamma: listed but has no candidate", report)

    def test_screen_only_needs_a_quarter_of_wrong_fixes(self):
        self.s.entry("e04")["whereItShows"] = "both"
        self.s.recount()
        self.assertTrue(self.run_validator()["passed"])     # 8 of 30 is a quarter, rounded up
        self.s.entry("e03")["whereItShows"] = "both"
        self.s.recount()
        self.assertUnmet("screen-only: 6 of 30 wrong fixes show only on screen, a quarter needs 8: "
                         "2 more screen-only wrong fixes")

    def test_every_family_needs_four(self):
        self.s.entry("e09")["family"] = "assets"
        self.s.recount()
        self.assertUnmet("family hud-text: 0 candidates, at least 4: 4 more candidates")

    def test_every_wrong_fix_kind_needs_six(self):
        changed = 0
        for e in self.s.doc["entries"]:
            for c in e.get("candidates", []):
                if c.get("wrongFixKind") == "partial" and changed < 2:
                    c["wrongFixKind"] = "does-nothing"
                    changed += 1
        self.s.recount()
        self.assertUnmet("wrong-fix kind partial: 4, at least 6: 2 more wrong fixes of this kind")

    def test_two_differently_written_correct_fixes(self):
        self.s.entry("e00")["candidates"].pop()
        self.s.entry("e01")["candidates"][-1]["style"] = "minimal"
        self.s.recount()
        report = self.run_validator()
        self.assertUnmet("entry e00: 1 correct fix, needs 2 written differently", report)
        self.assertUnmet("entry e01: its correct fixes are all minimal: 1 more correct fix in the style restructures", report)

    def test_every_kind_of_change_that_is_not_a_fix(self):
        for e in self.s.doc["entries"]:
            if e.get("notAFixKind") == "asset-rename":
                e["notAFixKind"] = "refactor"
        self.s.recount()
        self.assertUnmet("not-a-fix kind asset-rename: none in the set")

    def test_expected_verdicts_of_changes_that_are_not_fixes(self):
        self.s.entry("n02")["expectedVerdict"] = "needs-review"    # a refactor
        self.s.entry("n01")["expectedVerdict"] = "accept"          # intentional, no contract update
        report = self.run_validator()
        self.assertUnmet("entry n02: a refactor change is expected to be accepted", report)
        self.assertUnmet("entry n01: an intentional change without its contract update", report)

    # --- ground truth ----------------------------------------------------------------------------
    def test_ground_truth_missing(self):
        del self.s.entry("e00")["candidates"][2]["confirmedBy"]
        (self.s.set / "e01" / "defect.mp4").unlink()
        self.s.entry("e02")["reproduction"]["steps"] = []
        report = self.run_validator()
        self.assertUnmet("candidate e00/correct-0: a correct fix with no confirmedBy", report)
        self.assertUnmet("entry e01: the recording e01/defect.mp4 is not a file in the set", report)
        self.assertUnmet("entry e02: reproduction/steps", report)
        self.assertUnmet("entry e02: no reproduction steps", report)
        # The quotas are still reported beside the structure problem.
        self.assertTrue(report["counts"])

    def test_a_wrong_fix_without_its_own_reproduction_is_a_note(self):
        report = self.run_validator()
        self.assertTrue(any(n.startswith("30 wrong fix(es) have no reproduction of their own (e00/wrong-0, ")
                            for n in report["notes"]), report["notes"])
        self.s.entry("e00")["candidates"][0]["reproduction"] = {"steps": ["x"], "recording": "e00/missing.mp4"}
        self.assertUnmet("candidate e00/wrong-0: the recording e00/missing.mp4 is not a file in the set")

    # --- declared counts -------------------------------------------------------------------------
    def test_declared_counts_that_disagree(self):
        self.s.doc["declaredCounts"]["wrongFixes"] = 31
        self.s.doc["declaredCounts"]["byFamily"]["assets"] = 5
        report = self.run_validator()
        self.assertUnmet("declaredCounts.wrongFixes: declared 31, the entries give 30", report)
        self.assertUnmet("declaredCounts.byFamily.assets: declared 5, the entries give 4", report)

    def test_only_the_three_totals_must_be_declared(self):
        self.s.doc["declaredCounts"] = {k: self.s.doc["declaredCounts"][k] for k in ("wrongFixes", "correctFixes", "notAFix")}
        self.assertTrue(self.run_validator()["passed"])

    # --- exclusions ------------------------------------------------------------------------------
    def test_an_excluded_entry_is_not_counted_and_its_patches_are_not_applied(self):
        (self.s.set / "e14" / "defect.patch").write_text("not a patch\n", encoding="utf-8")
        self.s.doc["exclusions"] = [{"id": "e14", "reason": "patch-does-not-apply"}]
        report = self.run_validator()
        self.assertUnmet("declaredCounts.wrongFixes: declared 30, the entries give 28", report)
        self.assertFalse(any("e14" in u for u in report["unmet"]), report["unmet"])

    def test_exclusions_name_real_entries_once_for_an_allowed_reason(self):
        self.s.doc["exclusions"] = [{"id": "zz", "reason": "not-reproducible"}]
        self.assertUnmet("exclusion zz: no entry has this id")
        self.s.doc["exclusions"] = [{"id": "e14", "reason": "too hard"}]
        self.assertUnmet("exclusions/0/reason")

    # --- patches ---------------------------------------------------------------------------------
    def test_a_missing_patch(self):
        (self.s.set / "e03" / "wrong-1.patch").unlink()
        self.assertUnmet("candidate e03/wrong-1: the patch e03/wrong-1.patch is not a file in the set")

    def test_a_defect_that_does_not_apply(self):
        (self.s.projects["alpha"] / "e00.txt").write_text(_text("e00.txt", "7"), encoding="utf-8")
        self.assertUnmet("entry e00: the defect e00/defect.patch does not apply to project alpha")

    def test_a_candidate_is_checked_on_top_of_its_defect(self):
        # This candidate applies to the clean project but not on top of the defect.
        name = "e03.txt"
        self.s._write("e03/wrong-1.patch", _diff(name, _text(name, "1"), _text(name, "1  # x")))
        self.assertUnmet("candidate e03/wrong-1: e03/wrong-1.patch does not apply on top of its defect")

    def test_a_change_that_is_not_a_fix_applies_to_the_clean_project(self):
        name = "n00.txt"
        self.s._write("n00/change.patch", _diff(name, _text(name, "6"), _text(name, "6  # x")))
        self.assertUnmet("entry n00: n00/change.patch does not apply to project alpha")

    def test_a_project_with_no_folder_given(self):
        del self.s.projects["beta"]
        self.assertUnmet("project beta: patches not applied, because no folder was given")

    def test_a_patch_reached_through_a_link_is_refused(self):
        outside = Path(self.tmp.name) / "outside.patch"
        shutil.copy(self.s.set / "e00" / "wrong-0.patch", outside)
        (self.s.set / "e00" / "wrong-0.patch").unlink()
        os.symlink(outside, self.s.set / "e00" / "wrong-0.patch")
        self.assertUnmet("candidate e00/wrong-0: the patch e00/wrong-0.patch is not a file in the set")

    def test_paths_cannot_leave_the_set(self):
        self.s.entry("e00")["defectPatch"] = "../outside.patch"
        self.assertUnmet("entry e00: defectPatch")

    def test_the_pinned_commit_is_compared_on_the_project_folder(self):
        repo = Path(self.tmp.name) / "repo"
        shutil.copytree(self.s.projects["alpha"], repo / "game")
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
        for cmd in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "pin"]):
            subprocess.run(["git", "-C", str(repo), *cmd], check=True, env=env, capture_output=True)
        commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True,
                                text=True).stdout.strip()
        self.assertIsNone(blind_set.project_commit_problem(repo / "game", commit))
        (repo / "README").write_text("outside the folder\n", encoding="utf-8")
        self.assertIsNone(blind_set.project_commit_problem(repo / "game", commit))
        (repo / "game" / "e00.txt").write_text("edited\n", encoding="utf-8")
        self.assertIn("differs from commit", blind_set.project_commit_problem(repo / "game", commit))
        self.assertIn("not in this checkout", blind_set.project_commit_problem(repo / "game", "1" * 40))

    # --- structure, reader and writer ------------------------------------------------------------
    def test_schema_problems_name_the_entry_and_field(self):
        self.s.entry("e05")["family"] = "physics"
        self.s.entry("e06")["candidates"][0]["style"] = "minimal"          # a wrong fix has no style
        self.s.entry("n03")["typo"] = 1
        report = self.run_validator()
        self.assertUnmet("entry e05: family: must be one of: collision-physics, movement-input", report)
        self.assertUnmet("entry e06: candidates/0: a wrong fix carries no style or confirmedBy", report)
        self.assertUnmet("entry n03: Additional properties are not allowed ('typo'", report)

    def test_a_schema_problem_never_prints_the_set_text(self):
        self.s.entry("e05")["description"] = SECRET * 200
        self.s.entry("e06")["howItShouldBehave"] = 5
        del self.s.entry("e07")["reproduction"]
        self.s.entry("n04")["notAFixKind"] = SECRET
        report = self.run_validator()
        self.assertUnmet("entry e05: description: fails maxLength (4000)", report)
        self.assertUnmet("entry e06: howItShouldBehave", report)
        self.assertUnmet("entry e07: 'reproduction' is a required property", report)
        self.assertNotIn(SECRET, blind_set.render(report))

    def test_check_measured_is_optional(self):
        self.assertTrue(self.run_validator()["passed"])
        self.s.entry("e00")["checkMeasured"] = False
        self.s.entry("n00")["checkMeasured"] = True
        self.assertTrue(self.run_validator()["passed"])
        self.s.entry("e01")["checkMeasured"] = "maybe"
        self.assertUnmet("entry e01: checkMeasured")

    def test_duplicate_keys_and_ids_are_refused(self):
        text = (self.s.set / "manifest.json").read_text(encoding="utf-8")
        (self.s.set / "manifest.json").write_text(text.replace('"name": "synthetic"', '"name": "a", "name": "b"'))
        report = blind_set.validate(self.s.set / "manifest.json", self.s.projects)
        self.assertTrue(any("duplicate key" in u for u in report["unmet"]), report["unmet"])
        self.s.entry("e01")["id"] = "e00"
        self.assertUnmet("entry e00: the id is used twice")

    def test_writer_seals_only_when_sealed_at_is_set_and_the_reader_refuses_an_edit_after(self):
        path = self.s.set / "written.json"
        blind_set.write(self.s.doc, path)
        self.assertIsNone(json.loads(path.read_text())["sha256"])
        self.assertEqual(blind_set.read(path)["name"], "synthetic")
        sealed = dict(self.s.doc, sealedAt="2026-12-04T18:00:00Z")
        blind_set.write(sealed, path)
        doc = blind_set.read(path)
        self.assertEqual(doc["sha256"], blind_set.manifest_sha256(doc))
        doc["entries"][0]["difficulty"] = "hard"
        path.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaisesRegex(blind_set.ManifestError, "edited after sealing"):
            blind_set.read(path)
        bad = dict(self.s.doc, sealedAt="soon")
        with self.assertRaisesRegex(blind_set.ManifestError, "not a date and time"):
            blind_set.write(bad, path)

    def test_the_example_is_a_valid_v1_record_that_the_reader_accepts(self):
        doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(contracts.validate_v1(doc), "blind-manifest")
        self.assertEqual(blind_set.read(EXAMPLE)["name"], "example-set")
        # It is a format example, far below the minimum: the validator says so.
        report = blind_set.validate(EXAMPLE, {}, apply=False)
        self.assertFalse(report["passed"])
        self.assertTrue(any(u.startswith("size:") for u in report["unmet"]))

    def test_the_command_line(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = blind_set.main(["validate", str(self.s.save()), "--skip-apply"])
        self.assertEqual(code, 1)
        self.assertIn("Counts now: 30 wrong fixes", out.getvalue())
        self.assertNotIn(SECRET, out.getvalue())
        out = io.StringIO()
        with redirect_stdout(out):
            code = blind_set.main(["validate", str(self.s.save()), "--json", "--skip-apply"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue())["counts"]["notAFix"], 10)
        with self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                blind_set.main(["validate", "m.json", "--project", "nofolder"])


if __name__ == "__main__":
    unittest.main()
