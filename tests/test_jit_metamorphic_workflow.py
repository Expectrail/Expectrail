"""jit.yml's metamorphic checks (#675, piece 3): on in every rehearsal, and a dispatch input for live runs.

The structure is read from the workflow file and each step's shell is run with bash and a stand-in for
``python`` that records how it was called (tests/test_jit_candidate_workflow.py), so no game, model or
SAM is involved and nothing is dispatched. The metamorphic rows are advisory and need no model, so turning
them on adds replays, never spend."""
from __future__ import annotations

import json
import shlex
import unittest

from expectrail.jit import offer as offer_mod
from tests.test_jit_candidate_workflow import Scratch, step

PX = offer_mod.PIXEL
# Every job that replays a proposal through `jit.cli run` on a dispatch, and the step that does it.
RUN_STEPS = {
    "replay": "Replay, filter, run, assess",
    "replay-final": "Replay the revised proposal",
    "pixel-judge": "Judge the pixel checks",
}


def on(wf):
    return wf[True] if True in wf else wf["on"]


class TheRehearsal(Scratch):
    def test_every_rehearsal_case_offers_the_metamorphic_checks(self):
        run = step(self.jobs["rehearsal"], "Replay the stand-in proposal")["run"]
        self.reset()
        self.touch("runs/jit/gun-cooldown-long-comment-only/jit-report.md", "")
        calls = self.run_step(run, CASE="gun-cooldown-long-comment-only", REPORT="bench/r.txt", BASE="bugs/x.patch")
        [call] = [c for c in calls if "jit.cli run" in c]
        self.assertEqual(shlex.split(call).count("--metamorphic"), 1, call)

    def test_the_rehearsal_check_asks_for_the_metamorphic_rows(self):
        run = step(self.jobs["rehearsal"], "Check the rehearsal reached what it rehearses")["run"]
        self.assertIn("tools.jit_rehearsal_check --metamorphic", run)


class TheInput(Scratch):
    def test_the_input_is_a_boolean_off_by_default(self):
        spec = on(self.wf)["workflow_dispatch"]["inputs"]["metamorphic"]
        self.assertEqual(spec["type"], "boolean")
        self.assertIs(spec["default"], False)
        self.assertEqual(self.jobs["plan"]["outputs"]["metamorphic"], "${{ steps.plan.outputs.metamorphic }}")

    def test_only_the_replaying_jobs_take_the_plan_s_value(self):
        for job, d in self.jobs.items():
            with self.subTest(job=job):
                if job in RUN_STEPS:
                    self.assertEqual(d["env"]["METAMORPHIC"], "${{ needs.plan.outputs.metamorphic }}")
                elif job != "plan":
                    self.assertNotIn("METAMORPHIC", json.dumps(d))


class ThePlan(Scratch):
    def plan(self, ok=True, **env):
        self.reset()
        self.run_step(step(self.jobs["plan"], "Plan the cases")["run"], ok=ok,
                      **{"MODE": "repro", "OFFER": "baseline", "CANDIDATE_TO_MODEL": "withheld",
                         "GITHUB_REF": "refs/heads/main", **env})
        return dict(line.partition("=")[::2] for line in self.out.read_text().splitlines()) if self.out.exists() else {}

    def test_true_and_false_pass_through_and_unset_is_false(self):
        self.assertEqual(self.plan(METAMORPHIC="true")["metamorphic"], "true")
        self.assertEqual(self.plan(METAMORPHIC="false")["metamorphic"], "false")
        self.assertEqual(self.plan()["metamorphic"], "false")

    def test_anything_else_is_refused(self):
        for bad in ("yes", "1", "True", "true --x", "true; echo x"):
            with self.subTest(bad=bad):
                self.plan(ok=False, METAMORPHIC=bad)
                self.assertIn("metamorphic must be true or false", self.stderr)

    def test_the_known_bugs_bench_refuses_it(self):
        self.plan(ok=False, MODE="bench", METAMORPHIC="true", CANDIDATE_TO_MODEL="shown")
        self.assertIn("the known-bugs bench is registered without metamorphic checks", self.stderr)


class TheSteps(Scratch):
    def call(self, job, **env):
        self.reset()
        self.prepare(job)
        if job == "replay":
            self.touch("runs/jit-proposal/jit-proposal.json")
        calls = self.run_step(step(self.jobs[job], RUN_STEPS[job])["run"],
                              **{"OFFER": PX if job == "pixel-judge" else offer_mod.EVIDENCE, **env})
        [call] = [c for c in calls if "jit.cli run" in c]
        return shlex.split(call)

    def test_each_replay_passes_the_flag_once_when_on(self):
        for job in RUN_STEPS:
            with self.subTest(job=job):
                self.assertEqual(self.call(job, METAMORPHIC="true").count("--metamorphic"), 1)

    def test_no_replay_passes_it_when_off_or_unset(self):
        for job in RUN_STEPS:
            for env in ({"METAMORPHIC": "false"}, {}):
                with self.subTest(job=job, env=env):
                    self.assertNotIn("--metamorphic", self.call(job, **env))


if __name__ == "__main__":
    unittest.main()
