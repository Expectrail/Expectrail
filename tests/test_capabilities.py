"""The capability ledger: nothing is called measured without a run, and nothing advertised goes unlisted."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from agents import capabilities as cap

ROOT = Path(__file__).resolve().parent.parent


def _row(doc: dict, rid: str) -> dict:
    return next(r for r in doc["rows"] if r["id"] == rid)


class LedgerTest(unittest.TestCase):
    """The committed ledger, as it stands."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = cap.load()

    def test_the_committed_ledger_has_no_problems(self):
        self.assertEqual(cap.problems(self.doc), [])

    def test_the_page_is_what_the_ledger_renders_to(self):
        self.assertEqual(cap.PAGE.read_text(encoding="utf-8"), cap.render(self.doc),
                         "run: python3 -m agents.capabilities render")

    def test_the_readme_links_to_the_ledger(self):
        self.assertIn("(docs/capabilities.md)", (ROOT / "README.md").read_text(encoding="utf-8"))

    def test_every_mode_the_issue_names_has_a_row(self):
        ids = {r["id"] for r in self.doc["rows"]}
        self.assertEqual(set(cap.REQUIRED) - ids, set())

    def test_every_measured_row_links_a_run(self):
        measured = [r for r in self.doc["rows"] if r["status"] == "measured"]
        self.assertTrue(measured)
        for row in measured:
            self.assertTrue([e for e in row["evidence"] if e["kind"] == "run"], row["id"])

    def test_every_cited_run_carries_its_conclusion_and_only_experimental_rows_cite_a_failure(self):
        cited = [(r, e) for r in self.doc["rows"] for e in r["evidence"] if e["kind"] == "run"]
        self.assertGreater(len(cited), 20)
        for row, ev in cited:
            self.assertIn("conclusion", ev, row["id"])
            if ev["conclusion"] != "success":
                self.assertIn(row["status"], ("experimental", "implemented"), row["id"])
                self.assertTrue(ev.get("conclusionNote"), row["id"])

    def test_the_unity_row_says_its_specs_are_approved_and_cites_runs_that_passed(self):
        row = _row(self.doc, "unity-harness")
        self.assertEqual(row["status"], "experimental")
        self.assertIn("are approved (#235)", row["limits"])
        self.assertNotIn("draft", row["mode"].lower())
        runs = [e for e in row["evidence"] if e["kind"] == "run"]
        self.assertEqual({e["conclusion"] for e in runs}, {"success"})
        # The ledger's claim and the files agree: each spec in specs/unity/ carries an approval.
        specs = sorted((ROOT / "specs" / "unity").glob("*.json"))
        self.assertEqual(len(specs), 3)
        for path in specs:
            self.assertIn("approval", json.loads(path.read_text(encoding="utf-8")), path.name)

    def test_no_row_claims_a_grade_above_diagnostic_yet(self):
        # Isolated needs the replay sandbox, the two-job action and the receipt; none has landed.
        # When one does, this test changes in the pull request that shows it.
        self.assertEqual({r["grade"] for r in self.doc["rows"]} - {"fixture", "diagnostic"}, set())

    def test_the_example_matches_the_schema(self):
        example = cap.load(ROOT / "contracts" / "examples" / "capabilities.json")
        self.assertEqual(example["format"], "expectrail.capabilities/v1")
        self.assertEqual([p for p in cap.row_problems(example) if "must cover" not in p], [])

    def test_the_schema_itself_is_valid_draft_2020_12(self):
        import jsonschema

        jsonschema.Draft202012Validator.check_schema(json.loads(cap.SCHEMA.read_text(encoding="utf-8")))

    def test_the_wall_time_names_its_run_and_what_it_did_not_measure(self):
        self.assertTrue(self.doc["timings"])
        for timing in self.doc["timings"]:
            self.assertRegex(timing["run"], r"/actions/runs/\d+")
            self.assertTrue(timing["notMeasured"])


