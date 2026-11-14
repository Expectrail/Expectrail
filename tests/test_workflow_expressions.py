"""GitHub allows status functions (success(), failure(), cancelled(), always()) only in `if:`.

Anywhere else, GitHub refuses the whole workflow file. A workflow started only by `workflow_run`
then never starts at all, and every push records a failed run with no jobs. That happened to
"Expectrail comment", the trusted judge of the two-job gate, from #429's merge until this test's
change: `!cancelled()` sat in a step's `env`. This test reads every workflow and refuses a status
function in any expression that is not a job's or a step's `if`.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATUS = re.compile(r"\b(success|failure|cancelled|always)\s*\(\s*\)")
EXPR = re.compile(r"\$\{\{(.*?)\}\}", re.S)


def misplaced(node, path=()):
    """Every (path, expression) holding a status function outside an `if`."""
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "if":
                continue
            found += misplaced(value, path + (str(key),))
    elif isinstance(node, list):
        for n, value in enumerate(node):
            found += misplaced(value, path + (str(n),))
    elif isinstance(node, str):
        for expr in EXPR.findall(node):
            if STATUS.search(expr):
                found.append(("/".join(path), expr.strip()))
    return found


class StatusFunctionTest(unittest.TestCase):
    def test_status_functions_appear_only_in_if(self):
        problems = {}
        for wf in sorted((ROOT / ".github" / "workflows").glob("*.y*ml")):
            doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
            bad = misplaced(doc)
            if bad:
                problems[wf.name] = bad
        self.assertEqual(problems, {})

    def test_the_check_finds_the_case_that_broke_the_judge(self):
        doc = {"jobs": {"judge": {"steps": [{"env": {"R": "${{ steps.a.outcome == 'success' && !cancelled() }}"}},
                                            {"if": "always()", "run": "true"}]}}}
        self.assertEqual(len(misplaced(doc)), 1)


if __name__ == "__main__":
    unittest.main()
