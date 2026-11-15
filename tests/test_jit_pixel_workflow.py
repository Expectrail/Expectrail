"""jit.yml under the pixel setting (#286): three jobs, so SAM's key never meets the change's code.

replay-final replays the pixel checks' probes with frames and keeps them (no secret); pixel-ask asks SAM
about the kept frames and runs no game (the key, in main-only, within what the change's cap has left);
pixel-judge judges them from the frames and the answers (no secret), and its record is the result.

The structure is read from the workflow file. The branching in each job's shell step is run here with
bash and a stand-in for ``python`` that records how it was called, so no game, model or SAM is involved;
``pixel-budget`` (expectrail/jit/pixel_jobs.py, ``budget_left``) is run for real. Nothing here runs a
workflow."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from agents.assurance.audit import PERCEPTION
from expectrail.jit import cli
from expectrail.jit import offer as offer_mod
from expectrail.jit.pixel_jobs import budget_left

REPO = Path(__file__).resolve().parents[1]
WF = REPO / ".github" / "workflows" / "jit.yml"
PX = offer_mod.PIXEL
EXAMPLE = REPO / "contracts" / "examples" / "jit-run-pixel.json"


def load():
    text = WF.read_text(encoding="utf-8")
    return text, yaml.safe_load(text)


def dumped(job) -> str:
    return yaml.safe_dump(job, width=1_000_000)


def step_run(job: dict, name_part: str) -> str:
    return next(s["run"] for s in job["steps"] if name_part in (s.get("name") or ""))


def engine(job: dict) -> bool:
    return any(s.get("uses") == "./.github/actions/get-godot" for s in job["steps"])


class TheJobs(unittest.TestCase):
    def setUp(self):
        self.text, self.wf = load()
        self.jobs = self.wf["jobs"]
        on = self.wf[True] if True in self.wf else self.wf["on"]
        self.inputs = on["workflow_dispatch"]["inputs"]

    def test_the_setting_can_be_dispatched(self):
        self.assertIn(PX, self.inputs["offer"]["options"])
        self.assertEqual(self.inputs["offer"]["default"], "baseline")
        plan = next(s["run"] for s in self.jobs["plan"]["steps"] if s.get("id") == "plan")
        self.assertIn("signals-reach-evidence-pixel)$", plan)
        self.assertIn("registered under the baseline offer", plan)   # the known-bugs bench still refuses it

    def test_the_key_is_held_only_by_jobs_that_run_no_game_in_main_only(self):
        for name, job in self.jobs.items():
            if "secrets." in dumped(job):
                self.assertEqual(job.get("environment"), "main-only", name)
                self.assertFalse(engine(job), name)
                self.assertNotIn("jit.cli run", dumped(job), name)
        holders = sorted(n for n, j in self.jobs.items() if "secrets." in dumped(j))
        self.assertEqual(holders, ["pixel-ask", "propose", "revise"])

    def test_pixel_ask_installs_nothing_and_holds_the_key_only_in_its_asking_step(self):
        job = self.jobs["pixel-ask"]
        self.assertIn(f"needs.plan.outputs.offer == '{PX}'", job["if"])
        self.assertEqual(job["needs"], ["plan", "replay-final"])
        self.assertFalse(any("apt-install" in (s.get("uses") or "") for s in job["steps"]))
        self.assertNotIn("CANDIDATE", dumped(job))
        self.assertNotIn("BASE", job["env"])
        with_key = [s for s in job["steps"] if "MODEL_API_KEY" in (s.get("env") or {})]
        self.assertEqual([s.get("name") for s in with_key], ["Ask SAM 3.1 about the captured frames (one image a judged frame)"])
        run = with_key[0]["run"]
        self.assertIn("python -m expectrail.jit.cli pixel-budget", run)
        self.assertIn('export EXPECTRAIL_SAM_USD_CAP="$left"', run)
        self.assertIn('--budget-usd "$left" --sam-live', run)
        self.assertIn(".github/workflows/jit.yml#pixel-ask", PERCEPTION)

    def test_replay_final_captures_under_the_pixel_setting_and_holds_no_secret(self):
        job = self.jobs["replay-final"]
        self.assertNotIn("secrets.", dumped(job))
        self.assertNotIn("environment", job)
        run = step_run(job, "Replay the revised proposal")
        self.assertIn("--observer sam-3.1-anchor --pixel-capture runs/pixel-capture", run)
        # The capture job is given no way to ask SAM. --sam-every (#286) is the frame plan, not a way to ask.
        for way in ("--sam-answers", "--sam-live", "--sam-run"):
            self.assertNotIn(way, run)
        upload = next(s for s in job["steps"] if s.get("name") == "Keep the record")
        self.assertEqual(upload["with"]["name"],
                         f"jit-${{{{ matrix.c.case }}}}${{{{ needs.plan.outputs.offer == '{PX}' && '-captured' || '' }}}}")
        self.assertIn("runs/pixel-capture/", upload["with"]["path"].split())
        install = next(s for s in job["steps"] if s.get("uses") == "./.github/actions/apt-install")
        self.assertIn("xvfb", install["with"]["packages"])
        self.assertIn(f"needs.plan.outputs.offer == '{PX}'", install["with"]["packages"])

    def test_pixel_judge_reads_answers_never_asks_and_writes_the_result(self):
        job = self.jobs["pixel-judge"]
        self.assertNotIn("secrets.", dumped(job))
        self.assertNotIn("environment", job)
        self.assertTrue(job["if"].startswith("always() && "))
        self.assertIn(f"needs.plan.outputs.offer == '{PX}'", job["if"])
        run = step_run(job, "Judge the pixel checks")
        self.assertIn("--sam-answers runs/pixel-answers/answers.json --pixel-replays runs/captured/pixel-capture", run)
        self.assertNotIn("--sam-live", run)
        self.assertNotIn("--pixel-capture", run)
        upload = next(s for s in job["steps"] if s.get("name") == "Keep the record")
        self.assertEqual(upload["with"]["name"], "jit-${{ matrix.c.case }}")
        answers = next(s for s in job["steps"] if "pixel-answers" in json.dumps(s.get("with") or {})
                       and "download-artifact" in (s.get("uses") or ""))
        self.assertTrue(answers.get("continue-on-error"))

    def test_the_score_waits_for_the_judge_and_reads_only_results(self):
        job = self.jobs["repro-score"]
        self.assertIn("pixel-judge", job["needs"])
        run = step_run(job, "Score the reproduction bench")
        self.assertIn('*-round1 || "$name" == *-captured || "$name" == *-pixel-answers', run)

    def test_nothing_else_changed_what_the_workflow_may_do(self):
        self.assertEqual(self.text.count("permissions:"), 1)
        self.assertIn("permissions:\n  contents: read\n", self.text)
        self.assertNotIn("pull_request_target", self.text)
        self.assertNotIn("id-token", self.text)
        self.assertNotIn("offer", json.dumps(self.jobs["rehearsal"]))


FAKE_PYTHON = """#!/bin/bash
printf '%s\\n' "$*" >> "$CALLS"
case "$*" in
  -c*) echo stub ;;
  *"jit.cli pixel-budget"*) echo 1.2500 ;;
