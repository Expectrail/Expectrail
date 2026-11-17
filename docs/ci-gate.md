# The CI gate: Expectrail on a game repository's pull requests

## Require Expectrail clearance on the protected branch

Install the pull request caller, its reusable capture workflow and the trusted publisher together
on the default branch. The base checkout must contain Expectrail. Configure the same game folder,
spec directory and public route patterns in capture and judge. The workflow paths are part of the
publisher's identity check. A change to either capture workflow requires separate review.

The read-only candidate uses the base harness to replay each game inside Bubblewrap. For a
declared fix it captures three separate runs per side. Only replay records, traces, frames and
the manifest go in the public bundle. The trusted job checks the workflow revision, run attempt,
archive size and GitHub's SHA-256 before opening the bundle. It checks its closed manifest schema,
base policy digest, current PR head, intent and every saved replay. It hashes the game files from
the pinned base and head checkouts. A replay naming a different tree on either side is refused
with `EVIDENCE_MISMATCH`. The head checkout is read as data. The judge runs from the base checkout.
No private routes are used in this workflow.

The two checks are attached to the PR head. **Expectrail evidence** links to the trusted report
or to the run if publication was interrupted. **Expectrail clearance** passes only on accept.
Reject and needs-review fail it. A new head needs its own clearance. An interrupted capture or
judge leaves clearance failed or incomplete.

Install a dedicated GitHub App on this repository with Checks read/write. In the protected
`main-only` environment, set the variable `EXPECTRAIL_CHECKS_APP_ID` and secret
`EXPECTRAIL_CHECKS_PRIVATE_KEY`. Restrict deployments to the default branch. Require only
**Expectrail clearance** and select the dedicated App as its expected source. This prevents a
same-named Actions job satisfying the rule. A person with repository bypass permission can
merge outside that guarantee.

The judge uses engine observations and the configured base-side visual recording. The bundled
clean recording covers the smoke sample. Other frames and questions, including on combat, may
lack recorded answers. A missing answer needs review unless a failure already rejects the change.
A correct-fix trial must use a trusted recording covering the checks exercised. Neither job calls
a paid model.

## Gate command exit codes

`python -m expectrail.gate.verify` returns **0 for accept, 1 for reject and 2 for
needs-review**. A stopped verification still writes `findings.json` and returns 2.
Code **3** means the command refused before verification: for example a nonempty
output folder, invalid PR identity, or an unreadable/mismatched PR event. It must
not overwrite a record or run the game in those cases. Argument-parser errors
use argparse's exit 2 and do not promise a findings record.

With PR identity and `GITHUB_EVENT_PATH`, the command checks that the event names
the same PR and commits before replay. A local test using synthetic PR identities
must supply its own event or clear that variable; inheriting the CI runner's real
PR event tests identity refusal instead of the local verdict's exit code. The
exit mapping has not changed in #588.

## On Expectrail's own repository

