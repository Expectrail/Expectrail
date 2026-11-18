# Wheel sample and environment-sensitive tests (#249, #365)

## What changed

Based on main ff2c7a7aedd1d32a2f0dfdd89ce95fabc416b9f2. The wheel builder qualifies
private harness/agent imports under expectrail._bundle and removes only the staged
installed-copy path bootstrap. Repository implementations and source __init__ remain
unchanged. A foreign harness/agents package can coexist; sys.path is unchanged.
Three original public vision recordings are copied byte for byte into the wheel.

The explicit EXPECTRAIL_VLM_SAMPLE_RECORDINGS=1 profile uses the existing sample
runner and gate with exact recorded vision. Only doctor and the bundled sample
select this profile; ordinary verification and the no-key quickstart keep their
existing outcomes. A real project always uses normal project doctor. Missing or
invalid recordings block the profile; missing exact image/question answers need
review, with no live fallback. Dockerfile.sample selects the profile explicitly.

The pinned Ubuntu image installs just the wheel into a new Python environment.
Its build context holds only the Dockerfile, wheel and public pinned Godot archive.
The installed script checks SHA-512 inside a network-disabled build step. Read-only
build mounts and few layers avoid excessive copies on a rootless VFS Docker daemon.
The runtime has no checkout, no model key and a non-root user. README leads with
installation; docs/install explains the profile. CI is a proposal, not a workflow edit.

The two test failures had different causes here (UID 1000, not root):
- Worker wait included process-table scans for real descendant cleanup. The targeted
  original run spent 1.153 seconds in cleanup out of 1.160 seconds. The test now keeps
  the strict half-second recognition bound, additionally forbids any polling/lease
  sleep for a known-dead worker, and still performs/checks the real cleanup.
- The disk monitor could catch a 4 MiB write before chmod removed directory access.
  A legal 150 ms scheduling pause reproduced this. This case now measures the final
  unreadable state after the child exits, retaining the original file and assertion.
  Other tests retain periodic byte/entry enforcement. A real mode-000 permission probe
  permits a named skip only when this uid/filesystem bypasses denial; required mode
  fails instead of skipping. Root is an example, not the assumed cause here.

Guard: test change intended (#365)

Guard: test change intended (#249)

## What was run

Required historic c169a5e0da304773587304ed47bc8aabcec80da7 fetch completed.
Before edits, all EXPECTRAIL_* unset: python3 -m unittest discover -s tests -t .
4,683 tests in 801.927 seconds; FAILED (failures=1, skipped=60). Failure:
tests.test_orchestrator.ProcessTest.test_waiting_on_a_worker_that_died_reports_it_at_once
(0.776 seconds exceeded the test's combined recognition/cleanup bound).
The folder test happened to pass there; its forced legal interleaving failed as above.

53 focused tests passed in 21.519 seconds. Both repaired tests also passed with the
same instrumentation/interleaving; real cleanup still took 0.809 seconds. Mutations
that poll a known-dead worker or delay recognition by 0.6 seconds were both caught.
All four changed test modules loaded with numpy and PIL blocked.

Clean container: pip installed the wheel, doctor exit 0; actual sample exit 0,
accept/reject/accept, three completed jobs, no diagnostics, both observers required.
Godot 4.7.2, llvmpipe LLVM 20.1.2, UID 10001; doctor/sample network disabled. Full stdout
and identities are in the handover, including the original exact public recording sources.

The initial container fetch failed TLS verification; it was never disabled. Host fetch
and a checksum-checked cached archive solved that without adding trust material.
An earlier final-suite attempt exhausted disk because rootless Docker's VFS duplicates
intermediate filesystems: 4,592 tests, 3 failures, 2,676 errors, 43 skips in 119.331s.
Its complete log and failure names are retained separately; failures/errors originate
in ENOSPC and consequent setup/tool failures, not a valid product result. Removing only
this task's image and unused build cache recovered 6.5 GiB. No earlier evidence was deleted.
The image was rebuilt with fewer layers and the final full suite was restarted.
An intermediate complete after-run ran 4,694 tests in 839.047s and found one error:
tests.test_quickstart_timer.ContractTest.test_commands_are_the_published_blocks_and_readme_install.
The new first README install block differed from the published quickstart. Restoring
`pip install .` as the leading block (with wheel instructions beside it) fixes the drift;
the timer and its assertions are unchanged. Final wheel/native checks and suite were rerun.
Final after: 4,694 tests in 847.362s; OK (skipped=60). No failures or errors.

Requested export command: python -m agents.export_scan bench docs README.md apps --paths error.
It ran in a public export projection, excluding prohibited paths by metadata before opening
anything. No private/blind/fresh content was read. Initial scan: 829 files, 13 excluded paths,
zero errors and warnings. Final patch/application/export results are retained in the zip.

## Not done

No live model, spend, dispatch, deployed-service request, GitHub write, push or PR.
No workflow, approval, game source, onboarding, observations, verifier, gate/record,
jit or orchestrator implementation was edited. Installed modules' private import paths
are a build transformation; verification logic is unchanged. No hosted CI, registry
publication, release tag, macOS or lower-Python measurement. No general vision or
isolated-execution claim. Part of #249/#365; closure is not claimed for unrun release/CI cases.

## Files

- setup.py; packaging/doctor/sample portions of expectrail/cli.py; Dockerfile.sample
- README.md; docs/install.md; docs/proposals/249-wheel-sample.yml.txt
- tests/test_package.py; tests/test_wheel_sample.py
- tests/test_orchestrator.py; tests/test_replay_sandbox.py
- docs/new-work/2026-11-17-wheel-sample.md

## Review follow-up (architect)
The wheel-only sample image now lives in `Dockerfile.sample`. `Dockerfile.harness` is restored to
main's checkout harness image, so `harness/docker_run.sh` and docs/harness.md work as before. Not run
here: Docker (no daemon in this environment).
