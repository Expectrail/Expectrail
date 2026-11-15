# Use the shared visual sampling policy (#330, PR #493)

## What changed

Reworked PR #493 after the merge guard's review of fb031ad. The anchored observer and the gate
now call agents.sam_observations.sampling_plan for each spec. Fractional visible checks use
all frames. Explicit coverage obligations remain strict, including on reaches witnesses.

For an eligible sampled check that does not pass, refine_targets prioritizes the first failing
stretch, then the observer inspects every remaining frame. A reaches witness between samples
can therefore pass; an unrefined non-pass cannot reject or accept. The gate counts actual
observation rows rather than trusting refinement metadata. A provider stop during refinement
needs review. Missing-player rejection is checked against the refined consecutive sequence.
The requested stride stays in findings; observations name the effective rate and refined frames.
Defaults, engine coverage, calibration and paired-comparison schedules are unchanged.

The docs and run summary describe the policy. The old phase-allocation and lookup-comparison
tables are explicitly marked "not reproducible from this pull request". They are historical,
not evidence for this revision. The original work log is left intact as a historical record;
this entry supersedes its sampling and cost-evidence claims. No spec or approval changed.

## What was run

Fetched the required historical commit, PR head fb031ad785e3df032d2e6710f291131689482933 and main
at a72ce90adb6e1e46a97e43ede69b5691af1bdc39. Main merged cleanly; the merge remains uncommitted.
The baseline full unittest suite ran 3,861 tests in 404.812 seconds: OK, 45 skipped, no failures
or errors. Full logs, regression logs and exact failing-name comparison are in the handover.

The offline regression probes cover the guard's 30/120 fractional visibility case, a reaches
witness between samples, no reaches witness, sparse failures, coverage, missing-player
refinement, isolated negative samples, and provider failure while refining. The sampling,
anchored observer, two-observer gate and outside-vision tests run without a model or engine.
The focused run passed all 107 tests in 33.647 seconds. All nine final regression probes fail
on the merged unreworked code and pass here. The after full suite ran 3,870 tests in
459.536 seconds: OK, 45 skipped, no failures or errors. Before and after failing
name sets are both empty; no new failing test. Command/exit metadata and skip reasons are kept
in the handover. The work-log checks and exact-base patch application checks pass.

## Not done

No live model, paid call, dispatch, engine replay, push, commit or GitHub write. No new live
cost or runtime claim. The earlier handover-only tables were not reproduced. Optional per-key
RecordingClient locking is deferred; its existing exact-question reuse behavior is unchanged.
Sean must apply, review and push the uncommitted merge plus rework.

## Files

- expectrail/anchored.py
- expectrail/gate/verify.py
- tools/outside_vision.py
- tests/test_vision_sampling.py
- tests/test_vision_sampling_policy.py
- docs/outside-projects.md
- docs/new-work/2026-11-15-vision-sampling-review.md
