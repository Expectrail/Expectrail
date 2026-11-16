# Expectrail hosted trial kit (#254)

Start with the [one-page guide](../../docs/gate-trials.md). Every preparer has the same options:
`--target OWNER/REPO`, optional `--repository PATH`, optional new `--out PATH`. The fork preparer
also requires `--fork OWNER/REPO`. `python3 -m tools.gate_trials prepare KIND ...` is equivalent
to the individual `correct_fix`, `wrong_fix`, `new_head`, `tamper`, `fork` and `branch_enforcement`
modules. `--help` lists options. Neither path pushes or calls GitHub.

Preparation resolves **local `origin/main`**, applies the public patches with an alternate Git
index and uses `commit-tree`/transactional `update-ref`. It never checks out or writes the game,
changes the normal index, reads a credential, fetches, pushes or runs hooks. Refs are under
`expectrail-trials/SOURCE12/`. Existing different refs and existing output folders are refused.
A fresh `--out` may reuse matching deterministic refs. `plan.json`, `pr-body.txt` and `steps.txt`
are local instructions, not a verification verdict. The patches make exactly the same changes as the public
fall-through seed and existing collision-mask/comment-only fix fixtures; blank context lines are
trimmed so the nested patch files pass whitespace checks. No spec is edited.

All trials share a seeded base derived from one main revision. Correct/fork/new-head/tamper heads
undo the seed. Wrong/enforcement heads change a comment while leaving the bug present. The
new-head successor adds only `gate-trial-next-head.txt`, outside the game, and is prepared on a
separate `-next` ref. Its push command advances the original trial branch without force. The
initial push must not include that successor. Push commands use explicit target URLs, never an
ambiguous `origin`; Expectrail's own repository is refused as a target.

## One-time setup (Sean only)

Use an **existing disposable public repository**. This kit does not create a repository or install
an App, configure secrets, edit workflows or change settings. If these prerequisites are absent,
the trial is blocked until Sean prepares them; a green wrapper job does not satisfy the trial.

1. The test repository needs the existing `.github/workflows/expectrail-verify.yml`,
   `expectrail-capture.yml` and `expectrail-comment.yml`, plus the base Expectrail code, routes,
   approved checks and public recording bank. Preparing/pushing the seeded base copies main's
   existing tree; installing the kit on main first makes its helper available to a later trusted
   rehearsal. Leave the caller/capture files identical between base, synthetic merge and head.
2. The dedicated **Expectrail Checks** App must already be installed on this test repository with
   Checks read/write (App ID `5755185`, slug `expectrail-checks`). The prior audit only established
   installation on Expectrail's repository. Its existing App ID variable and private-key secret
   must already be available to the trusted `main-only` environment as the workflow expects.
   Do not give a model key or any secret to the candidate. This kit neither requests nor reads values.
3. After pushing the printed base ref, Settings → General → Default branch: select that exact
   `expectrail-trials/SOURCE12/base` branch. This is required: capture and publisher refuse PRs to
   other branches. In Settings → Environments → `main-only` → Deployment branches and tags,
   select that exact default branch. Do not relax the source repository's policy.
4. Open every trial **into that default branch**. Copy the supplied description, including
   `Expectrail-Intent: fix`; capture then plays three independent runs per side, per route.
   The base supplies all checks/routes/recordings. Existing recordings include the public seed,
   repair and combat; a renderer/frame mismatch still requires review. There is no live fallback.
5. For forks, use an existing fork of this disposable repository. The fork head branch is pushed
   to the fork URL; the base branch goes to the parent test repository. Confirm in the actual
   run that the candidate has only `contents: read`, no secrets/environment, base harness code
   and `persist-credentials: false`. The publisher must load `${{ github.workflow_sha }}` from
   the parent default branch and evaluate from `policy`, its pinned base checkout. `head-data`
   is input only. Save both job URLs and the effective permissions shown by GitHub. Reader PASS
   checks the published fork statement, repair and base binding; it is not a secret-flow audit.

## Expected public results

