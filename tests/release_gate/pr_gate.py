"""The release gate's run of the pull-request gate's command line (``python3 -m expectrail.gate.verify``),
for the intent rows, with the visual observer answering from the recorded vision answers of the "Run
it" samples.

    python3 -m tests.release_gate.pr_gate --repo HEAD [--base BASE] --game ... --routes ... --specs ...
                                          --out DIR [--intent fix|change|none] [--generated-checks FILE]

Why this command and not ``expectrail verify``: a change's declared intent (``--intent``) and the
advisory generated-checks block (``--generated-checks``) are inputs of the pull-request gate only. The
orchestrator's command takes neither: it judges every change as ``none`` and never reads a generated
block, so it cannot be misled by either. The intent rows are about those two inputs, so they are run
through the command that reads them.

Everything is the gate's own code (``verify.main``: its argument parsing, its reading of the intent
and of the block, its decision, its exit code), with one difference: ``run_gate`` is called with the
rule ``both`` and a ``RecordedObserver`` over the samples' recordings (``tests.release_gate.worker``),
as the orchestrator's registered engine judges. The command as published defaults to the engine's
record alone until the two-job form exists (#254); a release-gate row is never held on that path.
Clearance here is what it is for the orchestrator's command: exit 0, which only an accept gives.
"""
from __future__ import annotations

import sys

from expectrail import recorded
from expectrail.gate import record as rec
from expectrail.gate import verify
from tests.release_gate.worker import recording

_RUN_GATE = verify.run_gate


def run_gate(**kwargs):
    if "rule" in kwargs or "visual" in kwargs:
        raise AssertionError("the release gate sets the observers itself")
    return _RUN_GATE(**kwargs, rule=rec.BOTH, visual=recorded.RecordedObserver(recording()))


if __name__ == "__main__":
    verify.run_gate = run_gate
    sys.exit(verify.main(sys.argv[1:]))
