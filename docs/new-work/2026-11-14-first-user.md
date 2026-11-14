# Time the documented quickstart and prepare the first-user kit (#268)

## What changed

Added a timer that runs the six published command blocks in one clean Bash shell in a fresh temporary checkout, preserving their exact text and expected nonzero exits. Records command, exit, monotonic wall seconds, first error lines and log paths; blocked steps say "not run" with null measurements. Credentials, shell startup files and user pip config are excluded. Unauthenticated proxy and CA settings are retained so documented installation/downloads can use this machine's network.

Added the timing schema, an explicitly illustrative example, a validating writer and offline reader. The existing quickstart evidence validator runs only after all command blocks complete. Neither a completed command nor an expected nonzero exit is an accept. Added a one-page human-session kit marked needs-sean, with an unaided start, human minutes to first verdict, verbatim stop notes and a verdict-understanding question.

## What was run

- Main base: `33d0a501c5de60774d73ae48055cd0591b7a65b3`; branch `chatgpt/268-first-user`. Read AGENTS.md and #268/comments. Fetched the required baseline SHA and current main.
- Full suite before: 3,481 tests in 683.868 seconds, OK (37 existing skips).
- Focused timer and existing quickstart tests: 23 tests in 0.930 seconds, OK. Final focused run including the schema-pattern guard: 33 tests in 0.984 seconds, OK. Existing test bodies and assertions are unchanged; the schema-pattern guard receives one new timestamp sample.
- Ran the timer. Install completed in 7.355 seconds, exit 0. Doctor completed in 6.806 seconds, exit 3, but reported a missing display, could not check OpenGL, and found only 533 MB free against its 1 GB requirement. Sample, verify and report were not run; the project-variable assignment completed. No successful walkthrough or game verdict is claimed.
- The first attempt exposed a timer environment bug: it dropped this machine's unauthenticated proxy, making pip fail after 27.572 seconds. Corrected the environment handling, added a regression test and retained both attempts in the handover. The corrected measurement is the reported run.
- The actual timing JSON passes the standard-library reader and JSON Schema Draft 2020-12 validation.
- The first full after-run had one failure: `test_every_contract_pattern_has_a_matching_sample_and_refuses_it_with_a_newline (tests.test_schema_pattern.SchemaPatternTest.test_every_contract_pattern_has_a_matching_sample_and_refuses_it_with_a_newline)`. Added the required matching/newline sample for the timestamp pattern and reused the existing bounded-name pattern. Retained that failing log and comparison; both real timer outputs still pass the final schema. An AST audit confirms the existing test changes only its SAMPLES data, never its assertions.
- Final full-suite comparison: Before: 3481 tests in 683.868 s, OK (skipped=37). After: 3495 tests in 708.406 s, OK (skipped=37). Both failing-name/kind lists are empty; the same 37 skips remain. Fourteen new offline timer tests account for the increase. `git diff --check` passes. Patch application against the exact base is checked and the applied files compared byte for byte; real index unchanged.

## Not done

No human first-user session: Sean or Timothy must recruit a person and run the kit (`needs-sean`). No human time-to-verdict is reported. No complete quickstart here because machine prerequisites are missing. `app` is not documented in these two documents and was not run; future app instructions make the timer refuse stale coverage rather than silently omit them. No documentation defect was established, and README/quickstart are unchanged. Dossier integration belongs to #455 and is untouched. No model credentials, paid calls, approvals, branch commits, pushes or GitHub writes. No protected product files or workflows changed. Previous completed synthetic suite-speed test output was removed to free workspace disk; active/new test output was left alone.

## Files

- `.gitignore`
- `contracts/quickstart-timing.v1.schema.json`
- `contracts/examples/quickstart-timing.json`
- `tools/quickstart_timer.py`
- `tests/test_quickstart_timer.py`
- `tests/test_schema_pattern.py`
- `docs/first-user-test.md`
- `docs/new-work/2026-11-14-first-user.md`
