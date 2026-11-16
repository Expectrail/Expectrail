# Pointer/menu validation evidence

- [Red](red.log): ten new tests run on the pointer-contract prerequisite before implementation; one failure, eight errors, one pass.
- [Green](green.log): 39 menu/pointer/existing-event tests pass with Godot 4.7.2; [final menu tests](menu-final.log) add pending-review, retained-log, CLI-refusal and pointer-only coverage, 16 pass with no skips.
- [Related](related.log): 90 tests, one named prerequisite skip, otherwise pass.
- [Before full suite](before.log): the preceding pointer-contract final run, reused on dependency tree `ca054841c4739c9d4fcd389b82075fabd6ee9882`. Its original metadata deliberately still says label `after`; this copy is the continuation's baseline, not a newly run command.
- [First after](after.log): one captured-CLI-output JSONDecodeError in the existing ingest-repair test. [Isolated unchanged rerun](isolated-error-recheck.log) passes. The underlying transient cause was not established.
- [Final after](after-final.log) and [comparison by failing name](test-comparison.json).
- [Legacy comparison](parity-comparison.json): eight trace byte comparisons plus unchanged decisions, first frames, reasons and coverage. Raw evidence is under `parity/before/` and `parity/after/`. Before is the prior pointer-contract final evidence; after is the new real rendered replay. Default full-suite PATH has Godot 4.6.3; these engine captures and focused real tests use pinned 4.7.2. Legacy captures explicitly disable the sandbox in this restricted machine. No vision observer or paid model is involved.

The full-suite command is `python3 -m unittest discover -s tests -t .`. Only safe environment settings are inherited by the run wrapper; TMPDIR is memory-backed because the workspace disk is nearly full. No assertions were loosened or existing tests skipped to obtain a pass. The additional named full-suite skip is the new Godot-required class; its three tests also passed with the pinned engine as shown above.

Published path spellings were redacted in the registry follow-up; [evidence handling](../outside-trials/breakout-ci/evidence-notes.md) explains the placeholders and original handover records.
