# Required sample assets survive quickstart copies and source distributions (#249)

## What changed

Review follow-up to PR #599, head 8431535119ca89f2b1494604cab059eea1e54b7c,
on main 401236c97bdd9bbe80377dcdb92c78747ece878c. The prerequisite is identified
separately in the handover; a small review-only patch accompanies the complete patch.

The curated quickstart copy reads setup.py's literal SAMPLE_RECORDINGS declaration
and copies exactly those three public JSON files. BuildPy.get_source_files declares
the same recordings as mandatory source-distribution inputs. Missing assets still
fail the build. No repository sweep, fallback data, expected exit or evidence
assertion changed. New package regressions build from the curated copy, compare
the recordings byte for byte, then build a wheel from its sdist and compare again.

Sean's review explicitly requested the copier change and a tests/test_package.py
case. These narrow review edits extend the initial file list for that finding.

Guard: test change intended (#249)

Guard: test change intended (#365)

## What was run

The required historic c169a5e0da304773587304ed47bc8aabcec80da7 fetch completed.
Before review edits, main plus the identified prerequisite, all EXPECTRAIL_* unset:
python3 -m unittest discover -s tests -t . — 4,725 tests in 726.552 seconds,
OK (skipped=60). This is the review baseline, not an unmodified-main measurement.

The original host front-door command exited 1: pip could not build the wheel
because docs/run-it/vision/clean.json was missing from its curated checkout.
The new regression first failed for all three missing recordings and the wheel
build. A separate sdist regression first failed for all three missing inputs.
After the final fix, 56 package, quickstart, timer and sample-profile tests passed in
18.704 seconds, including rebuilding a wheel from the source distribution.

The first container attempts found prerequisite problems: the bind-mounted source
was private to UID 1000, then pip could not validate the package index certificate
chain. Running as UID 1000 and supplying the machine's existing public CA bundle
resolved those conditions; TLS verification stayed enabled. The unchanged timing
command then reproduced install exit 1 / overall exit 2, specifically missing
docs/run-it/vision/clean.json. No verification steps are claimed for that red run.

The direct python -m tools.quickstart command passed all six unchanged HTML blocks:
install 0, doctor 3, sample 3, project 0, verify 2, report 2. The sample decisions
were needs-review / reject / needs-review; the draft project remained needs-review,
one draft and zero replays. A wheel was built and installed without dependencies
in a new venv first; it reported installed package, standard library only, and
doctor found exactly vision-key and vision-cap missing.

xvfb-run -a python3 -m tools.quickstart_timer also exited 0: all six commands
completed at their unchanged documented exits and the real evidence check completed.
Both commands used Ubuntu 24.04.5, Python 3.12.3 and pinned Godot 4.7.2. The outer
container package lane passed 26 tests in 15.208 seconds with
EXPECTRAIL_PACKAGE_TESTS=required and no numpy or PIL installed.

An initial RAM mount was noexec, so cryptography could not map its shared library;
the final container explicitly used an executable tmpfs. Docker cp also staged
beneath the live mount; piping tar through docker exec populated it correctly.
These setup failures did not change source or test assertions.

An initial new-test prerequisite check incorrectly demanded a separate wheel
package; modern setuptools already provides the builder. It failed two new cases
in the container. Removing that unnecessary prerequisite retained all build/data
assertions; the final required lane passed. One after-suite was deliberately
interrupted to make this test correction; its partial log is retained separately.
Two intervening doctor runs correctly refused less than 1 GiB free space, including
a late project check after sample images filled the disk. Removing
only disposable task dependency/build caches restored space before the final run.
The final container put evidence and its timer scratch checkout on a real 2 GiB
RAM-backed filesystem; the disk threshold and all evidence checks stayed intact.

This is not a complete local pass of CI's sandbox-required package job. The real
bubblewrap probe was denied permission to create a namespace. The exact required
sample invocation ran, returned three needs-review outcomes, and the unchanged CI
evidence checker failed as intended; no successful isolated replay is claimed.
The directly requested front-door and timing entrypoints use their normal diagnostic
mode and both passed. The complete scripts and outputs are in the handover.

Final full after: 4,728 tests in 821.704 seconds, OK (skipped=60); no failures or errors. All EXPECTRAIL_* variables were unset.
Requested public export: python -m agents.export_scan bench docs README.md apps
--paths error, in a projection excluding restricted paths by metadata before opening.
Final public, patch and log scans and base-application checks are in the handover.

## Not done

No push, GitHub write, deployed-service call, deployment, model call, spend, real
dispatch, approval, workflow or source-game edit. No observation, verifier, gate
record, jit, onboarding or orchestrator implementation edit. No closure claim.
PR #603 had no requested code finding in the latest read-only review checked here.

## Files

- setup.py; tools/quickstart.py; tests/test_package.py
- docs/new-work/2026-11-17-wheel-quickstart-review.md
- The complete patch also includes the explicitly identified PR #599 prerequisite;
  its original file inventory and evidence remain in its own work-log entry.
