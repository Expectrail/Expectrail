"""The pressure workflow proposal runs commands the pressure command accepts (#271).

``docs/proposals/271-pressure.yml.txt`` is a workflow Sean reviews and installs himself; it is not an
active workflow. It and ``expectrail/jit/pressure.py`` are edited by different changes, so the proposal
can drift from the command: until November 19 it had no bank step, so as written it would have stopped
on every counting pixel check (#647 added ``--sensor-bank``).

These tests read every ``python3 -m expectrail.jit.pressure`` command in the proposal, put in the values
its declared variables can take, and parse it with pressure's own argument parser. They also check that
the correct-fix steps judge pixel checks with a bank the job calibrates itself on the clean game, before
any frozen evidence is on disk. Nothing here dispatches a workflow or replays the game."""
from __future__ import annotations

import io
import re
import shlex
import unittest
from contextlib import redirect_stderr
from pathlib import Path

import yaml

from expectrail.jit import pressure

REPO = Path(__file__).resolve().parents[1]
PROPOSAL = REPO / "docs" / "proposals" / "271-pressure.yml.txt"
PRESSURE = ["python3", "-m", "expectrail.jit.pressure"]
SENSOR_BANK = ["python3", "-m", "expectrail.jit.cli", "sensor-bank"]
# A value each declared variable can take when the proposal runs; a variable not declared in the job's or
# the step's env is refused, so a command cannot lean on something the job never sets.
SAMPLES = {"REPLAY_CAP": "1024", "SENSOR_EVERY": "10", "SOURCE_RUN": "1", "SOURCE_ARTIFACT": "2"}
VAR = re.compile(r"\$\{?([A-Z_][A-Z0-9_]*)\}?")


def proposal() -> dict:
    return yaml.safe_load(PROPOSAL.read_text(encoding="utf-8"))


def job() -> dict:
    return proposal()["jobs"]["pressure"]


def kinds(step: dict) -> list[str]:
    """The ``kind`` inputs under which the step runs."""
    cond = step.get("if", "")
    if "inputs.kind == 'correct'" in cond:
        return ["correct"]
    if "inputs.kind == 'adversary'" in cond:
        return ["adversary"]
    return ["correct", "adversary"]


def commands(step: dict, head: list[str]) -> list[list[str]]:
    """Every command in the step's ``run`` that starts with ``head``, split into words."""
    text = re.sub(r"\\\n\s*", " ", step.get("run", ""))
    found = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(" ".join(head)):
            words = shlex.split(line.split(">", 1)[0])
            found.append(words)
    return found


def expand(words: list[str], declared: set[str], kind: str) -> list[str]:
    def one(m):
        name = m.group(1)
        if name not in declared:
            raise AssertionError(f"${name} is not declared in the job's or the step's env")
        return kind if name == "KIND" else SAMPLES.get(name, "x")

    return [VAR.sub(one, w) for w in words]


def pressure_runs() -> list[tuple[int, dict, str, list[str]]]:
    """(step index, step, kind, argv) for every pressure command the proposal can run."""
    j = job()
    out = []
    for i, step in enumerate(j["steps"]):
        declared = set(j.get("env", {})) | set(step.get("env", {}))
        for words in commands(step, PRESSURE):
            for kind in kinds(step):
                out.append((i, step, kind, expand(words, declared, kind)[len(PRESSURE):]))
    return out


def flag(argv: list[str], name: str):
    return argv[argv.index(name) + 1] if name in argv else None


class ProposalCommands(unittest.TestCase):
    def test_every_pressure_command_is_one_the_command_accepts(self):
        runs = pressure_runs()
        self.assertGreaterEqual(len(runs), 5)
        for _i, step, kind, argv in runs:
            with self.subTest(step=step.get("name"), kind=kind):
                try:
                    pressure.parse_args(argv)
                except SystemExit as exc:
                    self.fail(f"pressure refuses {argv}: exit {exc.code}")

    def test_the_parser_refuses_what_the_proposal_must_not_do(self):
        for argv in (["adversary", "--sensor-bank", "b.json"],
                     ["correct", "--sensor-every", "0"],
                     ["correct", "--sensor-every", "61"],
                     ["correct", "--execute"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
                pressure.parse_args(argv)

    def test_every_correct_step_that_reads_frozen_checks_is_given_the_calibrated_bank(self):
        bank = self.calibrated_bank()
        judged = [(s, a) for _i, s, k, a in pressure_runs()
                  if k == "correct" and ("--execute" in a or "--preflight" in a)]
        self.assertEqual({("--execute" in a) for _s, a in judged}, {True, False})
        for step, argv in judged:
            with self.subTest(step=step.get("name")):
                self.assertEqual(flag(argv, "--sensor-bank"), bank)
                self.assertEqual(flag(argv, "--sensor-every"), SAMPLES["SENSOR_EVERY"])

    def test_the_adversary_is_never_given_a_bank(self):
        for _i, step, kind, argv in pressure_runs():
            if kind == "adversary":
                with self.subTest(step=step.get("name")):
                    self.assertNotIn("--sensor-bank", argv)

    def calibrated_bank(self) -> str:
        found = [(i, s, w) for i, s in enumerate(job()["steps"]) for w in commands(s, SENSOR_BANK)]
        self.assertEqual(len(found), 1, "one bank step")
        _i, step, words = found[0]
        return flag(words, "--out")


class BankStep(unittest.TestCase):
    def setUp(self):
        self.steps = job()["steps"]
        self.bank = [i for i, s in enumerate(self.steps) if commands(s, SENSOR_BANK)]
        self.assertEqual(len(self.bank), 1)
        self.step = self.steps[self.bank[0]]

    def test_the_bank_is_calibrated_before_any_frozen_evidence_is_downloaded(self):
        download = [i for i, s in enumerate(self.steps) if "download-artifact" in s.get("uses", "")]
        self.assertTrue(download)
        self.assertLess(self.bank[0], min(download))

    def test_the_bank_is_calibrated_on_this_checkout_s_clean_game_with_no_secret(self):
        (words,) = commands(self.step, SENSOR_BANK)
        self.assertNotIn("--game", words)  # the default: game/platformer of the checked-out main
        self.assertNotIn("frozen", " ".join(words))
        self.assertNotIn("secrets.", yaml.safe_dump(self.step))
        self.assertEqual(kinds(self.step), ["correct"])

    def test_the_bank_and_its_work_folder_are_outside_what_pressure_requires_unmodified(self):
        (words,) = commands(self.step, SENSOR_BANK)
        for name in ("--out", "--work"):
            top = flag(words, name).split("/", 1)[0]
            with self.subTest(flag=name):
                self.assertNotIn(top, ("expectrail", "agents", "contracts", "bench"))


class Inputs(unittest.TestCase):
    def test_sensor_every_is_an_input_with_jit_yml_s_default(self):
        inputs = proposal().get("on", proposal().get(True))["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["sensor_every"]["default"], "10")
        self.assertEqual(job()["env"]["SENSOR_EVERY"], "${{ inputs.sensor_every }}")

    def test_only_the_adversary_step_holds_a_secret(self):
        for step in job()["steps"]:
            with self.subTest(step=step.get("name")):
                has = "secrets." in yaml.safe_dump(step)
                sends = kinds(step) == ["adversary"] and any("--execute" in w for w in commands(step, PRESSURE))
                self.assertEqual(has, sends)
        self.assertNotIn("secrets.", yaml.safe_dump(job().get("env", {})))


if __name__ == "__main__":
    unittest.main()