Sean decided on November 14, 2026 (option C on #254): on this repository's own pull requests,
**Expectrail clearance** is advisory. It runs and shows green or red on every pull request, but
it is not a required check, and the merge guard records its conclusion without waiting for it.
Our own pull requests stay gated by the full test suite, the required checks and the merge
guard's review. The judge uses recorded vision answers, so a pull request that changes what the
bundled game draws (usually a harness change) has no recorded answer and shows needs-review.
The App is `Expectrail Checks`, installed on this repository only. `EXPECTRAIL_CHECKS_APP_ID` is a
repository variable and `EXPECTRAIL_CHECKS_PRIVATE_KEY` a secret of the `main-only` environment.
For a game studio's repository, require clearance as described above.

## Earlier composite actions

The following installation is for existing callers of the original verify and comment actions.
Those actions do not publish the two head checks described above.

The gate replays a pull request's Godot game on scripted routes, judges the approved test specs on
what the engine recorded, and posts the verdict (accept, reject or needs review) with its evidence
as one pull request comment. The comment is updated on every push, and each finding keeps its id
from push to push. It is the G04 package in [discovery.md](discovery.md#whats-next): evidence in the
pull request, posted from a separate trusted step.

It comes as two composite actions in this repository:

- [`.github/actions/expectrail-verify`](../.github/actions/expectrail-verify/action.yml) runs the
  pull request's game. It is the untrusted half.
- [`.github/actions/expectrail-comment`](../.github/actions/expectrail-comment/action.yml) posts the
  comment from a `workflow_run` job that never runs the pull request's code. It is the trusted half.

They live under `.github/actions/` rather than as one `action.yml` at the repository root because
the two halves need different trust and different permissions, and a root action would be a single
entry point for both. The repository root stays the project. Both actions come from the same commit,
so one pinned SHA covers both.

## Add it to a game repository

You need a Godot project that runs in Godot 4.7.2 (the version the harness pins), at least one route
(`expectrail.route/v0`, see [contracts.md](contracts.md)) and at least one approved test spec
(`expectrail.test-spec/v0` with an `approval`). The harness adds its autoload to a copy of the
project.

An approval binds to the spec's content (#420). `python3 -m expectrail.spec_writer approve SPEC --by
NAME` writes `approval.specSha256`, the SHA-256 of the spec's canonical JSON without its approval
(keys sorted, separators `,` and `:`, UTF-8). If the spec is edited afterwards, the digest no longer
matches: the gate counts the spec with the drafts, never lets it judge, and says in the record's
reasons and the comment that a person must approve it again. If it was the only spec, nothing is
accepted. Whitespace and key order do not change the digest. An approval written before this has no
digest: it still counts, and the record and the comment name it "approved before content binding"
until someone approves it again. The merge guard asks for a person when a pull request edits an
approved spec without a new approval bound to the new content. A route presses the game's own input actions on exact physics ticks, and the position log
follows the node named `Player`. Add two workflow files. Replace `COMMIT_SHA` with the full SHA of an Expectrail commit on
`main` that contains `.github/actions/` (for example from
`git ls-remote https://github.com/Expectrail/Expectrail refs/heads/main`). Pin both files to the same
SHA, as you would pin any third-party action.

`.github/workflows/expectrail-verify.yml`, the untrusted job:

```yaml
name: Expectrail verify
on: pull_request
permissions:
  contents: read
jobs:
  verify:
    runs-on: ubuntu-24.04
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: Expectrail/Expectrail/.github/actions/expectrail-verify@COMMIT_SHA
        with:
          game-path: game              # the folder holding project.godot ("." for the root)
          routes: tests/routes/*.json  # one path or glob per line
          specs: tests/specs
```

`.github/workflows/expectrail-comment.yml`, the trusted job:

```yaml
name: Expectrail comment
on:
  workflow_run:
    workflows: [Expectrail verify]
    types: [completed]
permissions: {}
jobs:
  comment:
    if: >-
      github.event.workflow_run.event == 'pull_request' &&
      github.event.workflow_run.path == '.github/workflows/expectrail-verify.yml' &&
      github.event.workflow_run.conclusion != 'cancelled'
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    permissions:
      actions: read
      contents: read
      pull-requests: write
    steps:
      - uses: Expectrail/Expectrail/.github/actions/expectrail-comment@COMMIT_SHA
```

The comment workflow takes effect once it is on your default branch: GitHub runs `workflow_run`
workflows only from the default branch's copy. Until then the verify job runs and uploads its
evidence, and no comment appears.

This repository runs the same pair on its own pull requests:
[`expectrail-verify.yml`](../.github/workflows/expectrail-verify.yml) (the platformer, the smoke and
combat routes, `agents/specs`) and [`expectrail-comment.yml`](../.github/workflows/expectrail-comment.yml).
Both use the actions from the checked-out repository (`./.github/actions/...`) instead of a pinned SHA.

### Inputs

| Action | Input | Default | What it does |
| --- | --- | --- | --- |
| verify | `game-path` | required | The Godot project folder, relative to the repository root |
| verify | `routes` | required | Route files, one path or pattern per line ([how a pattern is read](#route-patterns)) |
| verify | `specs` | required | The folder of test specs; only specs with an `approval` judge a change |
| verify | `compare-base` | `true` | Also replay the pull request's base commit, and read the specs and routes from it |
| verify | `heldout-repository` | empty | `owner/name` of a private repository of held-out routes (a `manifest.json` listing `routes[].file`) |
| verify | `heldout-ref` | empty | Its branch, tag or commit |
| verify | `heldout-token` | empty | A token that can read it; see "Held-out routes" below before passing one |
| verify | `fail-on` | `reject` | Fail the job on `reject`, on `needs-review` (or reject), or `never` |
| verify | `require-sandbox` | `false` | `true` refuses to replay the game outside the replay sandbox ([replay-sandbox.md](replay-sandbox.md)): where the runner cannot provide it nothing is replayed and the decision is needs-review. To let the sandbox start, `true` also sets `kernel.apparmor_restrict_unprivileged_userns=0` on the runner (Ubuntu 24.04 ships it on); on a hosted runner that ends with the job, on a self-hosted runner it stays until reboot. `false` changes no setting and sandboxes the game only where the runner already allows it; the record and the comment say how many replays were |
| verify | `artifact-name` | `expectrail-gate` | The evidence artifact's name |
| verify | `generated-checks` | empty | An advisory block of checks generated for this change ([jit.md](jit.md)), shown in the comment and the review page; it never changes the decision, and one that cannot be read shows as "no generated checks" |
| verify | `intent` | `from-pull-request` | What the change is for: `fix`, `change` or `none`, or `from-pull-request`, which reads closing-keyword links, a label `intent:...` or a description line `Expectrail-Intent: ...` from the event ([a change declared a fix](#a-change-declared-a-fix)); on any other event it is `none`. With PR identity and the event available, a stricter PR declaration overrides an explicit `none` or `change` |
| comment | `github-token` | the run's token | Reads the verify run's artifact and writes the comment |
| comment | `artifact-name` | `expectrail-gate` | Must match the verify action's |
| comment | `watch` | empty | More paths the verdict depends on, one per line (end a folder with `/`); the comment warns when the pull request changes one |
| comment | `bot-login` | `github-actions[bot]` | The only author whose comment is ever updated |

The gate takes its engine from the adapter registry ([harness.md](harness.md), "Adapters"):
`run_gate(adapter=...)` asks the adapter for the replay, for the file that marks a project folder, for
the folders left out of the game's digest and for the capture rate, and names no engine itself. The
record's `adapter` is that adapter's name. `godot` is the default and the only adapter with a verify
path today, so the gate still supports Godot only; a name the registry does not hold, or an adapter
with no verify path, stops the gate before anything is replayed. The verify action has no `adapter`
input yet. The gate reads the engine's record as a position log of the player and the ground line
(`expectrail.trace/v0`), so an engine's harness has to write that log to be judged by it.

## What the gate decides

The verify job checks out the pull request's merge commit. With `compare-base: true` (the default), it
also checks out the base commit. It then does this:

1. Reads the specs and routes **from the base commit**, so a pull request cannot weaken the checks that
   judge it. Spec and route files the pull request edits are counted in the comment. They judge
   changes once the pull request merges. Without a base (a push, or `compare-base: false`), the head's
   own checks are used, and the comment says so.
2. Replays every route on the head and on the base through the Godot harness ([harness.md](harness.md)).
3. Judges every approved spec on every route with the evaluator, on the engine's position log. Each
   check gets the review's comparison words ([review.md](review.md)): `REPAIRED`, `PRESERVED`,
   `REGRESSION`, `UNRESOLVED` or `INCONCLUSIVE`.
4. Replays the held-out routes on the head, if configured, and keeps counts only.
5. Decides. **Accept** only when at least one check ran and every public and held-out check passes
   (and, for a change declared a fix, a check demonstrated the repair: see below).
   **Reject** when any check fails after the change. **Needs review** otherwise: a check that could not
   be decided, a replay that did not finish, held-out routes that could not be read, a spec or route
   file the gate could not use, or no checks at all. Accepted means this change passed these checks
   on these routes, not that the game is correct.

   A spec or route file the gate could not use is one it refused (a link, a file over the size cap),
   one that is not valid, an id or a route name used by two files, or more files than its limits.
   Each is named in the reasons and counted in the record's `checkProblems`. The checks that ran
   are then not all of the project's checks, so their passing is needs review and never accept.
   (Until November 12, 2026 it was an accept with the problem added to the reasons, which the
   comment does not show on an accept.) A draft spec is not a problem: it is counted in `drafts`.

### A change declared a fix

Added November 12, 2026 (issue #284). "No check failed" is not "the fix is good" when no check
touches the bug: on blind set 3 the gate accepted eight wrong fixes that way. So a change can be
declared, and a fix is held to more:

    python3 -m expectrail.gate.verify ... --intent fix        # or change, or none (the default)

- **`fix`**: the change says it fixes a reported bug. Accept also needs **the repair
  demonstrated**: at least one check that failed on the base and passes on the head, on the same
  route. One failure on the base could be a flaky check, so each such check's route is replayed
  twice more on each side, and the check counts only when it fails on the base three times of three
  and passes on the head three times of three. With no check that counts the decision is needs
  review, its first reason starts `repair-not-demonstrated:` (also when no check ran or the run
  stopped; until November 13, 2026 "no checks ran" or the stop reason came first in those two
  cases), and the comment and the review page
  lead with "No check reproduced the reported bug, so this fix is not verified", then how to get a
  check. When a check did fail on the base but has no pass or fail on the head (it needs review, for
  example with no vision key, or its replay did not finish), the reason says so: "N check(s) failed
  before the change but could not be decided after the change", and the comment, the review page and
  `expectrail verify` lead with "A check failed before the change, but its result after the change
  could not be decided, so this fix is not verified" (#560). The decision is the same needs-review.
  A check that still fails after the change rejects, as always.
- **`change`** (an intended change of behaviour) and **`none`** are judged by the rule above,
  unchanged, and nothing is replayed again.
- Declaring `fix` can only take an accept away. Anything typed that is not one of the three stops
  the run as needs review and is recorded as `fix`.

The record carries `intent`, and for a fix a `repair` block: one row for every check that claims a
repair, with its result on each of the three runs a side and whether it counts. A reader
recomputes which rows count and holds the decision to them, so a record cannot call a repair
demonstrated that its own runs do not show. A record from before the field reads as `none`.

**On a pull request** (added November 13, 2026) the intent is read from the pull request itself:

- a closing-keyword link such as `Fixes #284`, `Closes #284` or `Resolves #284`, in any case; or
- a label `intent:fix`, `intent:change` or `intent:none`, or
- a line of the description that starts `Expectrail-Intent:` followed by `fix`, `change` or `none`
  and nothing else, for example `Expectrail-Intent: fix`.

Nothing declared is `none`. With several declarations the strictest wins (`fix`, then `change`,
then `none`), and a value that is not one of the three (`intent:bugfix`, `Expectrail-Intent: maybe`)
is a fix. So adding a label or a line can only move a change towards the stricter path, never away
from it (`python3 -m expectrail.gate.intent`).

Every closing-keyword link is read as `fix`, including links to issues about features or code,
cross-repository references and quoted examples. This conservative choice needs no issue-label API
lookup or new permission. Plain `Part of #284` and `See #284` are not closing declarations. Neither
`intent:none` nor `Expectrail-Intent: none` can cancel a closing link. Findings and CI bundles keep
the matched phrase and its 1-based PR-body line in `pullRequest.fixLinks`; reports and comments show
that source. A changed source line invalidates the captured metadata even if intent stays `fix`.
See the [case audit and measured counts](linked-bug-fix.md).

Both halves read it. The verify action's `intent` input defaults to `from-pull-request`: it reads the
declaration from the `pull_request` event file and passes it to the gate (an event file that cannot
be read is a fix). That half runs the pull request's own copy of the action, so a pull request could
edit it to declare `none`; the trusted comment job therefore reads the declaration again from the
pull request it fetched itself, and when the pull request declares a fix and the record was judged
as anything else, the comment says the evidence could not be used, instead of showing the verdict.
A reject is still shown (the fix rule never changes one), and so is a record judged more strictly
than declared. The comment job needs no new permission for this: the pull request it already reads
carries its labels and description. "Expectrail verify" also runs on `labeled`, `unlabeled` and
`edited`, so a declaration added after a push is judged by a new run.

**Measured on the known-bugs bench** (added November 13, 2026):
[`bench/jit/known/gate.md`](../bench/jit/known/gate.md) is the gate on the four reported bugs, each
with a wrong fix (a comment only) and the correct fix (the exact undo), judged with no stated intent
and declared a fix, on the gate's own routes and approved specs, the engine's record only
(`python3 -m expectrail.gate.known_bench run`; `show` checks the stored record and prints it). The
reader recomputes the totals from the rows and refuses a record where a declared fix is accepted
without a demonstrated repair.

What this does not do yet:

- **Links are not classified by issue labels.** Every closing-keyword reference is a fix. A future
  distinction would need an issue lookup and Sean's permission review; an optional
  [permission proposal](proposals/284-issue-labels.yml.txt) is provided, not installed.
- **Only approved checks can demonstrate a repair.** A generated check cannot count yet (#271), so
  for most reported bugs today the honest answer is needs review.
- The three runs are three replays of the same route on the same machine. That shows the check is
  not flaky there; it does not show the check is about the reported bug. A check that fails before
  and passes after for another reason would count.

A finding is a check that does not pass after the change. Its id is the first 12 hex digits of
`sha256(spec + "\n" + route + "\n" + kind)`, where kind is `fail`, `needs-review` or `replay-error`.
Nothing that changes between pushes goes into it (no commit, frame, reason or time), so the same
failure keeps its id. To reproduce one:
`printf '%s\n%s\n%s' player-stays-above-ground smoke fail | sha256sum | cut -c1-12`. The comment lists
the ids that are new and resolved since its last update.

## Two observers, one rule

Expectrail verifies by observing, and the full verdict has two observers on every check (Sean's
decision of November 12, 2026, #327): the engine's record, which is exact about positions, and a
visual observer, a vision model over the frames the replay captured, which sees what was drawn.
`expectrail.gate.record.combine` joins what the two said about a check:

| The engine's record | The visual observer | The check |
| --- | --- | --- |
| pass | pass | pass |
| fail | anything | fail |
| anything | fail | fail |
| pass | could not decide, gave no answer, or was not asked | needs review |
| needs review | pass | needs review |

So a pass needs both, a failure on either rejects, and nothing is accepted on the engine's record
alone. With no visual observer a seeded bug is still rejected and nothing is accepted; the reasons
say why. The visual observer is not asked about a check the engine's record already fails, since its
answer could not change the result.

**A pass has to cover the check.** Under `both` the gate counts the frames of the spec's window that
the replay should have, from the route's ticks (the gate's own input) and the tick rate the trace
states, never from what an observer returned. Then:

- The engine's record passes only when its log holds every tick of the route and its observations
  every frame of the window. A log that stops early is needs review ("the engine's record has 20 of
  240 ticks of the route").
- The visual observer's pass counts only when the replay captured every frame of the window and the
  observer's answer holds every one ("the replay captured 5 of 120 frames of the check's window",
  "the visual observer saw 4 of 120 frames of the check's window"). One exception: an assertion that
  passes on the frame that shows it (`reaches`) needs the whole capture but not the whole answer.
- An answer whose `replay.sha256` is not this replay's is no answer.
- When the gate cannot tell how many frames the route should have, nothing passes.

A failure seen in part of the window is still a failure; only a pass has to cover it. The rule
`engine-only` is not changed by this: there a log that stops early still passes on the rows it has,
as on main (#357).

**Held-out frames stay in unless a person says otherwise.** A visual observer over frames sends them
to the model's provider. Under `both` the held-out routes are replayed without frames and the visual
observer is not asked about them, so a failure on the engine's record still counts and no held-out
check passes; the reasons say so. `run_gate(heldout_frames_to_visual=True)` sends them (and keeps no
answer cache). Nothing passes that flag, and whether anything may is Sean's decision.

`run_gate` takes the rule (`rule="both"`, with `visual=` an `expectrail.observers.FramesObserver`), and
so does the orchestrator's engine (`GodotGate(rule="both", visual=...)`). The record then has
`observers` (the rule, and the visual observer's name, provider and model), and every row has
`observed`: what each observer said before and after, and the SHA256 of the visual observer's answer.
That answer, an observations document, is in the artifact at
`observations/<head or base>/<route>/<spec>.visual.json`, with its verdict at
`verdicts/.../<spec>.visual.json`, so the verdict can be read again without asking the model. The
reader recomputes every row from `observed`: a record whose row passes without the visual observer's
pass is refused. It does not check the answer behind that word: the digest is checked for its shape
only, and nothing reads `observations/.../*.visual.json` back against it or counts its frames again.
For the earlier composite actions (`expectrail.gate.verify.visual_gap` is the same question,
callable on a stored answer), "two observers on every check" rests on the record's word. Held-out
routes are judged by the same rule (see above for their frames). `contracts/examples/findings-both-observers.json` is such a record; it was made with
the tests' stand-in replay and stand-in model, not by a live run.

What is and is not in use, as of November 13, 2026:

- The orchestrator (`verify`, `sample`, and the app through verify) constructs a `FramesObserver`
  and uses `both`. Its findings record and job status carry the `observers` block; `report` says
  which observers judged in plain words.
- The earlier verify action uses `engine-only`. The two-job gate above uses `both`.
- No live model was asked to test this change. Tests use scripted SAM 3.1 wire-format answers.
- Decision B (#327) remains: an anchored-box difference needs review, never a reject. #373 is
  still open at the start of this work; this change does not implement or alter that check.

Verification (`expectrail verify`, `expectrail sample`, and the app through verify) needs
`MODEL_API_KEY` and `EXPECTRAIL_SAM_USD_CAP` in the verifier's environment. It judges with both the
engine's record and a `FramesObserver`; an accept needs both. Without either setting, nothing is
sent to the model, but the game still replays and its engine checks run. An engine failure
**rejects**; otherwise the result is **needs-review**. A `PROVIDER_FAILED` diagnostic names each
missing setting and its fix. There is no command option for an engine-only accept. `expectrail doctor` checks both settings
without printing the key, and `expectrail report` names the observers that judged.

Cost depends on frames, checks and cached answers. [The recorded costs in sam.md](sam.md)
describe **up to $0.60 for both prompts over one 120-frame run**, at $2.50 per 1,000 images.
More routes or checks add work; cached answers reduce it. This is not a price guarantee for another project. The spend cap is
the most one run may send, in US dollars; reaching it gives no answer, never an accept on silence.

The replay's environment excludes the model key, including the sandbox's final allowlist.
The monthly aggregate limit remains separate work (#267).

### The player's place on both sides

Under `both` with a base, the gate also asks the visual observer's model what is drawn inside the
player's own collision box (the trace's `body`, [harness.md](harness.md), widened by 4 game px) in
every tenth captured frame of each route and its last, on the base and on the head
(`expectrail/gate/anchor.py`). Each head frame is compared with the same base frame where the engine
has the player in the same place: a width, height, or reach above or below more than 6 game px apart,
the box no longer holding the player's point, or the model's confidence falling by more than 0.1 is a
difference.

By Sean's decision B on #327 (November 12, 2026):

| What the frames show | What it does to the decision |
| --- | --- |
| A difference in any compared frame | An accept becomes needs-review; the differing frames are kept as `anchor/<route>/base-NNNNNN.png` and `head-NNNNNN.png` |
| A frame asked about with no answer, or asking that stopped | An accept becomes needs-review |
| All compared frames agree | Nothing |
| Nothing compared (the engine moved the player, no body box logged, nothing asked) | Nothing |

It never rejects and never makes anything an accept: an accept still needs every check to pass on
both observers. It rejects only once blind test 4 has given it a false-alarm rate. The record's
`anchor` block says what was asked and found, and the reader recomputes the decision from it. Each
frame asked about is a paid image: 26 for one of the bundled game's 120-frame routes.

What it rests on: two live runs on the bundled game (docs/sam.md: no false alarm in 26 harmless
pairs; sinking v2 and both layering bugs differ), and stand-ins in `tests/test_anchor_gate.py`. The
review page does not show the kept frames yet; they are in the artifact.

The evidence artifact holds `findings.json` (the record, [`contracts/findings.schema.json`](../contracts/findings.schema.json)),
`verdicts/head/<route>/<spec>.json` and `verdicts/base/...` (the evaluator's verdicts), and
`review/index.html`. The review page opens from disk with no scripts. It shows every check, and for
each finding the first failing frame before and after the change, each with its SHA256. The comment
links the run that holds the artifact, [review.md](review.md) for how to read the comparisons, and this
page.

## How it is kept safe

GitHub's guidance is to run untrusted pull request code only where no secret and no write token can
be reached, and to treat anything that code produces as untrusted data
([Securely using pull_request_target](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target);
GitHub Security Lab,
[Preventing pwn requests](https://securitylab.github.com/research/github-actions-preventing-pwn-requests)).
The gate follows that split.

**The verify job is untrusted.** It runs on `pull_request`, with `contents: read` and no secret
except, optionally, the held-out token. It runs the pull request's game, so it is treated as
compromised by design:

- The action refuses `pull_request_target`, `workflow_run` and `issue_comment`, where it would run the
  pull request's code next to a write token.
- Every input reaches a script through `env`, never by `${{ }}` expansion inside a script.
- Godot gets only the display and rendering variables from the environment (`harness.run.game_env`).
- Python runs from the action's own folder, so a file in the pull request cannot stand in for an
  Expectrail module.
- Before upload, the evidence goes through the repository's export scan (`agents/export_scan.py`):
  key-like strings and, with the held-out set, its route names and lines. A finding stops the upload.

**The comment job is trusted.** It runs on `workflow_run`, from the default branch's copy of its
workflow file, with `actions: read`, `contents: read` and `pull-requests: write`, and nothing else:

- The legacy comment action does not check out or run pull request code. In the two-job workflow
  described above, a separate checkout of the head serves only as input to the game digest.
  `tests/test_ci_gate.py` checks the pinned revisions, working directories and commands.
- It installs nothing. The code is [`expectrail/gate/comment.py`](../expectrail/gate/comment.py) and
  [`expectrail/gate/record.py`](../expectrail/gate/record.py), standard library only (a test parses
  their imports). It runs as `python3 -I`, so `PYTHONPATH`, user site-packages and the current
  directory are ignored, and only the pinned commit's files can be imported.
- The artifact is downloaded into the runner's temp folder and read as data. Only `findings.json` is
  opened. It must be a regular file (not a symlink), at most 4 MiB, UTF-8, and JSON with no duplicate
  keys, NaN or Infinity, nested at most 32 deep. It is checked against the closed schema by a small
  validator that refuses any schema keyword it does not implement. A test holds that validator equal
  to `jsonschema` on the example and on mutated records. Then every derived value is recomputed: each
  finding id from its spec, route and kind, each comparison, the counts and the decision. A record
  that fails any of this is not shown. The comment says the evidence could not be used, so an older
  verdict does not stand.
- The pull request is found from the event (the run's head repository, branch and commit), not from
  the artifact. A fork's run carries no pull request list. A record that names another pull request
  or commit is refused. If the pull request's head has moved on, nothing is posted, because the newer
  run will post.
- Every string from the record is escaped before it goes into Markdown. Newlines and control,
  zero-width and bidirectional characters become spaces. HTML is entity-escaped, and Markdown
  punctuation is backslash-escaped, so a pipe cannot end a table cell. A word joiner follows `@` and
  `#` and breaks `://` and `www.`, so text cannot mention a person, link an issue or become a link.
  Each string is capped at 200 characters, at most 30 findings and 100 checks are listed, and the
  comment stays under 60,000 characters (GitHub's limit is 65,536). Every link is built from the event,
  never from the record.
- There is one comment per pull request. It is found by a hidden marker and by its author (the
  token's bot), so a comment anyone else writes with the same marker is never picked.
- The comment warns when the pull request changes the workflow file that produced the verdict, or a
  path listed in `watch`. It gets those paths from the pull request's file list, through the API.

**Held-out routes leave as counts only.** The record's schema has no field for a held-out route's
name, file, frame or reason. The verify step prints no held-out detail, even when the set cannot be
read. It replays the held-out routes without frames and deletes their run folders. The comment shows
routes and checks passed, failed and needing review. A test runs the gate with a stand-in held-out set
and searches every output file, the log and the comment for its route names.

## Limits

- **The verdict is computed where the pull request's code runs.** A pull request can edit the verify
  workflow: for `pull_request` events GitHub uses the pull request's copy. Code in the game runs as the
  same user as the gate, so it could rewrite files the gate reads before the upload. The comment
  job checks the record's shape, the commit it names and the workflow behind it, and says so when the
  pull request changes that workflow. It cannot prove that the verification itself was not tampered
  with. Use the comment as evidence for a reviewer.
  What the sandbox changes: the action installs bubblewrap and runs the game in the replay sandbox
  ([replay-sandbox.md](replay-sandbox.md)) where the runner allows it: no network, writes only to its
  own copy and one output folder, no view of the checks, the gate's files or its processes. With
  `require-sandbox: 'true'` (when requested by a caller) the game never runs outside it. The
  record's `isolation` block and a line in the comment say how many replays ran inside, and with which
  tool. So the game itself can no longer rewrite what the gate reads. What it does not change: the
  workflow can still be the pull request's copy, and that job writes the record. The two-job gate
  above judges saved replays in the trusted job.
- **What counts as the game.** The record's `headTree` and `baseTree` are taken before anything is
  replayed, over the files a replay's copy holds ([harness.md](harness.md#what-a-game-folder-holds)).
  A link in the game may lead anywhere inside its own checkout and nowhere else: a game with a link
  that leaves it, loops or leads nowhere is not replayed, and the step ends as needs-review (exit 2)
  with the reason. `.git` and `.godot` are never part of the game. The output and work folders may
  not be inside the game folder. A replay whose copy is not the tree the record names (the folder
  changed during the run) is a `replay-error`, not a result.
- **The checks are read once.** The gate reads each spec and route file one time, without following
  a link and up to a size cap (256 KiB a spec, 1 MiB a route), and says so in the reasons when it
  refuses one. Each replay plays a copy of its route written from the bytes that were read, in the
  gate's work folder, so the route a replay plays is the route the record names by its sha256.
  A spec that is a link is counted by its name and never by what it leads to, so `checksChanged`
  does not move when only the file a link leads to changes.
- <a id="route-patterns"></a>**A route pattern finds the same files on every machine.** The gate
  matches patterns itself (`expectrail.gate.verify.pattern_matches`) and does not use Python's
  `Path.glob`, which gives a pattern ending in `**` the files below on Python 3.13 and none on 3.12.
  Between the slashes, `*`, `?` and `[...]` match within one name, and the case of a name counts on
  every file system. `**` alone stands for no folder or any number of them, and as the last part
  for every file below; it never passes through a link to a folder. Any other part may name a link
  to a folder and continue below it. A route is a regular file inside the checkout: a link to a file
  is not a route, and neither is a file reached through a link that leaves the checkout. Neither is
  read, and neither is passed over in silence: each is named in the reasons and listed in the
  digest by its name and the refusal. A folder the gate cannot list is named too: a route named in
  full is still found there (a plain name needs no listing), and when a part with `*`, `?`, `[` or
  `**` needed the listing, the reasons say "cannot list the folder ... while looking for routes".
  Each of these is a problem with the check files, so the result is never accept (see step 5 above).
- **Held-out routes and pull request code share a job.** If you pass `heldout-token`, the pull
  request's code runs in the job that holds the held-out routes. Inside the replay sandbox the game
  sees only the one route it is playing, not the folder; a replay outside the sandbox, and any other
  step of the pull request's workflow, can read them all. Pass it only when the people and agents who
  open pull requests may see the held-out set anyway, and set `require-sandbox: 'true'` with it.
  This repository does not pass it on pull requests (OBAAF-GHA-001). A fork's pull request never gets
  it, because GitHub gives forks no secrets and the action checks the head repository too.
- **On a pull request the position log is the only observer.** No model key is used, so SAM 3.1 does
  not judge, and the comment and the review page say so on every verdict ("Judged on: the engine's
  record only"). That is not the full verdict: see [Two observers](#two-observers-one-rule) below. The
  harness logs the node named `Player`, and the stand-in observations use the platformer demo's player
  size ([sam.md](sam.md), `agents/observations.py`). A spec about any other object needs review. On
  another game, a spec's `tolerancePx` is measured against that size, so its meaning is approximate.
  Giving the verify job a model key would put the key next to the pull request's code.
- **Godot only, one way to replay.** Each route costs one replay on the head and one on the base. The
  smoke route took about 33 seconds in the 2-core container without a GPU that this was built on.
- **Artifacts of a public repository are public.** Everything in the evidence artifact can be
  downloaded by anyone who can see the repository, which is why held-out material never enters it.

## Verifying it after merge

`workflow_run` uses the workflow file on the default branch. So the comment half cannot run from this
pull request, and the end-to-end flow (verify run, artifact, comment) can only be shown after merge.
Before merge, the unit tests cover the record, the ids, the rendering and the YAML. The verify
workflow runs on this pull request itself, and the run's `expectrail-gate` artifact can be inspected.
After merge:

1. Open a pull request with a comment-only change to `expectrail/gate/page.py`. That path starts
   Expectrail verify, and the comment workflow's `watch` list names it.
2. When verify finishes, the Expectrail comment workflow runs from `main`. Expect one comment that
   starts `### Expectrail: accept`, lists the smoke and combat routes as `PRESERVED`, links the run, and
   warns that the pull request changes `expectrail/`, a path the verdict depends on.
3. Push a second commit to the same pull request. The same comment is edited, not duplicated. Its
   footer shows the new commit.
4. From a fork, open the same kind of pull request. Expect a comment from the same workflow, with
   "Held-out routes: not used. A fork's pull request gets no secrets".
5. A finding needs a pull request that breaks the game, and seeded bugs never go into
   `game/platformer` (CONTRIBUTING.md). See one locally instead (below): expect `REGRESSION` on both
   routes, with the same two finding ids on every run.

Locally, with Godot from `./harness/get_godot.sh`:

    python3 -m expectrail.gate.verify --repo HEAD_CHECKOUT --base BASE_CHECKOUT --game game/platformer \
        --routes 'harness/routes/smoke.json harness/routes/combat.json' --specs agents/specs \
        --out runs/gate --pr 1 --head-sha HEAD_SHA --base-sha BASE_SHA

`contracts/examples/findings.json` came from such a run. The base was the clean game at `618ad50`.
The head was the same game with `bugs/physics-fall-through/v1.patch` applied. A stand-in held-out set
was made from two public routes. Its pull request number and head commit are placeholders. The result
was reject: `REGRESSION` on both routes, first failing frame 5, and both held-out checks failed.

## Request a fixture repair on a pull request

Set the repository variable `EXPECTRAIL_CI_AUTOFIX` to `true` to enable fixture repairs.
After **Expectrail clearance** publishes **reject**, someone with write access can add
the `expectrail-autofix` label. The public repository's check must come from the app
identified by `EXPECTRAIL_CHECKS_APP_ID` and match the current head and capture. If
the label also starts a new capture and the clearance is pending, wait for its result
and rerun the fixture repair job. A newer accept or needs-review stops the repair.

The job runs in pull-request context. It checks out the base tools and replays the two
revisions in isolation. Only a reproduced reject starts repair. The patch comes from
the base checkout. Set `EXPECTRAIL_CI_AUTOFIX_FIXTURE` to choose it (default
`agents/fixtures/fix-collision-mask.patch`), and `EXPECTRAIL_CI_AUTOFIX_ATTEMPTS`
for the attempt limit (1–10, default 3). Each candidate gets a fresh isolated verify
using the base's recorded frame answers. A missing answer cannot establish an accept.

Open the job summary for the outcome and instructions. The artifact contains
`repair-run.json` and, only for an accepted repair, its patch. A person reviews and
applies it. This workflow uses no live fixer or model key, including on forks. It
never pushes, comments, opens a pull request or changes the published clearance.

## Trusted CI receipts (#255): proposal and offline checker

The code can write the existing `expectrail.receipt/v1` from a trusted recorded-CI
judgment and check a receipt end to end. **The attesting workflow is a proposal;
no real CI receipt was attested or verified for this change.** Sean installs
[the complete proposed trusted workflow](proposals/255-trusted-receipt.yml.txt)
after the producer/checker reaches the trusted default branch. It leaves the
candidate/capture jobs unchanged. The [new example](../contracts/examples/receipt-ci.v1.json)
is generated by an offline replay/`gh` stand-in test. Its carried key alone grants
no authority; it has no real GitHub attestation.

The producer is `python -m expectrail.gate.ci_receipt write`. It consumes the
existing trusted gate's findings, saved public capture and `ci_checks.start`
state. It binds PR/base/head/intent, captured policy, routes, replay digests and
game trees; it calls the existing receipt signer/reader. It never replays,
observes, proposes, repairs or decides a change. The gate's decision is copied.
Accept with both observers and required, complete sandbox accounting can have
full evidence; other decisions stay partial and cannot clear in trust-check.
The profile is explicitly recorded vision, with no live fallback: model API cost
is $0. The producer requires the gate's `recorded: ...` bank stamp; a live-provider
report is refused even with the CLI flag. This producer does not account for a live observer/fixer profile or GitHub
runner billing. A future live profile needs its own measured spend input.

The fresh Ed25519 key stays in memory; only its public key and signature are
written. The receipt expires after 24 hours. The proposed job's 14-day artifact
retention does not extend that expiry or clear a later head. The signature checks
the canonical body; the GitHub attestation checks the exact receipt file bytes.

### What Sean installs and checks

1. Review the proposal's two added permissions, **only on the trusted judge**:
   `id-token: write` and `attestations: write`. Its top-level permissions remain
   empty. Keep the existing `workflow_run`/PR-path guard, protected `main-only`
   environment, trusted checkout and dedicated App publisher. Fork PRs can trigger
   this parent job; their checkout is data, and their code never runs with its
   credentials. The candidate retains `contents: read`, no environment/secrets and
   no persisted checkout credentials. No new static signing secret is needed.
2. Keep the receipt and predicate after successful trusted judgment, using code
   from `policy`. `--recorded-vision` states the one supported $0 API profile.
   The producer refuses mismatched state/capture/result, missing engine version,
   private-suite results and an existing output; it never overwrites a receipt.
3. Review `actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6`, the public `v4`
   tag read on **2026-11-17**. Its [pinned action inputs](https://github.com/actions/attest/blob/1e69f48acb82d1966a394da916b4c1698aa569d6/action.yml)
   provide `subject-path`, `predicate-type`, `predicate-path`, and output
   `bundle-path`. The subject is only `receipt.json`; the custom type is
   `https://expectrail.tech/attestation/receipt/v1`. Registry push and storage
   records are disabled. Preserve the public Sigstore bundle with the report.
   The added cryptography pin is the existing `requirements-dev.txt` value.
4. Keep receipt/attestation/proof success in `REPORT_READY`. Their failure is
   named `CI_RECEIPT_MISSING` or `CI_ATTESTATION_MISSING`; the proposal preserves an
   earlier error such as `EVIDENCE_MISMATCH`. A failed attesting step cannot leave
   a successful clearance. A successful receipt for reject/needs-review still
   carries that original gate decision.
5. In that same person-reviewed installation, update the **exact** permission
   expectation in `WorkflowSafetyTest.test_the_trusted_workflow_runs_only_on_workflow_run_with_minimal_permissions`
   to the new five-key dictionary shown in the proposal. Keep every candidate
   read-only/no-secret, trusted-checkout, data-only and publisher-source assertion.
   The current test remains unchanged in this patch because the workflow has not
   changed. The new proposal test checks the planned role boundary separately.

Installing the proposal and recording a real receipt remains Sean's action. The
attestation-backed path needs no permanent issuer key. Publishing the first
trusted offline issuer key/store is still the separate human step in
[trust-store.md](trust-store.md).

### Read a real run without trusting its own claims

Use an independently known repository, signing workflow/ref, PR head, intended
build and approved policy. Do not copy the expected identity/build/policy from the
receipt you are checking. For this recorded-CI producer:

- `headSha256` / `baseSha256`: SHA-256 of the lowercase ASCII 40-digit Git commit ID.
- `buildSha256`: the gate's game-tree digest of the intended head build.
- `policySha256`: `ci_receipt.policy_digest(BASE_SHA, checks.digest)`, where `checks`
  is `verify.read_checks(TRUSTED_BASE, SPECS, ROUTES, "base")`. The canonical hash
  includes the base commit (therefore its verifier and recording bank), captured
  checks digest, both-observer rule, required sandbox and recorded-CI profile.
- `routeSetSha256`: the canonical public route-name to route-SHA-256 mapping.

The verifier version includes its base commit, the adapter version comes from the
saved replay, and the observer version names the recorded profile and its model
stamp. The receipt's required-check IDs are canonical SHA-256 digests of
`[spec ID, route name]`; its bound findings/report contain the readable names.

Download the trusted `expectrail-report` into `evidence/report`. Preserve the
candidate capture ZIP's exact bytes as `evidence/capture.zip`; do not unpack and
repack them. For example, with independently selected run/artifact IDs:

```bash
gh run download TRUSTED_RUN --repo OWNER/NAME --name expectrail-report --dir evidence/report
gh api repos/OWNER/NAME/actions/artifacts/CAPTURE_ARTIFACT_ID/zip > evidence/capture.zip
```

Use the public artifact metadata to select the capture from the correct
run/attempt (`expectrail-ATTEMPT.zip`). A wrong download fails the digest check.
The receipt hashes every original report evidence file plus `capture.zip`.
Receipt, predicate and Sigstore proof are verification metadata added afterwards;
the attestation binds the receipt itself, avoiding a circular self-hash.

```bash
python -m expectrail.gate.ci_receipt check evidence/report/receipt.json \
  --repo OWNER/NAME \
  --signer-workflow OWNER/NAME/.github/workflows/expectrail-comment.yml \
  --source-ref refs/heads/main \
  --bundle evidence/report/receipt-attestation.sigstore.json \
  --evidence-root evidence \
  --expect-head HEAD_DIGEST --expect-build BUILD_DIGEST --expect-policy POLICY_DIGEST
```

Use the actual trusted default ref if it differs from `refs/heads/main`, including
the disposable #254 repository. Install `expectrail[trust]` and GitHub CLI first.
The checker calls `attestation.check` (which runs `gh attestation verify` with all
pins and validates its JSON again), then the existing trust-check implementation
on the same receipt bytes. It independently hashes every named artifact and names
every missing, changed, unsafe or linked file. No signed text selects a command,
model, check or approval. Receipt changes during verification refuse the check.

Exit **0** means the pinned issuer, independent expectations, freshness, full
required-check coverage, original accept decision and all supplied artifact bytes
held. Exit **1** means no clearance and names the failed conditions. Exit **2**
means nothing checked/unusable input, naming a missing receipt/`gh`/dependency,
unreadable receipt/verification output or a receipt that changes while checked. `write` returns 0 for a written receipt and 2 for refusal.
A verified attestation on partial evidence gives **no clearance**.

This establishes who attested these bytes and what the trusted gate recorded.
It does not prove a repair rate, completeness of the check set, new live vision
accuracy, an authenticated capture beyond the existing pipeline, a hosted fork
secret boundary or branch enforcement. Keep #255 open until Sean installs the
proposal and records a real receipt through `gh attestation verify`,
`attestation check` and `trust-check` with the independent pins and actual evidence.
