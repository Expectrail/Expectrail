"""Release gate, intent (#258): an intentional change, a weakened tolerance, a misleading generated check.

The change used for all three is the seeded bug (the player falls through the floor): a change of
behaviour that breaks the approved check "player stays above ground". Declared or not, what it does
is the same, so what is tested is whether a declaration, an edit to the check, or a generated block
can turn that into clearance.

- **An intentional change passes as a contract change.** A change of behaviour that breaks an approved
  check is judged by the approved check. Declaring it an intended change (``--intent change``) does
  not make it pass, and neither does rewriting, in the same change, the check it breaks: the checks
  come from the base, and the record says the change edits a spec that judges changes only once it
  merges. So an intended change reaches clearance only as a contract change: the new check approved
  and merged first, then the behaviour.
- **A weakened tolerance.** The same through ``expectrail verify``: a change that raises its own check's
  tolerance from 20 px to 100,000 px is judged by the base's check, unweakened, and rejected.
- **A misleading generated check stays advisory.** A generated-checks block that reports eight valid
  generated checks and no catch, on a change that breaks an approved check, changes nothing: the
  decision is the reject it was. A block that cannot be read changes nothing either.

The intent and the generated block are inputs of the pull-request gate's command only (see
``tests.release_gate.pr_gate``, which runs that command with both observers); the weakened tolerance
is run through the orchestrator's command, as the other rows are.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.release_gate.common import GAME, REPO, ROUTE, SPEC_FILE, SPECS, GateCase, edit_json

EDITED = "this change edits 1 spec and 0 route files; they judge changes once it merges"
FAILS = "1 of 1 public checks fail after the change"


def weaken(doc: dict) -> None:
    """The check's tolerance raised from 20 px to 100,000 px."""
    doc["assertion"]["boundary"]["tolerancePx"] = 100000


# Eight generated checks, all valid, none of which caught anything: on a change that breaks an approved
# check this says "the generated checks found nothing", which is misleading and must stay advisory.
NOTHING_CAUGHT = {"status": "ran", "reason": None, "proposed": 8, "valid": 8, "strong": 0, "weak": 0,
                  "catches": [], "runSha256": "0" * 64}


class PullRequestGateCase(GateCase):
    def pr_gate(self, head: Path, *extra: str, base: Path | None = None) -> tuple[int, dict | None, str]:
        """The pull-request gate's command (with both observers): its exit code and its findings record."""
        out = self.tmp / f"out-{len(list(self.tmp.glob('out-*')))}"
        argv = [sys.executable, "-m", "tests.release_gate.pr_gate", "--repo", str(head), "--game", GAME,
                "--routes", ROUTE, "--specs", SPECS, "--out", str(out), *extra]
        if base is not None:
            argv += ["--base", str(base)]
        done = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, timeout=300)
        findings = out / "findings.json"
        record = json.loads(findings.read_text(encoding="utf-8")) if findings.is_file() else None
        return done.returncode, record, done.stdout + done.stderr

    def weakened_bug(self) -> Path:
        head = self.copy("bug-weakened", self.bug)
        edit_json(head / SPEC_FILE, weaken)
        return head


class IntentBaselineTest(PullRequestGateCase):
    def test_the_pull_request_gate_clears_the_unchanged_game_declared_an_intended_change(self):
        # Without this, "not cleared" through this command could hold because it never clears.
        code, record, log = self.pr_gate(self.clean, "--intent", "change", base=self.clean)
        self.assertEqual((code, record["decision"]), (0, "accept"), log)
        self.assertEqual(record["observers"]["rule"], "both")
        self.assertEqual(record["intent"], "change")


class IntentTest(PullRequestGateCase):
    # --- an intentional change passes as a contract change -----------------------------------------
    def test_a_change_declared_intended_that_breaks_an_approved_check_is_rejected(self):
        code, record, log = self.pr_gate(self.bug, "--intent", "change", base=self.clean)
        self.assertNotCleared(code, record, log)
        self.assertEqual((code, record["decision"], record["intent"]), (1, "reject", "change"))
        self.assertIn(FAILS, record["reasons"])

    def test_a_change_declared_intended_that_rewrites_the_check_it_breaks_is_judged_by_the_approved_check(self):
        code, record, log = self.pr_gate(self.weakened_bug(), "--intent", "change", base=self.clean)
        self.assertNotCleared(code, record, log)
        self.assertEqual((code, record["decision"]), (1, "reject"))
        self.assertEqual(record["checksFrom"], "base")
        self.assertIn(EDITED, record["reasons"])

    # --- a weakened tolerance ----------------------------------------------------------------------
    def test_a_tolerance_the_change_weakens_in_its_own_check_is_not_the_one_that_judges_it(self):
        code, status, err = self.verify(self.weakened_bug(), base=self.clean)
        self.assertNotCleared(code, status, err)
        self.assertEqual((code, status["decision"]), (1, "reject"))
        self.assertIn(EDITED, status["reasons"])

    # --- a misleading generated check stays advisory -----------------------------------------------
    def test_generated_checks_that_caught_nothing_do_not_clear_a_change_an_approved_check_rejects(self):
        block = self.tmp / "generated-checks.json"
        block.write_text(json.dumps(NOTHING_CAUGHT), encoding="utf-8")
        code, record, log = self.pr_gate(self.bug, "--generated-checks", str(block), base=self.clean)
        self.assertNotCleared(code, record, log)
        self.assertEqual((code, record["decision"]), (1, "reject"))
        self.assertEqual(record["generatedChecks"], NOTHING_CAUGHT)   # read, shown, and left out of the decision
        self.assertIn(FAILS, record["reasons"])

    def test_a_generated_block_that_cannot_be_read_changes_nothing(self):
        block = self.tmp / "generated-checks.json"
        # Counts that disagree with the rows: eight strong catches claimed, none listed.
        block.write_text(json.dumps({**NOTHING_CAUGHT, "strong": 8}), encoding="utf-8")
        code, record, log = self.pr_gate(self.bug, "--generated-checks", str(block), base=self.clean)
        self.assertNotCleared(code, record, log)
        self.assertEqual((code, record["decision"]), (1, "reject"))
        self.assertEqual(record["generatedChecks"]["status"], "nothing-generated")
        self.assertIn("could not be read", record["generatedChecks"]["reason"])
