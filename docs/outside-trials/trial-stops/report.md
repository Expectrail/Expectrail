# Three trial stops: Part A (#259)

This is the product-fix slice, plus the repeat of System Override. The new
independent-author GDScript trial has **not started**. It must be a separate
trial with its choice frozen before inspection; it is not counted as successful.

## System Override at the original pin

The source remains `aleshg/SystemOverride` at
`f95712a9e88480251e3ba38880d7144bf3f7b33a` (MIT). `git diff --exit-code` was
empty. The manual draft config from the first trial remains a draft.
[All four actual commands, timings, exit codes and complete outputs](system-override-refusals.json)
are recorded in numbered order. Doctor returns 3; inspect, init and auto-route
return 5. Each names `SystemOverride.csproj` and says:

> this project needs Godot .NET; only GDScript projects are supported today.

No engine or model ran, and no automatic route was published. This is an honest
unsupported-project refusal, not a verdict or a successful onboarding.
The first attempt to invoke these commands used `python3 -m expectrail`, which
this repository does not expose. It failed before invoking the product; the
corrected commands use `python3 -m expectrail.cli`. Both attempts are in the
handover logs.

## Entry scene and failure logs

Inspect and init inspect the configured text scene. Replay and auto-route start
that same scene explicitly. A missing, outside-project or non-text entry scene
is refused rather than silently replaced by the main scene. When the gate supplies
the base config, the head cannot choose a different scene by editing its config.
Unconfigured projects retain their implicit main scene.

The support check detects a `.csproj`, C# source, C# scene/resource reference,
Godot C#/.NET feature/settings declaration or a Mono/.NET toolchain declaration.
It ignores the generated `.godot` cache and comments. This conservative GDScript-only
support boundary is not a security sandbox or .NET support.

An unsuccessful replay during auto-route keeps bounded diagnostic files beside
`--out`, in `<route-file>.failed-<unique suffix>/`. The message names a surviving
`failure.txt`, and any named `godot.log` is retained there. Unrelated symlink
targets are not copied. If writing diagnostics itself fails, the message says
that no log path is available.

## Validation

`tests.test_trial_stops` tests the three stops with offline stand-ins and a real
Godot auto-route. The latter uses a fixture whose main scene is a menu while its
config names gameplay: three replays must be identical and the player must move.
A subprocess blocks NumPy and Pillow imports while loading the test module.

The handover includes red logs from unmodified product code, green logs, full
suite logs, and raw before/after replay evidence. Published before/after totals
and results are in the work log and PR body. No approved check was edited.
