# Third outside-project trial: System Override (#263)

**Result: blocked. Configuration-only onboarding was not demonstrated.**
The selected game was not replaced. No running gameplay, engine check, visual
finding, determinism claim or bug-detection rate was obtained. It is not added
to the working outside-trial list.

Trial date: November 15, 2026 (America/Chicago). This was an agent-operated product
trial, not the first-user test with an unfamiliar person. **Human setup minutes:
not measured.** The [numbered command log](commands.md) records all 31 trial
command invocations, their mistakes and stops, exact arguments, exit status,
what happened and what followed. Machine command time was **32.252 s**,
from [the command timing records](commands.json), excluding the nested variant
wrapper to avoid counting the same work twice. This sum is not wall-clock time
to onboard a game and excludes repository reading/writing and full-suite runs.

## Choice and pin

[The choice note](choice.md) was written before reading code or scenes or trying
onboarding. System Override is an independent author's top-down space shooter,
not a godotengine demo or starter template. Author: **aleshg / Aleš Gajdacz**.
MIT licence at **`f95712a9e88480251e3ba38880d7144bf3f7b33a`**. The README separately
credits CC0 music and an OFL font. The full pin was fetched; the game was not
vendored. Its README requires **Godot 4.1 Mono**, known at selection time.

Expectrail base: `a98dcb08c2d7fe068283e97148b07a37d423d91e` plus the requested pending role-box patch.
The audit is already merged on this base. This trial adds no changes under
`expectrail/`, `harness/`, `agents/` or `tools/`; core changes in the combined
handover are only the explicit prerequisite patch, unchanged from that review.

## What worked and what stopped

1. **Fetch at a full pin worked.** The first attempt failed because the trial's
   clean environment omitted the required proxy. Retaining network proxy settings
   fixed fetching, with no model keys copied. The same game was retained.
2. **Static inspect/init worked and refused to invent a binding.** They found
   nine custom actions and the menu entry, no player candidate, and wrote an
   unresolved draft. The original files are under
   [generated/](../../../tests/outside/system-override/generated/).
3. **The draft needed human decisions.** Init's first route pressed `exit` and
   `restart`. I wrote a short thrust/fire route and bound the gameplay scene's
   `Player Spaceship` and image. My initial `sprite` field was wrong; the tool
   named it and I changed it to `texture`. The config remained draft throughout.
4. **A headless route attempt failed.** With a schema-valid config selecting
   `res://scenes/main.tscn`, the command said:
   `bindings.player Player Spaceship not found on any tick; setup was not exercised`.
   It stopped on replay 1 of 3 and wrote no route. See
   [the actual output](evidence/19-auto-route.log). Config `entryScene` is validated
   but not passed into replay scene selection; the project still starts its menu.
   This path was stopped, not patched around. A .NET/toolchain mismatch also remains;
   the one failed attempt cannot isolate its effect from the wrong scene.
5. **Doctor and verify reported this machine's limits.** No xvfb/display, no
   rendering probe, and less than 1 GiB free. The provided binary is non-Mono
   Godot `4.7.2.stable.official.ed1daf0bf`, not the README's toolchain. No key or cap
   was supplied. Optional Chromium is absent too, but this Godot path does not
   require it. [Doctor JSON](evidence/13-doctor-cli.log).
6. **Three jobs were submitted and finished needs-review before replay.** No
   preflight was bypassed. There is no engine verdict underneath them to call
   pass or fail. The hidden-player variant did not demonstrate rejection.
7. **Draft policy and patches validate offline.** One route, zero approved checks,
   one draft check, `draft: true`, and zero reserved dollars in every job. The
   tracked pinned source stayed unchanged. Both changes applied to disposable
   copies and passed reverse checks. [Validation](evidence/31-validate-offline.log),
   [harmless patch proof](evidence/harmless-patch-proof.json),
   [broken patch proof](evidence/broken-patch-proof.json).
8. **Failure evidence was lost by the route command.** It printed a godot.log
   path under a temporary folder that was removed on exit. A later file-existence
   command returned 1. The concise binding error is preserved; the underlying
   engine log is unavailable, not silently reconstructed.

## Actual three-variant results

| Variant | Product result | Engine finding | Command seconds | Evidence |
| --- | --- | --- | ---: | --- |
| pinned | **needs-review** | not run | 1.593 | [job JSON](evidence/20-verify-pinned.log) |
| harmless | **needs-review** | not run | 1.303 | [job JSON](evidence/22-verify-harmless.log) |
| broken | **needs-review** | not run | 0.975 | [job JSON](evidence/23-verify-broken.log) |

All three records say `TOOL_MISSING` for display/rendering and disk. Their
`output` is null, their budgets reserve zero dollars, and their policy digests
match. Changed head-tree digests prove distinct variants were submitted. These
are **preflight refusals**, not evidence that draft checks executed or that
missing vision was the only blocker. A draft check is never counted as a pass.
There are zero measured gameplay frames here, so false-accept/false-reject and
bug-detection rates are **not measured**. There is no hosted CI run to link;
the local job records above are checked-in evidence.

