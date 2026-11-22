# First-user trial for the Expectrail local app

**Sean prepares the session.** Recruit one person who does not develop software
and has never used a terminal. On a clean Ubuntu 24.04 amd64 account, provide
the rehearsal desktop package and the [graphical install steps](../install.md#install-and-open-the-local-app).
Record its filename and SHA-256, the install instructions revision and any
prerequisites you supply. For a no-spend trial, leave the vision key and spend
cap unset. Record which observer actually answered. Keep keys and personal
information out of the notes.

Before the participant arrives, run this once from the matching Expectrail
checkout. Choose a new destination whose parent already exists.

```sh
python3 -m tools.prepare_app_trial "$HOME/Expectrail trial"
```

Give the participant the two folders it prints. **Clean** contains the bundled
game. **Broken** has the published fall-through patch. Both have the smoke route
and the same existing ground check.

**Participant card**

1. Install Expectrail using the supplied instructions and open it from Applications.
2. Select **Choose Before folder** and choose **Clean**. Select **Choose After folder** and choose **Broken**.
3. Select **Check folders**, then **Verify**. When the job finishes, select **Open this job’s evidence viewer** and explain the result.
4. Choose **Broken** for Before and **Clean** for After. Repeat the check and read the second result.

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
