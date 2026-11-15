"""jit.yml's candidate input (#285, step 6): the model shown the candidate patch, or given no byte of it.

``shown`` (the default) leaves every job as it was. ``withheld`` passes ``--withhold-candidate`` to propose,
revise and every replay, and has repro-score count only records made that way (``--candidate withheld``).
The known-bugs bench is registered with the candidate shown and refuses ``withheld``. repro-score also
reads the committed screen record (``--screen``).

The structure is read from the workflow file; each job's shell step is run with bash and a stand-in for
``python`` that records how it was called, so no game, model or SAM is involved. The argument lists the
steps build are then parsed by the real command lines, and repro-score's is run for real on an empty
records folder. Nothing here runs a workflow."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from expectrail.jit import cli
from expectrail.jit import offer as offer_mod
from expectrail.repro import __main__ as repro_main

REPO = Path(__file__).resolve().parents[1]
WF = REPO / ".github" / "workflows" / "jit.yml"
PX = offer_mod.PIXEL
SCREEN = "bench/jit/public/screen.json"

# The jobs that give the model something or replay what it proposed, and the step that does it.
MODEL_STEPS = {
    "propose": "Propose checks",
    "replay": "Replay, filter, run, assess",
    "revise": "Revise the rejected checks",
    "replay-final": "Replay the revised proposal",
    "pixel-judge": "Judge the pixel checks",
}


def load() -> dict:
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def step(job: dict, name_part: str) -> dict:
    return next(s for s in job["steps"] if name_part in (s.get("name") or ""))


# Records each call with its arguments quoted (%q), so shlex gives back exactly the arguments passed.
FAKE_PYTHON = """#!/bin/bash
{ printf '%q ' "$@"; echo; } >> "$CALLS"
case "$*" in
  -c*) echo stub ;;
  *"jit.cli pixel-budget"*) echo 1.2500 ;;
esac
exit 0
"""


class Scratch(unittest.TestCase):
    def setUp(self):
        self.wf = load()
        self.jobs = self.wf["jobs"]
        self.dir = Path(tempfile.mkdtemp(prefix="jit-cand-wf-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        bindir = self.dir / "bin"
        bindir.mkdir()
        fake = bindir / "python"
        fake.write_text(FAKE_PYTHON)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        self.calls = self.dir / "calls.txt"
        self.out = self.dir / "github-output.txt"
        self.env = {"PATH": f"{bindir}:{os.environ['PATH']}", "CALLS": str(self.calls), "CASE": "c1",
                    "BASE": "bugs/x.patch", "CANDIDATE": "bench/c.patch", "REPORT": "bench/r.txt",
                    "BUDGET": "2", "GITHUB_RUN_ID": "7", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "abc",
                    "GITHUB_STEP_SUMMARY": str(self.dir / "summary.md"), "GITHUB_OUTPUT": str(self.out),
                    "HOME": str(self.dir)}

    def run_step(self, run: str, ok: bool = True, **env) -> list[str]:
        done = subprocess.run(["bash", "-e", "-c", run], cwd=self.dir, env={**self.env, **env},
                              capture_output=True, text=True, timeout=60)
        if ok:
            self.assertEqual(done.returncode, 0, done.stderr)
        else:
            self.assertNotEqual(done.returncode, 0, "the step was expected to refuse")
            self.stderr = done.stdout + done.stderr
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def touch(self, rel: str, text: str = "{}"):
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def reset(self):
        shutil.rmtree(self.dir / "runs", ignore_errors=True)
        self.calls.unlink(missing_ok=True)
        self.out.unlink(missing_ok=True)

    def prepare(self, job: str):
        """The files each job's step needs before it calls the command line it is tested for."""
        if job == "replay-final":
            self.touch("runs/jit-proposal-2/jit-proposal.json")
            self.touch("runs/jit-proposal-2/revised.txt", "revised=true\n")
        if job == "pixel-judge":
            self.touch("runs/pixel-answers/answers.json")
            self.touch("runs/jit-proposal-2/jit-proposal.json")
            (self.dir / "runs/captured/pixel-capture").mkdir(parents=True, exist_ok=True)

    def model_call(self, job: str, setting: str, offer: str = offer_mod.EVIDENCE) -> str:
        self.reset()
        self.prepare(job)
        run = step(self.jobs[job], MODEL_STEPS[job])["run"]
        calls = self.run_step(run, OFFER=PX if job == "pixel-judge" else offer, CANDIDATE_TO_MODEL=setting)
        [call] = [c for c in calls if c.split()[2:3] in (["propose"], ["revise"], ["run"])]
        return call