| Trial | Expectrail evidence | Expectrail clearance | Reason/evidence required |
| --- | --- | --- | --- |
| correct fix | success | success, summary `accept` | Head-bound trusted comment: `player-stays-above-ground` repair demonstrated, failed before 3/3 and passes after 3/3 |
| wrong fix | success | failure, summary `reject` | Comment finding names `player-stays-above-ground`, after `fail`, and nonempty reason; a missing model answer alone is not this proof |
| new head | success on old pair, if finalized | failure on old pair | `Superseded capture or pull request`, or `GitHub did not bind the capture workflow to the current merge commit`; old capture never clears the new SHA; public timing proves first capture, second-head capture, then old refusal in that order |
| tamper, actual injected downloaded copy | success | failure | `EVIDENCE_MISMATCH` in both head check and bound bot comment |
| fork | success | success, summary `accept` | Different head repository; same demonstrated repair/base binding; trusted comment says `A fork's pull request gets no secrets`; additionally inspect both job boundaries |
| enforcement | success for evidence of wrong fix | failure for wrong fix | Check the settings and observe blocked non-bypass merges; public checks/comment alone cannot prove enforcement |

## New-head timing (Sean only)

The ordinary fast path is: wait until the first **Expectrail verify** capture is complete, then
paste the third printed push command. Record the two run timestamps. There are three outcomes:

- If the old trusted job already accepted before the push, the run did **not** exercise stale
  judgment. Its success stays on the old SHA. The new SHA needs its own capture; repeat the trial.
- If the completed-event judge starts after the push, `comment.find_pull_request` finds no open
  PR at the old head and `ci_checks.main('start')` returns. There may be no old failure check or
  stale reason text. That skip is safe, but missing output alone is not recorded stale proof.
- If the push happens after identity binding and before finish, `ci_checks.current` fails and
  `finish` writes `Expectrail clearance=failure`, `Superseded capture or pull request` on the
  old head. The new head has a distinct check/capture identity. This is the repeatable target.

For a deterministic window, **Sean must separately review a test-only change** to the disposable
repository's trusted `expectrail-comment.yml`, on its default branch. Immediately after the
`Start the checks and identify the base` step, add a step conditional on
`steps.start.outputs.base != ''` whose only command is `sleep 90`. This belongs to the trusted
job, after state creation; an environment hold before the job starts does not establish this
window. Leave caller/capture workflows unchanged. Open the trial PR, wait for capture completion
and that hold step to start in the **completed-event** judge, then run the second-head push.
After the run, save both check URLs, timing and the held trusted workflow revision; remove the
test-only delay through Sean's normal review path. No such workflow edit or run is made by this kit.
If Sean cannot arrange that window, report FAIL/incomplete rather than credit a timed-out job.
To repeat on the same frozen main, first close the old trial PR and delete **only its disposable
head branch** using GitHub's PR page (keep the seeded base). Run the same preparer with a fresh
`--out work/gate-trials/new-head-retry` folder. Matching local refs are reused; the printed pushes
re-create the initial remote head, without force. Open a new PR and retain the old run URLs.
A new output folder alone does not reset an already advanced remote branch.

## Tamper boundary and rehearsal

There is **no PR-only step that edits an already uploaded artifact between the jobs** in this
workflow. The candidate has read-only repository permissions, no publisher secret, and uploads
through pinned upload-artifact v7 (immutable artifacts). The trusted publisher validates the
caller/reusable workflow blobs against base and current merge; changing them on a PR yields
`candidate workflow differs from the trusted base` or an earlier identity refusal. It selects
one artifact from the exact run/attempt, bounds its size, and checks its GitHub SHA-256 before
opening it. The judge then checks the manifest and every trace/frame digest.

