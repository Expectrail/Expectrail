"""The reproduction audit's dispatches are ones jit.yml accepts (#285).

``docs/repro-audit.md`` tells Sean which live ``jit.yml`` runs to dispatch from main and what each may
cost. The page and the workflow are edited by different changes, so a dispatch on the page can drift
from what the workflow declares: an input it no longer has, a choice it does not offer, or a setting
it gained that the page never lists. Until November 18 the page listed no run under
``signals-reach-evidence-menu`` (#622), the only setting that can reach the two counter defects.

These tests read every ``gh workflow run jit.yml`` command in the page's shell blocks and check it
against the workflow's ``workflow_dispatch`` inputs. Nothing here dispatches a workflow."""
from __future__ import annotations

import re
import shlex
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
AUDIT = REPO / "docs" / "repro-audit.md"
WF = REPO / ".github" / "workflows" / "jit.yml"
BLOCK = re.compile(r"^```sh\n(.*?)^```", re.M | re.S)


def dispatch_inputs() -> dict:
    doc = yaml.safe_load(WF.read_text(encoding="utf-8"))
    # PyYAML reads the bare key ``on`` as the boolean true.
    triggers = doc.get("on", doc.get(True))
    return triggers["workflow_dispatch"]["inputs"]


def dispatches(text: str) -> list[list[str]]:
    """Every ``gh workflow run jit.yml`` command in the text's shell blocks, split into words."""
    found = []
    for block in BLOCK.findall(text):
        joined = re.sub(r"\\\n\s*", " ", block)
        for line in joined.splitlines():
            words = shlex.split(line)
            if words[:4] == ["gh", "workflow", "run", "jit.yml"]:
                found.append(words)
    return found


def fields(words: list[str]) -> dict[str, str]:
    """The ``-f key=value`` pairs of one command; a key given twice is refused."""
    out: dict[str, str] = {}
    for flag, value in zip(words, words[1:]):
        if flag in ("-f", "--raw-field", "-F", "--field"):
            key, sep, val = value.partition("=")
            if not sep:
                raise ValueError(f"field without a value: {value!r}")
            if key in out:
                raise ValueError(f"field given twice: {key}")
            out[key] = val
    return out


def problems(words: list[str], inputs: dict) -> list[str]:
    """What is wrong with one dispatch against the workflow's inputs; empty when nothing is."""
    found = []
    if "--ref" not in words or words[words.index("--ref") + 1] != "main":
        found.append("not dispatched from main")
    try:
        given = fields(words)
    except ValueError as err:
        return found + [str(err)]
    for key, val in given.items():
        spec = inputs.get(key)
        if spec is None:
            found.append(f"jit.yml has no input {key!r}")
        elif spec.get("type") == "choice" and val not in spec["options"]:
            found.append(f"{key}={val!r} is not one of {spec['options']}")
    budget = given.get("budget_usd")
    if budget is not None and not re.fullmatch(r"\d+(\.\d+)?", budget):
        found.append(f"budget_usd={budget!r} is not an amount")
    return found


class AuditDispatchTest(unittest.TestCase):
    def setUp(self):
        self.inputs = dispatch_inputs()
        self.commands = dispatches(AUDIT.read_text(encoding="utf-8"))

    def test_the_page_lists_dispatches(self):
        self.assertGreaterEqual(len(self.commands), 4)

    def test_every_dispatch_uses_inputs_and_choices_jit_yml_declares(self):
        for words in self.commands:
            with self.subTest(command=" ".join(words)):
                self.assertEqual(problems(words, self.inputs), [])

    def test_the_menu_setting_is_dispatched_with_the_candidate_withheld(self):
        # The only setting that offers the menu probes (#622), and the run that can reach the two
        # counter defects from the report alone (#285 step 6).
        runs = [fields(w) for w in self.commands]
        self.assertIn(
            {"mode": "repro", "offer": "signals-reach-evidence-menu", "candidate": "withheld", "budget_usd": "2"},
            runs,
        )

    def test_every_repro_offer_the_workflow_has_beyond_baseline_and_pixel_is_listed(self):
        # Baseline is the published baseline run; the pixel setting's steps are listed on #286.
        offers = set(self.inputs["offer"]["options"]) - {"baseline", "signals-reach-evidence-pixel"}
        listed = {fields(w).get("offer") for w in self.commands if fields(w).get("mode") == "repro"}
        self.assertEqual(offers - listed, set())


class CheckerTest(unittest.TestCase):
    """The checker itself catches the drift it is for."""

    INPUTS = {
        "mode": {"type": "choice", "options": ["rehearsal", "repro"]},
        "offer": {"type": "choice", "options": ["baseline", "signals-reach"]},
        "budget_usd": {"default": "2"},
    }

    def words(self, line: str) -> list[str]:
        return dispatches(f"```sh\n{line}\n```\n")[0]

    def test_a_good_dispatch_has_no_problem(self):
        cmd = "gh workflow run jit.yml --repo Expectrail/Expectrail --ref main -f mode=repro -f offer=signals-reach -f budget_usd=2"
        self.assertEqual(problems(self.words(cmd), self.INPUTS), [])

    def test_a_choice_the_workflow_does_not_offer_is_caught(self):
        cmd = "gh workflow run jit.yml --ref main -f mode=repro -f offer=signals-reach-menu"
        self.assertEqual(len(problems(self.words(cmd), self.INPUTS)), 1)

    def test_an_input_the_workflow_does_not_declare_is_caught(self):
        cmd = "gh workflow run jit.yml --ref main -f mode=repro -f observer=visual-sensor"
        self.assertIn("jit.yml has no input 'observer'", problems(self.words(cmd), self.INPUTS))

    def test_a_branch_other_than_main_is_caught(self):
        cmd = "gh workflow run jit.yml --ref agent2/x -f mode=repro"
        self.assertIn("not dispatched from main", problems(self.words(cmd), self.INPUTS))
        self.assertIn("not dispatched from main", problems(self.words("gh workflow run jit.yml -f mode=repro"), self.INPUTS))

    def test_a_field_given_twice_or_without_a_value_is_caught(self):
        self.assertTrue(problems(self.words("gh workflow run jit.yml --ref main -f mode=repro -f mode=rehearsal"), self.INPUTS))
        self.assertTrue(problems(self.words("gh workflow run jit.yml --ref main -f mode"), self.INPUTS))

    def test_a_budget_that_is_not_an_amount_is_caught(self):
        cmd = "gh workflow run jit.yml --ref main -f mode=repro -f budget_usd=two"
        self.assertTrue(problems(self.words(cmd), self.INPUTS))

    def test_a_continued_command_is_read_whole(self):
        text = "```sh\ngh workflow run jit.yml --ref main \\\n  -f mode=repro -f offer=baseline\n```\n"
        self.assertEqual(fields(dispatches(text)[0]), {"mode": "repro", "offer": "baseline"})


if __name__ == "__main__":
    unittest.main()