class TheInput(Scratch):
    def test_the_input_is_shown_or_withheld_and_shown_by_default(self):
        on = self.wf[True] if True in self.wf else self.wf["on"]
        inp = on["workflow_dispatch"]["inputs"]["candidate"]
        self.assertEqual(inp["type"], "choice")
        self.assertEqual(inp["options"], ["shown", "withheld"])
        self.assertEqual(inp["default"], "shown")

    def test_plan_hands_the_setting_to_every_job_that_uses_it(self):
        self.assertEqual(self.jobs["plan"]["outputs"]["candidate"], "${{ steps.plan.outputs.candidate }}")
        self.assertEqual(self.jobs["plan"]["env"]["CANDIDATE_TO_MODEL"], "${{ inputs.candidate || 'shown' }}")
        for job in MODEL_STEPS:
            with self.subTest(job=job):
                self.assertEqual(self.jobs[job]["env"]["CANDIDATE_TO_MODEL"], "${{ needs.plan.outputs.candidate }}")
        score_env = step(self.jobs["repro-score"], "Score the reproduction bench")["env"]
        self.assertEqual(score_env["CANDIDATE_TO_MODEL"], "${{ needs.plan.outputs.candidate }}")

    def test_jobs_that_neither_ask_the_model_nor_replay_its_checks_do_not_take_it(self):
        for job in ("rehearsal", "measure", "pixel-ask", "score"):
            with self.subTest(job=job):
                self.assertNotIn("CANDIDATE_TO_MODEL", json.dumps(self.jobs[job]))
                self.assertNotIn("withhold", json.dumps(self.jobs[job]))

    def test_nothing_else_changed_what_the_workflow_may_do(self):
        text = WF.read_text(encoding="utf-8")
        self.assertEqual(text.count("permissions:"), 1)
        self.assertIn("permissions:\n  contents: read\n", text)
        self.assertNotIn("pull_request_target", text)
        self.assertNotIn("id-token", text)
        # The environment is held only by the jobs that held it before this input.
        held = sorted(j for j, d in self.jobs.items() if "environment" in d)
        self.assertEqual(held, ["pixel-ask", "propose", "revise"])


class ThePlan(Scratch):
    def plan(self, ok: bool = True, **env) -> dict:
        self.reset()
        run = step(self.jobs["plan"], "Plan the cases")["run"]
        self.run_step(run, ok=ok, **{"OFFER": "baseline", "CANDIDATE_TO_MODEL": "shown",
                                     "GITHUB_REF": "refs/heads/main", **env})
        out = {}
        if self.out.exists():
            for line in self.out.read_text().splitlines():
                k, _, v = line.partition("=")
                out[k] = v
        return out

    def test_repro_mode_takes_either_setting(self):
        for setting in ("shown", "withheld"):
            with self.subTest(setting=setting):
                self.assertEqual(self.plan(MODE="repro", CANDIDATE_TO_MODEL=setting)["candidate"], setting)

    def test_live_mode_takes_withheld(self):
        out = self.plan(MODE="live", CANDIDATE_TO_MODEL="withheld", CASE="air-jump",
                        BASE="bugs/reported/air-jump.patch", CANDIDATE="bench/jit/public/no-fix.patch",
                        REPORT="bugs/reported/air-jump.txt")
        self.assertEqual(out["candidate"], "withheld")

    def test_anything_else_is_refused(self):
        for bad in ("", "Withheld", "hidden", "withheld; rm -rf /", "shown\nwithheld"):
            with self.subTest(bad=bad):
                self.plan(ok=False, MODE="repro", CANDIDATE_TO_MODEL=bad)
                self.assertIn("candidate must be shown or withheld", self.stderr)

    def test_the_known_bugs_bench_refuses_withheld(self):
        self.plan(ok=False, MODE="bench", CANDIDATE_TO_MODEL="withheld")
        self.assertIn("registered with the candidate shown", self.stderr)
        self.assertNotIn("bench-check", self.calls.read_text() if self.calls.exists() else "")

    def test_the_known_bugs_bench_still_runs_shown(self):
        self.plan(MODE="bench")
        self.assertIn("-m expectrail.jit.cli bench-check", self.calls.read_text())


