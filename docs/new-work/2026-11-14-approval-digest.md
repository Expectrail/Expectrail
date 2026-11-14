# An approval binds to the spec's content (#420)

## What changed
An approval was `{"by", "at"}`, and every reader treated it as present or absent, so an approved
spec could be edited (its assertion, window, tolerance, coverage) and stay approved. Now:

- `contracts/test-spec.schema.json`: `approval` gains `specSha256` (64 lower-case hex), described.
- `expectrail/approval.py`: the digest (the spec's canonical JSON without `approval`: keys sorted,
  separators `,` and `:`, no ASCII escaping, UTF-8, non-finite numbers refused) and one `state` every
  reader asks: `bound`, `legacy` (no digest, written before this), `mismatch`, `none`. Anything that
  is not a matching digest (null, a number, upper case, a prefix, a value that cannot be digested) is
  `mismatch`, never approved.
- `expectrail.spec_writer approve` computes and writes the digest, refuses a spec it cannot digest,
  and prints it. A person runs it; nothing types the digest.
- The gate (`expectrail/gate/verify.py`, `read_checks`): a spec whose approval does not match is
  counted with the drafts and never judges; the record's reasons say
  "spec <id>: approval does not match the spec's content; a person must approve it again". A legacy
  approval still judges, and the reasons say "spec <id>: approved before content binding". These
  lines go after every other reason, mismatches first, so the reasons' cap cuts them before anything
  else. No record field was added: the comment job runs main's reader with a closed schema.
- The comment (`expectrail/gate/comment.py`) names those lines on every decision, accept included.
- `agents/spark_open.py`'s `approved_specs` reads only bound and legacy approvals.
- The merge guard (`tools/merge_guard.py`, `check_approved_specs`): an approved test spec, in any
  folder, whose content changes while its approval is not bound to the new content is `needs-sean`,
  "an approved spec's content changed; a person approves it again".
- `docs/ci-gate.md` says how approvals bind.
- `setup.py`: `approval` is one of the modules the wheel carries, since the gate imports it
  (`tests.test_package` found it missing on the first full run).

## What was run
- `python3 -m unittest tests.test_approval_binding tests.test_spec_writer tests.test_two_observers tests.test_ci_gate`:
  160 tests, OK. The new file has 23 tests: whitespace and key order keep the digest; eight kinds of
  edit (tolerance, window, object, prompt, instruction, id, coverage, 12 written as 12.0) each make
  the approval not count; an approval copied from another spec does not match; a legacy approval
  counts and is named; six malformed digests and a NaN are no approval; the gate with an edited only
  spec is needs-review with the reason in the record and the comment; a bound spec accepts with no
  note; the Spark reader; the guard's rule in a specs folder and elsewhere.
- The full suite on the branch (main at 13e8f70 plus this change): see the pull request.

## Not done
- No spec in this repository carries a digest: agents never write an approval. Sean re-approves the
  live specs with `python3 -m expectrail.spec_writer approve <file> --by sean`.
- When `agents/specs/player-stays-above-ground.json` is re-approved, the tests that copy it and edit
  its body (`tests/test_exercised_coverage.py`, `tests/test_ci_gate.py` around `spec_edit`) will copy
  an approval that no longer matches, so their spec becomes a draft. Those helpers then need to
  approve their edited copy with `approve()` in the temporary folder.
- `contracts/examples/test-spec.json` keeps its approval as it was (changing it is a person's step).

## Files
`contracts/test-spec.schema.json`, `expectrail/approval.py`, `expectrail/spec_writer.py`,
`expectrail/gate/verify.py`, `expectrail/gate/comment.py`, `agents/spark_open.py`,
`tools/merge_guard.py`, `setup.py`, `docs/ci-gate.md`, `tests/test_approval_binding.py`,
`tests/test_spec_writer.py`, `tests/test_two_observers.py`, `tests/test_ci_gate.py`,
`docs/new-work/2026-11-14-approval-digest.md`
