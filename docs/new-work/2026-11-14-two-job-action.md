# Judge saved pull-request replays on the base (#254)

## What changed

The candidate captures base and head with required sandboxing. The trusted workflow validates the
GitHub artifact and its manifest before reading the saved replays. It runs the base's approved checks
with the shared evaluator. The protected publisher attaches evidence and clearance to the PR head.
Only an accept can clear it. A declared fix uses a separate capture for each repair repetition.

## What was run

- `python3 -m unittest discover -s tests -t .` on the base ran 3,225 tests, OK with 42 skipped.
- The same command after implementation ran 3,236 tests, OK with 42 skipped. Both lists of failing and erroring test names were empty.
- The focused command recorded in the handover's targeted.log ran 129 tests, OK. Replay, vision and GitHub responses were stand-ins.
- All five new bundle tests first errored because the bundle module was missing. All five passed after implementation.

## Not done

No hosted pull request, real sandboxed capture, model call or branch-rule change. The local replay
sandbox reported that xvfb-run was missing. A hosted trial must verify the workflow_run metadata,
artifact download, fork behavior and the dedicated App as the required check source. The bundled
clean visual recording covers smoke. Other frames can need review. Sean owns the environment and
publisher setup. The receipt hook is reserved for #255.

## Files

- `.github/workflows/expectrail-capture.yml`
- `.github/workflows/expectrail-comment.yml`
- `.github/workflows/expectrail-verify.yml`
- `contracts/ci-bundle.v1.schema.json`
- `contracts/examples/ci-bundle.v1.json`
- `docs/ci-gate.md`
- `docs/new-work/2026-11-14-two-job-action.md`
- `expectrail/gate/comment.py`
- `expectrail/gate/verify.py`
- `tests/test_ci_gate.py`
- `tests/test_main_only_environment.py`
- `tests/test_merge_guard.py`
- `tools/ci_bundle.py`
- `tools/ci_checks.py`

## Architect run (Linux, main 8083215e)
Applied cleanly with a three-way merge. Full suite: OK, 31 skipped. Not run on GitHub: the split needs the GitHub App and its secret, which do not exist yet. Before merging, see "Do not merge yet" in the pull request.