class TheModelSteps(Scratch):
    def test_withheld_reaches_propose_revise_and_every_replay(self):
        for job in MODEL_STEPS:
            with self.subTest(job=job):
                call = self.model_call(job, "withheld")
                self.assertEqual(shlex.split(call).count("--withhold-candidate"), 1, call)

    def test_shown_leaves_every_call_as_it_was(self):
        for job in MODEL_STEPS:
            with self.subTest(job=job):
                self.assertNotIn("--withhold-candidate", self.model_call(job, "shown"))

    def test_an_unexpected_value_never_withholds_by_accident_nor_reaches_the_command_line(self):
        # plan refuses anything else; were it to slip through, the steps treat it as shown.
        for job in MODEL_STEPS:
            with self.subTest(job=job):
                call = self.model_call(job, "--withhold-candidate --x")
                self.assertNotIn("--withhold-candidate", call)
                self.assertNotIn("--x", call)

    def test_replay_final_keeping_the_first_round_needs_no_setting(self):
        # Nothing revised and no pixel setting: the first round's record, made under the same setting.
        self.reset()
        self.touch("runs/jit-proposal-2/revised.txt", "revised=false\n")
        self.touch("runs/jit-round1/jit-run.json", '{"round": 1}')
        calls = self.run_step(step(self.jobs["replay-final"], MODEL_STEPS["replay-final"])["run"],
                              OFFER=offer_mod.EVIDENCE, CANDIDATE_TO_MODEL="withheld")
        self.assertFalse([c for c in calls if "jit.cli run" in c])
        self.assertEqual((self.dir / "runs/jit/c1/jit-run.json").read_text(), '{"round": 1}')

    def test_the_real_command_lines_accept_what_the_steps_build(self):
        for job in MODEL_STEPS:
            for setting in ("shown", "withheld"):
                with self.subTest(job=job, setting=setting):
                    argv = shlex.split(self.model_call(job, setting))[2:]   # past "-m expectrail.jit.cli"
                    args = self.parse(argv)
                    self.assertEqual(cli._candidate(args), setting)

    def parse(self, argv: list[str]):
        captured = {}

        def fake_main_parse(self_ap, args=None, namespace=None):
            ns = original(self_ap, args, namespace)
            captured["ns"] = ns
            raise SystemExit(0)

        import argparse
        original = argparse.ArgumentParser.parse_args
        argparse.ArgumentParser.parse_args = fake_main_parse
        try:
            with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit) as stop:
                cli.main(argv)
        finally:
            argparse.ArgumentParser.parse_args = original
        self.assertEqual(stop.exception.code, 0, err.getvalue())
        return captured["ns"]


class TheScore(Scratch):
    def score_call(self, setting: str) -> str:
        self.reset()
        self.touch("runs/artifacts/jit-repro-air-jump/jit-run.json")
        self.touch("runs/repro-score/repro-score.md", "# score\n")   # what the stand-in does not write
        run = step(self.jobs["repro-score"], "Score the reproduction bench")["run"]
        calls = self.run_step(run, OFFER=PX, CANDIDATE_TO_MODEL=setting)
        [call] = [c for c in calls if c.startswith("-m expectrail.repro score")]
        return call

    def test_the_score_counts_the_runs_setting_and_reads_the_screen_record(self):
        for setting in ("shown", "withheld"):
            with self.subTest(setting=setting):
                argv = shlex.split(self.score_call(setting))
                self.assertEqual(argv[argv.index("--candidate") + 1], setting)
                self.assertEqual(argv[argv.index("--screen") + 1], SCREEN)

    def test_the_score_command_runs_with_those_arguments(self):
        self.assertTrue((REPO / SCREEN).is_file())
        argv = shlex.split(self.score_call("withheld"))[3:]   # past "-m expectrail.repro score"
        records = self.dir / "records"
        records.mkdir()
        out = self.dir / "score"
        i = argv.index("--records")
        argv[i + 1] = str(records)
        argv[argv.index("--out") + 1] = str(out)
        argv[argv.index("--screen") + 1] = str(REPO / SCREEN)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(repro_main.main(["score", *argv]), 0)
        record = json.loads((out / "repro-score.json").read_text())
        self.assertEqual(record["candidate"], "withheld")
        self.assertEqual(record["totals"]["reproduced"], 0)
        self.assertIn("screenOnly", record["totals"])
        self.assertIn("Candidate: **withheld**", (out / "repro-score.md").read_text())


if __name__ == "__main__":
    unittest.main()