esac
exit 0
"""


class TheSteps(unittest.TestCase):
    """Each shell step run with bash, ``python`` standing in, in a scratch folder."""

    def setUp(self):
        _text, wf = load()
        self.jobs = wf["jobs"]
        self.dir = Path(tempfile.mkdtemp(prefix="jit-px-wf-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        bindir = self.dir / "bin"
        bindir.mkdir()
        fake = bindir / "python"
        fake.write_text(FAKE_PYTHON)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        self.calls = self.dir / "calls.txt"
        self.env = {"PATH": f"{bindir}:{os.environ['PATH']}", "CALLS": str(self.calls), "CASE": "c1",
                    "BASE": "bugs/x.patch", "CANDIDATE": "bench/c.patch", "REPORT": "bench/r.txt",
                    "BUDGET": "2", "GITHUB_RUN_ID": "7", "GITHUB_STEP_SUMMARY": str(self.dir / "summary.md"),
                    "HOME": str(self.dir)}

    def run_step(self, run: str, **env) -> list[str]:
        done = subprocess.run(["bash", "-e", "-c", run], cwd=self.dir, env={**self.env, **env},
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def touch(self, rel: str, text: str = "{}"):
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_replay_final_replays_with_capture_under_the_pixel_setting_even_unrevised(self):
        self.touch("runs/jit-proposal-2/jit-proposal.json")
        self.touch("runs/jit-proposal-2/revised.txt", "revised=false\n")
        calls = self.run_step(step_run(self.jobs["replay-final"], "Replay the revised proposal"), OFFER=PX)
        runs = [c for c in calls if "jit.cli run" in c]
        self.assertEqual(len(runs), 1)
        self.assertTrue(runs[0].endswith("--observer sam-3.1-anchor --pixel-capture runs/pixel-capture --sam-every 10"))

    def test_replay_final_keeps_the_first_round_otherwise(self):
        for offer, proposal in ((offer_mod.EVIDENCE, True), (PX, False)):
            with self.subTest(offer=offer, proposal=proposal):
                shutil.rmtree(self.dir / "runs", ignore_errors=True)
                self.calls.unlink(missing_ok=True)
                if proposal:
                    self.touch("runs/jit-proposal-2/jit-proposal.json")
                self.touch("runs/jit-proposal-2/revised.txt", "revised=false\n")
                self.touch("runs/jit-round1/jit-run.json", '{"round": 1}')
                calls = self.run_step(step_run(self.jobs["replay-final"], "Replay the revised proposal"), OFFER=offer)
                self.assertFalse([c for c in calls if "jit.cli run" in c])
                self.assertEqual((self.dir / "runs/jit/c1/jit-run.json").read_text(), '{"round": 1}')

    def test_replay_final_without_the_pixel_setting_never_captures(self):
        self.touch("runs/jit-proposal-2/jit-proposal.json")
        self.touch("runs/jit-proposal-2/revised.txt", "revised=true\n")
        calls = self.run_step(step_run(self.jobs["replay-final"], "Replay the revised proposal"), OFFER=offer_mod.EVIDENCE)
        [run] = [c for c in calls if "jit.cli run" in c]
        self.assertNotIn("--pixel-capture", run)
        self.assertNotIn("--observer", run)

    def test_pixel_ask_asks_nothing_when_nothing_was_captured(self):
        calls = self.run_step(step_run(self.jobs["pixel-ask"], "Ask SAM"))
        self.assertEqual(calls, [])

    def test_pixel_ask_spends_what_the_cap_has_left(self):
        (self.dir / "runs/captured/pixel-capture/pixel-reference").mkdir(parents=True)
        calls = self.run_step(step_run(self.jobs["pixel-ask"], "Ask SAM"))
        self.assertEqual(calls[0], "-m expectrail.jit.cli pixel-budget --record runs/captured/jit/c1/jit-run.json --budget-usd 2")
        self.assertEqual(calls[1], "-m expectrail.jit.cli pixel-ask --replays runs/captured/pixel-capture "
                                   "--out runs/pixel-answers/answers.json --budget-usd 1.2500 --sam-live --sam-every 10")

    def test_pixel_judge_judges_when_it_has_frames_answers_and_the_proposal(self):
        self.touch("runs/pixel-answers/answers.json")
        self.touch("runs/jit-proposal-2/jit-proposal.json")
        (self.dir / "runs/captured/pixel-capture").mkdir(parents=True)
        calls = self.run_step(step_run(self.jobs["pixel-judge"], "Judge the pixel checks"), OFFER=PX)
        [run] = [c for c in calls if "jit.cli run" in c]
        self.assertTrue(run.endswith("--observer sam-3.1-anchor --sam-answers runs/pixel-answers/answers.json "
                                     "--pixel-replays runs/captured/pixel-capture --sam-every 10"))

    def test_pixel_judge_keeps_the_captured_record_without_answers(self):
        for where in ("runs/captured/jit/c1/jit-run.json", "runs/captured/jit-run.json"):
            with self.subTest(where=where):
                shutil.rmtree(self.dir / "runs", ignore_errors=True)
                self.calls.unlink(missing_ok=True)
                self.touch("runs/jit-proposal-2/jit-proposal.json")
                self.touch(where, '{"captured": true}')
                calls = self.run_step(step_run(self.jobs["pixel-judge"], "Judge the pixel checks"), OFFER=PX)
                self.assertFalse([c for c in calls if "jit.cli run" in c])
                self.assertEqual((self.dir / "runs/jit/c1/jit-run.json").read_text(), '{"captured": true}')


class BudgetLeft(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="jit-px-budget-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def record(self, usd=None, edit=None) -> Path:
        doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        if usd is not None:
            doc["spend"]["usd"] = usd
        if edit:
            edit(doc)
        path = self.dir / "jit-run.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def test_the_cap_less_what_the_record_spent(self):
        self.assertEqual(budget_left(self.record(0.3), 2.0), (1.7, None))
        self.assertEqual(budget_left(self.record(0.12345), 2.0), (1.8765, None))

    def test_never_below_nothing_and_never_above_the_cap(self):
        self.assertEqual(budget_left(self.record(5.0), 2.0), (0.0, "the capture run spent the whole cap"))
        self.assertEqual(budget_left(self.record(0.0), 2.0)[0], 2.0)

    def test_an_unreadable_record_leaves_nothing(self):
        cases = {
            "missing": self.dir / "none.json",
            "negative spend": self.record(-1.0),
            "spend as text": self.record("0"),
            "not a record": self.record(edit=lambda d: d.pop("spend")),
        }
        for name, path in cases.items():
            with self.subTest(name):
                left, why = budget_left(path, 2.0)
                self.assertEqual(left, 0.0)
                self.assertTrue(why)
        link = self.dir / "link.json"
        link.symlink_to(self.record(0.1))
        self.assertEqual(budget_left(link, 2.0)[0], 0.0)
        big = self.dir / "big.json"
        big.write_bytes(b" " * (8 * 1024 * 1024 + 1))
        self.assertEqual(budget_left(big, 2.0)[0], 0.0)

    def test_a_cap_that_is_not_a_plain_amount_leaves_nothing(self):
        for cap in (-1.0, float("nan"), float("inf"), True):
            with self.subTest(cap=cap):
                self.assertEqual(budget_left(self.record(0.1), cap)[0], 0.0)

    def test_the_command_prints_the_amount(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(["pixel-budget", "--record", str(self.record(0.5)), "--budget-usd", "2"]), 0)
        self.assertEqual(out.getvalue(), "1.5000\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cli.main(["pixel-budget", "--record", str(self.dir / "none.json"), "--budget-usd", "2"])
        self.assertEqual(out.getvalue(), "0.0000\n")
        self.assertIn("pixel-budget:", err.getvalue())


if __name__ == "__main__":
    unittest.main()
