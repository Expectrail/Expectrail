""""Run it" (#265): the recording workflow, run-it-record.yml, and what it relies on in
expectrail.runit: `check-recording` and the spend line `record` prints.

No live model and no Godot. Recordings are made from the scripted stand-in model of
tests/test_runit.py, so they are not recordings of the live model.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import unittest
from pathlib import Path
from unittest import mock

import yaml

from expectrail import runit
from tests.test_runit import Case

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "run-it-record.yml"
# The line the workflow accepts as the spend, as in its record step.
SPEND = re.compile(r"\$[0-9]+\.[0-9]{4} at list price, [0-9]+ requests, [0-9]+ images answered")


class CheckRecordingTest(Case):
    def setUp(self):
        super().setUp()
        self.record("fall-through-bug")
        self.path = self.root / "docs" / "run-it" / "vision" / "fall-through-bug.json"

    def check(self, path=None, sample="fall-through-bug"):
        return runit.check_recording(path or self.path, sample_id=sample, root=self.root)

    def test_a_recording_of_the_sample_passes(self):
        self.assertEqual(self.check(), [])

    def test_a_recording_for_another_sample_is_refused(self):
        self.assertEqual(len(self.check(sample="clean")), 1)
        self.assertIn("not 'clean'", self.check(sample="clean")[0])

    def test_an_id_outside_the_manifest_is_refused(self):
        self.assertIn("no sample named", self.check(sample="other")[0])
        self.assertIn("not a sample id", self.check(sample="../x")[0])

    def test_a_recording_with_no_answers_is_refused(self):
        doc = json.loads(self.path.read_text())
        doc["answers"] = []
        self.path.write_text(json.dumps(doc))
        self.assertEqual(self.check(), ["the recording holds no answers"])

    def test_anything_that_is_not_a_usable_recording_is_refused(self):
        doc = json.loads(self.path.read_text())
        cases = {
            "not json": b"{",
            "extra field": json.dumps({**doc, "extra": 1}).encode(),
            "nan": self.path.read_bytes().replace(b'"answers"', b'"x": NaN, "answers"', 1),
            "answered twice": json.dumps({**doc, "answers": doc["answers"] + doc["answers"][:1]}).encode(),
        }
        for name, raw in cases.items():
            with self.subTest(name):
                bad = self.tmp / f"{name}.json"
                bad.write_bytes(raw)
                found = self.check(bad)
                self.assertEqual(len(found), 1)
                self.assertIn("cannot be used", found[0])
        link = self.tmp / "link.json"
        os.symlink(self.path, link)
        self.assertIn("not a file", self.check(link)[0])
        self.assertIn("not a file", self.check(self.tmp / "missing.json")[0])

    def test_the_command_line_says_refused_or_may_be_proposed(self):
        out, err = io.StringIO(), io.StringIO()
        real = runit.check_recording
        here = lambda p, sample_id: real(p, sample_id=sample_id, root=self.root)  # noqa: E731
        with mock.patch.object(runit, "check_recording", here), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(runit.main(["check-recording", str(self.path), "--sample", "fall-through-bug"]), 0)
            self.assertEqual(runit.main(["check-recording", str(self.path), "--sample", "clean"]), 1)
        self.assertIn("may be proposed", out.getvalue())
        self.assertIn("run test-1", out.getvalue())
        self.assertIn("refused: the recording is for", err.getvalue())


class SpendLineTest(unittest.TestCase):
    """`record` prints what was sent, whether or not the recording was written, in the form the
    workflow reads."""

    def run_main(self, fake):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(runit, "record", fake), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = runit.main(["record", "--sample", "clean", "--out", "x.json", "--run", "123"])
        return code, out.getvalue(), err.getvalue()

    def test_a_recording_prints_its_spend(self):
        code, out, _ = self.run_main(lambda *a, **kw: Path("x.json"))
        self.assertEqual(code, 0)
        line = next(l for l in out.splitlines() if l.startswith("spend: "))
        self.assertRegex(line[len("spend: "):], f"^{SPEND.pattern}$")
        self.assertIn("recorded: x.json", out)

    def test_a_failed_recording_still_prints_its_spend(self):
        def fail(*a, **kw):
            raise runit.RunItError("no")
        code, out, err = self.run_main(fail)
        self.assertEqual(code, 2)
        self.assertRegex(out, r"(?m)^spend: \$0\.0000 at list price")
        self.assertNotIn("recorded:", out)
        self.assertIn("error: no", err)

    def test_a_bad_run_id_records_nothing(self):
        called = []
        out = io.StringIO()
        with mock.patch.object(runit, "record", lambda *a, **kw: called.append(1)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(runit.main(["record", "--sample", "clean", "--out", "x", "--run", "a b"]), 2)
        self.assertEqual(called, [])


class WorkflowTest(unittest.TestCase):
    """What run-it-record.yml must keep: Sean dispatches it on main, the job holding the key writes
    nothing and is capped, the job that writes holds no key and runs nothing from the sample, and
    nothing is pushed to main."""

    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.doc = yaml.safe_load(cls.text)
        cls.on = cls.doc.get("on", cls.doc.get(True))

    def test_only_a_dispatch_of_a_manifest_sample_starts_it(self):
        self.assertEqual(list(self.on), ["workflow_dispatch"])
        inputs = self.on["workflow_dispatch"]["inputs"]
        self.assertEqual(set(inputs), {"sample", "sam_usd_cap"})
        manifest = json.loads((REPO / runit.MANIFEST).read_text())
        self.assertEqual(inputs["sample"]["options"], [s["id"] for s in manifest["samples"] if s["head"] != "recorded-fix"])
        self.assertEqual(self.doc["permissions"], {})
        self.assertEqual(self.doc["concurrency"], {"group": "run-it-record", "cancel-in-progress": False})
        for job in self.doc["jobs"].values():
            self.assertIn("github.ref == 'refs/heads/main'", job["if"])

    def test_the_record_job_holds_the_key_writes_nothing_and_is_capped(self):
        job = self.doc["jobs"]["record"]
        self.assertEqual(job["environment"], "main-only")
        self.assertEqual(job["permissions"], {"contents": "read"})
        self.assertLessEqual(job["timeout-minutes"], 30)
        body = yaml.safe_dump(job)
        self.assertNotIn("github.token", body)
        self.assertIn("--require-sandbox", body)
        self.assertEqual(set(re.findall(r"secrets\.([A-Z_]+)", body)), {"MODEL_API_KEY"})
        steps = job["steps"]
        self.assertIn("Check the inputs", steps[0]["name"])
        self.assertIn("at most 2", steps[0]["run"])
        self.assertIn("<= 2", steps[0]["run"])
        rec = next(s for s in steps if "runit record" in s.get("run", ""))
        self.assertLess(rec["run"].index('export EXPECTRAIL_SAM_USD_CAP="$CAP"'), rec["run"].index("runit record"))
        for step in steps:
            if step.get("uses", "").startswith("actions/checkout"):
                self.assertEqual(step["with"]["persist-credentials"], False)

    def test_the_propose_job_holds_no_key_and_runs_nothing_from_the_sample(self):
        job = self.doc["jobs"]["propose"]
        self.assertEqual(job["permissions"], {"contents": "write"})
        self.assertNotIn("environment", job)
        self.assertEqual(job["needs"], "record")
        self.assertLessEqual(job["timeout-minutes"], 5)
        body = yaml.safe_dump(job)
        for never in ("godot", "harness", "pip install", "get-godot", "apt-install", "secrets.", "gh pr",
                      "pull-requests"):
            self.assertNotIn(never, body)
        commands = "\n".join(s.get("run", "") for s in job["steps"])
        self.assertNotRegex(commands, r"(?m)^\s*python3? -m expectrail\.runit (record|run)\b")
        steps = job["steps"]
        self.assertIn("Check the inputs", steps[0]["name"])
        check = next(i for i, s in enumerate(steps) if "expectrail.runit check-recording" in s.get("run", ""))
        push = next(i for i, s in enumerate(steps) if "git push" in s.get("run", ""))
        self.assertLess(check, push)
        self.assertIn('HEAD:refs/heads/${branch}"', steps[push]["run"])
        self.assertIn('branch="run-it-vision/${SAMPLE}-${GITHUB_RUN_ID}"', steps[push]["run"])
        self.assertNotRegex(steps[push]["run"], r"push[^\n]*\bmain\b")

    def test_inputs_reach_shells_only_through_the_environment(self):
        for job in self.doc["jobs"].values():
            for step in job["steps"]:
                self.assertNotRegex(step.get("run", ""), r"\$\{\{")
        self.assertIn("^[a-z0-9-]{1,40}$", self.text)

    def test_actions_are_pinned(self):
        for job in self.doc["jobs"].values():
            for step in job["steps"]:
                uses = step.get("uses", "")
                if uses and not uses.startswith("./"):
                    self.assertRegex(uses, r"@[0-9a-f]{40}$")

    def test_the_spend_pattern_matches_the_one_the_workflow_reads(self):
        rec = next(s for s in self.doc["jobs"]["record"]["steps"] if "runit record" in s.get("run", ""))
        bash = re.search(r'\[\[ "\$spend" =~ \^(.*)\$ \]\]', rec["run"]).group(1)
        self.assertEqual(bash.replace("\\ ", " "), SPEND.pattern)


if __name__ == "__main__":
    unittest.main()
