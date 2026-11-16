# Local hosted-trial kit and public result reader (#254)

## What changed

Built six local preparers under `tools/gate_trials/`, plus a token-free public API reader and a
local capture mutation rehearsal. The kit creates trial refs from local `origin/main` through an
alternate Git index, public patch files and Git object/ref commands. It prints exact pushes into
an explicitly supplied disposable test repository, never executes them, and never changes the
working tree or normal index. Existing different refs/output folders and Expectrail's own
repository as a seed target are refused. All six share a deterministic seeded base; new-head
prepares a separate successor without advancing the first head.

The reader binds the public observations to the declared trial, full commit, dedicated App and
latest capture attempt; it checks the head-bound bot comment, base policy statement, repair
proof, failing check/reason, explicit mismatch or stale refusal as appropriate. Historical generic
accept/identity refusal are named separately, never counted as seeded/fork trials. Missing latest
checks, old comments, unknown trials, incomplete timing and unenforceable public-only settings
claims fail. No token is read, no redirect followed, and API pagination/response sizes are bounded.

One-page guide: `docs/gate-trials.md`. The kit README supplies exact expectations, human-only
settings checklist and the trusted-job pause/substitution steps that cannot be implemented
through a PR alone. Default-branch-only capture makes a disposable seeded default branch
necessary. Current start can safely skip an old head without publishing a reason, so absence alone
is not credited. A repeatable stale-finish test needs Sean's separately reviewed trusted-job pause.
Uploaded immutable artifacts cannot be edited by normal PR code; hosted downloaded-byte
substitution requires trusted instrumentation. Neither is described as performed by this kit.

Base: `a98dcb08c2d7fe068283e97148b07a37d423d91e` (current main and supplied
`chatgpt/254-hosted-trials` branch). Read AGENTS.md first; the historical required fetch object
was already fetched once in this shared repository. Earlier under-review builder patches were
not applied: this independent trial kit builds against the supplied current main.

## What was run

- `python3 -m unittest -v tests.test_gate_trials`: final 26 tests, OK, 1.112s
  (`focused-final-consistency.log`). All six real temporary Git preparations preserve caller bytes/index;
  second-head topology, ref collision refusal, hook suppression, original ZIP preservation,
  actual judge mismatch-before-observer, reader binding/negative cases, public GET-only/no-token
  behavior, pagination limits and source workflow boundaries are exercised. Replay/visual
  providers in the local judge test are offline stand-ins; no real engine or model trial claimed.
- Public unauthenticated GETs saved PR #514, both cited check pairs and capture-run objects,
  and its current marker comment. Fixtures keep API objects intact, with source sidecars.
  The overwritten older comment is explicitly unavailable; no historical comment was invented.
- `python3 -m tools.gate_trials read --pr 514`: PASS historical-accept through the live public
  API (`public-reader-514.log`). Both fixture replays pass with distinct limited classifications.
- Mutation red run: disabling only `read.require` in an isolated process makes the demonstrated
  repair, half-published pair and new-head timing/refusal regressions fail (3 tests, 6 failed
  assertions/subcases; `red-reader-guards-final.log`). Tests and source
  are unchanged; ordinary focused tests are green.
- First full `python3 -m unittest discover -s tests -t .`: 4,111 tests, OK, 48 skipped,
  412.905s (`full-suite-before-reader-consistency.log`), with no `EXPECTRAIL_*` variable set in
  the shell. Review then added pair-summary consistency and proof that the old refusal followed
  the new-head push, with a new regression for half-published pairs and another timing subcase.
  Earlier identity failures are no longer eligible as evidence of the deliberate push. Final
  full-suite rerun: **4,112 tests, OK, 48 skipped, 403.765s** (`full-suite.log`).
- All six literal preparer modules run against current main (`preparers-main.log`), with an
  explicitly illustrative target and no remote lookup/push. Full tracked game hashes and caller
  index bytes are unchanged. The trim of blank context lines in the copied patch fixtures removes
  nested-patch whitespace warnings without changing game diffs; the 25 focused tests pass again
  afterward in 2.296s (`focused-final-patch-context.log`). `git diff --check` passes.
- Fresh-process discovery with numpy/PIL absent: zero main-suite import errors; all 66 release-gate
  bodies load (`load-without-pixels.log`). No optional image package is imported by the kit.
- Final code patch applies cleanly to a fresh main worktree; all 26 kit tests pass there in
  1.559s (`apply-check-tests.log`). All 21 changed files match that applied copy after the final
  work-log stats update. Reverse patch application, protected-file comparisons and payload SHA-256
  checks pass. No `.github/` or tracked game file changes. Final manifest is in the handover.

## Not done

Part of #254. No hosted trial was started. Sean still needs correct-fix, wrong-fix, deliberate
new-head, actual fork and enforcement observations; hosted tamper scope must be recorded plainly.
No push, PR, GitHub comment, workflow dispatch, repository creation, setting/token/secret change,
model call, approval addition/change or private/held-out/blind/fresh content read. All GitHub
calls were read-only public evidence retrieval. No file under `.github/`, or
`expectrail/gate/verify.py`, `expectrail/anchored.py`, `tools/ci_bundle.py`, was changed.

## Files

`tools/gate_trials/` (preparers, shared builder, reader, mutator, patches, README);
`tests/test_gate_trials.py`; `tests/fixtures/gate_trials/` (two saved observations and provenance);
`docs/gate-trials.md`; this work log.
