# Verifier-resolved commit inputs (#250)

## What changed

`expectrail verify --repo PATH --base REF --head REF` now resolves references itself and judges
separate, job-owned read-only snapshots. It reads local Git objects through private metadata,
verifies their hashes and writes files directly. Repository hooks, filters, config includes,
replacement refs, inherited Git settings and missing-object fetches cannot supply those bytes.
There is no checkout, archive, submodule fetch or caller-working-tree modification.

Unknown or ambiguous references, equal resolved commits, dirty literal HEAD, non-repositories,
symlinks, submodules and unavailable/unsupported local objects stop before replay. The HEAD
diagnosis identifies committed bytes versus working-tree bytes and gives the folder alternative.
The base commit chooses configured policy, routes and observer settings; explicit folder-layout
arguments retain their existing base-policy path.

Request/job schemas, three new examples and both writers/readers change together. New jobs
record per-side folder/commit provenance; only resolved commit inputs carry authenticated full
commit IDs, Git trees and computed snapshot digests. Caller folder commit labels are discarded
on new jobs. Old requests and records stay readable, without claiming unrecorded provenance.
Refs are pinned before queuing, retained paths belong to the job, and queued snapshot changes
stop before replay. Idempotency does not leak unused snapshots or silently reuse moved refs.

Base: main `493a6b123be35cbb7feed880b569af9a67b2a841`, supplied branch
`chatgpt/250-commit-inputs`. Applied the earlier #258/#254/#250 audit first. Its generated
`docs/release-gate.md` no longer applied because newer main includes receipt controls, so the
adapted prerequisite preserves that newer report and applies the audit's other nine files.
The prerequisite is delivered separately from this task's patch. Its checkpoint tree is
`2f2a51522025bbeafa01726ecf4438d5819defb6` (a tree object, not a commit to fetch).

## What was run

- Prior audit prerequisite on isolated main: `python3 -m unittest discover -s tests -t .` —
  4,061 tests, OK, 48 skipped, 400.140 seconds (`full-suite-baseline.log`).
- Red before CLI/store integration: the new happy-path and unknown-ref tests both failed against
  the old CLI (`--repo` unrecognized), `red-cli-before-integration.log`. No replay ran.
- `python3 -m unittest -v tests.test_commit_inputs tests.test_schema_pattern` — 40 tests,
  OK, 6.586 seconds (`commits-final-with-staging.log`). The 30 commit tests use real temporary Git repositories:
  SHA-1/SHA-256, annotated tags, packed objects, a bare clone, a linked worktree, real ambiguous
  prefixes, branch/tag ambiguity, staged/unstaged changes, ignored files, forged claims,
  snapshot mutation, idempotency, base-config selection and decision parity with folder inputs.
  Hooks/filters/fsmonitor/config-includes have execution sentinels; an outside symlink target
  has an audit sentinel; a missing promisor object has a local HTTP sentinel. None fired.
  Replay and visual providers in these tests are offline stand-ins; the real worker, evaluator,
  contracts and record readers run. This is not a new real-Godot/model accuracy measurement.
- Focused integration: 172 tests, one new subprocess-fixture error — it invoked an unsupported
  `python3 -m expectrail` entry point. Corrected to `python3 -m expectrail.cli`; the subprocess
  test then passed in the 39-test run. The other 171 tests passed. An earlier schema-pattern
  registry omission was corrected by adding samples for the two new patterns. Initial snapshot
  adoption permission and new-fixture adapter omissions were fixed; intermediate logs are retained.
- First full run: 4,090 tests, OK, 48 skipped, 382.152 seconds
  (`full-suite-before-staging-fix.log`). Review then found that creating the job store inside a
  clean source repository could itself make HEAD dirty. The added regression fails before the
  fix (`red-inside-store-regression.log`). Initial staging now happens outside the working tree,
  with the store created only after the HEAD check; that regression passes in the 40-test run.
- Full discovery with numpy/PIL hidden from PathFinder — zero import errors; all 68 release-gate
  test bodies load (`load-without-pixels.log`). The new tests import no optional image packages.
- Final `python3 -m unittest discover -s tests -t .` — 4,091 tests, OK, 48 skipped,
  351.665 seconds (`full-suite-final.log`). No `EXPECTRAIL_*` variable was set in the invoking shell.
- Both patches applied to a fresh detached copy of main `493a6b1`; all 40 commit/schema tests
  passed there in 5.852 seconds (`apply-check-tests.log`). All 23 changed files match that applied
  copy. Protected files match main byte-for-byte and `.github/` has no diff. `git diff --check`
  passes. Both patches also pass reverse application checks on the applied copy.
- Both schemas and five old/new examples validate with JSON Schema and runtime readers
  (`contract-validation.log`). Final absent-numpy/PIL discovery still has zero errors and loads
  all 68 release-gate bodies (`load-without-pixels-final.log`).

## Not done

No live model calls, workflow dispatch, GitHub write, push or PR. No private held-out, blind-set or
`fresh-*` contents read. No approval added or changed. No edit to `.github/`, `tools/merge_guard.py`,
`expectrail/gate/verify.py` or `expectrail/anchored.py`. Temporary Git repositories are test
fixtures explicitly requested by this task; no external repository was created.

Part of #250. MCP/Action migration to the shared job service and a trusted private-suite request
remain separate work identified in the prerequisite audit. Symlinks/submodules, external object
alternates, reftable and reflog selectors are named unsupported inputs. Read-only modes are not
protection from the owning user changing permissions, nor a protected evidence grade. No hosted
run for this patch was performed; Sean applies the patches, runs tests and pushes.

## Files

- `contracts/verify-request.v1.schema.json`, `contracts/verify-job.v1.schema.json`;
  `contracts/examples/verify-request-commits.json`, `verify-request-resolved-commits.json`,
  `verify-job-commits.json`.
- `expectrail/orchestrator/commits.py`, `cli.py`, `request.py`, `store.py`.
- `tests/test_commit_inputs.py`, `tests/test_schema_pattern.py`.
- `docs/commit-inputs.md`, `docs/orchestrator.md`, this work log.
- The adapted prerequisite's nine files are enumerated separately in the handover; they are
  unchanged by this task's patch.
