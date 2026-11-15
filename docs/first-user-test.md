# First-user test kit (#268) — needs-sean

**Not run yet.** Sean or Timothy recruits someone who has never used Expectrail. This human session is separate from machine timings; neither substitutes for the other. Ask permission to take notes. Record no credentials or private source.

## Exact starting point

Use a fresh checkout of the tested main commit, with no Expectrail virtual environment or saved runs. Open a terminal at its root and the [README](../README.md); follow its [quickstart](quickstart.html) link. Record the commit, date and machine prerequisites already prepared (Linux, Python 3.12+, display, Godot). Do not silently fix missing tools. Keep keys and caps absent; do not approve checks or spend money during the session.

Ask the person to bring a project they may share. Start with the published bundled sample and Crate Run draft, then let them attempt their chosen project using the documented path instructions. If bindings, routes, approved checks or vision are missing, record the stop. A sample result does not verify their project. [Scope](capabilities.md#installed-command) · [Approval/verdict limits](capabilities.md#orchestrator).

## Say / do not say

Say: “Use these instructions to get a result. Please think aloud when you are unsure. This tests the instructions, not you. Tell me when you think you have a verdict and what its evidence tells you.”

Do not explain the expected verdict, point to a command, edit their input, explain an error, or suggest needs-review is a pass. At a stop, ask “What were you expecting here?” Record their words. If they request help, record its time and exact content; mark the rest **assisted**. Do not restart the clock. Debrief misunderstandings afterward, preserving the unaided answer; use the [concepts page](concepts.html) as the reference.

## Time and observe

Start the stopwatch when they first see the README and may act. Record **human minutes to the first displayed verification verdict**, including reading, installation and waits. Doctor output is not a verdict. Also record when they notice the verdict and find its evidence. Time their chosen-project attempt separately.

Agree on a session limit beforehand. If no verdict appears, write **“not reached” plus elapsed minutes**, never zero. Log interruptions. At every stop, note elapsed time, page/command, their exact words, next action and help given. Keep observations separate from your interpretation. Ask what the verdict covers, what remains unknown and which evidence supports it.

## Results template

- Date; facilitator; participant alias; consent; no prior use confirmed:
- Checkout commit; OS/Python; prepared tools/caches; starting URL; time limit:
- Chosen project (non-sensitive description); sharing permission; initial routes/checks:
- Start time; first verdict/job/evidence reference; human minutes (or “not reached” + elapsed):
- Minutes to notice verdict / find evidence; chosen-project start and time to its verdict:
- Each stop: elapsed minutes | page/command | their words | next action | help:
- What the report did not explain, in their words; interruptions; assisted/unaided; follow-up issues:
- did they understand the verdict and its evidence: yes, partly, no, and why

## From init to a saved draft config (#331)

Use a disposable copy of each game. Start the clock when the admin runs the
first command. Stop when the chosen `expectrail.project.json` is saved beside
`project.godot`. Record pauses, help, file-picker actions and actual clicks.
Keep this time separate from time to a verified change.

```sh
game=./my-game
expectrail init "$game"
expectrail onboard --project "$game"
```

Generating the review page writes `expectrail-review.html` in the game folder by
default. Opening that page changes no game file. Use `--out PATH` to generate it
elsewhere.

1. Open the local HTML address printed by the second command. Review the player
   node, images and route inputs. The images come from the project. The page
   carries its own content and download links and works with JavaScript off.
2. If the binding is right, use the link below. For Dodge, the link under the
   chosen image both selects it and downloads the draft. If none fits, leave
   the draft unsaved and record the stop.
3. Save the download as `expectrail.project.json` in the game folder. If the
   browser saves to Downloads, move it there. For the bundled game and
   kinematic-character, confirm replacement of the draft from init. Browser and
   OS file-picker clicks vary, so record those separately from page clicks.

| Game | Action on the review page | Page clicks for this path | Human minutes |
| --- | --- | ---: | --- |
| Bundled platformer | Check Level/Player and robot.webp, then click “Save these bindings”. | 1 | not measured |
| kinematic-character | Check Player and player/player.png, then click “Save these bindings”. | 1 | not measured |
| Dodge the Creeps | Compare the four player frames, then click “Use … and save” under the representative image. | 1 | not measured |

Opening the page and saving the file are separate from the page click. If the
config needs more work, record “not reached” and why. Saving bindings leaves
the config in draft. Approving the checks is a separate, explicit human step.
