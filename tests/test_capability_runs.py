"""Re-reading the ledger's runs: a run GitHub describes differently, or will not describe, is a problem."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import unittest
from unittest import mock

from expectrail import capabilities as cap
from expectrail import capability_runs as runs

RUN = "https://github.com/Expectrail/Expectrail/actions/runs/"


def _step(name: str, seconds: int = 29, conclusion: str = "success") -> dict:
    return {"name": name, "conclusion": conclusion, "startedAt": "2026-11-11T10:00:00Z",
            "completedAt": f"2026-11-11T10:00:{seconds:02d}Z"}


def _job(name: str, conclusion: str = "success", job_id: str = "7", steps: list | None = None) -> dict:
    return {"id": job_id, "name": name, "conclusion": conclusion, "steps": steps or []}


def _run(*jobs: dict, conclusion: str = "success", status: str = "completed") -> dict:
    return {"status": status, "conclusion": conclusion, "attempt": 1, "jobs": list(jobs)}


def _ledger(evidence: list | None = None, timings: list | None = None, status: str = "measured") -> dict:
    return {"rows": [{"id": "mode", "status": status, "evidence": evidence or []}], "timings": timings or []}


def _cite(number: str = "1", **more) -> dict:
    return {"kind": "run", "ref": RUN + number, "conclusion": "success", "shows": "it ran", **more}


def _timing(**more) -> dict:
    return {"run": RUN + "1/job/7", "step": "Verify", "seconds": 29, "resolutionSeconds": 1,
            "conclusion": "success", **more}


class _Checks:
    def check(self, doc: dict, answers: dict) -> list[str]:
        def read(number: str) -> dict:
            answer = answers[number]
            if isinstance(answer, Exception):
                raise answer
            return answer
        return runs.recheck(doc, read)[0]


class RecheckTest(_Checks, unittest.TestCase):
    def test_a_run_that_ended_as_recorded_with_its_jobs_green_has_no_problem(self):
        doc = _ledger([_cite(jobs=["build", "replay (a)"])])
        self.assertEqual(self.check(doc, {"1": _run(_job("build"), _job("replay (a)"), _job("extra", "skipped"))}), [])

    def test_a_conclusion_that_differs_from_the_recorded_one_is_a_problem(self):
        found = self.check(_ledger([_cite()]), {"1": _run(conclusion="failure")})
        self.assertEqual(found, ["mode: run 1: recorded as success and GitHub says failure"])

    def test_a_recorded_failure_that_github_now_calls_success_is_a_problem_too(self):
        found = self.check(_ledger([_cite(conclusion="failure", conclusionNote="why")], status="experimental"),
                           {"1": _run()})
        self.assertEqual(found, ["mode: run 1: recorded as failure and GitHub says success"])

    def test_a_recorded_failure_that_is_still_a_failure_has_no_problem(self):
        doc = _ledger([_cite(conclusion="failure", conclusionNote="why")], status="experimental")
        self.assertEqual(self.check(doc, {"1": _run(_job("trial", "failure"), conclusion="failure")}), [])

    def test_a_named_job_that_is_missing_failed_or_was_skipped_is_a_problem(self):
        doc = _ledger([_cite(jobs=["replay (a)"])])
        self.assertEqual(self.check(doc, {"1": _run(_job("replay (b)"))}),
                         ["mode: run 1: the evidence rests on job 'replay (a)' and the run has no job of that name"])
        for ending in ("failure", "skipped", "cancelled", None):
            found = self.check(doc, {"1": _run(_job("replay (a)", ending))})
            self.assertEqual(found, [f"mode: run 1: the evidence rests on job 'replay (a)', which ended in {ending}"])

    def test_a_job_name_is_matched_whole(self):
        doc = _ledger([_cite(jobs=["replay"])])
        self.assertEqual(len(self.check(doc, {"1": _run(_job("replay (a)"), _job("agents-replay"))})), 1)

    def test_a_green_run_does_not_cover_for_a_failed_job_the_evidence_names(self):
        # GitHub calls a run a success when a failed job was allowed to fail.
        doc = _ledger([_cite(jobs=["cross-runner"])])
        self.assertEqual(len(self.check(doc, {"1": _run(_job("cross-runner", "failure"), conclusion="success")})), 1)

    def test_a_linked_job_must_be_in_the_run_and_green(self):
        doc = _ledger([_cite("1/job/7")])
        self.assertEqual(self.check(doc, {"1": _run(_job("verify"))}), [])
        self.assertEqual(self.check(doc, {"1": _run(_job("verify", job_id="8"))}),
                         ["mode: run 1: the link names job 7 and the run's latest attempt has no such job"])
        self.assertEqual(self.check(doc, {"1": _run(_job("verify", "failure"))}),
                         ["mode: run 1: the link names job 'verify', which ended in failure"])

    def test_a_run_that_cannot_be_read_is_cannot_tell_for_every_row_that_cites_it(self):
        doc = _ledger([_cite(), _cite("2")], [_timing()])
        found = self.check(doc, {"1": runs.RunUnreadable("gh api exited 1: HTTP 404"), "2": _run()})
        self.assertEqual(found, ["mode: run 1: cannot tell: gh api exited 1: HTTP 404",
                                 "timings: run 1: cannot tell: gh api exited 1: HTTP 404"])

    def test_a_run_still_going_is_cannot_tell(self):
        found = self.check(_ledger([_cite()]), {"1": _run(status="in_progress", conclusion=None)})
        self.assertEqual(found, ["mode: run 1: cannot tell: the run is in_progress, not completed"])

    def test_a_reader_that_fails_in_any_other_way_is_cannot_tell_not_a_traceback(self):
        found = self.check(_ledger([_cite(), _cite("2")]), {"1": KeyError("jobs"), "2": _run()})
        self.assertEqual(found, ["mode: run 1: cannot tell: the reader failed: KeyError: 'jobs'"])

    def test_each_run_is_read_once_however_many_rows_cite_it(self):
        seen = []

        def read(number: str) -> dict:
            seen.append(number)
            return _run(_job("verify", steps=[_step("Verify")]))
        problems, checked = runs.recheck(_ledger([_cite(), _cite(), _cite("2")], [_timing()]), read)
        self.assertEqual((problems, seen), ([], ["1", "2"]))
        self.assertEqual(checked[0], "run 1: completed, success, attempt 1, 1 jobs")


class WallTimeTest(_Checks, unittest.TestCase):
    def timed(self, timing: dict, *steps: dict, job: str = "success") -> list[str]:
        return self.check(_ledger(timings=[timing]), {"1": _run(_job("verify", job, steps=list(steps)))})

    def test_a_time_read_from_the_step_must_be_the_time_the_step_lasted(self):
        self.assertEqual(self.timed(_timing(), _step("Verify", 29)), [])
        self.assertEqual(self.timed(_timing(), _step("Verify", 30)), [])
        self.assertEqual(self.timed(_timing(), _step("Verify", 41)),
                         ["timings: run 1: 29 s is recorded and the step lasted 41 s by its timestamps"])
        self.assertEqual(len(self.timed(_timing(), _step("Verify", 12))), 1)

    def test_a_time_measured_inside_the_step_may_not_exceed_the_step(self):
        phases = {"import": 2.8, "replay": 29.9, "evaluate": 0.3, "other": 0.1}
        inside = _timing(seconds=33.1, resolutionSeconds=0.1, phases=phases)
        self.assertEqual(self.timed(inside, _step("Verify", 34)), [])
        self.assertEqual(self.timed(inside, _step("Verify", 50)), [])
        self.assertEqual(self.timed(inside, _step("Verify", 20)),
                         ["timings: run 1: 33.1 s is recorded for a verification inside a step that lasted 20 s"])

    def test_a_rows_own_resolution_cannot_excuse_a_time_that_is_not_the_steps(self):
        self.assertEqual(len(self.timed(_timing(seconds=1000, resolutionSeconds=1000), _step("Verify", 30))), 1)
        self.assertEqual(len(self.timed(_timing(resolutionSeconds=1000), _step("Verify", 32))), 1)

    def test_the_step_must_be_there_once_and_green(self):
        self.assertEqual(self.timed(_timing(), _step("Something else")),
                         ["timings: run 1: job 'verify' has 0 steps named 'Verify', not one"])
        self.assertEqual(len(self.timed(_timing(), _step("Verify"), _step("Verify"))), 1)
        self.assertEqual(self.timed(_timing(), _step("Verify", conclusion="failure"), job="failure"),
                         ["timings: run 1: the link names job 'verify', which ended in failure",
                          "timings: run 1: the step 'Verify' ended in failure"])

    def test_a_step_with_no_timestamps_is_cannot_tell(self):
        step = dict(_step("Verify"), startedAt=None)
        self.assertEqual(self.timed(_timing(), step),
                         ["timings: run 1: cannot tell: the step 'Verify' has no start or end time"])
        self.assertEqual(len(self.timed(_timing(), dict(_step("Verify"), completedAt="yesterday"))), 1)

    def test_a_wall_time_that_links_no_job_is_cannot_tell(self):
        found = self.check(_ledger(timings=[_timing(run=RUN + "1")]), {"1": _run(_job("verify"))})
        self.assertEqual(found, ["timings: run 1: cannot tell: a wall time must link the job whose step it timed"])


class GithubReaderTest(unittest.TestCase):
    """The reader on saved answers in the shape GitHub's API gives."""

    RUN_ANSWER = {"id": 5, "status": "completed", "conclusion": "success", "run_attempt": 2}
    JOBS_ANSWER = {"total_count": 1, "jobs": [{
        "id": 130241583383, "name": "agents-harness-verify", "conclusion": "success",
        "steps": [{"name": "Verify", "conclusion": "success", "number": 4,
                   "started_at": "2026-11-11T10:00:00Z", "completed_at": "2026-11-11T10:00:29Z"}]}]}

    def reader(self, run=None, jobs=None, asked: list | None = None):
        def call(path: str) -> str:
            if asked is not None:
                asked.append(path)
            answer = (self.JOBS_ANSWER if jobs is None else jobs) if "/jobs" in path else \
                (self.RUN_ANSWER if run is None else run)
            return answer if isinstance(answer, str) else json.dumps(answer)
        return runs.github_reader(call)

    def test_it_asks_for_the_run_and_its_jobs_and_nothing_else(self):
        asked: list[str] = []
        run = self.reader(asked=asked)("5")
        self.assertEqual(asked, ["repos/Expectrail/Expectrail/actions/runs/5",
                                 "repos/Expectrail/Expectrail/actions/runs/5/jobs?per_page=100&page=1"])
        self.assertFalse([path for path in asked if "logs" in path or "artifacts" in path])
        self.assertEqual((run["status"], run["conclusion"], run["attempt"]), ("completed", "success", 2))
        self.assertEqual(run["jobs"][0]["id"], "130241583383")
        self.assertEqual(runs._seconds(run["jobs"][0]["steps"][0]), 29.0)

    def _paged(self, pages: dict, total: int, asked: list):
        def call(path: str) -> str:
            asked.append(path)
            if "/jobs" not in path:
                return json.dumps(self.RUN_ANSWER)
            page = int(path.rsplit("page=", 1)[1])
            return json.dumps({"total_count": total, "jobs": [
                {"id": i, "name": f"job {i}", "conclusion": "success", "steps": []} for i in pages.get(page, [])]})
        return runs.github_reader(call)

    def test_a_run_with_more_than_a_page_of_jobs_is_read_page_by_page(self):
        asked: list[str] = []
        run = self._paged({1: range(100), 2: range(100, 140)}, 140, asked)("5")
        self.assertEqual(len(run["jobs"]), 140)
        self.assertEqual(len(asked), 3)

    def test_pages_that_stop_short_or_repeat_a_job_are_unreadable(self):
        with self.assertRaisesRegex(runs.RunUnreadable, "counts 140 jobs and listed 100"):
            self._paged({1: range(100)}, 140, [])("5")
        with self.assertRaisesRegex(runs.RunUnreadable, "counts 140 jobs"):
            self._paged({1: range(100), 2: range(60, 100)}, 140, [])("5")

    def test_fewer_jobs_listed_than_counted_is_unreadable_not_a_shorter_list(self):
        with self.assertRaisesRegex(runs.RunUnreadable, "counts 140 jobs and listed 1"):
            self.reader(jobs=dict(self.JOBS_ANSWER, total_count=140))("5")

    def test_an_answer_that_is_not_json_or_lacks_a_field_is_unreadable(self):
        for run, jobs in (("<html>", None), ({"status": "completed"}, None), (None, {"jobs": []}),
                          (None, {"total_count": 1, "jobs": [{"id": 1}]}), (None, "[]")):
            with self.assertRaises(runs.RunUnreadable, msg=(run, jobs)):
                self.reader(run=run, jobs=jobs)("5")

    def test_gh_failing_or_missing_is_unreadable_with_its_last_line(self):
        failed = mock.Mock(returncode=1, stdout="", stderr="warning\ngh: Not Found (HTTP 404)\n")
        with mock.patch("subprocess.run", return_value=failed):
            with self.assertRaisesRegex(runs.RunUnreadable, r"gh api exited 1: gh: Not Found \(HTTP 404\)"):
                runs._gh("repos/x")
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("gh")):
            with self.assertRaisesRegex(runs.RunUnreadable, "gh api did not run"):
                runs._gh("repos/x")

    def test_gh_is_called_to_read_only(self):
        ok = mock.Mock(returncode=0, stdout="{}", stderr="")
        with mock.patch("subprocess.run", return_value=ok) as run:
            runs._gh("repos/x")
        self.assertEqual(run.call_args.args[0], ["gh", "api", "repos/x"])


