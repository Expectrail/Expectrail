# First-user test kit

## A Godot developer tries their own game (#750)

**Awaiting the first own-game observation.** Sean or Timothy recruits a Godot developer who has never used Expectrail.
Start with a change they want to check in their own game. Hold any sample
demonstration until after their session record is closed.

**Before they start.** Ask permission to observe and take redacted notes. Use
trusted local copies they have permission to run. Ask whether they allow draft
files to be written to those copies. Omit private source, screenshots without
permission, credentials and app access URLs. Agree on a time limit. Give them
the wheel and the [install instructions](install.md#install-and-open-the-local-app),
or access to the installed app if that is what you are testing. Record what you
prepared, including project setup and available observers. This protocol uses
existing check approvals and requires no paid model calls.

**Read aloud.** “Use Expectrail to check a change you care about in your game.
Tell me when you've learned enough to decide what to do next, or when you
would stop. Please talk me through what you're thinking.”

**Observe.** Start one clock when they receive the install instructions or
access to the installed app and can act. Include reading, installation,
waiting and interruptions. If you supplied an installed app, label the time
“from installed app” so readers can see where the clock began. Watch silently.
At a stop ask “What were you
expecting?” Record any help verbatim and mark subsequent work assisted.
Close the record at their decision, their stop or the agreed limit. Ask
“What did you learn about the change? What led you there? What would you do next?”

**Record the furthest point reached.** An install failure, no second version,
unresolved bindings, no usable route or no approved checks can end the attempt.
**Check folders** and saving a draft are preflight steps. If setup stops there,
record “no job started” and the message. If submission is uncertain, record
that uncertainty. For a confirmed job, keep its ID, phases and exact result.
A job can return **Needs review** with a reason and partial evidence. Record
“no verdict” if the job failed, was cancelled, could not be carried out or
was still running at the time limit. Use the [app guide](app.md) and
[evidence viewer guide](viewer.md) for the debrief.

### Own-game observation sheet

Copy this blank sheet for each participant. Use elapsed minutes and seconds.
For each missed milestone write “not reached”, the elapsed time and the reason.

| Observation | Session notes |
| --- | --- |
| Date, facilitator, alias, first use confirmed, permissions and time limit | |
| OS, wheel/build and instructions revision, prepared Python, browser, Godot, display, caches, vision and project setup | |
| Start time, install or installed access, time app opened | |
| Project alias and intended change in their words. Before and After version identifiers and how they found each | |
| Time of folder selection and setup. Routes, bindings and approved checks available or missing | |
| Time verification requested, job ID, progress shown and when they noticed it | |
| Time result appeared and time they noticed it. Exact state, reason and what they thought it meant | |
| Time evidence opened, route and check examined, first decisive frame or tick they identified and why | |
| At that tick, measurement source, paired Before and After values, units and bound if shown. Record first difference and first failure separately when they differ | |
| Missing frames, readings, observers or unchecked behavior. What could they conclude? | |
| End time, total human elapsed time, furthest unaided step and developer's next action in their words | |

Add a row for every hesitation, stop, interruption, terminal command or request
for help. Record who entered each command, including during installation.
Keep any later verdict and mark the session as requiring terminal input if a
command was needed. Record a terminal window opened by the launcher separately.
If nobody entered a command, write “no terminal input”.

| Elapsed | Page, action or redacted command | Exact message and participant's words | Help requested or given, by whom | What happened next |
| --- | --- | --- | --- | --- |
| | | | | |

If the developer already has a second candidate for the same change and
chooses to try it, record its version, job and outcome on a second sheet.
Ask which observation explains the difference between the two outcomes.
Keep the time to the first verdict on the original sheet.

## Prepared walkthroughs

The grant-judge walkthrough demonstrates a prepared sample. Show it only after
closing the own-game record, and keep any notes with the demonstration.

### Local app trial for a non-developer (#370)

Follow the [two-copy walkthrough](trials/370-first-user.md) for its separate
non-developer trial. It uses supplied clean and broken games. Keep its results
and timings with that trial.

## Historical checkout and CLI study (#268)

Sean or Timothy recruits someone who has never used Expectrail. Ask permission
to take notes and omit credentials and private source. Human timings for this
study remain unmeasured.

### Exact starting point

Use a fresh checkout of the tested main commit, with no Expectrail virtual environment or saved runs. Open a terminal at its root and the [README](../README.md); follow its [quickstart](quickstart.html) link. Record the commit, date and machine prerequisites already prepared (Linux, Python 3.12+, display, Godot). Do not silently fix missing tools. Keep keys and caps absent; do not approve checks or spend money during the session.

Ask the person to bring a project they may share. Start with the published bundled sample and Crate Run draft, then let them attempt their chosen project using the documented path instructions. If bindings, routes, approved checks or vision are missing, record the stop. A sample result does not verify their project. [Scope](capabilities.md#installed-command) · [Approval/verdict limits](capabilities.md#orchestrator).

### Say / do not say

Say: “Use these instructions to get a result. Please think aloud when you are unsure. This tests the instructions, not you. Tell me when you think you have a verdict and what its evidence tells you.”

Do not explain the expected verdict, point to a command, edit their input, explain an error, or suggest needs-review is a pass. At a stop, ask “What were you expecting here?” Record their words. If they request help, record its time and exact content; mark the rest **assisted**. Do not restart the clock. Debrief misunderstandings afterward, preserving the unaided answer; use the [concepts page](concepts.html) as the reference.

### Time and observe

Start the stopwatch when they first see the README and may act. Record **human minutes to the first displayed verification verdict**, including reading, installation and waits. Doctor output is not a verdict. Also record when they notice the verdict and find its evidence. Time their chosen-project attempt separately.

Agree on a session limit beforehand. If no verdict appears, write **“not reached” plus elapsed minutes**, never zero. Log interruptions. At every stop, note elapsed time, page/command, their exact words, next action and help given. Keep observations separate from your interpretation. Ask what the verdict covers, what remains unknown and which evidence supports it.

### Results template

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