## Draft check and seeded changes

[Trial inputs and reproduction instructions](../../../tests/outside/system-override/README.md).
The selected route is 150 ticks (2.5 seconds at the declared 60 Hz): pause 15,
hold positive thrust 60, pause 15, hold fire 30, pause 30. It does not represent
mouse aiming or a menu click, and was not successfully replayed.

The single draft asks that the player spaceship remain visible through that
initial thrust/fire sequence. It requires visibility on all 150 frames and at
least 150 judged frames. It is about this game's camera/player, not a platformer
floor. **Sean would be approving** the choice of gameplay entry, the player
binding/image, the adequacy of this short route, that initial gameplay should
keep the ship visible, and the exact 150-frame window/coverage. Review against
an actual clean replay before approving; we have no such replay yet. The draft
says nothing about aiming, hit accuracy, damage, enemies, scoring, victory or
later survival. No approval was added or requested from a model.

The broken patch hides the whole `Player Spaceship` node in the gameplay scene.
The harmless patch adds only a comment to its controller. These are proposed
seeded inputs, not observed behavioural outcomes. The upstream source is MIT;
small patch context retains the author's attribution in the trial README.

## Pinned source read for the trial

The source-read command did not become a vendored copy. These immutable links
are its reviewable inputs:

- [Project settings and input map](https://github.com/aleshg/SystemOverride/blob/f95712a9e88480251e3ba38880d7144bf3f7b33a/project.godot)
- [.NET project](https://github.com/aleshg/SystemOverride/blob/f95712a9e88480251e3ba38880d7144bf3f7b33a/SystemOverride.csproj)
- [Menu scene](https://github.com/aleshg/SystemOverride/blob/f95712a9e88480251e3ba38880d7144bf3f7b33a/scenes/main_menu.tscn) and [menu callback](https://github.com/aleshg/SystemOverride/blob/f95712a9e88480251e3ba38880d7144bf3f7b33a/scripts/MainMenu.cs)
- [Gameplay scene](https://github.com/aleshg/SystemOverride/blob/f95712a9e88480251e3ba38880d7144bf3f7b33a/scenes/main.tscn) and [player prefab](https://github.com/aleshg/SystemOverride/blob/f95712a9e88480251e3ba38880d7144bf3f7b33a/prefabs/spaceships/player_spaceship.tscn)
- [Player controller](https://github.com/aleshg/SystemOverride/blob/f95712a9e88480251e3ba38880d7144bf3f7b33a/scripts/PlayerController.cs), [input names](https://github.com/aleshg/SystemOverride/blob/f95712a9e88480251e3ba38880d7144bf3f7b33a/scripts/InputActions.cs), [ship](https://github.com/aleshg/SystemOverride/blob/f95712a9e88480251e3ba38880d7144bf3f7b33a/scripts/SpaceShip.cs), and [game logic](https://github.com/aleshg/SystemOverride/blob/f95712a9e88480251e3ba38880d7144bf3f7b33a/scripts/GameLogic.cs)

## Issue text and what needs Sean

[Three issue drafts and other stops](issues.md) give the symptoms, evidence,
where to look and the smallest proposed fixes. No issues were posted from this
session. The core scene-selection and toolchain gaps relate to the audit's #259;
the disappearing diagnostic relates to #329. The original project also has a
source-only case mismatch (`SpaceShip.cs` versus a `Spaceship.cs` resource path),
not fixed or tested here.

Sean's next steps, in order:

1. Route the issue text to #259/#260/#329 or open follow-ups. Honour or explicitly
   refuse the configured scene and incompatible .NET toolchain in separate code
   work. Do not merge fixes into this trial to turn the failure into success.
2. Prepare a Linux runner with working xvfb/rendering, at least the doctor's
   1 GiB free in its named folders, and a supported .NET build path. Decide how
   to handle the upstream case mismatch and old SDK explicitly; any upstream
   adaptation must be recorded as a different trial input. Installing ordinary
   Godot 4.7.2 alone has not been shown sufficient.
3. Re-run the pinned config-only onboarding instructions with every stop recorded.
   Do not add this project to the working outside-trial list until that succeeds
   without a further core edit. No workflow change was made here.
4. Review the draft against real clean gameplay, then personally approve only
   if it expresses the intended behaviour. Re-run pinned, harmless and broken;
   report engine findings separately from the product verdict. Without vision,
   no acceptance is demonstrated. Any paid calibration/vision run is a separate
   decision for Sean; no such run is requested or performed by this trial.

## Not done

No complete replay, captured frame, clean calibration, live model request,
engine finding, accepted outside change, native macOS/Windows run, first-user
session, hosted CI run, workflow edit, approval, commit, push or GitHub write.
No core change to make the selected game fit. No held-out or fresh-* content read.
The game remains the original selection even though onboarding stopped.
