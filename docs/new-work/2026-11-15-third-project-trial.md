# Third outside project: a blocked config-only trial (#263)

## What changed

Selected System Override (aleshg, MIT), fixed the choice before inspecting its
integration, and fetched full pin f95712a9e88480251e3ba38880d7144bf3f7b33a.
Recorded a fresh init/inspect/config/route/check trial and every attempted
onboarding command, including operator mistakes. Added one unapproved draft
check, a hidden-ship patch and a harmless comment patch. The project is not
added to the working outside-trial list: onboarding was blocked. No game is
vendored and no core edit was made to make it fit.

This is built on current main a98dcb08c2d7fe068283e97148b07a37d423d91e plus the
pending role-box patch, applied unchanged. The preceding audit is already on
main. That prerequisite is separated from this trial in the handover.

## What was run

See [the report](../outside-trials/system-override/report.md),
[31 numbered commands and stops](../outside-trials/system-override/commands.md),
and their machine-readable timings and outputs. Three actual verify jobs ended
needs-review during preparing, naming missing display and disk prerequisites.
No replay or engine finding was produced. The headless route command attempted
replay 1 of 3, refused a player binding not found on any tick, and wrote no route.
The selected config entryScene is not used for replay selection; the .NET
requirement remains unresolved. Draft selection reports one draft and zero
approved checks. Config, route, check and all three job records validate against
local schemas. Both seeded patches passed application and reverse checks.
No live-model key or cap was passed to the commands; job budgets reserved zero.

Before: **4,094 tests, 0 failures, 0 errors, 49 skips, 434.142 s**.
After: **4,094 tests, 0 failures, 0 errors, 49 skips, 434.048 s**.
Failing-name sets are both `[]`; skip names and reasons are unchanged.
Command: `python3 -m unittest discover -v -s tests -t .` with model keys/caps
and Godot override unset. Logs and a failure/skip-name comparison are in the
handover. Completed generated test fixtures were cleaned between runs to stay
within this workspace's disk limit; no assertions or tests were changed.
No test was edited or added for this trial; prerequisite test changes belong to
the unchanged role-box patch.

## Not done

Config-only onboarding failed. No gameplay, measured check, captured frame,
calibration, visual finding, bug-detection rate, human onboarding minutes or
accepted outside change was demonstrated. No paid request, approval, workflow
edit, commit, push or GitHub write. No forbidden material read. Three issue
texts are provided for Sean; no core blocker was fixed in this trial.

## Files

- docs/outside-projects.md: honest current table and trial link.
- docs/outside-trials/system-override/: pre-inspection choice, command/stop log,
  machine timings, actual outputs, results, report and issue text.
- tests/outside/system-override/: draft config, route, check, generated init
  proposal, seeded patches and reproduction instructions; no game source.
- docs/new-work/2026-11-15-third-project-trial.md: this log.

The full handover separately names the unchanged role-box dependency files.
