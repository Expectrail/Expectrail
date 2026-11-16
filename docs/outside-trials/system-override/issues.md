# Issue text from the third outside-project trial

Not posted to GitHub. These are findings for Sean to route to the existing issues
or open separately. No core change was made for this trial.

## 1. Configured entryScene is validated but not used for replay (#259)

**What happened.** System Override starts at a menu. The user config selected
`res://scenes/main.tscn` and bound `Player Spaceship`. `inspect` still reported
`res://scenes/main_menu.tscn`. The headless public route command ended with:

> configured replay refused: "expectrail: bindings.player Player Spaceship not found on any tick; setup was not exercised"

[Commands 16 and 19](commands.md) preserve the output. No route was published.
This is a failed config-only onboarding attempt, not a successful replay with an
empty check. The initial menu's New Game button changes to the gameplay scene
from a C# callback; its text scene has no shortcut or explicit initial focus.
We did not add a shortcut or change project.godot to rescue the trial.

**Where to look.** `expectrail/project_config.py` validates `entryScene` as a file;
`expectrail/onboarding.py` inspects project.godot's entry scene. `harness/run.py`
reads the config's frame rate and bindings but does not apply its entryScene;
the harness injection leaves the Godot project main scene unchanged.

**Smallest proposed change, not implemented.** Carry the base policy's selected
entryScene into the staged replay's scene selection (or explicitly refuse a
mismatch before importing). Test a menu/gameplay project with different scenes.
This would address scene selection; it would **not** prove that this .NET game
runs. Do not promise the trial is fixed until its other blockers are checked.

## 2. A Mono/.NET toolchain declaration is not enforced before running (#259/#260)

**What happened.** The README requires Godot 4.1 Mono and the project has a
`SystemOverride.csproj` targeting net6.0 with `Godot.NET.Sdk/4.1.0-dev.1`.
The config's toolchain says `4.1-mono`. Project selection accepts that declaration,
and the route command nevertheless uses the provided non-Mono Godot
`4.7.2.stable.official.ed1daf0bf`. `doctor` reports that binary as OK. It has no
project argument to compare against that project's C# requirements. See
[commands 13, 19, 26 and 31](commands.md).

**Where to look.** `expectrail/doctor.py`, `expectrail/project_config.py`, and the
engine selection/import/build path in `harness/run.py`. This is the audit's known
toolchain-enforcement gap, encountered on an actual outside project.

**Smallest proposed change, not implemented.** Refuse this project early with a
named .NET/toolchain mismatch and a fix. Supporting it fully also needs an
explicit .NET build/import path at a tested compatible version; that is larger
than a diagnostic. The single failed route does not isolate the effects of Mono
from the wrong entry scene. No claim that a .NET binary alone fixes the game.

**Separate upstream caveat, source-only.** The pinned scene references
`res://scripts/Spaceship.cs`, while the tracked file is `scripts/SpaceShip.cs`.
That case mismatch matters on a case-sensitive filesystem. We did not rename it
or test a corrected upstream game. It is not an Expectrail patch and should not
be described as a measured runtime failure here.

## 3. Failed auto-route refers to a diagnostic file it deletes (#329)

**What happened.** Command 19 pointed to
`/tmp/expectrail-auto-route-qbzcaq91/1/godot.log`. After exit, command 24's
`test -f` returned 1. The diagnostic location no longer exists. The concise
binding refusal survived on stderr, but the engine's full errors were lost.

**Where to look.** `expectrail/route.py:auto_route`, its TemporaryDirectory and
exception path. No private API or patched runner was used to retain a replay.

**Smallest proposed change, not implemented.** Copy the failure log to a named
persistent output, or emit a bounded diagnostic excerpt before deleting the
scratch directory. Test the error path and the promised path's existence.

## Other stops, not attributed to core bugs

- Missing xvfb/display and less than the doctor's 1 GiB free-space requirement
  blocked all three verify jobs. Doctor and job records named these correctly.
- No model key or cap was supplied. This trial was explicitly unpaid.
- Init's route presses `exit` and `restart` and cannot aim a mouse. It is labelled
  draft. We replaced it with a hand-written thrust/fire route; we did not claim
  it starts the menu or proves shooting. A suggestion to avoid destructive
  action names would need its own design, not a special case for this game.
- Initial `python3 -m expectrail` invocations were my mistake; the source checkout
  entry point is `python3 -m expectrail.cli`. Likewise I initially wrote `sprite`
  instead of the schema's `texture`, and corrected it following the error.
- The one-off artifact validation script initially used the loader's wrong path
  type, then failed to register a local JSON Schema reference. These are trial
  tooling mistakes; final offline validation passed. One default reference lookup
  reached a public schema URL and returned 404; no model request was made.
