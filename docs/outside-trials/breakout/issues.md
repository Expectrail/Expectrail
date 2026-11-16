# Follow-up issue text from the Breakout trial

No issues were posted. These are proposed texts for Sean to file. The source is
`mike0697/Breakout` at `0ac7aed444ea593a023d9b666c211d7ab8acd51e` (MIT).
No core fix was made during the trial.

## Route inputs cannot start and steer this mouse-controlled game

**What happened.** Init found only the authored `pause` action. Auto-route made
three identical 93-tick traces and explicitly reported no useful movement. A
manual 120-tick route sent `ui_focus_next` then `ui_accept`, followed by pause and
resume. The rendered replay stayed on the Start menu. In pinned, harmless and
broken captures the paddle stayed at `[168, 616]`, the ball stayed at its launch
position, and each trace had one distinct player position. The screenshot at
frame 40 still shows the menu. The injected physics defect never executed.

**Evidence.** Commands 16 and 31–33 in [commands.json](commands.json),
[results.json](results.json), [frame 40](menu-frame-40.png), and the per-variant
traces under `evidence/`. The game's `scripts/paddle.gd` reads the viewport mouse
position; its game manager pauses the scene until the Start button is pressed.

**Where to look.** `contracts/route.schema.json` represents only an action and
pressed state; there is no pointer coordinate or mouse-button event.
`harness/godot/expectrail_harness.gd::_event_for` explicitly falls back to an action
event when an input needs a place or amount. Also inspect the route recorder and
`expectrail/route.py`. Keyboard focus/accept did not start this particular menu
in these runs; the precise GUI event/focus cause was not diagnosed here.

**Smallest useful follow-up.** Define bounded, tick-indexed pointer positions and
button events with an explicit coordinate system, including schema/example,
recorder/writer and harness reader tests in one change. Demonstrate that this
pinned game's real menu starts and the route deliberately steers its paddle.
Keep the existing action-only format readable. A game-source shortcut is not a
config-only onboarding result. Do not approve these draft checks until the route
actually enters play and the seeded defect is exercised.

## The outside-trial list cannot represent a project at repository root

**What happened.** This game's `project.godot` is at repository root. A read-only
registration probe called the existing `tools.outside_trial.load_list` with
`path: "."` and received:

> breakout: path must be a plain path inside its repository

The probe did not modify `tests/outside/projects.json`. The game is not added to
the working list: gameplay onboarding failed, and this registration is refused.

**Evidence.** Command 35 and
[evidence/cli/35-registration-probe.txt](evidence/cli/35-registration-probe.txt).

**Where to look.** `_PATH`/`load_list` and `fetch` in `tools/outside_trial.py`.
From code inspection, `lay_out` also copies the upstream project plus route/spec
folders; it has no overlay for this trial's new config. That overlay limitation
was not executed through CI in this trial.

**Smallest useful follow-up.** Represent the repository root explicitly and
validate it safely. Add a reviewed config/route/check overlay to the pinned fetch
path, preserving draft status; never substitute the platformer's check. Test
both root and nested projects without fetching or approving anything in tests.

## Stops that are not proposed product defects

- Two candidate bodies (Paddle and Ball) made init ask for a manual player binding.
  Supplying the paddle node and its existing texture in the config resolved it.
- The initial machine lacked display discovery and enough free disk. Existing
  display tools plus the documented `TMPDIR`/`EXPECTRAIL_TOOLS` settings made the
  engine, display, OpenGL and disk checks pass. The session's temporary filesystem
  resets between tool calls, so directories had to be created inside each run.
- Nested bubblewrap could not create a uid map on this host. The recorded captures
  are diagnostic and **not isolated**, as their replay records say.
- Draft checks do not judge a CLI verification; all three jobs say no checks ran.
  That is the approval rule working, not a reason to add an approval here.
- The ball-launch draft fails on all three unstarted menus. The evaluator preserves
  an observed assertion failure even when the checkpoint is not reached. It is
  **not seeded-bug evidence** and is not ready for approval. The bounds draft is
  needs-review / not-exercised. Review lifecycle conditions after usable input
  control exists; no evaluator rule was changed in this trial.
- The logging helper had a brace typo; the first ad hoc validator used a nonexistent
  function; the first ball draft used the wrong boundary shape; the first diagnostic
  helper passed the whole route as its expected window. Each was corrected in trial
  scaffolding/drafts, recorded in the handover, and is not blamed on the product.
  The final diagnostics use the gate's existing `window_frames` function.
