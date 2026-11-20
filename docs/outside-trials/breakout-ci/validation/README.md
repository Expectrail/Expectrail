# Validation logs

Before/after full-suite logs, red probes and focused green checks are retained here.
Machine paths are redacted with portable placeholders; raw originals are in the handover.
The before ingest-repair JSON-output error was not reproduced in the first after run.
No assertion or test in that path was changed. [Final after](after-final.log): 4399 tests, zero failures/errors, 57 skips.
[Comparison by failing name](test-comparison.json) shows no new failing names.

The red old-draft run executes the new frozen-paddle assertion against the exact
prerequisite draft: a stopped paddle in the old left lane incorrectly passes.
The new separated in-window checkpoints fix that without ignoring an out-of-bounds counterexample.
