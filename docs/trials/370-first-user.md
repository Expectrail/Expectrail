# First-user trial for the Expectrail local app

**Sean runs this session.** Recruit one person who does not develop software and
has never used the terminal workflow. Use a clean account on a supported Linux
machine. Record every prerequisite you set up beforehand and the exact wheel,
its SHA-256, and the install instructions revision. Prepare two copies of the
bundled platformer with the same route and check files, one clean and one with
the published fall-through patch. Use `sample.checkout` from the checkout's
`expectrail.orchestrator.sample` module to prepare each folder. Give the
participant the wheel link, the install instructions and the two folder locations.
Record whether the machine
has vision configured and which observer actually answered. Keep keys and
personal information out of the notes.

**Include this on the instruction card:** In Expectrail, open **Older projects
without a config** and tick **Enter paths manually**. Enter `game/platformer`
for Game folder, `harness/routes/smoke.json` for Route files, and `agents/specs`
for Checks folder. Use the two supplied locations for Before and After. Click
**Check folders**, then **Verify**. Swap Before and After for the second run.

**Read to the participant:** “Install and open Expectrail using these
instructions. Check a change from the clean copy to the broken copy. Find and
explain the result. Then check the change from the broken copy to the clean
copy. Find and explain what that result lets you conclude.”

Watch silently through the first attempt. Note where they hesitate, what they
click, their words and any help they ask for. Give help only after recording
that they got stuck. Ask them to show which folder they used on each side,
where the job's progress appears, and where the evidence says what was checked
or left unchecked. Ask what they would do next for each result.

| Record | What to capture |
| --- | --- |
| Install and open | OS, prerequisites, start and end time, each action, browser opened or fallback used, every error and prompt |
| Broken and repaired | Before and After labels, job IDs, input digests, decisions, observer source, evidence opened and unchecked scope |
| Comprehension | Their explanation of each result and their next action, in their own words |
| Stumbles | Exact step and wording, time spent, help given and whether they could resume |
| Outcome | Which steps they finished unaided. Quote the result shown, including needs-review if vision was unavailable. |

Save the timings and observations with the two job records and evidence, using
redacted local paths. Mark the trial incomplete if they could not install, run
both comparisons and read both results without help. Keep any proposed fixes
separate from the trial record.
