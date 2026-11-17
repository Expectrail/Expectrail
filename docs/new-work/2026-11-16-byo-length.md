# Name and bound an empty, length-limited smoke answer (#562)

## What changed

Read #562 and the public logs of the Nov 14, 15 and 16 scheduled runs. The failed
request allowed 256 output tokens. The smoke, sender and workflow were identical
between Nov 14 and 15; the new capability record was not read by that path then.
Baseten documents always-on reasoning sharing the output allowance. The exact
failed run's usage is absent; reasoning exhaustion is likely, not a measured
internal trace. Nov 16 passed before this change. See [the investigation](../byo-smoke.md).

Added a shared `OutputLimitReached` error, preserved by the smoke, text readers,
check drafting and fixers. Legacy triage reports a fallback. The smoke names and
counts the new failure and exits 1. It never turns empty length-limited output
into a pass, empty candidate or unlabelled parser failure.

Added the capability record's smoke-only limits and public tariff sources. The
Baseten smoke uses one attempt, 256 input tokens (server truncation) and 2,048
output tokens including reasoning. At the recorded rates its token-charge
ceiling is $0.009024. Other smoke providers keep 256 output tokens and also use
one attempt; general sender retry defaults are unchanged. No reasoning-off
parameter is sent to a model whose provider says it cannot turn reasoning off.

## What was run

- Required historic-base fetch; current main and the claimed branch fetched.
  The branch was fast-forwarded locally from ada4c34 to current main
  `ec0919b60c03abf033ef79a996880300658e6887` (no new commit).
- Before: full discovery, 4,509 tests, 58 skips, no failures/errors,
  511.455 test seconds.
- New stand-in tests were red before implementation; their log is retained.
- Focused provider/smoke/wiring/drafting/spend/schema tests: 126 tests passed.
  The runtime policy reader was also tested without NumPy, Pillow or jsonschema.
- After: full discovery, 4,531 tests, 58 skips, no failures/errors,
  534.989 test seconds. Both runs end OK. Failing test names are `[]` before
  and `[]` after; 22 tests added, no new failures. Full logs are in the handover.
- Export scan: 761 files, no errors or warnings. Diff whitespace check passed.
  The patch is verified against the named base using a separate Git index.

## Not done

No live model call, dispatch, push, GitHub write or new main commit. No workflow
change, approval or game-source edit. No actual invoice or new live outcome was
measured. Sean must read the next scheduled run; this is Part of #562.

## Files

- `expectrail/providers.py`: shared error/readers, opt-in input bound and attempt
  limit; ordinary callers keep their existing defaults.
- `agents/byo_smoke.py`: named failed result, capability-backed allowance and
  no-key cost plan, one attempt per provider.
- `expectrail/spec_writer.py`, `agents/triage.py`: preserve the named failure on
  saved/legacy responses.
- `contracts/provider-capability.v1.schema.json` and its Baseten example.
- `tests/test_byo_output_limit.py`: new offline cases.
- `tests/test_byo_smoke.py`: update the length-limited outcome assertion and the
  old test's claim that any token budget guarantees a one-word answer.
- `docs/byo-smoke.md` and this work log. Full logs/source snapshots are in the ZIP.
