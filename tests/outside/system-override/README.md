# System Override — blocked config-only trial (#263)

Source: https://github.com/aleshg/SystemOverride
Pin: `f95712a9e88480251e3ba38880d7144bf3f7b33a`.
MIT, Copyright (c) 2023 Bc. Aleš Gajdacz. Keep the upstream licence when fetching.
The small contextual lines in the seeded patches come from that MIT source.
No game is vendored here. README credits also name CC0 music and an OFL font.

This project is deliberately **not in `tests/outside/projects.json`**: the trial
could not onboard it through config alone. See the
[choice, numbered stops and results](../../../docs/outside-trials/system-override/report.md).
The patches are trial inputs, not established regression fixtures with measured
engine outcomes.

- `generated/`: exact unresolved init proposal and its first route, retained for
  comparison. The generated route presses exit/restart; do not confuse it with
  the selected route.
- `expectrail.project.json`: manual completion, still `draft: true`, selecting
  the gameplay scene and its `Player Spaceship` node/image. The toolchain is the
  README requirement, not a promise that Expectrail can build it.
- `routes/thrust-fire.json`: 150 ticks at 60 Hz; pause 15, hold positive_thrust
  60 ticks, pause 15, hold fire_weapons 30 ticks, pause 30. There is no mouse
  positioning, no menu click and no claim that a round started.
- `checks/ship-visible.json`: one **unapproved draft**, visible over all 150
  frames, at least 150 judged frames. Names under `approvedContracts` select
  files; that field does not approve them.
- `changes/broken.patch`: hide the whole Player Spaceship node, including its
  children. Intended bug: the player's ship is not drawn while controls/physics
  remain active. **Not demonstrated on a running game here.**
- `changes/harmless.patch`: a C# comment only. Both patches have passed forward
  and reverse application checks against the pin.

## Fetch and lay out the draft (no approval)

From an Expectrail checkout with the role-box dependency applied, set `REPO` to
its absolute path. Choose an unused temporary directory outside that checkout.
These are reproduction instructions, not a claim the blocked replay now works.

```sh
REPO=/absolute/path/to/Expectrail
TRIAL=/absolute/path/to/empty-trial-directory
mkdir -p "$TRIAL"
git init "$TRIAL/game"
git -C "$TRIAL/game" remote add origin https://github.com/aleshg/SystemOverride.git
git -C "$TRIAL/game" fetch --no-tags --depth=1 origin f95712a9e88480251e3ba38880d7144bf3f7b33a
git -C "$TRIAL/game" checkout --detach f95712a9e88480251e3ba38880d7144bf3f7b33a
cd "$REPO"
python3 -m expectrail.cli inspect "$TRIAL/game" --json
python3 -m expectrail.cli init "$TRIAL/game"
cp tests/outside/system-override/expectrail.project.json "$TRIAL/game/"
mkdir -p "$TRIAL/game/routes" "$TRIAL/game/checks"
cp tests/outside/system-override/routes/thrust-fire.json "$TRIAL/game/routes/"
cp tests/outside/system-override/checks/ship-visible.json "$TRIAL/game/checks/"
python3 -m expectrail.cli doctor --no-fetch --json
python3 -m expectrail.cli route --project "$TRIAL/game" --auto --out "$TRIAL/game/routes/auto-checked.json"
python3 -m expectrail.cli verify --project "$TRIAL/game" --base "$TRIAL/game" --jobs-root "$TRIAL/jobs" --json
```

Do not proceed past a core blocker by editing the game or verifier. Missing
machine tools are distinct from core limitations. This trial stopped the route
path after the named binding failure. Verification was still invoked to record
its real preflight refusal; it did not bypass it.

For each variant, make a disposable copy of `game` outside the Expectrail
checkout. Apply its patch **there**, and check it took before submitting:

```sh
cp -a "$TRIAL/game" "$TRIAL/broken"
git -C "$TRIAL/broken" apply --check "$REPO/tests/outside/system-override/changes/broken.patch"
git -C "$TRIAL/broken" apply "$REPO/tests/outside/system-override/changes/broken.patch"
git -C "$TRIAL/broken" apply --reverse --check "$REPO/tests/outside/system-override/changes/broken.patch"
python3 -m expectrail.cli verify --project "$TRIAL/broken" --base "$TRIAL/game" --jobs-root "$TRIAL/jobs" --json
```

Repeat with `harmless` and `harmless.patch`. Never remove the draft flags or add
an approval for these commands. With draft checks, zero approved checks must not
be treated as a passing engine test. The reported local jobs all stopped earlier
at machine preflight, with no engine finding and no captures.