Evidence for that boundary: `HeadChecksTest.test_only_dedicated_publisher_can_publish_clearance`,
`test_caller_and_reusable_workflow_must_match_the_base_and_test_merge`,
`test_download_checks_the_attempt_digest_and_size_and_keeps_token_on_github`,
`SplitGateTest.test_bundle_edits_fail_before_the_observer` in `tests/test_ci_gate.py`, and the new
`TamperTest` tests. The workflows' current content is asserted by a test; none is changed here.
This does not authenticate what the game itself drew/wrote **before upload** (#246/#273).

For a local ZIP downloaded by Sean, preserve the original and run:

```bash
python3 -m tools.gate_trials.tamper --capture capture.zip --out altered.zip
```

This appends one space to a trace without updating its manifest; it extracts no members.
The actual judge refuses that copy as `EVIDENCE_MISMATCH` before any visual observer call.
**Local rehearsal is not a hosted substitution trial.** Normal tamper-control PRs still accept.

If Sean wants a person-controlled hosted reader trial, separately review a change to the test
repository's **trusted** workflow, immediately **after** `Fetch the published capture and verify
its digest`, before `Evaluate the saved runs from the base commit`. Once the kit exists on the
trusted default branch, the injected step's exact commands are:

```bash
python3 -m tools.gate_trials.tamper --capture "$RUNNER_TEMP/capture.zip" --out "$RUNNER_TEMP/altered-capture.zip"
mv -- "$RUNNER_TEMP/altered-capture.zip" "$RUNNER_TEMP/capture.zip"
```

Condition that step on `steps.start.outputs.base != ''`. Use the prepared tamper PR. Expect the
mismatch check/comment above, save the trusted workflow revision and both run/check URLs, then
remove the instrumentation through review. This tests substituted **downloaded bytes inside the
hosted trusted job**. It does not show that a PR can mutate GitHub's immutable stored artifact;
transport substitution itself needs control outside the PR. This kit makes neither change.

## Branch enforcement checklist (Sean only)

On the disposable repository, after the App has published its first checks:

- [ ] Settings → Branches → Add classic branch protection rule. Branch name pattern: the exact
  printed `expectrail-trials/SOURCE12/base` default branch. Confirm the rule is active on it.
- [ ] Enable **Require a pull request before merging**.
- [ ] Enable **Require status checks to pass before merging**, and **Require branches to be up
  to date before merging**.
- [ ] Select **Expectrail clearance** with expected source **Expectrail Checks** (App ID `5755185`,
  slug `expectrail-checks`). A same-named Actions job must not satisfy it. Require only clearance
  for this gate; evidence deliberately succeeds even for a reject.
- [ ] Enable **Do not allow bypassing the above settings**. Do not add bypass actors. A repository
  plan/ruleset that cannot enforce these settings is a blocker, not a successful trial.
- [ ] Use an account without bypass rights. On the wrong-fix PR, attempt the normal Merge action:
  it must be blocked by failed clearance. Save the PR URL and the visible refusal.
- [ ] Also observe a missing/pending clearance on a fresh second head: an old SHA's green check
  must not permit merging it. If a needs-review result occurs, it must be blocked too.
- [ ] Confirm a correctly cleared current head is eligible under the same rule. Save the rule's
  target, expected App source, effective bypass policy and observed results. Do not infer this
  from check color. Nothing here changes Expectrail's own advisory clearance policy.

The unauthenticated public API does not prove effective rule/bypass settings or an attempted
blocked merge. `read` reports enforcement as FAIL/manual evidence remaining, even when its
wrong-fix checks match. Sean keeps those observations separately; a PR comment is not proof of
settings. The same limitation applies if branch protection is unavailable on the account plan.

## Reader, fixtures and limits

```bash
python3 -m tools.gate_trials read --repo OWNER/REPO --pr NUMBER
python3 -m tools.gate_trials read --pr 514 --fixture tests/fixtures/gate_trials/hosted-accept.json
python3 -m tools.gate_trials read --pr 514 --fixture tests/fixtures/gate_trials/hosted-identity.json
```

Only unauthenticated HTTPS GETs to `api.github.com` are used; environment tokens are ignored and
redirects refused. No artifact is downloaded. The reader takes PR metadata, check runs (all
attempts/pages), and the bounded bot comment; new-head trials also read public capture-run timing.
It matches the trial marker/branch, full head, dedicated publisher App and latest complete
run/attempt pair. Incomplete latest checks or disagreeing pair summaries never reuse an older success. Commentary must name
the same head and base; same-named comments by other users are ignored. Duplicate declarations,
ambiguous/missing pairs, rate limits, malformed/oversized responses and pagination beyond 1,000
items are FAIL. Exit 0 is PASS for the stated **public observation**, 1 is FAIL (including missing
proof). An ordinary green PR is never silently classified as a seeded repair.

The two historical fixtures contain public response objects fetched on November 16, 2026:
PR #514's generic accept (`43768258238/1`) and its older identity refusal (`43766433329/1`). Their
source sidecars list immutable check/run URLs. The single bot comment was later updated; its
old refusal text is unavailable, so the older fixture retains today's accept comment as context
and proves only the identity refusal from its App checks. It does not fabricate an old comment.
`--head FULL_SHA` can inspect a historical check pair but cannot stand in for current-head trial
proof. `--app-id` supports a separately known expected publisher App ID (not its installation ID); it is never inferred
from an arbitrary passing check. These are observations of the publisher, not signed evidence
or proof of secret absence. #254 remains open until Sean records the missing hosted cases.
