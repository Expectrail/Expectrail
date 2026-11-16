# Run the hosted gate trials (#254)

The kit makes local branches and prints commands. **It never pushes, opens a PR, runs a workflow,
uses a token or changes a setting.** Sean does the GitHub steps. These trials do not close #254
until their hosted results are saved. Allow normal queue/replay time after each minute of setup.

1. **Choose an existing disposable public test repository.** Use its `OWNER/TEST-REPO` below.
   Never use `Expectrail/Expectrail`. The test repository must already have the existing gate
   workflows and dedicated App installation. Have a fork for the fork trial. The exact
   [setup and settings checklist](../tools/gate_trials/README.md#one-time-setup-sean-only) is for Sean.

2. **Open a terminal in your Expectrail checkout.** Once this kit is available, update the local
   pointer to main. Prepare all trials from that same pointer; do not fetch again between them.

   ```bash
   git fetch origin main
   ```

3. **Prepare the correct fix.** Replace `OWNER/TEST-REPO` with your test repository's name.

   ```bash
   python3 -m tools.gate_trials.correct_fix --target OWNER/TEST-REPO
   ```

4. **Copy the first printed push command.** Run it in the same terminal. On the test repository's
   GitHub page, Settings → General → Default branch: select the printed `.../base` branch.
   Restrict the existing `main-only` environment to that branch. This is the buggy test base.

5. **Copy the second printed push command.** On GitHub, open a pull request from the printed head
   branch **into that default base**. Paste `work/gate-trials/correct-fix/pr-body.txt` into its
   description. Do not merge the seeded trial into Expectrail's repository.

6. **Wait for the two checks, then read them.** Replace `123` with the PR number.

   ```bash
   python3 -m tools.gate_trials read --repo OWNER/TEST-REPO --pr 123
   ```

   Expected: both checks succeed; the comment demonstrates the seeded repair 3 times of 3.
   An unmatched recording or missing evidence is FAIL, not permission to call a model.

7. **Prepare the wrong fix; repeat steps 5–6.** Its description file is under `wrong-fix`.

   ```bash
   python3 -m tools.gate_trials.wrong_fix --target OWNER/TEST-REPO
   ```

   Expected: evidence succeeds, clearance fails with `reject`, and the comment names
   `player-stays-above-ground` with after=fail and its reason.

8. **Prepare the new-head trial.** Use its first two push commands and description to open a PR.
   When its first **Expectrail verify** capture finishes, run the third printed push command.

   ```bash
   python3 -m tools.gate_trials.new_head --target OWNER/TEST-REPO
   ```

   Read the PR again. An explicit stale refusal is PASS. A skipped/pending judge alone is FAIL /
   incomplete proof. For a repeatable timing window, Sean first uses the exact separate
   [trusted-job pause](../tools/gate_trials/README.md#new-head-timing-sean-only); this kit changes no workflow.

9. **Prepare the tamper control.** Normal PR code cannot replace an already uploaded artifact.
   The [tamper instructions](../tools/gate_trials/README.md#tamper-boundary-and-rehearsal) explain the
   proof and the separate person-controlled hosted experiment. Local mutation is not hosted proof.

   ```bash
   python3 -m tools.gate_trials.tamper --target OWNER/TEST-REPO
   ```

10. **Prepare the fork trial.** Replace `FORK-OWNER/TEST-REPO` with your existing fork.
    Push base to the test repository and head to the fork, as printed; open a fork PR into the
    test default branch. Paste its description. Check the secret/trusted-code checklist, then read it.

    ```bash
    python3 -m tools.gate_trials.fork --target OWNER/TEST-REPO --fork FORK-OWNER/TEST-REPO
    ```

11. **Prepare the enforcement trial.** Follow the exact
    [branch-rule checklist](../tools/gate_trials/README.md#branch-enforcement-checklist-sean-only).
    Use a non-bypass account to observe blocked merges. The public reader cannot prove settings.

    ```bash
    python3 -m tools.gate_trials.branch_enforcement --target OWNER/TEST-REPO
    ```

12. **Save the evidence lines.** Keep PR URLs, capture/judge URLs, both check URLs and reader
    output, plus the observed blocked-merge/settings evidence. `PASS historical-accept` and
    `PASS identity-refusal` only identify the two older records; neither fills a new trial.
    FAIL exits 1, including incomplete evidence. Keep #254 open for any trial still unproved.