class RowRulesTest(unittest.TestCase):
    """Each rule, with a ledger that breaks it."""

    def setUp(self) -> None:
        self.doc = copy.deepcopy(cap.load())
        self.assertEqual(cap.row_problems(self.doc), [])

    def test_measured_without_a_run_link_fails(self):
        row = _row(self.doc, "godot-verify")
        row["evidence"] = [e for e in row["evidence"] if e["kind"] != "run"]
        self.assertEqual(cap.row_problems(self.doc), ["godot-verify: marked measured with no CI run link"])

    def test_a_measured_or_integrated_row_that_cites_a_failed_run_fails(self):
        for rid, status in (("godot-verify", "measured"), ("ci-gate", "integrated")):
            doc = copy.deepcopy(self.doc)
            run = next(e for e in _row(doc, rid)["evidence"] if e["kind"] == "run")
            run["conclusion"] = "failure"
            number = run["ref"].split("/runs/")[1]
            self.assertEqual(cap.row_problems(doc), [f"{rid}: marked {status} and cites run {number}, recorded as failure"])

    def test_a_cancelled_run_is_not_a_success_either(self):
        run = next(e for e in _row(self.doc, "discovery")["evidence"] if e["kind"] == "run")
        run["conclusion"] = "cancelled"
        self.assertEqual(len(cap.row_problems(self.doc)), 1)
        self.assertIn("recorded as cancelled", cap.row_problems(self.doc)[0])

    def test_an_experimental_row_may_cite_a_failed_run_and_the_page_says_it_failed(self):
        row = _row(self.doc, "cocos-trial")
        self.assertEqual((row["status"], row["evidence"][0]["conclusion"]), ("experimental", "failure"))
        self.assertIn(". The run ended in failure: " + row["evidence"][0]["conclusionNote"], cap.render(self.doc))

    def test_a_run_with_no_recorded_conclusion_fails(self):
        run = next(e for e in _row(self.doc, "godot-verify")["evidence"] if e["kind"] == "run")
        del run["conclusion"]
        self.assertEqual(cap.row_problems(self.doc), [f"godot-verify: no recorded conclusion for {run['ref']}"])

    def test_a_failed_run_cited_without_a_reason_fails(self):
        # What let two failed Unity runs through review of #275: a link was accepted without a look.
        run = next(e for e in _row(self.doc, "unity-harness")["evidence"] if e["kind"] == "run")
        run["conclusion"] = "failure"
        found = cap.row_problems(self.doc)
        self.assertEqual(len(found), 1)
        self.assertIn("ended in failure without saying why", found[0])
        run["conclusionNote"] = "The failure is the result under test."
        self.assertEqual(cap.row_problems(self.doc), [])
        self.assertIn("The run ended in failure: The failure is the result under test.", cap.render(self.doc))

    def test_a_reason_does_not_let_a_measured_or_integrated_row_cite_a_failed_run(self):
        run = next(e for e in _row(self.doc, "judge-fallback")["evidence"] if e["kind"] == "run")
        run["conclusion"], run["conclusionNote"] = "failure", "The failure is the result."
        number = run["ref"].split("/runs/")[1]
        self.assertEqual(cap.row_problems(self.doc),
                         [f"judge-fallback: marked integrated and cites run {number}, recorded as failure"])

    def test_measured_with_no_successful_run_fails(self):
        for run in _row(self.doc, "godot-verify")["evidence"]:
            if run["kind"] == "run":
                run["conclusion"], run["conclusionNote"] = "failure", "explained"
        found = cap.row_problems(self.doc)
        self.assertEqual(found[0], "godot-verify: marked measured and no cited run ended in success")
        # Stricter than the first version of this test: each failed run is also reported on its own.
        self.assertEqual(len(found), 3)
        self.assertTrue(all("recorded as failure" in line for line in found[1:]), found)

    def test_the_unity_specs_are_not_called_drafts(self):
        row = _row(self.doc, "unity-harness")
        self.assertNotIn("no person has approved", row["limits"])
        for path in sorted((ROOT / "specs" / "unity").glob("*.json")):
            self.assertIn("approval", json.loads(path.read_text(encoding="utf-8")), path.name)

    def test_the_wall_time_may_not_rest_on_a_failed_run(self):
        self.doc["timings"][0]["conclusion"] = "failure"
        self.assertEqual(cap.row_problems(self.doc), ["timings: run 42934646223 is recorded as failure"])

    def test_the_schema_requires_a_conclusion_on_a_run_and_refuses_one_on_a_file(self):
        import jsonschema

        validator = jsonschema.Draft202012Validator(json.loads(cap.SCHEMA.read_text(encoding="utf-8")))
        self.assertEqual(list(validator.iter_errors(self.doc)), [])
        missing = copy.deepcopy(self.doc)
        del next(e for e in _row(missing, "ci-gate")["evidence"] if e["kind"] == "run")["conclusion"]
        self.assertTrue(list(validator.iter_errors(missing)))
        extra = copy.deepcopy(self.doc)
        next(e for e in _row(extra, "ci-gate")["evidence"] if e["kind"] == "test")["conclusion"] = "success"
        self.assertTrue(list(validator.iter_errors(extra)))
        note = copy.deepcopy(self.doc)
        next(e for e in _row(note, "ci-gate")["evidence"] if e["kind"] == "test")["conclusionNote"] = "x"
        self.assertTrue(list(validator.iter_errors(note)))
        unknown = copy.deepcopy(self.doc)
        next(e for e in _row(unknown, "ci-gate")["evidence"] if e["kind"] == "run")["conclusion"] = "green"
        self.assertTrue(list(validator.iter_errors(unknown)))

    def test_measured_on_saved_data_fails(self):
        _row(self.doc, "godot-verify")["grade"] = "fixture"
        self.assertEqual(len(cap.row_problems(self.doc)), 1)
        self.assertIn("not a measurement", cap.row_problems(self.doc)[0])

    def test_integrated_on_a_record_alone_fails(self):
        row = _row(self.doc, "spec-writer")
        row["evidence"] = [e for e in row["evidence"] if e["kind"] == "record"]
        self.assertEqual(cap.row_problems(self.doc), ["spec-writer: marked integrated with neither a test nor a run"])

    def test_the_protected_grade_is_refused(self):
        _row(self.doc, "ci-gate")["grade"] = "protected"
        self.assertEqual(len(cap.row_problems(self.doc)), 1)
        self.assertIn("reserved", cap.row_problems(self.doc)[0])

    def test_a_link_to_a_file_that_is_not_there_fails(self):
        _row(self.doc, "mcp-tools")["evidence"][0]["ref"] = "tests/test_no_such_file.py"
        self.assertEqual(cap.row_problems(self.doc), ["mcp-tools: evidence file not found: tests/test_no_such_file.py"])

    def test_an_anchor_on_a_real_file_is_fine(self):
        _row(self.doc, "godot-harness")["evidence"][2]["ref"] = "docs/harness.md#unity-harness"
        self.assertEqual(cap.row_problems(self.doc), [])

    def test_an_entry_point_a_workflow_or_a_doc_that_is_not_there_fails(self):
        row = _row(self.doc, "discovery")
        row["entryPoints"].append("expectrail.no_such_module")
        row["workflows"].append("no-such.yml")
        row["docs"].append("docs/no-such.md")
        self.assertEqual(cap.row_problems(self.doc), [
            "discovery: entry point not found: expectrail.no_such_module",
            "discovery: workflow not found: no-such.yml",
            "discovery: doc not found: docs/no-such.md",
        ])

    def test_a_package_counts_as_an_entry_point(self):
        self.assertIn("harness.web", _row(self.doc, "web-checkout")["entryPoints"])

    def test_the_same_id_twice_fails(self):
        self.doc["rows"].append(copy.deepcopy(_row(self.doc, "signing")))
        self.assertEqual(cap.row_problems(self.doc), ["signing: listed twice"])

    def test_dropping_a_mode_the_issue_names_fails(self):
        self.doc["rows"] = [r for r in self.doc["rows"] if r["id"] != "key-gateway"]
        self.assertEqual(cap.row_problems(self.doc), ["key-gateway: a mode the ledger must cover has no row"])

    def test_the_schema_refuses_an_unknown_status_and_a_run_link_to_another_repository(self):
        path = ROOT / "contracts" / "examples" / "capabilities.json"
        import tempfile

        for change in ("status", "run"):
            doc = json.loads(path.read_text(encoding="utf-8"))
            if change == "status":
                doc["rows"][0]["status"] = "works"
            else:
                doc["rows"][0]["evidence"][0]["ref"] = "https://github.com/someone/else/actions/runs/1"
            with tempfile.TemporaryDirectory() as tmp:
                bad = Path(tmp) / "capabilities.json"
                bad.write_text(json.dumps(doc), encoding="utf-8")
                with self.assertRaises(cap.LedgerError, msg=change):
                    cap.load(bad)


