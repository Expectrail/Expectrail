"""jit.yml's sam_every input (#286): one frame plan for the capture, asking and judging jobs.

The structure is read from the workflow file and each step's shell is run with bash and a stand-in for
``python`` that records how it was called (tests/test_jit_candidate_workflow.py), so no game, model or
SAM is involved and nothing is dispatched."""
from __future__ import annotations

import json
import shlex
import unittest

from expectrail.jit import offer as offer_mod
from tests.test_jit_candidate_workflow import Scratch, step

PX = offer_mod.PIXEL
# The jobs of the pixel setting's three, the step in each that calls the command line, and the call.
PIXEL_STEPS = {
    "replay-final": ("Replay the revised proposal", "jit.cli run"),
    "pixel-ask": ("Ask SAM", "jit.cli pixel-ask"),
    "pixel-judge": ("Judge the pixel checks", "jit.cli run"),
}
BAD = ("0", "61", "100", "ten", "1e1", "10 --sam-live", "10; echo x", "-5", " 10")


class TheInput(Scratch):
    def test_the_input_defaults_to_10(self):
        on = self.wf[True] if True in self.wf else self.wf["on"]
        self.assertEqual(on["workflow_dispatch"]["inputs"]["sam_every"]["default"], "10")
        self.assertEqual(self.jobs["plan"]["env"]["SAM_EVERY"], "${{ inputs.sam_every || '10' }}")
        self.assertEqual(self.jobs["plan"]["outputs"]["sam_every"], "${{ steps.plan.outputs.sam_every }}")

    def test_the_three_pixel_jobs_take_the_plan_s_value_and_no_other_job_does(self):
        for job, d in self.jobs.items():
            with self.subTest(job=job):
                if job in PIXEL_STEPS:
                    self.assertEqual(d["env"]["SAM_EVERY"], "${{ needs.plan.outputs.sam_every }}")
                elif job != "plan":
                    self.assertNotIn("SAM_EVERY", json.dumps(d))


class ThePlan(Scratch):
    def plan(self, ok=True, **env):
        self.reset()
        self.run_step(step(self.jobs["plan"], "Plan the cases")["run"], ok=ok,
                      **{"MODE": "repro", "OFFER": PX, "CANDIDATE_TO_MODEL": "shown", "GITHUB_REF": "refs/heads/main",
                         **env})
        return dict(line.partition("=")[::2] for line in self.out.read_text().splitlines()) if self.out.exists() else {}

    def test_one_to_sixty_pass_through(self):
        for value in ("1", "10", "20", "59", "60"):
            with self.subTest(value=value):
                self.assertEqual(self.plan(SAM_EVERY=value)["sam_every"], value)

    def test_unset_is_10(self):
        self.assertEqual(self.plan()["sam_every"], "10")

    def test_anything_else_is_refused(self):
        for bad in BAD:
            with self.subTest(bad=bad):
                self.plan(ok=False, SAM_EVERY=bad)
                self.assertIn("sam_every must be a whole number from 1 to 60", self.stderr)


class TheSteps(Scratch):
    def prepare(self, job):
        if job == "replay-final":
            self.touch("runs/jit-proposal-2/jit-proposal.json")
            self.touch("runs/jit-proposal-2/revised.txt", "revised=false\n")
        if job == "pixel-ask":
            (self.dir / "runs/captured/pixel-capture/pixel-reference").mkdir(parents=True, exist_ok=True)
        if job == "pixel-judge":
            self.touch("runs/pixel-answers/answers.json")
            self.touch("runs/jit-proposal-2/jit-proposal.json")
            (self.dir / "runs/captured/pixel-capture").mkdir(parents=True, exist_ok=True)

    def call(self, job, ok=True, **env):
        self.reset()
        self.prepare(job)
        name, command = PIXEL_STEPS[job]
        calls = self.run_step(step(self.jobs[job], name)["run"], ok=ok, **{"OFFER": PX, **env})
        return [c for c in calls if command in c]

    def test_each_job_passes_the_same_value_once(self):
        for job in PIXEL_STEPS:
            for value in ("10", "20", "60"):
                with self.subTest(job=job, value=value):
                    [call] = self.call(job, SAM_EVERY=value)
                    argv = shlex.split(call)
                    self.assertEqual(argv.count("--sam-every"), 1, call)
                    self.assertEqual(argv[argv.index("--sam-every") + 1], value)

    def test_a_bad_value_stops_the_step_before_any_call(self):
        for job in PIXEL_STEPS:
            for bad in BAD:
                with self.subTest(job=job, bad=bad):
                    self.assertEqual(self.call(job, ok=False, SAM_EVERY=bad), [])

    def test_without_the_pixel_setting_replay_final_takes_no_plan(self):
        self.reset()
        self.touch("runs/jit-proposal-2/jit-proposal.json")
        self.touch("runs/jit-proposal-2/revised.txt", "revised=true\n")
        calls = self.run_step(step(self.jobs["replay-final"], "Replay the revised proposal")["run"],
                              OFFER=offer_mod.EVIDENCE, SAM_EVERY="20")
        [run] = [c for c in calls if "jit.cli run" in c]
        self.assertNotIn("--sam-every", run)


if __name__ == "__main__":
    unittest.main()