class LedgerRunsTest(unittest.TestCase):
    """The committed ledger, against answers built from what it records. No network."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = cap.load()

    def answers(self) -> dict:
        out: dict[str, dict] = {}
        for cite in runs.cited(self.doc):
            number, job_id = runs._split(cite["ref"])
            run = out.setdefault(number, _run(conclusion=cite["conclusion"]))
            names = {job["name"] for job in run["jobs"]}
            run["jobs"] += [_job(name, job_id=f"n-{name}") for name in cite["jobs"] if name not in names]
            if job_id and "timing" in cite:
                seconds = int(cite["timing"]["seconds"]) + (1 if "phases" in cite["timing"] else 0)
                run["jobs"].append(_job("timed", job_id=job_id, steps=[_step(cite["timing"]["step"], seconds)]))
        return out

    def test_every_cited_run_is_asked_about_and_the_ledger_agrees_with_itself(self):
        answers = self.answers()
        problems, checked = runs.recheck(self.doc, answers.__getitem__)
        self.assertEqual(problems, [])
        self.assertEqual(len(checked), len(answers))
        self.assertGreater(len(answers), 20)

    def test_a_run_that_turned_red_since_is_caught_on_every_row_that_cites_it(self):
        answers = self.answers()
        answers["42934646223"]["conclusion"] = "failure"
        problems, _ = runs.recheck(self.doc, answers.__getitem__)
        self.assertGreaterEqual(len(problems), 6)
        self.assertTrue(all("recorded as success and GitHub says failure" in p for p in problems), problems)

    def test_evidence_that_names_a_job_in_words_lists_it_under_jobs(self):
        # "job capture-smoke: ..." in the text and no jobs field would be a claim recheck never tests.
        import re

        for row in self.doc["rows"]:
            for ev in row["evidence"]:
                if ev["kind"] != "run" or ev["conclusion"] != "success":
                    continue
                for name in re.findall(r"\bjob ([a-z0-9][a-z0-9-]*)", ev["shows"]):
                    self.assertIn(name, ev.get("jobs", []), f"{row['id']}: {ev['shows']}")

    def test_the_schema_takes_jobs_on_a_run_only_and_refuses_an_empty_list(self):
        doc = copy.deepcopy(self.doc)
        row = next(r for r in doc["rows"] if r["id"] == "godot-verify")
        run = next(e for e in row["evidence"] if e["kind"] == "run")
        test = next(e for e in row["evidence"] if e["kind"] == "test")
        import jsonschema

        validator = jsonschema.Draft202012Validator(json.loads(cap.SCHEMA.read_text(encoding="utf-8")))
        self.assertEqual(list(validator.iter_errors(doc)), [])
        for change in (lambda: run.update(jobs=[]), lambda: run.update(jobs=["a", "a"]),
                       lambda: run.update(jobs="agents-gate1"), lambda: test.update(jobs=["test"])):
            saved = (copy.deepcopy(run), copy.deepcopy(test))
            change()
            self.assertTrue(list(validator.iter_errors(doc)))
            run.clear(), run.update(saved[0]), test.clear(), test.update(saved[1])


class CommandTest(unittest.TestCase):
    def run_command(self, problems: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(runs, "github_reader", return_value=None), \
                mock.patch.object(runs, "recheck", return_value=(problems, ["run 1: completed, success, attempt 1, 1 jobs"])), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cap.main(["recheck"])
        return code, out.getvalue(), err.getvalue()

    def test_recheck_exits_0_and_lists_what_it_read(self):
        code, out, err = self.run_command([])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines(), ["run 1: completed, success, attempt 1, 1 jobs", "1 runs read, 0 problems"])

    def test_recheck_exits_1_with_one_line_a_problem(self):
        code, out, err = self.run_command(["mode: run 1: cannot tell: gh api did not run"])
        self.assertEqual(code, 1)
        self.assertEqual(err.splitlines(), ["mode: run 1: cannot tell: gh api did not run"])
        self.assertIn("1 problems", out)


class NotANumberTest(unittest.TestCase):
    def test_a_ledger_time_that_is_not_a_number_is_a_problem(self):
        for value in (float("nan"), float("inf")):
            doc = copy.deepcopy(cap.load())
            doc["timings"][1]["phases"]["replay"] = value
            self.assertEqual(cap.row_problems(doc), ["timings/1/phases/replay: not a finite number"])
            doc = copy.deepcopy(cap.load())
            doc["timings"][0]["seconds"] = value
            self.assertEqual(cap.row_problems(doc), ["timings/0/seconds: not a finite number"])

    def test_load_refuses_a_ledger_file_with_nan_in_it(self):
        import tempfile
        from pathlib import Path

        text = cap.LEDGER.read_text(encoding="utf-8").replace('"seconds": 29,', '"seconds": NaN,', 1)
        self.assertIn("NaN", text)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capabilities.json"
            path.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(cap.LedgerError, "timings/0/seconds: not a finite number"):
                cap.load(path)


if __name__ == "__main__":
    unittest.main()