class AdvertTest(unittest.TestCase):
    """What the README and the site name must be in the ledger."""

    def setUp(self) -> None:
        self.doc = copy.deepcopy(cap.load())
        self.texts = cap.read_adverts()
        self.assertEqual(cap.advert_problems(self.doc, self.texts), [])

    def _with(self, name: str, extra: str) -> list[str]:
        texts = dict(self.texts)
        texts[name] = texts[name] + "\n" + extra + "\n"
        return cap.advert_problems(self.doc, texts)

    def test_the_readme_and_the_site_are_the_files_read(self):
        self.assertEqual(sorted(self.texts), ["README.md", "docs/index.html"])
        self.assertIn("python3 -m agents.loop", self.texts["README.md"])

    def test_a_new_command_in_the_readme_fails(self):
        self.assertEqual(self._with("README.md", "python3 -m agents.teleport --out runs/x"),
                         ["README.md: names the command agents.teleport, which no ledger row lists"])

    def test_a_new_command_on_the_site_fails(self):
        self.assertEqual(self._with("docs/index.html", "<code>python -m expectrail.unreal</code>"),
                         ["docs/index.html: names the command expectrail.unreal, which no ledger row lists"])

    def test_a_new_switch_fails_and_a_role_prefix_covers_its_own(self):
        self.assertEqual(self._with("README.md", "set `EXPECTRAIL_AUDIO_BACKEND=whisper`"),
                         ["README.md: names the switch EXPECTRAIL_AUDIO_BACKEND, which no ledger row lists"])
        self.assertEqual(self._with("README.md", "set `EXPECTRAIL_FIXER_TIMEOUT=60`"), [])

    def test_a_workflow_no_row_lists_fails(self):
        self.assertEqual(self._with("README.md", "see `.github/workflows/mutation-bench.yml`"),
                         ["README.md: names the workflow mutation-bench.yml, which no ledger row lists"])
        self.assertEqual(self._with("README.md", "an `action.yml` at the root"), [])

    def test_a_doc_page_no_row_lists_fails(self):
        self.assertEqual(self._with("README.md", "[how](docs/unreal.md)"),
                         ["README.md: names the doc docs/unreal.md, which no ledger row lists"])

    def test_a_watched_name_with_no_row_fails(self):
        self.assertEqual(self._with("README.md", "Expectrail also judges Unreal games."),
                         ["README.md: names Unreal, which no ledger row lists"])
        self.assertEqual(self._with("docs/index.html", "<p>Now on <b>GameMaker</b>.</p>"),
                         ["docs/index.html: names GameMaker, which no ledger row lists"])

    def test_a_name_inside_a_tag_or_a_longer_word_is_not_a_claim(self):
        self.assertEqual(self._with("docs/index.html", '<img alt="x" data-engine="Unreal">'), [])
        self.assertEqual(self._with("README.md", "an Unrealistic result"), [])

    def test_removing_a_row_the_readme_still_advertises_fails(self):
        self.doc["rows"] = [r for r in self.doc["rows"] if r["id"] != "sam-observer"]
        found = cap.advert_problems(self.doc, self.texts)
        self.assertIn("README.md: names SAM 3.1, which no ledger row lists", found)
        self.assertIn("docs/index.html: names SAM 3.1, which no ledger row lists", found)
        self.assertIn("README.md: names the doc docs/sam.md, which no ledger row lists", found)
        self.assertIn("README.md: the Meta models table has 'SAM 3.1', which no ledger row lists", found)

    def test_a_new_row_in_the_meta_models_table_fails(self):
        readme = self.texts["README.md"]
        marker = "| Muse Voice Transcribe |"
        self.assertEqual(readme.count(marker), 1)
        texts = dict(self.texts)
        texts["README.md"] = readme.replace(marker, "| Muse Echo | Listens | nothing yet |\n" + marker)
        self.assertEqual(cap.advert_problems(self.doc, texts),
                         ["README.md: the Meta models table has 'Muse Echo', which no ledger row lists"])

    def test_the_meta_models_table_is_found(self):
        cells = cap.meta_models(self.texts["README.md"])
        self.assertIn("SAM 3.1", cells)
        self.assertGreaterEqual(len(cells), 7)

    def test_a_thing_that_is_not_a_mode_needs_its_reason_in_the_ledger(self):
        del self.doc["notModes"]["commands"]["unittest"]
        self.assertEqual(cap.advert_problems(self.doc, self.texts),
                         ["README.md: names the command unittest, which no ledger row lists"])


class CommandLineTest(unittest.TestCase):
    def test_check_passes_on_the_committed_ledger(self):
        self.assertEqual(cap.main(["check"]), 0)


if __name__ == "__main__":
    unittest.main()
